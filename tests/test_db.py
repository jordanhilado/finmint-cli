"""Tests for finmint.db — schema, category upsert, and CRUD helpers."""

import sqlite3

import pytest

from finmint.db import (
    get_copilot_id_for_label,
    get_label_by_copilot_id,
    get_label_by_name,
    get_labels,
    get_transactions,
    init_db_with_conn,
    insert_transaction,
    update_transaction_label,
    upsert_category,
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

    def test_labels_table_has_copilot_id_and_icon_columns(
        self, in_memory_db: sqlite3.Connection
    ):
        init_db_with_conn(in_memory_db)
        cur = in_memory_db.execute("PRAGMA table_info(labels)")
        cols = {row[1] for row in cur.fetchall()}
        assert "copilot_id" in cols
        assert "icon" in cols

    def test_transactions_table_has_item_id_column(
        self, in_memory_db: sqlite3.Connection
    ):
        init_db_with_conn(in_memory_db)
        cur = in_memory_db.execute("PRAGMA table_info(transactions)")
        cols = {row[1] for row in cur.fetchall()}
        assert "item_id" in cols


# ---------------------------------------------------------------------------
# Category upsert tests
# ---------------------------------------------------------------------------


class TestUpsertCategory:
    """upsert_category inserts and updates categories keyed on copilot_id."""

    @pytest.fixture(autouse=True)
    def _setup(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        self.conn = in_memory_db

    def test_inserts_new_category(self):
        upsert_category(self.conn, "cat-1", "Groceries", "#2ecc71", "🛒")
        labels = get_labels(self.conn)
        assert len(labels) == 1
        assert labels[0]["name"] == "Groceries"
        assert labels[0]["copilot_id"] == "cat-1"
        assert labels[0]["color"] == "#2ecc71"
        assert labels[0]["icon"] == "🛒"

    def test_updates_existing_category_on_conflict(self):
        upsert_category(self.conn, "cat-1", "Groceries", "#2ecc71", "🛒")
        upsert_category(self.conn, "cat-1", "Food & Groceries", "#00ff00", "🥑")
        labels = get_labels(self.conn)
        assert len(labels) == 1
        assert labels[0]["name"] == "Food & Groceries"
        assert labels[0]["color"] == "#00ff00"
        assert labels[0]["icon"] == "🥑"

    def test_multiple_categories(self):
        upsert_category(self.conn, "cat-1", "Groceries", "#2ecc71", "🛒")
        upsert_category(self.conn, "cat-2", "Dining", "#e74c3c", "🍽️")
        labels = get_labels(self.conn)
        assert len(labels) == 2

    def test_nullable_color_and_icon(self):
        upsert_category(self.conn, "cat-1", "Unknown")
        label = get_labels(self.conn)[0]
        assert label["color"] is None
        assert label["icon"] is None


class TestGetCopilotIdForLabel:
    """get_copilot_id_for_label returns the Copilot category ID for a local label."""

    @pytest.fixture(autouse=True)
    def _setup(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        self.conn = in_memory_db

    def test_returns_copilot_id(self):
        upsert_category(self.conn, "cat-abc", "Groceries")
        label = get_label_by_name(self.conn, "Groceries")
        assert get_copilot_id_for_label(self.conn, label["id"]) == "cat-abc"

    def test_returns_none_for_nonexistent_label(self):
        assert get_copilot_id_for_label(self.conn, 9999) is None


class TestGetLabelByCopilotId:
    """get_label_by_copilot_id returns a local label by its Copilot category ID."""

    @pytest.fixture(autouse=True)
    def _setup(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        self.conn = in_memory_db

    def test_returns_label(self):
        upsert_category(self.conn, "cat-xyz", "Travel", "#8e44ad")
        row = get_label_by_copilot_id(self.conn, "cat-xyz")
        assert row is not None
        assert row["name"] == "Travel"

    def test_returns_none_for_nonexistent(self):
        assert get_label_by_copilot_id(self.conn, "nonexistent") is None


# ---------------------------------------------------------------------------
# Transaction CRUD tests
# ---------------------------------------------------------------------------


class TestTransactions:
    """Transaction insert, retrieve, update helpers."""

    @pytest.fixture(autouse=True)
    def _setup(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        upsert_category(in_memory_db, "cat-groc", "Groceries", "#2ecc71")
        upsert_category(in_memory_db, "cat-shop", "Shopping", "#e67e22")
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

    def test_insert_with_item_id(self):
        insert_transaction(
            self.conn,
            {
                "id": "txn_002",
                "item_id": "item-abc",
                "amount": -1000,
                "date": "2026-03-10",
            },
        )
        row = self.conn.execute(
            "SELECT item_id FROM transactions WHERE id = ?", ("txn_002",)
        ).fetchone()
        assert row["item_id"] == "item-abc"

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
