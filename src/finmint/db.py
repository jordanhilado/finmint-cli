"""Database schema, initialization, and access helpers for finmint."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from finmint.models import Transaction

# ---------------------------------------------------------------------------
# Default labels: all 16 are is_default=True; Transfer and Income are
# is_protected=True.
# ---------------------------------------------------------------------------

DEFAULT_LABELS: list[tuple[str, bool]] = [
    ("Groceries", False),
    ("Dining Out", False),
    ("Transport", False),
    ("Housing", False),
    ("Utilities", False),
    ("Subscriptions", False),
    ("Shopping", False),
    ("Health", False),
    ("Entertainment", False),
    ("Income", True),
    ("Travel", False),
    ("Education", False),
    ("Personal Care", False),
    ("Gifts", False),
    ("Fees & Interest", False),
    ("Transfer", True),
]

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    enrollment_id TEXT,
    institution_name TEXT,
    account_type TEXT,
    account_subtype TEXT,
    last_four TEXT,
    access_token TEXT,
    last_synced_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    is_default BOOLEAN DEFAULT 0,
    is_protected BOOLEAN DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id),
    amount INTEGER NOT NULL,
    date TEXT NOT NULL,
    description TEXT,
    normalized_description TEXT,
    label_id INTEGER REFERENCES labels(id),
    review_status TEXT DEFAULT 'needs_review',
    categorized_by TEXT,
    transfer_pair_id TEXT,
    teller_type TEXT,
    teller_category TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS merchant_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    label_id INTEGER REFERENCES labels(id) NOT NULL,
    source TEXT DEFAULT 'manual',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    txn_count INTEGER NOT NULL,
    txn_total_cents INTEGER NOT NULL,
    generated_at TEXT,
    UNIQUE(period_type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_date
    ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_transactions_date
    ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_review_status
    ON transactions(review_status);
CREATE INDEX IF NOT EXISTS idx_transactions_transfer_pair
    ON transactions(transfer_pair_id);
CREATE INDEX IF NOT EXISTS idx_merchant_rules_pattern
    ON merchant_rules(pattern);
"""

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def get_connection(path: Path | str = ":memory:") -> sqlite3.Connection:
    """Return a sqlite3 connection with Row factory, WAL mode, and FK on."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | str = ":memory:") -> sqlite3.Connection:
    """Create all tables and indexes (idempotent), return connection."""
    conn = get_connection(path)
    conn.executescript(_SCHEMA_SQL)
    return conn


def init_db_with_conn(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes on an existing connection."""
    conn.executescript(_SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_default_labels(conn: sqlite3.Connection) -> None:
    """Insert the 16 default labels. Idempotent via INSERT OR IGNORE."""
    now = _now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO labels (name, is_default, is_protected, created_at) "
        "VALUES (?, 1, ?, ?)",
        [(name, is_protected, now) for name, is_protected in DEFAULT_LABELS],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------


def get_labels(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all labels ordered by id."""
    cur = conn.execute("SELECT * FROM labels ORDER BY id")
    return cur.fetchall()


def get_label_by_name(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    """Return a single label by exact name, or None."""
    cur = conn.execute("SELECT * FROM labels WHERE name = ?", (name,))
    return cur.fetchone()


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------


def insert_transaction(conn: sqlite3.Connection, data: Transaction) -> None:
    """Insert a single transaction. Amounts must already be in cents."""
    now = _now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO transactions "
        "(id, account_id, amount, date, description, normalized_description, "
        "label_id, review_status, categorized_by, transfer_pair_id, "
        "teller_type, teller_category, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["id"],
            data.get("account_id"),
            data["amount"],
            data["date"],
            data.get("description"),
            data.get("normalized_description"),
            data.get("label_id"),
            data.get("review_status", "needs_review"),
            data.get("categorized_by"),
            data.get("transfer_pair_id"),
            data.get("teller_type"),
            data.get("teller_category"),
            now,
        ),
    )
    conn.commit()


def get_transactions(
    conn: sqlite3.Connection, month: int, year: int
) -> list[sqlite3.Row]:
    """Return transactions for a given month/year, ordered by date."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    cur = conn.execute(
        "SELECT * FROM transactions WHERE date >= ? AND date < ? ORDER BY date",
        (start, end),
    )
    return cur.fetchall()


def update_transaction_label(
    conn: sqlite3.Connection,
    txn_id: str,
    label_id: int,
    categorized_by: str = "manual",
    status: str = "reviewed",
) -> None:
    """Update a transaction's label, categorized_by, and review_status."""
    conn.execute(
        "UPDATE transactions SET label_id = ?, categorized_by = ?, review_status = ? "
        "WHERE id = ?",
        (label_id, categorized_by, status, txn_id),
    )
    conn.commit()
