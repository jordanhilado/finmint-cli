"""Tests for CLI routing — validates Typer default command + subcommands coexistence."""

from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from finmint.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "finmint 0.1.0" in result.stdout


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "view" in result.stdout
    assert "labels" in result.stdout
    assert "accounts" in result.stdout
    assert "rules" in result.stdout


def _mock_ensure_setup():
    """Patch _ensure_setup to return a mock config and in-memory DB."""
    from finmint.db import init_db
    from tests.conftest import seed_test_categories
    conn = init_db(":memory:")
    seed_test_categories(conn)
    return {"copilot": {"token": "fake"}, "claude": {"api_key_env": "FAKE"}}, conn


@patch("finmint.cli._ensure_setup", side_effect=_mock_ensure_setup)
@patch("finmint.sync.sync_month", return_value={"new_count": 0, "total_fetched": 0, "error": None})
@patch("finmint.categorize.categorize_month", return_value={"rule_matched": 0, "transfers_detected": 0, "ai_categorized": 0, "uncategorized": 0})
@patch("finmint.review_tui.ReviewApp")
def test_default_command_with_period(mock_tui, mock_cat, mock_sync, mock_setup):
    """Typer routing spike: finmint 3-2026 routes to the review flow."""
    result = runner.invoke(app, ["3-2026"])
    assert result.exit_code == 0


@patch("finmint.cli._ensure_setup", side_effect=_mock_ensure_setup)
def test_view_subcommand_monthly_no_data(mock_setup):
    """finmint view 3-2026 routes to view, shows no-data message."""
    result = runner.invoke(app, ["view", "3-2026"])
    assert result.exit_code == 0
    assert "No transactions found" in result.stdout


@patch("finmint.cli._ensure_setup", side_effect=_mock_ensure_setup)
def test_view_subcommand_yearly_no_data(mock_setup):
    result = runner.invoke(app, ["view", "2026"])
    assert result.exit_code == 0
    assert "No transactions found" in result.stdout


@patch("finmint.cli._ensure_setup", side_effect=_mock_ensure_setup)
@patch("finmint.labels_tui.LabelsApp")
def test_labels_subcommand(mock_tui, mock_setup):
    result = runner.invoke(app, ["labels"])
    assert result.exit_code == 0


@patch("finmint.cli._ensure_setup", side_effect=_mock_ensure_setup)
@patch("finmint.accounts_tui.AccountsApp")
def test_accounts_subcommand(mock_tui, mock_setup):
    result = runner.invoke(app, ["accounts"])
    assert result.exit_code == 0


@patch("finmint.cli._ensure_setup", side_effect=_mock_ensure_setup)
@patch("finmint.rules_tui.RulesApp")
def test_rules_subcommand(mock_tui, mock_setup):
    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0


def test_invalid_period_format():
    result = runner.invoke(app, ["march-2026"])
    assert result.exit_code == 1
    assert "Invalid period format" in result.stdout


def test_invalid_month():
    result = runner.invoke(app, ["13-2026"])
    assert result.exit_code == 1
    assert "Invalid month" in result.stdout


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "Usage" in result.stdout
