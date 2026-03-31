"""Tests for finmint.sync — normalize_merchant and sync_month."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from finmint.db import get_transactions, init_db_with_conn, insert_transaction, seed_default_labels
from finmint.sync import SyncResult, normalize_merchant, sync_month
from finmint.teller import TellerAuthError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_CONFIG = {
    "teller": {
        "cert_path": "/tmp/fake-cert.pem",
        "key_path": "/tmp/fake-key.pem",
    }
}


def _seed_account(
    conn: sqlite3.Connection,
    account_id: str = "acc_001",
    access_token: str = "tok_001",
    institution_name: str = "Test Bank",
) -> None:
    """Insert a fake account row."""
    conn.execute(
        "INSERT INTO accounts (id, access_token, institution_name) VALUES (?, ?, ?)",
        (account_id, access_token, institution_name),
    )
    conn.commit()


def _make_teller_txn(
    txn_id: str,
    amount: int,
    date: str,
    description: str = "Some Merchant",
    txn_type: str = "card_payment",
    category: str = "shopping",
) -> dict:
    """Build a fake Teller transaction dict (amounts already in cents)."""
    return {
        "id": txn_id,
        "amount": amount,
        "date": date,
        "description": description,
        "type": txn_type,
        "category": category,
    }


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


class TestSyncMonth:
    """Tests for sync_month()."""

    @pytest.fixture(autouse=True)
    def setup_db(self, in_memory_db: sqlite3.Connection):
        """Initialize schema and seed data for every test."""
        init_db_with_conn(in_memory_db)
        seed_default_labels(in_memory_db)
        self.conn = in_memory_db

    # -- Happy path: inserts new transactions with normalized descriptions --

    @patch("finmint.sync.teller")
    def test_sync_inserts_new_transactions(self, mock_teller):
        _seed_account(self.conn)
        fake_txns = [
            _make_teller_txn("txn_1", -4250, "2026-03-05", "Trader Joe #123 LA"),
            _make_teller_txn("txn_2", -1500, "2026-03-10", "Starbucks Coffee"),
        ]

        mock_client = MagicMock()
        mock_teller.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_teller.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_teller.fetch_transactions.return_value = fake_txns
        mock_teller.TellerAuthError = TellerAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 2
        assert result["total_fetched"] == 2
        assert result["skipped_accounts"] == []

        rows = get_transactions(self.conn, 3, 2026)
        assert len(rows) == 2
        # Check normalized descriptions
        descs = {row["id"]: row["normalized_description"] for row in rows}
        assert descs["txn_1"] == "TRADER JOE LA"
        assert descs["txn_2"] == "STARBUCKS COFFEE"

    # -- Happy path: idempotent — skips already-existing transactions --

    @patch("finmint.sync.teller")
    def test_sync_skips_existing_transactions(self, mock_teller):
        _seed_account(self.conn)
        # Pre-insert a transaction
        insert_transaction(self.conn, {
            "id": "txn_1",
            "account_id": "acc_001",
            "amount": -4250,
            "date": "2026-03-05",
            "description": "Trader Joe #123 LA",
            "normalized_description": "TRADER JOE LA",
        })

        fake_txns = [
            _make_teller_txn("txn_1", -4250, "2026-03-05", "Trader Joe #123 LA"),
            _make_teller_txn("txn_2", -1500, "2026-03-10", "Starbucks Coffee"),
        ]

        mock_client = MagicMock()
        mock_teller.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_teller.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_teller.fetch_transactions.return_value = fake_txns
        mock_teller.TellerAuthError = TellerAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 1  # only txn_2 is new
        assert result["total_fetched"] == 2
        rows = get_transactions(self.conn, 3, 2026)
        assert len(rows) == 2

    # -- Edge case: no transactions returned --

    @patch("finmint.sync.teller")
    def test_sync_no_transactions_returns_zero(self, mock_teller):
        _seed_account(self.conn)

        mock_client = MagicMock()
        mock_teller.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_teller.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_teller.fetch_transactions.return_value = []
        mock_teller.TellerAuthError = TellerAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 0
        assert result["total_fetched"] == 0

    # -- Happy path: current month always re-fetches --

    @patch("finmint.sync._is_current_month", return_value=True)
    @patch("finmint.sync.teller")
    def test_sync_current_month_always_refetches(self, mock_teller, _mock_current):
        _seed_account(self.conn)
        # Pre-insert a transaction for the month
        insert_transaction(self.conn, {
            "id": "txn_existing",
            "account_id": "acc_001",
            "amount": -1000,
            "date": "2026-03-01",
            "description": "Old Txn",
            "normalized_description": "OLD TXN",
        })

        fake_txns = [
            _make_teller_txn("txn_new", -2000, "2026-03-15", "New Merchant"),
        ]

        mock_client = MagicMock()
        mock_teller.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_teller.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_teller.fetch_transactions.return_value = fake_txns
        mock_teller.TellerAuthError = TellerAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026)

        # Should have fetched despite existing data (current month)
        assert result["total_fetched"] == 1
        assert result["new_count"] == 1
        mock_teller.fetch_transactions.assert_called_once()

    # -- Happy path: past month with existing data skips fetch (unless force) --

    @patch("finmint.sync._is_current_month", return_value=False)
    @patch("finmint.sync.teller")
    def test_sync_past_month_skips_if_data_exists(self, mock_teller, _mock_current):
        _seed_account(self.conn)
        # Pre-insert a transaction for February 2026
        insert_transaction(self.conn, {
            "id": "txn_feb",
            "account_id": "acc_001",
            "amount": -1000,
            "date": "2026-02-15",
            "description": "Old Txn",
            "normalized_description": "OLD TXN",
        })

        mock_teller.TellerAuthError = TellerAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 2, 2026)

        # Should NOT have called Teller at all
        mock_teller.create_client.assert_not_called()
        assert result["new_count"] == 0
        assert result["total_fetched"] == 0

    @patch("finmint.sync._is_current_month", return_value=False)
    @patch("finmint.sync.teller")
    def test_sync_past_month_fetches_with_force(self, mock_teller, _mock_current):
        _seed_account(self.conn)
        # Pre-insert a transaction
        insert_transaction(self.conn, {
            "id": "txn_feb",
            "account_id": "acc_001",
            "amount": -1000,
            "date": "2026-02-15",
            "description": "Old Txn",
            "normalized_description": "OLD TXN",
        })

        fake_txns = [
            _make_teller_txn("txn_feb_new", -500, "2026-02-20", "New Feb Merchant"),
        ]

        mock_client = MagicMock()
        mock_teller.create_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_teller.create_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_teller.fetch_transactions.return_value = fake_txns
        mock_teller.TellerAuthError = TellerAuthError

        result = sync_month(self.conn, FAKE_CONFIG, 2, 2026, force=True)

        # Should have fetched because force=True
        mock_teller.fetch_transactions.assert_called_once()
        assert result["new_count"] == 1
        assert result["total_fetched"] == 1

    # -- Error path: TellerAuthError on one account, sync remaining --

    @patch("finmint.sync.teller")
    def test_teller_auth_error_skips_account_syncs_remaining(self, mock_teller):
        _seed_account(self.conn, "acc_001", "tok_001", "Good Bank")
        _seed_account(self.conn, "acc_002", "tok_002", "Bad Bank")

        mock_teller.TellerAuthError = TellerAuthError

        # First account succeeds, second raises TellerAuthError
        good_txns = [
            _make_teller_txn("txn_good", -3000, "2026-03-05", "Good Merchant"),
        ]

        call_count = {"n": 0}

        def fake_create_client(config, token):
            ctx = MagicMock()
            client = MagicMock()
            ctx.__enter__ = MagicMock(return_value=client)
            ctx.__exit__ = MagicMock(return_value=False)

            if token == "tok_002":
                # Simulate auth error when entering context
                def raise_auth(*a, **kw):
                    raise TellerAuthError("Token expired")
                ctx.__enter__ = raise_auth
            return ctx

        mock_teller.create_client.side_effect = fake_create_client
        mock_teller.fetch_transactions.return_value = good_txns

        result = sync_month(self.conn, FAKE_CONFIG, 3, 2026, force=True)

        assert result["new_count"] == 1
        assert result["total_fetched"] == 1
        assert len(result["skipped_accounts"]) == 1
        assert "Bad Bank" in result["skipped_accounts"][0]
        assert "token may be expired" in result["skipped_accounts"][0]
