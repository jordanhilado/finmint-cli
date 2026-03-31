"""Tests for finmint.transfers — inter-account transfer detection."""

import sqlite3
import uuid

import pytest

from finmint import db
from finmint.transfers import detect_transfers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db(conn: sqlite3.Connection) -> None:
    """Initialize schema and seed default labels."""
    db.init_db_with_conn(conn)
    db.seed_default_labels(conn)


def _insert_account(conn: sqlite3.Connection, account_id: str) -> None:
    conn.execute(
        "INSERT INTO accounts (id, institution_name, account_type) VALUES (?, ?, ?)",
        (account_id, "Test Bank", "checking"),
    )
    conn.commit()


def _insert_txn(
    conn: sqlite3.Connection,
    *,
    txn_id: str | None = None,
    account_id: str,
    amount: int,
    date: str,
    source_type: str | None = None,
    transfer_pair_id: str | None = None,
) -> str:
    tid = txn_id or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO transactions "
        "(id, account_id, amount, date, description, source_type, transfer_pair_id, review_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'needs_review')",
        (tid, account_id, amount, date, "Test txn", source_type, transfer_pair_id),
    )
    conn.commit()
    return tid


def _get_txn(conn: sqlite3.Connection, txn_id: str) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM transactions WHERE id = ?", (txn_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDetectTransfers:
    """Transfer detection test suite."""

    def test_matching_pair_same_day(self, in_memory_db):
        """Happy path: $500 debit and $500 credit across two accounts on same day."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        t1 = _insert_txn(conn, account_id="acct-1", amount=-50000, date="2026-03-15")
        t2 = _insert_txn(conn, account_id="acct-2", amount=50000, date="2026-03-15")

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        txn1 = _get_txn(conn, t1)
        txn2 = _get_txn(conn, t2)
        assert txn1["transfer_pair_id"] is not None
        assert txn1["transfer_pair_id"] == txn2["transfer_pair_id"]

    def test_matching_pair_within_2_day_window(self, in_memory_db):
        """Happy path: matching pair within 2-day window detected."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        t1 = _insert_txn(conn, account_id="acct-1", amount=-30000, date="2026-03-10")
        t2 = _insert_txn(conn, account_id="acct-2", amount=30000, date="2026-03-12")

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        txn1 = _get_txn(conn, t1)
        txn2 = _get_txn(conn, t2)
        assert txn1["transfer_pair_id"] == txn2["transfer_pair_id"]

    def test_same_account_not_flagged(self, in_memory_db):
        """Edge case: matching amounts on the same account NOT flagged."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")

        t1 = _insert_txn(conn, account_id="acct-1", amount=-50000, date="2026-03-15")
        t2 = _insert_txn(conn, account_id="acct-1", amount=50000, date="2026-03-15")

        count = detect_transfers(conn, 3, 2026)

        assert count == 0
        assert _get_txn(conn, t1)["transfer_pair_id"] is None
        assert _get_txn(conn, t2)["transfer_pair_id"] is None

    def test_dates_3_days_apart_not_flagged(self, in_memory_db):
        """Edge case: matching amounts 3+ days apart NOT flagged."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        t1 = _insert_txn(conn, account_id="acct-1", amount=-50000, date="2026-03-10")
        t2 = _insert_txn(conn, account_id="acct-2", amount=50000, date="2026-03-13")

        count = detect_transfers(conn, 3, 2026)

        assert count == 0
        assert _get_txn(conn, t1)["transfer_pair_id"] is None
        assert _get_txn(conn, t2)["transfer_pair_id"] is None

    def test_three_txns_only_closest_pair_matched(self, in_memory_db):
        """Edge case: three transactions with same amount — only closest pair matched."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")
        _insert_account(conn, "acct-3")

        # Debit on acct-1 on the 10th, credits on acct-2 (11th) and acct-3 (12th).
        t1 = _insert_txn(conn, account_id="acct-1", amount=-20000, date="2026-03-10")
        t2 = _insert_txn(conn, account_id="acct-2", amount=20000, date="2026-03-11")
        t3 = _insert_txn(conn, account_id="acct-3", amount=20000, date="2026-03-12")

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        txn1 = _get_txn(conn, t1)
        txn2 = _get_txn(conn, t2)
        txn3 = _get_txn(conn, t3)
        # t1 and t2 are the closest pair (1 day apart).
        assert txn1["transfer_pair_id"] is not None
        assert txn1["transfer_pair_id"] == txn2["transfer_pair_id"]
        # t3 remains unmatched.
        assert txn3["transfer_pair_id"] is None

    def test_already_linked_not_reprocessed(self, in_memory_db):
        """Edge case: already-linked transfers are not re-processed."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        existing_pair = str(uuid.uuid4())
        t1 = _insert_txn(
            conn,
            account_id="acct-1",
            amount=-50000,
            date="2026-03-15",
            transfer_pair_id=existing_pair,
        )
        t2 = _insert_txn(
            conn,
            account_id="acct-2",
            amount=50000,
            date="2026-03-15",
            transfer_pair_id=existing_pair,
        )

        count = detect_transfers(conn, 3, 2026)

        assert count == 0
        # Pair IDs unchanged.
        assert _get_txn(conn, t1)["transfer_pair_id"] == existing_pair
        assert _get_txn(conn, t2)["transfer_pair_id"] == existing_pair

    def test_detected_transfers_get_label_and_pair_ids(self, in_memory_db):
        """Happy path: detected transfers get 'Transfer' label and linked pair IDs."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        transfer_label = db.get_label_by_name(conn, "Transfer")
        assert transfer_label is not None

        t1 = _insert_txn(conn, account_id="acct-1", amount=-75000, date="2026-03-20")
        t2 = _insert_txn(conn, account_id="acct-2", amount=75000, date="2026-03-20")

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        txn1 = _get_txn(conn, t1)
        txn2 = _get_txn(conn, t2)
        # Both should have Transfer label.
        assert txn1["label_id"] == transfer_label["id"]
        assert txn2["label_id"] == transfer_label["id"]
        # Both should have matching pair IDs.
        assert txn1["transfer_pair_id"] is not None
        assert txn1["transfer_pair_id"] == txn2["transfer_pair_id"]
        # Both should be needs_review.
        assert txn1["review_status"] == "needs_review"
        assert txn2["review_status"] == "needs_review"

    def test_regular_transactions_still_candidates(self, in_memory_db):
        """REGULAR transactions are valid transfer candidates (no type exclusion)."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        t1 = _insert_txn(
            conn,
            account_id="acct-1",
            amount=-50000,
            date="2026-03-15",
            source_type="REGULAR",
        )
        t2 = _insert_txn(
            conn,
            account_id="acct-2",
            amount=50000,
            date="2026-03-15",
            source_type="REGULAR",
        )

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        assert _get_txn(conn, t1)["transfer_pair_id"] is not None
        assert _get_txn(conn, t1)["transfer_pair_id"] == _get_txn(conn, t2)["transfer_pair_id"]

    def test_internal_transfer_type_preferred(self, in_memory_db):
        """INTERNAL_TRANSFER pairs score higher than REGULAR pairs."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")
        _insert_account(conn, "acct-3")

        # Two possible matches for the debit: one INTERNAL_TRANSFER, one REGULAR.
        t1 = _insert_txn(
            conn, account_id="acct-1", amount=-10000, date="2026-03-15",
            source_type="REGULAR",
        )
        t2 = _insert_txn(
            conn, account_id="acct-2", amount=10000, date="2026-03-15",
            source_type="INTERNAL_TRANSFER",
        )
        t3 = _insert_txn(
            conn, account_id="acct-3", amount=10000, date="2026-03-15",
            source_type="REGULAR",
        )

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        # The INTERNAL_TRANSFER match should be preferred.
        txn1 = _get_txn(conn, t1)
        txn2 = _get_txn(conn, t2)
        txn3 = _get_txn(conn, t3)
        assert txn1["transfer_pair_id"] == txn2["transfer_pair_id"]
        assert txn3["transfer_pair_id"] is None

    def test_source_type_none_does_not_crash(self, in_memory_db):
        """source_type=None treated as non-preferred, no crash."""
        conn = in_memory_db
        _setup_db(conn)
        _insert_account(conn, "acct-1")
        _insert_account(conn, "acct-2")

        t1 = _insert_txn(
            conn, account_id="acct-1", amount=-25000, date="2026-03-15",
            source_type=None,
        )
        t2 = _insert_txn(
            conn, account_id="acct-2", amount=25000, date="2026-03-15",
            source_type=None,
        )

        count = detect_transfers(conn, 3, 2026)

        assert count == 1
        assert _get_txn(conn, t1)["transfer_pair_id"] is not None
