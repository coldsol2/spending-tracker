"""가맹점 → 카테고리 분류. 한 번 분류한 가맹점은 캐시해서 다시 묻지 않는다."""
import json
import sqlite3
from collections import Counter, defaultdict

from pydantic import BaseModel

from .. import categories as cats
from ..categories import EXCLUDED  # noqa: F401  (예전 이름으로 쓰는 곳을 위해)

BATCH_SIZE = 60
MAX_EXAMPLES = 40

SYSTEM = """한국 대학생의 은행 거래내역에서 돈이 나간 항목들이 JSON으로 주어진다.
각 항목(merchants)에는 이름(name), 은행이 적은 거래 유형(kind), 건수(count), 금액 예시(amounts), 시각 예시(times)가 있다.
각 이름을 다음 카테고리 중 하나로 분류하라. 사용자가 직접 만든 카테고리도 있으니 설명을 잘 읽어라.
{categories}

추가로 판단할 것:
- confident: 이름만으로 카테고리를 확신하면 true. 결제대행사 이름만 있거나(나이스, KCP, 코페이 등) 처음 보는 가게라 추측이면 false.
- varies: 같은 이름이라도 거래마다 용도가 다를 수 있으면 true. 사람에게 보낸 돈, 카카오페이·토스페이 같은 간편결제/충전,
  결제대행사 이름만 남은 결제가 여기에 해당한다. 특정 가게는 false.
examples에는 사용자가 직접 정한 분류가 있다. 같은 이름이나 비슷한 가게는 이를 따르라.
입력된 name을 merchant에 그대로 적어라."""


class Item(BaseModel):
    merchant: str
    category: str
    confident: bool = True
    varies: bool = False


class CategoryResult(BaseModel):
    """응답 모양. 실제 호출 때는 category를 지금 있는 카테고리로 묶은 같은 이름의 형식을 만들어 쓴다."""
    items: list[Item]


def result_schema(names: list[str]) -> type[BaseModel]:
    return cats.schema("CategoryResult", "items",
                       {"merchant": (str, ...), "confident": (bool, True), "varies": (bool, False)}, names)


def cached(conn: sqlite3.Connection, merchant: str) -> str | None:
    row = conn.execute("SELECT category FROM merchant_categories WHERE merchant = ?", (merchant,)).fetchone()
    return row["category"] if row else None


def remember(conn: sqlite3.Connection, merchant: str, category: str, source: str = "user",
             confident: bool = True, varies: bool = False) -> None:
    conn.execute(
        "INSERT INTO merchant_categories(merchant, category, source, confident, varies) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(merchant) DO UPDATE SET category = excluded.category, source = excluded.source, "
        "confident = excluded.confident, varies = excluded.varies",
        (merchant, category, source, int(confident), int(varies)),
    )


def _marks(items: list) -> str:
    return ",".join("?" * len(items))


def _merchant_contexts(conn: sqlite3.Connection, merchants: list[str]) -> list[dict]:
    """AI에 보낼 가게별 정보(거래 유형, 건수, 최근 금액·시각)를 한 번의 조회로 모은다."""
    rows_by = defaultdict(list)
    for r in conn.execute(
            f"SELECT description, kind, amount, occurred_at FROM transactions WHERE direction = 'out' "
            f"AND description IN ({_marks(merchants)}) ORDER BY occurred_at DESC", merchants):
        rows_by[r["description"]].append(r)
    out = []
    for m in merchants:
        rows = rows_by[m]
        kinds = Counter(r["kind"] for r in rows if r["kind"])
        out.append({
            "name": m,
            "kind": kinds.most_common(1)[0][0] if kinds else None,
            "count": len(rows),
            "amounts": [r["amount"] for r in rows[:3]],
            "times": [r["occurred_at"][11:16] for r in rows[:3]],
        })
    return out


def _examples(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT merchant, category FROM merchant_categories WHERE source = 'user' "
                        "ORDER BY rowid DESC LIMIT ?", (MAX_EXAMPLES,))
    return [{"name": r["merchant"], "category": r["category"]} for r in rows]


def categorize(conn: sqlite3.Connection, llm, merchants: list[str]) -> dict[str, str]:
    """캐시에 있는 건 바로, 없는 것만 Claude에 묻는다. llm이 None이면 캐시 결과만 돌려준다."""
    unique = list(dict.fromkeys(merchants))
    if not unique:
        return {}
    known = {r["merchant"]: r["category"] for r in conn.execute(
        f"SELECT merchant, category FROM merchant_categories WHERE merchant IN ({_marks(unique)})", unique)}
    result = {m: known[m] for m in unique if m in known}
    missing = [m for m in unique if m not in known]

    if llm is None or not missing:
        return result
    examples = _examples(conn)
    names = cats.names(conn)
    system = SYSTEM.format(categories=cats.prompt_list(conn))
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i:i + BATCH_SIZE]
        payload = {"merchants": _merchant_contexts(conn, batch), "examples": examples}
        out = llm.parse(system, json.dumps(payload, ensure_ascii=False), result_schema(names))
        for item in out.items:
            if item.merchant in batch and item.merchant not in result:
                cat = item.category if item.category in names else cats.FALLBACK
                result[item.merchant] = cat
                remember(conn, item.merchant, cat, source="ai", confident=item.confident, varies=item.varies)
    conn.commit()
    return result
