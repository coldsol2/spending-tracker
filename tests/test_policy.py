"""청년정책 추천: 내 정보로 거르고, 소득은 거르지 않고, 소비와 이어지는 정책을 앞에 둔다."""
from datetime import date

from fastapi.testclient import TestClient

from app import policy
from app.main import create_app
from conftest import FakeLLM

TODAY = date(2026, 11, 4)


def me(**kw):
    return {"birth_year": 2003, "region": "서울", "status": "대학생", "lives_alone": True, **kw}


def ids(r):
    return [i["id"] for i in r["items"]]


def test_filters_by_age_region_status_and_living_alone():
    r = policy.recommend(me(), {}, TODAY)
    assert r["age"] == 23
    got = set(ids(r))
    assert {"rent-national", "kpass", "climate-card", "national-scholarship"} <= got
    assert "job-support" not in got           # 취업준비만
    assert "gyeonggi-basic" not in got        # 경기만
    assert "culture-pass" not in got          # 2006~2007년생만
    assert [c["id"] for c in r["closed"]] == ["rent-seoul"]  # 올해 모집 끝남
    home = set(ids(policy.recommend(me(lives_alone=False), {}, TODAY)))
    assert "rent-national" not in home        # 자취하는 청년만


def test_income_is_shown_not_filtered_and_conflicts_noted():
    item = next(i for i in policy.recommend(me(), {}, TODAY)["items"] if i["id"] == "rent-national")
    assert item["income"] and "서울시 청년월세지원" in item["conflict_note"]


def test_spending_links_come_first():
    r = policy.recommend(me(), {"교통비": 120000}, TODAY)
    assert ids(r)[:2] == ["kpass", "climate-card"]
    assert r["items"][0]["spend_note"].startswith("이번 달 교통비 120,000원")


def test_profile_api(tmp_path):
    client = TestClient(create_app(tmp_path / "t.db", llm_factory=lambda: FakeLLM()))
    assert client.get("/api/policies?month=2026-10").json()["profile"] is None
    assert client.put("/api/policies/profile", json={**me(), "region": "화성"}).status_code == 400
    assert client.put("/api/policies/profile", json=me()).json()["region"] == "서울"
    body = client.get("/api/policies?month=2026-10").json()
    assert body["profile"]["status"] == "대학생" and body["items"]
