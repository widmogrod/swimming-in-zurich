---
type: plan
status: approved         # owner-approved 2026-07-20 (the "continue" after A/B/C = sign-off, incl. reversing S4's whole-batch abort)
created: 2026-07-20
feature: resilient-reconcile
gates:
  qa: full               # ruff, format, mypy strict, pytest+coverage floor (95), CRAP
  review: adversarial
pause_after: []
links: ["[[techdebt-remediation-roadmap]]", "[[2026-07-19-pool-identity-unification]]", "[[data-layer-architecture]]"]
---

# Plan D — Resilient reconcile

## Context

Roadmap debt **#3**: `scrape-gold`'s `resolve_all` aborts the WHOLE batch (a loud `Err`) on any single
unmatched WFS name — one bad name discards all ~29 good scrapes. This reverses the S4
"whole-batch-abort is stronger" decision **for the benign case only**: an ambiguous hint (would attach
to the WRONG pool) stays structurally fatal; a benign no-crosswalk miss (a name that matches no pool)
becomes reportable, not fatal. Owner sign-off given (the "continue" after A/B/C).

## Design (signature altitude)

- `build/reconcile.resolve_all(extracts, crosswalk) -> Result[ReconcileOutcome, ProviderError]`.
- `ReconcileOutcome(resolved: tuple[Keyed, ...], unresolved: tuple[str, ...])` — `unresolved` is a
  **required** field (a caller cannot silently swallow a miss). A benign miss (no crosswalk entry for a
  `Name`/`Xref`) lands in `unresolved`; an **ambiguous** resolution (a ref that maps to >1 pool) stays a
  hard `Err` — never-attach-to-wrong-pool is preserved by type.
- `cli.scrape_gold` composes only the `resolved` aspects, writes via `write_schedules`, prints the
  `unresolved` list to stderr, and exits non-zero **iff** `unresolved` is non-empty (still visible, not
  silent) — but the good scrapes are written.

## Out of scope

- Changing `attach_lane_plans` / `scrape-lanes` (its ambiguous-hint discipline is unchanged).
- Any change to the ambiguous-is-fatal rule.

## Slices

- **D1 — `resolve_all → ReconcileOutcome`.** *(M)* Change `resolve_all` to return
  `Result[ReconcileOutcome, ProviderError]`: collect benign misses into a required `unresolved`, keep
  ambiguous as a hard `Err`. Update `build/reconcile.py` + its unit tests.
  **Acceptance:** a batch with one benign-miss ref returns `Ok(ReconcileOutcome)` with that name in
  `unresolved` and the rest in `resolved`; an ambiguous ref returns `Err`; existing all-resolve callers
  still get every pool; QA green.
  **Depends on:** —

- **D2 — Wire `scrape-gold` to partial success.** *(M)* Rewire `cli.scrape_gold` to
  `compose(resolved)` + `write_schedules`, print `unresolved` to stderr, exit non-zero iff non-empty.
  **Acceptance:** a CLI test with one unmatched + several matched names writes the matched pools to
  `pool.facility_doc` (partial success), reports the unmatched name, and exits non-zero; an ambiguous
  name still aborts with a typed `Err` and writes nothing; QA green.
  **Depends on:** D1

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| —    | —     | —      | —          | —         | —             |

## Decisions & divergences

- **2026-07-20 — Open-question #3 resolved (owner "continue").** Partial-success scrape is accepted:
  benign misses are reported + non-zero exit, ambiguous stays structurally fatal (never a wrong-pool write).

## Summary

Written at `done`; distilled into `docs/summaries/resilient-reconcile.md`.
