---
title: "refactor: Replace Teller API with Copilot Money GraphQL backend"
type: refactor
status: completed
date: 2026-03-31
origin: docs/brainstorms/2026-03-31-copilot-money-backend-requirements.md
deepened: 2026-03-31
---

# Replace Teller API with Copilot Money GraphQL Backend

## Overview

Replace the Teller mTLS REST API with Copilot Money's reverse-engineered GraphQL API as the sole transaction data source. This eliminates mTLS certificate management, the browser-based enrollment flow, and per-account token handling. Auth becomes a single manually-pasted JWT. Accounts are auto-discovered. The schema is rebuilt clean (fresh start — no migration needed).

## Problem Frame

Teller's mTLS requirement creates significant setup friction. Jordan already has all bank accounts connected via Copilot Money. By using Copilot's GraphQL API, Finmint gets the same data with dramatically simpler auth (paste a JWT) and no bank enrollment flow. (see origin: `docs/brainstorms/2026-03-31-copilot-money-backend-requirements.md`)

## Requirements Trace

- R1. Manual JWT token paste via interactive prompt, not CLI arg
- R2. `finmint token` command stores JWT in `~/.finmint/config.yaml`
- R3. UNAUTHENTICATED errors display clear message directing user to `finmint token`
- R4. GraphQL POST to `https://app.copilot.money/api/graphql` with Bearer token
- R5. Client supports `Accounts` and `Transactions` queries
- R6. Automatic cursor-based pagination
- R7. Auto-discover accounts on sync, upsert locally
- R8. Account records: Copilot ID, institution name, account type, last four, last sync
- R9. `finmint accounts` becomes read-only
- R10. `sync_month` fetches from Copilot for all discovered accounts
- R11. Transactions mapped to Finmint data model (ID, amount in cents, date, description)
- R12. Copilot categories/tags/review status discarded
- R13. Upsert via INSERT OR IGNORE keyed on Copilot transaction ID
- R14–R17. Supersedes Teller-specific requirements from core doc (enrollment, config, first-run, secrets)

## Scope Boundaries

- **Fresh start** — DB is dropped and recreated with clean schema. No ALTER TABLE migration. This intentionally discards `merchant_rules` and `ai_summaries` data alongside `accounts` and `transactions`. Acceptable since the tool has no production data yet.
- **Teller code fully removed** — `teller.py`, `enrollment.py`, and their tests are deleted.
- **No Copilot write operations** — read-only data pipe.
- **No Playwright** — manual token paste only.
- **Copilot categories ignored** — Finmint owns all categorization.

## Context & Research

### Relevant Code and Patterns

- **API client pattern** (`src/finmint/teller.py`): Context manager factory yielding `httpx.Client`, pure functions per API call, domain-specific exceptions, pagination handled internally, amount conversion in client layer. The new `copilot.py` mirrors this structure.
- **Sync orchestration** (`src/finmint/sync.py`): Currently iterates per-account with per-account tokens. Needs restructuring — single JWT for all accounts means one client, fetch accounts first, then fetch transactions per account.
- **Config pattern** (`src/finmint/config.py`): `REQUIRED_KEYS` + `DEFAULT_CONFIG` + `init_config()` + `validate_config()` — all tightly coupled, change together.
- **TUI pattern** (`src/finmint/accounts_tui.py`): Textual `App` with `DataTable`, action methods, `_refresh_table()`. Remove `action_add_account`, `action_delete_account`, `ConfirmDeleteScreen`.
- **Transfer detection** (`src/finmint/transfers.py`): Uses `teller_type` column to exclude `card_payment` and prefer `transfer`/`ach`. Column renamed to `source_type`, Copilot's `InternalTransfer` maps to the preference logic.
- **Testing**: `respx` for httpx mocking, `@patch` for module-level imports, `in_memory_db` fixture, 1:1 test file to source file mapping.

### External References

- Copilot Money GraphQL endpoint: `https://app.copilot.money/api/graphql`
- Reference implementation: `github.com/JaviSoto/copilot-money-cli` (Rust, uses Playwright for auth, 28 GraphQL operations)
- Copilot transaction types: `Regular`, `InternalTransfer`, `Other`
- Copilot pagination: Relay-style cursor (`first`, `after`, `edges`/`nodes`/`pageInfo`)

## Key Technical Decisions

- **Rename `teller_type`/`teller_category` to `source_type`/`source_category`**: Generic names avoid confusion. `teller_category` was never used in app logic — drop it entirely. `source_type` stores Copilot's `type` field (`Regular`, `InternalTransfer`, `Other`) for transfer detection.

- **Drop `enrollment_id` and `access_token` from accounts schema**: These are Teller concepts. Copilot uses a single global JWT (stored in config), not per-account tokens. Accounts table keeps: `id`, `institution_name`, `account_type`, `last_four`, `last_synced_at`, `created_at`.

- **Restructure sync loop — accounts-first, then transactions**: Instead of iterating accounts with per-account tokens, sync first calls the Copilot `Accounts` query to upsert local records, then iterates all local accounts to fetch transactions using the single JWT.

- **Transfer detection adapts to Copilot types**: Drop the `card_payment` exclusion (Copilot's `Regular` doesn't distinguish card vs. non-card). Use `InternalTransfer` as a stronger signal — require at least one side of a candidate pair to have `source_type == "InternalTransfer"` OR fall back to amount-matching-only with a lower confidence. This reduces false positives from the wider candidate set. Transfers are still marked `needs_review`.

- **`finmint token` validates before storing**: Makes a lightweight API call (accounts query) to verify the JWT before writing to config. Fails fast on bad tokens.

- **httpx for GraphQL (no new dependency)**: GraphQL is just POST JSON. httpx is already in the stack. No need for a dedicated GraphQL client library. **Important pattern break:** Unlike REST APIs, GraphQL returns HTTP 200 for errors — the client must parse `response.json()["errors"]` for error detection, not rely on `response.raise_for_status()`. This is a departure from `teller.py`'s status-code-based error handling.

- **UNAUTHENTICATED aborts entire sync**: Since all accounts share one JWT, a single auth failure means the session is dead. No per-account skip logic (unlike Teller). Partial results from already-committed transactions are preserved (commit-per-insert is idempotent via `INSERT OR IGNORE`), so re-running sync after re-authenticating picks up where it left off.

- **`validate_config` checks for empty token values**: Beyond structural key existence, `validate_config` should warn when `copilot.token` is an empty string or placeholder. This prevents the confusing UX of config "validating" but sync immediately failing with an auth error.

## Open Questions

### Resolved During Planning

- **Schema migration strategy**: Fresh start. User confirmed no existing Teller data to preserve. DDL is rewritten clean — no ALTER TABLE.
- **How to handle per-account tokens**: Eliminated. Single JWT in config. `_get_connected_accounts()` filter on `access_token` is removed; sync iterates all accounts in the local table.
- **`card_payment` exclusion replacement**: Dropped. Copilot's type system doesn't distinguish card payments. `InternalTransfer` scoring is sufficient. False positives are acceptable since transfers require review.
- **`finmint init` vs `finmint token`**: `init_config()` is replaced. First-run flow: `finmint token` creates `~/.finmint/` dir and `config.yaml` if they don't exist. Claude API key env var defaults to `ANTHROPIC_API_KEY` (configurable in config.yaml).

### Deferred to Implementation

- **Copilot transaction amount format and sign convention**: Needs runtime inspection of actual API responses. The client layer will handle conversion to integer cents (negative = debit) regardless of source format.
- **Exact GraphQL query structures**: Need to inspect Copilot's actual schema for `Transactions` and `Accounts` queries — field names, filter arguments, pagination params. The reference implementation provides strong hints but runtime verification is needed.
- **Copilot transaction ID format**: Need to confirm IDs are stable strings suitable for `INSERT OR IGNORE` primary keys.
- **JWT token lifespan**: How long before expiry? Affects UX messaging. Discovered during testing.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
User Flow:
  finmint token --> prompt for JWT --> validate via Accounts query --> store in config.yaml
  finmint 3-2026 --> load config --> create Copilot client (JWT Bearer)
                 --> fetch Accounts from Copilot --> upsert local account records
                 --> for each account: fetch Transactions (paginated) --> normalize --> upsert
                 --> categorize (rules -> transfers -> AI) --> launch review TUI

Module Dependency:
  cli.py --> config.py (load JWT)
         --> copilot.py (GraphQL client: fetch_accounts, fetch_transactions)
         --> sync.py (orchestrate: discover accounts, fetch + normalize + upsert txns)
         --> categorize.py (unchanged) --> transfers.py (uses source_type instead of teller_type)

Config Shape:
  copilot:
    token: <jwt>
  claude:
    api_key_env: ANTHROPIC_API_KEY
```

## Implementation Units

- [ ] **Unit 1: Create Copilot Money GraphQL client**

**Goal:** Replace `teller.py` with `copilot.py` — the GraphQL client for Copilot Money.

**Requirements:** R4, R5, R6, R3

**Dependencies:** None

**Files:**
- Create: `src/finmint/copilot.py`
- Create: `tests/test_copilot.py`
- Note: `teller.py` and `test_teller.py` deletion deferred to Unit 8 to keep the codebase importable between units

**Approach:**
- **Start with a discovery spike:** Before writing production code, make actual API calls with a real JWT (via a throwaway script or REPL) to verify: transaction amount format and sign convention, account field names, transaction ID format, pagination structure. This resolves the four deferred implementation questions and prevents rework.
- Mirror `teller.py`'s structure: context manager factory yielding `httpx.Client`, pure functions for each query, domain-specific exception classes
- `create_client(token)` yields an `httpx.Client` with `base_url="https://app.copilot.money"` and `Authorization: Bearer <token>` header
- **GraphQL error detection pattern break:** Unlike `teller.py`'s `_raise_for_status` (HTTP status codes), the Copilot client must parse `response.json()` and inspect the `errors` array in the response body. GraphQL APIs return HTTP 200 even for auth errors. Use a `_raise_for_graphql_errors(data)` helper instead.
- `CopilotAuthError` raised on UNAUTHENTICATED GraphQL errors
- `CopilotAPIError` for other GraphQL errors
- `fetch_accounts(client)` sends the `Accounts` GraphQL query, returns list of account dicts
- `fetch_transactions(client, account_id, start_date, end_date)` sends paginated `Transactions` query, handles Relay-style cursor pagination internally, returns all transactions with amounts converted to integer cents
- `_amount_to_cents(amount)` moved from `teller.py` — adapt based on Copilot's amount format (discover during implementation)
- GraphQL queries embedded as string constants in the module

**Patterns to follow:**
- `src/finmint/teller.py` — context manager, pagination, amount conversion (but NOT error handling — see GraphQL pattern break above)
- `src/finmint/ai.py` — httpx POST with JSON body pattern
- Testing: use `respx` to mock httpx transport layer (matching `test_teller.py` pattern for client-level tests)

**Test scenarios:**
- Happy path: `fetch_accounts` returns parsed account list from GraphQL response
- Happy path: `fetch_transactions` returns all transactions with amounts in cents, pagination auto-followed
- Happy path: Single-page response (no pagination needed) returns correctly
- Edge case: Empty accounts list returns `[]`
- Edge case: Empty transactions list returns `[]`
- Error path: UNAUTHENTICATED GraphQL error raises `CopilotAuthError` with actionable message
- Error path: Other GraphQL error raises `CopilotAPIError` with error details
- Error path: Network error (httpx.ConnectError) propagates
- Edge case: Pagination stops when `pageInfo.hasNextPage` is false

**Verification:**
- `tests/test_copilot.py` passes
- `copilot.py` exports: `create_client`, `fetch_accounts`, `fetch_transactions`, `CopilotAuthError`, `CopilotAPIError`
- Discovery spike findings documented (amount format, ID format, pagination confirmed)

---

- [ ] **Unit 2: Update DB schema and models for Copilot**

**Goal:** Clean up the database schema and TypedDicts to remove Teller-specific columns and add generic equivalents.

**Requirements:** R8, R11, R14

**Dependencies:** None (can be done in parallel with Unit 1)

**Files:**
- Modify: `src/finmint/db.py`
- Modify: `src/finmint/models.py`
- Modify: `tests/conftest.py` (if fixture helpers reference old columns)
- Modify: `tests/test_sync.py` (has `_seed_account` helper that inserts into accounts with old column names)
- Modify: `tests/test_transfers.py` (has `_insert_account` helper and `teller_type` references in test data)
- Modify: `tests/test_accounts_tui.py` (has `_insert_account` helper; also remove `test_delete_account_keeps_transactions` since delete is being removed)

**Approach:**
- `accounts` table: Remove `enrollment_id`, `access_token`, `account_subtype`. Keep `id TEXT PRIMARY KEY`, `institution_name TEXT`, `account_type TEXT`, `last_four TEXT`, `last_synced_at TEXT`, `created_at TEXT`
- `transactions` table: Rename `teller_type` to `source_type`, drop `teller_category` entirely
- Update `_SCHEMA_SQL` DDL string
- Update `insert_transaction()` — remove `teller_type`/`teller_category` params, add `source_type` param
- Update `Account` TypedDict — remove `enrollment_id`, `access_token`, `account_subtype`
- Update `Transaction` TypedDict — replace `teller_type` with `source_type`, remove `teller_category`
- Add `upsert_account(conn, data)` function for account discovery (INSERT OR REPLACE keyed on Copilot account ID)

**Patterns to follow:**
- Existing `insert_transaction()` pattern in `db.py`
- Existing TypedDict pattern in `models.py` (`total=False`)

**Test scenarios:**
- Happy path: `insert_transaction` with `source_type` stores correctly and is retrievable
- Happy path: `upsert_account` creates new account record
- Happy path: `upsert_account` updates existing account (same ID) without duplicating
- Edge case: `insert_transaction` with `source_type=None` stores NULL
- Edge case: `upsert_account` with minimal fields (only ID and institution_name)

**Verification:**
- Schema DDL creates tables without Teller-specific columns
- `models.py` TypedDicts match the new schema
- All existing DB tests pass after schema update (may need fixture updates)

---

- [ ] **Unit 3: Update config for Copilot token management**

**Goal:** Replace Teller config with Copilot token storage. Add `finmint token` command.

**Requirements:** R1, R2, R3, R15, R16, R17

**Dependencies:** Unit 1 (needs `copilot.fetch_accounts` for token validation)

**Files:**
- Modify: `src/finmint/config.py`
- Modify: `src/finmint/cli.py`
- Modify: `config.example.yaml`
- Modify: `tests/test_config.py`

**Approach:**
- `REQUIRED_KEYS`: Replace `"teller": [...]` with `"copilot": ["token"]`
- `DEFAULT_CONFIG`: Replace teller section with `"copilot": {"token": ""}`, keep claude section
- `init_config()`: Remove Teller prompts. Create `~/.finmint/` dir + minimal `config.yaml` with empty copilot token and default claude section. No longer prompts interactively (that's `finmint token`'s job)
- Add `save_token(token, home=None)` function: loads existing config (or creates default), sets `copilot.token`, writes back with `0o600` permissions
- Add `get_token(config)` function: reads `config["copilot"]["token"]`, raises clear error if empty/missing
- `cli.py`: Add `finmint token` command — prompts via `getpass`-style input (no echo), calls `copilot.fetch_accounts()` to validate, calls `save_token()` on success
- `cli.py`: Update `_ensure_setup()` to handle missing config by running `init_config()` automatically (creates skeleton), then directing user to `finmint token`
- Update `config.example.yaml` to show copilot token placeholder + claude section

**Patterns to follow:**
- Existing `config.py` — `load_config`, `validate_config`, `resolve_api_key` structure
- Existing `cli.py` — error handling with Rich `[red]` markup and `typer.Exit(code=1)`

**Test scenarios:**
- Happy path: `validate_config` passes with valid copilot.token and claude.api_key_env
- Happy path: `save_token` writes token to existing config without clobbering claude section
- Happy path: `save_token` creates config file if it doesn't exist
- Happy path: `get_token` returns token string from valid config
- Error path: `validate_config` fails when copilot section is missing
- Error path: `validate_config` fails when copilot.token is missing
- Error path: `get_token` raises clear error when token is empty string
- Edge case: Config file has extra sections (preserved on save_token)
- Happy path: `init_config` creates directory with `0o700` and file with `0o600`

**Verification:**
- `tests/test_config.py` passes with no Teller references
- `finmint token` command is registered in CLI
- `config.example.yaml` shows Copilot + Claude config

---

- [ ] **Unit 4: Rewire sync module for Copilot**

**Goal:** Rewrite `sync_month` to use the Copilot client — accounts-first discovery, single JWT, new data mapping.

**Requirements:** R7, R10, R11, R12, R13

**Dependencies:** Unit 1 (copilot client), Unit 2 (schema + upsert_account), Unit 3 (token from config)

**Files:**
- Modify: `src/finmint/sync.py`
- Modify: `tests/test_sync.py`

**Approach:**
- Remove all `teller` imports and references
- Import from `finmint.copilot` instead
- Remove `_get_connected_accounts()` (no longer filtering by access_token)
- New sync flow:
  1. Read token from config via `config.get_token()`
  2. Create Copilot client with token
  3. Call `copilot.fetch_accounts()` → upsert each account locally via `db.upsert_account()`
  4. Query all accounts from local DB
  5. For each account: call `copilot.fetch_transactions()` with date range
  6. Normalize merchant description, map to Finmint data model, `INSERT OR IGNORE`
- `SyncResult` TypedDict changes: replace `skipped_accounts: list[str]` with `error: str | None` — since a single JWT means auth failures are all-or-nothing, a list of per-account warnings no longer makes sense
- `CopilotAuthError` aborts the entire sync with clear message (R3). Partial results from already-committed transactions are preserved (commit-per-insert is idempotent) — re-running sync after re-auth picks up where it left off
- The sync loop can iterate the API-returned account list directly for transaction fetching (avoids a stale-data window from querying local DB after upsert)
- Preserve `normalize_merchant()` — it's provider-agnostic
- Preserve `_has_transactions_for_month()` and `_is_current_month()` logic
- Transaction mapping: discard Copilot's `categoryId`, `tags`, `isReviewed`, `isPending`. Keep: `id`, `name` (as description), `amount`, `date`, `type` (as `source_type`), `accountId`
- Testing: use `@patch("finmint.sync.copilot")` to mock the copilot module (matching how `test_sync.py` currently patches `finmint.sync.teller`)

**Patterns to follow:**
- Existing `sync.py` — `SyncResult` TypedDict, normalize + upsert loop, force/current-month logic
- Existing `teller.py` → `copilot.py` — client creation pattern

**Test scenarios:**
- Happy path: `sync_month` discovers accounts, fetches transactions, upserts both into DB
- Happy path: Existing transactions are skipped via `INSERT OR IGNORE` (no duplicates)
- Happy path: Past month with existing data skips fetch (unless force=True)
- Happy path: Current month always re-fetches
- Happy path: `normalize_merchant` still works (preserved from existing tests)
- Edge case: Copilot returns 0 accounts → sync completes with 0 transactions
- Edge case: Copilot returns accounts but 0 transactions for the month
- Error path: `CopilotAuthError` aborts sync with clear message including "run `finmint token`"
- Error path: Network error during account fetch propagates
- Integration: New accounts from Copilot appear in local DB after sync
- Integration: `force=True` re-fetches even when data exists for past month

**Verification:**
- `tests/test_sync.py` passes with Copilot mocks (no Teller references)
- `normalize_merchant` tests preserved unchanged
- Sync correctly populates both accounts and transactions tables

---

- [ ] **Unit 5: Update transfer detection for Copilot types**

**Goal:** Adapt `transfers.py` to use `source_type` column with Copilot's type values.

**Requirements:** R22–R24 from core requirements (transfer detection)

**Dependencies:** Unit 2 (schema rename `teller_type` → `source_type`)

**Files:**
- Modify: `src/finmint/transfers.py`
- Modify: `tests/test_transfers.py`

**Approach:**
- Replace all `teller_type` references with `source_type`
- SQL WHERE clause: remove `teller_type != 'card_payment'` filter. No Copilot equivalent for card payment exclusion
- Scoring logic: replace `teller_type in ("transfer", "ach")` with `source_type == "InternalTransfer"`. Strengthen this to a gate: require at least one side of a candidate pair to have `source_type == "InternalTransfer"` for high-confidence matching. Amount-only matches between two `Regular` transactions can still be considered but should be scored lower (wider false-positive surface without the type signal)
- Candidate dict: rename `"teller_type"` key to `"source_type"`

**Patterns to follow:**
- Existing `transfers.py` — greedy matching algorithm, pair scoring, UUID pair IDs

**Test scenarios:**
- Happy path: Matching debit/credit across accounts within 2 days detected as transfer
- Happy path: `InternalTransfer` type pairs score higher than `Regular` pairs
- Edge case: Same account debit/credit not matched (different accounts required)
- Edge case: Amount mismatch not matched
- Edge case: > 2 day gap not matched
- Edge case: `source_type=None` treated as non-preferred (doesn't crash)
- Happy path: Greedy matching — closest date pairs matched first
- Integration: Detected transfers get Transfer label and `needs_review` status

**Verification:**
- `tests/test_transfers.py` passes with `source_type` column and Copilot type values
- No references to `teller_type` remain in the codebase

---

- [ ] **Unit 6: Simplify accounts TUI to read-only**

**Goal:** Remove add/delete actions from `AccountsApp`. Make it a read-only display of discovered accounts.

**Requirements:** R9

**Dependencies:** Unit 2 (accounts schema)

**Files:**
- Modify: `src/finmint/accounts_tui.py`
- Delete: `src/finmint/enrollment.py`
- Delete: `tests/test_enrollment.py`
- Modify: `tests/test_accounts_tui.py`

**Approach:**
- Delete `enrollment.py` and `test_enrollment.py` entirely
- Remove `ConfirmDeleteScreen` class
- Remove `action_add_account`, `_run_enrollment`, `action_delete_account`, `_on_delete_confirmed` methods
- Remove `"a"` and `"d"` bindings
- Update empty-state message: "No accounts found. Run `finmint token` and sync a month to discover accounts."
- Constructor: remove `config` parameter (no longer needed for enrollment)

**Patterns to follow:**
- Existing `accounts_tui.py` — `_refresh_table()`, DataTable column setup

**Test scenarios:**
- Happy path: Table displays discovered accounts with institution, type, last four, last synced
- Edge case: No accounts shows empty-state message
- Happy path: Quit binding (`q`) still works

**Verification:**
- `tests/test_accounts_tui.py` passes
- No enrollment imports remain
- `enrollment.py` and `test_enrollment.py` are deleted

---

- [ ] **Unit 7: Update CLI commands and status messages**

**Goal:** Update CLI to reference Copilot Money instead of Teller. Wire up `finmint token` command. Clean up status messages.

**Requirements:** R2, R3, R15, R16

**Dependencies:** Unit 3 (token command), Unit 4 (sync changes), Unit 6 (accounts TUI changes)

**Files:**
- Modify: `src/finmint/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`

**Approach:**
- Add `token` command: interactive prompt (use `getpass` or Rich prompt with `password=True`), validate via `copilot.fetch_accounts()`, save via `config.save_token()`
- Update `review` command: status message from "Syncing transactions from Teller..." to "Syncing transactions from Copilot Money..."
- Update `--force-sync` help text: remove "from Teller"
- Update `accounts` command: pass only `conn` to `AccountsApp` (no config needed)
- Update `_ensure_setup()`: if config is missing, run `init_config()` then instruct user to run `finmint token`
- Update `README.md`: replace all Teller references with Copilot Money setup instructions (paste JWT, etc.)

**Patterns to follow:**
- Existing `cli.py` — Typer commands, Rich console output, `_ensure_setup()` pattern

**Test scenarios:**
- Happy path: `finmint token` prompts and stores valid token
- Error path: `finmint token` with invalid token shows error, does not store
- Happy path: `finmint review` status message references Copilot Money
- Happy path: `finmint accounts` works without config parameter
- Error path: Missing config directs user to `finmint token`

**Verification:**
- All CLI tests pass
- No "Teller" references remain in CLI output or README
- `finmint token` is accessible as a command

---

- [ ] **Unit 8: Final cleanup and integration verification**

**Goal:** Remove all remaining Teller references, verify end-to-end flow, ensure no dead code.

**Requirements:** All

**Dependencies:** Units 1–7

**Files:**
- Delete: `src/finmint/teller.py`
- Delete: `tests/test_teller.py`
- Modify: `pyproject.toml` (update description, keep `respx` for `test_copilot.py` httpx mocking)
- Verify: all `src/finmint/*.py` files (including `ai.py` which has a Teller reference in a docstring)
- Verify: all `tests/*.py` files

**Approach:**
- Delete `teller.py` and `test_teller.py` (deferred from Unit 1 to avoid breaking imports between units)
- Update `pyproject.toml` description: remove "Teller API integration" → "Copilot Money integration"
- Grep for "teller", "Teller", "enrollment", "cert_path", "key_path", "mTLS" across entire codebase
- Remove any dead imports, unused variables, or orphaned references
- Verify `pyproject.toml` entry point still works (`finmint.cli:app`)
- Run full test suite

**Test scenarios:**
- Integration: Full test suite passes with zero Teller references
- Integration: `grep -ri teller src/ tests/` returns zero results (excluding git history)

**Verification:**
- Zero Teller/enrollment references in source or test files
- Full test suite green
- CLI entry point works

## System-Wide Impact

- **Interaction graph:** `sync.py` now imports from `copilot` instead of `teller`. `accounts_tui.py` no longer imports from `enrollment`. `cli.py` adds a `token` command. `transfers.py` uses renamed column. `categorize.py`, `ai.py`, `charts.py`, `review_tui.py`, `labels_tui.py`, `rules_tui.py` are unchanged structurally (but `ai.py` has a Teller docstring reference to clean up).
- **Error propagation:** `CopilotAuthError` in `copilot.py` → caught in `sync.py` → displayed in `cli.py` with direction to `finmint token`. This is all-or-nothing (not per-account like Teller). Partial results from committed transactions are preserved.
- **State lifecycle:** Token stored in `config.yaml` (file-level, not DB). `save_token()` introduces a read-modify-write pattern (load YAML, update field, write back) — note that YAML comments in config will be lost on save. Accounts are transient — re-discovered on each sync. Stale accounts (disconnected in Copilot) remain in local DB but stop receiving new transactions. Transactions are durable — keyed on Copilot ID.
- **API surface parity:** No external API consumers. CLI commands are the only interface.
- **Config indirection asymmetry:** `get_token(config)` reads the JWT directly from config, while `resolve_api_key(config)` reads an env var name then resolves it. This is intentional — JWT storage is direct, API key storage is indirect via env var. Both raise `RuntimeError` with actionable messages.

## Risks & Dependencies

- **Copilot API instability**: This is a reverse-engineered, unofficial API. It could change without notice. Mitigation: keep the GraphQL client thin and isolated in `copilot.py` so changes are contained to one file.
- **JWT lifespan unknown**: If tokens expire very quickly (minutes), the manual paste UX becomes painful. Mitigation: discover during implementation, consider caching the browser session if needed (future work).
- **Amount/sign convention mismatch**: If Copilot uses a different sign convention, spending reports will be inverted. Mitigation: verify during implementation by inspecting actual API responses before writing conversion logic.
- **Transaction ID stability**: If Copilot changes transaction IDs across requests, `INSERT OR IGNORE` will create duplicates. Mitigation: verify during implementation that IDs are deterministic.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-31-copilot-money-backend-requirements.md](docs/brainstorms/2026-03-31-copilot-money-backend-requirements.md)
- Reference implementation: github.com/JaviSoto/copilot-money-cli (Rust, 28 GraphQL operations)
- Core requirements: docs/brainstorms/2026-03-30-finmint-core-requirements.md (R1–R43)
- Original plan: docs/plans/2026-03-30-001-feat-finmint-core-cli-plan.md
