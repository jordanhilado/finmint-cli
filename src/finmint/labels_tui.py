"""Textual TUI for managing category labels."""

import sqlite3

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.screen import ModalScreen

from finmint.db import get_labels


class LabelInputScreen(ModalScreen[str | None]):
    """Modal for entering a label name."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="input-container"):
            yield Label("Enter label name:")
            yield Input(id="label-input", value=self.initial)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        self.dismiss(value if value else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ReassignScreen(ModalScreen[int | None]):
    """Modal to pick a reassignment target when deleting a label."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, conn: sqlite3.Connection, exclude_id: int, count: int) -> None:
        super().__init__()
        self.conn = conn
        self.exclude_id = exclude_id
        self.count = count

    def compose(self) -> ComposeResult:
        labels = [r for r in get_labels(self.conn) if r["id"] != self.exclude_id]
        with Vertical(id="reassign-container"):
            yield Label(
                f"Reassign {self.count} transaction(s) to which label?"
            )
            yield OptionList(
                *[Option(r["name"], id=str(r["id"])) for r in labels],
                id="reassign-options",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)


class LabelsApp(App):
    """Interactive TUI for managing category labels."""

    TITLE = "Finmint — Labels"

    BINDINGS = [
        Binding("a", "add_label", "Add Label"),
        Binding("enter", "edit_label", "Edit Name"),
        Binding("d", "delete_label", "Delete Label"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #input-container, #reassign-container {
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
        yield DataTable(id="labels-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#labels-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Label", "Transactions", "Type")
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
            ltype = "protected" if label["is_protected"] else (
                "default" if label["is_default"] else "custom"
            )
            table.add_row(label["name"], str(count), ltype, key=str(label["id"]))

    def _get_selected_label(self) -> tuple[int, str, bool] | None:
        table = self.query_one("#labels-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        label_id = int(row_key.value)
        row_idx = table.cursor_coordinate.row
        row_data = table.get_row_at(row_idx)
        name = row_data[0]
        is_protected = row_data[2] == "protected"
        return label_id, name, is_protected

    def action_add_label(self) -> None:
        self.push_screen(LabelInputScreen(), self._on_add_submitted)

    def _on_add_submitted(self, name: str | None) -> None:
        if not name:
            return
        try:
            self.conn.execute(
                "INSERT INTO labels (name, is_default, is_protected, created_at) "
                "VALUES (?, 0, 0, datetime('now'))",
                (name,),
            )
            self.conn.commit()
            self._refresh_table()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_edit_label(self) -> None:
        selected = self._get_selected_label()
        if not selected:
            return
        label_id, name, is_protected = selected
        if is_protected:
            self.notify("Protected labels cannot be renamed.", severity="warning")
            return
        self._editing_label_id = label_id
        self.push_screen(LabelInputScreen(initial=name), self._on_edit_submitted)

    def _on_edit_submitted(self, new_name: str | None) -> None:
        if not new_name:
            return
        try:
            self.conn.execute(
                "UPDATE labels SET name = ? WHERE id = ?",
                (new_name, self._editing_label_id),
            )
            self.conn.commit()
            self._refresh_table()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_delete_label(self) -> None:
        selected = self._get_selected_label()
        if not selected:
            return
        label_id, name, is_protected = selected
        if is_protected:
            self.notify("Protected labels cannot be deleted.", severity="warning")
            return
        # Check how many labels remain
        total = self.conn.execute("SELECT COUNT(*) as c FROM labels").fetchone()["c"]
        if total <= 1:
            self.notify("Cannot delete the last label.", severity="warning")
            return
        # Check affected transactions
        count = self.conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE label_id = ?",
            (label_id,),
        ).fetchone()["c"]
        if count > 0:
            self._deleting_label_id = label_id
            self.push_screen(
                ReassignScreen(self.conn, label_id, count),
                self._on_reassign_selected,
            )
        else:
            self.conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))
            self.conn.commit()
            self._refresh_table()

    def _on_reassign_selected(self, target_id: int | None) -> None:
        if target_id is None:
            return
        label_id = self._deleting_label_id
        # Atomic: reassign transactions + rules, then delete label
        with self.conn:
            self.conn.execute(
                "UPDATE transactions SET label_id = ? WHERE label_id = ?",
                (target_id, label_id),
            )
            self.conn.execute(
                "UPDATE merchant_rules SET label_id = ? WHERE label_id = ?",
                (target_id, label_id),
            )
            self.conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))
        self._refresh_table()
