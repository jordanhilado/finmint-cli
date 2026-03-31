---
date: 2026-03-31
topic: copilot-money-backend
---

# Backend Pivot: Teller API to Copilot Money GraphQL

## Problem Frame

Finmint currently depends on the Teller API with mTLS certificates for fetching bank transactions. This creates significant setup friction (obtaining certs, managing enrollment flows) and ties Finmint to a specific banking aggregator. Jordan already has a Copilot Money subscription with all bank accounts connected. By reverse-engineering Copilot Money's web GraphQL API, Finmint can pull transaction data from an existing, actively-maintained connection — eliminating mTLS complexity and the enrollment flow entirely.

## Requirements

**Authentication & Token Management**

- R1. User authenticates by manually pasting a JWT bearer token obtained from Copilot Money's web app (browser dev tools → Network tab → copy `Authorization` header value).
- R2. `finmint token` command accepts the JWT via interactive prompt (not as a CLI argument, to avoid shell history exposure) and stores it in `~/.finmint/config.yaml`.
- R3. On any API call that returns an `UNAUTHENTICATED` GraphQL error, Finmint displays a clear message: token is expired, run `finmint token` to paste a new one.

**Copilot Money GraphQL Client**

- R4. Finmint communicates with Copilot Money via `POST https://app.copilot.money/api/graphql` with the JWT as a `Bearer` token in the `Authorization` header.
- R5. The client supports the following GraphQL operations: `Accounts` (list all connected accounts), `Transactions` (fetch transactions with cursor-based pagination).
- R6. Cursor-based pagination is handled automatically — Finmint fetches all pages for a given query until no more results remain.

**Account Discovery**

- R7. On sync, Finmint queries Copilot Money's `Accounts` operation and automatically creates or updates local account records in SQLite. No manual account enrollment or selection required.
- R8. Account records store: Copilot account ID, institution name, account type, last four digits (if available), and last sync timestamp.
- R9. The `finmint accounts` command becomes a read-only list view showing discovered accounts and their last sync date. Add/enroll/delete operations are removed.

**Transaction Sync**

- R10. `sync_month` fetches transactions from Copilot Money for all discovered accounts within the requested month's date range.
- R11. Transactions are mapped to Finmint's existing data model: ID (Copilot transaction ID), account_id, amount (converted to integer cents), date, description (merchant name), normalized_description.
- R12. Copilot Money's own categories, tags, and review status are discarded — Finmint handles all categorization independently via its rules engine and Claude AI.
- R13. Upsert logic uses `INSERT OR IGNORE` keyed on Copilot transaction ID, same as today's Teller sync behavior.

**Impact on Existing Requirements**

- R14. Requirements R29 (browser enrollment with local callback server), R30 (account list with Teller-specific fields), and R31 (account deletion via Teller API) from the core requirements doc are superseded by R7-R9 above.
- R15. R37 (config.yaml) changes: Teller cert paths are removed, replaced by Copilot Money token storage. Claude API key config remains unchanged.
- R16. R38 (first run setup) changes: no longer prompts for Teller cert paths. Prompts for Copilot Money token via `finmint token` flow and Claude API key env var.
- R17. R42 (secrets handling) changes: Copilot Money JWT replaces Teller sandbox token. Same security principle — read from config file, never hardcoded, excluded from git.

## Success Criteria

- A user with a Copilot Money subscription can go from `pip install` to seeing transactions in under 5 minutes (paste token, run `finmint 3-2026`).
- Transaction sync for a month with ~100 transactions completes in under 10 seconds (no mTLS handshake overhead).
- Token expiry is handled gracefully with a clear, actionable error message.
- All existing categorization, review, and visualization features work identically with Copilot Money data.

## Scope Boundaries

- **Copilot Money is a data pipe only** — no importing of Copilot's categories, tags, budgets, or recurring items.
- **No Playwright or browser automation** — token acquisition is manual.
- **No Copilot Money write operations** — Finmint never mutates data in Copilot Money.
- **No multi-provider support** — this fully replaces Teller, not augments it. Teller code is removed.

## Key Decisions

- **Manual token paste over Playwright automation**: eliminates a heavy dependency (Playwright + browser binaries), keeps the tool lightweight. Acceptable trade-off since token refresh is infrequent.
- **Ignore Copilot categories entirely**: Finmint's value proposition is its own rules engine + AI categorization. Importing Copilot categories would create confusing dual-source behavior.
- **Auto-discover accounts**: since Copilot already manages bank connections, there's no reason for Finmint to gate which accounts sync. Simplifies the UX.
- **Store token in config file (not keychain)**: consistent with existing config approach, avoids OS-specific keychain APIs. Token file is already gitignored via `~/.finmint/` exclusion.

## Dependencies / Assumptions

- Jordan maintains an active Copilot Money subscription with bank accounts connected.
- Copilot Money's GraphQL API remains stable enough to use (no versioning guarantees since it's reverse-engineered).
- JWT tokens have a reasonable lifespan (hours to days) so manual refresh isn't needed per-session.

## Outstanding Questions

### Deferred to Planning

- [Affects R4][Needs research] What exact GraphQL query structure does the `Transactions` operation use? Need to inspect the specific fields, pagination parameters (`first`, `after`), and filter arguments (date range).
- [Affects R5][Needs research] What exact GraphQL query structure does the `Accounts` operation use? Need field names for institution, account type, last four, etc.
- [Affects R11][Technical] How does Copilot Money represent transaction amounts? Need to confirm whether they're floats, strings, or cents, and the sign convention for debits vs. credits.
- [Affects R6][Technical] What are the cursor-based pagination semantics? Does it use `edges`/`nodes`/`pageInfo` (Relay-style) or something custom?
- [Affects R1][Needs research] How long do Copilot Money JWT tokens typically last before expiring? This affects how often users need to re-paste.
- [Affects R14][Technical] What's the cleanest migration path for removing Teller-specific code and DB columns while preserving existing transaction data?

## Next Steps

-> `/ce:plan` for structured implementation planning
