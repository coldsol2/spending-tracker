import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    description TEXT NOT NULL,
    amount INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('out', 'in')),
    balance INTEGER,
    category TEXT,
    source_hash TEXT NOT NULL UNIQUE,
    kind TEXT,                          -- 은행이 적은 거래 유형 (체크카드결제, 출금 등)
    reviewed INTEGER NOT NULL DEFAULT 0 -- 사용자가 카테고리를 직접 정했으면 1
);
CREATE TABLE IF NOT EXISTS settlements (
    id INTEGER PRIMARY KEY,
    payment_id INTEGER NOT NULL REFERENCES transactions(id),
    incoming_id INTEGER NOT NULL REFERENCES transactions(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'confirmed', 'rejected')),
    reason TEXT
);
-- 하나의 입금은 최대 하나의 결제에만 확정된다
CREATE UNIQUE INDEX IF NOT EXISTS one_confirmed_per_incoming
    ON settlements(incoming_id) WHERE status = 'confirmed';
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'ai',     -- 'ai' | 'user'
    confident INTEGER NOT NULL DEFAULT 1,  -- AI가 확신하는지
    varies INTEGER NOT NULL DEFAULT 0      -- 사람·페이처럼 거래마다 용도가 다른 이름인지
);
CREATE TABLE IF NOT EXISTS budgets (
    category TEXT PRIMARY KEY,
    monthly_amount INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    week_start TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# 예전 버전 DB에 없던 열
NEW_COLUMNS = {
    "transactions": {"kind": "TEXT", "reviewed": "INTEGER NOT NULL DEFAULT 0"},
    "merchant_categories": {"source": "TEXT NOT NULL DEFAULT 'ai'", "confident": "INTEGER NOT NULL DEFAULT 1",
                            "varies": "INTEGER NOT NULL DEFAULT 0"},
}
# 예전 카테고리 이름 → 새 이름 (2026-10-31 카테고리 개편)
RENAMED_CATEGORIES = {"카페": "유흥", "구독": "구독료", "교통": "교통비", "의료": "생활"}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in NEW_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    for old, new in RENAMED_CATEGORIES.items():
        conn.execute("UPDATE transactions SET category = ? WHERE category = ?", (new, old))
        conn.execute("UPDATE merchant_categories SET category = ? WHERE category = ?", (new, old))
        if not conn.execute("SELECT 1 FROM budgets WHERE category = ?", (new,)).fetchone():
            conn.execute("UPDATE budgets SET category = ? WHERE category = ?", (new, old))
        conn.execute("DELETE FROM budgets WHERE category = ?", (old,))
    conn.commit()


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    path = Path(path or os.environ.get("APP_DB") or ROOT / "data" / "app.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    # 요청마다 새 연결을 쓰지만 FastAPI가 의존성과 엔드포인트를 다른 스레드에서 돌릴 수 있다
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
