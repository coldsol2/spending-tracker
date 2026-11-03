"""Claude Console에서 만든 에이전트(Managed Agents)와 대화하는 최소 앱.

실행: python agent_app/main.py "이번 주 지출을 정리해 줘"
      (메시지를 빼면 입력을 물어본다)

세션을 만들고 → 이벤트 스트림을 먼저 연 뒤 → 사용자 메시지를 보내고 →
agent.message 글자를 받는 대로 출력한다. 세션이 할 일을 마치고 쉬면(idle) 끝낸다.
"""
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

AGENT_ID = "agent_0128BxkQYuBQBb3NJmcTHWyp"
ENVIRONMENT_ID = "env_01Mw2tQr7zFEvZWqqysdU3i7"

# 실지출 트래커와 같은 .env의 ANTHROPIC_API_KEY를 쓴다
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def answer_pending(client: anthropic.Anthropic, session_id: str, event) -> None:
    """이 최소 앱은 사람이 옆에 없으니, 에이전트가 허락을 구하거나 직접 만든 도구를 부르면 정중히 거절한다."""
    if event.type == "agent.custom_tool_use":
        print(f"\n[도구 요청: {event.name} → 이 앱에는 없는 도구라 거절했어요]", file=sys.stderr)
        client.beta.sessions.events.send(session_id=session_id, events=[{
            "type": "user.custom_tool_result", "custom_tool_use_id": event.id, "is_error": True,
            "content": [{"type": "text", "text": "This client does not implement custom tools."}],
        }])
    else:  # agent.tool_use / agent.mcp_tool_use 가 승인을 기다리는 경우
        print(f"\n[도구 승인 요청: {getattr(event, 'name', '?')} → 자동으로 거절했어요]", file=sys.stderr)
        client.beta.sessions.events.send(session_id=session_id, events=[{
            "type": "user.tool_confirmation", "tool_use_id": event.id, "result": "deny",
        }])


def run(message: str) -> int:
    client = anthropic.Anthropic()
    session = client.beta.sessions.create(agent=AGENT_ID, environment_id=ENVIRONMENT_ID)
    print(f"[세션 {session.id}]", file=sys.stderr)

    # 스트림을 먼저 열고 나서 메시지를 보내야 처음부터 실시간으로 받는다
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(session_id=session.id, events=[{
            "type": "user.message", "content": [{"type": "text", "text": message}],
        }])
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)
            elif event.type == "agent.custom_tool_use" or (
                    event.type in ("agent.tool_use", "agent.mcp_tool_use")
                    and getattr(event, "evaluated_permission", None) == "ask"):
                answer_pending(client, session.id, event)
            elif event.type == "session.error":
                print(f"\n[세션 오류] {getattr(event, 'error', event)}", file=sys.stderr)
            elif event.type == "session.status_idle":
                reason = event.stop_reason.type
                if reason == "requires_action":
                    continue  # 우리 응답(위의 거절)을 기다리는 잠깐의 멈춤
                print()
                if reason == "end_turn":
                    return 0
                print(f"[세션이 멈췄어요: {reason}]", file=sys.stderr)
                return 1
            elif event.type == "session.status_terminated":
                print("\n[세션이 종료됐어요]", file=sys.stderr)
                return 1
    print("\n[스트림이 예상보다 일찍 끊겼어요]", file=sys.stderr)
    return 1


def main() -> int:
    message = " ".join(sys.argv[1:]).strip() or input("에이전트에게 보낼 메시지: ").strip()
    if not message:
        print("보낼 메시지가 없어요.", file=sys.stderr)
        return 2
    try:
        return run(message)
    except anthropic.AuthenticationError:
        print("API 키가 없거나 틀렸어요. spending-tracker/.env의 ANTHROPIC_API_KEY를 확인해 주세요.", file=sys.stderr)
    except anthropic.NotFoundError as e:
        print(f"에이전트나 환경을 찾을 수 없어요. ID를 확인해 주세요. ({e.message})", file=sys.stderr)
    except anthropic.RateLimitError:
        print("요청이 많아 잠시 막혔어요. 조금 뒤 다시 실행해 주세요.", file=sys.stderr)
    except anthropic.APIStatusError as e:
        print(f"API 오류 {e.status_code}: {e.message}", file=sys.stderr)
    except anthropic.APIConnectionError:
        print("Anthropic 서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n중단했어요.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
