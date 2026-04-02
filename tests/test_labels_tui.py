"""Tests for labels TUI data operations (read-only viewer)."""

from finmint.db import init_db, get_labels, get_label_by_name, insert_transaction
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


class TestLabelsReadOnly:
    def test_get_labels_returns_seeded_categories(self):
        conn = _setup_db()
        labels = get_labels(conn)
        assert len(labels) == 16
        names = {label["name"] for label in labels}
        assert "Groceries" in names
        assert "Transfer" in names
        assert "Dining Out" in names

    def test_labels_have_color_and_icon(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        assert groceries is not None
        assert groceries["color"] is not None
        assert groceries["icon"] is not None

    def test_transaction_count_per_label(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        for i in range(3):
            insert_transaction(conn, {
                "id": f"txn-{i}", "account_id": "acct1", "amount": -1000,
                "date": "2026-03-15", "description": f"STORE {i}",
                "normalized_description": f"STORE {i}", "label_id": groceries["id"],
            })
        count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE label_id = ?",
            (groceries["id"],),
        ).fetchone()["c"]
        assert count == 3

    def test_label_with_no_transactions_has_zero_count(self):
        conn = _setup_db()
        entertainment = get_label_by_name(conn, "Entertainment")
        count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE label_id = ?",
            (entertainment["id"],),
        ).fetchone()["c"]
        assert count == 0

    def test_protected_labels_exist(self):
        """Transfer and Income labels should be present from seed."""
        conn = _setup_db()
        transfer = get_label_by_name(conn, "Transfer")
        assert transfer is not None
        income = get_label_by_name(conn, "Income")
        assert income is not None
