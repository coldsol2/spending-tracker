# 실지출 트래커 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 거래내역 파일을 업로드받아 Claude로 분류·더치페이 정산을 처리하고 실지출 대시보드와 주간 보고서를 제공하는 로컬 FastAPI 웹앱.

**Architecture:** 순수 로직(parser, settle, stats)과 AI 래퍼(agent/*), 저장소(db), HTTP(main)를 분리한다. 프론트는 FastAPI가 서빙하는 정적 HTML/JS + Chart.js(CDN).

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, pandas + openpyxl, sqlite3(표준), anthropic SDK, python-dotenv, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-10-30-spending-tracker-design.md`

## Global Constraints

- 금액은 원 단위 양의 정수(`int`), 방향은 `direction` = `'out'|'in'`.
- 카테고리 고정 목록: `["식비","카페","유흥","교통","쇼핑","구독","생활","의료","기타"]`.
- 정산 후보 창: 결제 시각 ≤ 입금 시각 ≤ 결제 시각 + 7일, 입금액 < 결제액.
- 정산 제외 키워드: `급여, 월급, 이자, 환불, 취소, 캐시백, 배당, 적금, 예금, 이체`(본인 계좌 이체).
- 실지출 = max(0, 결제액 − confirmed 정산 입금 합). pending은 미반영.
- 주간 예산 = 월 예산 ÷ 해당 월 일수 × 7. 주는 월~일.
- AI 실패 시 분류는 '기타', 매칭 제안 생략, 앱은 계속 동작.
- 모델: `claude-opus-5-5` (환경변수 `CLAUDE_MODEL`로 변경 가능).

## Review Focus

1. 같은 파일 재업로드 → 추가 0건, 중복 n건 (test_upload_idempotent).
2. 하나의 입금을 두 결제에 확정 시도 → 두 번째는 409 (test_confirm_incoming_twice_rejected).
3. 정산 합이 결제액 초과 → 실지출 0, 음수 아님 (test_net_spend_floor_zero).
4. 금액 문자열 "1,234원", "-5,000" 파싱 (test_parse_amount_formats).
5. ANTHROPIC_API_KEY 없음 → 업로드 성공, 카테고리 '기타', 경고 메시지 (test_upload_without_api_key).

---

### Task 1: 프로젝트 골격 + DB

**Files:** Create `requirements.txt`, `.env.example`, `app/__init__.py`, `app/db.py`, `tests/conftest.py`

**Interfaces — Produces:**
- `db.connect(path: str | None = None) -> sqlite3.Connection` (row_factory=Row, 스키마 생성, 기본 경로 `data/app.db`, 환경변수 `APP_DB`)
- 테이블: spec §4 그대로.

- [ ] conftest에 임시 DB fixture `conn` 작성 → `db.connect(tmp_path/"t.db")`
- [ ] 스키마 생성 테스트 후 구현, pytest 통과

### Task 2: parser

**Files:** Create `app/parser.py`, `tests/test_parser.py`

**Interfaces — Produces:**
- `@dataclass Txn(occurred_at: datetime, description: str, amount: int, direction: str, balance: int | None)`
- `parse_amount(v) -> int` (부호 유지)
- `parse_file(filename: str, data: bytes, mapper=None) -> list[Txn]` — `.csv`(utf-8-sig, cp949 fallback) / `.xlsx`. 헤더가 첫 행이 아니면 앞 20행 안에서 날짜·금액 키워드가 있는 행을 헤더로 탐색. 열 인식 실패 시 `mapper(headers, sample_rows) -> dict`(역할→열이름) 호출, 그래도 실패면 `ValueError("인식하지 못한 열: ...")`.
- `txn_hash(t: Txn) -> str`

**Tests:** 입출금 분리형 CSV, 부호형 CSV + 거래유형 열, XLSX 상단 안내문 몇 줄 있는 경우, test_parse_amount_formats, 인식 실패 시 ValueError.

### Task 3: settle + stats (순수 함수)

**Files:** Create `app/settle.py`, `app/stats.py`, tests

**Interfaces — Produces:**
- `settle.is_excluded(description: str) -> bool`
- `settle.find_candidates(payments: list[dict], incomings: list[dict], days=7) -> list[dict]` — 각 dict `{"incoming": inc, "payments": [pay...]}`, 후보 없는 입금 제외. dict 키: `id, occurred_at(datetime), description, amount`.
- `stats.net_by_payment(payments, confirmed: list[tuple[payment_id, amount]]) -> dict[id,int]`
- `stats.summarize(payments: list[dict(id, occurred_at, category, amount)], confirmed, pending, start: date, end: date) -> dict` → `{"total": int, "projected_total": int, "daily": {"YYYY-MM-DD": int}, "by_category": {cat:int}}` (end 포함)
- `stats.week_budget(monthly: int, week_start: date) -> int`

**Tests:** 7일 경계(7일 포함, 7일+1초 제외), 금액 조건, 제외 키워드, test_net_spend_floor_zero, pending 미반영·projected 반영, week_budget(300000, 2026-10-26)=67741.

### Task 4: agent

**Files:** Create `app/agent/__init__.py`, `client.py`, `categorize.py`, `match.py`, `report.py`, `tests/test_agent.py`

**Interfaces — Produces:**
- `client.get_client() -> LLM | None` (키 없으면 None). `LLM.json(system: str, user: str) -> dict|list` (응답에서 JSON 추출, 실패 시 1회 재시도), `LLM.text(system, user) -> str`.
- `categorize.categorize(conn, llm, merchants: list[str]) -> dict[str,str]` — 캐시 우선, 미분류만 한 번에 요청, 목록 밖 값은 '기타', 결과 캐시 저장. llm None이면 '기타'(캐시 저장 안 함).
- `match.propose(llm, candidates) -> list[dict(incoming_id, payment_id|None, reason)]` — 후보 밖 payment_id는 버림.
- `report.build_week_input(conn, week_start: date) -> dict`, `report.generate(conn, llm, week_start) -> str` (저장까지).
- `parser` 열 매핑용 `client.column_mapper(llm)` → mapper 함수.

**Tests:** FakeLLM으로 캐시 히트 시 호출 0회, 잘못된 카테고리 → '기타', 후보 밖 매칭 무시.

### Task 5: API

**Files:** Create `app/main.py`, `app/service.py`, `tests/test_api.py`

**Interfaces — Produces (JSON):**
- `POST /api/upload` (multipart file) → `{added, duplicates, candidates, warning|null}`
- `GET /api/summary?month=YYYY-MM` → summarize 결과 + `today`, `budgets`
- `GET /api/transactions?month=` / `PATCH /api/transactions/{id}` `{category}` (가맹점 캐시 갱신)
- `GET /api/settlements` → `{pending:[...], confirmed:[...]}` 결제·입금 정보 포함
- `POST /api/settlements/{id}/confirm|reject`, `POST /api/settlements` `{payment_id, incoming_id}` (수동, confirmed)
- `GET/PUT /api/budgets` `{category: amount}`
- `POST /api/reports` `{week_start}` → `{content}`; `GET /api/reports`
- `/` → static/index.html

**Tests:** 업로드→후보→확정→summary 반영, test_upload_idempotent, test_confirm_incoming_twice_rejected, test_upload_without_api_key.

### Task 6: 프론트엔드

**Files:** Create `static/index.html`, `static/app.js`, `static/style.css`

탭 6개(spec §6). Chart.js 4.4.1(cdnjs). 수동 브라우저 확인: 샘플 CSV 업로드 → 정산 확정 → 대시보드 숫자 변화.

### Task 7: 샘플 데이터 + README

`samples/sample_toss.csv`(더치페이 시나리오 포함), `README.md`(설치·실행·토스 내보내기 안내).
