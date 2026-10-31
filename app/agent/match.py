"""더치페이 정산 매칭 제안. 규칙이 뽑은 후보 안에서 Claude가 어느 결제의 정산인지 고른다."""
import json

from pydantic import BaseModel

SYSTEM = """사용자는 친구들과 함께 쓴 돈을 자기 카드로 한 번에 결제하고, 친구들이 나중에 자기 몫을 송금해 준다.
입력은 JSON 배열이다. 각 원소는 사용자 계좌로 들어온 입금 하나(incoming)와,
그 입금 직전 7일 안에 있었던 사용자의 결제 후보들(payments)이다.

각 입금이 어느 결제에 대한 더치페이 정산인지 판단하라.
- 같은 시점에 비슷한 금액이 여러 사람에게서 들어오고, 그 합이 결제액보다 작으면 정산일 가능성이 높다.
- 결제액을 사람 수로 나눈 금액과 입금액이 비슷한지, 결제와 입금 사이 시간이 가까운지 본다.
- 여러 사람이 함께 쓰기 어려운 결제(구독, 교통카드 충전, 공과금 등)는 정산 대상이 아닐 가능성이 높다.
- 용돈·중고거래 대금·빌려준 돈을 받은 것처럼 보이면 정산이 아니다.
정산이 아니라고 보면 payment_id를 null로 둔다.
모든 입금에 대해 하나씩 답하고, reason에는 판단 근거를 한국어 한 문장으로 적어라."""


class Match(BaseModel):
    incoming_id: int
    payment_id: int | None
    reason: str


class MatchResult(BaseModel):
    matches: list[Match]


def _payload(candidates: list[dict]) -> list[dict]:
    def tx(t):
        return {"id": t["id"], "time": t["occurred_at"].isoformat(timespec="minutes"),
                "description": t["description"], "amount": t["amount"]}
    return [{"incoming": tx(c["incoming"]), "payments": [tx(p) for p in c["payments"]]} for c in candidates]


def propose(llm, candidates: list[dict]) -> list[dict]:
    """반환: [{"incoming_id", "payment_id", "reason"}] — 후보에 없던 결제를 고른 답은 버린다."""
    if not candidates:
        return []
    allowed = {c["incoming"]["id"]: {p["id"] for p in c["payments"]} for c in candidates}
    out = llm.parse(SYSTEM, json.dumps(_payload(candidates), ensure_ascii=False), MatchResult)
    result = []
    for m in out.matches:
        if m.incoming_id not in allowed:
            continue
        if m.payment_id is not None and m.payment_id not in allowed[m.incoming_id]:
            continue
        result.append({"incoming_id": m.incoming_id, "payment_id": m.payment_id, "reason": m.reason})
    return result
