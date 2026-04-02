"""Database schema, initialization, and access helpers for finmint."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from finmint.models import Transaction

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    institution_name TEXT,
    account_type TEXT,
    last_four TEXT,
    last_synced_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    copilot_id TEXT UNIQUE,
    name TEXT UNIQUE NOT NULL,
    color TEXT,
    icon TEXT,
    is_default BOOLEAN DEFAULT 0,
    is_protected BOOLEAN DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT REFERENCES accounts(id),
    item_id TEXT,
    amount INTEGER NOT NULL,
    date TEXT NOT NULL,
    description TEXT,
    normalized_description TEXT,
    label_id INTEGER REFERENCES labels(id),
    review_status TEXT DEFAULT 'needs_review',
    categorized_by TEXT,
    transfer_pair_id TEXT,
    source_type TEXT,
    note TEXT,
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


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing from older databases."""
    cur = conn.execute("PRAGMA table_info(transactions)")
    txn_cols = {row[1] for row in cur.fetchall()}
    if "source_type" not in txn_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN source_type TEXT")
        conn.commit()
    if "note" not in txn_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN note TEXT")
        conn.commit()
    if "item_id" not in txn_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN item_id TEXT")
        conn.commit()

    cur = conn.execute("PRAGMA table_info(labels)")
    label_cols = {row[1] for row in cur.fetchall()}
    if "color" not in label_cols:
        conn.execute("ALTER TABLE labels ADD COLUMN color TEXT")
        conn.commit()
    if "copilot_id" not in label_cols:
        conn.execute("ALTER TABLE labels ADD COLUMN copilot_id TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_labels_copilot_id ON labels(copilot_id)")
        conn.commit()
    if "icon" not in label_cols:
        conn.execute("ALTER TABLE labels ADD COLUMN icon TEXT")
        conn.commit()


def init_db(path: Path | str = ":memory:") -> sqlite3.Connection:
    """Create all tables and indexes (idempotent), return connection."""
    conn = get_connection(path)
    conn.executescript(_SCHEMA_SQL)
    _migrate(conn)
    return conn


def init_db_with_conn(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes on an existing connection."""
    conn.executescript(_SCHEMA_SQL)
    _migrate(conn)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------


def get_labels(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return Copilot Money categories ordered by name."""
    cur = conn.execute(
        "SELECT * FROM labels WHERE copilot_id IS NOT NULL ORDER BY name"
    )
    return cur.fetchall()


def get_label_by_name(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    """Return a single label by exact name, or None."""
    cur = conn.execute("SELECT * FROM labels WHERE name = ?", (name,))
    return cur.fetchone()


def upsert_category(
    conn: sqlite3.Connection,
    copilot_id: str,
    name: str,
    color: str | None = None,
    icon: str | None = None,
) -> None:
    """Insert or update a category from Copilot Money, keyed on copilot_id.

    Handles the case where a label with the same name already exists under a
    different (or NULL) copilot_id by updating the existing row in-place.
    """
    now = _now_iso()
    # If a row with this name exists but has a different copilot_id, update it
    existing = conn.execute(
        "SELECT id, copilot_id FROM labels WHERE name = ?", (name,)
    ).fetchone()
    if existing and existing["copilot_id"] != copilot_id:
        conn.execute(
            "UPDATE labels SET copilot_id = ?, color = ?, icon = ? WHERE id = ?",
            (copilot_id, color, icon, existing["id"]),
        )
        conn.commit()
        return

    conn.execute(
        "INSERT INTO labels (copilot_id, name, color, icon, created_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(copilot_id) DO UPDATE SET name=excluded.name, "
        "color=excluded.color, icon=excluded.icon",
        (copilot_id, name, color, icon, now),
    )
    conn.commit()


def get_copilot_id_for_label(
    conn: sqlite3.Connection, label_id: int
) -> str | None:
    """Look up the Copilot Money category ID for a local label ID."""
    row = conn.execute(
        "SELECT copilot_id FROM labels WHERE id = ?", (label_id,)
    ).fetchone()
    return row["copilot_id"] if row else None


def get_label_by_copilot_id(
    conn: sqlite3.Connection, copilot_id: str
) -> sqlite3.Row | None:
    """Look up a local label by its Copilot Money category ID."""
    return conn.execute(
        "SELECT * FROM labels WHERE copilot_id = ?", (copilot_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------


def insert_transaction(conn: sqlite3.Connection, data: Transaction) -> None:
    """Insert a single transaction. Amounts must already be in cents."""
    now = _now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO transactions "
        "(id, account_id, item_id, amount, date, description, normalized_description, "
        "label_id, review_status, categorized_by, transfer_pair_id, "
        "source_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["id"],
            data.get("account_id"),
            data.get("item_id"),
            data["amount"],
            data["date"],
            data.get("description"),
            data.get("normalized_description"),
            data.get("label_id"),
            data.get("review_status", "needs_review"),
            data.get("categorized_by"),
            data.get("transfer_pair_id"),
            data.get("source_type"),
            now,
        ),
    )
    conn.commit()


def upsert_account(conn: sqlite3.Connection, data: dict) -> None:
    """Insert or update an account record. Uses INSERT OR REPLACE keyed on ID."""
    now = _now_iso()
    conn.execute(
        "INSERT OR REPLACE INTO accounts "
        "(id, institution_name, account_type, last_four, last_synced_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            data["id"],
            data.get("institution_name"),
            data.get("account_type"),
            data.get("last_four"),
            data.get("last_synced_at"),
            data.get("created_at", now),
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
        "SELECT t.*, a.institution_name, a.last_four "
        "FROM transactions t "
        "LEFT JOIN accounts a ON t.account_id = a.id "
        "WHERE t.date >= ? AND t.date < ? ORDER BY t.date",
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


def delete_transactions_for_month(
    conn: sqlite3.Connection, month: int, year: int
) -> int:
    """Delete all transactions for a given month/year. Returns count deleted."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    cur = conn.execute(
        "DELETE FROM transactions WHERE date >= ? AND date < ?",
        (start, end),
    )
    # Also clear any AI summary for this month
    period_key = f"{year:04d}-{month:02d}"
    conn.execute(
        "DELETE FROM ai_summaries WHERE period_type = 'month' AND period_key = ?",
        (period_key,),
    )
    conn.commit()
    return cur.rowcount


def update_transaction_note(
    conn: sqlite3.Connection,
    txn_id: str,
    note: str | None,
) -> None:
    """Update a transaction's note. Pass None or empty string to clear."""
    conn.execute(
        "UPDATE transactions SET note = ? WHERE id = ?",
        (note or None, txn_id),
    )
    conn.commit()
