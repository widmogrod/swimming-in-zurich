---
type: summary
created: 2026-08-09
links: ["[[2026-08-08-sharedsource-fanout-plan]]", "[[shared-source]]", "[[admission]]", "[[annual-window]]", "[[discovery-driven-providers]]"]
---

# SharedSource fan-out

One page states three facts about thirteen pools; the fan-out carries them
without inventing a fourteenth. See [[shared-source]] for the entity.

## What exists

- **`OpenUnscheduledDay`** — `DaySchedule`'s third variant: open per a
  page-stated season, hours unpublished, `weather` required (the season
  gate passing `operating_season.weather` is its only producer). Every
  `DaySchedule` match ends in `assert_never`, enforced by an AST meta-test
  with a self-trap.
- **The season gate** — in `resolve_hours`, between exceptions and holiday
  policy: outside the facility window → `ClosedDay(OUT_OF_SEASON)`; inside
  with no rules → `OpenUnscheduledDay`. Inert for any facility without an
  `operating_season` (regression-pinned).
- **`parse_planschbecken`** — pure parser over a committed fixture that is
  byte-identical to its HTTP-cache entry (CRLFs preserved — materialize
  fixtures with binary writes). Reads only page-level lead prose (accordions
  stripped structurally): Mai–September at `MONTH` precision, `je nach
  Wetter` → `FAIR_ONLY`, `kostenlos` → `Free()`. Removal pins enforce
  stated-never-assumed; the three join-rejection measurements (Josefwiese
  heading, Föhrenwald absent, 12 accordion items) are committed tests.
- **The shared phase** — `shared_sources` admits a URL only when ≥2 roster
  entries share it AND a parser is registered (today: planschbecken.html,
  13 members; hallenbaeder.html excluded — no parser). One fetch per page,
  one identity-free extract per member (`basins=()`, so reconcile can never
  mint an id), one `ScrapeFailure` for the whole set. A registered page
  with <2 sharers emits an audit note rather than vanishing.
- **The store & wire** — exactly 13 blobs carry `operating_season`, all 13
  `admission_state: "free"` (citywide free: 17; split 21/17/19 literal-SQL
  checkable). `/swim` serves `open_unscheduled` with params
  `{weather, season_start_month, season_end_month, season_precision}` (day
  keys only at DAY precision); January yields `closed` +
  `out_of_season`. `/pools/{id}` carries the season; `freshness` stays
  `no_source` — it describes the timetable, and a Planschbecken has none.

## Known limits

Per-aspect provenance doesn't exist: the 13 blobs serve scrape-derived
facts under seed provenance (`source="catalog"`) — accepted, cited to the
pool-identity plan's deferral. The per-pool accordion blurbs stay unread
(fuzzy join measured and rejected). `flussbad-unterer-letten` remains an
identity-aliasing question, not a fan-out one.
