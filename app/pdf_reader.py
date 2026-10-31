"""은행 거래내역서 PDF 읽기.

1) PDF 안의 표를 행 목록으로 뽑아 일반 파서(열 자동 인식)에 넘긴다.
2) 표가 없으면(테두리 없는 표) 날짜로 시작하는 텍스트 줄을 직접 해석한다.
3) 그래도 안 되면 PDF 텍스트를 AI 추출기에 맡긴다.
"""
import io
import re
from typing import Callable

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

from .parser import IN_TYPE_WORDS, Txn, detect_columns, parse_amount, parse_datetime

OUT_TYPE_WORDS = ["결제", "출금", "지출", "자동이체"]
LINE_RE = re.compile(r"^(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\.?\s+(?:(\d{1,2}:\d{2}(?::\d{2})?)\s+)?(.+)$")
NUMBER_RE = re.compile(r"^[-+]?\d{1,3}(?:,\d{3})+(?:원)?$|^[-+]?\d+(?:원)?$")

RowsToTxns = Callable[[list[list[str]]], list[Txn]]
AiExtract = Callable[[str], list[Txn]]


def _is_password_error(e: Exception) -> bool:
    while e is not None:
        if isinstance(e, PDFPasswordIncorrect):
            return True
        e = e.__cause__ or e.__context__ or (e.args[0] if e.args and isinstance(e.args[0], Exception) else None)
    return False


def read_pdf(data: bytes, password: str | None) -> tuple[list[list[str]], str]:
    """(표 행 목록, 전체 텍스트)를 돌려준다."""
    try:
        with pdfplumber.open(io.BytesIO(data), password=password or "") as pdf:
            rows: list[list[str]] = []
            texts: list[str] = []
            for page in pdf.pages:
                for table in page.extract_tables():
                    rows.extend([re.sub(r"\s*\n\s*", " ", c or "").strip() for c in r] for r in table)
                texts.append(page.extract_text() or "")
    except Exception as e:
        if _is_password_error(e):
            if password:
                raise ValueError("PDF 비밀번호가 틀렸어요.") from e
            raise ValueError("비밀번호가 걸린 PDF예요. 업로드할 때 PDF 비밀번호(보통 생년월일 6자리)를 입력해 주세요.") from e
        raise ValueError("PDF를 열 수 없어요. 파일이 손상됐는지 확인해 주세요.") from e
    return rows, "\n".join(texts)


def _is_type_word(token: str) -> bool:
    return any(w in token for w in IN_TYPE_WORDS + OUT_TYPE_WORDS + ["캐시백", "오픈뱅킹"])


def _join_wrapped(before: str, after: str) -> str:
    """줄바꿈으로 잘린 이름을 잇는다. 영문/숫자끼리 만날 때만 띄어 쓴다."""
    if not before or not after:
        return before or after
    gap = " " if before[-1].isascii() and before[-1].isalnum() and after[0].isascii() and after[0].isalnum() else ""
    return before + gap + after


def _split_line(rest: str) -> tuple[str, str, int, int | None] | None:
    """날짜 뒤 부분을 (구분, 이름, 부호 있는 금액, 잔액)으로 나눈다.

    처음 나오는 숫자가 금액, 바로 다음 숫자가 잔액이다. 숫자 뒤에 글자가 있으면
    (토스: '입금 8,000 12,345 이민수') 앞은 구분, 뒤는 이름이고, 없으면
    ('고기집 체크카드결제 -96,000 904,000') 앞 글자에서 구분 단어를 뺀 것이 이름이다.
    """
    tokens = rest.split()
    k = next((i for i, t in enumerate(tokens) if NUMBER_RE.match(t)), None)
    if k is None:
        return None
    end = k + 2 if k + 1 < len(tokens) and NUMBER_RE.match(tokens[k + 1]) else k + 1
    before, after = tokens[:k], tokens[end:]
    balance = parse_amount(tokens[k + 1]) if end == k + 2 else None
    if after:
        kind, desc = " ".join(before), " ".join(after)
    else:
        kind = " ".join(t for t in before if _is_type_word(t))
        desc = " ".join(t for t in before if not _is_type_word(t))
    return kind, desc, parse_amount(tokens[k]), balance


PAGE_NUMBER_RE = re.compile(r"^\d+\s*/+\s*\d+$")


def parse_text_lines(lines: list[str]) -> list[Txn]:
    """날짜로 시작하는 줄을 거래로 읽는다. 이름이 길어 줄이 바뀐 경우 PDF 텍스트에서는
    이름이 날짜 줄의 바로 위·아래 줄로 갈라지므로, 이름이 빈 거래는 이웃 줄을 이어 붙인다."""
    lines = [l.strip() for l in lines]
    parsed = []  # (줄 번호, when, kind, desc, signed, balance)
    for i, line in enumerate(lines):
        m = LINE_RE.match(line)
        when = parse_datetime(m.group(1), m.group(2) or "") if m else None
        split = _split_line(m.group(3)) if when else None
        if split and split[2]:
            parsed.append((i, when, *split))
    dated = {p[0] for p in parsed}

    def neighbor(j: int) -> str:
        if not (0 <= j < len(lines)) or j in dated or not lines[j]:
            return ""
        line = lines[j]
        roles = detect_columns(line.split())
        is_header = "date" in roles and ("amount" in roles or "balance" in roles)
        if PAGE_NUMBER_RE.match(line) or LINE_RE.match(line) or is_header:
            return ""
        return line

    # 출금이 음수로 적힌 문서면 부호로만 방향을 정한다 (양수 '체크카드결제' = 결제 취소)
    signed_format = any(p[4] < 0 for p in parsed)
    txns = []
    for i, when, kind, desc, signed, balance in parsed:
        if not desc:
            desc = _join_wrapped(neighbor(i - 1), neighbor(i + 1)) or kind or "(내용 없음)"
        if signed < 0:
            direction = "out"
        elif signed_format:
            direction = "in"
        else:
            direction = "out" if any(w in f"{kind} {desc}" for w in OUT_TYPE_WORDS) else "in"
        txns.append(Txn(when, desc, abs(signed), direction, balance, kind=kind))
    return txns


def parse_pdf(data: bytes, password: str | None, rows_to_txns: RowsToTxns,
              ai_extract: AiExtract | None = None) -> list[Txn]:
    rows, text = read_pdf(data, password)
    if rows:
        try:
            return rows_to_txns(rows)
        except ValueError:
            pass
    txns = parse_text_lines(text.splitlines())
    if txns:
        return txns
    if not text.strip():
        raise ValueError("PDF에서 글자를 읽을 수 없어요. 스캔한 이미지 PDF일 수 있어요.")
    if ai_extract is not None:
        return ai_extract(text)
    raise ValueError("PDF에서 거래 표를 찾지 못했어요. API 키를 설정하면 AI가 대신 읽어볼 수 있어요.")
