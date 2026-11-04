"""거래 단위 추측: 앞뒤 거래·친구 정산·사용자 예시를 보고 페이 결제 같은 거래를 하나씩 추리한다."""
from app import service
from app.agent import categorize as cat
from app.agent import guess
from app.agent.guess import Guess, GuessResult
from conftest import FakeLLM
from test_agent import add_out
from test_multi_settle import add_in, tid


def evening(conn):
    """만화카페 결제 10분 뒤 카카오페이, 친구가 정산한 술자리 결제, 단서 없는 토스페이."""
    add_out(conn, "만화카페", 21000, "2026-10-16 17:34:00", category="유흥", h="cafe")
    add_out(conn, "카카오페이", 10000, "2026-10-16 17:44:00", kind="펌뱅킹출금", category="기타", h="kp")
    add_out(conn, "대표일반_나이스", 87640, "2026-10-21 20:58:00", category="기타", h="nice")
    add_in(conn, "이민수", 29000, "2026-10-21 23:00:00", h="back")
    add_out(conn, "토스페이", 7400, "2026-10-25 03:10:00", kind="오픈뱅킹", category="기타", h="tp")
    for name in ("카카오페이", "대표일반_나이스", "토스페이"):
        cat.remember(conn, name, "기타", source="ai", confident=False, varies=True)
    service.link_settlement(conn, [tid(conn, "nice")], tid(conn, "back"))
    conn.commit()


def test_payload_has_context_but_not_the_answer(conn):
    evening(conn)
    seen = {}

    def handle(payload):
        seen.update(payload)
        return GuessResult(guesses=[])
    guess.guess(conn, FakeLLM({"GuessResult": handle}), [tid(conn, "kp"), tid(conn, "nice")])
    kp, nice = sorted(seen["targets"], key=lambda t: t["amount"])
    assert kp["time"] == "2026-10-16 17:44 (금)"
    assert kp["nearby"] == [{"time": "17:34", "name": "만화카페", "amount": 21000, "category": "유흥"}]
    assert nice["paid_back"] == [{"name": "이민수", "amount": 29000}]
    assert "category" not in kp  # 지금 카테고리(정답 후보)는 보여주지 않는다


def test_apply_sets_category_unless_low_confidence(conn):
    evening(conn)
    llm = FakeLLM({"GuessResult": lambda p: GuessResult(guesses=[
        Guess(txn_id=t["txn_id"], category={"카카오페이": "유흥", "대표일반_나이스": "술", "토스페이": "편의점"}[t["name"]],
              confidence={"카카오페이": "high", "대표일반_나이스": "medium", "토스페이": "low"}[t["name"]],
              reason="이유") for t in p["targets"]])})
    assert service.guess_pending(conn, llm) == 3
    cats = {r["source_hash"]: (r["category"], r["ai_guess"], r["reviewed"])
            for r in conn.execute("SELECT * FROM transactions WHERE direction = 'out'")}
    assert cats["kp"] == ("유흥", "유흥", 0)
    assert cats["nice"] == ("술", "술", 0)
    assert cats["tp"] == ("기타", "편의점", 0)  # 단서 부족: 카테고리는 그대로, 추측만 보여준다
    # 아직 사용자가 확인하지 않았으니 분류 확인 목록에 남는다
    assert {t["source_hash"] for t in service.list_review(conn)} == {"kp", "nice", "tp"}
    # 이미 추측한 거래는 다시 묻지 않는다
    assert service.guess_pending(conn, FakeLLM()) == 0


def test_user_choices_become_examples_and_can_be_hidden(conn):
    evening(conn)
    add_out(conn, "카카오페이", 12000, "2026-10-01 23:10:00", kind="펌뱅킹출금", h="kp-old")
    add_out(conn, "GS25", 3000, "2026-10-02 10:00:00", category="편의점", h="g1")
    add_out(conn, "GS25", 2000, "2026-10-03 10:00:00", category="편의점", h="g2")
    service.set_category(conn, tid(conn, "kp-old"), "술")      # 페이: 이 거래만
    service.set_category(conn, tid(conn, "g1"), "편의점")       # 가게: 같은 이름 전체
    ex = guess.examples(conn)
    assert [(e["name"], e["category"]) for e in ex] == [("GS25", "편의점"), ("카카오페이", "술")]
    assert ex[1]["time"] == "2026-10-01 23:10 (목)" and ex[1]["amount"] == 12000
    # 정확도를 잴 때: 페이 거래는 그 거래만, 가게는 같은 이름 전체를 숨긴다
    assert [e["name"] for e in guess.examples(conn, hide_ids={tid(conn, "kp-old")})] == ["GS25"]
    assert [e["name"] for e in guess.examples(conn, hide_ids={tid(conn, "g2")})] == ["카카오페이"]


def test_guess_ignores_unasked_ids_and_bad_categories(conn):
    evening(conn)
    kp = tid(conn, "kp")
    llm = FakeLLM({"GuessResult": lambda p: GuessResult(guesses=[
        Guess(txn_id=kp, category="유흥", confidence="high", reason="x"),
        Guess(txn_id=999, category="술", confidence="high", reason="x")])})
    assert guess.guess(conn, llm, [kp]) == {kp: {"category": "유흥", "confidence": "high", "reason": "x"}}


def test_agent_engine_guesses_and_api_fills_the_rest(conn, monkeypatch):
    """GUESS_ENGINE=agent: Console 에이전트가 낸 답을 쓰고, 빠뜨린 거래만 기존 API로 추측한다."""
    from app.agent import managed
    evening(conn)
    monkeypatch.setenv("GUESS_ENGINE", "agent")
    kp = tid(conn, "kp")
    monkeypatch.setattr(managed, "guess_with_agent", lambda c, ids: (
        {kp: {"category": "유흥", "confidence": "high", "reason": "만화카페 10분 뒤"}}, {}))
    asked = []

    def handle(p):
        asked.extend(t["name"] for t in p["targets"])
        return GuessResult(guesses=[Guess(txn_id=t["txn_id"], category="술", confidence="medium", reason="api")
                                    for t in p["targets"]])
    assert service.guess_pending(conn, FakeLLM({"GuessResult": handle})) == 3
    assert sorted(asked) == ["대표일반_나이스", "토스페이"]
    row = conn.execute("SELECT category, ai_reason FROM transactions WHERE id = ?", (kp,)).fetchone()
    assert tuple(row) == ("유흥", "만화카페 10분 뒤")


def test_agent_failure_falls_back_to_api(conn, monkeypatch):
    from app.agent import managed
    from app.agent.client import LLMError
    evening(conn)
    monkeypatch.setenv("GUESS_ENGINE", "agent")

    def broken(c, ids):
        raise LLMError("연결 끊김")
    monkeypatch.setattr(managed, "guess_with_agent", broken)
    llm = FakeLLM({"GuessResult": lambda p: GuessResult(guesses=[
        Guess(txn_id=t["txn_id"], category="편의점", confidence="high", reason="api") for t in p["targets"]])})
    assert service.guess_pending(conn, llm) == 3  # 업로드는 멈추지 않는다


def test_scope_all_sends_every_unreviewed_payment_and_low_goes_to_review(conn, monkeypatch):
    """GUESS_SCOPE=all: 가게 이름이 분명한 결제도 거래 단위로 추측하고, 확신 low는 분류 확인에 올린다."""
    evening(conn)
    add_out(conn, "GS25", 3000, "2026-10-20 09:00:00", category="편의점", h="gs")
    add_out(conn, "적금 이체", 100000, "2026-10-20 10:00:00", category="제외", h="sv")
    cat.remember(conn, "GS25", "편의점", source="ai")
    conn.commit()
    monkeypatch.setenv("GUESS_SCOPE", "all")
    asked = []

    def handle(p):
        asked.extend(t["name"] for t in p["targets"])
        return GuessResult(guesses=[Guess(txn_id=t["txn_id"], category="편의점",
                                          confidence="low" if t["name"] == "GS25" else "high", reason="r")
                                    for t in p["targets"]])
    service.guess_pending(conn, FakeLLM({"GuessResult": handle}))
    assert "GS25" in asked and "만화카페" in asked and "적금 이체" not in asked  # 제외는 건드리지 않는다
    assert "gs" in {t["source_hash"] for t in service.list_review(conn)}  # low → 사용자 확인
