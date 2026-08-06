---
type: summary
name: seasonal-hours
created: 2026-08-06
links: ["[[annual-window]]", "[[2026-08-06-seasonal-hours-plan]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# Seasonal hours — what exists now

## A rule can carry a season, and a session a condition

`ScheduleRule` has `season: AnnualWindow | None` and `weather: Weather`
(`ANY | FAIR_ONLY`); `ResolvedSession` carries the weather forward. See
[[annual-window]] for why the window is year-free and what `precision` means.

The resolver filters by season **inside layer 4** — closures, one-off exceptions and
holiday policy are untouched. When every rule on a basin is seasoned and none is in
season, the day is `ClosedDay(ClosureCode.OUT_OF_SEASON)`, never `NO_SESSIONS`
("nothing scheduled this weekday" is a different sentence from "shut for the season").

`OUT_OF_SEASON` is a **distinct code from `SEASONAL_BREAK`**, decided by the owner after
S1 showed why: all five locales render `SEASONAL_BREAK` as *summer* break, which is the
wrong season for a lido. `SEASONAL_BREAK` keeps its curated/notice producer and its
wording; `OUT_OF_SEASON` is worded season-neutrally, because the code derives from the
pool's own window and cannot know which season it is outside.

**Weather is per-session, never per-day.** The two published windows are adjacent and
additive (`end` == `start` in 46 of 46 rows), so a summer day at Heuried is *certainly*
open 09:00–14:00 and *conditionally* open 14:00–21:00. `DaySchedule` is still
`OpenDay | ClosedDay`.

## Which pools are fetched

`etl.scrape.declared_sources` = `kind ∈ {indoor, thermal, school, outdoor, lake, river}`
**and** a URL **no other roster entry shares** → **26** pools (11 before).

Two are excluded by name in `_UNPARSEABLE_OPERATOR_PAGES`: `seebad-enge` and
`freibad-dolder` hold unshared URLs, so the widened gate would admit them, and neither
publishes a parseable table — under fail-fast that aborts the build. They are Gap 7.
The exclusion is permanent and unexpiring: **nothing notices if they start publishing.**

`domain/catalog.freshness_of` still tests only `kind in (INDOOR, THERMAL)`. Widening it
would flip `flussbad-unterer-letten` and `-flussteil` — which share a URL and can never
be declared sources — to `AWAITING_SCRAPE` forever.

## The parser

Format 1 is **element-scoped**: `<stzh-datatable>` regions are read off the raw page via
their `columns`/`rows` attributes and gated on the column header (`Zeitraum` |
`Wochentag`, else inert). The old page-wide `_ROW_RE` adjacency heuristic is gone.

That gate plus **section-scoped** heading attribution fixed a pre-existing leak:
**Hallenbad City was serving its sauna's timetable as pool hours**, because the sauna
heading is emitted *after* its own table inside the same section. City's pool is
`Montag–Sonntag 6–22 Uhr` — one row — and has no women-only session.

Handled: two `Zeitraum` grammars, two indoor grammars (bare `Mai–September` and
parenthesised — the parenthesised form matches on **month names**, not parentheses, or it
would eat maennerbad's `(Sonntag–Freitag)` weekday qualifiers), a `\xa0` continuation row,
weekday-in-cell forms with New Year wrap, EN-dash separators and dot minute separators.

`last_admission_before` has a producer: **23 carriers, all 30 minutes**, anchored on the
*sentence* rather than the footnote marker — 11 carriers use footnote ¹, 2 state it as
bare prose with no marker, and 1 page's ¹ is a daylight caveat with no last-admission at
all. The three non-carriers have no `Einlass` text: honest silence.

## What a user sees

A fair-weather block carries a marker naming its spans on the board row and the phone
card. **The canvas ribbon and day tail do not** — they paint a conditional block exactly
like a guaranteed one, and the ribbon is the primary visual. The qualification is textual
and adjacent (also the row's accessible name). 12 of the 26 scraped pools have a
fair-weather block, so this gap is broad.

The detail panel carries no marker either: it receives a `/pools/{id}` payload and never
the `/swim` option list, so it has no per-session row. On both phone and desktop the
card/row stays visible alongside the panel.

## Known gaps

- **The ribbon does not encode the conditional** (`blocks/ribbonmodel.ts` has no
  `weather`). Text-only honesty.
- `weather` is a bare `str` client-side, so an unknown future value degrades to
  *guaranteed* rather than to *unknown* — the wrong direction, though peer-conformant.
- The phone verdict bolds *"until 21:00"* unqualified while the marker beneath qualifies
  that same span.
- **mythenquai's per-area hours are dropped and recorded nowhere.**
  `Täglich ab 7 Uhr geöffnet` is open-ended and `TimeRange` requires `start < end`. A real
  loss against "we shouldn't compress information"; the raw-layer plan is where an
  unparsed cell gets a home.
- **Live WFS has drifted and it is not absorbed**: `schulschwimmanlage-isengrind` is
  renamed *Wolfsblick* (a pool_id change) and `maennerbad-schanzengraben`'s URL moved off
  sportamt.ch. Builds tolerate both; the next `build-catalog` re-snapshot must decide them.
- That URL move also means **Männerbad alone among the newly admitted pools carries the
  city tariff** while its city-run siblings carry `None` — correct value, arbitrary
  application. For the price plan.
- The dead-slug repair in `_normalize_roster_url` is pinned against fixtures only; nothing
  asserts the live slug still 404s.
