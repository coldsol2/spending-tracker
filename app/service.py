"""DB와 순수 로직, AI 모듈을 엮는 앱 동작들."""
import sqlite3
from datetime import date, datetime, timedelta

from . import settle, stats
from .agent import categorize as cat_agent
from .agent import extract, guess, match
from .agent.client import LLMError, column_mapper
from .parser import parse_file

NO_KEY_WARNING = "ANTHROPIC_API_KEY가 없어서 AI 분류와 정산 제안을 건너뛰었어요."


class ConflictError(Exception):
    pass


def _tx(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["occurred_at"] = datetime.fromisoformat(d["occurred_at"])
    return d


def _tx_json(t: dict) -> dict:
    return {**t, "occurred_at": t["occurred_at"].isoformat(sep=" ", timespec="minutes")}


# ---- 업로드 ----

def import_file(conn: sqlite3.Connection, filename: str, data: bytes, llm, password: str | None = None) -> dict:
    warnings: list[str] = []
    mapper = column_mapper(llm) if llm else None
    try:
        txns = parse_file(filename, data, mapper, password, extract.extractor(llm) if llm else None)
    except LLMError as e:
        raise ValueError(f"AI가 PDF를 읽지 못했어요. ({e})") from e

    for name in {t.description.strip() for t in txns if t.owner}:
        conn.execute("INSERT OR IGNORE INTO account_owners(name) VALUES (?)", (name,))
    owners = owner_names(conn)
    internal, kept = [], []
    for t in txns:
        mine = settle.is_internal(t.description) or t.description.strip() in owners
        (internal if mine else kept).append(t)
    txns = kept
    if internal:
        warnings.append(f"내 계좌끼리 오간 돈(비상금·환전·내 이름 계좌) {len(internal)}건은 수입·지출에서 뺐어요.")

    added = 0
    for t in txns:
        cur = conn.execute(
            "INSERT OR IGNORE INTO transactions(occurred_at, description, amount, direction, balance, source_hash, kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (t.occurred_at.isoformat(sep=" "), t.description, t.amount, t.direction, t.balance, t.source_hash,
             t.kind or None),
        )
        added += cur.rowcount
        if cur.rowcount == 0 and t.kind:
            # 예전 버전으로 올린 거래에는 거래 유형이 없으니 채워 넣는다
            conn.execute("UPDATE transactions SET kind = ? WHERE source_hash = ? AND kind IS NULL",
                         (t.kind, t.source_hash))
    conn.commit()
    link_refunds(conn, [t for t in txns if t.direction == "in" and settle.is_refund(t.kind, t.description)])

    if llm is None:
        warnings.append(NO_KEY_WARNING)
    try:
        categorize_pending(conn, llm)
    except LLMError as e:
        warnings.append(f"카테고리 분류 실패: {e}")

    proposals = 0
    if llm is not None:
        try:
            proposals = propose_settlements(conn, llm)
        except LLMError as e:
            warnings.append(f"정산 제안 실패: {e}")
        try:
            guess_pending(conn, llm)  # 정산 제안 다음에: 친구 정산도 추측 단서가 된다
        except LLMError as e:
            warnings.append(f"거래별 추측 실패: {e}")

    return {"added": added, "duplicates": len(txns) - added, "proposals": proposals,
            "warning": " ".join(warnings) or None}


REFUND_REASON = "결제 취소"


def owner_names(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM account_owners")}


def link_refunds(conn: sqlite3.Connection, refunds: list) -> None:
    """결제 취소 입금을 같은 가맹점의 직전 결제에 자동으로 확정 연결한다.
    결제 하나에는 취소 하나만 붙인다 (택시 가승인처럼 결제·취소가 여러 번 반복되는 경우)."""
    for t in sorted(refunds, key=lambda t: t.occurred_at):
        inc = conn.execute("SELECT id FROM transactions WHERE source_hash = ?", (t.source_hash,)).fetchone()
        if inc is None or conn.execute("SELECT 1 FROM settlements WHERE incoming_id = ?", (inc["id"],)).fetchone():
            continue
        start = t.occurred_at - timedelta(days=settle.REFUND_WINDOW_DAYS)
        pay = conn.execute(
            "SELECT id FROM transactions WHERE direction = 'out' AND description = ? AND amount >= ? "
            "AND occurred_at BETWEEN ? AND ? AND id NOT IN "
            "(SELECT payment_id FROM settlements WHERE status = 'confirmed' AND reason = ?) "
            "ORDER BY occurred_at DESC LIMIT 1",
            (t.description, t.amount, start.isoformat(sep=" "), t.occurred_at.isoformat(sep=" "), REFUND_REASON),
        ).fetchone()
        if pay:
            conn.execute("INSERT INTO settlements(payment_id, incoming_id, status, reason) VALUES (?, ?, 'confirmed', ?)",
                         (pay["id"], inc["id"], REFUND_REASON))
    conn.commit()


def categorize_pending(conn: sqlite3.Connection, llm) -> None:
    """카테고리가 없는 출금을 분류한다. 실패하거나 키가 없으면 비워 두고 화면에는 '기타'로 보인다."""
    merchants = [r["description"] for r in conn.execute(
        "SELECT DISTINCT description FROM transactions WHERE direction = 'out' AND category IS NULL")]
    for merchant, category in cat_agent.categorize(conn, llm, merchants).items():
        conn.execute("UPDATE transactions SET category = ? WHERE description = ? AND direction = 'out' "
                     "AND category IS NULL", (category, merchant))
    conn.commit()


def propose_settlements(conn: sqlite3.Connection, llm) -> int:
    """아직 정산 판단을 받은 적 없는 입금에 대해 Claude의 매칭 제안을 pending으로 저장한다.
    후보 결제에서 송금·제외 카테고리와 이미 취소된 결제는 뺀다."""
    payments = [_tx(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE direction = 'out' AND COALESCE(category, '') NOT IN ('송금', ?) "
        "AND id NOT IN (SELECT payment_id FROM settlements WHERE status = 'confirmed' AND reason = ?)",
        (cat_agent.EXCLUDED, REFUND_REASON))]
    incomings = [_tx(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE direction = 'in' "
        "AND id NOT IN (SELECT incoming_id FROM settlements)")]
    proposals = match.propose(llm, settle.find_candidates(payments, incomings))
    for p in proposals:
        _insert_group(conn, p["incoming_id"], p["payment_ids"], "pending", p["reason"])
    conn.commit()
    return len(proposals)


def _insert_group(conn, incoming_id: int, payment_ids: list[int], status: str, reason: str) -> int:
    """입금 하나를 결제 여러 개에 나눠 연결한다. 결제가 하나면 입금 전액(amount NULL)."""
    amounts = {r["id"]: r["amount"] for r in conn.execute(
        f"SELECT id, amount FROM transactions WHERE id IN ({','.join('?' * len(payment_ids))})", payment_ids)}
    incoming = conn.execute("SELECT amount FROM transactions WHERE id = ?", (incoming_id,)).fetchone()["amount"]
    shares = settle.allocate(incoming, [amounts[p] for p in payment_ids]) if len(payment_ids) > 1 else [None]
    group_id = None
    for payment_id, share in zip(payment_ids, shares):
        cur = conn.execute(
            "INSERT INTO settlements(payment_id, incoming_id, status, reason, amount, group_id) VALUES (?, ?, ?, ?, ?, ?)",
            (payment_id, incoming_id, status, reason, share, group_id))
        if group_id is None:
            group_id = cur.lastrowid
            conn.execute("UPDATE settlements SET group_id = ? WHERE id = ?", (group_id, group_id))
    return group_id


# ---- 집계 ----

def _settled(conn, status: str, payment_ids: list[int]) -> list[tuple[int, int]]:
    """(결제 id, 그 결제에 돌아온 금액). 여러 결제로 나눈 입금은 나눠 준 금액만 센다."""
    if not payment_ids:
        return []
    marks = ",".join("?" * len(payment_ids))
    rows = conn.execute(
        f"SELECT s.payment_id, COALESCE(s.amount, i.amount) AS amount FROM settlements s "
        f"JOIN transactions i ON i.id = s.incoming_id WHERE s.status = ? AND s.payment_id IN ({marks})",
        (status, *payment_ids))
    return [(r["payment_id"], r["amount"]) for r in rows]


def _days(start: date, end: date) -> tuple[str, str]:
    """start~end(포함) 기간을 occurred_at 문자열 범위로. date(occurred_at)로 감싸지 않아야 인덱스를 쓴다."""
    return start.isoformat(), (end + timedelta(days=1)).isoformat()


def in_period(col: str = "occurred_at") -> str:
    return f"{col} >= ? AND {col} < ?"


def period_summary(conn: sqlite3.Connection, start: date, end: date, top_n: int = 10) -> dict:
    payments = [_tx(r) for r in conn.execute(
        f"SELECT * FROM transactions WHERE direction = 'out' AND {in_period()} AND COALESCE(category, '') != ?",
        (*_days(start, end), cat_agent.EXCLUDED))]
    ids = [p["id"] for p in payments]
    s = stats.summarize(payments, _settled(conn, "confirmed", ids), _settled(conn, "pending", ids), start, end)
    net = s.pop("net")

    income = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE direction = 'in' AND {in_period()} "
        "AND id NOT IN (SELECT incoming_id FROM settlements WHERE status = 'confirmed')",
        _days(start, end)).fetchone()[0]

    top = sorted(payments, key=lambda p: -net[p["id"]])[:top_n]
    s["income"] = income
    s["top"] = [{"date": p["occurred_at"].date().isoformat(), "description": p["description"],
                 "category": p["category"] or stats.DEFAULT_CATEGORY, "amount": p["amount"],
                 "net": net[p["id"]]} for p in top if net[p["id"]] > 0]
    return s


def month_range(month: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{month}-01")
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


# ---- 거래 ----

# 사용자가 아직 정하지 않았고, AI 분류를 믿기 어려운 출금: 송금·기타, AI가 확신하지 못한 것,
# 사람·페이처럼 거래마다 용도가 다른 이름
NEEDS_REVIEW = (
    "t.direction = 'out' AND t.reviewed = 0 AND (t.category IS NULL OR t.category IN ('송금', '기타') "
    "OR COALESCE(m.varies, 0) = 1 OR COALESCE(m.confident, 1) = 0)"
)
TXN_SELECT = (
    "SELECT t.*, COALESCE(m.varies, 0) AS varies, "
    f"CASE WHEN {NEEDS_REVIEW} THEN 1 ELSE 0 END AS needs_review, "
    # 줄마다 정산 표를 뒤지지 않도록 확정된 입금 목록을 한 번만 만든다
    "CASE WHEN t.id IN (SELECT incoming_id FROM settlements WHERE status = 'confirmed') "
    "THEN 'confirmed' END AS settled "
    "FROM transactions t LEFT JOIN merchant_categories m ON m.merchant = t.description "
)


def list_transactions(conn: sqlite3.Connection, month: str) -> list[dict]:
    rows = conn.execute(TXN_SELECT + f"WHERE {in_period('t.occurred_at')} ORDER BY t.occurred_at DESC",
                        _days(*month_range(month)))
    return [_tx_json(_tx(r)) for r in rows]


def list_review(conn: sqlite3.Connection, limit: int = 300) -> list[dict]:
    rows = conn.execute(TXN_SELECT + f"WHERE {NEEDS_REVIEW} ORDER BY t.occurred_at DESC LIMIT ?", (limit,))
    return [_tx_json(_tx(r)) for r in rows]


def set_category(conn: sqlite3.Connection, txn_id: int, category: str, scope: str | None = None) -> dict:
    """scope='one'이면 이 거래만, 'merchant'면 같은 이름의 모든 거래와 앞으로 올라올 거래에 적용한다.
    정하지 않으면 사람·페이처럼 거래마다 용도가 다른 이름은 'one', 가게는 'merchant'."""
    if category not in cat_agent.CATEGORIES:
        raise ValueError(f"알 수 없는 카테고리: {category}")
    if scope not in (None, "one", "merchant"):
        raise ValueError(f"알 수 없는 적용 범위: {scope}")
    row = conn.execute(
        "SELECT t.description, COALESCE(m.varies, 0) AS varies FROM transactions t "
        "LEFT JOIN merchant_categories m ON m.merchant = t.description WHERE t.id = ? AND t.direction = 'out'",
        (txn_id,)).fetchone()
    if row is None:
        raise LookupError("출금 거래를 찾을 수 없어요.")
    scope = scope or ("one" if row["varies"] else "merchant")
    if scope == "one":
        cur = conn.execute("UPDATE transactions SET category = ?, reviewed = 1 WHERE id = ?", (category, txn_id))
    else:
        cur = conn.execute("UPDATE transactions SET category = ?, reviewed = 1 WHERE description = ? "
                           "AND direction = 'out'", (category, row["description"]))
        cat_agent.remember(conn, row["description"], category, source="user")
    conn.commit()
    return {"scope": scope, "updated": cur.rowcount}


def recategorize(conn: sqlite3.Connection, llm) -> int:
    """AI가 정한 분류를 지우고 새 기준으로 다시 분류한다. 사용자가 직접 정한 건 그대로 둔다."""
    if llm is None:
        raise LLMError(NO_KEY_WARNING)
    conn.execute("DELETE FROM merchant_categories WHERE source = 'ai'")
    cur = conn.execute(
        "UPDATE transactions SET category = NULL, ai_guess = NULL, ai_confidence = NULL, ai_reason = NULL "
        "WHERE direction = 'out' AND reviewed = 0 "
        "AND description NOT IN (SELECT merchant FROM merchant_categories WHERE source = 'user')")
    conn.commit()
    categorize_pending(conn, llm)
    guess_pending(conn, llm)
    return cur.rowcount


def guess_pending(conn: sqlite3.Connection, llm) -> int:
    """가게 이름만으로 정하지 못한 거래(분류 확인 목록)를 거래 하나씩 앞뒤 상황까지 보고 추측한다."""
    ids = [r["id"] for r in conn.execute(
        "SELECT t.id FROM transactions t LEFT JOIN merchant_categories m ON m.merchant = t.description "
        f"WHERE {NEEDS_REVIEW} AND t.ai_guess IS NULL")]
    return guess.apply(conn, llm, ids)


# ---- 정산 ----

# 정산은 묶음(group) 단위로 보여주고 확정·거절한다. 예전 기록은 group_id가 없으니 자기 id가 묶음 id다.
GROUP = "COALESCE(s.group_id, s.id)"


def list_settlements(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        f"SELECT {GROUP} AS gid, s.status, s.reason, COALESCE(s.amount, i.amount) AS share, "
        "p.id AS p_id, p.occurred_at AS p_at, p.description AS p_desc, p.amount AS p_amount, "
        "i.id AS i_id, i.occurred_at AS i_at, i.description AS i_desc, i.amount AS i_amount "
        "FROM settlements s JOIN transactions p ON p.id = s.payment_id JOIN transactions i ON i.id = s.incoming_id "
        "WHERE s.status != 'rejected' ORDER BY i.occurred_at DESC, p.occurred_at")
    groups: dict[int, dict] = {}
    for r in rows:
        g = groups.setdefault(r["gid"], {
            "id": r["gid"], "status": r["status"], "reason": r["reason"], "payments": [],
            "incoming": {"id": r["i_id"], "occurred_at": r["i_at"][:16], "description": r["i_desc"], "amount": r["i_amount"]},
        })
        g["payments"].append({"id": r["p_id"], "occurred_at": r["p_at"][:16], "description": r["p_desc"],
                              "amount": r["p_amount"], "share": r["share"]})
    out = {"pending": [], "confirmed": []}
    for g in groups.values():
        g["payment"] = g["payments"][0]
        out[g.pop("status")].append(g)
    return out


def unlinked_incomings(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE direction = 'in' AND id NOT IN "
        "(SELECT incoming_id FROM settlements WHERE status IN ('pending', 'confirmed')) "
        "ORDER BY occurred_at DESC LIMIT 200")
    return [_tx_json(_tx(r)) for r in rows]


def _ensure_incoming_free(conn, incoming_id: int, except_group: int | None = None) -> None:
    row = conn.execute(f"SELECT 1 FROM settlements s WHERE s.incoming_id = ? AND s.status = 'confirmed' "
                       f"AND {GROUP} IS NOT ?", (incoming_id, except_group)).fetchone()
    if row:
        raise ConflictError("이 입금은 이미 다른 결제의 정산으로 확정돼 있어요.")


def _group_incoming(conn, group_id: int) -> int:
    row = conn.execute(f"SELECT incoming_id FROM settlements s WHERE {GROUP} = ?", (group_id,)).fetchone()
    if row is None:
        raise LookupError("정산 제안을 찾을 수 없어요.")
    return row["incoming_id"]


def confirm_settlement(conn: sqlite3.Connection, group_id: int) -> None:
    incoming_id = _group_incoming(conn, group_id)
    _ensure_incoming_free(conn, incoming_id, group_id)
    conn.execute(f"UPDATE settlements AS s SET status = 'confirmed' WHERE {GROUP} = ?", (group_id,))
    conn.execute(f"UPDATE settlements AS s SET status = 'rejected' WHERE s.incoming_id = ? AND {GROUP} != ? "
                 "AND s.status = 'pending'", (incoming_id, group_id))
    conn.commit()


def reject_settlement(conn: sqlite3.Connection, group_id: int) -> None:
    _group_incoming(conn, group_id)
    conn.execute(f"UPDATE settlements AS s SET status = 'rejected' WHERE {GROUP} = ?", (group_id,))
    conn.commit()


def link_settlement(conn: sqlite3.Connection, payment_ids: int | list[int], incoming_id: int,
                    reason: str = "직접 연결") -> int:
    """받은 돈 하나를 결제 하나 또는 여러 개에 직접 연결해 바로 확정한다."""
    payment_ids = [payment_ids] if isinstance(payment_ids, int) else list(dict.fromkeys(payment_ids))
    marks = ",".join("?" * len(payment_ids))
    outs = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE direction = 'out' AND id IN ({marks})",
                        payment_ids).fetchone()[0]
    inc = conn.execute("SELECT direction FROM transactions WHERE id = ?", (incoming_id,)).fetchone()
    if not payment_ids or outs != len(payment_ids) or not inc or inc["direction"] != "in":
        raise ValueError("받은 돈 하나와 결제(출금)를 골라 주세요.")
    _ensure_incoming_free(conn, incoming_id)
    conn.execute("UPDATE settlements SET status = 'rejected' WHERE incoming_id = ? AND status = 'pending'",
                 (incoming_id,))
    # 예전에 거절했던 같은 짝은 지우고 새로 만든다 (짝마다 한 줄만 둘 수 있다)
    conn.execute(f"DELETE FROM settlements WHERE incoming_id = ? AND status = 'rejected' AND payment_id IN ({marks})",
                 (incoming_id, *payment_ids))
    group_id = _insert_group(conn, incoming_id, payment_ids, "confirmed", reason)
    conn.commit()
    return group_id


# ---- 예산 ----

def get_budgets(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["category"]: r["monthly_amount"] for r in conn.execute("SELECT * FROM budgets")}


def set_budgets(conn: sqlite3.Connection, budgets: dict[str, int]) -> None:
    for category, amount in budgets.items():
        if category not in cat_agent.CATEGORIES:
            raise ValueError(f"알 수 없는 카테고리: {category}")
        if amount and amount > 0:
            conn.execute("INSERT INTO budgets(category, monthly_amount) VALUES (?, ?) "
                         "ON CONFLICT(category) DO UPDATE SET monthly_amount = excluded.monthly_amount",
                         (category, int(amount)))
        else:
            conn.execute("DELETE FROM budgets WHERE category = ?", (category,))
    conn.commit()
