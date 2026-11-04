"""주간 보고서를 Console 보고서 에이전트가 쓴다. 숫자는 앱 도구가 계산해서 준다."""
import json
from datetime import date
from types import SimpleNamespace as NS

from app.agent import report, report_agent
from app.agent.client import LLMError
from conftest import FakeLLM
from test_agent import add_out

WEEK = date(2026, 10, 19)


def spend(conn):
    add_out(conn, "김밥천국", 8000, "2026-10-21 12:00:00", category="식비", h="a")
    add_out(conn, "코인노래방", 5000, "2026-10-24 21:00:00", category="유흥", h="b")
    add_out(conn, "김민수", 20000, "2026-10-24 23:00:00", category="송금", h="c")
    add_out(conn, "맘스터치", 9800, "2026-10-14 12:00:00", category="식비", h="d")  # 지난주
    conn.commit()


def test_tools_give_numbers_and_hide_friend_names(conn):
    spend(conn)
    tools = report_agent.ReportTools(conn, WEEK)
    summary = json.loads(tools.run("week_summary", {})[0])
    assert summary["this_week"]["total"] == 33000 and summary["last_week"]["total"] == 9800
    assert [d["amount"] for d in summary["this_week"]["daily"]] == [0, 0, 8000, 0, 0, 25000, 0]
    assert summary["this_week"]["daily"][5]["weekday"] == "토"
    found = json.loads(tools.run("find_transactions", {})[0])
    assert {t["description"] for t in found} == {"김밥천국", "코인노래방", "친구 송금"}
    only = json.loads(tools.run("find_transactions", {"category": "식비"})[0])
    assert [t["description"] for t in only] == ["김밥천국"]
    assert json.loads(tools.run("last_report", {})[0]) is None
    assert tools.run("없는도구", {})[1] is True


def test_last_report_is_the_previous_week(conn):
    conn.execute("INSERT INTO reports(week_start, content, created_at) VALUES ('2026-10-12', '목표: 배달 2번', 'x')")
    assert report_agent.ReportTools(conn, WEEK).last_report() == "목표: 배달 2번"


class FakeClient:
    """도구 하나 부르고 보고서 글을 쓴 뒤 끝나는 세션."""

    def __init__(self):
        self.sent = []
        events = [
            NS(type="agent.custom_tool_use", id="e1", name="week_summary", input={}),
            NS(type="session.status_idle", stop_reason=NS(type="requires_action")),
            NS(type="agent.message", id="m1", content=[NS(type="text", text="숫자를 봤어요.\n\n## 한 줄 요약\n33,000원 썼어요.")]),
            NS(type="session.status_idle", stop_reason=NS(type="end_turn")),
        ]

        class Stream:
            def __enter__(s): return iter(events)
            def __exit__(s, *a): return False
        self.beta = NS(sessions=NS(
            create=lambda **kw: NS(id="sesn_r"),
            retrieve=lambda sid: NS(usage=NS(list_cost=NS(amount="3", currency="USD"))),
            events=NS(stream=lambda session_id: Stream(),
                      send=lambda session_id, events: self.sent.extend(events))))


def test_agent_writes_report_from_tool_numbers(conn):
    spend(conn)
    client = FakeClient()
    text, info = report_agent.write(conn, WEEK, client=client)
    assert text == "## 한 줄 요약\n33,000원 썼어요."  # 앞의 혼잣말은 버린다
    answer = json.loads(client.sent[1]["content"][0]["text"])  # [0]은 처음 보낸 요청
    assert answer["this_week"]["total"] == 33000
    assert info["tool_calls"] == 1


def test_generate_falls_back_to_api_when_agent_fails(conn, monkeypatch):
    spend(conn)
    monkeypatch.setenv("REPORT_ENGINE", "agent")

    def broken(c, ws):
        raise LLMError("연결 끊김")
    monkeypatch.setattr(report_agent, "write", broken)
    assert report.generate(conn, FakeLLM(text="## 대신 쓴 보고서"), WEEK) == "## 대신 쓴 보고서"


def test_generate_uses_agent_report(conn, monkeypatch):
    spend(conn)
    monkeypatch.setenv("REPORT_ENGINE", "agent")
    monkeypatch.setattr(report_agent, "write", lambda c, ws: ("## 에이전트 보고서", {}))
    llm = FakeLLM()
    assert report.generate(conn, llm, WEEK) == "## 에이전트 보고서"
    assert llm.calls == []
