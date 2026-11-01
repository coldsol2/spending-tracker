"""정산 점검(2026-11-01)에서 찾은 패턴: 여러 결제를 합친 정산, 취소된 결제, 예금주·환전 입금."""
from datetime import date

import pytest

from app import service
from app.agent.match import Match, MatchResult
from app.pdf_reader import find_owner
from conftest import FakeLLM
from pdf_util import FONT, make_statement_pdf
from test_agent import add_out

OCT = (date(2026, 10, 1), date(2026, 10, 31))


def add_in(conn, desc, amount, when, kind="입금", h=None):
    conn.execute("INSERT INTO transactions(occurred_at, description, amount, direction, source_hash, kind) "
                 "VALUES (?, ?, ?, 'in', ?, ?)", (when, desc, amount, h or f"{desc}{when}", kind))
    conn.commit()


def tid(conn, h):
    return conn.execute("SELECT id FROM transactions WHERE source_hash = ?", (h,)).fetchone()["id"]


def dinner_and_cafe(conn):
    """1차 식당 2건 + 2차 만화카페, 친구가 전체의 절반을 보냄."""
    add_out(conn, "돈가스집", 15000, "2026-10-03 18:23:00", category="식비", h="p1")
    add_out(conn, "돈가스집", 26500, "2026-10-03 19:05:00", category="식비", h="p2")
    add_out(conn, "만화카페", 31200, "2026-10-03 22:48:00", category="유흥", h="p3")
    add_in(conn, "김철수", 36350, "2026-10-04 00:57:00", h="i1")
    return [tid(conn, h) for h in ("p1", "p2", "p3")], tid(conn, "i1")


def test_one_transfer_split_over_several_payments(conn):
    pays, inc = dinner_and_cafe(conn)
    gid = service.link_settlement(conn, pays, inc)
    s = service.period_summary(conn, *OCT)
    assert s["total"] == 72700 - 36350
    assert s["by_category"] == {"식비": 41500 - 7500 - 13250, "유흥": 31200 - 15600}
    assert s["income"] == 0
    [item] = service.list_settlements(conn)["confirmed"]
    assert item["id"] == gid
    assert [(p["description"], p["share"]) for p in item["payments"]] == [
        ("돈가스집", 7500), ("돈가스집", 13250), ("만화카페", 15600)]


def test_group_is_rejected_and_relinked_as_one(conn):
    pays, inc = dinner_and_cafe(conn)
    gid = service.link_settlement(conn, pays, inc)
    service.reject_settlement(conn, gid)
    assert service.period_summary(conn, *OCT)["total"] == 72700
    # 거절한 짝이 남아 있어도 다시 연결할 수 있다
    service.link_settlement(conn, pays[:2], inc)
    assert service.period_summary(conn, *OCT)["total"] == 72700 - 36350


def test_ai_proposes_several_payments_and_confirm_takes_the_group(conn):
    pays, inc = dinner_and_cafe(conn)
    seen = {}

    def handle(payload):
        seen["payments"] = sorted(p["id"] for p in payload[0]["payments"])
        return MatchResult(matches=[Match(incoming_id=inc, payment_ids=pays, reason="1차+2차 72,700원을 둘이 나눔")])
    assert service.propose_settlements(conn, FakeLLM({"MatchResult": handle})) == 1
    assert seen["payments"] == sorted(pays)  # 입금보다 작은 결제들도 후보로 간다
    [item] = service.list_settlements(conn)["pending"]
    assert len(item["payments"]) == 3
    assert service.period_summary(conn, *OCT)["projected_total"] == 36350
    service.confirm_settlement(conn, item["id"])
    assert service.period_summary(conn, *OCT)["total"] == 36350
    with pytest.raises(service.ConflictError):
        service.link_settlement(conn, [pays[0]], inc)


def test_cancelled_payment_is_not_a_candidate(conn):
    add_out(conn, "쿠팡이츠_KCP", 47600, "2026-10-20 10:10:30", category="식비", h="c1")
    add_in(conn, "쿠팡이츠_KCP", 47600, "2026-10-20 10:10:46", kind="체크카드결제", h="c2")
    add_out(conn, "쿠팡이츠_나이스", 59500, "2026-10-20 10:11:00", category="식비", h="c3")
    add_in(conn, "이민수", 11500, "2026-10-20 13:26:00", h="c4")
    conn.execute("INSERT INTO settlements(payment_id, incoming_id, status, reason) VALUES (?, ?, 'confirmed', ?)",
                 (tid(conn, "c1"), tid(conn, "c2"), service.REFUND_REASON))
    conn.commit()
    seen = {}

    def handle(payload):
        seen["payments"] = [p["description"] for p in payload[0]["payments"]]
        return MatchResult(matches=[])
    service.propose_settlements(conn, FakeLLM({"MatchResult": handle}))
    assert seen["payments"] == ["쿠팡이츠_나이스"]


@pytest.mark.skipif(not FONT.exists(), reason="한글 글꼴(맑은 고딕)이 없음")
def test_account_owner_and_exchange_transfers_are_skipped(conn):
    rows = [["거래 일시", "적요", "거래 유형", "거래 금액", "거래 후 잔액"],
            ["2026.10.11 10:15:00", "홍길동", "입금", "15,761", "100,000"],
            ["2026.10.12 09:07:00", "원하는 환율에 환전 (USD)", "출금", "-56,265", "43,735"],
            ["2026.10.18 20:02:00", "원화로 환전 (USD)", "입금", "13,391", "57,126"],
            ["2026.10.20 10:00:00", "이민수", "입금", "8,000", "65,126"]]
    r = service.import_file(conn, "toss.pdf", make_statement_pdf(rows, owner="홍길동"), llm=None)
    assert r["added"] == 1
    assert "3건" in r["warning"]
    assert service.owner_names(conn) == {"홍길동"}
    # 예금주 이름은 기억해 두어, 예금주 줄이 없는 CSV에서도 뺀다
    csv = "거래일시,적요,거래금액\n2026-10-25 12:00,홍길동,30000\n".encode()
    assert service.import_file(conn, "x.csv", csv, llm=None)["added"] == 0


def test_find_owner():
    assert find_owner("거래내역서\n예금주 홍길동\n계좌번호 1000-0000") == "홍길동"
    assert find_owner("예금주: 김철수") == "김철수"
    assert find_owner("거래내역서") is None
