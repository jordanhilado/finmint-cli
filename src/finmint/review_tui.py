"""Textual TUI for reviewing and categorizing transactions."""

import sqlite3

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.screen import ModalScreen, Screen

from finmint.db import get_labels, get_transactions, update_transaction_label
from finmint.rules import add_rule


# ---------------------------------------------------------------------------
# Modal: label picker
# ---------------------------------------------------------------------------


class LabelPickerScreen(ModalScreen[int | None]):
    """Pick a category label for a transaction."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        labels = get_labels(self.conn)
        with Vertical(id="picker-container"):
            yield Label("Select category:")
            yield OptionList(
                *[Option(r["name"], id=str(r["id"])) for r in labels],
                id="label-picker",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Screen: one-by-one review
# ---------------------------------------------------------------------------


class OneByOneScreen(Screen):
    """Step through unreviewed transactions one at a time."""

    BINDINGS = [
        Binding("a", "accept", "Accept"),
        Binding("c", "change_category", "Change"),
        Binding("e", "exempt", "Exempt"),
        Binding("s", "skip", "Skip"),
        Binding("t", "toggle_mode", "Table View"),
        Binding("q", "quit_review", "Quit"),
    ]

    def __init__(self, conn: sqlite3.Connection, month: int, year: int) -> None:
        super().__init__()
        self.conn = conn
        self.month = month
        self.year = year
        self._unreviewed: list = []
        self._current_idx = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="txn-detail")
        yield Footer()

    def on_mount(self) -> None:
        self._load_unreviewed()
        self._show_current()

    def _load_unreviewed(self) -> None:
        all_txns = get_transactions(self.conn, self.month, self.year)
        self._unreviewed = [t for t in all_txns if t["review_status"] == "needs_review"]
        self._current_idx = 0

    def _show_current(self) -> None:
        detail = self.query_one("#txn-detail", Static)
        if not self._unreviewed or self._current_idx >= len(self._unreviewed):
            detail.update("All transactions reviewed! Press 't' for table or 'q' to quit.")
            return
        txn = self._unreviewed[self._current_idx]
        total = len(self._unreviewed)
        label_name = self._get_label_name(txn["label_id"])
        amount = txn["amount"] / 100
        detail.update(
            f"Transaction {self._current_idx + 1}/{total}\n\n"
            f"  Date:     {txn['date']}\n"
            f"  Merchant: {txn['description']}\n"
            f"  Amount:   ${amount:,.2f}\n"
            f"  Category: {label_name or 'Uncategorized'}\n"
            f"  Source:   {txn['categorized_by'] or 'none'}\n\n"
            f"  [a] Accept  [c] Change  [e] Exempt  [s] Skip  [t] Table  [q] Quit"
        )

    def _get_label_name(self, label_id: int | None) -> str | None:
        if label_id is None:
            return None
        row = self.conn.execute(
            "SELECT name FROM labels WHERE id = ?", (label_id,)
        ).fetchone()
        return row["name"] if row else None

    def _advance(self) -> None:
        self._current_idx += 1
        self._show_current()

    def action_accept(self) -> None:
        if self._current_idx >= len(self._unreviewed):
            return
        txn = self._unreviewed[self._current_idx]
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"],
            txn["categorized_by"] or "manual", "reviewed",
        )
        self._advance()

    def action_change_category(self) -> None:
        if self._current_idx >= len(self._unreviewed):
            return
        self.app.push_screen(LabelPickerScreen(self.conn), self._on_label_picked)

    def _on_label_picked(self, label_id: int | None) -> None:
        if label_id is None:
            return
        txn = self._unreviewed[self._current_idx]
        update_transaction_label(self.conn, txn["id"], label_id, "manual", "reviewed")
        # Auto-create merchant rule silently
        if txn["normalized_description"]:
            add_rule(self.conn, txn["normalized_description"], label_id, source="auto_learned")
        self._advance()

    def action_exempt(self) -> None:
        if self._current_idx >= len(self._unreviewed):
            return
        txn = self._unreviewed[self._current_idx]
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"], txn["categorized_by"], "exempt",
        )
        self._advance()

    def action_skip(self) -> None:
        self._advance()

    def action_toggle_mode(self) -> None:
        self.app.pop_screen()

    def action_quit_review(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# Main review app
# ---------------------------------------------------------------------------


class ReviewApp(App):
    """Interactive transaction review TUI with table and one-by-one modes."""

    TITLE = "Finmint — Review"

    BINDINGS = [
        Binding("a", "accept", "Accept"),
        Binding("enter", "change_category", "Change Category"),
        Binding("e", "exempt", "Exempt"),
        Binding("space", "toggle_select", "Select"),
        Binding("b", "bulk_accept", "Bulk Accept"),
        Binding("t", "toggle_mode", "One-by-One"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #picker-container {
        align: center middle;
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #summary {
        dock: top;
        height: 3;
        padding: 0 2;
        background: $primary-background;
    }
    #all-reviewed {
        text-align: center;
        margin: 4 2;
        color: $success;
    }
    """

    def __init__(self, conn: sqlite3.Connection, month: int, year: int) -> None:
        super().__init__()
        self.conn = conn
        self.month = month
        self.year = year
        self._selected_keys: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        yield DataTable(id="review-table")
        yield Static("All transactions reviewed!", id="all-reviewed")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Date", "Merchant", "Amount", "Category", "Status")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.clear()
        self._selected_keys.clear()
        txns = get_transactions(self.conn, self.month, self.year)
        reviewed = sum(1 for t in txns if t["review_status"] in ("reviewed", "auto_accepted"))
        needs_review = sum(1 for t in txns if t["review_status"] == "needs_review")
        exempt = sum(1 for t in txns if t["review_status"] == "exempt")

        summary = self.query_one("#summary", Static)
        summary.update(
            f"{self.month}/{self.year} — {len(txns)} transactions | "
            f"{reviewed} reviewed | {needs_review} need review | {exempt} exempt"
        )

        all_reviewed_msg = self.query_one("#all-reviewed", Static)
        if not txns:
            table.display = False
            all_reviewed_msg.update("No transactions for this period.")
            all_reviewed_msg.display = True
            return
        if needs_review == 0:
            all_reviewed_msg.display = True
        else:
            all_reviewed_msg.display = False
        table.display = True

        for txn in txns:
            amount = txn["amount"] / 100
            label_name = self._get_label_name(txn["label_id"]) or "—"
            status = txn["review_status"]

            # Style based on status
            if status == "exempt":
                date_cell = Text(txn["date"], style="dim strike")
                merchant_cell = Text(txn["description"] or "", style="dim strike")
                amount_cell = Text(f"${amount:,.2f}", style="dim strike")
                label_cell = Text(label_name, style="dim strike")
                status_cell = Text("exempt", style="dim")
            elif status in ("reviewed", "auto_accepted"):
                date_cell = txn["date"]
                merchant_cell = txn["description"] or ""
                amount_cell = f"${amount:,.2f}"
                label_cell = label_name
                status_cell = Text("✓", style="green")
            else:
                date_cell = txn["date"]
                merchant_cell = txn["description"] or ""
                amount_cell = f"${amount:,.2f}"
                label_cell = label_name
                status_cell = Text("? review", style="yellow")

            table.add_row(
                date_cell, merchant_cell, amount_cell, label_cell, status_cell,
                key=txn["id"],
            )

    def _get_label_name(self, label_id: int | None) -> str | None:
        if label_id is None:
            return None
        row = self.conn.execute(
            "SELECT name FROM labels WHERE id = ?", (label_id,)
        ).fetchone()
        return row["name"] if row else None

    def _get_selected_txn(self) -> dict | None:
        table = self.query_one("#review-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        txn_id = row_key.value
        return self.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()

    def action_accept(self) -> None:
        txn = self._get_selected_txn()
        if not txn:
            return
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"],
            txn["categorized_by"] or "manual", "reviewed",
        )
        self._refresh_table()

    def action_change_category(self) -> None:
        txn = self._get_selected_txn()
        if not txn:
            return
        self._editing_txn_id = txn["id"]
        self._editing_txn_desc = txn["normalized_description"]
        self.push_screen(LabelPickerScreen(self.conn), self._on_category_picked)

    def _on_category_picked(self, label_id: int | None) -> None:
        if label_id is None:
            return
        update_transaction_label(self.conn, self._editing_txn_id, label_id, "manual", "reviewed")
        # Auto-create merchant rule silently (R12)
        if self._editing_txn_desc:
            add_rule(self.conn, self._editing_txn_desc, label_id, source="auto_learned")
        self._refresh_table()

    def action_exempt(self) -> None:
        txn = self._get_selected_txn()
        if not txn:
            return
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"], txn["categorized_by"], "exempt",
        )
        self._refresh_table()

    def action_toggle_select(self) -> None:
        table = self.query_one("#review-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key = row_key.value
        if key in self._selected_keys:
            self._selected_keys.discard(key)
        else:
            self._selected_keys.add(key)

    def action_bulk_accept(self) -> None:
        if not self._selected_keys:
            return
        for txn_id in self._selected_keys:
            txn = self.conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (txn_id,)
            ).fetchone()
            if txn:
                update_transaction_label(
                    self.conn, txn["id"], txn["label_id"],
                    txn["categorized_by"] or "manual", "reviewed",
                )
        self._selected_keys.clear()
        self._refresh_table()

    def action_toggle_mode(self) -> None:
        self.push_screen(OneByOneScreen(self.conn, self.month, self.year))
