#!/usr/bin/env python3
"""Generate demo screenshots with mock data for the README.

Produces SVG screenshots for each TUI app and PNG charts via matplotlib.
All data is fake and lives only in an in-memory SQLite database.

Usage:
    python scripts/generate_screenshots.py
"""

import asyncio
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

CATEGORIES = [
    ("cat-001", "Groceries", "#2ecc71", "🛒"),
    ("cat-002", "Dining Out", "#e74c3c", "🍽️"),
    ("cat-003", "Transport", "#3498db", "🚗"),
    ("cat-004", "Housing", "#9b59b6", "🏠"),
    ("cat-005", "Utilities", "#f39c12", "💡"),
    ("cat-006", "Subscriptions", "#1abc9c", "🔁"),
    ("cat-007", "Shopping", "#e67e22", "🛍️"),
    ("cat-008", "Health", "#2980b9", "💊"),
    ("cat-009", "Entertainment", "#d35400", "🎬"),
    ("cat-010", "Income", "#27ae60", "💰"),
    ("cat-011", "Transfer", "#7f8c8d", "🔄"),
    ("cat-012", "Travel", "#8e44ad", "✈️"),
    ("cat-013", "Personal Care", "#c0392b", "💇"),
    ("cat-014", "Fees & Interest", "#95a5a6", "🏦"),
]

ACCOUNTS = [
    ("acct-001", "Chase", "checking", "4821", "2026-03-28T12:00:00Z"),
    ("acct-002", "Amex", "credit", "1008", "2026-03-28T12:00:00Z"),
    ("acct-003", "Ally Bank", "savings", "7734", "2026-03-27T09:30:00Z"),
]

# (description, normalized, amount_cents, date, account_idx, label_idx, status, note)
TRANSACTIONS_MAR = [
    ("TRADER JOE'S #123", "trader joe's", -8742, "2026-03-02", 0, 0, "reviewed", None),
    ("WHOLE FOODS MKT", "whole foods", -6523, "2026-03-03", 0, 0, "reviewed", None),
    ("UBER EATS", "uber eats", -3450, "2026-03-04", 1, 1, "reviewed", None),
    ("CHEVRON GAS", "chevron", -5820, "2026-03-05", 0, 2, "reviewed", None),
    ("NETFLIX.COM", "netflix", -1599, "2026-03-06", 1, 5, "auto_accepted", None),
    ("SPOTIFY USA", "spotify", -1099, "2026-03-06", 1, 5, "auto_accepted", None),
    ("AMAZON.COM", "amazon", -14999, "2026-03-07", 1, 6, "reviewed", "New headphones"),
    ("CVS PHARMACY", "cvs pharmacy", -2345, "2026-03-08", 0, 7, "reviewed", None),
    ("AMC THEATRES", "amc theatres", -3200, "2026-03-09", 1, 8, "needs_review", None),
    ("VENMO PAYMENT", "venmo", -5000, "2026-03-10", 0, 10, "exempt", None),
    ("RENT PAYMENT", "rent", -195000, "2026-03-01", 0, 3, "reviewed", None),
    ("PG&E ELECTRIC", "pg&e", -12450, "2026-03-12", 0, 4, "reviewed", None),
    ("LYFT RIDE", "lyft", -2875, "2026-03-14", 1, 2, "needs_review", None),
    ("TARGET STORE", "target", -8932, "2026-03-15", 0, 6, "needs_review", None),
    ("CHIPOTLE", "chipotle", -1245, "2026-03-16", 1, 1, "reviewed", None),
    ("EMPLOYER DIRECT DEP", "employer", 550000, "2026-03-15", 0, 9, "auto_accepted", None),
    ("SAFEWAY GROCERY", "safeway", -7821, "2026-03-18", 0, 0, "reviewed", None),
    ("COSTCO WHOLESALE", "costco", -15634, "2026-03-20", 0, 0, "reviewed", "Monthly stock-up"),
    ("DELTA AIRLINES", "delta airlines", -34500, "2026-03-21", 1, 11, "reviewed", "LA trip"),
    ("HAIRCUT SALON", "haircut salon", -4500, "2026-03-22", 0, 12, "needs_review", None),
    ("CHASE CC PAYMENT", "chase cc", -25000, "2026-03-25", 0, 10, "exempt", None),
    ("BANK FEE", "bank fee", -1500, "2026-03-26", 2, 13, "reviewed", None),
    ("COMCAST INTERNET", "comcast", -7999, "2026-03-05", 0, 4, "auto_accepted", None),
    ("STARBUCKS", "starbucks", -675, "2026-03-19", 1, 1, "reviewed", None),
]

# Extra months for yearly chart
TRANSACTIONS_OTHER_MONTHS = [
    # January
    (-9200, "2026-01-05", 0, 0), (-3100, "2026-01-10", 1, 1),
    (-195000, "2026-01-01", 0, 3), (-12000, "2026-01-15", 0, 4),
    (-5500, "2026-01-20", 0, 2), (-2600, "2026-01-22", 1, 5),
    # February
    (-8800, "2026-02-03", 0, 0), (-4200, "2026-02-08", 1, 1),
    (-195000, "2026-02-01", 0, 3), (-11800, "2026-02-12", 0, 4),
    (-6100, "2026-02-18", 0, 2), (-2600, "2026-02-20", 1, 5),
    (-22000, "2026-02-14", 1, 8),
]


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------


def build_demo_db() -> sqlite3.Connection:
    """Create an in-memory DB with mock data."""
    from finmint.db import init_db, upsert_category, upsert_account, insert_transaction

    conn = init_db(":memory:")

    # Labels
    for copilot_id, name, color, icon in CATEGORIES:
        upsert_category(conn, copilot_id, name, color, icon)

    # Accounts
    for aid, inst, atype, last4, synced in ACCOUNTS:
        upsert_account(conn, {
            "id": aid,
            "institution_name": inst,
            "account_type": atype,
            "last_four": last4,
            "last_synced_at": synced,
        })

    # Build label name -> id map
    label_map = {}
    for row in conn.execute("SELECT id, name FROM labels").fetchall():
        label_map[row[0]] = row[1]
    # Build by index
    label_ids = [
        conn.execute("SELECT id FROM labels WHERE copilot_id = ?", (c[0],)).fetchone()[0]
        for c in CATEGORIES
    ]

    # March transactions
    for desc, norm, amount, date, acct_idx, lbl_idx, status, note in TRANSACTIONS_MAR:
        insert_transaction(conn, {
            "id": str(uuid.uuid4()),
            "account_id": ACCOUNTS[acct_idx][0],
            "item_id": f"item-{uuid.uuid4().hex[:8]}",
            "amount": amount,
            "date": date,
            "description": desc,
            "normalized_description": norm,
            "label_id": label_ids[lbl_idx],
            "review_status": status,
            "categorized_by": "rule" if status == "auto_accepted" else ("manual" if status == "reviewed" else None),
        })
        if note:
            conn.execute(
                "UPDATE transactions SET note = ? WHERE description = ? AND date = ?",
                (note, desc, date),
            )
            conn.commit()

    # Other months (for yearly chart)
    for amount, date, acct_idx, lbl_idx in TRANSACTIONS_OTHER_MONTHS:
        insert_transaction(conn, {
            "id": str(uuid.uuid4()),
            "account_id": ACCOUNTS[acct_idx][0],
            "item_id": f"item-{uuid.uuid4().hex[:8]}",
            "amount": amount,
            "date": date,
            "description": f"MOCK TXN {uuid.uuid4().hex[:6].upper()}",
            "normalized_description": f"mock-{uuid.uuid4().hex[:6]}",
            "label_id": label_ids[lbl_idx],
            "review_status": "reviewed",
            "categorized_by": "rule",
        })

    return conn


# ---------------------------------------------------------------------------
# TUI screenshots (Textual SVG export)
# ---------------------------------------------------------------------------


async def screenshot_review(conn: sqlite3.Connection) -> None:
    from finmint.review_tui import ReviewApp

    app = ReviewApp(conn, month=3, year=2026, copilot_token="")
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        svg = app.export_screenshot(title="finmint — Review")
        (OUT / "review-tui.svg").write_text(svg)
        print(f"  ✓ review-tui.svg")


async def screenshot_labels(conn: sqlite3.Connection) -> None:
    from finmint.labels_tui import LabelsApp

    app = LabelsApp(conn)
    async with app.run_test(size=(100, 28)) as pilot:
        await pilot.pause()
        svg = app.export_screenshot(title="finmint — Labels")
        (OUT / "labels-tui.svg").write_text(svg)
        print(f"  ✓ labels-tui.svg")


async def screenshot_accounts(conn: sqlite3.Connection) -> None:
    from finmint.accounts_tui import AccountsApp

    app = AccountsApp(conn)
    async with app.run_test(size=(90, 16)) as pilot:
        await pilot.pause()
        svg = app.export_screenshot(title="finmint — Accounts")
        (OUT / "accounts-tui.svg").write_text(svg)
        print(f"  ✓ accounts-tui.svg")


async def screenshot_rules(conn: sqlite3.Connection) -> None:
    from finmint.rules_tui import RulesApp

    app = RulesApp(conn)
    async with app.run_test(size=(100, 28)) as pilot:
        await pilot.pause()
        svg = app.export_screenshot(title="finmint — Rules")
        (OUT / "rules-tui.svg").write_text(svg)
        print(f"  ✓ rules-tui.svg")


# ---------------------------------------------------------------------------
# Chart screenshots (matplotlib PNG)
# ---------------------------------------------------------------------------


def screenshot_monthly_chart(conn: sqlite3.Connection) -> None:
    from finmint.charts import render_monthly_pie
    import shutil

    path = render_monthly_pie(conn, 3, 2026)
    if path:
        dest = OUT / "monthly-view.png"
        shutil.move(path, dest)
        print(f"  ✓ monthly-view.png")
    else:
        print(f"  ✗ monthly-view.png (no data)")


def screenshot_yearly_chart(conn: sqlite3.Connection) -> None:
    from finmint.charts import render_yearly_bars
    import shutil

    path = render_yearly_bars(conn, 2026)
    if path:
        dest = OUT / "yearly-view.png"
        shutil.move(path, dest)
        print(f"  ✓ yearly-view.png")
    else:
        print(f"  ✗ yearly-view.png (no data)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Building demo database...")
    conn = build_demo_db()

    print("Generating TUI screenshots...")
    await screenshot_review(conn)
    await screenshot_labels(conn)
    await screenshot_accounts(conn)
    await screenshot_rules(conn)

    print("Generating chart screenshots...")
    screenshot_monthly_chart(conn)
    screenshot_yearly_chart(conn)

    conn.close()
    print(f"\nDone! Screenshots saved to {OUT}/")


if __name__ == "__main__":
    asyncio.run(main())
