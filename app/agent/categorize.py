"""가맹점 → 카테고리 분류. 한 번 분류한 가맹점은 캐시해서 다시 묻지 않는다."""
import json
import sqlite3
from typing import Literal

from pydantic import BaseModel

CATEGORIES = ["식비", "편의점", "술", "유흥", "구독료", "교통비", "쇼핑", "생활", "송금", "기타", "제외"]
Category = Literal["식비", "편의점", "술", "유흥", "구독료", "교통비", "쇼핑", "생활", "송금", "기타", "제외"]
EXCLUDED = "제외"  # 지출이 아닌 돈의 이동. 실지출 집계에서 뺀다
BATCH_SIZE = 60
MAX_EXAMPLES = 40

SYSTEM = f"""한국 대학생의 은행 거래내역에서 돈이 나간 항목들이 JSON으로 주어진다.
각 항목(merchants)에는 이름(name), 은행이 적은 거래 유형(kind), 건수(count), 금액 예시(amounts), 시각 예시(times)가 있다.
각 이름을 다음 카테고리 중 하나로 분류하라: {", ".join(CATEGORIES)}.
- 식비: 식당, 학식, 분식, 패스트푸드, 배달앱(쿠팡이츠·배달의민족·요기요)
- 편의점: 이마트24, GS25(지에스25), CU(씨유), 세븐일레븐(코리아세븐), 미니스톱
- 술: 술집, 호프, 포차, 이자카야, 와인바
- 유흥: 카페·디저트·베이커리·아이스크림, 만화카페, PC방, 노래방, 보드게임카페, 방탈출, 영화, 공연, 게임
- 구독료: 넷플릭스·유튜브·멜론·쿠팡 와우멤버십·ChatGPT 등 정기결제
- 교통비: 택시(카카오T), 버스·지하철, 교통카드, 주유, 주차, 따릉이
- 쇼핑: 쿠팡(멤버십 제외)·무신사·올리브영 등 온라인몰, 옷, 전자기기, 화장품
- 생활: 미용실, 통신요금, 생활용품, 복사·인쇄, 세탁, 병원, 약국
- 송금: 사람 이름(2~4글자 한글 이름 등)에게 보낸 돈
- 제외: 지출이 아닌 돈의 이동 — 환전, 증권·투자 계좌로 이체, 적금·저축, 본인 계좌 이체
- 기타: 위 어디에도 넣기 어려운 것

추가로 판단할 것:
- confident: 이름만으로 카테고리를 확신하면 true. 결제대행사 이름만 있거나(나이스, KCP, 코페이 등) 처음 보는 가게라 추측이면 false.
- varies: 같은 이름이라도 거래마다 용도가 다를 수 있으면 true. 사람에게 보낸 돈, 카카오페이·토스페이 같은 간편결제/충전,
  결제대행사 이름만 남은 결제가 여기에 해당한다. 특정 가게는 false.
examples에는 사용자가 직접 정한 분류가 있다. 같은 이름이나 비슷한 가게는 이를 따르라.
입력된 name을 merchant에 그대로 적어라."""


class Item(BaseModel):
    merchant: str
    category: Category
    confident: bool = True
    varies: bool = False


class CategoryResult(BaseModel):
    items: list[Item]


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


def _merchant_context(conn: sqlite3.Connection, merchant: str) -> dict:
    rows = conn.execute(
        "SELECT kind, amount, occurred_at FROM transactions WHERE description = ? AND direction = 'out' "
        "ORDER BY occurred_at DESC", (merchant,)).fetchall()
    kinds = [r["kind"] for r in rows if r["kind"]]
    return {
        "name": merchant,
        "kind": max(set(kinds), key=kinds.count) if kinds else None,
        "count": len(rows),
        "amounts": [r["amount"] for r in rows[:3]],
        "times": [r["occurred_at"][11:16] for r in rows[:3]],
    }


def _examples(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT merchant, category FROM merchant_categories WHERE source = 'user' "
                        "ORDER BY rowid DESC LIMIT ?", (MAX_EXAMPLES,))
    return [{"name": r["merchant"], "category": r["category"]} for r in rows]


def categorize(conn: sqlite3.Connection, llm, merchants: list[str]) -> dict[str, str]:
    """캐시에 있는 건 바로, 없는 것만 Claude에 묻는다. llm이 None이면 캐시 결과만 돌려준다."""
    result: dict[str, str] = {}
    missing: list[str] = []
    for m in dict.fromkeys(merchants):
        cat = cached(conn, m)
        if cat:
            result[m] = cat
        else:
            missing.append(m)

    if llm is None or not missing:
        return result
    examples = _examples(conn)
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i:i + BATCH_SIZE]
        payload = {"merchants": [_merchant_context(conn, m) for m in batch], "examples": examples}
        out = llm.parse(SYSTEM, json.dumps(payload, ensure_ascii=False), CategoryResult)
        for item in out.items:
            if item.merchant in batch and item.merchant not in result:
                cat = item.category if item.category in CATEGORIES else "기타"
                result[item.merchant] = cat
                remember(conn, item.merchant, cat, source="ai", confident=item.confident, varies=item.varies)
    conn.commit()
    return result
