"""FastAPI 앱. 실행: python -m uvicorn app.main:app --reload"""
from datetime import date

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, service
from .agent import report
from .agent.categorize import CATEGORIES
from .agent.client import LLMError, get_client

STATIC = db.ROOT / "static"


class CategoryIn(BaseModel):
    category: str
    scope: str | None = None  # 'one' | 'merchant' | None(자동)


class LinkIn(BaseModel):
    incoming_id: int
    payment_ids: list[int] = []  # 여러 결제에 나눠 연결
    payment_id: int | None = None  # 결제 하나 (예전 형식)


class ReportIn(BaseModel):
    week_start: date


def create_app(db_path=None, llm_factory=get_client) -> FastAPI:
    load_dotenv(db.ROOT / ".env")
    app = FastAPI(title="실지출 트래커")

    def get_conn():
        conn = db.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def guard(fn, *args):
        try:
            return fn(*args)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        except service.ConflictError as e:
            raise HTTPException(409, str(e))
        except LLMError as e:
            raise HTTPException(503, str(e))

    @app.get("/api/meta")
    def meta():
        return {"categories": CATEGORIES, "ai_enabled": llm_factory() is not None, "today": date.today().isoformat()}

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...), password: str | None = Form(None), conn=Depends(get_conn)):
        data = await file.read()
        return guard(service.import_file, conn, file.filename or "", data, llm_factory(), password or None)

    @app.get("/api/summary")
    def summary(month: str, conn=Depends(get_conn)):
        start, end = guard(service.month_range, month)
        s = service.period_summary(conn, start, end)
        today = date.today().isoformat()
        return {**s, "month": month, "today": s["daily"].get(today, 0), "budgets": service.get_budgets(conn)}

    @app.get("/api/transactions")
    def transactions(month: str, conn=Depends(get_conn)):
        return guard(service.list_transactions, conn, month)

    @app.patch("/api/transactions/{txn_id}")
    def update_transaction(txn_id: int, body: CategoryIn, conn=Depends(get_conn)):
        return guard(service.set_category, conn, txn_id, body.category, body.scope)

    @app.get("/api/review")
    def review(conn=Depends(get_conn)):
        return service.list_review(conn)

    @app.post("/api/recategorize")
    def recategorize(conn=Depends(get_conn)):
        return {"reset": guard(service.recategorize, conn, llm_factory())}

    @app.get("/api/settlements")
    def settlements(conn=Depends(get_conn)):
        return {**service.list_settlements(conn), "unlinked": service.unlinked_incomings(conn)}

    @app.post("/api/settlements")
    def link(body: LinkIn, conn=Depends(get_conn)):
        ids = body.payment_ids or ([body.payment_id] if body.payment_id else [])
        return {"id": guard(service.link_settlement, conn, ids, body.incoming_id)}

    @app.post("/api/settlements/{sid}/confirm")
    def confirm(sid: int, conn=Depends(get_conn)):
        guard(service.confirm_settlement, conn, sid)
        return {"ok": True}

    @app.post("/api/settlements/{sid}/reject")
    def reject(sid: int, conn=Depends(get_conn)):
        guard(service.reject_settlement, conn, sid)
        return {"ok": True}

    @app.get("/api/budgets")
    def budgets(conn=Depends(get_conn)):
        return service.get_budgets(conn)

    @app.put("/api/budgets")
    def put_budgets(body: dict[str, int], conn=Depends(get_conn)):
        guard(service.set_budgets, conn, body)
        return service.get_budgets(conn)

    @app.get("/api/week")
    def week(start: date, conn=Depends(get_conn)):
        return report.build_week_input(conn, start)

    @app.get("/api/reports")
    def reports(conn=Depends(get_conn)):
        return report.list_reports(conn)

    @app.post("/api/reports/auto")
    def auto_report(today: date | None = None, conn=Depends(get_conn)):
        return report.ensure_last_week(conn, llm_factory(), today or date.today())

    @app.post("/api/reports")
    def create_report(body: ReportIn, conn=Depends(get_conn)):
        return {"content": guard(report.generate, conn, llm_factory(), body.week_start)}

    @app.middleware("http")
    async def no_stale_static(request, call_next):
        # 앱을 고친 뒤 브라우저가 예전 화면 파일을 쓰지 않도록 매번 새로 확인하게 한다
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
