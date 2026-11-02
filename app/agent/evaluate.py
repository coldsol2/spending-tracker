"""분류 정확도 재기. 사용자가 직접 고른 카테고리를 정답으로 삼는다.

실행: python -m app.agent.evaluate   (Claude를 부르므로 API 키가 필요하고 소액 비용이 든다)

정답을 3묶음으로 나눠, 한 묶음을 맞히는 동안 그 묶음의 정답은 예시에서 숨기고
나머지 묶음의 선택만 예시로 준다. 그래서 '내 선택에서 배우기'의 효과까지 공정하게 잰다.
비교 기준(예전 방식)은 가게 이름 단위 AI 분류다. 거래마다 용도가 다른 이름(페이·사람)만
예전 분류가 남아 있어서 그쪽만 비교한다.
"""
import sqlite3
from collections import Counter

from dotenv import load_dotenv

from .. import db
from . import guess
from .client import get_client

FOLDS = 3


def labeled(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT t.id, t.description, t.amount, t.occurred_at, t.category AS answer, "
        "COALESCE(m.varies, 0) AS varies, CASE WHEN m.source = 'ai' THEN m.category END AS old "
        "FROM transactions t LEFT JOIN merchant_categories m ON m.merchant = t.description "
        "WHERE t.direction = 'out' AND t.reviewed = 1 ORDER BY t.occurred_at").fetchall()


def run(conn: sqlite3.Connection, llm) -> dict:
    rows = labeled(conn)
    predicted: dict[int, dict] = {}
    for k in range(FOLDS):
        fold = [r["id"] for i, r in enumerate(rows) if i % FOLDS == k]
        predicted.update(guess.guess(conn, llm, fold, hide_ids=set(fold)))

    def acc(items, pick):
        hit = sum(1 for r in items if pick(r) == r["answer"])
        return hit, len(items)

    per_txn = [r for r in rows if r["varies"]]
    shops = [r for r in rows if not r["varies"]]
    new = lambda r: predicted.get(r["id"], {}).get("category")  # noqa: E731
    conf = Counter()
    for r in rows:
        c = predicted.get(r["id"], {}).get("confidence", "none")
        conf[(c, new(r) == r["answer"])] += 1
    return {
        "all": acc(rows, new),
        "per_txn_new": acc(per_txn, new),
        "per_txn_old": acc(per_txn, lambda r: r["old"]),
        "shops_new": acc(shops, new),
        "by_confidence": {c: (conf[(c, True)], conf[(c, True)] + conf[(c, False)])
                          for c in ("high", "medium", "low")},
        "misses": [(r["occurred_at"][:16], r["description"], r["amount"], r["answer"], new(r),
                    predicted.get(r["id"], {}).get("reason", "")) for r in rows if new(r) != r["answer"]],
    }


def main() -> None:
    load_dotenv(db.ROOT / ".env")
    llm = get_client()
    if llm is None:
        raise SystemExit("ANTHROPIC_API_KEY가 없어서 잴 수 없어요.")
    conn = db.connect()
    r = run(conn, llm)
    pct = lambda h, n: f"{h}/{n} ({h / n:.0%})" if n else "-"  # noqa: E731
    print("전체 (새 방식)           ", pct(*r["all"]))
    print("거래마다 다른 이름: 예전 ", pct(*r["per_txn_old"]))
    print("거래마다 다른 이름: 새   ", pct(*r["per_txn_new"]))
    print("가게 (새 방식)           ", pct(*r["shops_new"]))
    for c, (h, n) in r["by_confidence"].items():
        print(f"  확신 {c:<6}", pct(h, n))
    print("\n틀린 것:")
    for m in r["misses"]:
        print(" ", *m)


if __name__ == "__main__":
    main()
