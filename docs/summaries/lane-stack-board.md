---
type: summary
feature: lane-stack-board
plan: "[[2026-08-09-lane-stack-board-plan]]"
status: done
updated: 2026-08-11
links: ["[[board-row-identity]]", "[[lane-data-availability]]", "[[lane-plan-url-binding]]", "[[lane-reservations]]", "[[2026-08-10-scrape-gold-recompose-defect]]"]
---

# Lane-stack board

Lane load reaches the board. A pool that publishes a Belegungsplan renders **one row per basin**,
painting **one hairline sub-row per lane** across the day — public vs reserved, with that session's
best-public window banded behind. Seven basins across six pools qualify, and per
[[lane-data-availability]] that is the permanent ceiling, not a backlog.

## The defect this fixed

The board's proportional encoding was never removed — `ribbonmodel.ts` had always computed
`thickness = public_lanes / lane_count`. It rendered flat because **no `/swim` option carried a lane
plan**: `etl/scrape.py` mints a synthetic `<pool>-main` "Hauptbecken" holding the facility timetable,
while the curated lane basin holding the Belegungsplan carried no rules — so `query.py`'s Decision-#5
gate (`if not basin.rules: continue`) skipped it and it never produced a session. Data starvation, not
a UI regression.

## Shape

- **The join** (`build/compose.py::_carry_bindings`) — a carried lane basin inherits the timetable of
  the single rules-bearing scraped basin. `_session_option` needed **zero** change: its existing
  `isinstance(basin.lane_plan, LanePlan)` branch simply starts firing. **I1** fails the build loudly
  if a facility ever presents more than one rules-bearing scraped basin. **I2** adds only `rules` —
  `basin_id`, `name`, `lanes`, `dimensions`, `lane_plan_source`, `lane_plan` are untouched.
  Reached from `build` (atomic), **not** from a `scrape-gold` re-layer — see
  [[2026-08-10-scrape-gold-recompose-defect]].
- **The wire** — `SwimOption`/`OptionOut` gained `basin_id`, `lane_day_view` (per-lane strips with
  owners; `lane_timeline` only ever carried counts) and `lane_best_public`. The four DTOs are declared
  in `swim/model.py`, **not** shared with `/pools` (D1).
- **`best_public_time(plan, weekday, within=None)`** — `/swim` passes `session.time`; `/pools` passes
  nothing and keeps whole-day semantics. Identically-shaped `PublicWindowOut`, deliberately different
  meaning, documented in four places.
- **The row** ([[board-row-identity]]) — `dayRows` keys on `facility + NUL + basin_id`. Rule **L1**:
  the `· <basin>` suffix appears only when a facility contributes options from more than one basin
  *in this answer*, so single-basin pools are byte-identical to before. **I3**: a `StatusOut` names no
  basin, so a status-only pool stays one facility-level row. **I4**: Pool mode unchanged.
- **The paint** — `ribbonmodel.ts` decides the variant (`lanestack` / `lanes` / `unpublished`),
  `ribbonrender.ts::drawLaneStack` paints it. The stack is clipped to the option's own hours, because
  `lane_day_view` spans the weekday and two options of one basin share a row canvas.

## Invariants worth not breaking

- **I5 — three states stay three pictures.** A thin stack, an absent stack, and "lane split not
  published" must never look alike; ~50 of 57 pools will never have a plan and none may read as "no
  lanes free". `drawUnpublishedRibbon` keeps its capacity sheath.
- **I6 — a label is for humans, never a key.** Under L1 a multi-basin pool's label changes per answer,
  so any code keying on `row.label` fails *silently* and fails precisely for the pools this feature
  serves. Six such sites were converted (`app.ts` ×2, `poollist.ts` ×4); a whole-tree sweep confirmed
  no seventh. Row identity goes through `facility` / `basin_id`.
- **`drawLaneStack` deliberately drops `r.family`** and colours by lane-freeness. Safe *only* because
  every plan-bearing session measured is `PublicSwim` (1351/1351 over 200 dates). A `WomenOnly` lane
  session would paint teal under a legend reading "open to the public" — the exact lie `ACCESS_FAMILY`
  exists to prevent. Documented at the site.

## Known gap — the owner name does not render

Variant C was chosen for "which lane, **and whose**". `ROW_H = 46` over six lanes gives **5.13px**
bands and the label gate binds at **n ≤ 4**; City has 6, Oerlikon 8. The plan fixed both `ROW_H` and
"owner inline" and those are arithmetically incompatible — a defect in the plan, not the code. The
7px gate is *permissive*, not conservative: `OWNER_FONT` is 8.5px. Owners remain one click away in the
DetailPanel Gantt. Three options are recorded in the plan's Decisions; **undecided**.

## Measurements worth keeping

- Variant distribution on shipped data over 60 days: **415** `lanestack`, **686** `unpublished`,
  **0** `lanes`. The `lanes` branch is defensive-only — do not delete it, `poolrank.ts` and
  `insightbar.ts` still read `lane_timeline`.
- Real Belegungspläne tile a session completely: the uncovered fraction of every stack box is
  **0.000** across 60 days × six pools, so a gap is never painted as "not public".
- Before `lane_best_public` was bounded: **346 of 672** options carried a window outside their own
  session hours; **111** contradicted their own timeline peak. After: 0 and 0.

## Entry points

`build/compose.py::_carry_bindings` · `domain/query.py::_session_option` ·
`domain/lane_plan.py::best_public_time(within=)` · `apps/web/api/swim/model.py` ·
`blocks/board.ts::dayRows`/`applyLabelRule`/`rowBasinName` · `blocks/poolrank.ts::rowKey` ·
`blocks/ribbonmodel.ts::laneStackFor` · `blocks/ribbonrender.ts::drawLaneStack`/`laneBands` ·
`blocks/cursor.js::isPublicSegment`

## Backlog

Owner-label decision (above) · `poollist.ts:61` is a **third** independent definition of a row-label
format · `gantt.ts:133` and `detailpanel.ts:114` still inline their own PublicSwim test instead of
`isPublicSegment` · three fixture baselines (S1/S2/S4) are hand-generated by uncommitted scripts ·
Pool-mode multi-basin rows and the phone-specific treatment (research variant D) remain out of scope
and now have real data behind them.
