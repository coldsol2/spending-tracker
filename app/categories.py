"""카테고리 목록. 기본 11개는 앱이 정해 두고(이모지만 바꿀 수 있음), 사용자가 직접 추가할 수 있다.
AI 분류와 추측은 이 목록과 각 설명을 그때그때 읽어서 쓴다."""
import sqlite3
from typing import Literal

from pydantic import BaseModel, create_model

EXCLUDED = "제외"  # 지출이 아닌 돈의 이동. 실지출 집계에서 뺀다
FALLBACK = "기타"
# 이름·삭제가 앱 규칙과 묶여 있는 카테고리(실지출 제외, 분류 확인 대상)
SPECIAL = {"송금", FALLBACK, EXCLUDED}

# (이름, 이모지, 색, AI에게 줄 설명)
BUILTIN = [
    ("식비", "🍚", "#ffb98a", "식당, 학식, 분식, 패스트푸드, 배달앱(쿠팡이츠·배달의민족·요기요)"),
    ("편의점", "🏪", "#ffd23f", "이마트24, GS25(지에스25), CU(씨유), 세븐일레븐(코리아세븐), 미니스톱"),
    ("술", "🍺", "#f2709c", "술집, 호프, 포차, 이자카야, 와인바"),
    ("유흥", "🎮", "#a98bea", "카페·디저트·베이커리·아이스크림, 만화카페, PC방, 노래방, 보드게임카페, 방탈출, 영화, 공연, 게임"),
    ("구독료", "🔁", "#c9b6f5", "넷플릭스·유튜브·멜론·쿠팡 와우멤버십·ChatGPT 등 정기결제"),
    ("교통비", "🚕", "#ffe58a", "택시(카카오T), 버스·지하철, 교통카드, 주유, 주차, 따릉이"),
    ("쇼핑", "🛍️", "#f8a9c4", "쿠팡(멤버십 제외)·무신사·올리브영 등 온라인몰, 옷, 전자기기, 화장품"),
    ("생활", "🧴", "#e3d6f5", "미용실, 통신요금, 생활용품, 복사·인쇄, 세탁, 병원, 약국"),
    ("송금", "💸", "#ffd6bd", "사람 이름(2~4글자 한글 이름 등)에게 보낸 돈"),
    ("기타", "📦", "#cfc4e0", "위 어디에도 넣기 어려운 것"),
    ("제외", "⏸️", "#f1edf4", "지출이 아닌 돈의 이동 — 환전, 증권·투자 계좌로 이체, 적금·저축, 본인 계좌 이체"),
]
# 사용자 카테고리에 차례로 붙일 색 (키 컬러 라일락·핑크·노랑·피치 계열)
PALETTE = ["#9ad0c2", "#f4a7b9", "#b8a4f0", "#ffcf99", "#a7c7f2", "#f6c1e0", "#d6c48f", "#c3e0a5"]
MAX_NAME, MAX_EMOJI, MAX_DESC = 10, 8, 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY,
    emoji TEXT NOT NULL,
    color TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    builtin INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL
);
"""


def seed(conn: sqlite3.Connection) -> None:
    """기본 카테고리를 넣는다. 이미 있으면(이모지를 바꿨어도) 그대로 둔다."""
    for i, (name, emoji, color, desc) in enumerate(BUILTIN):
        conn.execute("INSERT OR IGNORE INTO categories(name, emoji, color, description, builtin, position) "
                     "VALUES (?, ?, ?, ?, 1, ?)", (name, emoji, color, desc, i))
    # 기본 설명은 앱이 고친 최신 문구를 따른다
    for name, _, _, desc in BUILTIN:
        conn.execute("UPDATE categories SET description = ? WHERE name = ? AND builtin = 1", (desc, name))


def all_categories(conn: sqlite3.Connection) -> list[dict]:
    """화면과 AI가 쓰는 순서: 사용자 카테고리는 기본 카테고리 중 '송금' 앞에 끼운다."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY builtin DESC, position")]
    builtin = [r for r in rows if r["builtin"]]
    custom = [r for r in rows if not r["builtin"]]
    cut = next((i for i, r in enumerate(builtin) if r["name"] == "송금"), len(builtin))
    out = builtin[:cut] + custom + builtin[cut:]
    for r in out:
        r["builtin"] = bool(r["builtin"])
        r["special"] = r["name"] in SPECIAL
    return out


def names(conn: sqlite3.Connection) -> list[str]:
    return [c["name"] for c in all_categories(conn)]


def ensure_known(conn: sqlite3.Connection, name: str) -> None:
    if not conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        raise ValueError(f"알 수 없는 카테고리: {name}")


def add(conn: sqlite3.Connection, name: str, emoji: str, description: str) -> dict:
    name, emoji, description = name.strip(), emoji.strip(), description.strip()
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"카테고리 이름은 1~{MAX_NAME}글자로 정해 주세요.")
    if not emoji or len(emoji) > MAX_EMOJI:
        raise ValueError("이모지를 하나 골라 주세요.")
    if len(description) > MAX_DESC:
        raise ValueError(f"설명은 {MAX_DESC}글자 안으로 적어 주세요.")
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        raise ValueError(f"'{name}' 카테고리는 이미 있어요.")
    count = conn.execute("SELECT COUNT(*) FROM categories WHERE builtin = 0").fetchone()[0]
    position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM categories").fetchone()[0]
    conn.execute("INSERT INTO categories(name, emoji, color, description, builtin, position) VALUES (?, ?, ?, ?, 0, ?)",
                 (name, emoji, PALETTE[count % len(PALETTE)], description, position))
    conn.commit()
    return next(c for c in all_categories(conn) if c["name"] == name)


def update(conn: sqlite3.Connection, name: str, emoji: str | None = None, description: str | None = None) -> None:
    row = conn.execute("SELECT builtin FROM categories WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise LookupError(f"'{name}' 카테고리를 찾을 수 없어요.")
    if emoji is not None:
        emoji = emoji.strip()
        if not emoji or len(emoji) > MAX_EMOJI:
            raise ValueError("이모지를 하나 골라 주세요.")
        conn.execute("UPDATE categories SET emoji = ? WHERE name = ?", (emoji, name))
    if description is not None:
        if row["builtin"]:
            raise ValueError("기본 카테고리의 설명은 바꿀 수 없어요.")
        if len(description.strip()) > MAX_DESC:
            raise ValueError(f"설명은 {MAX_DESC}글자 안으로 적어 주세요.")
        conn.execute("UPDATE categories SET description = ? WHERE name = ?", (description.strip(), name))
    conn.commit()


def remove(conn: sqlite3.Connection, name: str) -> int:
    """사용자 카테고리만 지운다. 그 카테고리의 거래는 '기타'로 옮기고 분류 확인에 다시 띄운다."""
    row = conn.execute("SELECT builtin FROM categories WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise LookupError(f"'{name}' 카테고리를 찾을 수 없어요.")
    if row["builtin"]:
        raise ValueError("기본 카테고리는 지울 수 없어요.")
    moved = conn.execute("UPDATE transactions SET category = ?, reviewed = 0, ai_guess = NULL, ai_confidence = NULL, "
                         "ai_reason = NULL WHERE category = ?", (FALLBACK, name)).rowcount
    conn.execute("DELETE FROM merchant_categories WHERE category = ?", (name,))
    conn.execute("DELETE FROM budgets WHERE category = ?", (name,))
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    conn.commit()
    return moved


def prompt_list(conn: sqlite3.Connection) -> str:
    """AI 지시문에 넣을 카테고리 설명 목록."""
    return "\n".join(f"- {c['name']}: {c['description'] or c['name']}" for c in all_categories(conn))


def schema(name: str, field: str, extra: dict, names_: list[str]) -> type[BaseModel]:
    """카테고리 목록이 바뀔 수 있어서, AI 응답 형식(구조화 출력)을 그때그때 만든다.
    field 이름의 값은 지금 있는 카테고리 중 하나로만 답하게 한다."""
    category = Literal[tuple(names_)]  # type: ignore[valid-type]
    item = create_model(f"{name}Item", **extra, category=(category, ...))
    return create_model(name, **{field: (list[item], ...)})
