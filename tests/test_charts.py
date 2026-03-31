"""Tests for finmint charts & visualization."""

import os
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")

import pytest

from finmint.db import init_db_with_conn, seed_default_labels, get_label_by_name
from finmint.charts import render_monthly_pie, render_yearly_bars, open_chart


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _label_id(conn, name: str) -> int:
    row = get_label_by_name(conn, name)
    assert row is not None, f"Label '{name}' not found"
    return row["id"]


def _insert_txn(conn, txn_id, date, amount_cents, label_name, review_status="reviewed"):
    """Insert a test transaction with the given label."""
    label_id = _label_id(conn, label_name)
    conn.execute(
        "INSERT INTO transactions "
        "(id, amount, date, description, label_id, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (txn_id, amount_cents, date, f"Test {txn_id}", label_id, review_status),
    )
    conn.commit()


@pytest.fixture
def seeded_db(in_memory_db):
    """In-memory DB with schema and default labels."""
    init_db_with_conn(in_memory_db)
    seed_default_labels(in_memory_db)
    return in_memory_db


# ---------------------------------------------------------------------------
# Monthly pie chart tests
# ---------------------------------------------------------------------------


class TestRenderMonthlyPie:
    def test_happy_path_generates_png(self, seeded_db):
        """Pie chart generates a valid, non-empty PNG for spending data."""
        _insert_txn(seeded_db, "t1", "2026-03-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-03-10", -2000, "Dining Out")
        _insert_txn(seeded_db, "t3", "2026-03-15", -3000, "Transport")

        path = render_monthly_pie(seeded_db, 3, 2026)

        assert path is not None
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        assert path.endswith(".png")
        # Clean up
        os.unlink(path)

    def test_transfers_excluded(self, seeded_db):
        """Transfer transactions should not appear in the pie chart."""
        _insert_txn(seeded_db, "t1", "2026-03-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-03-10", -10000, "Transfer")

        path = render_monthly_pie(seeded_db, 3, 2026)

        assert path is not None
        # The chart should only contain Groceries, not Transfer
        assert os.path.exists(path)
        os.unlink(path)

    def test_exempt_transactions_excluded(self, seeded_db):
        """Exempt transactions should not appear in the pie chart."""
        _insert_txn(seeded_db, "t1", "2026-03-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-03-10", -2000, "Dining Out", review_status="exempt")

        path = render_monthly_pie(seeded_db, 3, 2026)

        assert path is not None
        assert os.path.exists(path)
        os.unlink(path)

    def test_all_exempt_returns_none(self, seeded_db):
        """When all transactions are exempt, return None (no chart)."""
        _insert_txn(seeded_db, "t1", "2026-03-05", -5000, "Groceries", review_status="exempt")
        _insert_txn(seeded_db, "t2", "2026-03-10", -2000, "Dining Out", review_status="exempt")

        path = render_monthly_pie(seeded_db, 3, 2026)
        assert path is None

    def test_no_transactions_returns_none(self, seeded_db):
        """Empty month returns None."""
        path = render_monthly_pie(seeded_db, 3, 2026)
        assert path is None

    def test_only_transfers_returns_none(self, seeded_db):
        """Month with only transfers returns None (transfers excluded)."""
        _insert_txn(seeded_db, "t1", "2026-03-05", -5000, "Transfer")
        _insert_txn(seeded_db, "t2", "2026-03-10", -3000, "Transfer")

        path = render_monthly_pie(seeded_db, 3, 2026)
        assert path is None


# ---------------------------------------------------------------------------
# Yearly bar chart tests
# ---------------------------------------------------------------------------


class TestRenderYearlyBars:
    def test_happy_path_generates_png(self, seeded_db):
        """Bar chart generates a valid, non-empty PNG."""
        _insert_txn(seeded_db, "t1", "2026-01-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-02-10", -2000, "Dining Out")
        _insert_txn(seeded_db, "t3", "2026-03-15", -3000, "Transport")

        path = render_yearly_bars(seeded_db, 2026)

        assert path is not None
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        assert path.endswith(".png")
        os.unlink(path)

    def test_transfers_excluded(self, seeded_db):
        """Transfer transactions should not appear in the bar chart."""
        _insert_txn(seeded_db, "t1", "2026-01-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-02-10", -10000, "Transfer")

        path = render_yearly_bars(seeded_db, 2026)

        assert path is not None
        assert os.path.exists(path)
        os.unlink(path)

    def test_exempt_excluded(self, seeded_db):
        """Exempt transactions should not appear in the bar chart."""
        _insert_txn(seeded_db, "t1", "2026-01-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-02-10", -2000, "Dining Out", review_status="exempt")

        path = render_yearly_bars(seeded_db, 2026)

        assert path is not None
        assert os.path.exists(path)
        os.unlink(path)

    def test_no_data_returns_none(self, seeded_db):
        """Empty year returns None."""
        path = render_yearly_bars(seeded_db, 2026)
        assert path is None

    def test_single_month_data(self, seeded_db):
        """Year with only one month of data renders a single bar."""
        _insert_txn(seeded_db, "t1", "2026-06-05", -5000, "Groceries")
        _insert_txn(seeded_db, "t2", "2026-06-15", -2000, "Dining Out")

        path = render_yearly_bars(seeded_db, 2026)

        assert path is not None
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        os.unlink(path)


# ---------------------------------------------------------------------------
# open_chart tests
# ---------------------------------------------------------------------------


class TestOpenChart:
    def test_macos_uses_open(self):
        """On macOS, open_chart calls 'open'."""
        with patch("finmint.charts.sys.platform", "darwin"), \
             patch("finmint.charts.subprocess.run") as mock_run:
            open_chart("/tmp/test.png")
            mock_run.assert_called_once_with(["open", "/tmp/test.png"], check=True)

    def test_linux_uses_xdg_open(self):
        """On Linux, open_chart calls 'xdg-open'."""
        with patch("finmint.charts.sys.platform", "linux"), \
             patch("finmint.charts.subprocess.run") as mock_run:
            open_chart("/tmp/test.png")
            mock_run.assert_called_once_with(["xdg-open", "/tmp/test.png"], check=True)

    def test_windows_uses_start(self):
        """On Windows, open_chart calls 'start'."""
        with patch("finmint.charts.sys.platform", "win32"), \
             patch("finmint.charts.subprocess.run") as mock_run:
            open_chart("/tmp/test.png")
            mock_run.assert_called_once_with(["start", "", "/tmp/test.png"], check=True)

    def test_fallback_prints_path(self, capsys):
        """On unknown platform, prints the file path."""
        with patch("finmint.charts.sys.platform", "freebsd"):
            open_chart("/tmp/test.png")
            captured = capsys.readouterr()
            assert "/tmp/test.png" in captured.out

    def test_failed_opener_prints_path(self, capsys):
        """If the opener command fails, prints the file path."""
        with patch("finmint.charts.sys.platform", "darwin"), \
             patch("finmint.charts.subprocess.run", side_effect=FileNotFoundError):
            open_chart("/tmp/test.png")
            captured = capsys.readouterr()
            assert "/tmp/test.png" in captured.out
