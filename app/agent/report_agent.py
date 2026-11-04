"""Console에서 만든 보고서 전용 에이전트(주간 실지출 리포터)에게 주간 보고서를 맡긴다.

숫자는 지금처럼 코드가 계산하고, 에이전트는 아래 도구로 필요한 숫자를 물어본 뒤 글·표·그래프를 쓴다.
양식은 에이전트에 붙은 weekly-report-writer 스킬에 있다.
"""
import json
import os
import sqlite3
from datetime import date, timedelta

import anthropic

from .. import service
from ..stats import week_budget
from . import managed
from .client import LLMError

AGENT_ID = os.environ.get("REPORT_AGENT_ID", "agent_019QkdS6FWZNJa1tNiUuqJVx")
FRIEND = "친구 송금"  # 보고서에 친구 이름이 나가지 않게 송금 상대 이름은 가린다
MAX_ROWS = 40

TASK = """{week} 주간 보고서를 써 줘. 이 주의 월요일은 {week_start}이다.
도구로 숫자를 확인한 뒤 weekly-report-writer 스킬의 양식대로 쓰고, 마지막 답에는 보고서 마크다운만 담아."""

_WEEK = {"type": "string", "description": "주의 월요일 YYYY-MM-DD (생략하면 이번 보고서의 주)"}


def definitions() -> list[dict]:
    return [
        {"type": "custom", "name": "week_summary",
         "description": "이번 주와 지난주의 실지출 합계, 카테고리별 실지출, 날짜별 실지출(월~일 순서).",
         "input_schema": {"type": "object", "properties": {"week_start": _WEEK}}},
        {"type": "custom", "name": "budgets",
         "description": "카테고리별 주간 예산 (월 예산을 주 단위로 환산). 정한 예산이 없으면 빈 목록.",
         "input_schema": {"type": "object", "properties": {"week_start": _WEEK}}},
        {"type": "custom", "name": "find_transactions",
         "description": "그 주의 결제 목록 (실지출이 큰 순서). category를 주면 그 카테고리만. "
                        "net은 친구가 정산해 준 돈을 뺀 실지출.",
         "input_schema": {"type": "object", "properties": {"category": {"type": "string"}, "week_start": _WEEK}}},
        {"type": "custom", "name": "last_report",
         "description": "바로 전 주의 보고서 전문 (그때 정한 다음 주 목표가 들어 있다). 없으면 null.",
         "input_schema": {"type": "object", "properties": {}}},
    ]


def _agent() -> dict:
    agent = {"type": "agent_with_overrides", "id": AGENT_ID, "tools": [
        # 스킬 파일을 읽을 read만 켜고 bash·웹 검색 같은 기본 도구는 끈다
        {"type": "agent_toolset_20260401",
         "default_config": {"enabled": False, "permission_policy": {"type": "auto"}},
         "configs": [{"name": "read", "enabled": True}]},
        *definitions()]}
    if os.environ.get("REPORT_AGENT_VERSION"):
        agent["version"] = int(os.environ["REPORT_AGENT_VERSION"])
    return agent


class ReportTools:
    def __init__(self, conn: sqlite3.Connection, week_start: date):
        self.conn = conn
        self.week_start = week_start
        self.calls = 0

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        self.calls += 1
        try:
            ws = date.fromisoformat(args["week_start"]) if args.get("week_start") else self.week_start
            ws -= timedelta(days=ws.weekday())
            result = {"week_summary": lambda: self.week_summary(ws), "budgets": lambda: self.budgets(ws),
                      "find_transactions": lambda: self.find_transactions(ws, args.get("category")),
                      "last_report": self.last_report}[name]()
            return json.dumps(result, ensure_ascii=False), False
        except (KeyError, ValueError) as e:
            return f"도구를 쓸 수 없어요: {name} {e}", True

    def _week(self, ws: date) -> dict:
        s = service.period_summary(self.conn, ws, ws + timedelta(days=6))
        days = ["월", "화", "수", "목", "금", "토", "일"]
        daily = [{"date": (ws + timedelta(days=i)).isoformat(), "weekday": d,
                  "amount": s["daily"].get((ws + timedelta(days=i)).isoformat(), 0)} for i, d in enumerate(days)]
        return {"week": f"{ws.isoformat()} ~ {(ws + timedelta(days=6)).isoformat()}", "total": s["total"],
                "by_category": s["by_category"], "daily": daily}

    def week_summary(self, ws: date) -> dict:
        return {"this_week": self._week(ws), "last_week": self._week(ws - timedelta(days=7))}

    def budgets(self, ws: date) -> dict:
        return {c: week_budget(a, ws) for c, a in service.get_budgets(self.conn).items()}

    def find_transactions(self, ws: date, category: str | None) -> list[dict]:
        top = service.period_summary(self.conn, ws, ws + timedelta(days=6), top_n=10_000)["top"]
        rows = [t for t in top if not category or t["category"] == category][:MAX_ROWS]
        return [{**t, "description": FRIEND if t["category"] == "송금" else t["description"]} for t in rows]

    def last_report(self) -> str | None:
        row = self.conn.execute("SELECT content FROM reports WHERE week_start = ?",
                                ((self.week_start - timedelta(days=7)).isoformat(),)).fetchone()
        return row["content"] if row else None


def write(conn: sqlite3.Connection, week_start: date, client: anthropic.Anthropic | None = None) -> tuple[str, dict]:
    """반환: (보고서 마크다운, 실행 정보)"""
    tools = ReportTools(conn, week_start)
    message = TASK.format(week=f"{week_start.isoformat()} ~ {(week_start + timedelta(days=6)).isoformat()}",
                          week_start=week_start.isoformat())
    info, text = managed.run_session(client or anthropic.Anthropic(), _agent(), f"{week_start} 주간 보고서",
                                     message, tools)
    if "## " not in text:
        raise LLMError("보고서 에이전트가 보고서를 쓰지 않았어요.")
    return text[text.index("## "):].strip(), info
