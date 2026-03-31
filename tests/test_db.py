"""Tests for finmint.db — schema, seed data, and CRUD helpers."""

import sqlite3

import pytest

from finmint.db import (
    get_labels,
    get_label_by_name,
    get_transactions,
    init_db_with_conn,
    insert_transaction,
    seed_default_labels,
    update_transaction_label,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestInitDb:
    """init_db creates all tables and indexes."""

    def test_creates_all_tables(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        cur = in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = sorted(row["name"] for row in cur.fetchall())
        assert tables == [
            "accounts",
            "ai_summaries",
            "labels",
            "merchant_rules",
            "transactions",
        ]

    def test_creates_indexes(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        cur = in_memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indexes = sorted(row["name"] for row in cur.fetchall())
        assert indexes == [
            "idx_merchant_rules_pattern",
            "idx_transactions_account_date",
            "idx_transactions_date",
            "idx_transactions_review_status",
            "idx_transactions_transfer_pair",
        ]

    def test_idempotent(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        init_db_with_conn(in_memory_db)  # second call should not error


# ---------------------------------------------------------------------------
# Seed labels tests
# ---------------------------------------------------------------------------


class TestSeedDefaultLabels:
    """seed_default_labels populates 16 labels correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        self.conn = in_memory_db

    def test_inserts_16_labels(self):
        seed_default_labels(self.conn)
        labels = get_labels(self.conn)
        assert len(labels) == 16

    def test_transfer_is_protected(self):
        seed_default_labels(self.conn)
        transfer = get_label_by_name(self.conn, "Transfer")
        assert transfer is not None
        assert transfer["is_protected"] == 1

    def test_income_is_protected(self):
        seed_default_labels(self.conn)
        income = get_label_by_name(self.conn, "Income")
        assert income is not None
        assert income["is_protected"] == 1

    def test_non_protected_label(self):
        seed_default_labels(self.conn)
        groceries = get_label_by_name(self.conn, "Groceries")
        assert groceries is not None
        assert groceries["is_protected"] == 0

    def test_all_are_default(self):
        seed_default_labels(self.conn)
        labels = get_labels(self.conn)
        assert all(label["is_default"] == 1 for label in labels)

    def test_idempotent(self):
        seed_default_labels(self.conn)
        seed_default_labels(self.conn)
        labels = get_labels(self.conn)
        assert len(labels) == 16


# ---------------------------------------------------------------------------
# Transaction CRUD tests
# ---------------------------------------------------------------------------


class TestTransactions:
    """Transaction insert, retrieve, update helpers."""

    @pytest.fixture(autouse=True)
    def _setup(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        seed_default_labels(in_memory_db)
        self.conn = in_memory_db

    def test_insert_and_retrieve(self):
        insert_transaction(
            self.conn,
            {
                "id": "txn_001",
                "amount": -6742,
                "date": "2026-03-15",
                "description": "TRADER JOE #123",
            },
        )
        rows = get_transactions(self.conn, month=3, year=2026)
        assert len(rows) == 1
        assert rows[0]["id"] == "txn_001"
        assert rows[0]["amount"] == -6742
        assert rows[0]["review_status"] == "needs_review"

    def test_get_transactions_filters_by_month(self):
        for txn_id, date in [
            ("txn_mar", "2026-03-10"),
            ("txn_apr", "2026-04-05"),
            ("txn_feb", "2026-02-28"),
        ]:
            insert_transaction(
                self.conn,
                {"id": txn_id, "amount": -1000, "date": date},
            )
        march = get_transactions(self.conn, month=3, year=2026)
        assert [r["id"] for r in march] == ["txn_mar"]

    def test_get_transactions_empty_month(self):
        rows = get_transactions(self.conn, month=7, year=2026)
        assert rows == []

    def test_get_transactions_december_boundary(self):
        insert_transaction(
            self.conn,
            {"id": "txn_dec", "amount": -500, "date": "2026-12-15"},
        )
        insert_transaction(
            self.conn,
            {"id": "txn_jan_next", "amount": -500, "date": "2027-01-01"},
        )
        dec = get_transactions(self.conn, month=12, year=2026)
        assert len(dec) == 1
        assert dec[0]["id"] == "txn_dec"

    def test_update_transaction_label(self):
        groceries = get_label_by_name(self.conn, "Groceries")
        insert_transaction(
            self.conn,
            {
                "id": "txn_002",
                "amount": -2500,
                "date": "2026-03-20",
                "description": "WHOLE FOODS",
            },
        )
        update_transaction_label(
            self.conn,
            txn_id="txn_002",
            label_id=groceries["id"],
            categorized_by="manual",
            status="reviewed",
        )
        rows = get_transactions(self.conn, month=3, year=2026)
        txn = rows[0]
        assert txn["label_id"] == groceries["id"]
        assert txn["categorized_by"] == "manual"
        assert txn["review_status"] == "reviewed"

    def test_full_round_trip(self):
        """Integration: insert, update label, query back with new label."""
        insert_transaction(
            self.conn,
            {
                "id": "txn_rt",
                "amount": -15099,
                "date": "2026-03-05",
                "description": "AMAZON MARKETPLACE",
            },
        )
        shopping = get_label_by_name(self.conn, "Shopping")
        update_transaction_label(
            self.conn,
            txn_id="txn_rt",
            label_id=shopping["id"],
            categorized_by="ai",
            status="auto_accepted",
        )
        rows = get_transactions(self.conn, month=3, year=2026)
        txn = next(r for r in rows if r["id"] == "txn_rt")
        assert txn["amount"] == -15099
        assert txn["label_id"] == shopping["id"]
        assert txn["categorized_by"] == "ai"
        assert txn["review_status"] == "auto_accepted"
