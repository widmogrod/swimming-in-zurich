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


## The published contract (added by S5)

A store is not only a file the build produces; once it can be **downloaded**, it is an interface.
`swimzh export-ios --manifest --url <URL>` emits `manifest.json` beside the store, every field read
back out of the finished store rather than remembered:

```
{schema_version, built_at, horizon_end, url, sha256, bytes}
```

`make ios-release` produces both in one run and **requires** `IOS_STORE_URL` — a manifest with no URL
is refused (exit 2) rather than given a placeholder, because a placeholder is a URL that silently
fails at 3 a.m.

**`schema_version` is the brick guard.** It is `2` as of S5 (the `pool.baditicker_poiid` column), and
`tests/scripts/test_ios_schema_version.py` joins the Python constant to the Swift literal so the two
languages cannot drift. A client **rejects** any store whose version is not its own — on download and
on adoption — and keeps serving the one it has. A bad upload must never brick an installed app, and
the bundled store is the floor that makes that possible.

**A downloaded store is validated exactly like the bundled one**, in this order, each step
separately provable: byte length → sha256 → the **not-WAL** header byte (a WAL file opens fine and
fails on the first *prepare*) → `PRAGMA integrity_check` → `schema_version` from the store's own
`meta` → `sqlite_stat1` **row count**. That last one is not pedantry: `ANALYZE` always *creates*
`sqlite_stat1`, so checking the table exists proves nothing.

**The swap is atomic and closes first.** `FileManager.replaceItemAt` exchanges the *file* while an
open connection still holds a descriptor to the **old inode** — a live reader would go on serving the
previous data with no error to reveal it. So every connection is closed before the swap and reopened
after. The temp file lives in Application Support, not `tmp`: `replaceItemAt` requires the same
volume, and `Caches`/`tmp` are system-purgeable and must never hold the only copy.

## The one live seam (added by S5)

The export is offline by construction, and the client's *offline* guarantee is structural: a lint
asserts that **no file in either iOS target** references `URLSession`, `Network`, `NWConnection` or
`CFSocket` — except exactly two, `Live.swift` and `Refresh.swift`, keyed by path so a new
`App/Live.swift` cannot squat the name. Narrowing that lint rather than deleting it is what keeps
"this app works offline" a checkable claim instead of a hope.

Through that seam the client reads **water temperature** (Baditicker, a 2-minute in-process TTL
matching the web runtime). A reading is a fact about **one instant**: its age is derived at render and
never stored, a stale reading is flagged rather than shown as current, and an absent reading is an
explicit state — never zero, never blank.

**Occupancy is deliberately absent**, not degraded. `data/sources.md` defers CrowdMonitor pending
vendor terms, and the crowdmonitor crosswalk keys are display names rather than protocol uids.
Building a crowd badge would quietly advance an integration the owner deferred on legal grounds, so
the client renders **no row at all** — an "unavailable" row would imply a source that does not exist.
