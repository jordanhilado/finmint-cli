"""Finmint CLI — command routing via Typer with custom Click group.

Uses a custom Click group to allow `finmint 3-2026` (default positional arg)
to coexist with named subcommands like `finmint view`, `finmint labels`, etc.
"""

import re
from typing import Optional

import typer
from typer.core import TyperGroup
from rich.console import Console

from finmint import __version__

console = Console()


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


@app.callback()
def main(
    version: Optional[bool] = typer.Option(None, "--version", callback=version_callback, is_eager=True),
):
    """Terminal-based personal finance tool."""
    pass


@app.command()
def review(
    period: str = typer.Argument(..., help="Month to review (e.g., 3-2026)"),
    force_sync: bool = typer.Option(False, "--force-sync", help="Re-fetch from Teller even if already synced"),
):
    """Review and categorize transactions for a given month."""
    month, year = _parse_period(period)
    console.print(f"[bold]Finmint[/bold] — reviewing {month}/{year} (force_sync={force_sync})")
    # Will be wired in Unit 17: sync → categorize → review TUI


@app.command()
def view(
    period: str = typer.Argument(..., help="Month (e.g., 3-2026) or year (e.g., 2026)"),
):
    """View spending charts and AI summary."""
    if re.match(r"^\d{4}$", period):
        year = int(period)
        console.print(f"[bold]Finmint[/bold] — yearly view for {year}")
    else:
        month, year = _parse_period(period)
        console.print(f"[bold]Finmint[/bold] — monthly view for {month}/{year}")
    # Will be wired in Unit 16


@app.command()
def labels():
    """Manage category labels."""
    console.print("[bold]Finmint[/bold] — label management")
    # Will be wired in Unit 14


@app.command()
def accounts():
    """Manage connected bank accounts."""
    console.print("[bold]Finmint[/bold] — account management")
    # Will be wired in Unit 7


@app.command()
def rules():
    """Manage merchant categorization rules."""
    console.print("[bold]Finmint[/bold] — rules management")
    # Will be wired in Unit 13


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
