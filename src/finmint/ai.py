"""AI categorization and summary generation via Claude API."""

import json
import sqlite3
from datetime import datetime, timezone

import anthropic

from finmint.config import resolve_api_key
from finmint.db import get_labels, get_label_by_name, update_transaction_label

MODEL = "claude-sonnet-4-20250514"
BATCH_SIZE = 100
MAX_UNSPLIT = 200


def _build_label_list(conn: sqlite3.Connection) -> list[str]:
    """Return list of label names from the database."""
    return [row["name"] for row in get_labels(conn)]


def _build_categorization_prompt(
    label_names: list[str],
    items: list[dict],
) -> tuple[str, str]:
    """Build system and user prompts for batch categorization.

    Returns (system_prompt, user_prompt).
    """
    system_prompt = (
        "You are a personal finance categorization assistant. "
        "Given a list of bank transactions, assign each one to exactly one "
        "category from the provided list.\n\n"
        "Available categories:\n"
        + "\n".join(f"- {name}" for name in label_names)
        + "\n\n"
        "Respond with ONLY a JSON object mapping the sequence number (as a string key) "
        "to the category name. Example: {\"1\": \"Groceries\", \"2\": \"Dining Out\"}\n"
        "Do not include any other text."
    )

    lines = []
    for item in items:
        lines.append(
            f"  {item['seq']}: {item['description']} | "
            f"${item['amount_dollars']:.2f} | {item['date']}"
        )
    user_prompt = "Categorize these transactions:\n" + "\n".join(lines)

    return system_prompt, user_prompt


def categorize_transactions(
    config: dict,
    conn: sqlite3.Connection,
    transactions: list[sqlite3.Row],
) -> int:
    """Send uncategorized transactions to Claude for batch categorization.

    Only transactions without a label_id (uncategorized) are sent.
    Data minimization: only merchant description, amount, and date are sent,
    keyed by local sequence numbers (not transaction IDs).

    Returns the count of successfully categorized transactions.
    """
    # Filter to uncategorized only
    uncategorized = [t for t in transactions if t["label_id"] is None]
    if not uncategorized:
        return 0

    api_key = resolve_api_key(config)
    client = anthropic.Anthropic(api_key=api_key)
    label_names = _build_label_list(conn)

    # Build mapping from sequence number to transaction
    seq_to_txn: dict[int, sqlite3.Row] = {}
    items: list[dict] = []
    for i, txn in enumerate(uncategorized, start=1):
        seq_to_txn[i] = txn
        amount_dollars = abs(txn["amount"]) / 100.0
        items.append({
            "seq": i,
            "description": txn["description"] or txn["normalized_description"] or "Unknown",
            "amount_dollars": amount_dollars,
            "date": txn["date"],
        })

    # Split into batches if > MAX_UNSPLIT
    if len(items) > MAX_UNSPLIT:
        batches = [
            items[i : i + BATCH_SIZE]
            for i in range(0, len(items), BATCH_SIZE)
        ]
    else:
        batches = [items]

    total_categorized = 0

    for batch in batches:
        system_prompt, user_prompt = _build_categorization_prompt(
            label_names, batch
        )

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text
        try:
            mapping = json.loads(raw_text)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Claude returned invalid JSON for categorization: {raw_text[:200]}"
            )

        for seq_str, label_name in mapping.items():
            seq = int(seq_str)
            txn = seq_to_txn.get(seq)
            if txn is None:
                continue

            label_row = get_label_by_name(conn, label_name)
            if label_row is None:
                # Unknown label name from Claude — skip this transaction
                continue

            update_transaction_label(
                conn,
                txn["id"],
                label_row["id"],
                categorized_by="ai",
                status="needs_review",
            )
            total_categorized += 1

    return total_categorized


def _get_category_totals(
    conn: sqlite3.Connection,
    month: int,
    year: int,
) -> list[tuple[str, int]]:
    """Return (label_name, total_cents) for categorized transactions in a month."""
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    cur = conn.execute(
        "SELECT l.name, SUM(ABS(t.amount)) AS total_cents "
        "FROM transactions t "
        "JOIN labels l ON t.label_id = l.id "
        "WHERE t.date >= ? AND t.date < ? AND t.label_id IS NOT NULL "
        "GROUP BY l.name "
        "ORDER BY total_cents DESC",
        (start, end),
    )
    return [(row["name"], row["total_cents"]) for row in cur.fetchall()]


def _get_trailing_averages(
    conn: sqlite3.Connection,
    month: int,
    year: int,
    trailing_months: int = 3,
) -> dict[str, float] | None:
    """Return average spending per category over trailing N months.

    Returns None if fewer than trailing_months of data exist.
    """
    # Build list of (year, month) for trailing period
    periods = []
    m, y = month, year
    for _ in range(trailing_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        periods.append((y, m))

    # Check each period has data
    months_with_data = 0
    totals_by_category: dict[str, int] = {}

    for py, pm in periods:
        start = f"{py:04d}-{pm:02d}-01"
        if pm == 12:
            end = f"{py + 1:04d}-01-01"
        else:
            end = f"{py:04d}-{pm + 1:02d}-01"

        cur = conn.execute(
            "SELECT COUNT(*) AS cnt FROM transactions "
            "WHERE date >= ? AND date < ? AND label_id IS NOT NULL",
            (start, end),
        )
        if cur.fetchone()["cnt"] > 0:
            months_with_data += 1

        cur = conn.execute(
            "SELECT l.name, SUM(ABS(t.amount)) AS total_cents "
            "FROM transactions t "
            "JOIN labels l ON t.label_id = l.id "
            "WHERE t.date >= ? AND t.date < ? AND t.label_id IS NOT NULL "
            "GROUP BY l.name",
            (start, end),
        )
        for row in cur.fetchall():
            totals_by_category[row["name"]] = (
                totals_by_category.get(row["name"], 0) + row["total_cents"]
            )

    if months_with_data < trailing_months:
        return None

    return {
        cat: total / trailing_months
        for cat, total in totals_by_category.items()
    }


def _cache_summary(
    conn: sqlite3.Connection,
    period_type: str,
    period_key: str,
    summary_text: str,
    txn_count: int,
    txn_total_cents: int,
) -> None:
    """Insert or replace a cached AI summary."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO ai_summaries "
        "(period_type, period_key, summary_text, txn_count, txn_total_cents, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (period_type, period_key, summary_text, txn_count, txn_total_cents, now),
    )
    conn.commit()


def _get_cached_summary(
    conn: sqlite3.Connection,
    period_type: str,
    period_key: str,
) -> str | None:
    """Return cached summary text, or None if not cached."""
    cur = conn.execute(
        "SELECT summary_text FROM ai_summaries "
        "WHERE period_type = ? AND period_key = ?",
        (period_type, period_key),
    )
    row = cur.fetchone()
    return row["summary_text"] if row else None


def generate_monthly_summary(
    config: dict,
    conn: sqlite3.Connection,
    month: int,
    year: int,
) -> str:
    """Generate a narrative monthly spending summary via Claude.

    Includes category totals for the month and trailing 3-month averages
    (if available) for comparison. Caches the result in ai_summaries table.
    """
    period_key = f"{year:04d}-{month:02d}"

    category_totals = _get_category_totals(conn, month, year)
    if not category_totals:
        return "No categorized transactions for this month."

    trailing_avgs = _get_trailing_averages(conn, month, year)

    # Build the prompt
    system_prompt = (
        "You are a personal finance analyst. Generate a concise narrative "
        "paragraph summarizing the user's monthly spending. Be specific about "
        "amounts and trends. Keep it to one paragraph."
    )

    lines = [f"Monthly spending for {period_key}:"]
    total_cents = 0
    txn_count_result = conn.execute(
        "SELECT COUNT(*) AS cnt FROM transactions "
        "WHERE date >= ? AND date < ? AND label_id IS NOT NULL",
        (
            f"{year:04d}-{month:02d}-01",
            f"{year:04d}-{month + 1:02d}-01" if month < 12
            else f"{year + 1:04d}-01-01",
        ),
    ).fetchone()
    txn_count = txn_count_result["cnt"]

    for name, cents in category_totals:
        total_cents += cents
        line = f"  {name}: ${cents / 100:.2f}"
        if trailing_avgs and name in trailing_avgs:
            avg = trailing_avgs[name]
            delta = cents - avg
            direction = "up" if delta > 0 else "down"
            line += f" (3-month avg: ${avg / 100:.2f}, {direction} ${abs(delta) / 100:.2f})"
        lines.append(line)

    lines.append(f"  Total: ${total_cents / 100:.2f}")
    if trailing_avgs is None:
        lines.append("(Less than 3 months of history; no trailing comparison available.)")

    user_prompt = "\n".join(lines)

    api_key = resolve_api_key(config)
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    summary = response.content[0].text

    _cache_summary(conn, "monthly", period_key, summary, txn_count, total_cents)

    return summary


def generate_yearly_summary(
    config: dict,
    conn: sqlite3.Connection,
    year: int,
) -> str:
    """Generate a narrative year-to-date spending summary via Claude.

    Aggregates spending by category across all months in the year.
    Caches the result in ai_summaries table.
    """
    period_key = f"{year:04d}"

    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"

    cur = conn.execute(
        "SELECT l.name, SUM(ABS(t.amount)) AS total_cents "
        "FROM transactions t "
        "JOIN labels l ON t.label_id = l.id "
        "WHERE t.date >= ? AND t.date < ? AND t.label_id IS NOT NULL "
        "GROUP BY l.name "
        "ORDER BY total_cents DESC",
        (start, end),
    )
    category_totals = [(row["name"], row["total_cents"]) for row in cur.fetchall()]

    if not category_totals:
        return "No categorized transactions for this year."

    txn_count_result = conn.execute(
        "SELECT COUNT(*) AS cnt FROM transactions "
        "WHERE date >= ? AND date < ? AND label_id IS NOT NULL",
        (start, end),
    ).fetchone()
    txn_count = txn_count_result["cnt"]

    # Monthly breakdown for trends
    cur = conn.execute(
        "SELECT strftime('%Y-%m', t.date) AS month, "
        "SUM(ABS(t.amount)) AS total_cents "
        "FROM transactions t "
        "WHERE t.date >= ? AND t.date < ? AND t.label_id IS NOT NULL "
        "GROUP BY month ORDER BY month",
        (start, end),
    )
    monthly_totals = [(row["month"], row["total_cents"]) for row in cur.fetchall()]

    system_prompt = (
        "You are a personal finance analyst. Generate a concise narrative "
        "paragraph summarizing the user's year-to-date spending trends. "
        "Be specific about amounts and trends. Keep it to one paragraph."
    )

    lines = [f"Year-to-date spending for {year}:"]
    total_cents = 0
    for name, cents in category_totals:
        total_cents += cents
        lines.append(f"  {name}: ${cents / 100:.2f}")
    lines.append(f"  Total: ${total_cents / 100:.2f}")

    if monthly_totals:
        lines.append("\nMonthly totals:")
        for month_str, cents in monthly_totals:
            lines.append(f"  {month_str}: ${cents / 100:.2f}")

    user_prompt = "\n".join(lines)

    api_key = resolve_api_key(config)
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    summary = response.content[0].text

    _cache_summary(conn, "yearly", period_key, summary, txn_count, total_cents)

    return summary
