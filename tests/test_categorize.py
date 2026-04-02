"""Tests for the categorization orchestrator pipeline."""

import sqlite3
from unittest.mock import patch, call, MagicMock

import pytest

from finmint.categorize import categorize_month
from finmint.db import (
    init_db,
    insert_transaction,
    get_transactions,
)
from finmint.db import get_label_by_name
from tests.conftest import seed_test_categories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db() -> sqlite3.Connection:
    """Create an in-memory DB with schema, default labels, and a test account."""
    conn = init_db(":memory:")
    seed_test_categories(conn)
    conn.execute(
        "INSERT INTO accounts (id, institution_name, account_type, last_four) "
        "VALUES (?, ?, ?, ?)",
        ("acct1", "Test Bank", "checking", "1234"),
    )
    conn.execute(
        "INSERT INTO accounts (id, institution_name, account_type, last_four) "
        "VALUES (?, ?, ?, ?)",
        ("acct2", "Test Credit", "credit_card", "5678"),
    )
    conn.commit()
    return conn


def _insert_txn(conn, txn_id, description, amount, date, account_id="acct1",
                label_id=None):
    """Insert a transaction."""
    insert_transaction(conn, {
        "id": txn_id,
        "account_id": account_id,
        "amount": amount,
        "date": date,
        "description": description,
        "normalized_description": description.upper() if description else None,
        "label_id": label_id,
        "review_status": "needs_review",
        "categorized_by": None,
        "transfer_pair_id": None,
        "source_type": None,
    })


# ---------------------------------------------------------------------------
# Unit tests with mocked components
# ---------------------------------------------------------------------------


class TestPipelineOrder:
    """Verify the pipeline calls components in the correct order."""

    @patch("finmint.categorize.categorize_transactions", return_value=0)
    @patch("finmint.categorize.detect_transfers", return_value=0)
    @patch("finmint.categorize.apply_rules_to_transactions", return_value=0)
    def test_pipeline_calls_in_order(self, mock_rules, mock_transfers, mock_ai):
        """Pipeline applies rules first, then transfers, then AI."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Insert an uncategorized txn so AI step gets triggered
        _insert_txn(conn, "txn-1", "SOME STORE", -1000, "2026-03-15")

        categorize_month(conn, config, 3, 2026)

        mock_rules.assert_called_once_with(conn, 3, 2026)
        mock_transfers.assert_called_once_with(conn, 3, 2026)
        mock_ai.assert_called_once()

    @patch("finmint.categorize.categorize_transactions", return_value=0)
    @patch("finmint.categorize.detect_transfers", return_value=0)
    @patch("finmint.categorize.apply_rules_to_transactions", return_value=3)
    def test_rule_matched_transactions_not_sent_to_ai(
        self, mock_rules, mock_transfers, mock_ai
    ):
        """Rule-matched transactions should not be passed to the AI step."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Insert 3 transactions
        for i in range(3):
            _insert_txn(conn, f"txn-{i}", f"MERCHANT {i}", -1000, "2026-03-15")

        # Simulate rules matching all 3: mark them as categorized
        groceries = get_label_by_name(conn, "Groceries")
        for i in range(3):
            conn.execute(
                "UPDATE transactions SET label_id = ?, categorized_by = 'rule', "
                "review_status = 'auto_accepted' WHERE id = ?",
                (groceries["id"], f"txn-{i}"),
            )
        conn.commit()

        result = categorize_month(conn, config, 3, 2026)

        # AI not called because no uncategorized remain
        mock_ai.assert_not_called()

    @patch("finmint.categorize.categorize_transactions", return_value=0)
    @patch("finmint.categorize.detect_transfers", return_value=1)
    @patch("finmint.categorize.apply_rules_to_transactions", return_value=0)
    def test_transfer_detected_transactions_not_sent_to_ai(
        self, mock_rules, mock_transfers, mock_ai
    ):
        """Transfer-detected transactions should not be passed to the AI step."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Insert 2 transactions that form a transfer pair
        _insert_txn(conn, "txn-a", "TRANSFER OUT", -50000, "2026-03-10", "acct1")
        _insert_txn(conn, "txn-b", "TRANSFER IN", 50000, "2026-03-10", "acct2")

        # Simulate transfer detection: mark them
        transfer_label = get_label_by_name(conn, "Transfer")
        conn.execute(
            "UPDATE transactions SET label_id = ?, transfer_pair_id = 'pair-1', "
            "review_status = 'needs_review' WHERE id IN ('txn-a', 'txn-b')",
            (transfer_label["id"],),
        )
        conn.commit()

        result = categorize_month(conn, config, 3, 2026)

        assert result["transfers_detected"] == 1

    @patch("finmint.categorize.categorize_transactions", return_value=0)
    @patch("finmint.categorize.detect_transfers", return_value=0)
    @patch("finmint.categorize.apply_rules_to_transactions", return_value=5)
    def test_all_matched_by_rules_ai_gets_empty_list(
        self, mock_rules, mock_transfers, mock_ai
    ):
        """When all transactions are matched by rules, AI receives empty list."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Insert 5 transactions, all pre-categorized by rules
        groceries = get_label_by_name(conn, "Groceries")
        for i in range(5):
            _insert_txn(conn, f"txn-{i}", f"STORE {i}", -500, "2026-03-20")
            conn.execute(
                "UPDATE transactions SET label_id = ?, categorized_by = 'rule', "
                "review_status = 'auto_accepted' WHERE id = ?",
                (groceries["id"], f"txn-{i}"),
            )
        conn.commit()

        result = categorize_month(conn, config, 3, 2026)

        assert result["rule_matched"] == 5
        # AI not called because no uncategorized remain
        mock_ai.assert_not_called()
        assert result["ai_categorized"] == 0
        assert result["uncategorized"] == 0

    @patch("finmint.categorize.categorize_transactions", return_value=3)
    @patch("finmint.categorize.detect_transfers", return_value=0)
    @patch("finmint.categorize.apply_rules_to_transactions", return_value=0)
    def test_no_rules_all_go_to_ai(self, mock_rules, mock_transfers, mock_ai):
        """When no rules exist, all uncategorized go to AI."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Insert 3 uncategorized transactions
        for i in range(3):
            _insert_txn(conn, f"txn-{i}", f"UNKNOWN {i}", -2000, "2026-03-05")

        result = categorize_month(conn, config, 3, 2026)

        assert result["rule_matched"] == 0
        assert result["transfers_detected"] == 0
        # AI should receive all 3 transactions
        ai_call_args = mock_ai.call_args
        transactions_arg = ai_call_args[0][2]
        assert len(transactions_arg) == 3
        assert result["ai_categorized"] == 3

    @patch("finmint.categorize.categorize_transactions", return_value=0)
    @patch("finmint.categorize.detect_transfers", return_value=0)
    @patch("finmint.categorize.apply_rules_to_transactions", return_value=0)
    def test_returns_correct_summary_dict(self, mock_rules, mock_transfers, mock_ai):
        """categorize_month returns dict with expected keys."""
        conn = _setup_db()
        config = {}

        result = categorize_month(conn, config, 1, 2026)

        assert "rule_matched" in result
        assert "transfers_detected" in result
        assert "ai_categorized" in result
        assert "uncategorized" in result
        assert isinstance(result["rule_matched"], int)
        assert isinstance(result["transfers_detected"], int)
        assert isinstance(result["ai_categorized"], int)
        assert isinstance(result["uncategorized"], int)


# ---------------------------------------------------------------------------
# Integration tests with real DB
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests using real in-memory DB (no mocks on rules/transfers)."""

    def test_rules_categorize_matching_transactions(self):
        """Copilot-derived rules categorize matching transactions in the pipeline."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        groceries = get_label_by_name(conn, "Groceries")
        # Seed a categorized transaction to act as a rule
        _insert_txn(conn, "txn-seed", "WHOLE FOODS MARKET", -3000, "2026-02-10",
                    label_id=groceries["id"])

        _insert_txn(conn, "txn-1", "WHOLE FOODS MARKET #123", -5000, "2026-03-10")
        _insert_txn(conn, "txn-2", "RANDOM STORE", -2000, "2026-03-12")

        # Mock only AI (we don't want real API calls) and transfers
        with patch("finmint.categorize.categorize_transactions", return_value=0) as mock_ai, \
             patch("finmint.categorize.detect_transfers", return_value=0):
            result = categorize_month(conn, config, 3, 2026)

        assert result["rule_matched"] == 1
        # The unmatched txn should be sent to AI
        ai_txns = mock_ai.call_args[0][2]
        assert len(ai_txns) == 1
        assert ai_txns[0]["id"] == "txn-2"

        # Verify DB state
        txn1 = conn.execute(
            "SELECT * FROM transactions WHERE id = 'txn-1'"
        ).fetchone()
        assert txn1["categorized_by"] == "rule"
        assert txn1["label_id"] == groceries["id"]

    def test_transfers_detected_in_pipeline(self):
        """Transfer detection works within the pipeline."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Insert matching transfer pair (opposite amounts, different accounts, ach type)
        insert_transaction(conn, {
            "id": "txn-debit",
            "account_id": "acct1",
            "amount": -100000,
            "date": "2026-03-15",
            "description": "ACH TRANSFER",
            "normalized_description": "ACH TRANSFER",
            "label_id": None,
            "review_status": "needs_review",
            "categorized_by": None,
            "transfer_pair_id": None,
            "source_type": "ACH",
        })
        insert_transaction(conn, {
            "id": "txn-credit",
            "account_id": "acct2",
            "amount": 100000,
            "date": "2026-03-15",
            "description": "ACH TRANSFER",
            "normalized_description": "ACH TRANSFER",
            "label_id": None,
            "review_status": "needs_review",
            "categorized_by": None,
            "transfer_pair_id": None,
            "source_type": "ACH",
        })

        with patch("finmint.categorize.categorize_transactions", return_value=0):
            result = categorize_month(conn, config, 3, 2026)

        assert result["transfers_detected"] == 1

        # Verify both transactions are labeled as Transfer
        transfer_label = get_label_by_name(conn, "Transfer")
        for tid in ("txn-debit", "txn-credit"):
            txn = conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (tid,)
            ).fetchone()
            assert txn["label_id"] == transfer_label["id"]
            assert txn["transfer_pair_id"] is not None

    def test_full_pipeline_mixed(self):
        """Full pipeline with a mix of rule-matched, transfer, and AI transactions."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        # Seed a categorized transaction to act as a rule for CHIPOTLE
        dining = get_label_by_name(conn, "Dining Out")
        _insert_txn(conn, "txn-seed", "CHIPOTLE", -1000, "2026-02-05",
                    label_id=dining["id"])

        # Transaction 1: matches derived rule
        _insert_txn(conn, "txn-rule", "CHIPOTLE MEXICAN GRILL", -1200, "2026-03-05")

        # Transactions 2-3: transfer pair
        insert_transaction(conn, {
            "id": "txn-xfer-out",
            "account_id": "acct1",
            "amount": -200000,
            "date": "2026-03-10",
            "description": "TRANSFER TO SAVINGS",
            "normalized_description": "TRANSFER TO SAVINGS",
            "label_id": None,
            "review_status": "needs_review",
            "categorized_by": None,
            "transfer_pair_id": None,
            "source_type": "INTERNAL_TRANSFER",
        })
        insert_transaction(conn, {
            "id": "txn-xfer-in",
            "account_id": "acct2",
            "amount": 200000,
            "date": "2026-03-10",
            "description": "TRANSFER FROM CHECKING",
            "normalized_description": "TRANSFER FROM CHECKING",
            "label_id": None,
            "review_status": "needs_review",
            "categorized_by": None,
            "transfer_pair_id": None,
            "source_type": "INTERNAL_TRANSFER",
        })

        # Transaction 4: should go to AI
        _insert_txn(conn, "txn-unknown", "MYSTERIOUS SHOP", -3000, "2026-03-20")

        with patch("finmint.categorize.categorize_transactions", return_value=1) as mock_ai:
            result = categorize_month(conn, config, 3, 2026)

        assert result["rule_matched"] == 1
        assert result["transfers_detected"] == 1
        assert result["ai_categorized"] == 1

        # Verify AI only received the unknown transaction
        ai_txns = mock_ai.call_args[0][2]
        # Filter to those actually uncategorized (categorized_by is None, review_status needs_review)
        uncategorized_ids = [t["id"] for t in ai_txns if t["label_id"] is None]
        assert "txn-unknown" in uncategorized_ids
        assert "txn-rule" not in uncategorized_ids

    def test_idempotent_rerun(self):
        """Running categorize_month twice produces same results."""
        conn = _setup_db()
        config = {"anthropic_api_key": "fake"}

        groceries = get_label_by_name(conn, "Groceries")
        # Seed a categorized transaction to act as a rule
        _insert_txn(conn, "txn-seed", "TRADER JOE", -2000, "2026-02-05",
                    label_id=groceries["id"])

        _insert_txn(conn, "txn-1", "TRADER JOE'S", -4000, "2026-03-08")

        with patch("finmint.categorize.categorize_transactions", return_value=0), \
             patch("finmint.categorize.detect_transfers", return_value=0):
            result1 = categorize_month(conn, config, 3, 2026)

        # Second run: rule already matched, so 0 new matches
        with patch("finmint.categorize.categorize_transactions", return_value=0), \
             patch("finmint.categorize.detect_transfers", return_value=0):
            result2 = categorize_month(conn, config, 3, 2026)

        assert result2["rule_matched"] == 0  # already categorized
        assert result2["uncategorized"] == 0
