"""정답지: 엑셀로 내보내고, 채운 정답을 거래 하나씩 다시 넣는다."""
from openpyxl import load_workbook

from app.agent import answer_sheet
from test_agent import add_out
from test_multi_settle import tid


def test_export_then_load(conn, tmp_path):
    add_out(conn, "토스페이", 4500, "2026-10-01 12:00:00", kind="체크카드결제", category="기타", h="a")
    add_out(conn, "토스페이", 9000, "2026-10-02 12:00:00", kind="체크카드결제", category="기타", h="b")
    add_out(conn, "GS25", 3000, "2026-10-03 09:00:00", category="편의점", h="c")
    path = tmp_path / "sheet.xlsx"
    assert answer_sheet.export(conn, path) == 3

    wb = load_workbook(path)
    ws = wb["정답지"]
    assert [c.value for c in ws[1]] == answer_sheet.COLUMNS
    assert all(ws.cell(r, answer_sheet.ANSWER_COL).value is None for r in (2, 3, 4))  # AI 분류는 안 보여준다
    assert ws.data_validations.dataValidation  # 정답 칸은 목록에서 고른다
    assert "참고_전체거래" in wb.sheetnames

    ws.cell(2, answer_sheet.ANSWER_COL).value = "식비"
    ws.cell(3, answer_sheet.ANSWER_COL).value = "없는것"
    wb.save(path)
    r = answer_sheet.load(conn, path)
    assert (r["loaded"], r["blank"], len(r["problems"])) == (1, 1, 1)
    a, b = (conn.execute("SELECT category, reviewed FROM transactions WHERE id = ?", (tid(conn, h),)).fetchone()
            for h in ("a", "b"))
    assert tuple(a) == ("식비", 1)  # 같은 이름의 다른 거래는 그대로 (거래 하나씩)
    assert tuple(b) == ("기타", 0)


def test_click_page_and_csv_answers(conn, tmp_path):
    add_out(conn, "토스페이", 4500, "2026-10-01 12:00:00", kind="체크카드결제", h="a")
    add_out(conn, "만화카페</script>", 8000, "2026-10-01 11:30:00", h="b")
    html = tmp_path / "p.html"
    assert answer_sheet.page(conn, html) == 2
    text = html.read_text(encoding="utf-8")
    assert "/*DATA*/" not in text and "만화카페<\\/script>" in text  # 이름 속 태그가 페이지를 깨지 않는다
    assert '"in": false' in text  # 앞뒤 거래가 단서로 들어간다

    answers = tmp_path / "정답.csv"
    answers.write_text(f"﻿번호,정답,메모\r\n{tid(conn, 'a')},\"유흥\",\"만화카페 직후\"\r\n", encoding="utf-8")
    assert answer_sheet.load(conn, answers)["loaded"] == 1
    row = conn.execute("SELECT category, reviewed FROM transactions WHERE id = ?", (tid(conn, "a"),)).fetchone()
    assert tuple(row) == ("유흥", 1)


def test_income_answers_with_settled_payments(conn, tmp_path):
    from test_guess import evening
    evening(conn)  # 나이스 결제 + 친구 입금
    nice = tid(conn, "nice")
    income = conn.execute("SELECT id FROM transactions WHERE direction = 'in' ORDER BY id").fetchone()["id"]
    html = tmp_path / "p.html"
    answer_sheet.page(conn, html)
    assert f'"id": {nice}' in html.read_text(encoding="utf-8")  # 정산 후보 결제로 보인다

    answers = tmp_path / "정답.csv"
    answers.write_text(f"번호,방향,정답,정산결제,메모\n{income},들어옴,정산,{nice} x,\n"
                       f"{nice},나감,데이트없음,,\n", encoding="utf-8")
    r = answer_sheet.load(conn, answers)
    assert (r["income"], r["loaded"], len(r["problems"])) == (1, 0, 1)
    label = conn.execute("SELECT label, payment_ids FROM income_labels WHERE txn_id = ?", (income,)).fetchone()
    assert tuple(label) == ("정산", str(nice))
