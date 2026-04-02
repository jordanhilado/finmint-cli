"""Tests for rules TUI data operations (Copilot-derived rules)."""

from finmint.db import init_db, get_label_by_name, insert_transaction
from finmint.rules import get_all_rules
from tests.conftest import seed_test_categories


def _setup_db():
    conn = init_db(":memory:")
    seed_test_categories(conn)
    return conn


def _insert_txn(conn, txn_id, normalized_description, label_id=None):
    insert_transaction(conn, {
        "id": txn_id,
        "amount": -1000,
        "date": "2026-03-15",
        "description": normalized_description,
        "normalized_description": normalized_description,
        "label_id": label_id,
        "review_status": "needs_review",
    })


class TestRulesTuiData:
    def test_derived_rules_from_categorized_transactions(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        _insert_txn(conn, "txn-1", "WHOLE FOODS", label_id=groceries["id"])
        rules = get_all_rules(conn)
        assert len(rules) == 1
        assert rules[0]["pattern"] == "WHOLE FOODS"
        assert rules[0]["label_name"] == "Groceries"

    def test_empty_rules_when_no_categorized_transactions(self):
        conn = _setup_db()
        rules = get_all_rules(conn)
        assert len(rules) == 0

    def test_uncategorized_transactions_not_shown_as_rules(self):
        conn = _setup_db()
        _insert_txn(conn, "txn-1", "WHOLE FOODS")
        rules = get_all_rules(conn)
        assert len(rules) == 0

    def test_multiple_merchants_shown(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        dining = get_label_by_name(conn, "Dining Out")
        _insert_txn(conn, "txn-1", "WHOLE FOODS", label_id=groceries["id"])
        _insert_txn(conn, "txn-2", "CHIPOTLE", label_id=dining["id"])
        rules = get_all_rules(conn)
        assert len(rules) == 2
        # Alphabetical order
        assert rules[0]["pattern"] == "CHIPOTLE"
        assert rules[1]["pattern"] == "WHOLE FOODS"
