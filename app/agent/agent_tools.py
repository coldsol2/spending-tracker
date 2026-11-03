"""Console 에이전트(Managed Agents)가 부르는 거래 조회 도구. 앱이 직접 DB에서 답한다.

정확도를 잴 때는 정답(사용자가 고른 카테고리)을 숨겨야 하므로, hide_ids에 든 거래와
같은 가게(거래마다 다른 이름이 아닌 것)의 카테고리는 '미정'으로 가린다.
추측 대상 거래 자체의 카테고리도 늘 가린다(지금 값이 곧 AI의 이전 추측이라).
"""
import json
import sqlite3
from datetime import datetime, timedelta

from .. import categories as cats
from . import guess

MAX_ROWS = 50
HIDDEN = "미정"


def definitions(names: list[str]) -> list[dict]:
    """세션 생성 때 넘기는 사용자 정의 도구 목록 (Managed Agents custom tool 형식)."""
    date = {"type": "string", "description": "YYYY-MM-DD"}
    return [
        {"type": "custom", "name": "find_transactions",
         "description": "거래를 찾는다. 이름 일부, 기간, 방향으로 거를 수 있다. 같은 가게·같은 친구의 다른 거래나 "
                        "같은 요일·시간대 패턴을 볼 때 쓴다. 최신순, 최대 50건.",
         "input_schema": {"type": "object", "properties": {
             "name_contains": {"type": "string", "description": "가게·사람 이름 일부"},
             "start_date": date, "end_date": date,
             "direction": {"type": "string", "enum": ["out", "in"], "description": "out=나간 돈, in=들어온 돈"},
             "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS}}}},
        {"type": "custom", "name": "nearby_transactions",
         "description": "어떤 거래 앞뒤 몇 시간 안의 다른 거래(나간 돈·들어온 돈 모두)와 그 카테고리.",
         "input_schema": {"type": "object", "properties": {
             "txn_id": {"type": "integer"},
             "hours": {"type": "integer", "minimum": 1, "maximum": 24, "description": "앞뒤로 볼 시간 (기본 3)"}},
             "required": ["txn_id"]}},
        {"type": "custom", "name": "settlement_info",
         "description": "결제에 친구들이 보내준 정산, 또는 들어온 돈이 연결된 결제. 여럿이 나눈 결제인지 볼 때 쓴다.",
         "input_schema": {"type": "object", "properties": {"txn_id": {"type": "integer"}}, "required": ["txn_id"]}},
        {"type": "custom", "name": "user_choices",
         "description": "사용자가 직접 고른 카테고리(정답 예시). 이름 일부로 거를 수 있다. 사용자의 분류 습관을 볼 때 쓴다.",
         "input_schema": {"type": "object", "properties": {"name_contains": {"type": "string"}}}},
        {"type": "custom", "name": "submit_guesses",
         "description": "최종 답을 제출한다. 맡은 거래 전부를 한 번에 낸다. 이 도구를 부른 뒤 일을 마친다.",
         "input_schema": {"type": "object", "properties": {"guesses": {"type": "array", "items": {
             "type": "object", "properties": {
                 "txn_id": {"type": "integer"},
                 "category": {"type": "string", "enum": names},
                 "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                 "reason": {"type": "string", "description": "판단에 쓴 단서를 짚는 한국어 한 문장"}},
             "required": ["txn_id", "category", "confidence", "reason"]}}},
             "required": ["guesses"]}},
    ]


class Toolbox:
    """도구 호출 한 번에 답을 돌려준다. 제출된 답은 submitted에 모인다."""

    def __init__(self, conn: sqlite3.Connection, targets: list[int], hide_ids: set[int] = frozenset()):
        self.conn = conn
        self.targets = set(targets)
        self.names = cats.names(conn)
        self.hide_ids = set(hide_ids)
        self.hidden_ids = set(targets) | self.hide_ids
        self.hidden_shops: set[str] = set()
        if hide_ids:
            # 가게는 같은 가게의 다른 거래 카테고리가 곧 답이라 이름째 가린다
            self.hidden_shops = {r[0] for r in conn.execute(
                f"SELECT DISTINCT t.description FROM transactions t LEFT JOIN merchant_categories m "
                f"ON m.merchant = t.description WHERE t.id IN ({','.join('?' * len(hide_ids))}) "
                f"AND COALESCE(m.varies, 0) = 0", list(hide_ids))}
        self.submitted: dict[int, dict] = {}
        self.calls = 0

    # ---- 공통 ----
    def _row(self, r: sqlite3.Row) -> dict:
        hidden = r["id"] in self.hidden_ids or r["description"] in self.hidden_shops
        return {"id": r["id"], "time": guess._when(r["occurred_at"]), "name": r["description"], "kind": r["kind"],
                "amount": r["amount"], "direction": r["direction"],
                "category": HIDDEN if hidden or r["direction"] == "in" else (r["category"] or HIDDEN),
                "user_chosen": bool(r["reviewed"]) and not hidden}

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """(결과 JSON 문자열, 오류 여부)"""
        self.calls += 1
        try:
            out = getattr(self, f"_{name}")(**args)
        except (AttributeError, TypeError):
            return json.dumps({"error": f"모르는 도구이거나 입력이 잘못됐어요: {name}"}, ensure_ascii=False), True
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False), True
        return json.dumps(out, ensure_ascii=False), False

    # ---- 도구 ----
    def _find_transactions(self, name_contains: str = "", start_date: str = "", end_date: str = "",
                           direction: str = "", limit: int = 20) -> list[dict]:
        sql, params = "SELECT * FROM transactions WHERE 1=1", []
        if name_contains:
            sql += " AND description LIKE ?"
            params.append(f"%{name_contains}%")
        if start_date:
            sql += " AND occurred_at >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND occurred_at < ?"
            params.append((datetime.fromisoformat(end_date) + timedelta(days=1)).date().isoformat())
        if direction in ("out", "in"):
            sql += " AND direction = ?"
            params.append(direction)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), MAX_ROWS)))
        return [self._row(r) for r in self.conn.execute(sql, params)]

    def _nearby_transactions(self, txn_id: int, hours: int = 3) -> list[dict]:
        row = self.conn.execute("SELECT occurred_at FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        if row is None:
            raise ValueError(f"거래 {txn_id}를 찾을 수 없어요.")
        at, span = datetime.fromisoformat(row["occurred_at"]), timedelta(hours=max(1, min(int(hours), 24)))
        rows = self.conn.execute(
            "SELECT * FROM transactions WHERE id != ? AND occurred_at >= ? AND occurred_at <= ? ORDER BY occurred_at",
            (txn_id, (at - span).isoformat(sep=" "), (at + span).isoformat(sep=" ")))
        return [self._row(r) for r in rows]

    def _settlement_info(self, txn_id: int) -> dict:
        paid_back = [{"name": r["description"], "amount": r["amount"], "status": r["status"]} for r in self.conn.execute(
            "SELECT i.description, COALESCE(s.amount, i.amount) AS amount, s.status FROM settlements s "
            "JOIN transactions i ON i.id = s.incoming_id WHERE s.payment_id = ? AND s.status != 'rejected'", (txn_id,))]
        linked_payments = [{"name": r["description"], "amount": r["amount"], "time": guess._when(r["occurred_at"])}
                           for r in self.conn.execute(
            "SELECT p.description, p.amount, p.occurred_at FROM settlements s JOIN transactions p ON p.id = s.payment_id "
            "WHERE s.incoming_id = ? AND s.status != 'rejected'", (txn_id,))]
        return {"paid_back_by_friends": paid_back, "this_money_settles": linked_payments}

    def _user_choices(self, name_contains: str = "") -> list[dict]:
        out = [e for e in guess.examples(self.conn, self.hide_ids | self.targets)
               if not name_contains or name_contains in e["name"]]
        return out[:MAX_ROWS]

    def _submit_guesses(self, guesses: list[dict]) -> dict:
        accepted = 0
        for g in guesses:
            tid = int(g.get("txn_id", -1))
            if tid not in self.targets:
                continue
            category = g.get("category") if g.get("category") in self.names else cats.FALLBACK
            confidence = g.get("confidence") if g.get("confidence") in ("high", "medium", "low") else "low"
            self.submitted[tid] = {"category": category, "confidence": confidence, "reason": str(g.get("reason", ""))}
            accepted += 1
        missing = sorted(self.targets - set(self.submitted))
        return {"accepted": accepted, "missing_txn_ids": missing,
                "message": "모두 받았어요. 이제 마치면 돼요." if not missing else "빠진 거래도 마저 제출해 주세요."}
