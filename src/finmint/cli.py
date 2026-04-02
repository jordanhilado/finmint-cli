"""Finmint CLI — command routing via Typer with custom Click group.

Uses a custom Click group to allow `finmint 3-2026` (default positional arg)
to coexist with named subcommands like `finmint view`, `finmint labels`, etc.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from typer.core import TyperGroup
from rich.console import Console
from rich.status import Status

from finmint import __version__

console = Console()

# Default data directory
FINMINT_DIR = Path.home() / ".finmint"
DB_PATH = FINMINT_DIR / "finmint.db"


class DefaultGroup(TyperGroup):
    """Typer group that routes unknown args to the default 'review' command."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["review"] + args
        return super().parse_args(ctx, args)


app = typer.Typer(
    name="finmint",
    help="Terminal-based personal finance tool.",
    cls=DefaultGroup,
    no_args_is_help=True,
)


def version_callback(value: bool):
    if value:
        console.print(f"finmint {__version__}")
        raise typer.Exit()


def _ensure_setup() -> tuple:
    """Load config, init DB, sync categories from Copilot Money, return (config, conn)."""
    from finmint.config import load_config, validate_config, check_permissions
    from finmint.db import init_db
    from finmint.sync import sync_categories

    check_permissions()

    try:
        config = load_config()
        validate_config(config)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    conn = init_db(str(DB_PATH))

    # Fetch categories from Copilot Money; fall back to existing DB labels if offline
    try:
        sync_categories(conn)
    except Exception:
        pass  # Categories from a previous sync remain in the DB

    return config, conn


@app.callback()
def main(
    version: Optional[bool] = typer.Option(None, "--version", callback=version_callback, is_eager=True),
):
    """Terminal-based personal finance tool."""
    pass


@app.command()
def review(
    period: str = typer.Argument(..., help="Month to review (e.g., 3-2026)"),
    force_sync: bool = typer.Option(False, "--sync", help="Re-fetch even if already synced"),
):
    """Review and categorize transactions for a given month."""
    month, year = _parse_period(period)
    config, conn = _ensure_setup()

    # Step 1: Sync
    from finmint.sync import sync_month

    with Status("[bold]Syncing transactions from Copilot Money...", console=console):
        result = sync_month(conn, config, month, year, force=force_sync)

    if result["error"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"Synced {result['total_fetched']} transactions "
        f"({result['new_count']} new)."
    )

    # Step 2: Categorize
    from finmint.categorize import categorize_month

    with Status("[bold]Categorizing transactions...", console=console):
        cat_result = categorize_month(conn, config, month, year)

    console.print(
        f"Categorized: {cat_result['rule_matched']} by rules, "
        f"{cat_result['transfers_detected']} transfers, "
        f"{cat_result['ai_categorized']} by AI. "
        f"{cat_result['uncategorized']} uncategorized."
    )

    # Step 3: Launch review TUI
    from finmint.config import get_token
    from finmint.review_tui import ReviewApp

    tui = ReviewApp(conn, month, year, copilot_token=get_token())
    tui.run()


@app.command()
def view(
    period: str = typer.Argument(..., help="Month (e.g., 3-2026) or year (e.g., 2026)"),
):
    """View spending charts and AI summary."""
    config, conn = _ensure_setup()

    from finmint.db import get_transactions
    from finmint.charts import render_monthly_pie, render_yearly_bars, open_chart
    from finmint.ai import generate_monthly_summary, generate_yearly_summary

    if re.match(r"^\d{4}$", period):
        # Yearly view
        year = int(period)

        # Check for data
        has_data = False
        for m in range(1, 13):
            if get_transactions(conn, m, year):
                has_data = True
                break
        if not has_data:
            console.print(
                f"[yellow]No transactions found for {year}. "
                f"Run [bold]finmint <M-{year}>[/bold] to sync and review.[/yellow]"
            )
            raise typer.Exit()

        # Render chart
        chart_path = render_yearly_bars(conn, year)
        if chart_path:
            open_chart(chart_path)

        # AI summary
        try:
            summary = generate_yearly_summary(config, conn, year)
            console.print(f"\n[bold]AI Summary — {year}[/bold]\n")
            console.print(summary)
        except Exception as e:
            console.print(f"[yellow]Could not generate AI summary: {e}[/yellow]")

    else:
        # Monthly view
        month, year = _parse_period(period)
        txns = get_transactions(conn, month, year)

        if not txns:
            console.print(
                f"[yellow]No transactions found for {month}/{year}. "
                f"Run [bold]finmint {month}-{year}[/bold] to sync and review.[/yellow]"
            )
            raise typer.Exit()

        # Unreviewed count
        unreviewed = sum(1 for t in txns if t["review_status"] == "needs_review")
        if unreviewed > 0:
            console.print(
                f"[yellow]⚠ {unreviewed} transactions still need review. "
                f"Run [bold]finmint {month}-{year}[/bold] to review.[/yellow]"
            )

        # Render chart
        chart_path = render_monthly_pie(conn, month, year)
        if chart_path:
            open_chart(chart_path)

        # AI summary
        try:
            summary = generate_monthly_summary(config, conn, month, year)
            console.print(f"\n[bold]AI Summary — {month}/{year}[/bold]\n")
            console.print(summary)
        except Exception as e:
            console.print(f"[yellow]Could not generate AI summary: {e}[/yellow]")


@app.command()
def token():
    """Set or validate your Copilot Money JWT token."""
    from finmint.config import get_token, save_token, _token_path
    from finmint.copilot import create_client, fetch_accounts, CopilotAuthError

    token_file = _token_path()

    if not token_file.exists():
        save_token("", home=None)
        console.print(f"Created token file: [bold]{token_file}[/bold]\n")

    console.print(
        f"Paste your Copilot Money JWT into [bold]{token_file}[/bold]\n"
        "Find it in browser dev tools: Network tab → any graphql request → Authorization header.\n"
        "You can include or omit the 'Bearer ' prefix.\n"
    )
    subprocess.run(["open", str(token_file)])
    console.input("[dim]Press Enter once you've saved the file...[/dim]")

    try:
        jwt = get_token()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    # Validate by making a test API call
    with Status("[bold]Validating token...", console=console):
        try:
            with create_client(jwt) as client:
                accts = fetch_accounts(client)
        except CopilotAuthError:
            console.print("[red]Token is invalid or expired. Please try again.[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[red]Failed to validate token: {e}[/red]")
            raise typer.Exit(code=1)

    console.print(f"[green]Token validated ({token_file})[/green]")
    console.print(f"Found {len(accts)} connected accounts.")


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Reset all reviews, categories, and AI data to start fresh.

    Clears all transaction labels, review statuses, notes, and transfer
    pairings. Deletes cached AI summaries and AI-learned merchant rules.
    Your synced transactions, accounts, labels, and manual rules are kept.
    """
    _, conn = _ensure_setup()

    # Show what will be affected
    txn_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    reviewed = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE review_status = 'reviewed'"
    ).fetchone()[0]
    ai_summaries = conn.execute("SELECT COUNT(*) FROM ai_summaries").fetchone()[0]
    ai_rules = conn.execute(
        "SELECT COUNT(*) FROM merchant_rules WHERE source = 'ai'"
    ).fetchone()[0]

    if txn_count == 0:
        console.print("[yellow]Nothing to reset — no transactions found.[/yellow]")
        raise typer.Exit()

    console.print("[bold]This will reset:[/bold]")
    console.print(f"  • {txn_count} transactions → labels, review status, notes cleared")
    console.print(f"    ({reviewed} currently reviewed)")
    console.print(f"  • {ai_summaries} cached AI summaries → deleted")
    console.print(f"  • {ai_rules} AI-learned merchant rules → deleted")
    console.print()
    console.print("[dim]Kept: synced transactions, accounts, labels, manual rules.[/dim]")

    if not yes:
        confirm = console.input("\n[bold red]Type 'reset' to confirm:[/bold red] ")
        if confirm.strip() != "reset":
            console.print("Aborted.")
            raise typer.Exit()

    # Reset all transaction review state
    conn.execute(
        "UPDATE transactions SET "
        "label_id = NULL, "
        "review_status = 'needs_review', "
        "categorized_by = NULL, "
        "transfer_pair_id = NULL, "
        "note = NULL"
    )
    # Delete AI summaries
    conn.execute("DELETE FROM ai_summaries")
    # Delete AI-learned merchant rules (keep manual ones)
    conn.execute("DELETE FROM merchant_rules WHERE source = 'ai'")
    conn.commit()

    console.print(f"\n[green]Reset complete. {txn_count} transactions ready for fresh review.[/green]")


@app.command(name="check-key")
def check_key():
    """Validate that the Anthropic API key is configured and working."""
    from finmint.config import load_config, validate_config, check_permissions, resolve_api_key

    check_permissions()

    try:
        config = load_config()
        validate_config(config)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    try:
        api_key = resolve_api_key(config)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    env_var = config["claude"]["api_key_env"]
    masked = api_key[:7] + "..." + api_key[-4:]
    console.print(f"Found key in [bold]${env_var}[/bold]: {masked}")

    # Make a minimal API call to verify the key works
    import anthropic

    with Status("[bold]Validating key with Anthropic API...", console=console):
        try:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        except anthropic.AuthenticationError:
            console.print("[red]Key is invalid. Check your API key and try again.[/red]")
            raise typer.Exit(code=1)
        except anthropic.PermissionError:
            console.print("[red]Key lacks permissions. Check your Anthropic dashboard.[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[red]API call failed: {e}[/red]")
            raise typer.Exit(code=1)

    console.print("[green]Anthropic API key is valid and working.[/green]")


@app.command()
def labels():
    """Manage category labels."""
    _, conn = _ensure_setup()
    from finmint.labels_tui import LabelsApp

    tui = LabelsApp(conn)
    tui.run()



@app.command()
def accounts():
    """View connected bank accounts."""
    _, conn = _ensure_setup()
    from finmint.accounts_tui import AccountsApp

    tui = AccountsApp(conn)
    tui.run()


@app.command()
def rules():
    """Manage merchant categorization rules."""
    _, conn = _ensure_setup()
    from finmint.rules_tui import RulesApp

    tui = RulesApp(conn)
    tui.run()


def _parse_period(period: str) -> tuple[int, int]:
    """Parse M-YYYY format into (month, year)."""
    match = re.match(r"^(\d{1,2})-(\d{4})$", period)
    if not match:
        console.print(f"[red]Invalid period format: {period}. Use M-YYYY (e.g., 3-2026)[/red]")
        raise typer.Exit(code=1)
    month, year = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        console.print(f"[red]Invalid month: {month}. Must be 1-12.[/red]")
        raise typer.Exit(code=1)
    return month, year
