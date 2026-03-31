"""Transaction sync — fetch from Teller, normalize, and upsert into SQLite."""

import calendar
import re
import sqlite3
from datetime import datetime, timezone
from typing import TypedDict

from finmint import teller
from finmint.db import insert_transaction


class SyncResult(TypedDict):
    new_count: int
    skipped_accounts: list[str]
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


def _get_connected_accounts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all accounts that have an access_token."""
    cur = conn.execute(
        "SELECT * FROM accounts WHERE access_token IS NOT NULL "
        "AND access_token != ''"
    )
    return cur.fetchall()


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
    """Sync transactions from Teller for a given month into the local DB.

    For the current calendar month, always re-fetches (month is incomplete).
    For past months, skips if transactions already exist unless *force* is True.
    Uses INSERT OR IGNORE keyed on Teller transaction ID for safe re-sync.

    On TellerAuthError for a specific account, skips it and continues with
    remaining accounts, collecting warnings in the result.

    Returns:
        SyncResult with new_count, skipped_accounts, and total_fetched.
    """
    accounts = _get_connected_accounts(conn)
    result: SyncResult = {
        "new_count": 0,
        "skipped_accounts": [],
        "total_fetched": 0,
    }

    current_month = _is_current_month(month, year)

    # For past months, skip fetch if data already exists (unless forced)
    if not current_month and not force and _has_transactions_for_month(conn, month, year):
        return result

    # Build date range
    start_date = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

    for account in accounts:
        account_id = account["id"]
        access_token = account["access_token"]

        try:
            with teller.create_client(config, access_token) as client:
                txns = teller.fetch_transactions(
                    client, account_id, start_date, end_date
                )
        except teller.TellerAuthError:
            institution = account["institution_name"] or account_id
            result["skipped_accounts"].append(
                f"Account {institution} failed to sync — token may be expired. "
                "Run `finmint accounts` to re-enroll."
            )
            continue

        result["total_fetched"] += len(txns)

        for txn in txns:
            raw_desc = txn.get("description", "")
            normalized = normalize_merchant(raw_desc)

            # Count rows before insert to detect new vs ignored
            cur = conn.execute(
                "SELECT 1 FROM transactions WHERE id = ?", (txn["id"],)
            )
            already_exists = cur.fetchone() is not None

            insert_transaction(conn, {
                "id": txn["id"],
                "account_id": account_id,
                "amount": txn["amount"],
                "date": txn["date"],
                "description": raw_desc,
                "normalized_description": normalized,
                "teller_type": txn.get("type"),
                "teller_category": txn.get("category"),
            })

            if not already_exists:
                result["new_count"] += 1

    return result
