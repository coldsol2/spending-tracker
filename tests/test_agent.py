from datetime import date, datetime

from app.agent import categorize as cat
from app.agent import match, report
from app.agent.categorize import CategoryResult, Item
from app.agent.match import Match, MatchResult
from app.service import set_budgets
from conftest import FakeLLM


def add_out(conn, desc, amount=1000, when="2026-10-27 12:00:00", kind="체크카드결제", category=None, h=None):
    conn.execute("INSERT INTO transactions(occurred_at, description, amount, direction, category, source_hash, kind) "
                 "VALUES (?, ?, ?, 'out', ?, ?, ?)", (when, desc, amount, category, h or f"{desc}{when}", kind))
    conn.commit()


def all_food(payload):
    return CategoryResult(items=[Item(merchant=m["name"], category="식비") for m in payload["merchants"]])


def test_categorize_uses_cache_and_only_asks_missing(conn):
    cat.remember(conn, "스타벅스", "유흥")
    asked = []
    llm = FakeLLM({"CategoryResult": lambda p: (asked.extend(m["name"] for m in p["merchants"]), all_food(p))[1]})
    result = cat.categorize(conn, llm, ["스타벅스", "김밥천국", "김밥천국"])
    assert result == {"스타벅스": "유흥", "김밥천국": "식비"}
    assert asked == ["김밥천국"]
    assert cat.cached(conn, "김밥천국") == "식비"


def test_categorize_sends_context_and_user_examples(conn):
    add_out(conn, "김철수", 28600, "2026-10-29 21:39:32", kind="출금")
    cat.remember(conn, "만화카페 행복점", "유흥", source="user")
    cat.remember(conn, "어떤가게", "식비", source="ai")
    seen = {}

    def handle(payload):
        seen.update(payload)
        return CategoryResult(items=[Item(merchant="김철수", category="송금", confident=True, varies=True)])
    cat.categorize(conn, FakeLLM({"CategoryResult": handle}), ["김철수"])
    assert seen["merchants"] == [{"name": "김철수", "kind": "출금", "count": 1, "amounts": [28600], "times": ["21:39"]}]
    assert seen["examples"] == [{"name": "만화카페 행복점", "category": "유흥"}]  # AI가 정한 건 예시가 아니다
    row = conn.execute("SELECT * FROM merchant_categories WHERE merchant = '김철수'").fetchone()
    assert (row["category"], row["source"], row["varies"]) == ("송금", "ai", 1)


def test_categorize_skips_llm_when_all_cached(conn):
    cat.remember(conn, "스타벅스", "유흥")
    llm = FakeLLM()
    assert cat.categorize(conn, llm, ["스타벅스"]) == {"스타벅스": "유흥"}
    assert llm.calls == []


def test_categorize_ignores_unasked_merchants(conn):
    llm = FakeLLM({"CategoryResult": lambda p: CategoryResult(items=[Item(merchant="엉뚱한곳", category="쇼핑")])})
    assert cat.categorize(conn, llm, ["김밥천국"]) == {}


def test_categorize_without_llm_returns_cache_only(conn):
    assert cat.categorize(conn, None, ["김밥천국"]) == {}


def test_match_drops_payment_outside_candidates():
    t = datetime(2026, 10, 3, 19)
    cands = [{"incoming": {"id": 10, "occurred_at": t, "description": "이민수", "amount": 1},
              "payments": [{"id": 1, "occurred_at": t, "description": "고기집", "amount": 9}]}]
    llm = FakeLLM({"MatchResult": lambda _: MatchResult(matches=[
        Match(incoming_id=10, payment_ids=[99], reason="x"),
        Match(incoming_id=77, payment_ids=[1], reason="x"),
        Match(incoming_id=10, payment_ids=[], reason="정산 아님"),
    ])})
    assert match.propose(llm, cands) == []
    llm = FakeLLM({"MatchResult": lambda _: MatchResult(matches=[
        Match(incoming_id=10, payment_ids=[1, 99, 1], reason="같이 먹음")])})
    assert match.propose(llm, cands) == [{"incoming_id": 10, "payment_ids": [1], "reason": "같이 먹음"}]


def test_report_input_and_save(conn):
    add_out(conn, "김밥천국", 8000, category="식비")
    set_budgets(conn, {"식비": 310000})
    data = report.build_week_input(conn, date(2026, 10, 29))  # 목요일 → 그 주 월요일로
    assert data["week"] == "2026-10-26 ~ 2026-11-01"
    assert data["this_week"]["by_category"] == {"식비": 8000}
    assert data["weekly_budget"] == {"식비": 70000}
    assert data["top_payments"][0]["description"] == "김밥천국"

    content = report.generate(conn, FakeLLM(text="# 이번 주"), date(2026, 10, 29))
    assert content == "# 이번 주"
    assert report.list_reports(conn)[0]["week_start"] == "2026-10-26"
