"""Textual TUI for viewing connected bank accounts (read-only)."""

import sqlite3

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static


class AccountsApp(App):
    """Interactive TUI for viewing connected bank accounts."""

    TITLE = "Finmint — Accounts"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #empty-message {
        text-align: center;
        margin: 4 2;
        color: $text-muted;
    }
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="accounts-table")
        yield Static(
            "No accounts found. Run 'finmint token' and sync a month to discover accounts.",
            id="empty-message",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Institution", "Type", "Last 4", "Last Synced")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        table.clear()
        rows = self.conn.execute(
            "SELECT id, institution_name, account_type, last_four, last_synced_at "
            "FROM accounts ORDER BY institution_name"
        ).fetchall()
        empty_msg = self.query_one("#empty-message", Static)
        if not rows:
            table.display = False
            empty_msg.display = True
            return
        table.display = True
        empty_msg.display = False
        for row in rows:
            synced = row["last_synced_at"][:10] if row["last_synced_at"] else "Never"
            table.add_row(
                row["institution_name"] or "Unknown",
                row["account_type"] or "",
                row["last_four"] or "",
                synced,
                key=row["id"],
            )
