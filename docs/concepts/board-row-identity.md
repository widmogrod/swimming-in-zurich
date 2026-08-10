---
type: concept
created: 2026-08-09
links: ["[[2026-08-09-lane-stack-board-plan]]", "[[basin]]", "[[lane-data-availability]]", "[[2026-07-19-ux-ascii-design]]"]
---

# Board-row identity — what one row of the board is about

**Stub, created with [[2026-08-09-lane-stack-board-plan]]. Fill in once S3 lands.**

A board row was a **pool**: `dayRows` (`apps/web/static/js/blocks/board.ts`) grouped a
`/swim` answer by `option.facility`, and every ribbon for that pool stacked into one
46 px row. That held while a row carried only opening hours, because a pool's hours are
a facility-level fact.

It stops holding once a row carries **lane load**. A lane plan describes one basin — City
publishes a Belegungsplan for its Schwimmerbecken and (eventually) its Variobecken, and
Oerlikon binds two basins today. A lane stack drawn on a row labelled "Hallenbad City"
would attribute one basin's six lanes to a four-basin pool. So a row becomes a
**facility + basin** pair, keyed by `option.basin_id`.

**Labelling (rule L1).** The label is the pool name; the `· <basin>` suffix is appended
**only when that facility contributes options from more than one basin in this answer**.
A single-basin pool therefore reads exactly as it does today. Because the rule is
per-answer, a pool's label can differ between days — a basin that resolves `ClosedDay`
drops the pool back to one option-bearing basin.

**A label is for humans, never a key.** That day-dependence is only safe because every
row-to-pool lookup goes through `row.facility` / `row.basin_id`. Matching on `row.label`
fails silently and precisely for multi-basin pools; `app.ts`'s selection restore and
`appdata.ts::rowFacilityName` both did exactly that before this change.

The asymmetry to keep straight: a `StatusOut` (closed, `awaiting_scrape`, `no_source`,
`open_unscheduled`) names a facility and **no basin** — there is no schedule to attribute
to any particular water. So a status-only pool stays exactly one facility-level row, and
only pools that produce options split per basin. A pool must never render both at once
for the same fact. Pool mode (`weekRows`) is unaffected: its rows are days, not pools.
