---
type: concept
name: ios-resolved-export
status: draft
updated: 2026-08-23
links: ["[[2026-08-23-native-ios-app-plan]]", "[[gold-store]]", "[[data-layer-architecture]]", "[[session-access]]"]
---

# iOS resolved export

A **derived projection** of the [[gold-store]] in which every date inside a fixed forward horizon
(400 days from the build date) has already been resolved into concrete sessions, day statuses,
notices and warnings. Produced offline by
`swimzh export-ios` (no network — it reads gold only) and written atomically, like every other
store this project emits.

Gold remains the single source of truth. The export stands to gold the way `data/catalog.json`
stands to the WFS: a snapshot for a consumer that cannot run the pipeline. It is never read by
`apps/web/**`, and nothing may be true in the export that is not derivable from gold.

## Why it exists

`domain/resolver.py` — the correctness core — composes closures, exceptions, the season gate,
public-holiday policy and school-term scope to answer *"what is open on this date?"*. `resolver.py`
is 166 lines, but the modules that must agree with it — `query.py` (841), `access.py` (435),
`lane_plan.py` (392), `calendar.py` (96), `holiday.py` (67), `pricing.py` (58) — total 2,055 lines
inside a 3,076-line `domain/` package, and iOS cannot run any of it. Baking the answers keeps one
implementation of the core instead of two that must be kept in agreement every week.

## The seam it defines

Baked (date-dependent): sessions, day statuses, closure codes, notices, warnings, lane day views
(incl. their coverage), feature hours, prices, identity.

Runtime: `eligibility` and `price_for` (person-dependent), `haversine_km` (place-dependent), and
the lane/open-now derivations (clock-dependent — comparing the wall clock to a *baked* window is
not a date rule, and baking it per minute would be absurd).

No date-dependent RULE may be evaluated on the client — if the client needs to know whether a date
is a school holiday, the seam has been violated.

## The honest horizon

`ZurichCalendar.covers()` is year-bounded, but `find_swim_options` does **not** withhold answers
outside coverage — it appends a warning and serves (`query.py:581-585`). The export matches that
behaviour rather than a stricter one: it bakes a fixed **400-day** horizon from the build date and
carries the identical coverage warning on every out-of-coverage date, so the iOS client never shows
"unknown" where the web shows real options.

The obligation this creates is operational, not architectural: `data/calendar/zurich.yaml` must
gain the next year before the seeded years stop covering the horizon, or a growing share of baked
days ship warned. The export report counts those days so the signal is visible at build time.

Beyond `horizon_end` the client renders an explicit "beyond the published horizon" state — never
"closed", and never an empty list. That is the same invariant which protects schedule-less pools,
applied along the time axis.
