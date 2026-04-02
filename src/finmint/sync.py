"""Transaction sync — fetch from Copilot Money, normalize, and upsert into SQLite."""

import calendar
import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable, TypedDict

from finmint import copilot
from finmint.config import get_token
from finmint.db import (
    get_label_by_copilot_id,
    insert_transaction,
    upsert_account,
    upsert_category,
)


class SyncResult(TypedDict):
    new_count: int
    error: str | None
    total_fetched: int


def normalize_merchant(raw: str | None) -> str:
    """Normalize a merchant description for matching.

    - Uppercase
    - Strip trailing ``#\\d+`` patterns (e.g., ``#123``)
    - Collapse whitespace

    Returns empty string for None or blank input.
    """
    if not raw or not raw.strip():
        return ""
    text = raw.upper()
    # Strip trailing #digits (possibly preceded by space)
    text = re.sub(r"\s*#\d+", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_transactions_for_month(
    conn: sqlite3.Connection, month: int, year: int
) -> bool:
    """Check whether any transactions exist for the given month/year."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"
    cur = conn.execute(
        "SELECT 1 FROM transactions WHERE date >= ? AND date < ? LIMIT 1",
        (start, end),
    )
    return cur.fetchone() is not None


def _is_current_month(month: int, year: int) -> bool:
    """Return True if the given month/year matches the current calendar month."""
    now = datetime.now(timezone.utc)
    return now.month == month and now.year == year


def sync_categories(conn: sqlite3.Connection) -> int:
    """Fetch categories from Copilot Money and upsert into the labels table.

    Returns the number of categories synced.
    """
    token = get_token()
    with copilot.create_client(token) as client:
        categories = copilot.fetch_categories(client)

    for cat in categories:
        upsert_category(conn, cat["id"], cat["name"], cat.get("color"), cat.get("icon"))

    return len(categories)


def sync_month(
    conn: sqlite3.Connection,
    config: dict,
    month: int,
    year: int,
    force: bool = False,
    on_progress: "Callable[[str, int, int], None] | None" = None,
) -> SyncResult:
    """Sync transactions from Copilot Money for a given month into the local DB.

    For the current calendar month, always re-fetches (month is incomplete).
    For past months, skips if transactions already exist unless *force* is True.
    Uses INSERT OR IGNORE keyed on Copilot transaction ID for safe re-sync.

    On CopilotAuthError, sets result["error"] with a clear message.

    Returns:
        SyncResult with new_count, error, and total_fetched.
    """
    result: SyncResult = {
        "new_count": 0,
        "error": None,
        "total_fetched": 0,
    }

    current_month = _is_current_month(month, year)

    # For past months, skip fetch if data already exists (unless forced)
    if not current_month and not force and _has_transactions_for_month(conn, month, year):
        return result

    token = get_token()

    def _progress(step: str, current: int, total: int) -> None:
        if on_progress:
            on_progress(step, current, total)

    try:
        with copilot.create_client(token) as client:
            # Sync categories first so we can map category IDs on transactions
            _progress("Fetching categories", 0, 1)
            categories = copilot.fetch_categories(client)
            for cat in categories:
                upsert_category(
                    conn, cat["id"], cat["name"], cat.get("color"), cat.get("icon")
                )
            _progress("Fetching categories", 1, 1)

            # Fetch and upsert accounts
            _progress("Fetching accounts", 0, 1)
            accounts = copilot.fetch_accounts(client)
            for account in accounts:
                upsert_account(conn, {
                    "id": account["id"],
                    "institution_name": account["institution_name"],
                    "account_type": account["type"],
                    "last_four": account["mask"],
                })
            _progress("Fetching accounts", 1, 1)

            # Build date range
            start_date = f"{year:04d}-{month:02d}-01"
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

            # Fetch transactions for the date range
            _progress("Fetching transactions", 0, 1)
            txns = copilot.fetch_transactions(client, start_date, end_date)
            result["total_fetched"] = len(txns)
            _progress("Fetching transactions", 1, 1)

            total_txns = len(txns)
            for i, txn in enumerate(txns):
                raw_desc = txn.get("description", "")
                normalized = normalize_merchant(raw_desc)

                # Check if transaction already exists to track new_count
                cur = conn.execute(
                    "SELECT 1 FROM transactions WHERE id = ?", (txn["id"],)
                )
                already_exists = cur.fetchone() is not None

                # Map Copilot category ID to local label_id
                label_id = None
                copilot_cat_id = txn.get("category_id")
                if copilot_cat_id:
                    label_row = get_label_by_copilot_id(conn, copilot_cat_id)
                    if label_row:
                        label_id = label_row["id"]

                # Map Copilot reviewed status
                is_reviewed = txn.get("is_reviewed", False)
                review_status = "reviewed" if is_reviewed else "needs_review"

                insert_transaction(conn, {
                    "id": txn["id"],
                    "account_id": txn["account_id"],
                    "item_id": txn.get("item_id"),
                    "amount": txn["amount"],
                    "date": txn["date"],
                    "description": raw_desc,
                    "normalized_description": normalized,
                    "label_id": label_id,
                    "review_status": review_status,
                    "note": txn.get("user_notes"),
                    "source_type": txn["source_type"],
                })

                if not already_exists:
                    result["new_count"] += 1

                _progress("Processing transactions", i + 1, total_txns)

    except copilot.CopilotAuthError:
        result["error"] = (
            "Token expired or invalid. Run `finmint token` to paste a new one."
        )

    return result
