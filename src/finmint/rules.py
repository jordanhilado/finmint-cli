"""Merchant rules engine for finmint: CRUD, substring matching, longest-match-wins."""

import sqlite3
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_rule(
    conn: sqlite3.Connection,
    pattern: str,
    label_id: int,
    source: str = "manual",
) -> int:
    """Add a merchant rule. Pattern is normalized to uppercase.

    If a rule with the same normalized pattern already exists, update its
    label_id instead of inserting a duplicate. Returns the rule id.
    """
    normalized = pattern.strip().upper()
    existing = conn.execute(
        "SELECT id FROM merchant_rules WHERE pattern = ?", (normalized,)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE merchant_rules SET label_id = ?, source = ? WHERE id = ?",
            (label_id, source, existing["id"]),
        )
        conn.commit()
        return existing["id"]

    cur = conn.execute(
        "INSERT INTO merchant_rules (pattern, label_id, source, created_at) "
        "VALUES (?, ?, ?, ?)",
        (normalized, label_id, source, _now_iso()),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    """Delete a merchant rule. Transactions that used it keep their labels."""
    conn.execute("DELETE FROM merchant_rules WHERE id = ?", (rule_id,))
    conn.commit()


def update_rule(
    conn: sqlite3.Connection, rule_id: int, label_id: int
) -> None:
    """Update a rule's label_id."""
    conn.execute(
        "UPDATE merchant_rules SET label_id = ? WHERE id = ?",
        (label_id, rule_id),
    )
    conn.commit()


def match_rules(
    conn: sqlite3.Connection, normalized_description: str
) -> Optional[sqlite3.Row]:
    """Match a normalized description against all rules via substring containment.

    Returns the longest matching rule (most specific wins), or None.
    """
    desc_upper = normalized_description.upper()
    rows = conn.execute(
        "SELECT * FROM merchant_rules ORDER BY id"
    ).fetchall()

    best: Optional[sqlite3.Row] = None
    best_len = 0
    for row in rows:
        if row["pattern"] in desc_upper:
            plen = len(row["pattern"])
            if plen > best_len:
                best = row
                best_len = plen
    return best


def get_all_rules(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all rules with label names, sorted alphabetically by pattern."""
    return conn.execute(
        "SELECT mr.id, mr.pattern, mr.label_id, mr.source, mr.created_at, "
        "l.name AS label_name "
        "FROM merchant_rules mr "
        "JOIN labels l ON mr.label_id = l.id "
        "ORDER BY mr.pattern ASC"
    ).fetchall()


def apply_rules_to_transactions(
    conn: sqlite3.Connection, month: int, year: int
) -> int:
    """Apply merchant rules to all uncategorized transactions for a month.

    For each uncategorized transaction, run match_rules on its
    normalized_description. If a match is found, set label_id,
    categorized_by='rule', review_status='auto_accepted'.

    Returns the count of matched transactions.
    """
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    rows = conn.execute(
        "SELECT id, normalized_description FROM transactions "
        "WHERE date >= ? AND date < ? AND label_id IS NULL "
        "ORDER BY date",
        (start, end),
    ).fetchall()

    count = 0
    for txn in rows:
        nd = txn["normalized_description"]
        if not nd:
            continue
        rule = match_rules(conn, nd)
        if rule:
            conn.execute(
                "UPDATE transactions "
                "SET label_id = ?, categorized_by = 'rule', "
                "review_status = 'auto_accepted' "
                "WHERE id = ?",
                (rule["label_id"], txn["id"]),
            )
            count += 1

    conn.commit()
    return count
