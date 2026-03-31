---
date: 2026-03-30
topic: finmint-core
focus: Terminal-based personal finance tool with Teller API, AI categorization, and merchant rules
---

# Ideation: Finmint Core Features

## Codebase Context
- Greenfield Python 3.11+ CLI project — no code exists yet
- Tech stack: Typer, Rich, httpx (mTLS for Teller), SQLite, Pandas, Matplotlib, Claude API
- Local-first, single-user, open-source from day 0
- Config at ~/.finmint/ (YAML), DB at ~/.finmint/finmint.db
- Core commands: `finmint 3-2026`, `finmint view 3-2026`, `finmint view 2026`, `finmint labels`, `finmint accounts`

## Ranked Ideas

### 1. Merchant Memory — Local Rules That Compound Over Time
**Description:** Store a merchant-to-category lookup table in SQLite. Normalize merchant strings and check the table before calling Claude. Learn from every human correction. `finmint rules` to view/edit/add merchant mappings.
**Rationale:** 80%+ of transactions hit repeat merchants. After 3 months, most API calls and review time disappear.
**Downsides:** Merchant name normalization is messy (bank-specific formats). Rules can conflict.
**Confidence:** 95%
**Complexity:** Medium
**Status:** Explored — selected for brainstorm 2026-03-30

### 2. Confidence-Gated Review — Only Show What Needs Human Eyes
**Description:** Every categorization gets a confidence score. High-confidence items auto-accepted. Only uncertain/novel transactions surface in review. Tunable threshold.
**Rationale:** Turns 30-minute review into 5-minute exception check.
**Downsides:** Silent auto-acceptance can hide errors.
**Confidence:** 90%
**Complexity:** Low
**Status:** Unexplored

### 3. Drift Detection — Automatic Spending Anomaly Alerts
**Description:** Compare each category against trailing 3-month rolling average. Surface outliers in `view` command.
**Rationale:** Lifestyle creep is invisible without explicit comparison.
**Downsides:** Needs 3+ months of data.
**Confidence:** 90%
**Complexity:** Low
**Status:** Unexplored

### 4. Recurring Transaction Fingerprinting & Subscription Tracker
**Description:** Detect recurring charges by matching merchant + amount + cadence. `finmint subscriptions` shows monthly burn and lifetime cost.
**Rationale:** Auto-discovers forgotten subscriptions. Lifetime cost reframing changes psychology.
**Downsides:** Fuzzy matching needed for price changes.
**Confidence:** 85%
**Complexity:** Medium
**Status:** Unexplored

### 5. Ghost Budget — Velocity Warnings Without Setup
**Description:** Track daily spending velocity per category. Warn mid-month if pace exceeds last month. No config needed.
**Rationale:** Behavioral nudge without budget-setting overhead.
**Downsides:** No explicit targets means no accountability.
**Confidence:** 80%
**Complexity:** Low
**Status:** Unexplored

### 6. Time-Travel Diffing — Compare Any Two Periods
**Description:** `finmint diff 3-2025 3-2026` with category-by-category comparison, colored Rich output, AI narration.
**Rationale:** Comparison is the killer query for personal finance.
**Downsides:** Category changes over time can make comparisons inconsistent.
**Confidence:** 80%
**Complexity:** Low-Medium
**Status:** Unexplored

### 7. Transaction Annotations — Capture Context at Review Time
**Description:** Optional freetext notes on transactions during review. Searchable via `finmint search`.
**Rationale:** Context decays fast; the review step is the one moment you remember what a charge was.
**Downsides:** Can feel like friction if not clearly optional.
**Confidence:** 85%
**Complexity:** Low
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Natural language queries | Scope creep for v1 |
| 2 | Spending heatmap calendar | Lower priority than core workflow |
| 3 | Time-to-earn reframing | Nice-to-have display option |
| 4 | Transaction splitting | Complex UX in CLI; later addition |
| 5 | Regret scoring | Niche, adds friction |
| 6 | Shadow accounts / simulator | Too ambitious |
| 7 | Financial decision simulator | Depends on too many other features |
| 8 | Monte Carlo projections | Premature for v1 |
| 9 | Daemon/cron sync | Changes core workflow paradigm |
| 10 | Append-only journal / CRDT | Over-engineered for single-user |
| 11 | Adversarial AI two-pass | Doubles API cost for marginal gain |
| 12 | Fuzzy time references | UX detail, not standalone idea |
| 13 | Teller connection health | Niche operational concern |
| 14 | Retroactive re-categorization | Feature detail, not standalone |
| 15 | Commitment contracts / budgets | User wants tracker, not budgeting app |

## Session Log
- 2026-03-30: Initial ideation — 48 generated across 6 frames, 22 unique after dedupe, 7 survived filtering
- 2026-03-30: Idea #1 (Merchant Memory) selected for brainstorm alongside full project scope
