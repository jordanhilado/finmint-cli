"""Textual TUI for managing connected bank accounts."""

import sqlite3

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Label, Static
from textual.screen import ModalScreen


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Confirm account deletion."""

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "Cancel"),
    ]

    def __init__(self, account_name: str) -> None:
        super().__init__()
        self.account_name = account_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(
                f"Delete '{self.account_name}'? Transactions will be kept. (y/n)"
            )

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class AccountsApp(App):
    """Interactive TUI for managing connected bank accounts."""

    TITLE = "Finmint — Accounts"

    BINDINGS = [
        Binding("a", "add_account", "Add Account"),
        Binding("d", "delete_account", "Delete Account"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #empty-message {
        text-align: center;
        margin: 4 2;
        color: $text-muted;
    }
    #confirm-container {
        align: center middle;
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def __init__(self, conn: sqlite3.Connection, config: dict | None = None) -> None:
        super().__init__()
        self.conn = conn
        self.config = config or {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="accounts-table")
        yield Static(
            "No accounts connected. Press 'a' to add your first account.",
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

    def action_add_account(self) -> None:
        from finmint.enrollment import start_enrollment

        try:
            start_enrollment(self.config, self.conn)
            self._refresh_table()
            self.notify("Account enrolled successfully!")
        except Exception as e:
            self.notify(f"Enrollment failed: {e}", severity="error")

    def action_delete_account(self) -> None:
        table = self.query_one("#accounts-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        self._deleting_account_id = row_key.value
        row_idx = table.cursor_coordinate.row
        name = table.get_row_at(row_idx)[0]
        self.push_screen(ConfirmDeleteScreen(name), self._on_delete_confirmed)

    def _on_delete_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        account_id = self._deleting_account_id
        # Remove from local DB only (transactions kept)
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()
        self._refresh_table()
        self.notify("Account removed.")
