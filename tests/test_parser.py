import io
from datetime import datetime

import pytest
from openpyxl import Workbook

from app.parser import parse_amount, parse_file

TOSS_CSV = """거래 일시,적요,거래 유형,거래 기관,계좌번호,거래 금액,거래 후 잔액,메모
2026.10.03 19:20:11,고기굽는집,체크카드결제,,,-96000,904000,
2026.10.03 21:05:40,이민수,입금,토스뱅크,,24000,928000,
2026.10.04 09:00:00,이자,이자입금,,,"1,200",929200,
"""

SPLIT_CSV = """거래일자,거래시간,내용,출금액,입금액,잔액
2026-10-05,08:30,스타벅스,4800,0,"100,000"
2026-10-05,12:00,박지훈,0,"20,000","120,000"
"""


def test_parse_amount_formats():
    assert parse_amount("1,234원") == 1234
    assert parse_amount("-5,000") == -5000
    assert parse_amount("+3,000") == 3000
    assert parse_amount(96000.0) == 96000
    assert parse_amount("") == 0
    assert parse_amount(None) == 0


def test_signed_amount_with_type_column():
    txns = parse_file("toss.csv", TOSS_CSV.encode("utf-8-sig"))
    assert [(t.description, t.amount, t.direction) for t in txns] == [
        ("고기굽는집", 96000, "out"),
        ("이민수", 24000, "in"),
        ("이자", 1200, "in"),
    ]
    assert txns[0].occurred_at == datetime(2026, 10, 3, 19, 20, 11)
    assert txns[0].balance == 904000


def test_split_in_out_columns_and_cp949():
    txns = parse_file("bank.csv", SPLIT_CSV.encode("cp949"))
    assert [(t.description, t.amount, t.direction) for t in txns] == [
        ("스타벅스", 4800, "out"),
        ("박지훈", 20000, "in"),
    ]
    assert txns[0].occurred_at == datetime(2026, 10, 5, 8, 30)


def test_xlsx_with_notice_rows_above_header():
    wb = Workbook()
    ws = wb.active
    ws.append(["토스뱅크 거래내역서"])
    ws.append(["조회기간: 2026.10.01 ~ 2026.10.31"])
    ws.append([])
    ws.append(["거래 일시", "적요", "거래 금액", "거래 후 잔액"])
    ws.append([datetime(2026, 10, 7, 18, 0), "티머니", -1450, 98550])
    ws.append(["합계", "", -1450, ""])
    buf = io.BytesIO()
    wb.save(buf)
    txns = parse_file("toss.xlsx", buf.getvalue())
    assert len(txns) == 1
    assert (txns[0].description, txns[0].amount, txns[0].direction) == ("티머니", 1450, "out")


def test_same_file_gives_same_hashes_and_distinguishes_repeats():
    csv_text = "거래일시,적요,거래금액\n2026-10-01 10:00,편의점,-1000\n2026-10-01 10:00,편의점,-1000\n"
    a = parse_file("a.csv", csv_text.encode())
    b = parse_file("a.csv", csv_text.encode())
    assert [t.source_hash for t in a] == [t.source_hash for t in b]
    assert a[0].source_hash != a[1].source_hash


def test_unrecognized_columns_raise():
    with pytest.raises(ValueError, match="인식하지 못한 열"):
        parse_file("x.csv", "a,b,c\n1,2,3\n".encode())


def test_mapper_used_when_headers_unknown():
    csv_text = "when,what,how much\n2026-10-01 10:00,편의점,-1000\n"
    mapper = lambda rows: {"header_row": 0, "date": 0, "desc": 1, "amount": 2}
    txns = parse_file("x.csv", csv_text.encode(), mapper=mapper)
    assert (txns[0].description, txns[0].amount, txns[0].direction) == ("편의점", 1000, "out")


def test_rejects_other_file_types():
    with pytest.raises(ValueError, match="CSV"):
        parse_file("x.docx", b"PK")
