"""들어온 돈의 종류(정산·용돈·알바비·환불·기타 수입)를 추리한다.
보낸 사람의 다른 입금 패턴(매달 같은 날·같은 금액), 그 사람에게 보낸 돈, 받기 전후의 결제와
'결제 ÷ 사람 수' 금액이 맞는지, 사용자가 직접 고른 예시를 단서로 쓴다.
결과는 guess.py와 같은 모양 {txn_id: {"category", "confidence", "reason"}} (category = 들어온 돈 종류)."""
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from .. import settle
from .guess import _when

INCOME = [
    {"name": "정산", "emoji": "🤝", "description": "친구가 같이 쓴 돈의 내 몫을 보내줌"},
    {"name": "용돈", "emoji": "💌", "description": "가족 등에게 받은 용돈"},
    {"name": "알바비", "emoji": "💼", "description": "알바·월급·근로 소득"},
    {"name": "환불", "emoji": "↩️", "description": "결제 취소·환불"},
    {"name": "기타 수입", "emoji": "📥", "description": "중고거래, 빌려준 돈, 이자 등"},
]
NAMES = [c["name"] for c in INCOME]
Label = Literal["정산", "용돈", "알바비", "환불", "기타 수입"]
BATCH_SIZE = 30
PAY_BEFORE, PAY_AFTER = timedelta(days=7), timedelta(days=1)
MAX_HISTORY, MAX_PAYMENTS, MAX_EXAMPLES = 12, 6, 40

SYSTEM = """한국 대학생의 은행 계좌에 들어온 돈이 무슨 돈인지 하나씩 추리하라.
종류:
{labels}

각 입금(targets)의 단서:
- time(요일 포함), name(보낸 사람·회사), kind(은행 거래 유형), amount
- same_sender_in: 같은 사람이 보낸 다른 입금들. 매달 비슷한 날 비슷한 금액이면 용돈·알바비일 가능성이 높다.
  보낸 이름이 회사·가게면 알바비, 가족처럼 보이는 사람이 매달 보내면 용돈.
- sent_to_sender: 사용자가 그 사람에게 보낸 돈. 친구 사이에 오가는 돈이면 정산이나 기타 수입일 수 있다.
- payments_near: 받기 7일 전 ~ 1일 뒤 사용자의 결제. split이 있으면 '결제 ÷ 사람 수'가 입금액과 맞는다는 뜻으로,
  정산일 가능성이 높다. 결제 직후 몇 시간 안에 여러 사람이 비슷한 금액을 보내면 정산.
- 딱 떨어지는 큰 금액(5만·10만 원)이 근처 결제와 안 맞으면 정산보다 용돈·기타 수입 쪽이다.
- 이자·캐시백·중고거래·빌려준 돈 돌려받기는 기타 수입.

examples는 사용자가 직접 고른 정답이다. 같은 사람·비슷한 금액·시기 패턴이면 그 선택을 따른다.

입금마다 category(위 종류 중 하나), confidence(high: 단서가 분명함 / medium: 그럴듯함 / low: 단서가 거의 없음),
reason(판단에 쓴 단서를 짚는 한국어 한 문장)을 답하라. 모든 txn_id에 하나씩 답하라."""


class IncomeGuess(BaseModel):
    txn_id: int
    category: Label
    confidence: Literal["high", "medium", "low"]
    reason: str


class IncomeResult(BaseModel):
    guesses: list[IncomeGuess]


def _split(amount: int, payment: int) -> int | None:
    """입금이 이 결제를 몇 명이 나눈 몫으로 보이는지 (2~8명, 10% 안쪽). 아니면 None."""
    for n in range(2, 9):
        if abs(payment / n - amount) <= amount * 0.1:
            return n
    return None


def _target(conn: sqlite3.Connection, t: sqlite3.Row) -> dict:
    at = datetime.fromisoformat(t["occurred_at"])
    history = [{"time": _when(r["occurred_at"]), "amount": r["amount"]} for r in conn.execute(
        "SELECT occurred_at, amount FROM transactions WHERE direction = 'in' AND description = ? AND id != ? "
        "ORDER BY occurred_at DESC LIMIT ?", (t["description"], t["id"], MAX_HISTORY))]
    sent = [{"time": _when(r["occurred_at"]), "amount": r["amount"]} for r in conn.execute(
        "SELECT occurred_at, amount FROM transactions WHERE direction = 'out' AND description = ? "
        "ORDER BY occurred_at DESC LIMIT ?", (t["description"], MAX_HISTORY))]
    pays = conn.execute(
        "SELECT occurred_at, description, amount FROM transactions WHERE direction = 'out' "
        "AND occurred_at >= ? AND occurred_at <= ?",
        ((at - PAY_BEFORE).isoformat(sep=" "), (at + PAY_AFTER).isoformat(sep=" "))).fetchall()
    pays = sorted(pays, key=lambda r: abs(datetime.fromisoformat(r["occurred_at"]) - at))[:MAX_PAYMENTS]
    payments = []
    for r in sorted(pays, key=lambda r: r["occurred_at"]):
        p = {"time": _when(r["occurred_at"]), "name": r["description"], "amount": r["amount"]}
        if n := _split(t["amount"], r["amount"]):
            p["split"] = f"{r['amount']:,}원 ÷ {n}명 ≈ 입금액"
        payments.append(p)
    return {"txn_id": t["id"], "time": _when(t["occurred_at"]), "name": t["description"], "kind": t["kind"],
            "amount": t["amount"], "same_sender_in": history, "sent_to_sender": sent, "payments_near": payments}


def examples(conn: sqlite3.Connection, hide_ids: set[int] = frozenset()) -> list[dict]:
    """사용자가 고른 들어온 돈 종류. hide_ids는 정확도를 잴 때 정답을 숨기는 데 쓴다."""
    rows = conn.execute(
        "SELECT t.id, t.description, t.kind, t.amount, t.occurred_at, l.label FROM income_labels l "
        "JOIN transactions t ON t.id = l.txn_id ORDER BY t.occurred_at DESC").fetchall()
    return [{"name": r["description"], "kind": r["kind"], "amount": r["amount"], "time": _when(r["occurred_at"]),
             "category": r["label"]} for r in rows if r["id"] not in hide_ids][:MAX_EXAMPLES]


def _rule(t: sqlite3.Row, settled: set[int]) -> dict | None:
    """AI 없이 확실한 것: 결제 취소는 환불, 사용자가 정산으로 확정한 입금은 정산."""
    if settle.is_refund(t["kind"], t["description"]):
        return {"category": "환불", "confidence": "high", "reason": "결제 취소 거래예요."}
    if t["id"] in settled:
        return {"category": "정산", "confidence": "high", "reason": "정산으로 확정한 입금이에요."}
    return None


def classify(conn: sqlite3.Connection, llm, txn_ids: list[int], hide_ids: set[int] = frozenset()) -> dict[int, dict]:
    """반환: {txn_id: {"category", "confidence", "reason"}}. llm이 없으면 규칙으로 정해지는 것만."""
    result: dict[int, dict] = {}
    if not txn_ids:
        return result
    settled = {r[0] for r in conn.execute("SELECT incoming_id FROM settlements WHERE status = 'confirmed'")}
    rows = conn.execute(f"SELECT * FROM transactions WHERE direction = 'in' AND id IN "
                        f"({','.join('?' * len(txn_ids))}) ORDER BY occurred_at", txn_ids).fetchall()
    ask = []
    for r in rows:
        if rule := _rule(r, settled):
            result[r["id"]] = rule
        else:
            ask.append(r)
    if llm is None or not ask:
        return result
    ex = examples(conn, hide_ids | {r["id"] for r in ask})
    system = SYSTEM.format(labels="\n".join(f"- {c['name']}: {c['description']}" for c in INCOME))
    for i in range(0, len(ask), BATCH_SIZE):
        batch = ask[i:i + BATCH_SIZE]
        payload = {"targets": [_target(conn, r) for r in batch], "examples": ex}
        out = llm.parse(system, json.dumps(payload, ensure_ascii=False), IncomeResult)
        ids = {r["id"] for r in batch}
        for g in out.guesses:
            if g.txn_id in ids:
                result[g.txn_id] = {"category": g.category, "confidence": g.confidence, "reason": g.reason}
    return result


def apply(conn: sqlite3.Connection, llm, txn_ids: list[int]) -> int:
    """추측을 들어온 돈의 ai_guess 열에 저장한다 (나간 돈의 카테고리 추측과 같은 열, 값은 들어온 돈 종류)."""
    guesses = classify(conn, llm, txn_ids)
    for tid, g in guesses.items():
        conn.execute("UPDATE transactions SET ai_guess = ?, ai_confidence = ?, ai_reason = ? WHERE id = ?",
                     (g["category"], g["confidence"], g["reason"], tid))
    conn.commit()
    return len(guesses)
