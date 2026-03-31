"""Tests for rules TUI data operations."""

from finmint.db import init_db, seed_default_labels, get_label_by_name
from finmint.rules import add_rule, delete_rule, get_all_rules, update_rule


def _setup_db():
    conn = init_db(":memory:")
    seed_default_labels(conn)
    return conn


class TestRulesTuiData:
    def test_add_and_list_rules(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        add_rule(conn, "WHOLE FOODS", groceries["id"])
        rules = get_all_rules(conn)
        assert len(rules) == 1
        assert rules[0]["pattern"] == "WHOLE FOODS"
        assert rules[0]["label_name"] == "Groceries"

    def test_edit_rule_label(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        dining = get_label_by_name(conn, "Dining Out")
        rule_id = add_rule(conn, "TRADER JOE", groceries["id"])
        update_rule(conn, rule_id, dining["id"])
        rules = get_all_rules(conn)
        assert rules[0]["label_name"] == "Dining Out"

    def test_delete_rule(self):
        conn = _setup_db()
        groceries = get_label_by_name(conn, "Groceries")
        rule_id = add_rule(conn, "TARGET", groceries["id"])
        delete_rule(conn, rule_id)
        rules = get_all_rules(conn)
        assert len(rules) == 0

    def test_empty_rules_list(self):
        conn = _setup_db()
        rules = get_all_rules(conn)
        assert len(rules) == 0
