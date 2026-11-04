"""청년정책 추천 (발표 데모). 직접 조사한 정책 목록(policies.json)을 내 정보로 걸러서 보여준다.

- 나이·지역·상태(대학생/휴학생/취업준비/직장인)·자취 여부로만 거른다.
- 소득 조건은 알 수 없으니 거르지 않고 '소득 기준 확인'으로 보여준다.
- 이번 달 소비와 이어지는 정책(교통비 → K-패스 등)은 그 금액을 이유로 붙여 앞에 둔다.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

DATA = Path(__file__).with_name("policies.json")
REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
           "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
STATUSES = ["대학생", "휴학생", "취업준비", "직장인"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    birth_year INTEGER NOT NULL,
    region TEXT NOT NULL,
    status TEXT NOT NULL,
    lives_alone INTEGER NOT NULL
);
"""


def catalog() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def get_profile(conn: sqlite3.Connection) -> dict | None:
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT * FROM policy_profile WHERE id = 1").fetchone()
    if not row:
        return None
    return {"birth_year": row["birth_year"], "region": row["region"], "status": row["status"],
            "lives_alone": bool(row["lives_alone"])}


def set_profile(conn: sqlite3.Connection, birth_year: int, region: str, status: str, lives_alone: bool,
                today: date | None = None) -> dict:
    year = (today or date.today()).year
    if not 1950 <= birth_year <= year - 10:
        raise ValueError("태어난 해를 다시 확인해 주세요.")
    if region not in REGIONS:
        raise ValueError("사는 지역을 골라 주세요.")
    if status not in STATUSES:
        raise ValueError("지금 상태를 골라 주세요.")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO policy_profile(id, birth_year, region, status, lives_alone) VALUES (1, ?, ?, ?, ?) "
                 "ON CONFLICT(id) DO UPDATE SET birth_year = excluded.birth_year, region = excluded.region, "
                 "status = excluded.status, lives_alone = excluded.lives_alone",
                 (birth_year, region, status, int(lives_alone)))
    conn.commit()
    return get_profile(conn)


def recommend(profile: dict, spending: dict[str, int], today: date | None = None, month_label: str = "이번 달") -> dict:
    """반환: {as_of, note, sources, age, items: 받을 수 있는 정책, closed: 이번 모집이 끝난 정책}
    spending: 이번 달 카테고리별 실지출 (정책과 소비를 잇는 데 쓴다)"""
    data = catalog()
    age = (today or date.today()).year - profile["birth_year"]  # 만 나이는 생일에 따라 1살 적을 수 있다
    names = {p["id"]: p["name"] for p in data["policies"]}
    items, closed = [], []
    for p in data["policies"]:
        lo, hi = p["age"]
        if not lo <= age <= hi:
            continue
        if p["regions"] and profile["region"] not in p["regions"]:
            continue
        if p["statuses"] and profile["status"] not in p["statuses"]:
            continue
        if p["alone"] and not profile["lives_alone"]:
            continue
        why = [f"만 {age}세"]
        if p["regions"]:
            why.append(f"{profile['region']} 거주")
        if p["statuses"]:
            why.append(profile["status"])
        if p["alone"]:
            why.append("자취")
        spent = spending.get(p["spend"]["category"], 0) if p["spend"] else 0
        item = {**p, "reason": " · ".join(why) + " 조건이 맞아요",
                "spend_note": f"{month_label} {p['spend']['category']} {spent:,}원 — {p['spend']['hint']}" if spent else None,
                "conflict_note": ", ".join(names[c] for c in p["conflicts"]) + "와(과) 중복 신청은 안 돼요"
                if p["conflicts"] else None}
        (items if p["open"] else closed).append(item)
    # 소비와 이어지는 정책 먼저, 그다음 받을 수 있는 금액이 큰 순서
    items.sort(key=lambda i: (i["spend_note"] is None, -i["value"]))
    return {"as_of": data["as_of"], "note": data["note"], "sources": data["sources"], "age": age,
            "items": items, "closed": closed}
