---
type: plan
status: done             # both slices on main 2026-07-20; see Summary
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
| 2026-07-20 | D1 | done | none — `resolve_all -> Result[ReconcileOutcome, ProviderError]` (`unresolved` required); a typed `_Matched/_NotFound/_Ambiguous` classification (`_classify` + `assert_never`) makes ambiguous-vs-not-found STRUCTURAL — never-attach-to-wrong-pool holds by construction (only `BasinHint` can be ambiguous; `Name`/`Xref` are dict lookups). `resolve`'s public `Ok\|Err` behavior is unchanged | interim `cli.scrape_gold` shim keeps pre-D1 whole-batch-fail behavior (D2 rewires to real partial success). Discovery: scrape extracts are `Name` only → never ambiguous by construction → D2's ambiguous-aborts test needs a `BasinHint`/seeded-ambiguous crosswalk | no |
| 2026-07-20 | D2 | done | none — `cli.scrape_gold` composes `outcome.resolved` + `write_schedules` UNCONDITIONALLY (partial success), reports `unresolved` to stderr, exits 1 iff non-empty; the ambiguous `Err` branch still aborts writing nothing. Ambiguous was tested at the CLI `Err` branch via a monkeypatched `resolve_all` returning the exact typed error a real ambiguous ref produces (critic-verified shape-identical) — a CLI-level ambiguous scrape is impossible by construction (scrape emits `Name` only) | none — the success summary now counts written pools (`len(resolved)`), truthful under partial success | no |

## Decisions & divergences

- **2026-07-20 — Open-question #3 resolved (owner "continue").** Partial-success scrape is accepted:
  benign misses are reported + non-zero exit, ambiguous stays structurally fatal (never a wrong-pool write).

## Summary

**Done — `scrape-gold` survives a benign miss; ambiguous stays structurally fatal.** Both slices on
`main` (`c3bc632` D1, plus D2); 348 tests, 95.67% coverage, mypy strict + CRAP green.

- **D1** — `resolve_all -> Result[ReconcileOutcome, ProviderError]`; `ReconcileOutcome(resolved,
  unresolved)` with `unresolved` required. A typed `_Matched/_NotFound/_Ambiguous` classification makes
  the benign-vs-ambiguous split structural: `Name`/`Xref` dict-lookups can only miss (→ `unresolved`),
  only a `BasinHint` can be ambiguous (→ hard `Err`) — so never-attach-to-wrong-pool holds by
  construction, not convention.
- **D2** — `cli.scrape_gold` writes the matched pools via `write_schedules` even when some refs are
  unresolved, reports the misses to stderr, and exits non-zero iff any are unresolved. The ambiguous
  `Err` branch still aborts writing nothing.

One unmatched WFS name no longer discards the whole batch. Backlog: **E** (calendar pyright) is the last
roadmap item.

