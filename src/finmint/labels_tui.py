"""Textual TUI for viewing and editing Copilot Money categories."""

import sqlite3

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.screen import ModalScreen

from finmint import copilot
from finmint.config import get_token
from finmint.copilot import COPILOT_COLOR_MAP, COPILOT_HEX_TO_NAME
from finmint.db import get_labels


def _is_hex_color(color: str) -> bool:
    """Return True if color is a valid hex color like '#2ecc71' or '2ecc71'."""
    h = color.lstrip("#")
    return len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h)


def _text_color_for_bg(hex_color: str) -> str:
    """Return 'white' or 'black' for best contrast against a hex background."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return "black" if luminance > 0.5 else "white"


# Display names for the color picker
_COLOR_DISPLAY_NAMES: dict[str, str] = {
    "RED1": "Red 1",
    "RED2": "Red 2",
    "ORANGE1": "Orange 1",
    "ORANGE2": "Orange 2",
    "BROWN1": "Brown 1",
    "YELLOW1": "Yellow 1",
    "YELLOW2": "Yellow 2",
    "OLIVE1": "Olive 1",
    "GREEN1": "Green 1",
    "TEAL1": "Teal 1",
    "BLUE1": "Blue 1",
    "PURPLE1": "Purple 1",
    "PURPLE2": "Purple 2",
    "PINK1": "Pink 1",
    "PINK2": "Pink 2",
    "GRAY1": "Gray 1",
}


class ColorPickerScreen(ModalScreen[str | None]):
    """Pick a color from the Copilot Money palette."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    #color-picker-container {
        align: center middle;
        width: 40;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def __init__(self, current_hex: str | None = None) -> None:
        super().__init__()
        self._current_hex = current_hex

    def compose(self) -> ComposeResult:
        options: list[Option] = []
        for name, hex_code in COPILOT_COLOR_MAP.items():
            display = _COLOR_DISPLAY_NAMES.get(name, name)
            fg = _text_color_for_bg(hex_code)
            label = Text(f" {display} ", style=f"{fg} on {hex_code}")
            if self._current_hex and hex_code.lower() == self._current_hex.lower():
                label.append("  ✓", style="bold")
            options.append(Option(label, id=name))
        with Vertical(id="color-picker-container"):
            yield Label("Select color:")
            yield OptionList(*options, id="color-picker")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LabelsApp(App):
    """Viewer and color editor for Copilot Money categories."""

    TITLE = "Finmint — Categories (from Copilot Money)"
    MOUSE_SUPPORT = False

    BINDINGS = [
        Binding("c", "change_color", "Change Color"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        try:
            self._copilot_token = get_token()
        except Exception:
            self._copilot_token = ""

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
            if color and _is_hex_color(color):
                fg = _text_color_for_bg(color)
                label_cell = Text(f" {label['name']} ", style=f"{fg} on {color}")
                color_cell = Text(f" {color} ", style=f"{fg} on {color}")
            else:
                label_cell = label["name"]
                color_cell = "—"
            table.add_row(icon, label_cell, color_cell, str(count), key=str(label["id"]))

    def _get_selected_label(self) -> dict | None:
        table = self.query_one("#labels-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        label_id = int(row_key.value)
        return self.conn.execute(
            "SELECT * FROM labels WHERE id = ?", (label_id,)
        ).fetchone()

    def action_change_color(self) -> None:
        label = self._get_selected_label()
        if not label:
            return
        self._editing_label_id = label["id"]
        self._editing_copilot_id = label["copilot_id"]
        self.push_screen(ColorPickerScreen(label["color"]), self._on_color_picked)

    def _on_color_picked(self, color_name: str | None) -> None:
        if color_name is None:
            return
        hex_code = COPILOT_COLOR_MAP.get(color_name)
        if not hex_code:
            return
        # Update local DB
        self.conn.execute(
            "UPDATE labels SET color = ? WHERE id = ?",
            (hex_code, self._editing_label_id),
        )
        self.conn.commit()
        self._refresh_table()

        # Push to Copilot Money
        if self._copilot_token and self._editing_copilot_id:
            def _do():
                try:
                    with copilot.create_client(self._copilot_token) as client:
                        copilot.set_category_color(
                            client, self._editing_copilot_id, color_name,
                        )
                except copilot.CopilotAuthError:
                    self.notify(
                        "Copilot sync failed: token expired.", severity="warning",
                    )
                except Exception as e:
                    self.notify(f"Copilot sync error: {e}", severity="warning")

            self.run_worker(_do, thread=True)

    def _move_cursor(self, delta: int) -> None:
        table = self.query_one("#labels-table", DataTable)
        if table.row_count == 0:
            return
        row, col = table.cursor_coordinate
        new_row = max(0, min(row + delta, table.row_count - 1))
        table.move_cursor(row=new_row)

    def action_cursor_down(self) -> None:
        self._move_cursor(1)

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)
