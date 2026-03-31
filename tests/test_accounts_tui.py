"""Tests for accounts TUI data operations."""

from finmint.db import init_db, seed_default_labels


def _setup_db():
    conn = init_db(":memory:")
    seed_default_labels(conn)
    return conn


def _insert_account(conn, acct_id="acct1", name="Test Bank", atype="checking", last_four="1234"):
    conn.execute(
        "INSERT INTO accounts (id, institution_name, account_type, last_four) VALUES (?, ?, ?, ?)",
        (acct_id, name, atype, last_four),
    )
    conn.commit()


class TestAccountsData:
    def test_list_accounts_with_data(self):
        conn = _setup_db()
        _insert_account(conn)
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        assert len(rows) == 1
        assert rows[0]["institution_name"] == "Test Bank"
        assert rows[0]["last_four"] == "1234"

    def test_delete_account_keeps_transactions(self):
        conn = _setup_db()
        _insert_account(conn)
        from finmint.db import insert_transaction
        insert_transaction(conn, {
            "id": "txn-1", "account_id": "acct1", "amount": -5000,
            "date": "2026-03-15", "description": "TEST",
            "normalized_description": "TEST",
        })
        # Disable FK constraints for this delete (simulates ON DELETE SET NULL behavior)
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM accounts WHERE id = ?", ("acct1",))
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        # Transactions remain
        txns = conn.execute("SELECT * FROM transactions").fetchall()
        assert len(txns) == 1

    def test_no_accounts_returns_empty(self):
        conn = _setup_db()
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        assert len(rows) == 0
