"""더치페이 정산 매칭 제안. 규칙이 뽑은 후보 안에서 Claude가 어느 결제(들)의 정산인지 고른다."""
import json

from pydantic import BaseModel

SYSTEM = """사용자는 친구들과 함께 쓴 돈을 자기 카드로 한 번에 결제하고, 친구들이 나중에 자기 몫을 송금해 준다.
입력은 JSON 배열이다. 각 원소는 사용자 계좌로 들어온 입금 하나(incoming)와,
그 입금 무렵(결제 2시간 전 ~ 결제 7일 후)에 있었던 사용자의 결제 후보들(payments)이다.

각 입금이 어느 결제에 대한 더치페이 정산인지 판단하라.
- 같은 시점에 비슷한 금액이 여러 사람에게서 들어오면 정산일 가능성이 높다.
  결제액(또는 여러 결제의 합)을 사람 수로 나눈 금액과 입금액이 비슷한지, 시간이 가까운지 본다.
- 한 입금이 같은 자리에서 이어진 여러 결제의 몫일 수 있다(예: 1차 식당 + 2차 카페, 배달 + 편의점).
  입금액이 결제 하나보다 크거나, 여러 결제의 합을 나눈 값과 맞으면 그 결제들을 모두 고른다.
- 친구가 결제 직전에 자기 몫을 미리 보내기도 한다. 결제보다 조금 먼저 들어온 입금도 정산일 수 있다.
- 여러 사람이 함께 쓰기 어려운 결제(구독, 교통카드 충전, 공과금, 미용실 등)는 정산 대상이 아닐 가능성이 높다.
- 용돈·알바비·중고거래 대금·빌려준 돈을 받은 것처럼 보이면(딱 떨어지는 큰 금액, 근처에 맞는 결제 없음) 정산이 아니다.
payment_ids에는 정산 대상 결제 id를 모두 적고, 정산이 아니면 빈 배열로 둔다.
모든 입금에 대해 하나씩 답하고, reason에는 판단 근거(어떤 금액을 몇 명이 나눴는지 등)를 한국어 한 문장으로 적어라."""


class Match(BaseModel):
    incoming_id: int
    payment_ids: list[int]
    reason: str


class MatchResult(BaseModel):
    matches: list[Match]


def _payload(candidates: list[dict]) -> list[dict]:
    def tx(t):
        return {"id": t["id"], "time": t["occurred_at"].isoformat(timespec="minutes"),
                "description": t["description"], "amount": t["amount"]}
    return [{"incoming": tx(c["incoming"]), "payments": [tx(p) for p in c["payments"]]} for c in candidates]


def propose(llm, candidates: list[dict]) -> list[dict]:
    """반환: 정산이라고 본 입금만 [{"incoming_id", "payment_ids", "reason"}].
    후보에 없던 결제는 버리고, 남은 결제가 없으면 그 답을 버린다."""
    if not candidates:
        return []
    allowed = {c["incoming"]["id"]: {p["id"] for p in c["payments"]} for c in candidates}
    out = llm.parse(SYSTEM, json.dumps(_payload(candidates), ensure_ascii=False), MatchResult)
    result = []
    for m in out.matches:
        if m.incoming_id not in allowed:
            continue
        ids = [p for p in dict.fromkeys(m.payment_ids) if p in allowed[m.incoming_id]]
        if ids:
            result.append({"incoming_id": m.incoming_id, "payment_ids": ids, "reason": m.reason})
    return result
