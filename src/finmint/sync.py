"""Transaction sync — fetch from Copilot Money, normalize, and upsert into SQLite."""

import calendar
import re
import sqlite3
from datetime import datetime, timezone
from typing import TypedDict

from finmint import copilot
from finmint.config import get_token
from finmint.db import insert_transaction, upsert_account


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


def sync_month(
    conn: sqlite3.Connection,
    config: dict,
    month: int,
    year: int,
    force: bool = False,
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

    token = get_token(config)

    try:
        with copilot.create_client(token) as client:
            # Fetch and upsert accounts
            accounts = copilot.fetch_accounts(client)
            for account in accounts:
                upsert_account(conn, {
                    "id": account["id"],
                    "institution_name": account["institution_name"],
                    "account_type": account["type"],
                    "last_four": account["mask"],
                })

            # Build date range
            start_date = f"{year:04d}-{month:02d}-01"
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

            # Fetch transactions for the date range
            txns = copilot.fetch_transactions(client, start_date, end_date)
            result["total_fetched"] = len(txns)

            for txn in txns:
                raw_desc = txn.get("description", "")
                normalized = normalize_merchant(raw_desc)

                # Check if transaction already exists to track new_count
                cur = conn.execute(
                    "SELECT 1 FROM transactions WHERE id = ?", (txn["id"],)
                )
                already_exists = cur.fetchone() is not None

                insert_transaction(conn, {
                    "id": txn["id"],
                    "account_id": txn["account_id"],
                    "amount": txn["amount"],
                    "date": txn["date"],
                    "description": raw_desc,
                    "normalized_description": normalized,
                    "source_type": txn["source_type"],
                })

                if not already_exists:
                    result["new_count"] += 1

    except copilot.CopilotAuthError:
        result["error"] = (
            "Token expired or invalid. Run `finmint token` to paste a new one."
        )

    return result
