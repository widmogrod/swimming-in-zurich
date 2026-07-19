---
type: plan
status: in-progress      # draft -> approved -> in-progress -> done (owner approved 2026-07-19: all 4 slices, no pause)
created: 2026-07-19
feature: ux-presentation
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: []          # owner chose to run S1..S4 back-to-back (2026-07-19)
scope: presentation only # data model shapes live in [[rich-pool-domain]]; this plan maps data -> pixels
links: ["[[rich-pool-domain]]", "[[basin]]", "[[feature]]", "[[fastapi-service-integration]]"]
---

# Plan — UX / ASCII presentation design (glance · week-planner · tourist)

Design produced by 3 UX sub-agents (one per persona) → 1 design-lead synthesis agent.
This is the **presentation** companion to [[rich-pool-domain]] (which defines the data
*shapes*); here we decide how that data reaches three swimmer personas as glanceable,
**honest** monospace/HTML screens.

## Context

`/swim` already answers "where can I swim?" with eligibility-annotated options, `closed` vs
`uncurated` statuses, warnings, and notices; the catalog lists all ~57 pools (7 indoor with
real schedules). The product is terminal-first / minimal-HTML, so the design language is
monospace ASCII: no color, no images, glanceable, and — the load-bearing constraint —
**honest about data it does not have** (live occupancy is modeled but not wired).

Three personas were designed for:
1. **Glance Swimmer** — decide where to swim *right now* in seconds.
2. **Week Planner** — find the best recurring lap windows across the week near home.
3. **Tourist** — a newcomer who needs the vocabulary, not a grid.

## The governing principle (adjudicated)

All three designs independently converged on two invariants; the synthesis makes them law:

| # | Invariant | Why |
|---|-----------|-----|
| 1 | **Three terminal states are never merged**: `open` · `closed` (with reason + reopen date) · `uncurated` ("schedule unknown — NOT closed"). | Conflating "we don't know" with "it's shut" strands a swimmer at a locked door. Backed by `statuses` in `query.py`. |
| 2 | **Real data is plain; every un-wired/derived value is `[bracketed]` with `~` or `fc`.** Busyness is barred from being a top sort key while it is a placeholder. | The shared failure mode across all three drafts was invented signals (busyness, walk-time, best-window, per-lane counts) borrowing the visual authority of real fields. One honesty primitive, learnable once. |

Two glyph axes, kept **orthogonal** so one grid serves every persona:
- **Access** (what the water *is*): `≈` lane/Bahnen · `◇` public/Öffentlich · `⌂` family ·
  `W` women-only · `S` seniors · `X` school/club reserved · `·` closed.
- **Eligibility** (whether it's *you*, resolved from gender/age): `✓` in · `✗` not you · `?` unknown.

Shading (`▓░`) belongs to **busyness only** — access is letter-coded so no cell ever blends
two shaded meanings.

```text
┌─ swimzh legend ─────────────────────────────────────────────────────────┐
│ ACCESS   ≈ lane   ◇ public   ⌂ family   W women   S seniors   X resvd  · closed │
│ FOR YOU  ✓ in     ✗ not you  ? unknown                                   │
│ STATUS   OPEN ·closes HH:MM    CLOSED ⊘ reason+reopen    UNCURATED ? unknown│
│ BUSY     [~quiet] [~fair] [~busy]   ▓▓▓▓▓░░░░░ [fc]   (forecast, not live)│
│ PROV     ⓘ valid_as_of DATE · source · (curated|scraped)                  │
└──────────────────────────────────────────────────────────────────────────┘
```

## Screen 1 — Glance Swimmer (consolidated hero)

A ranked list of "go here" cards. The immutable physical fact (length + lanes) is a fat
left badge — the thing lap swimmers filter on hardest, readable in a quarter-second.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  swimzh · swim now         Sun 19 Jul 14:32  ⌖ Zürich HB  ≤5km        ⚙  │
│  filter: ▸lane ○public ○any    sort: [best now] distance price           │
└──────────────────────────────────────────────────────────────────────────┘

╔════════╗  Hallenbad City                       OPEN · closes 18:00 (3h28)
║  50 m  ║  ≈ LANE SWIM now  ✓ open to all              1.2 km · CHF 8
║ 6 lane ║  ─────────────────────────────────────────────────────────────
╚════════╝  busy [~busy] ▓▓▓▓▓▓▓░░░ [fc — not live]
            X 14:00–15:30  club reserved (SC Zürich)   ⚠ blocks some water
            amenities: sauna · 1m Sprungbrett · Hubboden          [ open › ]

╔════════╗  Hallenbad Oerlikon                    OPEN · closes 21:00 (6h28)
║  25 m  ║  ≈ LANE SWIM now  ✓ open to all              3.4 km · CHF 8
║ 8 lane ║  busy [~quiet] ▓▓▓░░░░░░░ [fc — not live]
╚════════╝  amenities: sauna · Nichtschwimmerbecken (kids)        [ open › ]

┄┄ not shown as options ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  ⊘ Hallenbad Altstetten   CLOSED — Revision (annual) until 02 Aug
  ? Hallenbad Leimbach     UNCURATED — schedule unknown, NOT closed
──────────────────────────────────────────────────────────────────────────
  ⓘ schedules valid as of 18 Jul 2026 · stadt-zuerich.ch (scraped)
    busyness is forecast/placeholder — live occupancy not wired yet
```

Detail drill-down adds a today-timeline with stacked swimlanes (lane / club-reserved /
women-only on a time axis with a `▼ now` marker) + notices + holiday policy + provenance.
Design decision from synthesis: **"best window today" and per-lane arithmetic were removed
from the hero card** — both derive from un-wired occupancy, so they must not be the most
prominent lines. Reservations degrade honestly to `X … ⚠ blocks some water`.

## Screen 2 — Week Planner (weekly grid)

Days = columns, time = rows, distance-sorted pool switcher on top. A "pick 3 slots" tray
turns comparison into routine-building; filters re-rank pools by *usable recurring slots*.

```text
┌─ swimzh · PLAN MY WEEK ──────────────────── you: ♀ 34 · 8003 Wiedikon ─┐
│ Week of Mon 20 Jul 2026   Pools: ● City 0.9km  ○ Bungertwies 1.4  …    │
│ Filter: [✓ lap only] [ ] show reserved  [ ] eligible-to-me only        │
├───────────────────────────────────────────────────────────────────────┤
│  HALLENBAD CITY · 0.9 km · Schwimmerbecken 50m, 6 lanes                │
│  time │ Mon   Tue   Wed   Thu   Fri   Sat   Sun                        │
│  06:30│ ≈✓    ≈✓    ≈✓    ≈✓    ≈✓    ·     ·      3 free lanes/6 [fc]  │
│  09:00│ X     X     X     X     X     ◇✓    ◇✓     school Mo–Fr        │
│  17:00│ X     ≈✓    X     ≈✓    X     ◇✓    ◇✓     club Mo/We/Fr       │
│  19:00│ ≈✓    ≈✓    ≈✓    ≈✓    W✗    ◇✓    ·      Fri 19:00 women     │
│  ⓘ data valid_as_of 2026-07-18 · scraped                              │
├───────────────────────────────────────────────────────────────────────┤
│  MY WEEK (pick 3)  1. City Mon 06:30 ≈  2. City Wed 06:30 ≈  3. ____   │
│                    coverage: Mon ✓  Wed ✓  Fri ✗   [save routine]      │
└───────────────────────────────────────────────────────────────────────┘
```

One glyph pair per cell (`access` + `eligibility`); busyness moves to a per-row `[fc]`
caption rather than a second shaded glyph inside the cell (fixes the draft's `≈:`
two-per-cell overload). A two-pool overlay compares the same time band side by side.

## Screen 3 — Tourist (orientation-first)

The newcomer's blocker is vocabulary, not search. Lead with a plain-language primer, then
2–3 hand-picked starter pools where every jargon term is decoded inline.

```text
┌─ swimzh ───────────────────────── Zürich indoor swimming, for visitors ─┐
│  Staying near: [ Zürich HB ]  Radius: [3km]   You: age[34] gender[any]  │
├──── FIRST TIME HERE? ───────────────────────────────────────────────────┤
│ POOL TYPES  Hallenbad=indoor all-year · Freibad=outdoor summer · See/Fluss│
│ TO ENTER    Walk in, pay in CHF at the door. No booking, no card.        │
│ TO BRING    Swimsuit + towel. Lockers on site.                           │
│ THE SLOTS   Bahnenschwimmen=lap ✓ · Öffentlich=public ✓ · Frauenbad=women│
│             only ✗ · Schule/Verein=reserved ✗                            │
├──── 3 STARTER POOLS NEAR YOU ───────────────────────────────────────────┤
│ ① Hallenbad City      0.4 km  ● OPEN NOW → Öffentlich until 20:00  ✓     │
│    50 m Olympic, 6 lanes + sauna.  CHF 8/4/6.  busy ~moderate [FORECAST] │
│ ② Hallenbad Bungertwies 1.1 km ✕ CLOSED 11–31 Jul (Sommerpause) reopens 1 Aug│
├─────────────────────────────────────────────────────────────────────────┤
│ ⚠ Only 7 of ~57 pools have verified timetables. Others = "unknown", NOT closed.│
└─────────────────────────────────────────────────────────────────────────┘
```

Detail screen leads with a **"CAN I SWIM RIGHT NOW? → YES ✓"** box, lists basins (each with
its own schedule), a "typical weekday" primer, and a **Data honesty** panel linking the
official page. Closed pools stay visible and distance-ranked (a tourist at a locked door is
the worst outcome); `[hide closed]` / `[open now]` are opt-in, off by default.

## Data → UI mapping (shared)

| UI element | Field | Status |
|---|---|---|
| Length/lane badge | `Basin.length_m`; lane count | length real; **lane count parsed from prose** — see gap #2 |
| `OPEN ·closes HH:MM` | `ResolvedSession` time range; `open_at_query_time` | real |
| Access glyph `≈◇⌂WSX·` | `SessionAccess` union | real |
| `✓ ✗ ?` for-you | `eligibility(person).allowed` + reason | real |
| distance / walk-time | `distance_km` from `lat/lon` | km real; **walk-time faked** — gap #4 |
| price CHF | `prices` by age | real |
| busyness bar / `[~fair]` | `Occupancy.percent_full` … | **NOT WIRED** — always `[fc]` — gap #1 |
| `X … blocks some water` | `ClubReserved`/`SchoolReserved` overlap | tag real; **per-lane count faked** — gap #3 |
| CLOSED / reopen date | `closures`, `statuses(closed)` | real |
| UNCURATED | `statuses(uncurated)` | real |
| notices, holiday policy | `notices`, `public_holiday_policy` | real |
| freshness / source | `provenance.valid_as_of` / `source` / `curated` | real |
| "pick 3 / save routine" | — | **no backing entity** — gap #5 |

## Data-model gaps the UI needs (prioritized)

Several are already in flight in [[rich-pool-domain]] — noted inline.

1. **Wire live occupancy** (`percent_full`/`people`/`measured_at` via `crowdmonitor_keys`).
   Highest impact; every persona fakes "how busy". Contract already designed in
   [[rich-pool-domain]] (decision #4: `LiveOccupancy | OccupancyUnavailable`, freshness
   derived) — this is the ETL/wiring slice. Until wired, `[fc]` treatment is mandatory.
2. **Structured `Basin.lane_count`** — anchors the glance badge and the planner ranking;
   today parsed best-effort from prose. Tracked under [[rich-pool-domain]] basin attributes.
3. **Per-lane / partial-session reservations** — `ClubReserved`/`SchoolReserved` optionally
   carrying a lane subset, so "4 of 6 lanes clubbed" becomes expressible. Medium effort,
   highest-value nuance for the lap-swimmer persona. **New** — not yet in the domain plan.
4. **Walk / transit time + routing** — tourist view fabricates "6 min walk" from km.
   Either integrate routing or **show km only**. Cheapest fix is removal until real.
5. **`Routine` entity** (user + recurring slots + coverage check) — the planner's "pick 3 /
   save" has no store. Ship manual "pick 3 + save" first; defer any auto-optimizer.
6. **Per-time-of-day busyness curve** — detail sparklines imply a daily curve that doesn't
   exist even as forecast. Follow-on once historical occupancy (#1) accumulates.

## Slices

Each slice is one vertical increment through the FastAPI service (`[[fastapi-service-integration]]`
conventions) + its tests, taken fully through the QA + adversarial-review gates before the next.
Presentation-only: no domain-model field is invented here — where the badge wants data the model
lacks (lane count), the slice **degrades gracefully** and the gap is deferred to [[rich-pool-domain]].

- **S1 — Glance screen: honest states + length badge + unified legend.** *(pause after)*
  Surface `basin.length_m` and `facility.kind` through the swim service into `OptionOut` (the
  only new plumbing — length exists on `Basin` but the API does not expose it). Rewrite the
  "Find a swim" results as ranked cards: fat length badge, access glyph (`≈◇⌂WSX·`) + separate
  eligibility axis (`✓✗?`), the three never-merged terminal states (open `·closes HH:MM` /
  `closed` with reason / `uncurated`), the `ⓘ valid_as_of · source` provenance stamp, and the
  shared legend. No busyness element yet (not in the `/swim` response — nothing to bracket).
  Lane count degrades to length-only until S2. Tests: `test_swim` for the new fields; a UI
  smoke test asserting the three states render distinctly.

- **S2 — Typed lane count feeds the badge.** Add `Basin.lane_count: int | None` (parsed from
  `description` prose), surface it to `OptionOut`, render `N lane` in the badge. **Coordinate
  with [[rich-pool-domain]]** — if that plan lands lane count first, this slice becomes wiring
  only. Closes gap #2.

- **S3 — Tourist orientation screen.** New UI tab: the plain-language primer (pool types,
  how-to-enter, slot glossary keyed off `/access-types`) + 2–3 distance-ranked starter pools
  with jargon decoded inline and closed pools kept visible. Static teaching copy over current
  data; **walk-time is not rendered** (gap #4 — km only) until routing exists.

- **S4 — Week planner grid (read-only).** New UI tab: days×time grid for the nearest pool with
  the unified access+eligibility glyphs, distance-sorted pool switcher, `[fc]` busyness caption
  placeholder. Read-only — the "pick 3 / save routine" tray is **deferred** to gap #5
  (`Routine` entity), out of scope for this presentation plan. May need a multi-day query path
  (7× resolver) — flag as a discovery if `/swim`'s single-moment contract proves insufficient.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| 2026-07-19 | S1 | done | added `OptionOut.source`/`.curated` beyond the two named fields — required to render the provenance stamp honestly (in-scope per S1's stamp deliverable) | uncurated state renders but `build_answer` calls `find_swim_options` without a registry, so it is never produced at runtime (honest scaffolding); `?` eligibility detected in JS by reason-substring match, not a structured flag | yes |
| 2026-07-19 | S2 | done | field is the domain's existing `Basin.lanes` (parsed from prose by [[rich-pool-domain]]), not a new `lane_count` — exactly the plan's "wiring only" branch | only City's curated 50m basin carries a real lane count today; other curated basins degrade to length-only (data-curation backfill, not a code gap) | no |
| 2026-07-19 | S3 | done | mockup's free-text "Staying near" realized as a 3-landmark preset dropdown (Zürich HB / Bellevue / Zürichhorn, real lat/lon) — no geocoder in the domain | location presets are hardcoded landmark coords (a geocoding port is future work); closed/uncurated pools come from `statuses` which carry no distance, so they stay visible but can't be distance-ranked | no |

## Decisions & divergences

**2026-07-19 — S1 (approved by critic, non-blocking suggestions carried forward):**
- **Registry not wired at runtime.** The UNCURATED terminal state is rendered in the page but
  `build_answer` (`apps/web/api/swim/service.py`) calls `find_swim_options` without a `registry`,
  so `query.py` never emits uncurated statuses live. Invariant #1 (three never-merged states) is
  present in source but only half-observable. Wiring the registry is data-plumbing beyond S1's
  presentation-only scope — deferred; worth a dedicated slice or a [[rich-pool-domain]] follow-up.
- **`?` eligibility via substring match.** The unknown-eligibility axis is detected in JS by
  matching reason substrings (`determine eligibility` / `confirm admission`). Correct today (critic
  traced all `access.py` reasons), but fragile if reason copy changes. A structured tri-state on
  `EligibilityResult` (e.g. `determinable: bool`) would remove the fragility — deferred (domain
  change, touches the correctness core).
- **Cosmetic legend drift:** code renders `CLOSED ⊘ reason` vs the plan mockup's `reason+reopen`;
  `AdultsOnly` maps to `◇` (public) glyph. Accepted as-is.
