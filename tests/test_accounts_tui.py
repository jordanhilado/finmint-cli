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

    def test_no_accounts_returns_empty(self):
        conn = _setup_db()
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        assert len(rows) == 0
