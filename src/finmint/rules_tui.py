"""Textual TUI for managing merchant categorization rules."""

import sqlite3

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.screen import ModalScreen

from finmint.db import get_labels
from finmint.rules import add_rule, delete_rule, get_all_rules, update_rule


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------


class LabelSelectScreen(ModalScreen[int | None]):
    """Modal that lets the user pick a label. Resolves with label_id or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, conn: sqlite3.Connection, prompt: str = "Select a label:") -> None:
        super().__init__()
        self.conn = conn
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        labels = get_labels(self.conn)
        with Vertical(id="label-select-container"):
            yield Label(self.prompt)
            ol = OptionList(
                *[Option(row["name"], id=str(row["id"])) for row in labels],
                id="label-options",
            )
            yield ol

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)


class PatternInputScreen(ModalScreen[str | None]):
    """Modal for entering a rule pattern string."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="pattern-input-container"):
            yield Label("Enter pattern (substring to match):")
            yield Input(id="pattern-input", placeholder="e.g. TRADER JOE")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Modal confirmation for deleting a rule."""

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "Cancel"),
    ]

    def __init__(self, pattern: str) -> None:
        super().__init__()
        self.pattern = pattern

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(f"Delete rule for '{self.pattern}'? (y/n)")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class RulesApp(App):
    """Interactive TUI for managing merchant categorization rules."""

    TITLE = "Finmint — Merchant Rules"

    BINDINGS = [
        Binding("a", "add_rule", "Add Rule"),
        Binding("d", "delete_rule", "Delete Rule"),
        Binding("enter", "edit_rule", "Edit Label"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #empty-message {
        text-align: center;
        margin: 4 2;
        color: $text-muted;
    }
    #label-select-container, #pattern-input-container, #confirm-container {
        align: center middle;
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="rules-table")
        yield Static("No rules yet. Press 'a' to add your first rule.", id="empty-message")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Pattern", "Label", "Source", "Created")
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
            created = rule["created_at"][:10] if rule["created_at"] else ""
            table.add_row(
                rule["pattern"],
                rule["label_name"],
                rule["source"],
                created,
                key=str(rule["id"]),
            )

    # -- Add flow: pattern input -> label select --

    def action_add_rule(self) -> None:
        self.push_screen(PatternInputScreen(), self._on_pattern_entered)

    def _on_pattern_entered(self, pattern: str | None) -> None:
        if pattern is None:
            return
        self._pending_pattern = pattern
        self.push_screen(
            LabelSelectScreen(self.conn, prompt=f"Select label for '{pattern}':"),
            self._on_add_label_selected,
        )

    def _on_add_label_selected(self, label_id: int | None) -> None:
        if label_id is None:
            return
        add_rule(self.conn, self._pending_pattern, label_id)
        self._refresh_table()

    # -- Edit flow: change label of selected rule --

    def action_edit_rule(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        self._editing_rule_id = int(row_key.value)
        self.push_screen(
            LabelSelectScreen(self.conn, prompt="Select new label:"),
            self._on_edit_label_selected,
        )

    def _on_edit_label_selected(self, label_id: int | None) -> None:
        if label_id is None:
            return
        update_rule(self.conn, self._editing_rule_id, label_id)
        self._refresh_table()

    # -- Delete flow: confirm then delete --

    def action_delete_rule(self) -> None:
        table = self.query_one("#rules-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        self._deleting_rule_id = int(row_key.value)
        # Get pattern for display
        row_idx = table.cursor_coordinate.row
        pattern = table.get_row_at(row_idx)[0]
        self.push_screen(ConfirmDeleteScreen(pattern), self._on_delete_confirmed)

    def _on_delete_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        delete_rule(self.conn, self._deleting_rule_id)
        self._refresh_table()
