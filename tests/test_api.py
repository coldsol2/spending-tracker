import pytest
from fastapi.testclient import TestClient

from app.agent.categorize import CategoryResult, Item
from app.agent.match import Match, MatchResult
from app.main import create_app
from conftest import FakeLLM

CSV = """거래 일시,적요,거래 유형,거래 금액,거래 후 잔액
2026.10.03 19:20:00,고기굽는집,체크카드결제,-96000,904000
2026.10.03 21:05:00,이민수,입금,24000,928000
2026.10.04 10:12:00,박지훈,입금,24000,952000
2026.10.05 08:30:00,스타벅스,체크카드결제,-4800,947200
2026.10.10 09:00:00,(주)한빛 급여,입금,500000,1447200
""".encode("utf-8-sig")


def fake_llm():
    def categories(payload):
        return CategoryResult(items=[Item(merchant=m["name"], category="유흥" if "스타벅스" in m["name"] else "식비")
                                     for m in payload["merchants"]])

    def matches(cands):
        return MatchResult(matches=[Match(incoming_id=c["incoming"]["id"], payment_id=c["payments"][0]["id"],
                                          reason="결제 직후 입금") for c in cands])
    return FakeLLM({"CategoryResult": categories, "MatchResult": matches})


@pytest.fixture
def client(tmp_path):
    llm = fake_llm()
    return TestClient(create_app(tmp_path / "api.db", llm_factory=lambda: llm))


def upload(client, data=CSV):
    return client.post("/api/upload", files={"file": ("toss.csv", data, "text/csv")})


def test_upload_confirm_flow_updates_net_spend(client):
    r = upload(client).json()
    assert r == {"added": 5, "duplicates": 0, "proposals": 2, "warning": None}

    s = client.get("/api/summary?month=2026-10").json()
    assert s["gross"] == 100800
    assert s["total"] == 100800  # 아직 확정 전
    assert s["projected_total"] == 52800
    assert s["by_category"] == {"식비": 96000, "유흥": 4800}
    assert s["income"] == 548000

    pending = client.get("/api/settlements").json()["pending"]
    assert len(pending) == 2
    for p in pending:
        assert client.post(f"/api/settlements/{p['id']}/confirm").status_code == 200

    s = client.get("/api/summary?month=2026-10").json()
    assert s["total"] == 52800
    assert s["daily"]["2026-10-03"] == 48000
    assert s["income"] == 500000  # 정산 입금은 수입에서 빠진다


def test_upload_idempotent(client):
    upload(client)
    r = upload(client).json()
    assert (r["added"], r["duplicates"], r["proposals"]) == (0, 5, 0)


def test_confirm_incoming_twice_rejected(client):
    upload(client)
    settlement = client.get("/api/settlements").json()
    p = settlement["pending"][0]
    client.post(f"/api/settlements/{p['id']}/confirm")
    # 같은 입금을 다른 결제(스타벅스는 금액이 작아 후보가 아니지만 직접 연결은 가능)에 또 연결
    txns = client.get("/api/transactions?month=2026-10").json()
    starbucks = next(t for t in txns if t["description"] == "스타벅스")
    r = client.post("/api/settlements", json={"payment_id": starbucks["id"], "incoming_id": p["incoming"]["id"]})
    assert r.status_code == 409


def test_manual_link_and_category_change(client):
    upload(client)
    txns = client.get("/api/transactions?month=2026-10").json()
    starbucks = next(t for t in txns if t["description"] == "스타벅스")
    assert client.patch(f"/api/transactions/{starbucks['id']}", json={"category": "식비"}).status_code == 200
    assert client.patch(f"/api/transactions/{starbucks['id']}", json={"category": "없는것"}).status_code == 400
    s = client.get("/api/summary?month=2026-10").json()
    assert s["by_category"] == {"식비": 100800}


def test_upload_without_api_key(tmp_path):
    client = TestClient(create_app(tmp_path / "nokey.db", llm_factory=lambda: None))
    r = upload(client).json()
    assert r["added"] == 5 and r["proposals"] == 0
    assert "ANTHROPIC_API_KEY" in r["warning"]
    s = client.get("/api/summary?month=2026-10").json()
    assert s["by_category"] == {"기타": 100800}
    r = client.post("/api/reports", json={"week_start": "2026-09-28"})
    assert r.status_code == 503


def test_bad_file_returns_400(client):
    r = client.post("/api/upload", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert r.status_code == 400
    assert "인식하지 못한 열" in r.json()["detail"]


def test_budgets_roundtrip(client):
    assert client.put("/api/budgets", json={"식비": 300000, "유흥": 0}).json() == {"식비": 300000}
    assert client.put("/api/budgets", json={"없음": 1}).status_code == 400


def test_report_generation(client):
    upload(client)
    r = client.post("/api/reports", json={"week_start": "2026-09-28"})
    assert r.json() == {"content": "# 보고서"}
    assert client.get("/api/reports").json()[0]["week_start"] == "2026-09-28"
