"""Categorization orchestrator: rules -> transfers -> AI pipeline."""

import sqlite3

from finmint.db import get_transactions
from finmint.rules import apply_rules_to_transactions
from finmint.transfers import detect_transfers
from finmint.ai import categorize_transactions


def categorize_month(
    conn: sqlite3.Connection,
    config: dict,
    month: int,
    year: int,
) -> dict:
    """Run the full categorization pipeline for a given month.

    Pipeline order:
      1. Apply merchant rules to uncategorized transactions
      2. Detect inter-account transfers
      3. Batch-send remaining uncategorized to Claude API

    Each step is idempotent and can be re-run safely.

    Returns a dict with keys:
      rule_matched (int), transfers_detected (int),
      ai_categorized (int), uncategorized (int)
    """
    # Step 1: Apply merchant rules
    rule_matched = apply_rules_to_transactions(conn, month, year)

    # Step 2: Detect transfers
    transfers_detected = detect_transfers(conn, month, year)

    # Step 3: Send remaining uncategorized to AI
    # Only pass transactions where categorized_by is None and
    # review_status is 'needs_review'
    all_txns = get_transactions(conn, month, year)
    uncategorized_txns = [
        t for t in all_txns
        if t["categorized_by"] is None and t["review_status"] == "needs_review"
    ]

    ai_categorized = 0
    if uncategorized_txns:
        ai_categorized = categorize_transactions(config, conn, uncategorized_txns)

    # Count final uncategorized (re-query to get fresh state)
    final_txns = get_transactions(conn, month, year)
    uncategorized = sum(1 for t in final_txns if t["label_id"] is None)

    return {
        "rule_matched": rule_matched,
        "transfers_detected": transfers_detected,
        "ai_categorized": ai_categorized,
        "uncategorized": uncategorized,
    }
