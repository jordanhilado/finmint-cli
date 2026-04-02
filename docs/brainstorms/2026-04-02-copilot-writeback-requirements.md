---
date: 2026-04-02
topic: copilot-writeback
---

# Copilot Money Write-Back Sync

## Problem Frame

Finmint currently reads transaction data from Copilot Money but stores all categorizations, notes, and review status locally in SQLite. This means the work done in finmint's TUI — categorizing transactions, marking them reviewed, adding notes — never reaches Copilot Money. Users must duplicate effort or accept that Copilot Money remains uncategorized. The goal is to make finmint a lightweight UX wrapper that pushes all user actions back to Copilot Money immediately, so the platform stays in sync.

## Requirements

**Categories from Copilot Money**

- R1. Fetch the user's existing categories from Copilot Money via a `Categories` GraphQL query and store them locally as the label set.
- R2. Remove the 16 hardcoded default labels and local label creation/rename/delete. Categories are managed in Copilot Money only.
- R3. The label picker in the review TUI shows Copilot Money categories (with icon/emoji if available).

**Write-Back: Category Changes**

- R4. When a user changes a transaction's category in the TUI (via accept or change), finmint immediately fires a `SetTransactionCategory` mutation to Copilot Money.
- R5. Auto-categorizations (from rules or AI) are NOT pushed to Copilot Money. They only sync after the user explicitly reviews/accepts the transaction in the TUI.

**Write-Back: Review Status**

- R6. When a user accepts a transaction (marks it reviewed) in the TUI, finmint immediately fires a `MarkTransactionReviewed` mutation to Copilot Money.
- R7. The "exempt" action remains local-only — Copilot Money has no equivalent concept.

**Write-Back: Notes**

- R8. When a user adds or edits a note in the TUI, finmint immediately fires a `SetTransactionNote` mutation to Copilot Money.

**Sync Enhancements**

- R9. During sync, also fetch each transaction's existing Copilot Money category, reviewed status, and note — so finmint reflects the current state from the platform.
- R10. During sync, fetch categories from Copilot Money and upsert them into the local labels table (keyed on Copilot category ID).

**Error Handling**

- R11. Mutation failures must not crash the TUI. Show a notification/warning and keep the local DB update intact (eventual consistency).
- R12. If a mutation fails with an auth error, suggest re-running `finmint token`.

## Success Criteria

- A category change made in finmint's TUI is immediately visible in the Copilot Money web app.
- A note added in finmint appears in Copilot Money within seconds.
- Marking a transaction reviewed in finmint marks it reviewed in Copilot Money.
- The category picker shows the user's actual Copilot Money categories, not hardcoded defaults.
- Mutation failures degrade gracefully — the TUI continues working, local state is preserved.

## Scope Boundaries

- **No new features** — this enhances existing review, categorize, and note workflows to sync back.
- **No category creation from finmint** — categories are managed in Copilot Money's UI.
- **No batch push command** — mutations fire immediately on user action.
- **No syncing of tags, budgets, or recurring items** — only categories, notes, and review status.
- **Labels TUI becomes read-only** — users can view categories but not create/rename/delete them.

## Key Decisions

- **Replace local labels with Copilot categories**: Eliminates dual-source confusion. Copilot Money is the source of truth for categories.
- **Immediate sync over batch**: Each user action fires a mutation right away. Simpler mental model, no "unsaved changes" state.
- **Auto-categorizations only sync after review**: Prevents AI/rule mistakes from polluting Copilot Money. User must explicitly accept.
- **Exempt stays local-only**: No Copilot Money equivalent, and it's a finmint workflow concept.
- **Graceful degradation on mutation failure**: Local DB always updates; Copilot sync is best-effort with user notification.

## Dependencies / Assumptions

- Copilot Money's GraphQL API supports mutations for setting category, note, and reviewed status (confirmed via JaviSoto/copilot-money-cli reference project, but exact signatures need discovery).
- The same JWT bearer token used for queries works for mutations.
- Copilot Money categories have an ID field that can be used as a stable foreign key.

## Outstanding Questions

### Resolve Before Planning

(None — all product decisions resolved.)

### Deferred to Planning

- [Affects R1, R4, R6, R8][Needs research] Exact GraphQL mutation and query signatures must be reverse-engineered via browser DevTools or the JaviSoto/copilot-money-cli Rust source code.
- [Affects R9][Technical] What fields does the Copilot Money transaction object expose for category, reviewed status, and note? Need to update the Transactions query.
- [Affects R2][Technical] Migration strategy for existing local databases that have the 16 default labels with transactions referencing them.
- [Affects R4][Technical] Best approach for non-blocking mutations in Textual TUI (run_worker vs threading).

## Next Steps

→ `/ce:plan` for structured implementation planning
