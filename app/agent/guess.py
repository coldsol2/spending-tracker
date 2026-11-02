"""거래 단위 추측. 가게 이름만으로는 알 수 없는 거래(페이 결제, 결제대행사, 친구 송금)를
앞뒤 거래·시각·금액·친구 정산과 사용자가 직접 고른 예시까지 보고 하나씩 추리한다."""
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from .categorize import CATEGORIES, Category

BATCH_SIZE = 30
NEARBY = timedelta(hours=2)
MAX_EXAMPLES = 40
WEEKDAYS = "월화수목금토일"

SYSTEM = f"""한국 대학생의 은행 거래내역에서, 가게 이름만으로는 용도를 알 수 없는 출금들을 하나씩 추리하라.
카카오페이·토스페이 같은 간편결제, 나이스·KCP·코페이 같은 결제대행사 이름, 친구에게 보낸 송금이 주로 해당한다.
카테고리: {", ".join(CATEGORIES)}.
(식비=식당·배달, 편의점, 술=술집·포차, 유흥=카페·PC방·만화카페·노래방·놀거리, 구독료, 교통비=택시·대중교통,
쇼핑, 생활=미용·통신·약국·생활용품, 송금=용도를 알 수 없는 사람 간 송금, 제외=지출이 아닌 이동, 기타=정말 모를 때)

각 거래(targets)에는 다음 단서가 있다.
- time(요일 포함), amount, kind(은행 거래 유형), name
- nearby: 앞뒤 2시간 안의 다른 결제와 그 카테고리. 같은 자리에서 이어진 결제면 같은 용도일 가능성이 높다
  (예: 만화카페 결제 10분 뒤 카카오페이 → 유흥, 술집 결제 직후 친구 송금 → 술).
- paid_back: 이 결제에 친구들이 보내준 정산. 여럿이 나눠 낸 결제면 식사·술·놀거리일 가능성이 높다.
- 시각과 금액 자체: 새벽 택시비 금액대, 점심 시간 1만 원 안팎, 늦은 밤 편의점 금액대 등.

examples는 사용자가 직접 고른 정답이다. 비슷한 이름·금액·시간대·요일 패턴이면 그 선택을 따른다.

거래마다 category, confidence(high: 단서가 분명함 / medium: 그럴듯함 / low: 단서가 거의 없음), reason을 답하라.
reason은 판단에 쓴 단서를 짚는 한국어 한 문장(예: "만화카페 결제 10분 뒤라 같은 자리의 간식·추가 결제로 보여요").
단서가 거의 없으면 억지로 맞히지 말고 confidence를 low로 둔다. 모든 txn_id에 하나씩 답하라."""


class Guess(BaseModel):
    txn_id: int
    category: Category
    confidence: Literal["high", "medium", "low"]
    reason: str


class GuessResult(BaseModel):
    guesses: list[Guess]


def _when(at: str) -> str:
    d = datetime.fromisoformat(at)
    return f"{at[:16]} ({WEEKDAYS[d.weekday()]})"


def _target(conn: sqlite3.Connection, t: sqlite3.Row) -> dict:
    at = datetime.fromisoformat(t["occurred_at"])
    lo, hi = (at - NEARBY).isoformat(sep=" "), (at + NEARBY).isoformat(sep=" ")
    nearby = [{"time": r["occurred_at"][11:16], "name": r["description"], "amount": r["amount"],
               "category": r["category"] or "미정"}
              for r in conn.execute(
                  "SELECT occurred_at, description, amount, category FROM transactions "
                  "WHERE direction = 'out' AND id != ? AND occurred_at >= ? AND occurred_at <= ? ORDER BY occurred_at",
                  (t["id"], lo, hi))]
    paid_back = [{"name": r["description"], "amount": r["amount"]} for r in conn.execute(
        "SELECT i.description, COALESCE(s.amount, i.amount) AS amount FROM settlements s "
        "JOIN transactions i ON i.id = s.incoming_id WHERE s.payment_id = ? AND s.status != 'rejected'", (t["id"],))]
    return {"txn_id": t["id"], "time": _when(t["occurred_at"]), "name": t["description"], "kind": t["kind"],
            "amount": t["amount"], "nearby": nearby, "paid_back": paid_back}


def examples(conn: sqlite3.Connection, hide_ids: set[int] = frozenset()) -> list[dict]:
    """사용자가 직접 고른 거래들. 가게 단위로 고른 것과 거래 하나만 고른 것을 모두 담는다.
    hide_ids는 정확도를 잴 때 정답을 숨기는 데 쓴다. 페이·사람처럼 거래마다 다른 이름은 그 거래만,
    가게는 같은 가게의 다른 거래가 곧 답이므로 이름 전체를 숨긴다."""
    rows = conn.execute(
        "SELECT t.id, t.description, t.kind, t.amount, t.occurred_at, t.category, COALESCE(m.varies, 0) AS varies "
        "FROM transactions t LEFT JOIN merchant_categories m ON m.merchant = t.description "
        "WHERE t.direction = 'out' AND t.reviewed = 1 ORDER BY t.occurred_at DESC").fetchall()
    hidden_shops = {r["description"] for r in rows if r["id"] in hide_ids and not r["varies"]}
    out, seen_shops = [], set()
    for r in rows:
        if r["id"] in hide_ids or r["description"] in hidden_shops:
            continue
        # 가게 단위로 정한 건 한 줄이면 충분하고, 거래마다 다른 이름(페이·사람)은 거래마다 예시가 된다
        if not r["varies"]:
            if r["description"] in seen_shops:
                continue
            seen_shops.add(r["description"])
        out.append({"name": r["description"], "kind": r["kind"], "amount": r["amount"],
                    "time": _when(r["occurred_at"]), "category": r["category"]})
        if len(out) >= MAX_EXAMPLES:
            break
    return out


def guess(conn: sqlite3.Connection, llm, txn_ids: list[int], hide_ids: set[int] = frozenset()) -> dict[int, dict]:
    """반환: {txn_id: {"category", "confidence", "reason"}}"""
    result: dict[int, dict] = {}
    if not txn_ids:
        return result
    ex = examples(conn, hide_ids)
    for i in range(0, len(txn_ids), BATCH_SIZE):
        batch = txn_ids[i:i + BATCH_SIZE]
        rows = conn.execute(f"SELECT * FROM transactions WHERE id IN ({','.join('?' * len(batch))})", batch).fetchall()
        payload = {"targets": [_target(conn, r) for r in rows], "examples": ex}
        out = llm.parse(SYSTEM, json.dumps(payload, ensure_ascii=False), GuessResult)
        for g in out.guesses:
            if g.txn_id in batch:
                result[g.txn_id] = {"category": g.category if g.category in CATEGORIES else "기타",
                                    "confidence": g.confidence, "reason": g.reason}
    return result


def apply(conn: sqlite3.Connection, llm, txn_ids: list[int]) -> int:
    """추측을 저장하고, low가 아니면 카테고리에도 반영한다. 사용자 확인 전이라 reviewed는 그대로 0."""
    guesses = guess(conn, llm, txn_ids)
    for tid, g in guesses.items():
        conn.execute(
            "UPDATE transactions SET ai_guess = ?, ai_confidence = ?, ai_reason = ?, "
            "category = CASE WHEN ? != 'low' THEN ? ELSE category END WHERE id = ? AND reviewed = 0",
            (g["category"], g["confidence"], g["reason"], g["confidence"], g["category"], tid))
    conn.commit()
    return len(guesses)
