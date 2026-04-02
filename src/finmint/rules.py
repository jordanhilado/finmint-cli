"""Merchant rules engine for finmint: derive rules from Copilot Money categorizations.

Instead of maintaining a local rules table, rules are derived from transactions
that Copilot Money has already categorized. For each unique normalized merchant
description with a category, the most common category becomes the rule.
"""

import sqlite3
from typing import Optional


def _build_merchant_rules(
    conn: sqlite3.Connection,
) -> list[dict]:
    """Build merchant→category rules from already-categorized transactions.

    Groups transactions by normalized_description, picks the most frequently
    assigned label_id for each merchant. Only considers transactions that have
    both a normalized_description and a label_id.

    Returns a list of dicts with keys: pattern, label_id.
    """
    rows = conn.execute(
        "SELECT normalized_description, label_id, COUNT(*) as cnt "
        "FROM transactions "
        "WHERE normalized_description IS NOT NULL "
        "AND normalized_description != '' "
        "AND label_id IS NOT NULL "
        "GROUP BY normalized_description, label_id "
        "ORDER BY normalized_description, cnt DESC"
    ).fetchall()

    # For each merchant, keep only the most frequent label
    rules: dict[str, dict] = {}
    for row in rows:
        nd = row["normalized_description"]
        if nd not in rules:
            rules[nd] = {"pattern": nd, "label_id": row["label_id"]}

    return list(rules.values())


def match_rules(
    conn: sqlite3.Connection, normalized_description: str
) -> Optional[dict]:
    """Match a normalized description against Copilot-derived rules via substring.

    Returns the longest matching rule (most specific wins), or None.
    """
    desc_upper = normalized_description.upper()
    rules = _build_merchant_rules(conn)

    best: Optional[dict] = None
    best_len = 0
    for rule in rules:
        if rule["pattern"] in desc_upper:
            plen = len(rule["pattern"])
            if plen > best_len:
                best = rule
                best_len = plen
    return best


def get_all_rules(conn: sqlite3.Connection) -> list[dict]:
    """Return all derived rules with label names, sorted by pattern.

    Rules are derived from how transactions are already categorized in
    Copilot Money, grouped by normalized merchant description.
    """
    rows = conn.execute(
        "SELECT t.normalized_description AS pattern, "
        "t.label_id, l.name AS label_name, COUNT(*) as txn_count "
        "FROM transactions t "
        "JOIN labels l ON t.label_id = l.id "
        "WHERE t.normalized_description IS NOT NULL "
        "AND t.normalized_description != '' "
        "AND t.label_id IS NOT NULL "
        "GROUP BY t.normalized_description, t.label_id "
        "ORDER BY t.normalized_description ASC"
    ).fetchall()

    # Deduplicate: keep the most frequent label per merchant
    seen: dict[str, dict] = {}
    for row in rows:
        nd = row["pattern"]
        if nd not in seen:
            seen[nd] = {
                "pattern": nd,
                "label_id": row["label_id"],
                "label_name": row["label_name"],
                "txn_count": row["txn_count"],
            }

    return sorted(seen.values(), key=lambda r: r["pattern"])


def apply_rules_to_transactions(
    conn: sqlite3.Connection, month: int, year: int
) -> int:
    """Apply Copilot-derived merchant rules to uncategorized transactions.

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
