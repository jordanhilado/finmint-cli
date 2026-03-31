---
title: "feat: Build Finmint CLI — Terminal-Based Personal Finance Tool"
type: feat
status: active
date: 2026-03-30
origin: docs/brainstorms/2026-03-30-finmint-core-requirements.md
deepened: 2026-03-30
---

# feat: Build Finmint CLI — Terminal-Based Personal Finance Tool

## Overview

Build a complete terminal-based personal finance CLI tool from scratch. Finmint pulls bank transactions via Teller API (mTLS), auto-categorizes them using a tiered system (local merchant rules first, Claude API fallback), and provides an interactive TUI for reviewing, categorizing, and analyzing monthly spending. Open-source (MIT) from day 0.

## Problem Frame

Personal finance tracking is either too complex (spreadsheets, beancount) or too opaque (bank apps). Finmint fills the gap: a fast, local-first CLI tool that pulls real bank data, uses AI for initial categorization, learns from corrections via merchant rules, and provides pie charts and narrative summaries — all from the terminal. (see origin: docs/brainstorms/2026-03-30-finmint-core-requirements.md)

## Requirements Trace

- R1-R6. CLI command routing (`finmint <M-YYYY>`, `view`, `labels`, `accounts`, `rules`)
- R7-R12. Interactive transaction review (table + one-by-one modes, exempt, auto-rule on correction)
- R13-R16. Tiered AI categorization (rules first, Claude fallback)
- R17-R21. Merchant rules engine (substring match, longest wins, CRUD TUI)
- R22-R24. Inter-account transfer detection
- R25-R28. Label management (15 user-facing defaults + Transfer system label, cascading edits, reassign on delete)
- R29-R31. Account management (Teller enrollment via browser, CRUD)
- R32-R35. Visualization (pie chart, bar chart, AI narrative summaries)
- R36-R38. Data storage (SQLite) and config (YAML)
- R39-R43. Open source (MIT, .gitignore, example configs, synthetic test data)

## Scope Boundaries

- Not a budgeting app — no budget targets, envelopes, or spending limits
- No web UI or mobile app — terminal only
- No multi-user support — single user, single machine
- No real-time sync or daemon — on-demand invocation only
- No transaction splitting — one category per transaction
- No natural language queries — structured commands only
- No export — data stays in local SQLite

(see origin: docs/brainstorms/2026-03-30-finmint-core-requirements.md)

## Context & Research

### Relevant Code and Patterns

- **Greenfield project** — no existing code. Package structure will follow `src/finmint/` layout with flat modules and functions (classes only for Textual TUI apps).
- **Typer + Textual** is the canonical CLI + TUI stack from the same author (Will McGugan). Typer handles command routing; Textual apps launch for interactive screens.
- **Textual DataTable** provides built-in arrow key navigation, row/cell selection, and virtual rendering (handles thousands of rows). Inline editing requires a small custom subclass (~50 lines) overlaying an `Input` widget on `CellSelected`.
- **httpx** supports mTLS natively via `cert=("/path/to/cert.pem", "/path/to/key.pem")`. Teller uses HTTP Basic Auth (access token as username, empty password).
- **Teller API**: transactions at `GET /accounts/:id/transactions` with cursor pagination (`from_id`, `count`). Enrollment via browser-based Teller Connect JS widget that returns an `accessToken`.
- **SQLite** stdlib module — no ORM needed. Store amounts as INTEGER cents to avoid floating point issues.

### External References

- Teller API docs: https://teller.io/docs/api — transactions, accounts, enrollment
- Textual DataTable: https://textual.textualize.io/widgets/data_table/
- Anthropic Python SDK: https://docs.anthropic.com/en/docs/sdks

## Key Technical Decisions

- **Textual for all interactive TUIs** (review, labels, accounts, rules): Textual's DataTable covers navigation, selection, and styled rendering. Rich alone cannot provide interactivity. prompt_toolkit would require building table rendering from scratch. Textual + Typer are designed to compose.
- **Single batch Claude API call per sync**: Send all uncategorized transactions in one prompt with the full label list. ~100 transactions fit well within context. Reduces API calls from ~100 to 1 per monthly sync. If >200 transactions, batch into groups of 100.
- **Merchant name normalization**: Before substring matching, normalize by: uppercase, collapse whitespace, strip trailing `#` followed by digits (e.g., `TRADER JOE #123` → `TRADER JOE`). Store normalized patterns in rules table. Match against normalized transaction descriptions.
- **Chart rendering via temp file + open**: Save Matplotlib charts to a temp PNG file and open with the system viewer (`open` on macOS). This works universally. iTerm2/Kitty inline rendering is a future nice-to-have, not v1.
- **Teller enrollment via local HTML page with JS widget**: CLI spins up a Flask-less `http.server` on a random port bound to `127.0.0.1` only. It serves a local HTML page that embeds the Teller Connect JS widget (`https://cdn.teller.io/connect/connect.js`). The widget's `onSuccess` callback sends the `accessToken` to the local server via a POST request. A CSRF state parameter (cryptographic random nonce) is generated by the CLI, embedded in the HTML page, and validated on the POST to prevent token injection by other local processes. The server stores the token, signals the main thread, and shuts down.
- **Amounts stored as INTEGER cents**: Avoids floating point issues. `$67.42` stored as `6742`. All display logic divides by 100. Pandas operations use cents natively.
- **"Transfer" as a 16th default label, protected from deletion**: Transfer detection needs a "Transfer" label. Seed it alongside the 15 user-facing defaults. Mark it (and "Income") as `is_protected` in the labels table so `finmint labels` prevents deletion/rename of system labels.
- **Re-sync semantics**: If the requested month is the current calendar month, always re-fetch from Teller (month is incomplete). For past months, skip Teller fetch if any transactions exist for that month unless `--force-sync` is passed. `INSERT OR IGNORE` ensures re-syncing is safe.
- **Auto-rule uses full normalized_description**: When a user corrects a category, the rule is created from the full `normalized_description` of that transaction. This is intentionally specific — it may not generalize to all variations of a merchant. Over time, the user can broaden rules via `finmint rules`. This is a v1 simplicity choice.
- **Teller token expiry recovery**: On 401/403 from Teller, skip that account, sync remaining accounts, and print a warning: "Account [name] failed to sync — token may be expired. Run `finmint accounts` to re-enroll." Do not abort the entire sync.
- **Transfer detection filters by teller_type**: Exclude `card_payment` transactions from transfer pair matching to reduce false positives (coincidental same-amount purchases).
- **Summary cache invalidation**: Store transaction count + total amount for the period alongside each cached AI summary. Regenerate if either value changes.
- **`finmint view` without prior sync**: If no local data exists for the period, print: "No transactions found for [period]. Run `finmint <M-YYYY>` to sync and review." Do not auto-trigger a sync.
- **Cross-platform chart opening**: Use `sys.platform` to select: `open` (macOS), `xdg-open` (Linux), `start` (Windows). Fallback to printing the file path if none work.

## Open Questions

### Resolved During Planning

- **TUI library choice** (R7, R9): Textual — DataTable with custom EditableDataTable subclass for inline editing. One-by-one mode implemented as a separate Textual screen or widget within the same app.
- **Claude API prompt structure** (R13): Single batch call with all unknown merchants per sync. Include the full label list and transaction details (merchant, amount, date) in structured format. Ask for JSON response mapping transaction IDs to labels.
- **Merchant normalization** (R18): Uppercase + collapse whitespace + strip trailing `#\d+`. Applied before both rule storage and matching.
- **Chart rendering** (R32): Matplotlib → temp PNG → system `open` command. Universal and simple.
- **Teller enrollment callback** (R29): Local HTML page served by the CLI embeds the Teller Connect JS widget. On successful enrollment, the widget's `onSuccess` callback posts the `accessToken` back to the local server. Token stored as plaintext in SQLite, protected by filesystem permissions (directory mode 0700, files mode 0600). Encryption-at-rest deferred to v2 — filesystem permissions are right-sized for a single-user local tool.
- **SQLite schema** (R38): See High-Level Technical Design below.

### Deferred to Implementation

- Exact Textual CSS styling for dimmed/strikethrough exempt transactions — will depend on Textual's current TCSS capabilities
- Claude API response format validation — may need retry logic if JSON is malformed
- Matplotlib chart sizing and color palette — iterate visually during implementation

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### SQLite Schema

```
tables:
  accounts
    id TEXT PRIMARY KEY        -- Teller account ID
    enrollment_id TEXT
    institution_name TEXT
    account_type TEXT          -- "checking", "savings", "credit_card"
    account_subtype TEXT
    last_four TEXT
    access_token TEXT          -- Teller access token for this enrollment
    last_synced_at TEXT        -- ISO 8601 timestamp
    created_at TEXT

  labels
    id INTEGER PRIMARY KEY AUTOINCREMENT
    name TEXT UNIQUE NOT NULL
    is_default BOOLEAN DEFAULT 0
    is_protected BOOLEAN DEFAULT 0  -- Transfer, Income: cannot be deleted/renamed
    created_at TEXT

  transactions
    id TEXT PRIMARY KEY        -- Teller transaction ID
    account_id TEXT REFERENCES accounts(id)
    amount INTEGER NOT NULL    -- cents (negative = debit)
    date TEXT NOT NULL         -- ISO 8601 date
    description TEXT           -- raw merchant string from bank
    normalized_description TEXT -- uppercase, stripped, for matching
    label_id INTEGER REFERENCES labels(id)
    review_status TEXT DEFAULT 'needs_review'
        -- 'needs_review', 'reviewed', 'auto_accepted', 'exempt'
    categorized_by TEXT        -- 'rule', 'ai', 'manual'
    transfer_pair_id TEXT      -- links two transfer transactions
    teller_type TEXT           -- 'card_payment', 'transfer', etc.
    teller_category TEXT       -- Teller's own category hint
    created_at TEXT

  merchant_rules
    id INTEGER PRIMARY KEY AUTOINCREMENT
    pattern TEXT NOT NULL      -- normalized substring pattern
    label_id INTEGER REFERENCES labels(id) NOT NULL
    source TEXT DEFAULT 'manual'  -- 'manual' or 'auto_learned'
    created_at TEXT

  ai_summaries
    id INTEGER PRIMARY KEY AUTOINCREMENT
    period_type TEXT NOT NULL  -- 'month' or 'year'
    period_key TEXT NOT NULL   -- '3-2026' or '2026'
    summary_text TEXT NOT NULL
    txn_count INTEGER NOT NULL     -- cached count for staleness check
    txn_total_cents INTEGER NOT NULL -- cached total for staleness check
    generated_at TEXT
    UNIQUE(period_type, period_key)

indexes:
  transactions(account_id, date)
  transactions(date)
  transactions(review_status)
  transactions(transfer_pair_id)
  merchant_rules(pattern)
```

### Data Flow: Monthly Sync + Categorize

```
finmint 3-2026
  │
  ├─ 1. Check local DB for March 2026 transactions
  │     └─ If empty or stale → fetch from Teller API
  │
  ├─ 2. Fetch from Teller (per connected account)
  │     ├─ GET /accounts/:id/transactions?start_date=2026-03-01&end_date=2026-03-31
  │     ├─ Paginate via from_id cursor
  │     └─ Upsert into transactions table (skip duplicates by Teller ID)
  │
  ├─ 3. Detect transfers
  │     ├─ Pre-filter: exclude card_payment teller_type
  │     ├─ Find matching (amount, -amount) pairs across accounts within 2-day window
  │     ├─ Prefer pairs with teller_type=transfer/ach
  │     └─ Set label to "Transfer", link via transfer_pair_id, status=needs_review
  │
  ├─ 4. Apply merchant rules (for non-transfer transactions)
  │     ├─ Normalize each transaction description
  │     ├─ Check all rules via substring match
  │     ├─ Longest match wins → set label, categorized_by='rule', status='auto_accepted'
  │     └─ No match → add to uncategorized batch
  │
  ├─ 5. Batch Claude API call (for remaining uncategorized)
  │     ├─ Send all uncategorized transactions + label list in one prompt
  │     ├─ Parse JSON response: { transaction_id: label_name }
  │     └─ Set label, categorized_by='ai', status='needs_review'
  │
  └─ 6. Launch Textual review TUI
        ├─ DataTable with all transactions
        ├─ Keyboard: ↑↓ navigate, Enter edit category, a accept, Space select, B bulk accept
        ├─ On category correction → auto-create merchant rule silently
        └─ e to exempt (dimmed style, excluded from analytics)
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│  CLI Layer (cli.py — Typer)                             │
│  Commands: review, view, labels, accounts, rules        │
└───────────┬─────────────────────────────────────────────┘
            │
   ┌────────┴────────┐
   │                 │
   ▼                 ▼
┌──────────┐  ┌──────────────────────────────────────────┐
│ TUI Apps │  │  Business Logic (functions, no classes)   │
│ Textual  │  │                                          │
│          │  │  teller.py    — fetch, enroll, sync       │
│ review   │  │  categorize.py — rules check + AI batch  │
│ labels   │  │  rules.py     — CRUD, substring match    │
│ accounts │  │  transfers.py — detect linked pairs      │
│ rules    │  │  ai.py        — Claude API wrapper       │
│          │  │  charts.py    — Matplotlib rendering      │
└──────┬───┘  └───────────────┬──────────────────────────┘
       │                      │
       └──────────┬───────────┘
                  │
                  ▼
       ┌─────────────────────┐
       │  Data Layer          │
       │  db.py  — SQLite     │
       │  config.py — YAML    │
       │  models.py — dicts   │
       └─────────────────────┘
```

## Implementation Units

### Phase 1: Foundation

- [ ] **Unit 1: Project Skeleton & Packaging**

  **Goal:** Initialize the repository with all scaffolding needed to install and run a `finmint` CLI command that prints a version string.

  **Requirements:** R39, R40, R41, R42

  **Dependencies:** None

  **Files:**
  - Create: `pyproject.toml`
  - Create: `src/finmint/__init__.py`
  - Create: `src/finmint/cli.py`
  - Create: `LICENSE`
  - Create: `.gitignore`
  - Create: `config.example.yaml`
  - Create: `README.md`
  - Create: `tests/__init__.py`
  - Create: `tests/conftest.py`

  **Approach:**
  - `pyproject.toml` with PEP 621 metadata, hatchling build backend, `[project.scripts] finmint = "finmint.cli:app"`
  - `src/finmint/` layout to prevent accidental imports
  - `cli.py` creates a Typer app with a `--version` callback and stub subcommands for `view`, `labels`, `accounts`, `rules`
  - `.gitignore` covers: `__pycache__/`, `.venv/`, `*.pem`, `*.crt`, `*.key`, `.env`, `dist/`, `*.egg-info/`
  - MIT license with current year
  - `conftest.py` sets up an in-memory SQLite fixture

  **Patterns to follow:**
  - Standard `src/` layout per Python packaging guide
  - Typer app pattern: `app = typer.Typer()` with `@app.command()` decorators

  **Test scenarios:**
  - Happy path: `finmint --version` prints version string
  - Happy path: `finmint --help` lists available commands
  - Happy path: `pip install -e .` succeeds and `finmint` is available on PATH
  - Happy path: `finmint 3-2026` routes to the review flow (default command with positional arg)
  - Happy path: `finmint view 3-2026` routes to the view subcommand (not confused with default)
  - **Spike: Typer routing** — validate that a Typer app can have both a default callback with a positional argument AND named subcommands. If Typer cannot do this cleanly, fallback to `finmint review 3-2026` as an explicit subcommand. This must be resolved in Unit 1 before downstream units depend on it.

  **Verification:**
  - `finmint --version` prints `finmint 0.1.0`
  - `finmint --help` shows subcommands
  - All test files pass with `pytest`

- [ ] **Unit 2: Configuration & First-Run Setup**

  **Goal:** Implement config loading from `~/.finmint/config.yaml` with first-run initialization that creates the directory and prompts for required settings.

  **Requirements:** R37, R38, R42

  **Dependencies:** Unit 1

  **Files:**
  - Create: `src/finmint/config.py`
  - Create: `tests/test_config.py`

  **Approach:**
  - `load_config()` reads `~/.finmint/config.yaml` via PyYAML. Returns a dict.
  - `init_config()` creates `~/.finmint/` directory with mode 0700 (owner-only access), prompts for Teller cert path and Claude API key env var name, writes config.yaml with mode 0600. Validates on startup that permissions are not too open (warn if world-readable, similar to SSH key checks).
  - API keys read from environment variables (name configured in YAML), never stored directly in config
  - Teller cert paths stored in config (paths to existing PEM files, not the certs themselves)

  **Patterns to follow:**
  - Simple function-based module, no Config class
  - `pathlib.Path` for all file operations

  **Test scenarios:**
  - Happy path: load_config reads a valid YAML file and returns expected dict
  - Happy path: init_config creates directory and writes config file
  - Edge case: load_config with missing file raises clear error with setup instructions
  - Edge case: config file exists but missing required keys raises validation error
  - Happy path: API key resolution from environment variable works
  - Error path: missing environment variable for API key raises clear error
  - Happy path: init_config creates directory with mode 0700 and config file with mode 0600
  - Edge case: startup warns if ~/.finmint/ directory is world-readable

  **Verification:**
  - Config loads from a test YAML file with correct values
  - First-run creates `~/.finmint/` and `config.yaml` with restrictive permissions

- [ ] **Unit 3: Database Schema & Access Layer**

  **Goal:** Implement SQLite database initialization, schema creation, and basic CRUD helpers for all tables.

  **Requirements:** R36, R25

  **Dependencies:** Unit 2

  **Files:**
  - Create: `src/finmint/db.py`
  - Create: `src/finmint/models.py`
  - Create: `tests/test_db.py`

  **Approach:**
  - `init_db(path)` creates all tables and indexes per the schema in High-Level Technical Design. Uses `IF NOT EXISTS` for idempotency.
  - `get_connection(path)` returns a sqlite3 connection with `row_factory = sqlite3.Row` and WAL mode enabled
  - `seed_default_labels(conn)` inserts the 16 default labels (15 user-facing + Transfer) if they don't exist. Marks Transfer and Income as `is_protected=True`
  - `models.py` defines TypedDicts for Transaction, Account, Label, MerchantRule (no classes)
  - Amounts stored as INTEGER cents throughout
  - CRUD helpers are thin functions: `insert_transaction(conn, data)`, `get_transactions(conn, month, year)`, `update_transaction_label(conn, txn_id, label_id, categorized_by, status)`, etc.

  **Patterns to follow:**
  - sqlite3 stdlib module, no ORM
  - Context manager for transactions: `with conn:` for auto-commit
  - TypedDict for type hints without class overhead

  **Test scenarios:**
  - Happy path: init_db creates all tables and indexes
  - Happy path: init_db is idempotent (running twice doesn't error)
  - Happy path: seed_default_labels inserts exactly 16 labels (15 + Transfer)
  - Happy path: seed_default_labels marks Transfer and Income as protected
  - Happy path: seed_default_labels is idempotent
  - Happy path: insert and retrieve a transaction with correct cent values
  - Happy path: get_transactions filters by month/year correctly
  - Edge case: get_transactions for empty month returns empty list
  - Happy path: update_transaction_label changes label and categorized_by
  - Integration: full round-trip — insert transaction, update label, query back with new label

  **Verification:**
  - All tables exist with correct columns after init_db
  - 16 default labels present after seeding (including protected Transfer and Income)
  - Transaction CRUD works with in-memory SQLite

### Phase 2: Accounts & Sync

- [ ] **Unit 4: Teller API Client**

  **Goal:** Implement the httpx-based Teller API client with mTLS support for fetching accounts and transactions.

  **Requirements:** R29, R30, R31

  **Dependencies:** Unit 2, Unit 3

  **Files:**
  - Create: `src/finmint/teller.py`
  - Create: `tests/test_teller.py`

  **Approach:**
  - `create_client(config)` returns an httpx.Client with `cert=(cert_path, key_path)` and Basic Auth `(access_token, "")`
  - `fetch_accounts(client)` calls `GET /accounts`, returns list of account dicts
  - `fetch_transactions(client, account_id, start_date, end_date)` paginates via `from_id` cursor, returns all transactions in date range
  - `delete_account(client, account_id)` calls `DELETE /accounts/:id`
  - All functions return plain dicts, converting amounts to integer cents
  - Use `respx` for mocking httpx in tests

  **Patterns to follow:**
  - httpx.Client with context manager
  - Cursor-based pagination: loop while results == count, pass last ID as `from_id`

  **Test scenarios:**
  - Happy path: fetch_accounts returns parsed account list from mock response
  - Happy path: fetch_transactions returns all transactions, correctly paginated across 2 pages
  - Happy path: fetch_transactions converts string amounts to integer cents
  - Edge case: fetch_transactions with no results returns empty list
  - Error path: Teller API returns 401 — raises clear auth error
  - Error path: Teller API returns 410 (closed account) — handled gracefully
  - Happy path: delete_account sends DELETE and handles 204 response

  **Verification:**
  - All Teller interactions work against mocked responses
  - Pagination correctly fetches all pages
  - Amount conversion is accurate (e.g., "-67.42" → -6742)

- [ ] **Unit 5: Teller Enrollment (Browser + Local Callback)**

  **Goal:** Implement the account enrollment flow that opens Teller Connect in the browser and captures the access token via a local HTTP callback server.

  **Requirements:** R29

  **Dependencies:** Unit 4

  **Files:**
  - Modify: `src/finmint/teller.py` (add enrollment functions)
  - Create: `src/finmint/enrollment.py` (local HTTP server for callback)
  - Modify: `tests/test_teller.py`

  **Approach:**
  - `start_enrollment(config)` picks a random available port, generates a cryptographic random state nonce, starts a background `http.server.HTTPServer` bound to `127.0.0.1` only, serves a local HTML page embedding the Teller Connect JS widget, and opens the page in the browser via `webbrowser.open()`
  - The HTML page loads `https://cdn.teller.io/connect/connect.js`, calls `TellerConnect.setup()` with the application ID and environment (sandbox/production from config), and in the `onSuccess` callback, POSTs the `accessToken` along with the state nonce back to the local server
  - POST handler validates the state nonce, stores the access token in the accounts table, and signals the main thread to shut down
  - After enrollment, immediately fetch accounts to populate the accounts table
  - Blocks until the POST is received or timeout (120s)

  **Patterns to follow:**
  - `http.server.HTTPServer` from stdlib (no Flask dependency), bound to `127.0.0.1`
  - `threading.Event` for signaling between POST handler and main thread
  - `webbrowser.open()` for cross-platform browser launch
  - `secrets.token_urlsafe()` for CSRF state nonce generation

  **Test scenarios:**
  - Happy path: enrollment server starts on a random port and serves the HTML page with Teller Connect widget
  - Happy path: POST handler correctly parses access token and validates state nonce
  - Error path: POST with invalid or missing state nonce is rejected (CSRF protection)
  - Error path: enrollment timeout (120s) with no callback raises clear error
  - Edge case: port already in use — retries on a different port
  - Happy path: server bound to 127.0.0.1 only, not externally accessible

  **Verification:**
  - Enrollment flow can be tested manually against Teller sandbox (username: `username`, password: `password`)
  - Access token is stored in the accounts table after successful enrollment

- [ ] **Unit 6: Transaction Sync & Storage**

  **Goal:** Implement the sync logic that fetches transactions from Teller for a given month and upserts them into SQLite with normalized descriptions.

  **Requirements:** R1, R13 (partial)

  **Dependencies:** Unit 4, Unit 3

  **Files:**
  - Create: `src/finmint/sync.py`
  - Create: `tests/test_sync.py`

  **Approach:**
  - `sync_month(conn, config, month, year, force=False)` iterates all connected accounts, fetches transactions for the date range, normalizes descriptions, and upserts into DB
  - **Re-sync logic**: if the month is the current calendar month, always re-fetch (month is incomplete). For past months, skip fetch if transactions already exist unless `force=True`. `INSERT OR IGNORE` ensures re-syncing is safe.
  - **Token expiry handling**: on 401/403 from Teller for a specific account, skip that account, continue syncing remaining accounts, and collect warnings. Return warnings to CLI layer for display.
  - `normalize_merchant(raw)` uppercases, collapses whitespace, strips trailing `#\d+` patterns (e.g., `"Trader Joe #123 Los Angeles"` → `"TRADER JOE LOS ANGELES"`)
  - Upsert uses `INSERT OR IGNORE` keyed on Teller transaction ID to skip duplicates
  - Returns count of new transactions inserted

  **Patterns to follow:**
  - Batch INSERT for efficiency (use `executemany`)
  - Normalize once on insert, store both raw and normalized descriptions

  **Test scenarios:**
  - Happy path: sync inserts new transactions with correct normalized descriptions
  - Happy path: sync skips already-existing transactions (idempotent)
  - Happy path: sync across multiple accounts merges into one table
  - Happy path: normalize_merchant strips trailing #digits and collapses whitespace
  - Edge case: normalize_merchant handles already-clean strings
  - Edge case: normalize_merchant handles empty or None description
  - Edge case: sync for month with no transactions inserts nothing, returns 0
  - Happy path: sync for current calendar month always re-fetches
  - Happy path: sync for past month with existing data skips fetch (unless force=True)
  - Error path: Teller 401 on one account skips it, syncs remaining accounts, returns warning
  - Integration: full sync → query by month returns correct transactions

  **Verification:**
  - Normalized descriptions match expected patterns
  - Re-syncing the same month doesn't create duplicates

- [ ] **Unit 7: Accounts Management TUI**

  **Goal:** Build the `finmint accounts` interactive TUI for listing, adding (enrolling), and deleting connected bank accounts.

  **Requirements:** R5, R29, R30, R31

  **Dependencies:** Unit 5, Unit 3

  **Files:**
  - Create: `src/finmint/accounts_tui.py`
  - Modify: `src/finmint/cli.py` (wire up `accounts` command)
  - Create: `tests/test_accounts_tui.py`

  **Approach:**
  - Textual app with a DataTable showing: institution name, account type, last 4 digits, last synced date
  - Keybindings: `a` to add (launches enrollment flow), `d` to delete (with confirmation), `q` to quit
  - Deletion calls `delete_account()` on Teller API and removes from local DB. Transactions from that account remain.
  - Footer bar shows available actions

  **Patterns to follow:**
  - Textual `App` subclass with `DataTable` widget
  - Keybinding actions via `BINDINGS` class variable

  **Test scenarios:**
  - Happy path: accounts list renders with correct columns and data
  - Happy path: delete account removes from DB but keeps transactions
  - Edge case: accounts list with no connected accounts shows helpful empty state message
  - Error path: delete account with Teller API failure shows error but doesn't crash

  **Verification:**
  - `finmint accounts` launches TUI with account data from DB
  - Account operations persist correctly

### Phase 3: Categorization & Review

- [ ] **Unit 8: Merchant Rules Engine**

  **Goal:** Implement the rules engine: CRUD operations, substring matching with normalization, and longest-match-wins logic.

  **Requirements:** R17, R18, R19, R21

  **Dependencies:** Unit 3

  **Files:**
  - Create: `src/finmint/rules.py`
  - Create: `tests/test_rules.py`

  **Approach:**
  - `add_rule(conn, pattern, label_id, source='manual')` normalizes the pattern and inserts
  - `delete_rule(conn, rule_id)` removes the rule without affecting existing transaction labels
  - `match_rules(conn, normalized_description)` fetches all rules, filters by substring containment, returns the longest matching rule (most specific wins)
  - `get_all_rules(conn)` returns all rules with their label names for TUI display
  - All pattern storage and matching is case-insensitive (patterns stored uppercase, descriptions normalized uppercase)

  **Patterns to follow:**
  - Pure functions operating on sqlite3 connection
  - Matching logic in Python (fetch all rules, filter in-memory) — rule count will be small (<500)

  **Test scenarios:**
  - Happy path: add_rule stores normalized pattern
  - Happy path: match_rules finds correct rule by substring
  - Happy path: longest match wins when multiple rules match (e.g., "TRADER JOE" vs "TRADER")
  - Edge case: no rules match returns None
  - Edge case: delete_rule doesn't affect transactions that used that rule
  - Happy path: get_all_rules returns rules sorted alphabetically with label names
  - Edge case: adding duplicate pattern (same normalized string) updates existing rule

  **Verification:**
  - Substring matching works with various merchant name formats
  - Longest match consistently wins

- [ ] **Unit 9: Transfer Detection**

  **Goal:** Implement inter-account transfer detection by matching debit/credit pairs across accounts within a 2-day window.

  **Requirements:** R22, R23, R24

  **Dependencies:** Unit 3

  **Files:**
  - Create: `src/finmint/transfers.py`
  - Create: `tests/test_transfers.py`

  **Approach:**
  - `detect_transfers(conn, month, year)` queries all transactions for the month, finds pairs where: amount_a == -amount_b, different account_ids, dates within 2 days
  - **Pre-filter**: exclude transactions with `teller_type = 'card_payment'` from transfer candidate pool to reduce false positives
  - **Additional heuristic**: prefer pairs where at least one transaction has `teller_type = 'transfer'` or `teller_type = 'ach'`. Pairs with no transfer-type indicator are still detected but marked with lower confidence.
  - When a pair is found, set both transactions' `transfer_pair_id` to link them, set label to "Transfer" label (looked up by `is_protected` + name, not hardcoded ID), set `review_status` to `needs_review`
  - **Transfer pairs are always surfaced prominently in the review TUI** — show them grouped together so the user can confirm or reject the pairing. Rejecting unlinks the pair and removes the Transfer label, returning both to uncategorized.
  - Greedy matching: process pairs by closest date first to avoid ambiguous matches. Tie-breaking when date distance is equal: prefer pairs where teller_type suggests a transfer.
  - Skip transactions already marked as transfers

  **Patterns to follow:**
  - Pure function operating on DB connection
  - Use Pandas DataFrame for efficient pair-finding if helpful, or plain SQL + Python

  **Test scenarios:**
  - Happy path: matching $500 debit and $500 credit across two accounts on same day detected
  - Happy path: matching pair within 2-day window detected
  - Edge case: matching amounts on same account NOT flagged as transfer
  - Edge case: matching amounts 3+ days apart NOT flagged as transfer
  - Edge case: three transactions with same amount — only closest pair matched
  - Edge case: already-linked transfers are not re-processed
  - Happy path: detected transfers get "Transfer" label and linked pair IDs

  **Verification:**
  - Transfer pairs are correctly linked in DB
  - No false positives from same-account transactions

- [ ] **Unit 10: AI Categorization (Claude API)**

  **Goal:** Implement batch transaction categorization via Claude API for transactions not matched by rules.

  **Requirements:** R13, R14, R15, R16

  **Dependencies:** Unit 8, Unit 3

  **Files:**
  - Create: `src/finmint/ai.py`
  - Create: `tests/test_ai.py`

  **Approach:**
  - `categorize_transactions(conn, config, transactions)` sends uncategorized transactions to Claude in a single batch call
  - **Data minimization**: Prompt includes only what Claude needs for categorization — merchant description, amount, and date. Omit account IDs, Teller transaction IDs, and institution names (use local sequence numbers as keys in the JSON response). Do not send any personally identifiable information.
  - Prompt includes: full list of available labels, minimized transaction details (local sequence number, merchant description, amount, date), instruction to return JSON mapping sequence numbers to label names
  - Parse response, validate label names exist, update transactions with `categorized_by='ai'`, `review_status='needs_review'`
  - If >200 uncategorized transactions, split into batches of 100
  - `generate_monthly_summary(conn, config, month, year)` sends categorized data to Claude for narrative summary generation. Includes current month totals by category and trailing 3-month averages.
  - `generate_yearly_summary(conn, config, year)` similar but for year-to-date

  **Patterns to follow:**
  - Anthropic Python SDK: `client.messages.create()` with structured system prompt
  - JSON response parsing with fallback for malformed responses

  **Test scenarios:**
  - Happy path: batch categorization assigns correct labels from mock Claude response
  - Happy path: categorization skips transactions already categorized by rules
  - Happy path: batching splits >200 transactions into groups of 100
  - Edge case: Claude returns unknown label name — transaction left uncategorized
  - Error path: Claude API returns error — raises clear message, no partial state corruption
  - Happy path: monthly summary includes category totals and 3-month comparison
  - Edge case: monthly summary with <3 months of history omits comparison

  **Verification:**
  - Uncategorized transactions get labels after AI call
  - Rule-categorized transactions are not sent to the API

- [ ] **Unit 11: Categorization Orchestrator**

  **Goal:** Wire together the full categorization pipeline: rules → transfers → AI, executed as part of the `finmint <M-YYYY>` command flow.

  **Requirements:** R1, R13, R14, R15

  **Dependencies:** Unit 6, Unit 8, Unit 9, Unit 10

  **Files:**
  - Create: `src/finmint/categorize.py`
  - Modify: `src/finmint/cli.py` (wire up the review command)
  - Create: `tests/test_categorize.py`

  **Approach:**
  - `categorize_month(conn, config, month, year)` runs the pipeline: (1) apply merchant rules to all uncategorized transactions, (2) detect transfers, (3) batch-send remaining to Claude API
  - Returns a summary: counts of rule-matched, transfer-detected, AI-categorized, and still-uncategorized
  - Called by `finmint <M-YYYY>` after sync and before launching review TUI

  **Patterns to follow:**
  - Orchestrator function that calls into rules.py, transfers.py, ai.py
  - Clear separation: each step is idempotent and can be re-run

  **Test scenarios:**
  - Happy path: pipeline applies rules first, then transfers, then AI, in correct order
  - Happy path: rule-matched transactions are not sent to AI
  - Happy path: transfer-detected transactions are not sent to AI
  - Integration: full pipeline with mix of rule-matched, transfer, and AI-categorized transactions
  - Edge case: all transactions matched by rules — AI never called
  - Edge case: no rules exist — all go to AI

  **Verification:**
  - Pipeline produces correct categorization with tiered priority
  - Each step's results persist in DB before next step runs

- [ ] **Unit 12: Transaction Review TUI**

  **Goal:** Build the interactive Textual app for reviewing and categorizing transactions, with both table and one-by-one modes.

  **Requirements:** R7, R8, R9, R10, R11, R12

  **Dependencies:** Unit 11, Unit 8

  **Files:**
  - Create: `src/finmint/review_tui.py`
  - Create: `tests/test_review_tui.py`

  **Approach:**
  - Textual `App` with main screen: `DataTable` showing date, merchant, amount, category, status
  - Status column uses Rich styling: green checkmark for reviewed/auto_accepted, yellow `?` for needs_review, dimmed/strikethrough for exempt
  - Keybindings: `↑↓` navigate, `Enter` opens category picker (list of labels), `a` accepts current category, `Space` toggles selection, `B` bulk-accepts selected, `e` exempts, `t` toggles to one-by-one mode, `q` quits
  - One-by-one mode: separate Textual screen showing single transaction detail with accept/change/exempt/skip actions
  - **Auto-rule creation on correction**: when user changes category via Enter, silently call `add_rule(conn, normalized_description, new_label_id, source='auto_learned')` (R12)
  - Category picker: Textual `OptionList` or `Select` widget showing all labels
  - Header shows: month/year, total transactions, reviewed count, unreviewed count
  - Footer shows available keybindings

  **Patterns to follow:**
  - Textual `App` with `Screen` for mode switching
  - Custom `EditableDataTable` subclass for inline category editing
  - `BINDINGS` for keyboard shortcuts

  **Test scenarios:**
  - Happy path: review table renders all transactions with correct columns
  - Happy path: accepting a transaction changes status to 'reviewed'
  - Happy path: changing category updates label and creates merchant rule silently
  - Happy path: exempting dims the row and sets status to 'exempt'
  - Happy path: bulk accept marks all selected transactions as reviewed
  - Happy path: toggling to one-by-one mode shows first unreviewed transaction
  - Edge case: all transactions already reviewed — shows "all reviewed" message
  - Integration: category correction creates rule that applies to next sync

  **Verification:**
  - Review session persists all changes to SQLite
  - Auto-learned rules appear in merchant_rules table after corrections

- [ ] **Unit 13: Rules Management TUI**

  **Goal:** Build the `finmint rules` interactive TUI for viewing, adding, editing, and deleting merchant rules.

  **Requirements:** R6, R17, R20

  **Dependencies:** Unit 8

  **Files:**
  - Create: `src/finmint/rules_tui.py`
  - Modify: `src/finmint/cli.py` (wire up `rules` command)
  - Create: `tests/test_rules_tui.py`

  **Approach:**
  - Textual app with DataTable: pattern, label, source (manual/auto_learned), created date
  - Sorted alphabetically by pattern
  - Keybindings: `a` to add new rule (prompts for pattern and label), `Enter` to edit selected rule's label, `d` to delete (with confirmation), `q` to quit
  - Adding: Textual Input for pattern string, then OptionList for label selection
  - Editing: OptionList for new label selection
  - Footer shows available actions

  **Patterns to follow:**
  - Same Textual App pattern as accounts_tui.py
  - Reuse label selection widget across review and rules TUIs

  **Test scenarios:**
  - Happy path: rules table shows all rules with correct columns
  - Happy path: add rule creates new rule in DB and refreshes table
  - Happy path: edit rule changes label and refreshes table
  - Happy path: delete rule removes from DB (transactions keep their labels)
  - Edge case: empty rules table shows helpful message
  - Edge case: adding rule with pattern that already exists updates the existing rule

  **Verification:**
  - `finmint rules` displays current rules from DB
  - All CRUD operations persist correctly

### Phase 4: Labels, Visualization & Polish

- [ ] **Unit 14: Label Management TUI**

  **Goal:** Build the `finmint labels` interactive TUI for managing category labels with cascading operations.

  **Requirements:** R4, R25, R26, R27, R28

  **Dependencies:** Unit 3

  **Files:**
  - Create: `src/finmint/labels_tui.py`
  - Modify: `src/finmint/cli.py` (wire up `labels` command)
  - Create: `tests/test_labels_tui.py`

  **Approach:**
  - Textual app with DataTable: label name, transaction count using that label, default/custom indicator
  - Keybindings: `a` to add, `Enter` to edit name, `d` to delete, `q` to quit
  - **Delete flow**: check `is_protected` first — protected labels (Transfer, Income) cannot be deleted. For deletable labels, show count of affected transactions and prompt for reassignment label via OptionList. Update all transactions and merchant rules to the new label in a single SQLite transaction (atomic), then delete.
  - **Edit flow**: check `is_protected` first — protected labels cannot be renamed. For editable labels, rename cascades via foreign key (label_id stays same, name changes), so no manual cascade needed.

  **Patterns to follow:**
  - Same Textual App pattern as other TUIs
  - Foreign key relationships handle cascade for edit (label_id stays same, name changes)

  **Test scenarios:**
  - Happy path: labels table shows all labels with transaction counts
  - Happy path: add label creates new label and refreshes table
  - Happy path: edit label name updates in labels table (transactions auto-reflect via FK)
  - Happy path: delete label reassigns all transactions to chosen label before removal
  - Happy path: delete label reassigns merchant rules to chosen label
  - Edge case: cannot delete the last remaining label
  - Edge case: cannot delete or rename protected labels (Transfer, Income) — shows error
  - Edge case: deleting a label with zero transactions skips reassignment prompt
  - Integration: label deletion reassigns both transactions AND merchant rules atomically

  **Verification:**
  - No orphaned transactions after label deletion
  - Label rename reflected everywhere via FK relationship

- [ ] **Unit 15: Charts & Visualization**

  **Goal:** Implement pie chart (monthly) and bar chart (yearly) rendering via Matplotlib, opened in system viewer.

  **Requirements:** R2, R3, R32, R34

  **Dependencies:** Unit 3

  **Files:**
  - Create: `src/finmint/charts.py`
  - Create: `tests/test_charts.py`

  **Approach:**
  - `render_monthly_pie(conn, month, year)` queries spending by category (excluding exempt and transfers), generates Matplotlib pie chart, saves to temp file, opens with cross-platform opener (`open` on macOS, `xdg-open` on Linux, `start` on Windows, fallback to printing file path)
  - `render_yearly_bars(conn, year)` queries monthly totals with category breakdown, generates grouped/stacked bar chart, same display approach
  - Use Pandas for aggregation: group transactions by label, sum amounts, convert cents to dollars for display
  - Color palette: use a consistent color map keyed by label name so categories always get the same color
  - Charts show amounts in dollars, percentages on pie slices, legend with label names

  **Patterns to follow:**
  - Matplotlib `plt.figure()` → `plt.savefig()` → `subprocess.run(["open", ...])` pattern
  - `tempfile.NamedTemporaryFile(suffix='.png', delete=False)` for temp chart files
  - Pandas groupby for aggregation

  **Test scenarios:**
  - Happy path: monthly pie chart generates valid PNG file with correct category proportions
  - Happy path: yearly bar chart generates valid PNG with monthly bars
  - Edge case: month with all transactions exempt renders empty chart with message
  - Edge case: year with only one month of data renders single bar
  - Happy path: transfers excluded from charts
  - Happy path: exempt transactions excluded from charts

  **Verification:**
  - Charts render without errors for various data distributions
  - Excluded categories (Transfer, exempt) don't appear in charts

- [ ] **Unit 16: View Command (Monthly + Yearly)**

  **Goal:** Wire up `finmint view <M-YYYY>` and `finmint view <YYYY>` commands with charts, AI summaries, and unreviewed counts.

  **Requirements:** R2, R3, R33, R34, R35

  **Dependencies:** Unit 15, Unit 10

  **Files:**
  - Modify: `src/finmint/cli.py` (implement `view` subcommand)
  - Create: `tests/test_view.py`

  **Approach:**
  - `finmint view 3-2026`: (1) query transactions for month, (2) render pie chart, (3) generate or retrieve cached AI summary, (4) print summary + unreviewed count via Rich
  - `finmint view 2026`: (1) query all months in year, (2) render yearly bar chart, (3) generate or retrieve cached yearly AI summary, (4) print summary
  - AI summaries cached in `ai_summaries` table to avoid redundant API calls. Regenerate if transactions have changed since last generation.
  - Rich console output for summary text with styled formatting
  - Show warning if unreviewed transactions exist: "⚠ 12 transactions still need review. Run `finmint 3-2026` to review."

  **Patterns to follow:**
  - Typer command with argument parsing (`M-YYYY` vs `YYYY` format detection)
  - Rich Console for formatted output

  **Test scenarios:**
  - Happy path: monthly view shows pie chart, summary, and unreviewed count
  - Happy path: yearly view shows bar chart and year summary
  - Happy path: cached summary is reused when transactions haven't changed
  - Happy path: summary regenerated when new transactions exist since last generation
  - Edge case: view for month with no transactions shows "no data" message
  - Edge case: unreviewed count shown only when >0

  **Verification:**
  - `finmint view 3-2026` produces chart + summary output
  - Summary caching avoids redundant API calls

- [ ] **Unit 17: CLI Wiring & End-to-End Flow**

  **Goal:** Wire all components together in the main `finmint <M-YYYY>` command: sync → categorize → review TUI. Ensure all commands are routable and error handling is consistent.

  **Requirements:** R1, R7

  **Dependencies:** Unit 6, Unit 11, Unit 12, Unit 16

  **Files:**
  - Modify: `src/finmint/cli.py` (finalize all command routing)
  - Create: `tests/test_cli_integration.py`

  **Approach:**
  - `finmint 3-2026` flow: (1) load config, (2) sync month from Teller with Rich spinner/progress indicator (skip if past month already synced), (3) run categorization pipeline, (4) print summary ("Synced 83 transactions. 71 auto-categorized by rules, 12 need review.") plus any token expiry warnings, (5) launch review TUI
  - Argument parsing: detect `M-YYYY` format for review command vs `view` subcommand
  - Global error handling: catch config errors, API errors, DB errors with user-friendly messages via Rich
  - `--force-sync` flag to re-fetch even if already synced

  **Patterns to follow:**
  - Typer callback for the default command (no subcommand name needed)
  - Rich `Console.print()` for formatted status messages

  **Test scenarios:**
  - Happy path: full flow from CLI invocation through sync, categorize, and TUI launch
  - Happy path: already-synced month skips Teller API call
  - Happy path: `--force-sync` re-fetches from Teller
  - Error path: no config file shows setup instructions
  - Error path: Teller API failure shows clear error, doesn't corrupt DB
  - Error path: Claude API failure shows error but rule-categorized transactions are preserved

  **Verification:**
  - End-to-end flow works: `finmint 3-2026` syncs, categorizes, and opens review
  - Error states produce helpful messages, not stack traces

## System-Wide Impact

- **Interaction graph:** CLI commands → Textual TUIs → business logic modules → DB/API. No callbacks, middleware, or observers. All interactions are synchronous and user-initiated.
- **Error propagation:** API errors (Teller, Claude) should be caught at the CLI layer and displayed via Rich. DB errors should abort the current operation cleanly. No partial state: use SQLite transactions for multi-step writes.
- **State lifecycle risks:** Interrupted sync could leave partial transaction data. Mitigate with `INSERT OR IGNORE` on Teller transaction IDs — re-sync is safe and idempotent. Interrupted categorization is also safe — uncategorized transactions remain as `needs_review`.
- **API surface parity:** N/A — single CLI interface, no API consumers.
- **Integration coverage:** Key cross-layer scenarios: (1) correction in review TUI creates rule that affects next sync's categorization, (2) label deletion cascades through transactions and rules, (3) account deletion preserves historical transactions.

## Risks & Dependencies

- **Teller API availability:** Teller is a third-party service. If it goes down or changes endpoints, sync breaks. Mitigation: local DB is the source of truth; offline review always works.
- **Teller Connect browser flow:** The local HTTP callback server approach is fragile across different OS/browser configurations. Mitigation: test on macOS first (Jordan's platform), document known issues.
- **Claude API costs:** Batch categorization of 100+ transactions per month is inexpensive (~$0.01-0.05 per call) but costs could add up. Mitigation: merchant rules reduce AI calls over time; the success criterion targets >70% rule-based after 3 months.
- **Textual DataTable inline editing:** Not built-in; requires custom subclass. Mitigation: well-documented community pattern, ~50 lines of code.
- **Matplotlib in headless environments:** `subprocess.run(["open", ...])` requires a display. Mitigation: this is a personal terminal tool, always run on a local machine with a display.

## Documentation / Operational Notes

- **README.md:** Setup instructions covering Python install, pip install, Teller cert setup, Claude API key, first run. Include screenshots of the review TUI.
- **config.example.yaml:** Shipped in repo with placeholder values and comments explaining each field.
- **CONTRIBUTING.md:** Basic contribution guide for open-source repo. Include: dev setup, running tests, code style expectations.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-30-finmint-core-requirements.md](docs/brainstorms/2026-03-30-finmint-core-requirements.md)
- **Teller API docs:** https://teller.io/docs/api
- **Textual DataTable:** https://textual.textualize.io/widgets/data_table/
- **Anthropic Python SDK:** https://docs.anthropic.com/en/docs/sdks
- **Ideation doc:** [docs/ideation/2026-03-30-finmint-core-ideation.md](docs/ideation/2026-03-30-finmint-core-ideation.md)
