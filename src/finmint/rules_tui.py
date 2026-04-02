"""Textual TUI for viewing merchant categorization rules derived from Copilot Money."""

import sqlite3

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static

from finmint.rules import get_all_rules


class RulesApp(App):
    """Read-only TUI showing merchant rules derived from Copilot Money categorizations."""

    TITLE = "Finmint — Merchant Rules (from Copilot Money)"
    MOUSE_SUPPORT = False

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
        yield DataTable(id="rules-table")
        yield Static(
            "No rules yet. Categorize transactions in Copilot Money, "
            "then sync to see derived rules.",
            id="empty-message",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Merchant", "Category", "Transactions")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        table.clear()
        rules = get_all_rules(self.conn)
        empty_msg = self.query_one("#empty-message", Static)
        if not rules:
            table.display = False
            empty_msg.display = True
            return
        table.display = True
        empty_msg.display = False
        for rule in rules:
            table.add_row(
                rule["pattern"],
                rule["label_name"],
                str(rule["txn_count"]),
            )
