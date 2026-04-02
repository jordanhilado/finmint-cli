"""Tests for review TUI data operations."""

from finmint.db import (
    init_db, insert_transaction,
    get_transactions, get_label_by_name, update_transaction_label,
)
from finmint.rules import get_all_rules, match_rules
from tests.conftest import seed_test_categories


def _setup_db():
    conn = init_db(":memory:")
    seed_test_categories(conn)
    conn.execute(
        "INSERT INTO accounts (id, institution_name, account_type, last_four) VALUES (?, ?, ?, ?)",
        ("acct1", "Test Bank", "checking", "1234"),
    )
    conn.commit()
    return conn


def _insert_txn(conn, txn_id, description, amount=-5000, date="2026-03-15", label_id=None):
    insert_transaction(conn, {
        "id": txn_id, "account_id": "acct1", "amount": amount,
        "date": date, "description": description,
        "normalized_description": description.upper() if description else None,
        "label_id": label_id, "review_status": "needs_review",
    })


class TestReviewDataOps:
    def test_accept_transaction_changes_status(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        _insert_txn(conn, "txn-1", "Store", label_id=groceries["id"])
        update_transaction_label(conn, "txn-1", groceries["id"], "ai", "reviewed")
        txn = conn.execute("SELECT * FROM transactions WHERE id = ?", ("txn-1",)).fetchone()
        assert txn["review_status"] == "reviewed"

    def test_category_change_creates_derived_rule(self):
        """Categorizing a transaction makes it act as a rule for future matches."""
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        _insert_txn(conn, "txn-1", "Trader Joe's")
        # Simulate category correction
        update_transaction_label(conn, "txn-1", groceries["id"], "manual", "reviewed")

        # The categorized transaction now acts as a derived rule
        rules = get_all_rules(conn)
        assert len(rules) == 1
        assert rules[0]["pattern"] == "TRADER JOE'S"

    def test_exempt_transaction(self):
        conn = _setup_db()
        _insert_txn(conn, "txn-1", "Store")
        update_transaction_label(conn, "txn-1", None, None, "exempt")
        txn = conn.execute("SELECT * FROM transactions WHERE id = ?", ("txn-1",)).fetchone()
        assert txn["review_status"] == "exempt"

    def test_bulk_accept(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        for i in range(5):
            _insert_txn(conn, f"txn-{i}", f"Store {i}", label_id=groceries["id"])
        # Bulk accept all
        for i in range(5):
            update_transaction_label(conn, f"txn-{i}", groceries["id"], "ai", "reviewed")
        txns = get_transactions(conn, 3, 2026)
        reviewed = [t for t in txns if t["review_status"] == "reviewed"]
        assert len(reviewed) == 5

    def test_all_reviewed_state(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        _insert_txn(conn, "txn-1", "Store", label_id=groceries["id"])
        update_transaction_label(conn, "txn-1", groceries["id"], "ai", "reviewed")
        txns = get_transactions(conn, 3, 2026)
        needs_review = [t for t in txns if t["review_status"] == "needs_review"]
        assert len(needs_review) == 0

    def test_categorized_transaction_matches_future(self):
        """A categorized transaction acts as a rule for future similar transactions."""
        conn = _setup_db()
        dining = get_label_by_name(conn, "Dining Out")
        # First transaction: user corrects category
        _insert_txn(conn, "txn-1", "CHIPOTLE MEXICAN GRILL")
        update_transaction_label(conn, "txn-1", dining["id"], "manual", "reviewed")

        # Should match future transactions with similar description
        result = match_rules(conn, "CHIPOTLE MEXICAN GRILL #456")
        assert result is not None
        assert result["label_id"] == dining["id"]
