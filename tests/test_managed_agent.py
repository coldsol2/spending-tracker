"""Console 에이전트 연결: 거래 조회 도구가 정답을 새지 않는지, 세션 흐름이 맞는지 (네트워크 없이)."""
import json
from types import SimpleNamespace as NS

from app import service
from app.agent import managed
from app.agent.agent_tools import HIDDEN, Toolbox, definitions
from test_agent import add_out
from test_guess import evening
from test_multi_settle import tid


def data(conn):
    evening(conn)  # 만화카페 → 10분 뒤 카카오페이, 친구가 정산한 나이스 결제, 단서 없는 토스페이
    add_out(conn, "카카오페이", 12000, "2026-10-01 23:10:00", kind="펌뱅킹출금", h="kp-old")
    service.set_category(conn, tid(conn, "kp-old"), "술")  # 사용자가 고른 정답
    add_out(conn, "GS25", 3000, "2026-10-02 10:00:00", category="편의점", h="g1")
    service.set_category(conn, tid(conn, "g1"), "편의점")


def test_tools_hide_target_and_hidden_answers(conn):
    data(conn)
    kp, old, gs = tid(conn, "kp"), tid(conn, "kp-old"), tid(conn, "g1")
    box = Toolbox(conn, [kp, old], hide_ids={old, gs})
    rows, _ = box.run("find_transactions", {"name_contains": "카카오페이"})
    by_id = {r["id"]: r for r in json.loads(rows)}
    assert by_id[kp]["category"] == HIDDEN and by_id[old]["category"] == HIDDEN
    assert by_id[old]["user_chosen"] is False
    gs_row = json.loads(box.run("find_transactions", {"name_contains": "GS25"})[0])[0]
    assert gs_row["category"] == HIDDEN  # 숨긴 가게는 이름째 가린다
    assert json.loads(box.run("user_choices", {})[0]) == []  # 정답 예시도 숨긴다


def test_tools_show_context(conn):
    data(conn)
    kp, nice = tid(conn, "kp"), tid(conn, "nice")
    box = Toolbox(conn, [kp, nice])
    near = json.loads(box.run("nearby_transactions", {"txn_id": kp, "hours": 1})[0])
    assert [(r["name"], r["category"]) for r in near] == [("만화카페", "유흥")]
    info = json.loads(box.run("settlement_info", {"txn_id": nice})[0])
    assert info["paid_back_by_friends"] == [{"name": "이민수", "amount": 29000, "status": "confirmed"}]
    choices = json.loads(box.run("user_choices", {"name_contains": "카카오"})[0])
    assert [(c["name"], c["category"]) for c in choices] == [("카카오페이", "술")]
    text, err = box.run("없는도구", {})
    assert err and "모르는 도구" in text


def test_submit_keeps_only_targets_and_valid_values(conn):
    data(conn)
    kp, nice = tid(conn, "kp"), tid(conn, "nice")
    box = Toolbox(conn, [kp, nice])
    out = json.loads(box.run("submit_guesses", {"guesses": [
        {"txn_id": kp, "category": "유흥", "confidence": "high", "reason": "만화카페 직후"},
        {"txn_id": 999, "category": "술", "confidence": "high", "reason": "x"},
        {"txn_id": nice, "category": "없는카테고리", "confidence": "아주", "reason": "y"}]})[0])
    assert out["accepted"] == 2 and out["missing_txn_ids"] == []
    assert box.submitted[kp]["category"] == "유흥"
    assert box.submitted[nice] == {"category": "기타", "confidence": "low", "reason": "y"}


def test_tool_definitions_limit_categories():
    defs = {d["name"]: d for d in definitions(["식비", "기타"])}
    item = defs["submit_guesses"]["input_schema"]["properties"]["guesses"]["items"]
    assert item["properties"]["category"]["enum"] == ["식비", "기타"]
    assert set(defs) == {"find_transactions", "nearby_transactions", "settlement_info", "user_choices", "submit_guesses"}


class FakeClient:
    """세션 하나를 흉내 낸다: 도구 두 번 부르고(조회 → 제출) 쉬었다가 끝난다."""

    def __init__(self, kp):
        self.sent, self.created = [], None
        events = [
            NS(type="agent.custom_tool_use", id="e1", name="nearby_transactions", input={"txn_id": kp}),
            NS(type="session.status_idle", stop_reason=NS(type="requires_action")),
            NS(type="agent.custom_tool_use", id="e2", name="submit_guesses",
               input={"guesses": [{"txn_id": kp, "category": "유흥", "confidence": "high", "reason": "만화카페 10분 뒤"}]}),
            NS(type="session.status_idle", stop_reason=NS(type="end_turn")),
        ]

        class Stream:
            def __enter__(s): return iter(events)
            def __exit__(s, *a): return False

        def create(**kw):
            self.created = kw
            return NS(id="sesn_test")
        self.beta = NS(sessions=NS(
            create=create,
            retrieve=lambda sid: NS(usage=NS(list_cost=NS(amount="12", currency="USD"))),
            events=NS(stream=lambda session_id: Stream(),
                      send=lambda session_id, events: self.sent.extend(events))))


def test_session_flow_answers_tools_and_collects_guesses(conn):
    data(conn)
    kp = tid(conn, "kp")
    client = FakeClient(kp)
    result, info = managed.guess_with_agent(conn, [kp], web=False, client=client)
    assert result == {kp: {"category": "유흥", "confidence": "high", "reason": "만화카페 10분 뒤"}}
    assert (info["session_id"], info["tool_calls"], info["cost_usd"]) == ("sesn_test", 2, 0.12)
    # 에이전트 설정은 그대로 두고 이 세션만 도구를 바꿔 끼운다
    agent = client.created["agent"]
    assert agent["type"] == "agent_with_overrides" and agent["id"] == managed.AGENT_ID
    toolset = agent["tools"][0]
    assert {c["name"]: c["enabled"] for c in toolset["configs"]} == {"read": True, "web_search": False, "web_fetch": False}
    assert client.created["budget"]["max_list_cost"]["amount"] == managed.BUDGET_CENTS
    kinds = [e["type"] for e in client.sent]
    assert kinds == ["user.message", "user.custom_tool_result", "user.custom_tool_result"]
    assert "만화카페" in client.sent[1]["content"][0]["text"]
