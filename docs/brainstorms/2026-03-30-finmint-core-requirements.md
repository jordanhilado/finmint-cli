---
date: 2026-03-30
topic: finmint-core
---

# Finmint CLI — Core Requirements

## Problem Frame

Personal finance tracking is either too complex (spreadsheets, beancount) or too opaque (bank apps, Mint). Jordan wants a fast, terminal-native tool that pulls real bank data via Teller API, uses AI to auto-categorize transactions, and lets him review and analyze spending monthly — all from the CLI. The tool is open-source from day 0, local-first, and designed for a single user who runs it on-demand.

## Requirements

**CLI Commands & Routing**

- R1. `finmint <M-YYYY>` opens the transaction review UI for the given month (e.g., `finmint 3-2026` for March 2026). Fetches transactions from Teller if not already cached locally.
- R2. `finmint view <M-YYYY>` shows a pie chart of categorized spending, a narrative AI summary, and a count of unreviewed transactions for the given month.
- R3. `finmint view <YYYY>` shows a monthly stacked/grouped bar chart of spending across all months of the year, plus a narrative AI summary of the year so far.
- R4. `finmint labels` opens a TUI for managing category labels: list, add, edit, delete.
- R5. `finmint accounts` opens a TUI for managing Teller-connected bank accounts: list, add (enroll), edit, delete.
- R6. `finmint rules` opens a TUI showing all merchant-to-label rules in a table. Supports adding new rules, editing existing ones, and deleting rules.

**Transaction Review (R1 detail)**

- R7. Default view is an interactive Rich table showing all transactions for the month: date, merchant, amount, category, and review status (auto-accepted, needs review, reviewed, exempt).
- R8. User can navigate with arrow keys, press Enter on a transaction to edit its category inline, press `a` to accept the current category, and use Space to multi-select for bulk accept.
- R9. An alternate one-by-one detail view is available (toggled from the table). Steps through each unreviewed transaction sequentially with accept/change/exempt/skip actions.
- R10. Table view is the default. User can switch between table and one-by-one modes within the same session.
- R11. Transactions can be marked as "exempt" — they remain visible in the table with a dimmed/strikethrough style but are excluded from pie charts, summaries, and spending totals.
- R12. When the user corrects a transaction's category, a merchant rule is automatically and silently created (merchant substring -> new category). No confirmation prompt.

**AI Categorization**

- R13. When transactions are fetched for a month, each transaction is categorized using a tiered approach: (1) check merchant rules table first, (2) fall back to Claude API for unknown merchants.
- R14. Each categorization carries a confidence indicator: "rule" (from merchant rules, highest confidence), or "ai" (from Claude API).
- R15. Transactions categorized by rules are auto-accepted and marked as reviewed. AI-categorized transactions are marked as "needs review" by default.
- R16. The AI categorizer receives the full list of available labels and the transaction details (merchant name, amount, date, account) to make its categorization decision.

**Merchant Rules Engine (R6 detail)**

- R17. Rules are stored in SQLite as merchant_pattern -> label mappings. Each rule has: pattern string, label, created_at, source (manual or auto-learned).
- R18. Rule matching uses case-insensitive substring contains: rule pattern "TRADER JOE" matches "TRADER JOE #123 LOS ANGELES CA".
- R19. If multiple rules match a single transaction, the longest (most specific) pattern wins.
- R20. The `finmint rules` TUI shows a table of all rules sorted alphabetically. Supports inline add, edit, and delete operations.
- R21. When a rule is deleted, transactions that were categorized by that rule are not retroactively changed — they keep their current category.

**Inter-Account Transfer Detection**

- R22. Automatically detect likely inter-account transfers: matching amounts (one debit, one credit) across different connected accounts within a 2-day window.
- R23. Detected transfers are auto-labeled with a special "Transfer" category and flagged for review like normal transactions.
- R24. Reviewed transfers are excluded from spending totals and pie charts.

**Label Management (R4 detail)**

- R25. Ship with 15 default labels: Groceries, Dining Out, Transport, Housing, Utilities, Subscriptions, Shopping, Health, Entertainment, Income, Travel, Education, Personal Care, Gifts, Fees & Interest.
- R26. Users can add custom labels, edit label names, and delete labels.
- R27. Deleting a label prompts the user to reassign all transactions currently using that label to a different label before deletion completes.
- R28. Editing a label name cascades to all transactions and merchant rules using that label.

**Account Management (R5 detail)**

- R29. Adding a new account opens the Teller Connect URL in the user's default browser. The CLI spins up a temporary local HTTP server to capture the enrollment callback token.
- R30. Accounts list shows: institution name, account type, last 4 digits, last sync date.
- R31. Deleting an account removes the Teller connection. Transactions already fetched from that account remain in the local database.

**Visualization & AI Summaries (R2, R3 detail)**

- R32. Monthly pie chart rendered via Matplotlib, displayed inline in the terminal (saved as image or rendered via terminal graphics protocol depending on terminal support).
- R33. Monthly AI summary is a narrative paragraph (3-4 sentences) generated by Claude API. Covers: top spending category, notable changes vs. trailing 3-month average, new merchants or anomalies, overall month-over-month delta.
- R34. Yearly bar chart shows monthly totals with category breakdown. AI summary covers year-to-date trends.
- R35. Both view commands show a count of unreviewed transactions if any remain for the period.

**Data Storage & Config**

- R36. All transaction data, rules, labels, and account metadata stored in SQLite at `~/.finmint/finmint.db`.
- R37. Configuration stored in YAML at `~/.finmint/config.yaml`: Teller cert paths, Claude API key reference (env var name), default settings.
- R38. First run creates `~/.finmint/` directory and initializes the database schema. Prompts for Teller cert path and Claude API key env var.

**Open Source & Security**

- R39. MIT license from day 0.
- R40. `.gitignore` excludes: `~/.finmint/`, `.env`, `*.pem`, `*.crt`, `*.key`, any file containing secrets.
- R41. Repository includes `config.example.yaml` with placeholder values. No real tokens, certs, or personal data ever committed.
- R42. Teller sandbox token and Claude API key are read from environment variables or the local config file, never hardcoded.
- R43. Test fixtures use synthetic/mock transaction data. CI runs without real bank connections.

## Success Criteria

- Running `finmint 3-2026` for a month with ~100 transactions takes under 30 seconds to fetch, categorize, and display the review table.
- After 3 months of use, >70% of transactions are auto-resolved by merchant rules without hitting the Claude API.
- The monthly review workflow (for remaining unreviewed transactions) completes in under 5 minutes.
- `finmint view` renders a readable pie chart and useful AI summary for any reviewed month.
- A new user can clone the repo, install dependencies, configure Teller certs, and run `finmint accounts` to enroll their first account within 15 minutes.

## Scope Boundaries

- **Not a budgeting app** — no budget targets, envelopes, or spending limits (ghost budgets from ideation are a potential future addition, not v1).
- **No web UI or mobile app** — terminal only.
- **No multi-user support** — single user, single machine.
- **No real-time sync or daemon** — on-demand invocation only.
- **No transaction splitting** — one category per transaction in v1.
- **No natural language queries** — structured commands only.
- **No export** — data stays in local SQLite (export is a reasonable v2 feature).

## Key Decisions

- **Interactive table as default review UX** with alternate one-by-one mode available: table gives full context and supports batch operations; one-by-one is available for focused review.
- **Silent auto-rule creation on correction**: every human correction compounds into the rules engine with zero friction. Reduces AI dependency over time.
- **Transfers auto-detected but still require review**: prevents silent miscategorization while reducing manual work.
- **Exempt = visible but excluded**: dimmed/strikethrough style keeps the audit trail while keeping analytics clean.
- **Substring matching for rules**: simple, predictable, handles the 80% case of bank merchant name variations.
- **Label deletion requires reassignment**: prevents orphaned transactions and data loss.
- **Broader default label set (15)**: covers most spending categories out of the box while remaining manageable.
- **Narrative AI summaries**: more actionable than bullet points; creates a "financial advisor note" feel.
- **Browser-based Teller enrollment with local callback**: smoothest UX for OAuth-style bank enrollment from CLI.

## Dependencies / Assumptions

- Teller API is available and the user can obtain mTLS certificates through Teller's enrollment process.
- Claude API is accessible via API key for transaction categorization and summary generation.
- User's terminal supports Rich output (colors, tables, Unicode). Matplotlib charts are saved as images or rendered via a terminal graphics protocol (iTerm2, Kitty, etc.).
- Python 3.11+ is installed on the user's machine.

## Outstanding Questions

### Deferred to Planning

- [Affects R13][Needs research] What's the optimal Claude API prompt structure for batch-categorizing transactions? Single call with all transactions vs. one call per transaction vs. batches of N?
- [Affects R18][Technical] How should merchant name normalization work before substring matching? (Strip trailing numbers, whitespace normalization, etc.)
- [Affects R32][Needs research] Which terminal graphics protocol should be prioritized for inline chart rendering? iTerm2's inline images, Kitty protocol, or fallback to opening the image in the default viewer?
- [Affects R29][Needs research] What does Teller's enrollment callback look like exactly? What data does the local server need to capture?
- [Affects R38][Technical] What should the SQLite schema look like? (Tables, indexes, relationships)
- [Affects R7, R9][Needs research] Which Python TUI library is best for the interactive table? Rich alone, Textual (by the Rich author), or prompt_toolkit?

## Next Steps

-> `/ce:plan` for structured implementation planning
