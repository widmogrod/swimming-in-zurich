---
type: summary
created: 2026-07-19
links: ["[[2026-07-19-ux-ascii-design]]", "[[rich-pool-domain]]", "[[fastapi-service-integration]]"]
---

# UX presentation (glance · tourist · week grid) — what exists now

Implemented 2026-07-19 via /dev:implement (4 slices, all gates green: 143 tests,
coverage 93.79% ≥ 91 floor, mypy strict clean, CRAP clean). Presentation-only — one
self-contained static HTML page in `apps/web/api/ui/router.py` over the existing
`/swim`, `/pools`, `/access-types` responses, plus a thin DTO widening. No new domain
fields were invented; where the UI wanted data the model lacks, it degrades and the gap
is deferred to [[rich-pool-domain]].

## The two governing invariants (the design's backbone)

1. **Three terminal states are never merged:** `open ·closes HH:MM` / `closed` (with reason)
   / `uncurated` ("schedule unknown — NOT closed"). Backed by `statuses` in `domain/query.py`.
2. **Real data is plain; every un-wired/derived value is `[bracketed]` with `~` or `fc`**, and
   busyness is barred from being a sort key. One honesty primitive across all three screens.

Two glyph axes, kept **orthogonal**: access (`≈` lane · `◇` public · `⌂` family · `W` women ·
`S` seniors · `X` reserved · `·` closed) says *what the water is*; eligibility (`✓` in · `✗`
not you · `?` unknown) says *whether it's you*. Shading (`▓░`) is reserved for busyness only.

## What's on the page (three tabs)

- **Find a swim** — ranked cards: fat length badge (+`N lane` sub-line), access+eligibility
  glyphs, the three states, `ⓘ valid_as_of · source` provenance stamp, shared legend.
- **First time here?** (tourist) — primer (pool types by `kind`, how-to-enter, glossary from
  `/access-types`) + 2–3 distance-ranked starter pools, jargon decoded inline, closed pools
  kept visible, km-only (no walk-time). Location = 3-landmark preset dropdown (no geocoder).
- **Plan my week** — read-only days×time grid for the nearest pool, distance-sorted switcher,
  `[fc]` busyness placeholder. Assembled from **7 client-side `/swim` calls** (one per weekday):
  a single `/swim` call already returns the whole day's sessions (the `at` time only sets each
  option's `open_at_query_time` flag; eligibility is time-independent), so no API change.

## DTO surface added

`OptionOut` (`apps/web/api/swim/model.py`) gained `kind`, `length_m`, `lanes`, `source`,
`curated`; `SwimOption` (`domain/query.py`) carries `facility_kind`/`basin_length_m`;
`apps/web/api/swim/service.py` maps them (`Decimal→float`, `PoolKind.value`, provenance).

## Open backlog (tech debt + deferred gaps)

- **Live occupancy wiring** (gap #1) — busyness is a `[fc]` placeholder everywhere; the
  bracketed seams are where real data attaches. Contract in [[rich-pool-domain]].
- **Registry not wired at runtime** — `build_answer` calls `find_swim_options` without a
  registry, so the UNCURATED state renders but is never produced live (invariant #1 only
  half-observable). Wants a dedicated wiring slice.
- **`?` eligibility via JS reason-substring match** — correct today, fragile; a structured
  `determinable` flag on `EligibilityResult` would decouple it from reason copy.
- **Resolver closed-without-reason vs no-data** — some genuinely-closed days render as `?`
  unknown (errs safe: never falsely says "shut"); a structured distinction would tighten it.
- **`Routine` entity** (gap #5) — the week grid's pick-3/save tray is deferred until it exists.
- Per-lane reservations (gap #3), routing/walk-time (gap #4), per-time-of-day busyness curve
  (gap #6), and curated lane-count backfill beyond City.
