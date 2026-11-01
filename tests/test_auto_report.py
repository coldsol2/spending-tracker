"""지난 주 보고서 자동 작성."""
from datetime import date

from fastapi.testclient import TestClient

from app.agent import report
from app.agent.client import LLMError
from app.main import create_app
from conftest import FakeLLM
from test_agent import add_out

SUNDAY = date(2026, 11, 1)   # 지난 주 = 10.19(월) ~ 10.25(일)
MONDAY = date(2026, 11, 2)   # 지난 주 = 10.26(월) ~ 11.1(일)


def test_last_full_week():
    assert report.last_full_week(SUNDAY) == date(2026, 10, 19)
    assert report.last_full_week(MONDAY) == date(2026, 10, 26)


def test_creates_last_week_report_once(conn):
    add_out(conn, "김밥천국", 8000, "2026-10-21 12:00:00", category="식비", h="a")
    add_out(conn, "맘스터치", 9800, "2026-10-29 12:00:00", category="식비", h="b")
    llm = FakeLLM(text="# 지난 주")
    assert report.ensure_last_week(conn, llm, SUNDAY) == {"status": "created", "week_start": "2026-10-19"}
    assert report.ensure_last_week(conn, llm, SUNDAY) == {"status": "exists", "week_start": "2026-10-19"}
    assert llm.calls == ["text"]
    assert report.list_reports(conn)[0]["content"] == "# 지난 주"


def test_waits_until_data_covers_the_whole_week(conn):
    add_out(conn, "맘스터치", 9800, "2026-10-29 12:00:00", category="식비", h="b")
    llm = FakeLLM()
    # 11.1(일) 거래가 아직 없으니 10.26 주는 기다린다
    assert report.ensure_last_week(conn, llm, MONDAY) == {"status": "waiting_data", "week_start": "2026-10-26"}
    assert llm.calls == []


def test_skips_week_without_spending_and_without_ai(conn):
    add_out(conn, "맘스터치", 9800, "2026-10-29 12:00:00", category="식비", h="b")
    assert report.ensure_last_week(conn, FakeLLM(), SUNDAY)["status"] == "no_spending"
    add_out(conn, "김밥천국", 8000, "2026-10-21 12:00:00", category="식비", h="a")
    assert report.ensure_last_week(conn, None, SUNDAY)["status"] == "no_ai"


def test_ai_failure_is_reported_not_raised(conn):
    add_out(conn, "김밥천국", 8000, "2026-10-21 12:00:00", category="식비", h="a")
    add_out(conn, "맘스터치", 9800, "2026-10-29 12:00:00", category="식비", h="b")

    class Broken(FakeLLM):
        def text(self, system, user):
            raise LLMError("Claude 호출 실패")
    r = report.ensure_last_week(conn, Broken(), SUNDAY)
    assert r["status"] == "failed" and "Claude" in r["message"]
    assert report.list_reports(conn) == []


def test_auto_report_endpoint(tmp_path):
    llm = FakeLLM(text="# 지난 주")
    client = TestClient(create_app(tmp_path / "auto.db", llm_factory=lambda: llm))
    csv = "거래일시,적요,거래금액\n2026-10-21 12:00,김밥천국,-8000\n2026-10-30 12:00,맘스터치,-9800\n".encode()
    client.post("/api/upload", files={"file": ("t.csv", csv, "text/csv")})
    r = client.post("/api/reports/auto?today=2026-11-01").json()
    assert r == {"status": "created", "week_start": "2026-10-19"}
    assert client.post("/api/reports/auto?today=2026-11-01").json()["status"] == "exists"
