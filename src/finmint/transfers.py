"""Inter-account transfer detection for finmint."""

import sqlite3
import uuid
from datetime import datetime


def detect_transfers(conn: sqlite3.Connection, month: int, year: int) -> int:
    """Detect transfer pairs among transactions for the given month.

    Finds matching debit/credit pairs across different accounts within a
    2-day window.  Excludes card_payment transactions and those already
    linked as transfers.  Greedy matching processes closest-date pairs
    first, preferring pairs where teller_type indicates a transfer or ACH.

    Returns the number of transfer pairs detected.
    """
    from finmint.db import get_label_by_name

    # Look up the protected "Transfer" label.
    transfer_label = get_label_by_name(conn, "Transfer")
    if transfer_label is None:
        raise RuntimeError("Transfer label not found; call seed_default_labels first")
    transfer_label_id: int = transfer_label["id"]

    # Build date range for the month.
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    # Fetch candidate transactions: not card_payment, not already linked.
    rows = conn.execute(
        "SELECT id, account_id, amount, date, teller_type "
        "FROM transactions "
        "WHERE date >= ? AND date < ? "
        "  AND (teller_type IS NULL OR teller_type != 'card_payment') "
        "  AND transfer_pair_id IS NULL",
        (start, end),
    ).fetchall()

    if not rows:
        return 0

    # Build a list of candidate dicts for easier manipulation.
    candidates = [
        {
            "id": r["id"],
            "account_id": r["account_id"],
            "amount": r["amount"],
            "date": datetime.strptime(r["date"], "%Y-%m-%d"),
            "teller_type": r["teller_type"],
        }
        for r in rows
    ]

    # Generate all valid pairs and score them.
    pairs: list[tuple[int, bool, int, int]] = []  # (day_diff, has_transfer_type, i, j)
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a = candidates[i]
            b = candidates[j]

            # Must be opposite amounts.
            if a["amount"] + b["amount"] != 0:
                continue

            # Must be different accounts.
            if a["account_id"] == b["account_id"]:
                continue

            # Must be within 2 days.
            day_diff = abs((a["date"] - b["date"]).days)
            if day_diff > 2:
                continue

            # Check if either has a transfer-indicating teller_type.
            has_transfer_type = (
                a["teller_type"] in ("transfer", "ach")
                or b["teller_type"] in ("transfer", "ach")
            )

            # Sort key: closest date first, prefer transfer-type pairs
            # (False < True, so we negate to prefer True).
            pairs.append((day_diff, not has_transfer_type, i, j))

    # Sort: closest date first, then prefer transfer-type pairs.
    pairs.sort()

    # Greedy matching.
    matched: set[int] = set()
    pair_count = 0

    for _day_diff, _pref, i, j in pairs:
        if i in matched or j in matched:
            continue

        matched.add(i)
        matched.add(j)

        pair_id = str(uuid.uuid4())
        txn_a_id = candidates[i]["id"]
        txn_b_id = candidates[j]["id"]

        conn.execute(
            "UPDATE transactions "
            "SET transfer_pair_id = ?, label_id = ?, review_status = 'needs_review' "
            "WHERE id = ?",
            (pair_id, transfer_label_id, txn_a_id),
        )
        conn.execute(
            "UPDATE transactions "
            "SET transfer_pair_id = ?, label_id = ?, review_status = 'needs_review' "
            "WHERE id = ?",
            (pair_id, transfer_label_id, txn_b_id),
        )
        pair_count += 1

    conn.commit()
    return pair_count
