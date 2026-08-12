---
type: summary
feature: board-order-and-defects
plan: "[[2026-08-11-board-order-and-defects-plan]]"
status: done
updated: 2026-08-12
links: ["[[board-row-identity]]", "[[lane-stack-board]]", "[[2026-08-10-scrape-gold-recompose-defect]]", "[[data-sourcing-rule]]", "[[gold-store]]", "[[lane-data-availability]]"]
---

# Board order, and the defects behind it

A pool's board position is now a property of **where it is**, not of whether it happens to be open
today. Plus three defects fixed alongside: `scrape-gold` refreshing nothing, the lane owner never
rendering, and an anomaly reported three times that turned out not to be a bug.

## The reported bug

> "when I switch dates order of swimming pools changes, this is non intuitive"

`query.py` sorted **options** by distance. **Statuses were never sorted and carried no distance at
all.** `dayRows` rendered every option row before every status row. So a pool sat distance-ranked
near the top the day it was open and dropped into an unranked tail the day it shut.

**Statuses come from two places**, and this is the trap the plan nearly walked into: 20 of 38 are
emitted inside the facility loop where the distance is already computed; the other 18 come from
`_schedule_less_statuses`, **outside** it, built from a `RosterEntry` rather than a `Facility`. Fixing
only the easy half would have left 18 of 38 rows unranked — the same defect, half-fixed and invisible.
Both halves now carry it, and both mutate independently under test.

## Shape

- **`FacilityStatus.distance_km` / `StatusOut.distance_km`** — the same value an option carries,
  through the shared `service._km_out` so the equality is structural, not two roundings that happen
  to agree. `_distance_km(query, geo)` takes a `GeoPoint` so the roster half can call it.
- **Rule O1** — options keep `(distance_km, session.time.start, facility_name)`; statuses gain
  `(distance_km ?? inf, facility_name)`.
- **Rule O2** — two groups, open first, with a named divider between them. A pool still moves groups
  the day it shuts; the boundary makes that visible instead of silent. Interleaving was the rejected
  alternative.
- **O3** — the divider renders only when both groups are non-empty, and never in Pool mode.
- **O4** — a facility genuinely without geo keeps `None`, sorts last by name, and is never given a
  fabricated 0.
- **`rowHeight(row) = max(ROW_H, 10 × lanes)`** — plan-bearing rows grow so the owner label clears its
  7px gate. `ribbonrender` needed no change; `drawLaneStack` already took `h`.

## What it delivers — measured, and NOT what the plan implied

The plan was framed on "34 of 57 facilities change position". **This does not move that number.**

| | before | after |
|---|---|---|
| facilities changing board position | 43 of 55 | **43 of 55** |
| closed group, stable indices | 17 / 36 | **0 / 36** |

Closed-group indices got *less* stable, because a pool now inserts at its true rank instead of being
appended at an arbitrary slot. That is O2 working as chosen.

What it delivers is that the order became **explicable**. The closed group was never sorted at all —
it was in facility-iteration order:

| closed group | before | after |
|---|---|---|
| first three | Altstetten, Bläsi, Leimbach — all `null` km | Riedtli 1.22, Bäckeranlage 1.27, Letten 1.36 |
| last | Seebad Enge (`null`) | Hallenbad Leimbach **6.07 km** |

Leimbach — the furthest shut pool — was served **3rd of 38**.

## The three defects fixed alongside

**`scrape-gold` refreshed nothing already present.** It re-composed over its own output, so the
stored blob was the "curated" side and won every aspect. It now composes onto the curated tier rebuilt
from `data/`. **The fix opened a second door, and closing it is the real result:** `compose` emits a
facility for every curated pool whether scraped or not, so a pool the catalog *names* but this run
does not scrape had its scraped facts overwritten curated-only, exit 0. `_compose_schedules` now
writes only the pools it resolved an extract for — **the invariant lives in the write, because that is
the only safe narrowing point**. One deliberate deletion path remains: re-pointing a
`lane_plan_source` in `data/` drops the stale plan until the next `scrape-lanes`.

**The owner name never rendered.** [[lane-stack-board]] fixed both `ROW_H = 46` and "owner inline",
which are arithmetically incompatible at six lanes (5.13px bands, gate binds at n ≤ 4). Now verified
on **painted strings** through the compiled board with a realistic 8.5px `measureText`: `ASVZ`,
`Schwimmverein Zürileu`, `Trigether`, `Sportaktiv`.

**The "6 vs 7 lane plans" anomaly is a test-double artifact.** `tests/providers/wfs_snapshot.py`
serves `city-schwimmerbecken.pdf` for **every** `.pdf` URL. The join is URL-keyed so five single-basin
sources bind — to City's plan — and `oerlikon-sprungbecken`'s declared `section` token finds no match
in a header reading `Hallenbad City Schwimmerbecken`. `silver.py` and `belegungsplan.py` are correct.
It also explains why City, Bungertwies and Käferberg were all seen serving identical six-lane views.

## Invariants worth not breaking

- **Both status sources carry a distance.** A change that adds a third source must carry it too; the
  test asserts over the whole answer, per source count, so a missed half fails loudly.
- **`_compose_schedules` writes only what it scraped.** Widening it silently reintroduces the deletion
  door; `compose` cannot be made safe from the caller side.
- **The 7.00px owner band has no margin.** At `10n` the band is exactly 7.00 and the gate admits it.
  Changing `STACK_BOX` (0.8), the 1px separator or `OWNER_LABEL_MIN_H` flips every real basin back to
  unlabelled — each mutation reddens 2–3 tests, so it fails loudly rather than silently.

## What this plan should be remembered for

**Five acceptance criteria across this plan and its predecessor did not discriminate**, and every one
was caught by mutation rather than by reading:

| criterion | why it didn't discriminate |
|---|---|
| "0 within-group moves" | impossible — an insertion shifts every later index |
| "relative order per group" | trivially true — facility iteration order is already stable |
| Pool-mode divider guard | its fixture had options on all seven days |
| `publicSpan` predicate | inverting it left all 466 tests green |
| `... in EXPECTED_LANE_COUNTS` | asserted a literal contains a key written three lines away |

Two agents also **built a fix and then declined to ship it** on hitting a gate — the `scrape-gold`
filename routing, and the lane-plan routing that would have left a pre-change baseline permanently
red. Mutation-testing the *tests*, not just the code, is the practice that earned this plan.

## Entry points

`domain/query.py` — `FacilityStatus.distance_km`, `_status_order`, `_option_order`,
`_schedule_less_statuses` · `apps/web/api/swim/service.py::_km_out` ·
`blocks/board.ts` — `isOpenToday`, `groupByOpenToday`, `dividerIndex`, `appendDivider`, `rowHeight` ·
`blocks/poolrank.ts::rowDistance` · `cli.py::_compose_schedules` ·
`build/compose.py::carry_lane_plans` · `tests/etl/test_lane_attachment_pin.py`

## Backlog

The offline double still serves one sheet for every PDF — fixing it needs filename routing **and** a
decision on `swim_lane_fields_pre_s2.json`, which must move together: regeneration cannot rescue that
baseline, because the generator `git archive`s 659c76a and replays the old double by construction ·
`find_swim_options` at CRAP 26.5 against a 30 gate · the 7.00px band has never been seen in a real
browser · `_schedule_less_statuses` does not apply `query.radius_km` while the in-loop half does
(pre-existing) · `appdata.classifyPools` still derives distance from options only, so the pool-picker
shows no km for a closed pool while the board and phone list now do.
