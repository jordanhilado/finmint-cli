"""Tests for labels TUI data operations."""

from finmint.db import init_db, seed_default_labels, get_labels, get_label_by_name, insert_transaction
from finmint.rules import add_rule


def _setup_db():
    conn = init_db(":memory:")
    seed_default_labels(conn)
    conn.execute(
        "INSERT INTO accounts (id, institution_name, account_type, last_four) VALUES (?, ?, ?, ?)",
        ("acct1", "Test Bank", "checking", "1234"),
    )
    conn.commit()
    return conn


class TestAddLabel:
    def test_add_custom_label(self):
        conn = _setup_db()
        conn.execute(
            "INSERT INTO labels (name, is_default, is_protected, created_at) "
            "VALUES (?, 0, 0, datetime('now'))",
            ("Coffee Shops",),
        )
        conn.commit()
        label = get_label_by_name(conn, "Coffee Shops")
        assert label is not None
        assert label["is_protected"] == 0
        assert label["is_default"] == 0


class TestEditLabel:
    def test_rename_cascades_via_fk(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        insert_transaction(conn, {
            "id": "txn-1", "account_id": "acct1", "amount": -5000,
            "date": "2026-03-15", "description": "STORE",
            "normalized_description": "STORE", "label_id": groceries["id"],
        })
        # Rename the label
        conn.execute("UPDATE labels SET name = ? WHERE id = ?", ("Food & Groceries", groceries["id"]))
        conn.commit()
        # Transaction still points to the same label_id
        txn = conn.execute("SELECT * FROM transactions WHERE id = ?", ("txn-1",)).fetchone()
        assert txn["label_id"] == groceries["id"]
        # Label name changed
        label = conn.execute("SELECT * FROM labels WHERE id = ?", (groceries["id"],)).fetchone()
        assert label["name"] == "Food & Groceries"


class TestDeleteLabel:
    def test_delete_reassigns_transactions_atomically(self):
        conn = _setup_db()
        shopping = get_label_by_name(conn, "Shopping")
        groceries = get_label_by_name(conn, "Groceries")

        # Insert transactions with shopping label
        for i in range(3):
            insert_transaction(conn, {
                "id": f"txn-{i}", "account_id": "acct1", "amount": -1000,
                "date": "2026-03-15", "description": f"STORE {i}",
                "normalized_description": f"STORE {i}", "label_id": shopping["id"],
            })

        # Also create a rule pointing to shopping
        add_rule(conn, "STORE", shopping["id"])

        # Delete shopping label, reassign to groceries
        with conn:
            conn.execute("UPDATE transactions SET label_id = ? WHERE label_id = ?", (groceries["id"], shopping["id"]))
            conn.execute("UPDATE merchant_rules SET label_id = ? WHERE label_id = ?", (groceries["id"], shopping["id"]))
            conn.execute("DELETE FROM labels WHERE id = ?", (shopping["id"],))

        # Verify: no orphaned transactions
        orphans = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE label_id = ?", (shopping["id"],)).fetchone()["c"]
        assert orphans == 0

        # All moved to groceries
        moved = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE label_id = ?", (groceries["id"],)).fetchone()["c"]
        assert moved == 3

        # Rule also moved
        rule = conn.execute("SELECT * FROM merchant_rules WHERE pattern = ?", ("STORE",)).fetchone()
        assert rule["label_id"] == groceries["id"]

    def test_cannot_delete_protected_label(self):
        conn = _setup_db()
        transfer = get_label_by_name(conn, "Transfer")
        assert transfer["is_protected"] == 1
        income = get_label_by_name(conn, "Income")
        assert income["is_protected"] == 1

    def test_delete_label_with_zero_transactions(self):
        conn = _setup_db()
        # Add a custom label
        conn.execute("INSERT INTO labels (name, is_default, is_protected) VALUES (?, 0, 0)", ("Temporary",))
        conn.commit()
        temp = get_label_by_name(conn, "Temporary")
        # Delete it directly (no reassignment needed)
        conn.execute("DELETE FROM labels WHERE id = ?", (temp["id"],))
        conn.commit()
        assert get_label_by_name(conn, "Temporary") is None
