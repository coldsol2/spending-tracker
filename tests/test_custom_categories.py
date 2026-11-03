"""사용자 카테고리: 추가·이모지 바꾸기·삭제, AI가 새 카테고리를 쓰는지."""
import pytest
from fastapi.testclient import TestClient

from app import categories, service
from app.agent import categorize as cat
from app.agent import guess
from app.agent.categorize import CategoryResult, Item
from app.agent.guess import Guess, GuessResult
from app.main import create_app
from conftest import FakeLLM
from test_agent import add_out


def test_builtins_are_seeded_in_order(conn):
    names = categories.names(conn)
    assert names[:3] == ["식비", "편의점", "술"] and names[-3:] == ["송금", "기타", "제외"]
    assert len(names) == 11


def test_custom_category_sits_before_special_ones(conn):
    c = categories.add(conn, " 운동 ", "🏋️", "헬스장, 필라테스, 클라이밍")
    assert (c["name"], c["emoji"], c["builtin"], c["special"]) == ("운동", "🏋️", False, False)
    assert c["color"].startswith("#")
    assert categories.names(conn)[-4:] == ["운동", "송금", "기타", "제외"]
    assert "- 운동: 헬스장, 필라테스, 클라이밍" in categories.prompt_list(conn)


@pytest.mark.parametrize("name, emoji, desc, msg", [
    ("", "🏋️", "", "1~10글자"),
    ("열한글자가넘는긴이름이요", "🏋️", "", "1~10글자"),
    ("운동", "", "", "이모지"),
    ("식비", "🍙", "", "이미 있어요"),
    ("운동", "🏋️", "가" * 81, "80글자"),
])
def test_add_validation(conn, name, emoji, desc, msg):
    with pytest.raises(ValueError, match=msg):
        categories.add(conn, name, emoji, desc)


def test_builtin_emoji_can_change_but_not_name_description_or_existence(conn):
    categories.update(conn, "식비", emoji="🍙")
    assert next(c for c in categories.all_categories(conn) if c["name"] == "식비")["emoji"] == "🍙"
    with pytest.raises(ValueError, match="설명"):
        categories.update(conn, "식비", description="밥")
    with pytest.raises(ValueError, match="지울 수 없어요"):
        categories.remove(conn, "기타")
    with pytest.raises(LookupError):
        categories.update(conn, "없는것", emoji="🙂")


def test_remove_moves_transactions_back_to_review(conn):
    categories.add(conn, "운동", "🏋️", "헬스장")
    add_out(conn, "헬스장", 50000, "2026-10-10 19:00:00", h="gym")
    gym = conn.execute("SELECT id FROM transactions WHERE source_hash = 'gym'").fetchone()["id"]
    service.set_category(conn, gym, "운동")
    service.set_budgets(conn, {"운동": 60000})
    assert categories.remove(conn, "운동") == 1
    row = conn.execute("SELECT category, reviewed FROM transactions WHERE id = ?", (gym,)).fetchone()
    assert (row["category"], row["reviewed"]) == ("기타", 0)
    assert service.get_budgets(conn) == {}
    assert cat.cached(conn, "헬스장") is None
    with pytest.raises(ValueError, match="알 수 없는 카테고리"):
        service.set_category(conn, gym, "운동")


def test_ai_gets_custom_category_in_prompt_and_schema(conn):
    categories.add(conn, "운동", "🏋️", "헬스장, 필라테스")
    add_out(conn, "스포애니 강남점", 69000, "2026-10-10 19:00:00", h="gym")
    seen = {}

    class Spy(FakeLLM):
        def parse(self, system, user, schema):
            seen["system"], seen["schema"] = system, schema
            return super().parse(system, user, schema)

    llm = Spy({"CategoryResult": lambda p: CategoryResult(items=[Item(merchant="스포애니 강남점", category="운동")])})
    assert cat.categorize(conn, llm, ["스포애니 강남점"]) == {"스포애니 강남점": "운동"}
    assert "- 운동: 헬스장, 필라테스" in seen["system"]
    # 응답 형식이 지금 있는 카테고리만 받는다
    schema = seen["schema"].model_json_schema()
    assert "운동" in str(schema) and "없는카테고리" not in str(schema)
    with pytest.raises(Exception):
        seen["schema"].model_validate({"items": [{"merchant": "x", "category": "없는카테고리"}]})


def test_guess_falls_back_when_category_was_deleted(conn):
    add_out(conn, "카카오페이", 10000, "2026-10-16 17:44:00", kind="펌뱅킹출금", category="기타", h="kp")
    kp = conn.execute("SELECT id FROM transactions WHERE source_hash = 'kp'").fetchone()["id"]
    llm = FakeLLM({"GuessResult": lambda p: GuessResult(guesses=[
        Guess(txn_id=kp, category="지운카테고리", confidence="high", reason="x")])})
    assert guess.guess(conn, llm, [kp])[kp]["category"] == "기타"


def test_category_api(tmp_path):
    client = TestClient(create_app(tmp_path / "c.db", llm_factory=lambda: None))
    r = client.post("/api/categories", json={"name": "운동", "emoji": "🏋️", "description": "헬스장"})
    assert r.status_code == 200 and r.json()["name"] == "운동"
    assert client.post("/api/categories", json={"name": "운동", "emoji": "🏋️"}).status_code == 400
    meta = client.get("/api/meta").json()
    assert "운동" in meta["categories"] and any(c["name"] == "운동" for c in meta["category_info"])
    assert client.patch("/api/categories/운동", json={"emoji": "🤸"}).status_code == 200
    assert client.delete("/api/categories/식비").status_code == 400
    assert client.delete("/api/categories/운동").json() == {"moved": 0}
    assert client.delete("/api/categories/운동").status_code == 404
