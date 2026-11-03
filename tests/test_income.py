"""들어온 돈 종류 분류: 규칙(환불·확정 정산) 먼저, 나머지는 단서와 함께 AI에게, 정답 예시는 숨길 수 있게."""
from app import service, settle
from app.agent import income
from app.agent.income import IncomeGuess, IncomeResult
from conftest import FakeLLM
from test_agent import add_out
from test_guess import evening
from test_multi_settle import add_in, tid


def month_of_pocket_money(conn):
    add_in(conn, "박엄마", 300000, "2026-09-01 09:00:00", h="m9")
    add_in(conn, "박엄마", 300000, "2026-10-01 09:00:00", h="m10")
    add_out(conn, "고기집", 60000, "2026-10-10 20:00:00", category="식비", h="meat")
    add_in(conn, "김친구", 20000, "2026-10-10 22:00:00", h="friend")
    add_in(conn, "(주)카페알바", 450000, "2026-10-10 10:00:00", kind="급여", h="pay")


def echo(seen):
    def handler(payload):
        seen.append(payload)
        return IncomeResult(guesses=[IncomeGuess(txn_id=t["txn_id"], category="용돈", confidence="medium",
                                                 reason="매달 같은 금액") for t in payload["targets"]])
    return handler


def test_rules_first_then_ai_with_clues(conn):
    evening(conn)  # 이민수 입금은 나이스 결제의 정산으로 확정되어 있다
    month_of_pocket_money(conn)
    assert settle.is_refund("체크카드결제", "GS25")  # 결제 취소는 들어온 돈 쪽 체크카드결제
    add_in(conn, "GS25", 3000, "2026-10-11 10:00:00", kind="체크카드결제", h="refund")
    ids = [r["id"] for r in conn.execute("SELECT id FROM transactions WHERE direction = 'in'")]
    seen = []
    out = income.classify(conn, FakeLLM({"IncomeResult": echo(seen)}), ids)

    assert out[tid(conn, "refund")]["category"] == "환불"
    assert out[tid(conn, "back")]["category"] == "정산"
    asked = {t["txn_id"]: t for t in seen[0]["targets"]}
    assert set(asked) == {tid(conn, h) for h in ("m9", "m10", "friend", "pay")}  # 규칙으로 정한 건 묻지 않는다
    assert [h["amount"] for h in asked[tid(conn, "m10")]["same_sender_in"]] == [300000]  # 매달 오는 패턴
    meat = next(p for p in asked[tid(conn, "friend")]["payments_near"] if p["name"] == "고기집")
    assert meat["split"].endswith("÷ 3명 ≈ 입금액")  # 6만 원 ÷ 3명 = 2만 원


def test_examples_hide_answers(conn):
    month_of_pocket_money(conn)
    for h, label in (("m9", "용돈"), ("pay", "알바비")):
        conn.execute("INSERT INTO income_labels(txn_id, label) VALUES (?, ?)", (tid(conn, h), label))
    seen = []
    income.classify(conn, FakeLLM({"IncomeResult": echo(seen)}), [tid(conn, "m10")], hide_ids={tid(conn, "pay")})
    assert [e["category"] for e in seen[0]["examples"]] == ["용돈"]


def test_import_saves_income_guess_without_touching_spending(conn):
    month_of_pocket_money(conn)
    conn.execute("INSERT INTO income_labels(txn_id, label) VALUES (?, '용돈')", (tid(conn, "m9"),))
    seen = []
    assert service.classify_income_pending(conn, FakeLLM({"IncomeResult": echo(seen)})) == 3  # 고른 건 건너뜀
    row = conn.execute("SELECT ai_guess, ai_confidence, category FROM transactions WHERE id = ?",
                       (tid(conn, "m10"),)).fetchone()
    assert tuple(row) == ("용돈", "medium", None)
    assert service.list_review(conn) == []  # 들어온 돈은 지출 확인 목록에 끼지 않는다
