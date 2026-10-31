"""테스트용 은행 거래내역서 PDF 생성기."""
from pathlib import Path

from fpdf import FPDF

FONT = Path("C:/Windows/Fonts/malgun.ttf")


def make_statement_pdf(rows: list[list[str]], password: str | None = None, borders: bool = True,
                       rows_per_page: int = 100) -> bytes:
    pdf = FPDF()
    pdf.add_font("kr", fname=str(FONT))
    pdf.set_font("kr", size=8)
    header, body = rows[0], rows[1:]
    for start in range(0, max(1, len(body)), rows_per_page):
        pdf.add_page()
        pdf.cell(0, 10, "토스뱅크 거래내역서", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, "조회기간 2026.10.01 ~ 2026.10.31", new_x="LMARGIN", new_y="NEXT")
        with pdf.table(borders_layout="ALL" if borders else "NONE", first_row_as_headings=False) as table:
            for r in [header] + body[start:start + rows_per_page]:
                row = table.row()
                for c in r:
                    row.cell(c)
    if password:
        pdf.set_encryption(owner_password=password + "-owner", user_password=password)
    return bytes(pdf.output())
