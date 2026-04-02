"""Tests for finmint.sync — normalize_merchant, sync_categories, and sync_month."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from finmint.db import (
    get_labels,
    get_transactions,
    init_db_with_conn,
    insert_transaction,
    upsert_category,
)
from finmint.sync import SyncResult, normalize_merchant, sync_categories, sync_month
from finmint.copilot import CopilotAuthError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_CONFIG = {
    "copilot": {
        "token": "fake-jwt-token",
    },
    "claude": {
        "api_key_env": "ANTHROPIC_API_KEY",
    },
}


def _make_copilot_account(
    account_id: str = "acc_001",
    name: str = "Checking",
    account_type: str = "depository",
    sub_type: str = "checking",
    mask: str = "1234",
    institution_name: str = "Test Bank",
) -> dict:
    """Build a fake Copilot account dict."""
    return {
        "id": account_id,
        "name": name,
        "type": account_type,
        "sub_type": sub_type,
        "mask": mask,
        "institution_name": institution_name,
    }


def _make_copilot_txn(
    txn_id: str,
    account_id: str,
    amount: int,
    date: str,
    description: str = "Some Merchant",
    source_type: str = "card_payment",
    item_id: str = "item_001",
    category_id: str | None = None,
    is_reviewed: bool = False,
    user_notes: str | None = None,
) -> dict:
    """Build a fake Copilot transaction dict (amounts already in cents)."""
    return {
        "id": txn_id,
        "account_id": account_id,
        "item_id": item_id,
        "amount": amount,
        "date": date,
        "description": description,
        "source_type": source_type,
        "category_id": category_id,
        "is_reviewed": is_reviewed,
        "user_notes": user_notes,
    }


FAKE_CATEGORIES = [
    {"id": "cat-groc", "name": "Groceries", "color": "green", "icon": "🛒"},
    {"id": "cat-din", "name": "Dining", "color": "red", "icon": "🍽️"},
]


# ---------------------------------------------------------------------------
# normalize_merchant tests
# ---------------------------------------------------------------------------


class TestNormalizeMerchant:
    """Tests for normalize_merchant()."""

    def test_strips_trailing_hash_digits_and_collapses_whitespace(self):
        result = normalize_merchant("Trader Joe #123 Los Angeles")
        assert result == "TRADER JOE LOS ANGELES"

    def test_strips_multiple_hash_patterns(self):
        result = normalize_merchant("Store #45 Location #67")
        assert result == "STORE LOCATION"

    def test_already_clean_string(self):
        result = normalize_merchant("WHOLE FOODS")
        assert result == "WHOLE FOODS"

    def test_empty_string(self):
        assert normalize_merchant("") == ""

    def test_none(self):
        assert normalize_merchant(None) == ""

    def test_whitespace_only(self):
        assert normalize_merchant("   ") == ""

    def test_collapses_multiple_spaces(self):
        result = normalize_merchant("Target   Store   East")
        assert result == "TARGET STORE EAST"

    def test_uppercases(self):
        result = normalize_merchant("starbucks coffee")
        assert result == "STARBUCKS COFFEE"


# ---------------------------------------------------------------------------
# sync_month tests
# ---------------------------------------------------------------------------


class TestSyncCategories:
    """Tests for sync_categories()."""

    @pytest.fixture(autouse=True)
    def setup_db(self, in_memory_db: sqlite3.Connection):
        init_db_with_conn(in_memory_db)
        self.conn = in_memory_db

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync.copilot")
    def test_sync_categories_upserts_labels(self, mock_copilot, _mock_get_token):
        mock_client = MagicMock()
        mock_copilot.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_copilot.fetch_categories.return_value = FAKE_CATEGORIES

        count = sync_categories(self.conn)

        assert count == 2
        labels = get_labels(self.conn)
        assert len(labels) == 2
        assert labels[0]["name"] == "Groceries"
        assert labels[0]["copilot_id"] == "cat-groc"


class TestSyncMonth:
    """Tests for sync_month()."""

    @pytest.fixture(autouse=True)
    def setup_db(self, in_memory_db: sqlite3.Connection):
        """Initialize schema and seed categories for every test."""
        init_db_with_conn(in_memory_db)
        for cat in FAKE_CATEGORIES:
            upsert_category(in_memory_db, cat["id"], cat["name"], cat.get("color"), cat.get("icon"))
        self.conn = in_memory_db

    # -- Happy path: discovers accounts, fetches transactions, upserts both --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync.copilot")
    def test_sync_inserts_new_transactions(self, mock_copilot, _mock_get_token):
        fake_accounts = [
            _make_copilot_account("acc_001", "Checking", "depository", "checking", "1234", "Test Bank"),
        ]
        fake_txns = [
            _make_copilot_txn("txn_1", "acc_001", -4250, "2026-03-05", "Trader Joe #123 LA"),
            _make_copilot_txn("txn_2", "acc_001", -1500, "2026-03-10", "Starbucks Coffee"),
        ]

        mock_client = MagicMock()
        mock_copilot.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_copilot.fetch_categories.return_value = FAKE_CATEGORIES
        mock_copilot.fetch_accounts.return_value = fake_accounts
        mock_copilot.fetch_transactions.return_value = fake_txns
        mock_copilot.CopilotAuthError = CopilotAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 2
        assert result["total_fetched"] == 2
        assert result["error"] is None

        rows = get_transactions(self.conn, 3, 2026)
        assert len(rows) == 2
        # Check normalized descriptions
        descs = {row["id"]: row["normalized_description"] for row in rows}
        assert descs["txn_1"] == "TRADER JOE LA"
        assert descs["txn_2"] == "STARBUCKS COFFEE"

        # Verify account was upserted
        cur = self.conn.execute("SELECT * FROM accounts WHERE id = ?", ("acc_001",))
        account_row = cur.fetchone()
        assert account_row is not None
        assert account_row["institution_name"] == "Test Bank"
        assert account_row["account_type"] == "depository"
        assert account_row["last_four"] == "1234"

    # -- Happy path: idempotent — existing transactions skipped via INSERT OR IGNORE --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync.copilot")
    def test_sync_skips_existing_transactions(self, mock_copilot, _mock_get_token):
        # Pre-insert account and transaction
        self.conn.execute(
            "INSERT INTO accounts (id, institution_name) VALUES (?, ?)",
            ("acc_001", "Test Bank"),
        )
        self.conn.commit()
        insert_transaction(self.conn, {
            "id": "txn_1",
            "account_id": "acc_001",
            "amount": -4250,
            "date": "2026-03-05",
            "description": "Trader Joe #123 LA",
            "normalized_description": "TRADER JOE LA",
        })

        fake_accounts = [_make_copilot_account()]
        fake_txns = [
            _make_copilot_txn("txn_1", "acc_001", -4250, "2026-03-05", "Trader Joe #123 LA"),
            _make_copilot_txn("txn_2", "acc_001", -1500, "2026-03-10", "Starbucks Coffee"),
        ]

        mock_client = MagicMock()
        mock_copilot.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_copilot.fetch_categories.return_value = FAKE_CATEGORIES
        mock_copilot.fetch_accounts.return_value = fake_accounts
        mock_copilot.fetch_transactions.return_value = fake_txns
        mock_copilot.CopilotAuthError = CopilotAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 1  # only txn_2 is new
        assert result["total_fetched"] == 2
        rows = get_transactions(self.conn, 3, 2026)
        assert len(rows) == 2

    # -- Edge case: 0 accounts -> sync completes with 0 transactions --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync.copilot")
    def test_sync_zero_accounts_returns_zero(self, mock_copilot, _mock_get_token):
        mock_client = MagicMock()
        mock_copilot.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_copilot.fetch_categories.return_value = FAKE_CATEGORIES
        mock_copilot.fetch_accounts.return_value = []
        mock_copilot.fetch_transactions.return_value = []
        mock_copilot.CopilotAuthError = CopilotAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 0
        assert result["total_fetched"] == 0
        assert result["error"] is None

    # -- Happy path: current month always re-fetches --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync._is_current_month", return_value=True)
    @patch("finmint.sync.copilot")
    def test_sync_current_month_always_refetches(self, mock_copilot, _mock_current, _mock_get_token):
        # Pre-insert account and transaction for the month
        self.conn.execute(
            "INSERT INTO accounts (id, institution_name) VALUES (?, ?)",
            ("acc_001", "Test Bank"),
        )
        self.conn.commit()
        insert_transaction(self.conn, {
            "id": "txn_existing",
            "account_id": "acc_001",
            "amount": -1000,
            "date": "2026-03-01",
            "description": "Old Txn",
            "normalized_description": "OLD TXN",
        })

        fake_accounts = [_make_copilot_account()]
        fake_txns = [
            _make_copilot_txn("txn_new", "acc_001", -2000, "2026-03-15", "New Merchant"),
        ]

        mock_client = MagicMock()
        mock_copilot.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_copilot.fetch_categories.return_value = FAKE_CATEGORIES
        mock_copilot.fetch_accounts.return_value = fake_accounts
        mock_copilot.fetch_transactions.return_value = fake_txns
        mock_copilot.CopilotAuthError = CopilotAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026)

        # Should have fetched despite existing data (current month)
        assert result["total_fetched"] == 1
        assert result["new_count"] == 1
        mock_copilot.fetch_transactions.assert_called_once()

    # -- Happy path: past month with existing data skips fetch (unless force) --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync._is_current_month", return_value=False)
    @patch("finmint.sync.copilot")
    def test_sync_past_month_skips_if_data_exists(self, mock_copilot, _mock_current, _mock_get_token):
        # Pre-insert account and transaction for February 2026
        self.conn.execute(
            "INSERT INTO accounts (id, institution_name) VALUES (?, ?)",
            ("acc_001", "Test Bank"),
        )
        self.conn.commit()
        insert_transaction(self.conn, {
            "id": "txn_feb",
            "account_id": "acc_001",
            "amount": -1000,
            "date": "2026-02-15",
            "description": "Old Txn",
            "normalized_description": "OLD TXN",
        })

        mock_copilot.CopilotAuthError = CopilotAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 2, 2026)

        # Should NOT have called Copilot at all
        mock_copilot.create_client.assert_not_called()
        assert result["new_count"] == 0
        assert result["total_fetched"] == 0

    # -- Integration: force=True re-fetches past month --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync._is_current_month", return_value=False)
    @patch("finmint.sync.copilot")
    def test_sync_past_month_fetches_with_force(self, mock_copilot, _mock_current, _mock_get_token):
        # Pre-insert account and transaction
        self.conn.execute(
            "INSERT INTO accounts (id, institution_name) VALUES (?, ?)",
            ("acc_001", "Test Bank"),
        )
        self.conn.commit()
        insert_transaction(self.conn, {
            "id": "txn_feb",
            "account_id": "acc_001",
            "amount": -1000,
            "date": "2026-02-15",
            "description": "Old Txn",
            "normalized_description": "OLD TXN",
        })

        fake_accounts = [_make_copilot_account()]
        fake_txns = [
            _make_copilot_txn("txn_feb_new", "acc_001", -500, "2026-02-20", "New Feb Merchant"),
        ]

        mock_client = MagicMock()
        mock_copilot.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_copilot.fetch_categories.return_value = FAKE_CATEGORIES
        mock_copilot.fetch_accounts.return_value = fake_accounts
        mock_copilot.fetch_transactions.return_value = fake_txns
        mock_copilot.CopilotAuthError = CopilotAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 2, 2026, force=True)

        # Should have fetched because force=True
        mock_copilot.fetch_transactions.assert_called_once()
        assert result["new_count"] == 1
        assert result["total_fetched"] == 1

    # -- Error path: CopilotAuthError sets result["error"] with clear message --

    @patch("finmint.sync.get_token", return_value="fake-jwt-token")
    @patch("finmint.sync.copilot")
    def test_copilot_auth_error_sets_error_message(self, mock_copilot, _mock_get_token):
        mock_copilot.CopilotAuthError = CopilotAuthError
        mock_copilot.create_client.return_value.__enter__ = MagicMock(
            side_effect=CopilotAuthError("Token expired")
        )
        mock_copilot.create_client.return_value.__exit__ = MagicMock(return_value=False)

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["error"] is not None
        assert "Token expired or invalid" in result["error"]
        assert "finmint token" in result["error"]
        assert result["new_count"] == 0
        assert result["total_fetched"] == 0
