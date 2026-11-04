"""성능검증용 정답지. 거래내역 PDF를 따로 둔 검증용 DB에 넣고, 사용자가 정답을 채울 엑셀을 만든다.

1) 정답지 만들기:  python -m app.agent.answer_sheet export "토스.pdf"
   → data/eval.db 에 거래를 넣고(앱과 똑같이 AI 분류·정산 제안까지), data/answer_sheet.xlsx 를 만든다.
2) 엑셀의 '정답' 칸을 채운다 (모르면 비워 둔다).
3) 정답 넣기:      python -m app.agent.answer_sheet load data/answer_sheet.xlsx
4) 채점:          python -m app.agent.evaluate --db data/eval.db --engine both

검증용 DB는 앱이 쓰는 data/app.db와 따로라서 실제 데이터는 건드리지 않는다.
"""
import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .. import categories as cats
from .. import db, service
from . import income
from .client import get_client

EVAL_DB = db.ROOT / "data" / "eval.db"
SHEET = db.ROOT / "data" / "answer_sheet.xlsx"
PAGE = db.ROOT / "data" / "정답_매기기.html"
WEEKDAYS = "월화수목금토일"
# 들어온 돈의 정답은 앱 카테고리와 따로(income.INCOME). 정산이면 어느 결제의 몫인지도 고른다.
INCOME_NAMES = set(income.NAMES)
PAY_BEFORE, PAY_AFTER, MAX_PAYS = income.PAY_BEFORE, income.PAY_AFTER, 8
COLUMNS = ["번호", "날짜", "시간", "이름", "금액", "종류", "정답", "메모"]
ANSWER_COL, MEMO_COL = COLUMNS.index("정답") + 1, COLUMNS.index("메모") + 1


def export(conn: sqlite3.Connection, out: Path) -> int:
    """나간 돈마다 한 줄. AI 추측은 넣지 않는다(미리 보면 판단이 흔들린다). 이미 고른 정답은 채워 둔다."""
    names = cats.names(conn)
    wb = Workbook()
    ws = wb.active
    ws.title = "정답지"
    ws.append(COLUMNS)
    rows = conn.execute("SELECT * FROM transactions WHERE direction = 'out' ORDER BY occurred_at").fetchall()
    for r in rows:
        day, time = r["occurred_at"][:10], r["occurred_at"][11:16]
        ws.append([r["id"], day, time, r["description"], r["amount"], r["kind"] or "",
                   r["category"] if r["reviewed"] else None, None])

    # 정답 칸은 목록에서 고르게 한다 (카테고리 이름 오타 방지)
    lists = wb.create_sheet("카테고리")
    for n in names:
        lists.append([n])
    rule = DataValidation(type="list", formula1=f"=카테고리!$A$1:$A${len(names)}", allow_blank=True,
                          showErrorMessage=True, error="목록에 있는 카테고리만 고를 수 있어요.")
    ws.add_data_validation(rule)
    rule.add(f"{ws.cell(2, ANSWER_COL).coordinate}:{ws.cell(len(rows) + 1, ANSWER_COL).coordinate}")

    # 참고용: 들어온 돈까지 모든 거래 (친구가 언제 보냈는지 떠올릴 때)
    ref = wb.create_sheet("참고_전체거래")
    ref.append(["날짜", "시간", "이름", "금액", "방향", "종류"])
    for r in conn.execute("SELECT * FROM transactions ORDER BY occurred_at"):
        ref.append([r["occurred_at"][:10], r["occurred_at"][11:16], r["description"], r["amount"],
                    "나감" if r["direction"] == "out" else "들어옴", r["kind"] or ""])

    for sheet, widths in ((ws, [7, 11, 7, 26, 10, 12, 10, 30]), (ref, [11, 7, 26, 10, 8, 12])):
        sheet.freeze_panes = "A2"
        for i, w in enumerate(widths):
            sheet.column_dimensions[chr(65 + i)].width = w
        for c in sheet[1]:
            c.font = Font(bold=True)
    for (c,) in ws.iter_rows(min_row=2, min_col=5, max_col=5):
        c.number_format = "#,##0"
    for c in (ws.cell(1, ANSWER_COL), ws.cell(1, MEMO_COL)):
        c.fill = PatternFill("solid", fgColor="FFF2CC")
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return len(rows)


def _preset(conn: sqlite3.Connection, app: sqlite3.Connection) -> dict:
    """앱에서 이미 고른 답을 미리 채운다: 직접 고른 카테고리, 확정한 정산(어느 결제의 몫인지까지).
    두 DB는 거래 id가 달라서 (시각, 이름, 금액, 방향)으로 맞춘다."""
    key = lambda r: (r["occurred_at"], r["description"], r["amount"], r["direction"])  # noqa: E731
    ids = {key(r): r["id"] for r in conn.execute("SELECT * FROM transactions")}
    app_ids = {r["id"]: ids.get(key(r)) for r in app.execute("SELECT * FROM transactions")}
    out: dict[int, dict] = {}
    for r in app.execute("SELECT * FROM transactions WHERE direction = 'out' AND reviewed = 1"):
        if app_ids.get(r["id"]):
            out[app_ids[r["id"]]] = {"category": r["category"]}
    for r in app.execute("SELECT incoming_id, payment_id FROM settlements WHERE status = 'confirmed'"):
        tid, pid = app_ids.get(r["incoming_id"]), app_ids.get(r["payment_id"])
        if tid:
            got = out.setdefault(tid, {"category": "정산", "pays": []})
            if pid:
                got["pays"].append(pid)
    return out


def page(conn: sqlite3.Connection, out: Path, prefill: sqlite3.Connection | None = None) -> int:
    """클릭으로 정답을 고르는 한 장짜리 HTML. 서버 없이 열리고, 고른 답은 정답.csv로 저장한다.
    실제 거래가 들어 있으니 data/ 밖으로(공유·업로드) 내보내지 않는다."""
    near_span = timedelta(hours=2)
    every = conn.execute("SELECT * FROM transactions ORDER BY occurred_at").fetchall()
    at = [datetime.fromisoformat(r["occurred_at"]) for r in every]
    when = lambda d: f"{d:%m.%d} ({WEEKDAYS[d.weekday()]}) {d:%H:%M}"  # noqa: E731
    rows = []
    for k, r in enumerate(every):
        is_in = r["direction"] == "in"
        near = [{"time": at[j].strftime("%H:%M"), "name": every[j]["description"], "amount": every[j]["amount"],
                 "in": every[j]["direction"] == "in"}
                for j in range(len(every)) if j != k and abs(at[j] - at[k]) <= near_span]
        row = {"id": r["id"], "in": is_in, "when": f"{at[k]:%Y.}{when(at[k])}", "name": r["description"],
               "amount": r["amount"], "kind": r["kind"] or "", "near": near}
        if is_in:
            # 정산이면 어느 결제의 몫인지: 받기 7일 전 ~ 1일 뒤의 결제 중 가까운 것
            pays = [j for j in range(len(every)) if every[j]["direction"] == "out"
                    and -PAY_AFTER <= at[k] - at[j] <= PAY_BEFORE]
            pays = sorted(sorted(pays, key=lambda j: abs(at[k] - at[j]))[:MAX_PAYS], key=lambda j: at[j])
            row["pays"] = [{"id": every[j]["id"], "when": when(at[j]), "name": every[j]["description"],
                            "amount": every[j]["amount"]} for j in pays]
        rows.append(row)
    built = datetime.now()
    # 만든 시각을 key에 넣어서, 페이지를 새로 만들면 이 브라우저에 저장된 이전 답은 쓰지 않고 처음부터 시작한다
    data = {"key": hashlib.sha1(f"{[r['id'] for r in rows]}{built.isoformat()}".encode()).hexdigest()[:10],
            "built": f"{built.month}월 {built.day}일 {built:%H:%M}",
            "categories": [{k: c[k] for k in ("name", "emoji", "description")} for c in cats.all_categories(conn)],
            "income": income.INCOME, "rows": rows, "preset": _preset(conn, prefill) if prefill else {}}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (Path(__file__).with_name("label_page.html")).read_text(encoding="utf-8").replace("/*DATA*/", blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return len(rows)


def _answer_rows(path: Path):
    """(번호, 정답, 정산결제, 메모) 목록. 엑셀 정답지와 클릭 화면이 저장한 정답.csv 둘 다 읽는다."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                yield row.get("번호"), row.get("정답"), row.get("정산결제") or "", row.get("메모") or ""
        return
    ws = load_workbook(path, read_only=True)["정답지"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row:
            yield row[0], row[ANSWER_COL - 1], "", row[MEMO_COL - 1] or ""


def load(conn: sqlite3.Connection, path: Path) -> dict:
    """채운 정답을 거래 하나씩 넣는다. 빈칸은 건너뛴다(채점에서 빠진다).
    나간 돈 → 거래의 '사용자가 고른 카테고리', 들어온 돈 → income_labels (정산이면 결제 id까지)."""
    names = set(cats.names(conn))
    direction = dict(conn.execute("SELECT id, direction FROM transactions"))
    loaded, got_income, blank, problems = 0, 0, 0, []
    for raw_id, raw_answer, raw_pays, memo in _answer_rows(path):
        if raw_id in (None, ""):
            continue
        txn_id, answer = int(raw_id), (str(raw_answer).strip() if raw_answer else "")
        if not answer:
            blank += 1
            continue
        if txn_id not in direction:
            problems.append(f"{txn_id}번: 검증용 DB에 없는 거래")
        elif direction[txn_id] == "out":
            if answer not in names:
                problems.append(f"{txn_id}번 '{answer}': 없는 카테고리")
                continue
            conn.execute("UPDATE transactions SET category = ?, reviewed = 1 WHERE id = ?", (answer, txn_id))
            loaded += 1
        elif answer not in INCOME_NAMES:
            problems.append(f"{txn_id}번 '{answer}': 들어온 돈 정답이 아님")
        else:
            pays = " ".join(p for p in str(raw_pays).split() if p.isdigit()) if answer == "정산" else ""
            conn.execute("INSERT OR REPLACE INTO income_labels(txn_id, label, payment_ids, memo) VALUES (?, ?, ?, ?)",
                         (txn_id, answer, pays, str(memo)))
            got_income += 1
    conn.commit()
    return {"loaded": loaded, "income": got_income, "blank": blank, "problems": problems}


def _app_conn(eval_db: Path) -> sqlite3.Connection | None:
    """앱 DB(앱에서 이미 고른 답을 미리 채우는 데 쓴다). 검증용 DB와 같거나 없으면 None."""
    app_db = db.ROOT / "data" / "app.db"
    return db.connect(app_db) if app_db.exists() and app_db.resolve() != eval_db.resolve() else None


def main() -> None:
    p = argparse.ArgumentParser(description="성능검증용 정답지 만들기·넣기")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="거래내역 파일을 검증용 DB에 넣고 정답지 엑셀을 만든다")
    e.add_argument("files", nargs="+", type=Path, help="토스 PDF/엑셀 (여러 개 가능)")
    e.add_argument("--password", help="PDF 비밀번호가 있을 때")
    e.add_argument("--out", type=Path, default=SHEET)
    e.add_argument("--no-ai", action="store_true", help="AI 없이 거래만 넣고 정답지를 만든다 (비용 0)")
    pg = sub.add_parser("page", help="검증용 DB의 거래로 클릭해서 고르는 화면(HTML)을 만든다")
    pg.add_argument("--out", type=Path, default=PAGE)
    pg.add_argument("--prefill", action="store_true", help="앱에서 이미 고른 답(카테고리·확정 정산)을 미리 채운다")
    lo = sub.add_parser("load", help="채운 정답지(엑셀) 또는 정답.csv를 검증용 DB에 넣는다")
    lo.add_argument("sheet", type=Path, nargs="?", default=SHEET)
    for s in (e, pg, lo):
        s.add_argument("--db", type=Path, default=EVAL_DB)
    args = p.parse_args()

    load_dotenv(db.ROOT / ".env")
    conn = db.connect(args.db)
    if args.cmd == "export":
        llm = None if args.no_ai else get_client()  # 앱과 같은 조건(가게 분류·정산 제안)을 만들려고 AI를 쓴다. 키가 없으면 AI 없이.
        for f in args.files:
            r = service.import_file(conn, f.name, f.read_bytes(), llm, args.password)
            print(f"{f.name}: {r['added']}건 추가, 중복 {r['duplicates']}건")
            for w in r.get("warnings", []):
                print("  -", w)
        if llm:
            print(f"AI 비용 약 ${llm.cost_usd:.3f}")
        n = export(conn, args.out)
        print(f"정답지: {args.out} (나간 돈 {n}건)")
        print(f"클릭 화면: {PAGE} ({page(conn, PAGE)}건)")
    elif args.cmd == "page":
        prefill = _app_conn(args.db) if args.prefill else None
        print(f"클릭 화면: {args.out} ({page(conn, args.out, prefill)}건)")
    else:
        r = load(conn, args.sheet)
        print(f"나간 돈 정답 {r['loaded']}건, 들어온 돈 정답 {r['income']}건 넣음, 빈칸 {r['blank']}건")
        for msg in r["problems"]:
            print("  !", msg)


if __name__ == "__main__":
    main()
