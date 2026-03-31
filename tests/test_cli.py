"""Tests for CLI routing — validates Typer default command + subcommands coexistence."""

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


def test_default_command_with_period():
    """Typer routing spike: finmint 3-2026 routes to the review flow."""
    result = runner.invoke(app, ["3-2026"])
    assert result.exit_code == 0
    assert "reviewing 3/2026" in result.stdout


def test_default_command_with_force_sync():
    result = runner.invoke(app, ["3-2026", "--force-sync"])
    assert result.exit_code == 0
    assert "force_sync=True" in result.stdout


def test_view_subcommand_monthly():
    """finmint view 3-2026 routes to view, not confused with default."""
    result = runner.invoke(app, ["view", "3-2026"])
    assert result.exit_code == 0
    assert "monthly view for 3/2026" in result.stdout


def test_view_subcommand_yearly():
    result = runner.invoke(app, ["view", "2026"])
    assert result.exit_code == 0
    assert "yearly view for 2026" in result.stdout


def test_labels_subcommand():
    result = runner.invoke(app, ["labels"])
    assert result.exit_code == 0
    assert "label management" in result.stdout


def test_accounts_subcommand():
    result = runner.invoke(app, ["accounts"])
    assert result.exit_code == 0
    assert "account management" in result.stdout


def test_rules_subcommand():
    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0
    assert "rules management" in result.stdout


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
    # Click convention: no_args_is_help returns exit code 2
    assert result.exit_code == 2
    assert "Usage" in result.stdout
