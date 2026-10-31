"""거래내역 파일(PDF/CSV/XLSX)을 표준 거래 목록으로 바꾼다."""
import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

# 역할별 열 이름 키워드. 순서가 중요하다: '입금액'이 '금액'으로 잡히지 않도록
# 입금/출금/잔액/유형을 금액보다 먼저 찾는다.
ROLES = [
    ("date", ["거래일시", "거래일자", "일시", "일자", "날짜", "거래일", "date"]),
    ("time", ["거래시간", "시간", "시각", "time"]),
    ("balance", ["잔액", "balance"]),
    ("type", ["거래유형", "입출금구분", "구분", "유형", "type"]),
    ("in", ["입금액", "입금", "받은금액", "deposit"]),
    ("out", ["출금액", "출금", "지출", "보낸금액", "withdrawal"]),
    ("amount", ["거래금액", "금액", "amount"]),
    ("desc", ["적요", "거래내용", "내용", "가맹점", "거래처", "받는분", "보낸분", "메모", "description"]),
]
IN_TYPE_WORDS = ["입금", "수입", "받기", "받은"]
HEADER_SCAN_ROWS = 20

# mapper(rows) -> {"header_row": int, "date": int, ...} 역할→열 번호
Mapper = Callable[[list[list[str]]], dict]


@dataclass
class Txn:
    occurred_at: datetime
    description: str
    amount: int
    direction: str  # 'out' | 'in'
    balance: int | None = None
    source_hash: str = ""
    kind: str = ""  # 은행이 적은 거래 유형(체크카드결제, 입금 등). 결제 취소 판별에 쓴다


def parse_amount(value) -> int:
    if value is None:
        return 0
    s = re.sub(r"[,\s원+]", "", str(value))
    if s in ("", "-", "nan", "None"):
        return 0
    return int(round(float(s)))


def parse_datetime(date_value: str, time_value: str = "") -> datetime | None:
    s = re.sub(r"[./]", "-", str(date_value).strip()).rstrip("-")
    s = re.sub(r"\s+", " ", s)
    if time_value and ":" not in s:
        s = f"{s} {str(time_value).strip()}"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def detect_columns(row: list[str]) -> dict[str, int]:
    headers = [re.sub(r"\s+", "", str(c)).lower() for c in row]
    roles: dict[str, int] = {}
    used: set[int] = set()
    for role, keywords in ROLES:
        for i, h in enumerate(headers):
            if i not in used and h and any(k in h for k in keywords):
                roles[role] = i
                used.add(i)
                break
    return roles


def _is_header(roles: dict[str, int]) -> bool:
    return "date" in roles and any(r in roles for r in ("amount", "in", "out"))


def read_rows(filename: str, data: bytes) -> list[list[str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        return [
            ["" if v is None else (v.isoformat(sep=" ") if isinstance(v, datetime) else str(v)) for v in row]
            for row in ws.iter_rows(values_only=True)
        ]
    if filename.lower().endswith(".csv"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp949")
        return [row for row in csv.reader(io.StringIO(text))]
    raise ValueError("PDF, 엑셀(.xlsx), CSV 파일만 올릴 수 있어요.")


def _find_layout(rows: list[list[str]], mapper: Mapper | None) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        roles = detect_columns(row)
        if _is_header(roles):
            return i, roles
    if mapper is not None:
        try:
            mapped = mapper(rows[:HEADER_SCAN_ROWS])
        except Exception:
            mapped = {}  # AI도 못 찾으면 아래의 일반 오류로
        header_row = mapped.pop("header_row", None)
        roles = {k: v for k, v in mapped.items() if isinstance(v, int)}
        if isinstance(header_row, int) and _is_header(roles):
            return header_row, roles
    found = detect_columns(rows[0]) if rows else {}
    missing = [label for role, label in [("date", "거래일시"), ("amount", "거래금액")] if role not in found]
    raise ValueError(f"인식하지 못한 열: {', '.join(missing)}. 거래일시와 금액 열이 있는 파일인지 확인해 주세요.")


def _cell(row: list[str], roles: dict[str, int], role: str) -> str:
    i = roles.get(role)
    return row[i] if i is not None and i < len(row) else ""


def _direction(row, roles, signed_amount: int, signed_format: bool) -> tuple[str, int]:
    if "in" in roles or "out" in roles:
        inc, out = parse_amount(_cell(row, roles, "in")), parse_amount(_cell(row, roles, "out"))
        return ("in", abs(inc)) if inc else ("out", abs(out))
    if signed_amount < 0:
        return "out", -signed_amount
    if signed_format:
        # 출금이 음수로 적히는 파일이면 양수는 모두 들어온 돈이다 (양수 '체크카드결제' = 결제 취소)
        return "in", signed_amount
    kind = _cell(row, roles, "type")
    if kind:
        return ("in" if any(w in kind for w in IN_TYPE_WORDS) else "out"), signed_amount
    return "in", signed_amount


def txn_key(t: Txn) -> str:
    return f"{t.occurred_at.isoformat()}|{t.description}|{t.amount}|{t.direction}|{t.balance}"


def parse_file(filename: str, data: bytes, mapper: Mapper | None = None,
               password: str | None = None, ai_extract=None) -> list[Txn]:
    if filename.lower().endswith(".pdf"):
        from .pdf_reader import parse_pdf

        txns = parse_pdf(data, password, lambda rows: rows_to_txns(rows, mapper), ai_extract)
    else:
        txns = rows_to_txns(read_rows(filename, data), mapper)

    # 같은 파일 안에서 완전히 똑같은 거래가 여러 번 있으면 순번을 붙여 구분한다.
    # 같은 파일을 다시 올리면 같은 해시가 나와 중복으로 걸러진다.
    seen: Counter[str] = Counter()
    for t in txns:
        key = txn_key(t)
        seen[key] += 1
        t.source_hash = hashlib.sha1(f"{key}#{seen[key]}".encode()).hexdigest()
    return txns


def rows_to_txns(rows: list[list[str]], mapper: Mapper | None = None) -> list[Txn]:
    header_row, roles = _find_layout(rows, mapper)
    body = rows[header_row + 1:]
    signed_format = any(_cell(r, roles, "amount").strip().startswith("-") for r in body)
    txns: list[Txn] = []
    for row in body:
        when = parse_datetime(_cell(row, roles, "date"), _cell(row, roles, "time"))
        if when is None:
            continue  # 빈 줄, 합계 줄 등
        try:
            direction, amount = _direction(row, roles, parse_amount(_cell(row, roles, "amount")), signed_format)
            balance_text = _cell(row, roles, "balance")
            balance = parse_amount(balance_text) if balance_text.strip() else None
        except ValueError:
            continue
        if amount == 0:
            continue
        desc = _cell(row, roles, "desc").strip() or "(내용 없음)"
        txns.append(Txn(when, desc, amount, direction, balance, kind=_cell(row, roles, "type").strip()))
    return txns
