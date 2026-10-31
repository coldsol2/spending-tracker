"""카테고리 개편: 건별/가게별 적용, 분류 확인 목록, 제외, 재분류, 예전 DB 이전."""
import sqlite3
from datetime import date

import pytest

from app import db, service
from app.agent import categorize as cat
from app.agent.categorize import CategoryResult, Item
from app.agent.client import LLMError
from conftest import FakeLLM
from test_agent import add_out

OCT = (date(2026, 10, 1), date(2026, 10, 31))


def setup_data(conn):
    add_out(conn, "김철수", 28600, "2026-10-29 21:00:00", kind="출금", h="a")
    add_out(conn, "김철수", 13000, "2026-10-20 12:00:00", kind="출금", h="b")
    add_out(conn, "이마트24 행복점", 1500, "2026-10-21 09:00:00", h="c")
    add_out(conn, "이마트24 행복점", 2500, "2026-10-22 09:00:00", h="d")
    add_out(conn, "대표일반_나이스", 54000, "2026-10-23 19:00:00", h="e")
    add_out(conn, "원하는 환율에 환전 (USD)", 100000, "2026-10-24 10:00:00", kind="출금", h="f")
    answers = {
        "김철수": Item(merchant="김철수", category="송금", varies=True),
        "이마트24 행복점": Item(merchant="이마트24 행복점", category="편의점"),
        "대표일반_나이스": Item(merchant="대표일반_나이스", category="기타", confident=False, varies=True),
        "원하는 환율에 환전 (USD)": Item(merchant="원하는 환율에 환전 (USD)", category="제외"),
    }
    llm = FakeLLM({"CategoryResult": lambda p: CategoryResult(items=[answers[m["name"]] for m in p["merchants"]])})
    service.categorize_pending(conn, llm)
    return llm


def txn_id(conn, h):
    return conn.execute("SELECT id FROM transactions WHERE source_hash = ?", (h,)).fetchone()["id"]


def test_excluded_category_is_not_spending(conn):
    setup_data(conn)
    s = service.period_summary(conn, *OCT)
    assert s["total"] == 28600 + 13000 + 1500 + 2500 + 54000
    assert "제외" not in s["by_category"]


def test_review_list_holds_transfers_and_unsure_items(conn):
    setup_data(conn)
    review = {t["description"] for t in service.list_review(conn)}
    assert review == {"김철수", "대표일반_나이스"}


def test_person_transfer_category_applies_to_one_transaction(conn):
    setup_data(conn)
    r = service.set_category(conn, txn_id(conn, "a"), "술")
    assert r == {"scope": "one", "updated": 1}
    s = service.period_summary(conn, *OCT)
    assert s["by_category"]["술"] == 28600 and s["by_category"]["송금"] == 13000
    # 정한 거래는 확인 목록에서 빠지고, 나머지 송금은 남는다
    assert [t["source_hash"] for t in service.list_review(conn) if t["description"] == "김철수"] == ["b"]
    assert cat.cached(conn, "김철수") == "송금"  # 사람 이름 캐시는 그대로


def test_store_category_applies_to_all_and_is_remembered(conn):
    setup_data(conn)
    r = service.set_category(conn, txn_id(conn, "c"), "식비")
    assert r == {"scope": "merchant", "updated": 2}
    row = conn.execute("SELECT category, source FROM merchant_categories WHERE merchant = '이마트24 행복점'").fetchone()
    assert (row["category"], row["source"]) == ("식비", "user")


def test_explicit_scope_overrides_default(conn):
    setup_data(conn)
    r = service.set_category(conn, txn_id(conn, "a"), "식비", scope="merchant")
    assert r["updated"] == 2
    with pytest.raises(ValueError):
        service.set_category(conn, txn_id(conn, "a"), "식비", scope="all")


def test_recategorize_keeps_user_choices(conn):
    setup_data(conn)
    service.set_category(conn, txn_id(conn, "c"), "식비")          # 가게: 사용자 지정
    service.set_category(conn, txn_id(conn, "a"), "술")             # 송금 한 건: 사용자 지정
    asked = []
    llm = FakeLLM({"CategoryResult": lambda p: (asked.extend(m["name"] for m in p["merchants"]),
                                                CategoryResult(items=[Item(merchant=m["name"], category="쇼핑")
                                                                      for m in p["merchants"]]))[1]})
    service.recategorize(conn, llm)
    assert sorted(asked) == sorted(["김철수", "대표일반_나이스", "원하는 환율에 환전 (USD)"])
    cats = {r["source_hash"]: r["category"] for r in conn.execute("SELECT source_hash, category FROM transactions")}
    assert cats["a"] == "술" and cats["c"] == "식비" and cats["d"] == "식비" and cats["b"] == "쇼핑"
    with pytest.raises(LLMError):
        service.recategorize(conn, None)


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE transactions (id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, description TEXT NOT NULL,
            amount INTEGER NOT NULL, direction TEXT NOT NULL, balance INTEGER, category TEXT,
            source_hash TEXT NOT NULL UNIQUE);
        CREATE TABLE merchant_categories (merchant TEXT PRIMARY KEY, category TEXT NOT NULL);
        CREATE TABLE budgets (category TEXT PRIMARY KEY, monthly_amount INTEGER NOT NULL);
        INSERT INTO transactions VALUES (1, '2026-10-01 10:00:00', '스타벅스', 5000, 'out', NULL, '카페', 'x');
        INSERT INTO merchant_categories VALUES ('스타벅스', '카페');
        INSERT INTO budgets VALUES ('교통', 50000);
    """)
    old.commit()
    old.close()
    conn = db.connect(path)
    assert conn.execute("SELECT category, reviewed, kind FROM transactions").fetchone()[:] == ("유흥", 0, None)
    assert conn.execute("SELECT category, source FROM merchant_categories").fetchone()[:] == ("유흥", "ai")
    assert service.get_budgets(conn) == {"교통비": 50000}
    conn.close()
