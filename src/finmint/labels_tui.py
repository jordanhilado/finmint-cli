"""Textual TUI for viewing Copilot Money categories (read-only)."""

import sqlite3

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header

from finmint.db import get_labels


def _text_color_for_bg(hex_color: str) -> str:
    """Return 'white' or 'black' for best contrast against a hex background."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "black" if luminance > 0.5 else "white"


class LabelsApp(App):
    """Read-only viewer for Copilot Money categories."""

    TITLE = "Finmint — Categories (from Copilot Money)"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="labels-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#labels-table", DataTable)
        table.cursor_type = "row"
        self._col_keys = table.add_columns("Icon", "Category", "Color", "Transactions")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#labels-table", DataTable)
        table.clear()
        labels = get_labels(self.conn)
        for label in labels:
            count = self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE label_id = ?",
                (label["id"],),
            ).fetchone()["c"]
            icon = label["icon"] or ""
            color = label["color"]
            if color:
                fg = _text_color_for_bg(color)
                label_cell = Text(f" {label['name']} ", style=f"{fg} on {color}")
                color_cell = Text(f" {color} ", style=f"{fg} on {color}")
            else:
                label_cell = label["name"]
                color_cell = "—"
            table.add_row(icon, label_cell, color_cell, str(count), key=str(label["id"]))
