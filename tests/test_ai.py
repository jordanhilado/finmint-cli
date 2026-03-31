"""Tests for AI categorization and summary generation."""

import json
from unittest.mock import MagicMock, patch

from finmint import ai, db


def _setup(conn):
    """Initialize schema and seed labels."""
    db.init_db_with_conn(conn)
    db.seed_default_labels(conn)


def _get_label_id(conn, name):
    row = db.get_label_by_name(conn, name)
    assert row is not None, f"Label {name!r} not found"
    return row["id"]


def _insert_txn(conn, txn_id, date, description, label_id=None, categorized_by=None):
    """Insert a minimal transaction for testing."""
    db.insert_transaction(conn, {
        "id": txn_id,
        "amount": -1500,
        "date": date,
        "description": description,
        "normalized_description": description.upper(),
        "label_id": label_id,
        "review_status": "needs_review",
        "categorized_by": categorized_by,
    })


def _mock_claude_response(text):
    """Build a mock Anthropic messages response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


CONFIG = {"claude": {"api_key_env": "ANTHROPIC_API_KEY"}}


class TestCategorizeTransactions:
    """Tests for categorize_transactions()."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_happy_path_assigns_correct_labels(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        _insert_txn(in_memory_db, "t1", "2026-03-15", "TRADER JOES")
        _insert_txn(in_memory_db, "t2", "2026-03-16", "CHIPOTLE")

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(
            json.dumps({"1": "Groceries", "2": "Dining Out"})
        )

        txns = db.get_transactions(in_memory_db, 3, 2026)
        count = ai.categorize_transactions(CONFIG, in_memory_db, txns)

        assert count == 2

        row1 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 't1'"
        ).fetchone()
        assert row1["label_id"] == _get_label_id(in_memory_db, "Groceries")
        assert row1["categorized_by"] == "ai"
        assert row1["review_status"] == "needs_review"

        row2 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 't2'"
        ).fetchone()
        assert row2["label_id"] == _get_label_id(in_memory_db, "Dining Out")

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_skips_already_categorized(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        _insert_txn(
            in_memory_db, "t1", "2026-03-15", "TRADER JOES",
            label_id=groceries_id, categorized_by="rule",
        )
        _insert_txn(in_memory_db, "t2", "2026-03-16", "CHIPOTLE")

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        # Only 1 uncategorized, so response maps seq 1 only
        mock_client.messages.create.return_value = _mock_claude_response(
            json.dumps({"1": "Dining Out"})
        )

        txns = db.get_transactions(in_memory_db, 3, 2026)
        count = ai.categorize_transactions(CONFIG, in_memory_db, txns)

        assert count == 1
        # t1 should still be rule-categorized
        row1 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 't1'"
        ).fetchone()
        assert row1["categorized_by"] == "rule"
        assert row1["label_id"] == groceries_id

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_batching_splits_over_200(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        # Insert 250 uncategorized transactions
        for i in range(250):
            _insert_txn(
                in_memory_db, f"t{i}", "2026-03-15", f"MERCHANT_{i}"
            )

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Each batch returns all items as Groceries
        def side_effect(**kwargs):
            user_msg = kwargs["messages"][0]["content"]
            # Count how many lines have sequences
            lines = [l for l in user_msg.split("\n") if l.strip() and ":" in l and "$" in l]
            mapping = {}
            for line in lines:
                seq = line.strip().split(":")[0]
                mapping[seq] = "Groceries"
            return _mock_claude_response(json.dumps(mapping))

        mock_client.messages.create.side_effect = side_effect

        txns = db.get_transactions(in_memory_db, 3, 2026)
        count = ai.categorize_transactions(CONFIG, in_memory_db, txns)

        # Should have made 3 API calls: 100 + 100 + 50
        assert mock_client.messages.create.call_count == 3
        assert count == 250

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_unknown_label_skipped(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        _insert_txn(in_memory_db, "t1", "2026-03-15", "TRADER JOES")
        _insert_txn(in_memory_db, "t2", "2026-03-16", "MYSTERY SHOP")

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(
            json.dumps({"1": "Groceries", "2": "FakeCategory"})
        )

        txns = db.get_transactions(in_memory_db, 3, 2026)
        count = ai.categorize_transactions(CONFIG, in_memory_db, txns)

        # Only t1 should be categorized; t2 has unknown label
        assert count == 1

        row2 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 't2'"
        ).fetchone()
        assert row2["label_id"] is None

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_api_error_raises_no_partial_corruption(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        _insert_txn(in_memory_db, "t1", "2026-03-15", "TRADER JOES")
        _insert_txn(in_memory_db, "t2", "2026-03-16", "CHIPOTLE")

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic_api_error()

        txns = db.get_transactions(in_memory_db, 3, 2026)

        try:
            ai.categorize_transactions(CONFIG, in_memory_db, txns)
            assert False, "Should have raised"
        except Exception:
            pass

        # No transactions should be modified
        row1 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 't1'"
        ).fetchone()
        assert row1["label_id"] is None
        assert row1["categorized_by"] is None

    def test_no_uncategorized_returns_zero(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        _insert_txn(
            in_memory_db, "t1", "2026-03-15", "TRADER JOES",
            label_id=groceries_id, categorized_by="rule",
        )

        txns = db.get_transactions(in_memory_db, 3, 2026)
        count = ai.categorize_transactions(CONFIG, in_memory_db, txns)
        assert count == 0


class TestGenerateMonthlySummary:
    """Tests for generate_monthly_summary()."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_includes_category_totals(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        _insert_txn(
            in_memory_db, "t1", "2026-03-15", "TRADER JOES",
            label_id=groceries_id, categorized_by="rule",
        )
        _insert_txn(
            in_memory_db, "t2", "2026-03-16", "CHIPOTLE",
            label_id=dining_id, categorized_by="ai",
        )

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(
            "Your March spending was $30.00 total, with $15.00 on Groceries and $15.00 on Dining Out."
        )

        summary = ai.generate_monthly_summary(CONFIG, in_memory_db, 3, 2026)

        assert "March" in summary or "30" in summary
        # Verify the prompt included category totals
        call_kwargs = mock_client.messages.create.call_args
        user_msg = call_kwargs.kwargs["messages"][0]["content"]
        assert "Groceries" in user_msg
        assert "Dining Out" in user_msg

        # Verify cached in ai_summaries
        cached = in_memory_db.execute(
            "SELECT * FROM ai_summaries WHERE period_type = 'monthly' AND period_key = '2026-03'"
        ).fetchone()
        assert cached is not None
        assert cached["summary_text"] == summary

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_omits_comparison_with_less_than_3_months(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        # Only 1 month of data (March 2026), no prior months
        _insert_txn(
            in_memory_db, "t1", "2026-03-15", "TRADER JOES",
            label_id=groceries_id, categorized_by="rule",
        )

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(
            "Your March spending was $15.00, all on Groceries. Not enough history for comparison."
        )

        summary = ai.generate_monthly_summary(CONFIG, in_memory_db, 3, 2026)
        assert summary is not None

        # Verify prompt mentions lack of trailing comparison
        call_kwargs = mock_client.messages.create.call_args
        user_msg = call_kwargs.kwargs["messages"][0]["content"]
        assert "Less than 3 months" in user_msg or "no trailing" in user_msg.lower()

    def test_no_transactions_returns_message(self, in_memory_db):
        _setup(in_memory_db)
        summary = ai.generate_monthly_summary(CONFIG, in_memory_db, 3, 2026)
        assert summary == "No categorized transactions for this month."


class TestGenerateYearlySummary:
    """Tests for generate_yearly_summary()."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-key"})
    @patch("finmint.ai.anthropic.Anthropic")
    def test_yearly_summary_generated(self, mock_anthropic_cls, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        _insert_txn(
            in_memory_db, "t1", "2026-01-15", "TRADER JOES",
            label_id=groceries_id, categorized_by="rule",
        )
        _insert_txn(
            in_memory_db, "t2", "2026-03-15", "WHOLE FOODS",
            label_id=groceries_id, categorized_by="rule",
        )

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(
            "Year-to-date: $30.00 on Groceries across 2 months."
        )

        summary = ai.generate_yearly_summary(CONFIG, in_memory_db, 2026)
        assert "30" in summary

        # Verify cached
        cached = in_memory_db.execute(
            "SELECT * FROM ai_summaries WHERE period_type = 'yearly' AND period_key = '2026'"
        ).fetchone()
        assert cached is not None

    def test_no_transactions_returns_message(self, in_memory_db):
        _setup(in_memory_db)
        summary = ai.generate_yearly_summary(CONFIG, in_memory_db, 2026)
        assert summary == "No categorized transactions for this year."


def anthropic_api_error():
    """Create an exception that simulates an Anthropic API error."""
    return Exception("API error: rate limit exceeded")
