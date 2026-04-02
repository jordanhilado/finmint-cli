"""Tests for the merchant rules engine."""

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


class TestAddRule:
    def test_stores_normalized_uppercase_pattern(self, in_memory_db):
        _setup(in_memory_db)
        label_id = _get_label_id(in_memory_db, "Groceries")

        rule_id = rules.add_rule(in_memory_db, "trader joe", label_id)

        row = in_memory_db.execute(
            "SELECT * FROM merchant_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        assert row is not None
        assert row["pattern"] == "TRADER JOE"
        assert row["label_id"] == label_id
        assert row["source"] == "manual"

    def test_duplicate_pattern_updates_existing_rule(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        rule_id_1 = rules.add_rule(in_memory_db, "trader joe", groceries_id)
        rule_id_2 = rules.add_rule(in_memory_db, "TRADER JOE", dining_id)

        # Same rule row updated, not a new one
        assert rule_id_1 == rule_id_2

        row = in_memory_db.execute(
            "SELECT * FROM merchant_rules WHERE id = ?", (rule_id_1,)
        ).fetchone()
        assert row["label_id"] == dining_id

        # Only one rule exists
        count = in_memory_db.execute(
            "SELECT COUNT(*) as c FROM merchant_rules"
        ).fetchone()["c"]
        assert count == 1


class TestMatchRules:
    def test_finds_correct_rule_by_substring(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        rules.add_rule(in_memory_db, "TRADER JOE", groceries_id)

        result = rules.match_rules(in_memory_db, "TRADER JOE #123 SAN FRANCISCO")
        assert result is not None
        assert result["label_id"] == groceries_id

    def test_longest_match_wins(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        shopping_id = _get_label_id(in_memory_db, "Shopping")

        rules.add_rule(in_memory_db, "TRADER", shopping_id)
        rules.add_rule(in_memory_db, "TRADER JOE", groceries_id)

        result = rules.match_rules(in_memory_db, "TRADER JOE #456")
        assert result is not None
        assert result["label_id"] == groceries_id
        assert result["pattern"] == "TRADER JOE"

    def test_no_match_returns_none(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        rules.add_rule(in_memory_db, "TRADER JOE", groceries_id)

        result = rules.match_rules(in_memory_db, "WHOLE FOODS MARKET")
        assert result is None

    def test_case_insensitive_matching(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        rules.add_rule(in_memory_db, "trader joe", groceries_id)

        result = rules.match_rules(in_memory_db, "trader joe #123")
        assert result is not None
        assert result["label_id"] == groceries_id


class TestDeleteRule:
    def test_does_not_affect_transactions(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")

        rule_id = rules.add_rule(in_memory_db, "TRADER JOE", groceries_id)

        # Insert a transaction that was categorized by this rule
        _insert_txn(
            in_memory_db, "txn-1", "2026-03-15",
            "TRADER JOE #123", label_id=groceries_id,
        )

        rules.delete_rule(in_memory_db, rule_id)

        # Rule is gone
        row = in_memory_db.execute(
            "SELECT * FROM merchant_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        assert row is None

        # Transaction still has its label
        txn = in_memory_db.execute(
            "SELECT * FROM transactions WHERE id = 'txn-1'"
        ).fetchone()
        assert txn["label_id"] == groceries_id


class TestUpdateRule:
    def test_updates_label(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        rule_id = rules.add_rule(in_memory_db, "CHIPOTLE", groceries_id)
        rules.update_rule(in_memory_db, rule_id, dining_id)

        row = in_memory_db.execute(
            "SELECT * FROM merchant_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        assert row["label_id"] == dining_id


class TestGetAllRules:
    def test_returns_sorted_with_label_names(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        rules.add_rule(in_memory_db, "TRADER JOE", groceries_id)
        rules.add_rule(in_memory_db, "CHIPOTLE", dining_id)

        all_rules = rules.get_all_rules(in_memory_db)
        assert len(all_rules) == 2
        # Alphabetical: CHIPOTLE before TRADER JOE
        assert all_rules[0]["pattern"] == "CHIPOTLE"
        assert all_rules[0]["label_name"] == "Dining Out"
        assert all_rules[1]["pattern"] == "TRADER JOE"
        assert all_rules[1]["label_name"] == "Groceries"


class TestApplyRulesToTransactions:
    def test_categorizes_matching_transactions(self, in_memory_db):
        _setup(in_memory_db)
        groceries_id = _get_label_id(in_memory_db, "Groceries")
        dining_id = _get_label_id(in_memory_db, "Dining Out")

        rules.add_rule(in_memory_db, "TRADER JOE", groceries_id)
        rules.add_rule(in_memory_db, "CHIPOTLE", dining_id)

        # Uncategorized transactions
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
