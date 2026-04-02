"""Tests for view command logic."""

from unittest.mock import patch, MagicMock

from finmint.db import (
    init_db, insert_transaction,
    get_transactions, get_label_by_name,
)
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


def _insert_txn(conn, txn_id, label_name, amount, date):
    label = get_label_by_name(conn, label_name)
    insert_transaction(conn, {
        "id": txn_id, "account_id": "acct1", "amount": amount,
        "date": date, "description": f"Test {txn_id}",
        "normalized_description": f"TEST {txn_id}",
        "label_id": label["id"], "review_status": "reviewed",
        "categorized_by": "manual",
    })


class TestViewLogic:
    def test_no_transactions_detected(self):
        conn = _setup_db()
        txns = get_transactions(conn, 3, 2026)
        assert len(txns) == 0

    def test_unreviewed_count(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        insert_transaction(conn, {
            "id": "txn-1", "account_id": "acct1", "amount": -5000,
            "date": "2026-03-15", "description": "Store",
            "normalized_description": "STORE",
            "label_id": groceries["id"], "review_status": "needs_review",
        })
        insert_transaction(conn, {
            "id": "txn-2", "account_id": "acct1", "amount": -3000,
            "date": "2026-03-16", "description": "Other",
            "normalized_description": "OTHER",
            "label_id": groceries["id"], "review_status": "reviewed",
        })
        txns = get_transactions(conn, 3, 2026)
        unreviewed = sum(1 for t in txns if t["review_status"] == "needs_review")
        assert unreviewed == 1

    def test_monthly_data_aggregation(self):
        conn = _setup_db()
        _insert_txn(conn, "txn-1", "Groceries", -5000, "2026-03-10")
        _insert_txn(conn, "txn-2", "Groceries", -3000, "2026-03-15")
        _insert_txn(conn, "txn-3", "Dining Out", -2000, "2026-03-20")
        txns = get_transactions(conn, 3, 2026)
        assert len(txns) == 3

        # Group by label
        import pandas as pd
        df = pd.DataFrame([dict(t) for t in txns])
        totals = df.groupby("label_id")["amount"].sum()
        assert len(totals) == 2  # Two distinct labels

    def test_exempt_excluded_from_totals(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        insert_transaction(conn, {
            "id": "txn-normal", "account_id": "acct1", "amount": -5000,
            "date": "2026-03-15", "description": "Store",
            "normalized_description": "STORE",
            "label_id": groceries["id"], "review_status": "reviewed",
        })
        insert_transaction(conn, {
            "id": "txn-exempt", "account_id": "acct1", "amount": -3000,
            "date": "2026-03-16", "description": "Exempt",
            "normalized_description": "EXEMPT",
            "label_id": groceries["id"], "review_status": "exempt",
        })
        txns = get_transactions(conn, 3, 2026)
        non_exempt = [t for t in txns if t["review_status"] != "exempt"]
        assert len(non_exempt) == 1
