"""Tests for the Copilot-derived merchant rules engine."""

from finmint import db, rules
from tests.conftest import seed_test_categories


def _setup(conn):
    """Initialize schema and seed labels."""
    db.init_db_with_conn(conn)
    seed_test_categories(conn)


def _get_label_id(conn, name):
    row = db.get_label_by_name(conn, name)
    assert row is not None, f"Label {name!r} not found"
    return row["id"]


def _insert_txn(conn, txn_id, date, normalized_description, label_id=None):
    """Insert a minimal transaction for testing."""
    db.insert_transaction(conn, {
        "id": txn_id,
        "amount": -1000,
        "date": date,
        "description": normalized_description,
        "normalized_description": normalized_description,
        "label_id": label_id,
        "review_status": "needs_review",
    })


class TestMatchRules:
    def test_derives_rule_from_categorized_transactions(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        # A previously categorized transaction acts as a rule
        _insert_txn(
            in_memory_db, "txn-old", "2026-02-10",
            "TRADER JOE", label_id=groceries_id,
        )

        result = rules.match_rules(in_memory_db, "TRADER JOE #123 SAN FRANCISCO")
        assert result is not None
        assert result["label_id"] == groceries_id

    def test_longest_match_wins(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        shopping_id = _get_label_id(in_memory_db, "Shopping")

        # Short match
        _insert_txn(
            in_memory_db, "txn-1", "2026-02-10",
            "TRADER", label_id=shopping_id,
        )
        # Longer match
        _insert_txn(
            in_memory_db, "txn-2", "2026-02-11",
            "TRADER JOE", label_id=groceries_id,
        )

        result = rules.match_rules(in_memory_db, "TRADER JOE #456")
        assert result is not None
        assert result["label_id"] == groceries_id
        assert result["pattern"] == "TRADER JOE"

    def test_no_match_returns_none(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        _insert_txn(
            in_memory_db, "txn-1", "2026-02-10",
            "TRADER JOE", label_id=groceries_id,
        )

        result = rules.match_rules(in_memory_db, "WHOLE FOODS MARKET")
        assert result is None

    def test_most_frequent_category_wins(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        # 2 transactions as Groceries, 1 as Dining
        _insert_txn(
            in_memory_db, "txn-1", "2026-02-10",
            "TRADER JOE", label_id=groceries_id,
        )
        _insert_txn(
            in_memory_db, "txn-2", "2026-02-11",
            "TRADER JOE", label_id=groceries_id,
        )
        _insert_txn(
            in_memory_db, "txn-3", "2026-02-12",
            "TRADER JOE", label_id=dining_id,
        )

        result = rules.match_rules(in_memory_db, "TRADER JOE #999")
        assert result is not None
        assert result["label_id"] == groceries_id

    def test_uncategorized_transactions_not_used_as_rules(self, in_memory_db):
        _setup(in_memory_db)

        # Transaction with no label — should not generate a rule
        _insert_txn(in_memory_db, "txn-1", "2026-02-10", "TRADER JOE")

        result = rules.match_rules(in_memory_db, "TRADER JOE #123")
        assert result is None


class TestGetAllRules:
    def test_returns_sorted_with_label_names(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        _insert_txn(
            in_memory_db, "txn-1", "2026-02-10",
            "TRADER JOE", label_id=groceries_id,
        )
        _insert_txn(
            in_memory_db, "txn-2", "2026-02-11",
            "CHIPOTLE", label_id=dining_id,
        )

        all_rules = rules.get_all_rules(in_memory_db)
        assert len(all_rules) == 2
        # Alphabetical: CHIPOTLE before TRADER JOE
        assert all_rules[0]["pattern"] == "CHIPOTLE"
        assert all_rules[0]["label_name"] == "Dining Out"
        assert all_rules[1]["pattern"] == "TRADER JOE"
        assert all_rules[1]["label_name"] == "Groceries"

    def test_includes_transaction_count(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        _insert_txn(
            in_memory_db, "txn-1", "2026-02-10",
            "TRADER JOE", label_id=groceries_id,
        )
        _insert_txn(
            in_memory_db, "txn-2", "2026-02-11",
            "TRADER JOE", label_id=groceries_id,
        )

        all_rules = rules.get_all_rules(in_memory_db)
        assert len(all_rules) == 1
        assert all_rules[0]["txn_count"] == 2


class TestApplyRulesToTransactions:
    def test_categorizes_from_copilot_derived_rules(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        # Previously categorized transactions (from Copilot or earlier months)
        _insert_txn(
            in_memory_db, "txn-old-1", "2026-02-10",
            "TRADER JOE", label_id=groceries_id,
        )
        _insert_txn(
            in_memory_db, "txn-old-2", "2026-02-11",
            "CHIPOTLE", label_id=dining_id,
        )

        # Uncategorized transactions for March
        _insert_txn(in_memory_db, "txn-1", "2026-03-10", "TRADER JOE #123")
        _insert_txn(in_memory_db, "txn-2", "2026-03-15", "CHIPOTLE ONLINE")
        _insert_txn(in_memory_db, "txn-3", "2026-03-20", "UNKNOWN MERCHANT")
        # Already categorized — should be skipped
        _insert_txn(
            in_memory_db, "txn-4", "2026-03-25",
            "TRADER JOE #456", label_id=dining_id,
        )

        matched = rules.apply_rules_to_transactions(in_memory_db, 3, 2026)
        assert matched == 2

        txn1 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 'txn-1'"
        ).fetchone()
        assert txn1["label_id"] == groceries_id
        assert txn1["categorized_by"] == "rule"
        assert txn1["review_status"] == "auto_accepted"

        txn2 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 'txn-2'"
        ).fetchone()
        assert txn2["label_id"] == dining_id

        # Unmatched stays uncategorized
        txn3 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 'txn-3'"
        ).fetchone()
        assert txn3["label_id"] is None

        # Already-categorized stays unchanged
        txn4 = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 'txn-4'"
        ).fetchone()
        assert txn4["label_id"] == dining_id
