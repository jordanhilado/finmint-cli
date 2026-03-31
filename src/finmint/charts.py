"""Charts & Visualization for finmint.

Renders monthly pie charts and yearly bar charts via Matplotlib,
saves to temp PNG files, and opens with the system viewer.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

# Use non-interactive backend when no display is available.
matplotlib.use("Agg")

# ---------------------------------------------------------------------------
# Consistent color palette keyed by label name
# ---------------------------------------------------------------------------

_LABEL_COLORS: dict[str, str] = {
    "Groceries": "#2ecc71",
    "Dining Out": "#e74c3c",
    "Transport": "#3498db",
    "Housing": "#9b59b6",
    "Utilities": "#f39c12",
    "Subscriptions": "#1abc9c",
    "Shopping": "#e67e22",
    "Health": "#2980b9",
    "Entertainment": "#d35400",
    "Income": "#27ae60",
    "Travel": "#8e44ad",
    "Education": "#16a085",
    "Personal Care": "#c0392b",
    "Gifts": "#f1c40f",
    "Fees & Interest": "#7f8c8d",
}

# Fallback colors for user-created labels
_EXTRA_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9a6324", "#800000", "#aaffc3",
    "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]


def _get_color(label_name: str, idx: int) -> str:
    """Return a consistent color for a label name."""
    if label_name in _LABEL_COLORS:
        return _LABEL_COLORS[label_name]
    return _EXTRA_COLORS[idx % len(_EXTRA_COLORS)]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _spending_by_category(
    conn: sqlite3.Connection, month: int, year: int
) -> pd.DataFrame:
    """Query spending grouped by label, excluding exempt and Transfer.

    Returns DataFrame with columns: label_name, total_dollars.
    Amounts are absolute values in dollars (spending is negative cents in DB).
    """
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    query = """
        SELECT l.name AS label_name, SUM(ABS(t.amount)) AS total_cents
        FROM transactions t
        JOIN labels l ON t.label_id = l.id
        WHERE t.date >= ? AND t.date < ?
          AND t.review_status != 'exempt'
          AND l.name NOT IN ('Transfer', 'Income')
        GROUP BY l.name
        ORDER BY total_cents DESC
    """
    rows = conn.execute(query, (start, end)).fetchall()
    if not rows:
        return pd.DataFrame(columns=["label_name", "total_dollars"])

    df = pd.DataFrame(rows, columns=["label_name", "total_cents"])
    df["total_dollars"] = df["total_cents"] / 100.0
    return df[["label_name", "total_dollars"]]


def _monthly_totals_by_category(
    conn: sqlite3.Connection, year: int
) -> pd.DataFrame:
    """Query monthly spending by category for a year.

    Returns DataFrame with columns: month, label_name, total_dollars.
    """
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"

    query = """
        SELECT CAST(strftime('%m', t.date) AS INTEGER) AS month,
               l.name AS label_name,
               SUM(ABS(t.amount)) AS total_cents
        FROM transactions t
        JOIN labels l ON t.label_id = l.id
        WHERE t.date >= ? AND t.date < ?
          AND t.review_status != 'exempt'
          AND l.name NOT IN ('Transfer', 'Income')
        GROUP BY month, l.name
        ORDER BY month, total_cents DESC
    """
    rows = conn.execute(query, (start, end)).fetchall()
    if not rows:
        return pd.DataFrame(columns=["month", "label_name", "total_dollars"])

    df = pd.DataFrame(rows, columns=["month", "label_name", "total_cents"])
    df["total_dollars"] = df["total_cents"] / 100.0
    return df[["month", "label_name", "total_dollars"]]


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------


def render_monthly_pie(
    conn: sqlite3.Connection, month: int, year: int
) -> Optional[str]:
    """Render a pie chart of spending by category for a given month.

    Returns the path to the saved PNG file, or None if no data to chart.
    """
    df = _spending_by_category(conn, month, year)
    if df.empty:
        return None

    labels = df["label_name"].tolist()
    amounts = df["total_dollars"].tolist()
    colors = [_get_color(name, i) for i, name in enumerate(labels)]

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        amounts,
        labels=None,
        autopct="%1.1f%%",
        colors=colors,
        startangle=140,
    )

    # Build legend with dollar amounts
    legend_labels = [f"{name} (${amt:,.2f})" for name, amt in zip(labels, amounts)]
    ax.legend(
        wedges,
        legend_labels,
        title="Categories",
        loc="center left",
        bbox_to_anchor=(1, 0, 0.5, 1),
    )

    ax.set_title(f"Spending by Category — {month}/{year}")
    fig.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    fig.savefig(tmp.name, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return tmp.name


def render_yearly_bars(
    conn: sqlite3.Connection, year: int
) -> Optional[str]:
    """Render a stacked bar chart of monthly spending by category for a year.

    Returns the path to the saved PNG file, or None if no data to chart.
    """
    df = _monthly_totals_by_category(conn, year)
    if df.empty:
        return None

    # Pivot: rows=month, columns=label_name, values=total_dollars
    pivot = df.pivot_table(
        index="month",
        columns="label_name",
        values="total_dollars",
        aggfunc="sum",
        fill_value=0,
    )

    # Assign colors consistently
    cat_colors = [
        _get_color(name, i) for i, name in enumerate(pivot.columns)
    ]

    fig, ax = plt.subplots(figsize=(12, 6))
    pivot.plot(kind="bar", stacked=True, ax=ax, color=cat_colors, width=0.7)

    ax.set_title(f"Monthly Spending by Category — {year}")
    ax.set_xlabel("Month")
    ax.set_ylabel("Amount ($)")
    ax.set_xticklabels(
        [f"{int(m)}" for m in pivot.index], rotation=0
    )
    ax.legend(
        title="Categories",
        bbox_to_anchor=(1.05, 1),
        loc="upper left",
    )
    fig.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    fig.savefig(tmp.name, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return tmp.name


# ---------------------------------------------------------------------------
# Cross-platform chart opener
# ---------------------------------------------------------------------------


def open_chart(path: str) -> None:
    """Open a chart image using the system's default viewer.

    Falls back to printing the file path if the opener command fails.
    """
    if sys.platform == "darwin":
        cmd = ["open", path]
    elif sys.platform.startswith("linux"):
        cmd = ["xdg-open", path]
    elif sys.platform == "win32":
        cmd = ["start", "", path]
    else:
        print(f"Chart saved to: {path}")
        return

    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"Chart saved to: {path}")
