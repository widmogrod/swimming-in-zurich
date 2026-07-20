---
type: summary
feature: resilient-reconcile
status: done
created: 2026-07-20
links: ["[[techdebt-remediation-roadmap]]", "[[data-layer-architecture]]"]
---

# Resilient reconcile — partial-batch scrape, ambiguous stays fatal

**What & why.** Roadmap debt #3: `scrape-gold`'s `resolve_all` aborted the whole batch on any single
unmatched WFS name, discarding all the good scrapes. Now benign misses are reported (not fatal) while
an ambiguous hint (wrong-pool hazard) stays structurally fatal.

## What exists now

- **`resolve_all -> Result[ReconcileOutcome, ProviderError]`** where `ReconcileOutcome(resolved,
  unresolved)` has a **required** `unresolved` field (no silent swallow). A typed
  `_Matched/_NotFound/_Ambiguous` classification (`assert_never`) makes the split structural:
  `Name`/`Xref` are dict lookups → can only be `_NotFound` (→ `unresolved`); only a `BasinHint` can be
  `_Ambiguous` (→ hard `Err`). Never-attach-to-wrong-pool holds by construction.
- **`cli.scrape_gold`** composes `outcome.resolved` + `write_schedules` unconditionally (matched pools
  are written even amid misses), prints the `unresolved` list to stderr, and exits non-zero iff any are
  unresolved. The ambiguous `Err` branch still aborts writing nothing.

## Notes

- Scrape extracts are `Name`-only, so a CLI-level ambiguous scrape is impossible by construction; the
  ambiguous abort is proven at the reconcile seam (D1) and at the CLI `Err` branch via a shape-identical
  monkeypatched error (D2).
- The `scrape-gold` success summary counts pools actually written (`len(resolved)`), truthful under
  partial success.

Reverses the S4 "whole-batch-abort is stronger" decision for the benign case only (owner sign-off). See
[[2026-07-20-resilient-reconcile-plan]] for the ledger.
