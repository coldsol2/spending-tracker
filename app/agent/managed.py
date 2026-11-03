"""Console에서 만든 에이전트(Managed Agents)에게 어려운 거래의 추측을 맡긴다.

에이전트 설정은 그대로 두고, 이 세션에서만 도구를 바꿔 끼운다(agent_with_overrides).
- 거래 조회 도구(agent_tools.py)를 붙여 에이전트가 필요한 만큼 스스로 더 찾아보게 한다.
- 웹 검색은 환경 네트워크가 허용할 때만 켠다 (WEB_SEARCH=1).
결과는 guess.guess와 같은 모양 {txn_id: {category, confidence, reason}}으로 돌려준다.
"""
import json
import os
import sqlite3
import time

import anthropic

from .. import categories as cats
from . import guess
from .agent_tools import Toolbox, definitions
from .client import DEFAULT_MODEL, LLMError

AGENT_ID = os.environ.get("AGENT_ID", "agent_0128BxkQYuBQBb3NJmcTHWyp")
ENVIRONMENT_ID = os.environ.get("AGENT_ENVIRONMENT_ID", "env_01Mw2tQr7zFEvZWqqysdU3i7")
MODEL = os.environ.get("AGENT_MODEL", os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL))  # 기존 API와 같은 모델로 비교
EFFORT = os.environ.get("AGENT_EFFORT", "medium")  # Haiku 5.5·Opus 5.5 기본값과 같다
BUDGET_CENTS = "300"  # 세션 하나에 $3 넘게 쓰지 않는다
DEADLINE_SECONDS = 15 * 60

TASK = """아래 targets는 가게 이름만으로는 용도를 알 수 없는 출금이다(페이 결제, 결제대행사 이름, 친구 송금, 처음 보는 가게).
각 거래의 카테고리를 추리하라. 도구로 필요한 만큼 더 찾아볼 수 있다:
- nearby_transactions: 같은 자리에서 이어진 결제 (예: 만화카페 결제 10분 뒤 카카오페이 → 유흥)
- settlement_info: 친구들이 나눠 낸 결제인지
- find_transactions: 같은 친구·같은 가게의 다른 거래, 같은 요일·시간대 패턴
- user_choices: 사용자가 직접 고른 정답 예시 (비슷한 이름·금액·시간대면 따른다)
{web}
카테고리 (사용자가 만든 것도 있다):
{categories}
송금은 용도를 알 수 없는 사람 간 송금, 기타는 정말 모를 때만 쓴다.

다 추리했으면 submit_guesses로 모든 거래를 한 번에 제출하고 마친다.
confidence는 high(단서가 분명함) / medium(그럴듯함) / low(단서가 거의 없음). 단서가 없으면 억지로 맞히지 말고 low.
reason은 판단에 쓴 단서를 짚는 한국어 한 문장.

targets:
{targets}"""
WEB_HINT = "- web_search: 처음 보는 가게 이름이 무슨 업종인지 (예: 법인명만 적힌 가게 → 마트인지 PC방인지)\n"


def _tools(names: list[str], web: bool) -> list[dict]:
    # 에이전트에 붙은 pdf 스킬 때문에 read는 켜 둔다. 이 일에 쓰지 않는 bash·파일 쓰기는 끈다.
    toolset = {"type": "agent_toolset_20260401",
               "default_config": {"enabled": False, "permission_policy": {"type": "auto"}},
               "configs": [{"name": "read", "enabled": True},
                           {"name": "web_search", "enabled": web},
                           {"name": "web_fetch", "enabled": False}]}
    return [toolset, *definitions(names)]


def _targets(conn: sqlite3.Connection, txn_ids: list[int]) -> str:
    rows = conn.execute(f"SELECT * FROM transactions WHERE id IN ({','.join('?' * len(txn_ids))}) "
                        "ORDER BY occurred_at", txn_ids)
    return json.dumps([{"txn_id": r["id"], "time": guess._when(r["occurred_at"]), "name": r["description"],
                        "kind": r["kind"], "amount": r["amount"]} for r in rows], ensure_ascii=False)


def guess_with_agent(conn: sqlite3.Connection, txn_ids: list[int], hide_ids: set[int] = frozenset(),
                     web: bool | None = None, client: anthropic.Anthropic | None = None) -> tuple[dict, dict]:
    """반환: (추측 {txn_id: {...}}, 실행 정보 {session_id, cost_usd, tool_calls, seconds})"""
    if not txn_ids:
        return {}, {}
    web = os.environ.get("WEB_SEARCH") == "1" if web is None else web
    client = client or anthropic.Anthropic()
    names = cats.names(conn)
    box = Toolbox(conn, txn_ids, hide_ids)
    started = time.monotonic()
    try:
        session = client.beta.sessions.create(
            agent={"type": "agent_with_overrides", "id": AGENT_ID, "tools": _tools(names, web),
                   "model": {"id": MODEL, "effort": {"type": EFFORT}}},
            environment_id=ENVIRONMENT_ID,
            title=f"거래 {len(txn_ids)}건 추측",
            budget={"type": "limit", "max_list_cost": {"amount": BUDGET_CENTS, "currency": "USD"}},
        )
        message = TASK.format(web=WEB_HINT if web else "", categories=cats.prompt_list(conn),
                              targets=_targets(conn, txn_ids))
        with client.beta.sessions.events.stream(session_id=session.id) as stream:
            client.beta.sessions.events.send(session_id=session.id, events=[
                {"type": "user.message", "content": [{"type": "text", "text": message}]}])
            for event in stream:
                if time.monotonic() - started > DEADLINE_SECONDS:
                    client.beta.sessions.events.send(session_id=session.id, events=[{"type": "user.interrupt"}])
                    raise LLMError("에이전트가 제한 시간 안에 끝내지 못했어요.")
                if event.type == "agent.custom_tool_use":
                    text, is_error = box.run(event.name, dict(event.input or {}))
                    client.beta.sessions.events.send(session_id=session.id, events=[{
                        "type": "user.custom_tool_result", "custom_tool_use_id": event.id, "is_error": is_error,
                        "content": [{"type": "text", "text": text}]}])
                elif event.type == "session.error":
                    raise LLMError(f"에이전트 세션 오류: {getattr(event, 'error', event)}")
                elif event.type == "session.status_idle":
                    if event.stop_reason.type == "requires_action":
                        continue
                    if event.stop_reason.type != "end_turn":
                        raise LLMError(f"에이전트가 멈췄어요: {event.stop_reason.type}")
                    break
                elif event.type == "session.status_terminated":
                    break
        usage = client.beta.sessions.retrieve(session.id).usage
        cost = getattr(getattr(usage, "list_cost", None), "amount", None)
    except anthropic.APIError as e:
        raise LLMError(f"에이전트 호출 실패: {e}") from e
    info = {"session_id": session.id, "cost_usd": float(cost) / 100 if cost is not None else None,
            "tool_calls": box.calls, "seconds": round(time.monotonic() - started)}
    return box.submitted, info
