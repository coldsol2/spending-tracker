from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.agent.extract import Extracted, Row, extractor
from app.main import create_app
from app.parser import parse_file
from app.pdf_reader import parse_text_lines
from conftest import FakeLLM
from pdf_util import FONT, make_statement_pdf

pytestmark = pytest.mark.skipif(not FONT.exists(), reason="한글 글꼴(맑은 고딕)이 없음")

ROWS = [
    ["거래 일시", "적요", "거래 유형", "거래 금액", "거래 후 잔액"],
    ["2026.10.03 19:20:11", "고기굽는집 강남점", "체크카드결제", "-96,000", "904,000"],
    ["2026.10.03 21:05:40", "이민수", "입금", "24,000", "928,000"],
    ["2026.10.04 10:12:03", "박지훈", "입금", "24,000", "952,000"],
]
EXPECTED = [("고기굽는집 강남점", 96000, "out"), ("이민수", 24000, "in"), ("박지훈", 24000, "in")]


def simple(txns):
    return [(t.description, t.amount, t.direction) for t in txns]


def test_bordered_table_across_pages_with_password():
    data = make_statement_pdf(ROWS, password="900101", rows_per_page=2)
    txns = parse_file("toss.pdf", data, password="900101")
    assert simple(txns) == EXPECTED
    assert txns[0].occurred_at == datetime(2026, 10, 3, 19, 20, 11)
    assert txns[0].balance == 904000


def test_password_missing_or_wrong():
    data = make_statement_pdf(ROWS, password="900101")
    with pytest.raises(ValueError, match="비밀번호가 걸린 PDF"):
        parse_file("toss.pdf", data)
    with pytest.raises(ValueError, match="비밀번호가 틀렸어요"):
        parse_file("toss.pdf", data, password="000000")


def test_borderless_table_read_from_text_lines():
    txns = parse_file("toss.pdf", make_statement_pdf(ROWS, borders=False))
    assert simple(txns) == EXPECTED


def test_text_lines_name_before_amount():
    lines = [
        "토스뱅크 거래내역서",
        "2026.10.25 00:00:01 토스뱅크 이자 이자입금 1,820 2,140,320",
        "2026.10.30 08:45:00 스타벅스 판교역 체크카드결제 -5,300 2,059,620",
    ]
    assert simple(parse_text_lines(lines)) == [("토스뱅크 이자", 1820, "in"), ("스타벅스 판교역", 5300, "out")]


def test_text_lines_unsigned_amounts_use_type_words():
    lines = ["2026-10-14 SKT 통신요금 자동이체 65,000", "2026-10-15 이민수 입금 20,000"]
    assert simple(parse_text_lines(lines)) == [("SKT 통신요금", 65000, "out"), ("이민수", 20000, "in")]


# 토스뱅크 거래내역서 PDF에서 뽑힌 텍스트와 같은 모양 (이름·가게·잔액은 모두 가짜)
TOSS_TEXT = """거래내역서
조회기간 2026년 09월 30일 ~ 2026년 10월 30일
단위: 원
거래일자 구분 거래금액 거래 후 잔액 거래내용
2026-10-29 23:15:48 입금 8,000 50,000 이민수
2026-10-29 19:55:36 체크카드결제 -2,500 42,000 이마트24 R행복캠퍼스점
2026-10-29 17:56:56 캐시백 100 44,500 카드 캐시백
스트리밍서비스_정기결제
2026-10-26 20:12:19 체크카드결제 -3,000 44,400
(3)_이
해피치킨(Happy
2026-10-24 00:34:30 체크카드결제 26,000 47,400
Chicken)
해피치킨(Happy
2026-10-24 00:33:48 체크카드결제 -26,000 21,400
Chicken)
2026-10-24 00:30:52 입금 50,000 47,400 비상금
11 // 99
보드게임카페 무지개 행복
2026-10-02 15:39:22 체크카드결제 -7,000 100,000
역점
2026-10-01 09:00:00 이자입금 12 107,000 이자"""


def test_toss_layout_with_wrapped_names():
    txns = parse_text_lines(TOSS_TEXT.splitlines())
    assert [(t.description, t.amount, t.direction, t.kind) for t in txns] == [
        ("이민수", 8000, "in", "입금"),
        ("이마트24 R행복캠퍼스점", 2500, "out", "체크카드결제"),
        ("카드 캐시백", 100, "in", "캐시백"),
        ("스트리밍서비스_정기결제(3)_이", 3000, "out", "체크카드결제"),
        ("해피치킨(Happy Chicken)", 26000, "in", "체크카드결제"),  # 결제 취소
        ("해피치킨(Happy Chicken)", 26000, "out", "체크카드결제"),
        ("비상금", 50000, "in", "입금"),
        ("보드게임카페 무지개 행복역점", 7000, "out", "체크카드결제"),
        ("이자", 12, "in", "이자입금"),
    ]
    assert txns[1].balance == 42000
    assert txns[0].occurred_at == datetime(2026, 10, 29, 23, 15, 48)


def test_ai_fallback_when_layout_unknown():
    # 금액이 줄 앞에 있어 규칙으로는 못 읽는 배치
    rows = [["금액", "내용", "날짜"], ["-96,000", "고기굽는집", "2026.10.03"]]
    data = make_statement_pdf(rows, borders=False)
    with pytest.raises(ValueError, match="AI가 대신"):
        parse_file("odd.pdf", data)

    seen = {}

    def handle(payload):
        seen["text"] = payload["text"]
        return Extracted(transactions=[Row(occurred_at="2026-10-03", description="고기굽는집",
                                           amount=96000, direction="out", balance=None)])
    llm = FakeLLM({"Extracted": handle})
    txns = parse_file("odd.pdf", data, ai_extract=extractor(llm))
    assert simple(txns) == [("고기굽는집", 96000, "out")]
    assert "고기굽는집" in seen["text"]


def test_upload_pdf_with_password_via_api(tmp_path):
    client = TestClient(create_app(tmp_path / "pdf.db", llm_factory=lambda: None))
    data = make_statement_pdf(ROWS, password="900101")
    files = {"file": ("toss.pdf", data, "application/pdf")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 400 and "비밀번호" in r.json()["detail"]
    r = client.post("/api/upload", files=files, data={"password": "900101"})
    assert r.status_code == 200 and r.json()["added"] == 3
