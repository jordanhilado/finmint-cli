"""Shared test fixtures for finmint."""

import sqlite3
import pytest

from finmint.db import upsert_category


# Categories used across tests — mirrors what Copilot Money would return.
TEST_CATEGORIES = [
    ("cat-groc", "Groceries", "#2ecc71", "🛒"),
    ("cat-din", "Dining Out", "#e74c3c", "🍽️"),
    ("cat-trans", "Transport", "#3498db", "🚗"),
    ("cat-house", "Housing", "#9b59b6", "🏠"),
    ("cat-util", "Utilities", "#f39c12", "⚡"),
    ("cat-sub", "Subscriptions", "#1abc9c", "📱"),
    ("cat-shop", "Shopping", "#e67e22", "🛍️"),
    ("cat-health", "Health", "#2980b9", "💊"),
    ("cat-ent", "Entertainment", "#d35400", "🎬"),
    ("cat-inc", "Income", "#27ae60", "💰"),
    ("cat-travel", "Travel", "#8e44ad", "✈️"),
    ("cat-edu", "Education", "#16a085", "📚"),
    ("cat-pcare", "Personal Care", "#c0392b", "💇"),
    ("cat-gift", "Gifts", "#f1c40f", "🎁"),
    ("cat-fees", "Fees & Interest", "#7f8c8d", "💳"),
    ("cat-xfer", "Transfer", "#95a5a6", "🔄"),
]


def seed_test_categories(conn: sqlite3.Connection) -> None:
    """Seed categories for tests (replaces the old seed_default_labels)."""
    for copilot_id, name, color, icon in TEST_CATEGORIES:
        upsert_category(conn, copilot_id, name, color, icon)


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()
