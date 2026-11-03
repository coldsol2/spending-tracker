"""분류 정확도 재기. 사용자가 직접 고른 카테고리를 정답으로 삼는다.

실행: python -m app.agent.evaluate                 (기존 API 방식)
      python -m app.agent.evaluate --engine agent  (Console 에이전트 + 거래 조회 도구)
      python -m app.agent.evaluate --engine both   (둘 다 같은 조건으로 재서 나란히 비교)
      python -m app.agent.evaluate --target in     (들어온 돈 종류: 정산·용돈·알바비·환불·기타 수입)
Claude를 부르므로 API 키가 필요하고 비용이 든다(에이전트 쪽이 더 비싸다).

정답을 3묶음으로 나눠, 한 묶음을 맞히는 동안 그 묶음의 정답은 숨기고
나머지 묶음의 선택만 예시로 준다. 그래서 '내 선택에서 배우기'의 효과까지 공정하게 잰다.
'예전'은 가게 이름 단위 AI 분류다. 거래마다 용도가 다른 이름(페이·사람)만 예전 분류가 남아 있다.
"""
import argparse
import sqlite3
from collections import Counter
from typing import Callable

from dotenv import load_dotenv

from .. import db
from . import guess, income, managed
from .client import get_client

FOLDS = 3
# predict(이번 묶음 거래 id, 숨길 정답 id) -> ({txn_id: {category, confidence, reason}}, 비용 달러)
Predict = Callable[[list[int], set[int]], tuple[dict, float]]


def labeled(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT t.id, t.description, t.amount, t.occurred_at, t.category AS answer, "
        "COALESCE(m.varies, 0) AS varies, CASE WHEN m.source = 'ai' THEN m.category END AS old "
        "FROM transactions t LEFT JOIN merchant_categories m ON m.merchant = t.description "
        "WHERE t.direction = 'out' AND t.reviewed = 1 ORDER BY t.occurred_at").fetchall()


def run(conn: sqlite3.Connection, predict: Predict) -> dict:
    rows = labeled(conn)
    predicted: dict[int, dict] = {}
    cost = 0.0
    for k in range(FOLDS):
        fold = [r["id"] for i, r in enumerate(rows) if i % FOLDS == k]
        result, spent = predict(fold, set(fold))
        predicted.update(result)
        cost += spent or 0.0

    def acc(items, pick):
        return sum(1 for r in items if pick(r) == r["answer"]), len(items)

    per_txn = [r for r in rows if r["varies"]]
    shops = [r for r in rows if not r["varies"]]
    new = lambda r: predicted.get(r["id"], {}).get("category")  # noqa: E731
    conf = Counter((predicted.get(r["id"], {}).get("confidence", "none"), new(r) == r["answer"]) for r in rows)
    return {
        "all": acc(rows, new), "per_txn_new": acc(per_txn, new), "per_txn_old": acc(per_txn, lambda r: r["old"]),
        "shops_new": acc(shops, new), "cost_usd": cost,
        "by_confidence": {c: (conf[(c, True)], conf[(c, True)] + conf[(c, False)]) for c in ("high", "medium", "low")},
        "predicted": predicted, "rows": rows,
    }


def api_predict(conn: sqlite3.Connection, llm) -> Predict:
    def predict(fold, hide):
        before = llm.cost_usd
        return guess.guess(conn, llm, fold, hide_ids=hide), llm.cost_usd - before
    return predict


def agent_predict(conn: sqlite3.Connection, web: bool) -> Predict:
    def predict(fold, hide):
        result, info = managed.guess_with_agent(conn, fold, hide_ids=hide, web=web)
        print(f"  에이전트 세션 {info['session_id']}: 도구 {info['tool_calls']}번, {info['seconds']}초, "
              f"${info['cost_usd']}", flush=True)
        return result, info["cost_usd"] or 0.0
    return predict


def run_income(conn: sqlite3.Connection, llm) -> dict:
    """들어온 돈 종류(정산·용돈·알바비…). 정답은 income_labels, 같은 3묶음 방식."""
    rows = conn.execute(
        "SELECT t.id, t.description, t.amount, t.occurred_at, l.label AS answer FROM income_labels l "
        "JOIN transactions t ON t.id = l.txn_id ORDER BY t.occurred_at").fetchall()
    predicted: dict[int, dict] = {}
    before = llm.cost_usd
    for k in range(FOLDS):
        fold = [r["id"] for i, r in enumerate(rows) if i % FOLDS == k]
        predicted.update(income.classify(conn, llm, fold, hide_ids=set(fold)))
    pick = lambda r: predicted.get(r["id"], {}).get("category")  # noqa: E731
    conf = Counter((predicted.get(r["id"], {}).get("confidence", "none"), pick(r) == r["answer"]) for r in rows)
    by_label = {lab: (sum(1 for r in rows if r["answer"] == lab and pick(r) == lab),
                      sum(1 for r in rows if r["answer"] == lab)) for lab in income.NAMES}
    return {"all": (sum(1 for r in rows if pick(r) == r["answer"]), len(rows)), "by_label": by_label,
            "by_confidence": {c: (conf[(c, True)], conf[(c, True)] + conf[(c, False)]) for c in ("high", "medium", "low")},
            "cost_usd": llm.cost_usd - before, "predicted": predicted, "rows": rows}


def report_income(r: dict) -> None:
    pct = lambda h, n: f"{h}/{n} ({h / n:.0%})" if n else "-"  # noqa: E731
    print("\n== 들어온 돈 종류 (기존 API) ==")
    print("전체        ", pct(*r["all"]))
    for lab, (h, n) in r["by_label"].items():
        print(f"  {lab:<6}", pct(h, n))
    for c, (h, n) in r["by_confidence"].items():
        print(f"  확신 {c:<6}", pct(h, n))
    print(f"비용 약 ${r['cost_usd']:.3f}")
    print("\n틀린 것 (정답 | AI | 근거):")
    for row in r["rows"]:
        p = r["predicted"].get(row["id"], {})
        if p.get("category") != row["answer"]:
            print(f"  {row['occurred_at'][:16]} {row['description']} +{row['amount']:,}원 | {row['answer']} | "
                  f"{p.get('category')} | {p.get('reason', '')}")


def report(name: str, r: dict) -> None:
    pct = lambda h, n: f"{h}/{n} ({h / n:.0%})" if n else "-"  # noqa: E731
    print(f"\n== {name} ==")
    print("전체                 ", pct(*r["all"]))
    print("페이·송금 (예전 → 지금)", pct(*r["per_txn_old"]), "→", pct(*r["per_txn_new"]))
    print("가게                 ", pct(*r["shops_new"]))
    for c, (h, n) in r["by_confidence"].items():
        print(f"  확신 {c:<6}", pct(h, n))
    print(f"비용 약 ${r['cost_usd']:.2f}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["api", "agent", "both"], default="api")
    p.add_argument("--web", action="store_true", help="에이전트에 웹 검색을 켠다 (환경 네트워크가 허용해야 결과가 나온다)")
    p.add_argument("--db", help="채점할 DB (정답지로 만든 검증용 DB: data/eval.db). 없으면 앱 DB")
    p.add_argument("--target", choices=["out", "in"], default="out",
                   help="out=나간 돈 카테고리, in=들어온 돈 종류(정산·용돈·알바비…)")
    args = p.parse_args()
    load_dotenv(db.ROOT / ".env")
    llm = get_client()
    if llm is None:
        raise SystemExit("ANTHROPIC_API_KEY가 없어서 잴 수 없어요.")
    conn = db.connect(args.db)
    if args.target == "in":
        report_income(run_income(conn, llm))
        return
    results = {}
    if args.engine in ("api", "both"):
        results["API"] = run(conn, api_predict(conn, llm))
        report("기존 API (거래 단위 추측)", results["API"])
    if args.engine in ("agent", "both"):
        results["에이전트"] = run(conn, agent_predict(conn, args.web))
        report("Console 에이전트 + 거래 조회 도구" + (" + 웹 검색" if args.web else ""), results["에이전트"])

    print("\n틀린 것 (정답 | " + " | ".join(results) + "):")
    first = next(iter(results.values()))
    for r in first["rows"]:
        picks = [res["predicted"].get(r["id"], {}).get("category") for res in results.values()]
        if any(pk != r["answer"] for pk in picks):
            print(f"  {r['occurred_at'][:16]} {r['description']} {r['amount']:,}원 | {r['answer']} | " + " | ".join(
                str(pk) for pk in picks))


if __name__ == "__main__":
    main()
