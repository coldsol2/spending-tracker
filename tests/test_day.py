"""하루 화면: 그날 실지출, 카테고리별 금액, 결제·받은 돈 목록."""
from datetime import date

from app import service
from test_agent import add_out
from test_multi_settle import add_in, tid


def test_day_detail_with_settlement_and_budget(conn):
    add_out(conn, "고깃집", 60000, "2026-10-30 19:00:00", category="식비", h="meat")
    add_out(conn, "GS25", 3000, "2026-10-30 22:10:00", category="편의점", h="gs")
    add_out(conn, "환전", 50000, "2026-10-30 12:00:00", category="제외", h="fx")
    add_out(conn, "다음 날", 9000, "2026-10-31 00:10:00", category="식비", h="next")
    add_in(conn, "이민수", 30000, "2026-10-30 21:00:00", h="back")
    service.link_settlement(conn, [tid(conn, "meat")], tid(conn, "back"))
    service.set_budgets(conn, {"식비": 310000})

    d = service.day_detail(conn, date(2026, 10, 30))
    assert (d["date"], d["total"], d["gross"]) == ("2026-10-30", 33000, 63000)
    assert d["by_category"] == {"식비": 30000, "편의점": 3000}
    assert [(p["description"], p["amount"], p["net"]) for p in d["payments"]] == [
        ("환전", 50000, 50000), ("고깃집", 60000, 30000), ("GS25", 3000, 3000)]
    assert [i["description"] for i in d["incomings"]] == ["이민수"]
    assert d["incomings"][0]["settled"] == "confirmed"
    assert d["daily_budget"] == 10000  # 310,000원 ÷ 31일
    assert d["latest"] == "2026-10-31"


def test_empty_day_points_to_latest_record(conn):
    add_out(conn, "고깃집", 60000, "2026-10-30 19:00:00", category="식비", h="meat")
    d = service.day_detail(conn, date(2026, 11, 2))
    assert (d["total"], d["payments"], d["incomings"], d["daily_budget"]) == (0, [], [], None)
    assert d["latest"] == "2026-10-30"
