"""Textual TUI for reviewing and categorizing transactions."""

import sqlite3

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.screen import ModalScreen, Screen

from finmint import copilot
from finmint.db import (
    get_copilot_id_for_label,
    get_labels,
    get_transactions,
    update_transaction_label,
    update_transaction_note,
)
from finmint.rules import add_rule

# ---------------------------------------------------------------------------
# Sort column definitions
# ---------------------------------------------------------------------------

_SORT_COLUMNS = ("date", "merchant", "amount", "category", "account", "note", "status")
_COLUMN_LABELS = ("Date", "Merchant", "Amount", "Category", "Account", "Note", "Status")


def _text_color_for_bg(hex_color: str) -> str:
    """Return 'white' or 'black' for best contrast against a hex background."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "black" if luminance > 0.5 else "white"


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
        options: list[Option] = []
        for r in labels:
            color = r["color"]
            if color:
                fg = _text_color_for_bg(color)
                prompt = Text(f" {r['name']} ", style=f"{fg} on {color}")
            else:
                prompt = r["name"]
            options.append(Option(prompt, id=str(r["id"])))
        with Vertical(id="picker-container"):
            yield Label("Select category:")
            yield OptionList(*options, id="label-picker")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Modal: note input
# ---------------------------------------------------------------------------


class NoteInputScreen(ModalScreen[str | None]):
    """Enter or edit a note for a transaction."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_note: str | None = None) -> None:
        super().__init__()
        self._current_note = current_note or ""

    def compose(self) -> ComposeResult:
        with Vertical(id="note-container"):
            yield Label("Add/edit note (Enter to save, Esc to cancel):")
            yield Input(value=self._current_note, id="note-input")

    def on_mount(self) -> None:
        self.query_one("#note-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Modal: sort picker
# ---------------------------------------------------------------------------


class SortPickerScreen(ModalScreen[tuple[str | None, bool] | None]):
    """Pick a column to sort by. Selecting the active column toggles direction,
    then clears the sort on the third click."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_column: str | None, ascending: bool) -> None:
        super().__init__()
        self._current_column = current_column
        self._ascending = ascending

    def compose(self) -> ComposeResult:
        options: list[Option] = []
        for col, label in zip(_SORT_COLUMNS, _COLUMN_LABELS):
            if col == self._current_column:
                indicator = " ▲" if self._ascending else " ▼"
                options.append(Option(label + indicator, id=col))
            else:
                options.append(Option(label, id=col))
        with Vertical(id="sort-container"):
            yield Label("Sort by column:")
            yield OptionList(*options, id="sort-picker")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        col = event.option.id
        if col == self._current_column:
            if self._ascending:
                self.dismiss((col, False))  # toggle to desc
            else:
                self.dismiss((None, True))  # clear sort
        else:
            self.dismiss((col, True))  # new column, ascending

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
        Binding("n", "edit_note", "Note"),
        Binding("s", "skip", "Skip"),
        Binding("t", "toggle_mode", "Table View"),
        Binding("q", "quit_review", "Quit"),
    ]

    def __init__(
        self, conn: sqlite3.Connection, month: int, year: int, copilot_token: str = ""
    ) -> None:
        super().__init__()
        self.conn = conn
        self.month = month
        self.year = year
        self._copilot_token = copilot_token
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
        amount = -txn["amount"] / 100
        account_name = self._format_account(txn)
        note = txn["note"] or ""
        styled_cat = self._styled_label(txn["label_id"])

        content = Text()
        content.append(f"Transaction {self._current_idx + 1}/{total}\n\n")
        content.append(f"  Date:     {txn['date']}\n")
        content.append(f"  Merchant: {txn['description']}\n")
        content.append(f"  Amount:   ${amount:,.2f}\n")
        content.append("  Category: ")
        content.append_text(styled_cat)
        content.append(f"\n  Account:  {account_name}\n")
        content.append(f"  Source:   {txn['categorized_by'] or 'none'}\n")
        if note:
            content.append(f"  Note:     {note}\n")
        content.append(
            "\n  [a] Accept  [c] Change  [e] Exempt  [n] Note  [s] Skip  [t] Table  [q] Quit"
        )
        detail.update(content)

    def _format_account(self, txn) -> str:
        name = txn["institution_name"] or ""
        last4 = txn["last_four"] or ""
        if name and last4:
            return f"{name} ••{last4}"
        return name or last4 or "Unknown"

    def _get_label_name(self, label_id: int | None) -> str | None:
        if label_id is None:
            return None
        row = self.conn.execute(
            "SELECT name FROM labels WHERE id = ?", (label_id,)
        ).fetchone()
        return row["name"] if row else None

    def _styled_label(self, label_id: int | None) -> Text:
        """Return a Text with the label's background color and contrasting text."""
        if label_id is None:
            return Text("Uncategorized")
        row = self.conn.execute(
            "SELECT name, color FROM labels WHERE id = ?", (label_id,)
        ).fetchone()
        if not row:
            return Text("Uncategorized")
        name = row["name"]
        color = row["color"]
        if color:
            fg = _text_color_for_bg(color)
            return Text(f" {name} ", style=f"{fg} on {color}")
        return Text(name)

    def _advance(self) -> None:
        self._current_idx += 1
        self._show_current()

    def _push_to_copilot(self, fn, *args) -> None:
        """Fire a Copilot Money mutation in a background worker."""
        if not self._copilot_token:
            return

        def _do():
            try:
                with copilot.create_client(self._copilot_token) as client:
                    fn(client, *args)
            except copilot.CopilotAuthError:
                self.app.notify(
                    "Copilot sync failed: token expired. Run `finmint token`.",
                    severity="warning",
                )
            except Exception as e:
                self.app.notify(f"Copilot sync error: {e}", severity="warning")

        self.app.run_worker(_do, thread=True)

    def _sync_category_and_review(self, txn, label_id: int | None) -> None:
        """Push category + reviewed status to Copilot Money for a transaction."""
        if not txn["item_id"] or not txn["account_id"]:
            return
        copilot_cat_id = get_copilot_id_for_label(self.conn, label_id) if label_id else None
        if copilot_cat_id:
            self._push_to_copilot(
                copilot.set_transaction_category,
                txn["id"], txn["account_id"], txn["item_id"], copilot_cat_id,
            )
        self._push_to_copilot(
            copilot.set_transaction_reviewed,
            txn["id"], txn["account_id"], txn["item_id"], True,
        )

    def action_accept(self) -> None:
        if self._current_idx >= len(self._unreviewed):
            return
        txn = self._unreviewed[self._current_idx]
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"],
            txn["categorized_by"] or "manual", "reviewed",
        )
        self._sync_category_and_review(txn, txn["label_id"])
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
        if txn["normalized_description"]:
            add_rule(self.conn, txn["normalized_description"], label_id, source="auto_learned")
        self._sync_category_and_review(txn, label_id)
        self._advance()

    def action_exempt(self) -> None:
        if self._current_idx >= len(self._unreviewed):
            return
        txn = self._unreviewed[self._current_idx]
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"], txn["categorized_by"], "exempt",
        )
        # Exempt is local-only — no Copilot mutation
        self._advance()

    def action_skip(self) -> None:
        self._advance()

    def action_edit_note(self) -> None:
        if self._current_idx >= len(self._unreviewed):
            return
        txn = self._unreviewed[self._current_idx]
        self.app.push_screen(NoteInputScreen(txn["note"]), self._on_note_entered)

    def _on_note_entered(self, note: str | None) -> None:
        if note is None:
            return
        txn = self._unreviewed[self._current_idx]
        update_transaction_note(self.conn, txn["id"], note)
        if txn["item_id"] and txn["account_id"]:
            self._push_to_copilot(
                copilot.set_transaction_note,
                txn["id"], txn["account_id"], txn["item_id"], note,
            )
        self._load_unreviewed()
        self._show_current()

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
        Binding("c", "change_category", "Change Category"),
        Binding("e", "exempt", "Exempt"),
        Binding("n", "edit_note", "Note"),
        Binding("s", "sort", "Sort"),
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
    #note-container {
        align: center middle;
        width: 70;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #sort-container {
        align: center middle;
        width: 40;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def __init__(
        self, conn: sqlite3.Connection, month: int, year: int, copilot_token: str = ""
    ) -> None:
        super().__init__()
        self.conn = conn
        self.month = month
        self.year = year
        self._copilot_token = copilot_token
        self._selected_keys: set[str] = set()
        self._sort_column: str | None = None
        self._sort_ascending: bool = True

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="summary")
        yield DataTable(id="review-table")
        yield Static("All transactions reviewed!", id="all-reviewed")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.cursor_type = "row"
        self._col_keys = table.add_columns("Date", "Merchant", "Amount", "Category", "Account", "Note", "Status")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.clear()
        self._selected_keys.clear()
        txns = get_transactions(self.conn, self.month, self.year)

        self._update_column_headers()

        all_reviewed_msg = self.query_one("#all-reviewed", Static)
        if not txns:
            table.display = False
            all_reviewed_msg.update("No transactions for this period.")
            all_reviewed_msg.display = True
            self._update_summary()
            return
        table.display = True

        for txn in self._sorted_transactions(txns):
            cells = self._build_row_cells(txn)
            table.add_row(*cells, key=txn["id"])

        self._update_summary()

    def _build_row_cells(self, txn) -> list:
        """Build the cell values for a transaction row."""
        amount = -txn["amount"] / 100
        status = txn["review_status"]
        account_name = self._format_account(txn)
        note = txn["note"] or ""

        if status == "exempt":
            label_name = self._get_label_name(txn["label_id"]) or "—"
            return [
                Text(txn["date"], style="dim strike"),
                Text(txn["description"] or "", style="dim strike"),
                Text(f"${amount:,.2f}", style="dim strike"),
                Text(label_name, style="dim strike"),
                Text(account_name, style="dim strike"),
                Text(note, style="dim strike"),
                Text("exempt", style="dim"),
            ]

        styled_cat = self._styled_label(txn["label_id"])
        if status in ("reviewed", "auto_accepted"):
            return [
                txn["date"],
                txn["description"] or "",
                f"${amount:,.2f}",
                styled_cat,
                account_name,
                note,
                Text("✓", style="green"),
            ]
        else:
            return [
                txn["date"],
                txn["description"] or "",
                f"${amount:,.2f}",
                styled_cat,
                account_name,
                note,
                Text("? review", style="yellow"),
            ]

    def _update_row(self, txn_id: str) -> None:
        """Update a single row in-place without clearing the table."""
        table = self.query_one("#review-table", DataTable)
        txn = self.conn.execute(
            "SELECT t.*, a.institution_name, a.last_four "
            "FROM transactions t "
            "LEFT JOIN accounts a ON t.account_id = a.id "
            "WHERE t.id = ?",
            (txn_id,),
        ).fetchone()
        if not txn:
            return
        cells = self._build_row_cells(txn)
        for col_key, value in zip(self._col_keys, cells):
            table.update_cell(txn_id, col_key, value)

    def _update_summary(self) -> None:
        """Update the summary line and all-reviewed banner."""
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
        all_reviewed_msg.display = (needs_review == 0)

    def _format_account(self, txn) -> str:
        name = txn["institution_name"] or ""
        last4 = txn["last_four"] or ""
        if name and last4:
            return f"{name} ••{last4}"
        return name or last4 or "—"

    def _get_label_name(self, label_id: int | None) -> str | None:
        if label_id is None:
            return None
        row = self.conn.execute(
            "SELECT name FROM labels WHERE id = ?", (label_id,)
        ).fetchone()
        return row["name"] if row else None

    def _styled_label(self, label_id: int | None) -> Text:
        """Return a Text with the label's background color and contrasting text."""
        if label_id is None:
            return Text("—")
        row = self.conn.execute(
            "SELECT name, color FROM labels WHERE id = ?", (label_id,)
        ).fetchone()
        if not row:
            return Text("—")
        name = row["name"]
        color = row["color"]
        if color:
            fg = _text_color_for_bg(color)
            return Text(f" {name} ", style=f"{fg} on {color}")
        return Text(name)

    def _sorted_transactions(self, txns: list) -> list:
        """Return transactions sorted by the current sort column/direction."""
        if self._sort_column is None:
            return txns

        def sort_key(txn):
            col = self._sort_column
            if col == "date":
                return txn["date"] or ""
            elif col == "merchant":
                return (txn["description"] or "").lower()
            elif col == "amount":
                return txn["amount"]
            elif col == "category":
                return (self._get_label_name(txn["label_id"]) or "").lower()
            elif col == "account":
                return self._format_account(txn).lower()
            elif col == "note":
                return (txn["note"] or "").lower()
            elif col == "status":
                return txn["review_status"] or ""
            return ""

        return sorted(txns, key=sort_key, reverse=not self._sort_ascending)

    def _update_column_headers(self) -> None:
        """Update column header labels with sort direction indicators."""
        table = self.query_one("#review-table", DataTable)
        for i, col_key in enumerate(self._col_keys):
            label = _COLUMN_LABELS[i]
            if self._sort_column == _SORT_COLUMNS[i]:
                label += " ▲" if self._sort_ascending else " ▼"
            table.columns[col_key].label = Text(label)

    def _apply_sort(self, column: str) -> None:
        """Toggle sort on a column: asc -> desc -> clear."""
        if self._sort_column == column:
            if self._sort_ascending:
                self._sort_ascending = False
            else:
                self._sort_column = None
        else:
            self._sort_column = column
            self._sort_ascending = True
        self._refresh_table()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Sort by clicked column header."""
        idx = event.column_index
        if idx < len(_SORT_COLUMNS):
            self._apply_sort(_SORT_COLUMNS[idx])

    def _push_to_copilot(self, fn, *args) -> None:
        """Fire a Copilot Money mutation in a background worker."""
        if not self._copilot_token:
            return

        def _do():
            try:
                with copilot.create_client(self._copilot_token) as client:
                    fn(client, *args)
            except copilot.CopilotAuthError:
                self.notify(
                    "Copilot sync failed: token expired. Run `finmint token`.",
                    severity="warning",
                )
            except Exception as e:
                self.notify(f"Copilot sync error: {e}", severity="warning")

        self.run_worker(_do, thread=True)

    def _sync_category_and_review(self, txn, label_id: int | None) -> None:
        """Push category + reviewed status to Copilot Money for a transaction."""
        if not txn["item_id"] or not txn["account_id"]:
            return
        copilot_cat_id = get_copilot_id_for_label(self.conn, label_id) if label_id else None
        if copilot_cat_id:
            self._push_to_copilot(
                copilot.set_transaction_category,
                txn["id"], txn["account_id"], txn["item_id"], copilot_cat_id,
            )
        self._push_to_copilot(
            copilot.set_transaction_reviewed,
            txn["id"], txn["account_id"], txn["item_id"], True,
        )

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
        self._sync_category_and_review(txn, txn["label_id"])
        self._update_row(txn["id"])
        self._update_summary()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter key on a row — open category picker."""
        self.action_change_category()

    def action_change_category(self) -> None:
        txn = self._get_selected_txn()
        if not txn:
            return
        self._editing_txn_id = txn["id"]
        self._editing_txn_desc = txn["normalized_description"]
        self._editing_txn = txn
        self.push_screen(LabelPickerScreen(self.conn), self._on_category_picked)

    def _on_category_picked(self, label_id: int | None) -> None:
        if label_id is None:
            return
        update_transaction_label(self.conn, self._editing_txn_id, label_id, "manual", "reviewed")
        if self._editing_txn_desc:
            add_rule(self.conn, self._editing_txn_desc, label_id, source="auto_learned")
        self._sync_category_and_review(self._editing_txn, label_id)
        self._update_row(self._editing_txn_id)
        self._update_summary()

    def action_exempt(self) -> None:
        txn = self._get_selected_txn()
        if not txn:
            return
        update_transaction_label(
            self.conn, txn["id"], txn["label_id"], txn["categorized_by"], "exempt",
        )
        # Exempt is local-only — no Copilot mutation
        self._update_row(txn["id"])
        self._update_summary()

    def action_edit_note(self) -> None:
        txn = self._get_selected_txn()
        if not txn:
            return
        self._noting_txn_id = txn["id"]
        self._noting_txn = txn
        self.push_screen(NoteInputScreen(txn["note"]), self._on_note_entered)

    def _on_note_entered(self, note: str | None) -> None:
        if note is None:
            return
        update_transaction_note(self.conn, self._noting_txn_id, note)
        txn = self._noting_txn
        if txn["item_id"] and txn["account_id"]:
            self._push_to_copilot(
                copilot.set_transaction_note,
                txn["id"], txn["account_id"], txn["item_id"], note,
            )
        self._update_row(self._noting_txn_id)

    def action_sort(self) -> None:
        self.push_screen(
            SortPickerScreen(self._sort_column, self._sort_ascending),
            self._on_sort_picked,
        )

    def _on_sort_picked(self, result: tuple[str | None, bool] | None) -> None:
        if result is None:
            return
        col, ascending = result
        self._sort_column = col
        self._sort_ascending = ascending
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
                self._sync_category_and_review(txn, txn["label_id"])
                self._update_row(txn["id"])
        self._selected_keys.clear()
        self._update_summary()

    def action_toggle_mode(self) -> None:
        self.push_screen(
            OneByOneScreen(self.conn, self.month, self.year, self._copilot_token)
        )
