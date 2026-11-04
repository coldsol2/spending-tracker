"""주간 절약 보고서. 숫자는 코드가 계산하고, Claude는 해석과 제안만 쓴다."""
import json
import logging
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

from .. import service
from ..stats import week_budget
from .client import LLMError

SYSTEM = """너는 사용자의 개인 소비 코치다. 입력 JSON에는 한 주(월~일)의 실지출이 들어 있다.
실지출은 사용자가 결제한 금액에서 친구들이 더치페이로 돌려준 돈과 결제 취소를 뺀 금액이다.
'송금'은 친구에게 보낸 돈 중 용도를 아직 정하지 않은 것이고, '제외'(환전·투자 등)는 이미 빠져 있다.
- this_week / last_week: 카테고리별 실지출(by_category), 일별 실지출(daily), 합계(total)
- weekly_budget: 카테고리별 주간 예산 (월 예산을 주 단위로 환산). 없는 카테고리는 예산 미설정
- top_payments: 이번 주 실지출이 큰 결제

한국어 마크다운으로 짧은 주간 보고서를 써라. 구성:
## 한 줄 요약
## 예산 대비 (예산을 넘긴 카테고리와 초과 금액. 예산이 하나도 없으면 예산 설정을 권하는 한 문장)
## 지난 주 대비 (많이 늘어난 카테고리)
## 이번 주에 줄일 수 있었던 곳 (실제 결제 항목을 근거로 구체적인 금액과 함께 2~3개)
## 다음 주 목표 (실천 가능한 한 가지)
친구에게 말하듯 '~했어요', '~해 보세요' 같은 해요체로 쓴다.
금액은 '12,300원'처럼 쓴다. 입력에 없는 숫자를 지어내지 말고, 전체 400단어 이내로 쓴다."""


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_week_input(conn: sqlite3.Connection, week_start: date) -> dict:
    ws = week_start_of(week_start)
    this = service.period_summary(conn, ws, ws + timedelta(days=6))
    last = service.period_summary(conn, ws - timedelta(days=7), ws - timedelta(days=1))
    pick = lambda s: {"total": s["total"], "by_category": s["by_category"], "daily": s["daily"]}
    return {
        "week": f"{ws.isoformat()} ~ {(ws + timedelta(days=6)).isoformat()}",
        "this_week": pick(this),
        "last_week": pick(last),
        "weekly_budget": {c: week_budget(a, ws) for c, a in service.get_budgets(conn).items()},
        "top_payments": this["top"],
    }


def generate(conn: sqlite3.Connection, llm, week_start: date) -> str:
    if llm is None:
        raise LLMError(service.NO_KEY_WARNING)
    ws = week_start_of(week_start)
    content = None
    if os.environ.get("REPORT_ENGINE", "api") == "agent":
        from . import report_agent  # 순환 import를 피해 여기서 부른다
        try:
            content, _ = report_agent.write(conn, ws)
        except LLMError as e:
            logging.warning("보고서 에이전트 실패, 기존 API로 대신 씀: %s", e)
    if content is None:
        content = llm.text(SYSTEM, json.dumps(build_week_input(conn, ws), ensure_ascii=False))
    conn.execute(
        "INSERT INTO reports(week_start, content, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(week_start) DO UPDATE SET content = excluded.content, created_at = excluded.created_at",
        (ws.isoformat(), content, datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return content


def last_full_week(today: date) -> date:
    """오늘 기준으로 이미 끝난 가장 최근 주의 월요일."""
    return week_start_of(today) - timedelta(days=7)


# 앱을 여러 탭에서 동시에 열어도 같은 주 보고서를 두 번 만들지 않게 한다
_auto_lock = threading.Lock()


def ensure_last_week(conn: sqlite3.Connection, llm, today: date) -> dict:
    """지난 주 보고서가 없으면 만든다. 결과 상태:
    exists(이미 있음) · no_ai(키 없음) · waiting_data(그 주 일요일까지 거래가 아직 안 올라옴)
    · no_spending(그 주 지출 없음) · created(새로 만듦) · failed(AI 호출 실패)"""
    ws = last_full_week(today)
    we = ws + timedelta(days=6)
    result = {"week_start": ws.isoformat()}
    with _auto_lock:
        if conn.execute("SELECT 1 FROM reports WHERE week_start = ?", (ws.isoformat(),)).fetchone():
            return {"status": "exists", **result}
        if llm is None:
            return {"status": "no_ai", **result}
        latest = conn.execute("SELECT MAX(date(occurred_at)) FROM transactions").fetchone()[0]
        if not latest or latest < we.isoformat():
            return {"status": "waiting_data", **result}
        if not service.period_summary(conn, ws, we)["gross"]:
            return {"status": "no_spending", **result}
        try:
            generate(conn, llm, ws)
        except LLMError as e:
            return {"status": "failed", "message": str(e), **result}
        return {"status": "created", **result}


def list_reports(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM reports ORDER BY week_start DESC")]
