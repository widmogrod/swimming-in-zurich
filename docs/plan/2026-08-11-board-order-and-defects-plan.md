---
type: plan
status: in-progress      # owner approved 2026-08-11;
branch: plan/board-order-and-defects
worktree: .claude/worktrees/plan-board-order-and-defects
base_branch: feat/new-ui draft -> approved -> in-progress -> done
created: 2026-08-11
feature: board-order-and-defects
gates:
  # TWO chains, both required. `make qa` CANNOT see the vitest .ts suites — the pytest bridge
  # (apps/web/tests/test_static_js.py) pins discovery to `**/*.test.js` to exclude them, so
  # `make qa` can go green with every TypeScript test failing.
  qa: "make qa && (cd apps/web/static/js && npm run qa)"
  review: adversarial
  max_rounds: 2
pause_after: [S1]        # S1 (scrape-gold) changes what a refresh writes for every pool; run riskiest first
links: ["[[lane-stack-board]]", "[[board-row-identity]]", "[[2026-08-10-scrape-gold-recompose-defect]]", "[[data-sourcing-rule]]", "[[gold-store]]", "[[2026-07-19-ux-ascii-design]]"]
---

# Plan — stable board order, and the defects behind it

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-11**

> when I switch dates order of swimming pools changes, this is non intuitive ; number of lanes ui is fine but you still shoudl address issues and defects

## Context

[[lane-stack-board]] shipped, and testing it surfaced a defect older than that plan: **a pool's
position on the board is decided by whether it happens to be open that day, not by where it is.**
Measured against `gold_db` with the place the UI actually sends (`PLACE_PRESETS[0]`, Zürich HB —
`app.ts:78-82,121`, always emitted as `lat`/`lon` by `api.ts:105-107`): Wed 2026-08-12 → Thu
2026-08-13, **34 of 57 facilities change position** (33 of 57 at row level); Schulschwimmanlage
Tannenrauch moves **15 → 41** purely because it is open on one day and closed on the other.

*(An earlier revision of this plan cited 37 of 58 and 21 → 39. Those reproduce only with **no**
`lat`/`lon`, where every `distance_km` is null — a configuration no user is ever in, since the app
seeds a place on load. Corrected here rather than silently: the defect is real either way, but a
measurement taken in a state the product cannot reach is not evidence about the product.)*

Cause, in two halves. `query.py:633` sorts **options** by `(distance_km, session start,
facility_name)` — stable. **Statuses are never sorted and carry no distance at all**
(`FacilityStatus` has no such field). `dayRows` then renders every option row first and every status
row after. So a pool distance-ranked near the top on Wednesday lands in an unranked tail on Thursday,
and everything downstream shifts.

This was foreseen and abandoned once: [[2026-07-19-ux-ascii-design]]'s S3 ledger records *"closed /
uncurated pools come from `statuses` which carry no distance, so they stay visible but can't be
distance-ranked."* The field was missing, so the ranking was dropped.

**Statuses come from two places, and only one of them is easy.** `_distance_km(query, facility)` is
already computed at `query.py:550` in the facility loop that emits *closed* statuses — 20 of 38 on
2026-08-12. The other 18 come from `_schedule_less_statuses(facilities, roster)` at `query.py:631`,
**outside** that loop: it takes no `query` and builds each `FacilityStatus` from a `RosterEntry`, not
a `Facility`. Fixing only the easy half would leave 18 of 38 closed rows with `distance_km: None`,
sorted into O4's unranked tail — the very defect this plan exists to remove, half-fixed and
invisible. `PoolCatalogEntry.geo` exists (`domain/catalog.py:35`) and all 57 roster entries carry
it, so the fix is to thread the query into that helper too.

The owner also asked for the remaining recorded defects in the same pass: the `scrape-gold`
silent-staleness bug ([[2026-08-10-scrape-gold-recompose-defect]]), the owner-name gap left open by
[[lane-stack-board]] S4, and two small items its ledger recorded.

## Design (signature altitude)

### Row order — a stable key, and one honest divider

```python
# domain/query.py
@dataclass(frozen=True, slots=True)
class FacilityStatus:
    ...
    distance_km: float | None = None      # NEW — same value the options carry

statuses.sort(key=lambda s: (s.distance_km if s.distance_km is not None else inf, s.facility_name))
```

```ts
// blocks/board.ts — dayRows keeps its two groups, both distance-ordered
// NO new field: which group a row is in is exactly `row.options.length > 0` — `board.ts:196-207`
// records that status facilities and option facilities are disjoint on shipped input. A stored
// `openToday` could desync from the rows it describes; a helper cannot.
export function isOpenToday(row: BoardRow): boolean
```

**Rule O1 — position is a property of geography, never of today's outcome.** Options keep their
existing key `(distance_km, session.time.start, facility_name)` (`query.py:633`); statuses gain
`(distance_km ?? inf, facility_name)`. Note the option key breaks ties on *session start*, so two
basins of one pool order by earliest session — latent, not live (0 flips measured over 60 days), but
it is the real key and this plan does not change it.

**Rule O2 — the two groups stay, and the boundary is named.** Open rows first, then a labelled
divider, then closed / schedule-less rows. A pool still moves between groups on the day it shuts —
that is a real change in the world — but the move is now *explained by a visible boundary* instead of
being a silent re-sort. This preserves "what can I use today" as the scannable top block, which
interleaving would have cost.

**Invariant (O3):** the divider is rendered only when both groups are non-empty. An empty group must
never leave a dangling header — the same never-merged-states discipline the three terminal states
already carry.

**Invariant (O4):** a status with no geo keeps `distance_km: None` and sorts last within its group,
by name. It is never given a fabricated distance — an unknown position is not zero.

### `scrape-gold` — re-layer from sources, not from the store

Today `scrape_gold` does `curated = GoldRepository(conn).load_all()` then `compose(curated, scraped)`
and writes back, so on a re-layer the previously-composed blob **is** the curated side:
`_has_schedule(curated_basins)` is true, `_merge_basins` takes curated-wins-wholesale, and the fresh
scrape is discarded. All ten `_ASPECTS` are `CURATED_WINS`, so the same feedback silences prices,
closures, notices, lockers, rentals and geo too. Exit code 0, no signal.

Fix = option 2 from the defect report, the only listed option short of a full re-architecture that
fixes **both** basins and aspects:

```python
def scrape_gold(*, db_path: Path, data_dir: Path, catalog_path: Path, ...) -> int:
    """Re-layer: compose the freshly scraped aspects onto the CURATED TIER REBUILT FROM `data/`,
    never onto the store's own previous output."""
```

**Invariant (S-1):** `compose` is never called with its own output as an input. The curated side
comes from `data/`; the scraped side from this run. Re-running the phase twice with the same source
data yields a byte-identical store.

**Invariant (S-2):** an empty or failed scrape must not delete what a previous run wrote — the fix
trades silent staleness for a *risk* of silent deletion, so that risk is pinned. **No new type is
introduced:** `cli.py:320-331` already aborts fatal on a declared-source failure and on
`not report.extracts`, and the phase runs inside `atomic_swap(db_path, seed_from=db_path)`
(`cli.py:591`) which commits only on a non-fatal outcome (`cli.py:600-603`). The property already
holds; S2 pins it as a regression rather than building a `Facts | NothingFound | Failed` sum type
and threading it through `write_schedules` and both callers.

### The owner name — height is the constraint, so height is the fix

At `ROW_H = 46` a six-lane stack gives 5.13px bands and the label gate binds at `n <= 4`, so the
owner never renders on City (6) or Oerlikon (8) — the arithmetic behind [[lane-stack-board]]'s known
gap. The band must clear ~7px against an 8.5px font:

```
band = ROW_H * 0.8 / n - 1 >= 7   →   ROW_H >= 10 * n
```

```ts
// blocks/board.ts
export function rowHeight(row: BoardRow): number   // max(ROW_H, 10 * lane_count), ROW_H when no plan
```

Feasible because each row already builds **its own canvas** (`board.ts:621`) and its label cell sizes
off the same constant (`board.ts:560`). Against the seven real lane plans, `max(46, 10n)` gives:

| basin | lanes | height |
|---|---|---|
| Oerlikon 50m | 8 | **80** |
| City Schwimmerbecken | 6 | **60** |
| Bläsi 25m, Leimbach 25m | 5 | **50** |
| Bungertwies, Käferberg | 4 | 46 (unchanged) |
| Oerlikon Sprungbecken | 2 | 46 (unchanged) |

So **4 of 7 rows grow**, three stay — and every row without a plan is untouched.

**Invariant (H1):** the shared timescale is unchanged. Row *height* varies; the x-axis, the cursor
overlay and the axis header must stay aligned to the pixel, because a Gantt/board desync is the
single hardest correctness property this UI has (`gantt.ts` throws without an injected timescale).

## Out of scope

- **Interleaving closed pools with open ones.** Considered and rejected by the owner: it costs the
  scannable "what's open" block. O2 is the chosen shape.
- **A cursor-following readout on the board.** The alternative to H1 for the owner name; `board.ts`
  carries no pointer handler today, so it is a new interaction surface and its own plan.
- **Normalizing the gold store.** [[data-sourcing-rule]] settles this as amend-not-reverse; the
  `scrape-gold` fix here is the write-door half, not the schema half.
- **Pool-mode multi-basin rows**, and the phone-specific lane treatment (research variant D).
- Re-opening `lane_best_public`'s session bound, or the `lanes` ribbon variant.

## Slices

### S1 — a re-layer actually refreshes

- **Goal**: `scrape-gold` composes onto the curated tier rebuilt from `data/`, so re-running it
  changes what changed and nothing else.
- **Touches**: `src/swimzh/cli.py` (`scrape_gold` gains `data_dir`; the arg parser), the curated
  assemble path it reuses from `build`, `src/swimzh/build/compose.py` (only if `_merge_basins`'
  branch comment needs correcting), `tests/test_cli.py`.
- **Acceptance**:
  1. **The defect's own reproduction, inverted.** With a mutated page fixture (`6–22 Uhr` →
     `7–21 Uhr`), a `scrape-gold` re-layer against an already-built store changes the stored rules.
     Today it does not — this test must fail before the fix.
  2. **A non-basin aspect too** — a mutated tariff changes the stored price. The defect report's
     option 4 warns that a basins-only guard passes while prices stay frozen.
  3. Idempotence (S-1): running the phase twice with unchanged sources yields a byte-identical store.
  4. An empty or failed scrape leaves prior content unchanged (S-2) — no silent deletion.
  5. `docs/2026-08-10-scrape-gold-recompose-defect.md` gains a resolution note; `README.md`'s warning
     is removed.
  6. Both chains green.
- **Depends on**: —
- **Risk**: changes what a refresh writes for every pool, and the failure mode it replaces was
  silent. Hence the pause.

### S2 — a pool sits in the same place every day

- **Goal**: row position is a property of distance, and the open/closed boundary is visible.
- **Touches**: `domain/query.py` (`FacilityStatus.distance_km`, status sort), `apps/web/api/swim/model.py`
  (`StatusOut.distance_km`), `apps/web/api/swim/service.py`, `blocks/board.ts` (`dayRows` grouping +
  `openToday`), the board's row rendering (the divider), `blocks/poolrank.ts` /
  `blocks/poollist.ts` (`rowDistance` reads statuses), `locales/*` (the divider's label),
  `blocks/board.test.ts`, `blocks/poolrank.test.ts`, `apps/web/static/js/appdata.test.ts`.
  **Also `domain/query.py::_schedule_less_statuses` (`query.py:754-787`)** — it must take the query
  and read `RosterEntry.geo`, or 18 of 38 statuses keep no distance.
- **Acceptance**:
  1. **The reported defect, pinned as RELATIVE ORDER — not as indices.** For a fixed pair of dates
     against `gold_db` with a stated place, the facilities common to both answers appear in the
     **same relative order** within each group. Identical *indices* are unachievable and must not be
     asserted: a pool crossing the boundary shifts every later index in the destination group, which
     O2 concedes is a real change in the world. (Simulated against the store: relative order holds
     `True` for both groups, while 14 of 18 open-group and 36 of 36 closed-group indices move.)
  2. **Both status sources carry a distance.** No status for a geo-bearing facility ships
     `distance_km: None` — asserted over the whole answer, so the `_schedule_less_statuses` half
     cannot be missed. A facility genuinely without geo keeps `None`, sorts last in its group by
     name, and is never given a fabricated 0 (O4).
  3. The divider renders only when both groups are non-empty (O3) — pinned for both empty cases.
  4. `StatusOut.distance_km` for a closed facility matches the value an option for that facility
     carries on a day it is open.
  5. **Both surfaces rank on the same key, inside their own grouping.** `poolrank.ts` keeps its four
     tiers (`now`/`soon`/`closed`/`unknown`, `poolrank.ts:155-166` — its header records why: "a phone
     list IS the answer, and a bad sort is a wrong answer"); this plan does NOT collapse them. What
     must change is `rowDistance` (`poolrank.ts:247-252`), which reads only
     `row.options[].distance_km` and so leaves a status-only row at `Infinity` however much
     `StatusOut` gains — it must read `statuses[].distance_km` too. Asserted: a status-only row sorts
     by its real distance within its tier.
  6. Both chains green.
- **Depends on**: —

### S3 — the owner name renders

- **Goal**: a plan-bearing row is tall enough to carry its owner labels; every other row is unchanged.
- **Touches**: `blocks/board.ts` ONLY — `rowHeight`, `drawRow`'s `const h = ROW_H` (`board.ts:413`),
  the label cell (`:560`) and canvas sizing (`:624-626`). **`ribbonrender.ts` needs no signature
  change**: `drawLaneStack` already takes `h` (`ribbonrender.ts:365-372`, via `drawRibbons`
  `:488-496`) and never sees `ROW_H`, which is board.ts-private. Plus `blocks/board.test.ts`,
  `blocks/ribbonrender.test.ts` (two shipped tests encode S3's opposite — `:164` "the row does not
  grow to fit the stack" and `:226-231` "every real Zürich basin"; both use a local `H = 46` so they
  keep passing, and both must be superseded explicitly). `blocks/daytail.ts` must NOT grow.
- **Acceptance**:
  1. City's 6-lane row and Oerlikon's 8-lane row each render **named owners**; a no-plan row keeps
     `ROW_H = 46` byte-identical to today.
  2. `rowHeight` is pure and tested at n = 1..10 including the 46 floor.
  3. **H1, pinned where it can actually break.** An x-for-a-minute cannot differ between a 46px and
     an 80px row — `ts.X` takes no height and `cursorXAt` routes through the shared `cursorX`
     (`board.ts:677-691`), so that test would be vacuous. The real desync risk is **column 1 drifting
     from column 2**: assert `label.style.height` (`board.ts:560`) equals `canvas.height`
     (`board.ts:624-626`) for every row, at mixed heights.
  4. The phone day tail is unchanged (`TAIL_H` untouched), so variant-D remains a separate question.
  5. Both chains green; `npm run build` exits 0.
- **Depends on**: S2 (it touches the same row-construction code; sequencing avoids a collision).

### S4 — the two small recorded defects

- **Goal**: close the items [[lane-stack-board]]'s ledger left open.
- **Touches**: `blocks/detailpanel.ts` + its test; `src/swimzh/etl/silver.py` or
  `providers/belegungsplan.py` (whichever the section-token diagnosis implicates), `tests/`.
- **Acceptance**:
  1. `detailpanel.ts:117`'s `publicSpan` predicate is pinned — inverting it must fail a test. It
     currently leaves the whole suite green.
  2. **The lane-plan attachment count is pinned.** A test over the committed fixtures asserts the
     build attaches **7** lane plans and that `attachment.unmatched_sections` is empty. One build
     reported `unmatched section … 'sprungbecken' matched no parsed header` and attached 6; the next
     attached 7, so a silent drop is currently undetectable. If the cause turns out to be a genuinely
     varying input the test cannot control, the criterion becomes: the count is asserted and the one
     expected `unmatched_sections` member is named — never an unasserted range.
  3. Both chains green.
- **Depends on**: —

## Accepted drift

Findings the user has knowingly blessed, so `/dev:present` folds them into a
count instead of re-listing them every run. See [[accepted-drift]]. Ships empty:
rows are added by the human, or pasted from what `/dev:present` prints — never
by the command itself.

**Append-only, like the ledger.** Rows are added, never edited or deleted; a row
that stops applying is reported as stale, not removed.

`kind` is the bare word — `DROP`, `SUB`, `INV` — never the rendered symbol
(`− DROP`). `key` is `intent:+<n>`, an offset counted from the
`## Intent (verbatim)` heading line (offset 0), never a file line number.
`+ ADD` findings have no Intent phrase to anchor and cannot be accepted.

| kind | key | why | date |
|------|-----|-----|------|

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-12 | S1 | done | (1) `compose.py` gained `carry_lane_plans` + `_lane_key`, beyond the plan's "only if the branch comment needs correcting" — the curated rebuild strands attached lane plans otherwise. (2) `etl/build.py` split into `assemble_curated` + `write_curated_store`; `build_store`'s signature and behaviour unchanged (verified byte-identical over all 57 blobs). (3) `build` runs the roster fetch and curated assemble BEFORE `atomic_swap` — neither writes, failure paths identical, now covered. (4) `_compose_schedules` writes a SUBSET of `composition.facilities` — the adjudicated fix for the deletion door. | `CuratedAssembly.facilities`/`keyed_facilities` re-run `codec.loads` over all 57 blobs on every access; called at most twice per run. | yes |

## Decisions & divergences

**2026-08-12 — S1: the fix opened a second silent-deletion door, and closing it is the real result of
this slice.** Critic verdict `revise`, accepted without rebuttal.

Rebuilding the curated tier from `data/` removes the re-compose feedback, but `compose` emits a
facility for **every** curated pool whether it was scraped or not (`compose.py:344-360`), and
`write_schedules` then UPDATEs it. So a pool the catalog **names** but this run does not scrape had
its stored scraped facts overwritten curated-only — exit 0, no stderr line naming it. Reproduced
twice against committed fixtures: `freibad-heuried` with `url=None` lost 8 rules and all prices;
`planschbecken-artergut` given a unique url lost `operating_season {May 1 – Sep 30, fair_only}`.

A real input class, not a hypothesis: `scrape-gold` reads the **committed** `data/catalog.json` while
`build` uses the **live WFS** roster (`cli.py:606-609`), and `etl/scrape.py:400-404` already records
that "WFS drift has renamed roster entries before" and must "never [be] a silent exit from BOTH
phases." One drifted Planschbecken keeps `sharers[url] >= 2`, so not even the `fan-out inert` note
fires.

**Adjudicated fix (a) — narrow the write — over (b) accept the risk.** Trading silent staleness for
silent deletion is a worse trade, not an equal one. `_compose_schedules` now writes only the pools it
resolved an extract for. **The invariant landed in the write, not in the callers**, which is the
durable part: `compose` emitting a facility per curated pool makes the write the only safe narrowing
point, so any future caller handing `compose` a wider curated tier inherits the same risk unless the
rule lives there.

**Two false claims corrected rather than left standing.** `cli.py:619` and the defect report's
resolution note both said the re-layer "leaves every other blob exactly as it was" — true only for
pools the catalog OMITS. And a test docstring claimed to guard the deletion door; **mutation proved
it does not** (reverting the `scraped_ids` filter leaves it green, because an unchanged catalog
rewrites unscraped pools with byte-identical content — only a DRIFTED catalog exposes a too-wide
write). Both fixed. The orchestrator had asserted that same false property when directing the fix;
the critic caught it.

**Verification standard.** AC1/AC2 proven red pre-fix by the implementer AND independently by the
critic against a `git archive HEAD` tree with a signature-only shim. Every new guard mutation-tested:
reverting `scraped_ids` reddens the parametrized deletion test; reducing `_lane_key` to
`(facility_id, basin_id)` reddens both re-pointed-binding tests; removing `carry_lane_plans` reddens
two more. The critic hunted a **third** shape of the defect across every `facility_doc` writer and
found none, and verified `build`'s output byte-identical across the refactor rather than accepting
the identity argument.

**One deliberate deletion path remains, now pinned end-to-end:** re-pointing a `lane_plan_source` in
`data/` drops the stale plan until the next `scrape-lanes`. Intended, documented in three places
(docstring, README, defect report), and asserted as a targeted drop rather than a sweep.

**2026-08-11 — pre-approval adversarial review (dev:plan-critic), verdict `revise` → all seven
blocking findings accepted, none rebutted.** The critic recomputed every number from the domain
rather than trusting the plan's.

1. **The headline measurement described a state no user can reach.** "37 of 58, Tannenrauch 21→39"
   reproduces only with **no** `lat`/`lon`; the app seeds `PLACE_PRESETS[0]` on load and always emits
   coordinates. With a place: **34 of 57**, Tannenrauch **15→41**. Corrected in Context, with the
   error named rather than quietly replaced.
2. **"0 within-group moves" is unachievable and was the wrong property.** An insertion shifts every
   later index; simulated, 14 of 18 open-group and 36 of 36 closed-group indices still move while
   *relative order* holds. AC1 now asserts relative order.
3. **The Design would have half-fixed the bug, invisibly.** `_schedule_less_statuses`
   (`query.py:631,754-787`) runs OUTSIDE the facility loop and builds from `RosterEntry`, not
   `Facility` — so 18 of 38 statuses would have kept `distance_km: None` and stayed in the unranked
   tail, and AC4 could not catch it (it compares against an option the facility never has). Named in
   the Design and Touches, with its own criterion.
4. **AC5 was unsatisfiable.** `poolrank.ts` groups into **four** tiers, not two, and `rowDistance`
   reads only `options[].distance_km` so a status-only row stays `Infinity` however much `StatusOut`
   gains. Restated as the property that can hold; the four tiers stay.
5. **S-2's `Facts | NothingFound | Failed` writer was YAGNI.** `atomic_swap` + the two fatal aborts
   already guarantee it; kept as a regression test, dropped as a type.
6. **S4's "a diagnosis is an acceptable outcome" was an escape hatch** — replaced with an assertable
   count plus empty `unmatched_sections`.
7. **The ROW_H enumeration was wrong**: 4 of 7 rows grow, not 7; Bläsi and Leimbach go to 50, and
   "everything else stays 46" was false for two of them.

Accepted suggestions: S3's Touches corrected (`drawLaneStack` already takes `h`; the change is
`board.ts:413` alone) and its AC3 re-pointed at the real desync risk (label vs canvas height) since
the x-mapping test would have been vacuous; two shipped `ribbonrender.test.ts` tests that encode S3's
opposite are named as superseded; `openToday` dropped in favour of a derived helper; **slices
reordered so the riskiest (`scrape-gold`) runs first**, which is where the pause now sits; `O1`
restated with the real sort key.

**2026-08-11 — row order: two groups, both distance-sorted (owner's choice).** Interleaving closed
pools into one distance-ordered list was the alternative, and matches [[2026-07-19-ux-ascii-design]]'s
original intent — but it costs the scannable "what's open today" block, which the owner chose to keep.
A pool still moves between groups the day it closes; O2 makes that move visible rather than silent,
which is the actual complaint.

**2026-08-11 — the owner name is fixed by height, not by a readout.** `ROW_H = 46` and "owner inline"
are arithmetically incompatible at six lanes; the plan that shipped them both was wrong. Raising the
row for plan-bearing basins is possible because each row already owns its canvas and label cell. The
alternative — a cursor-following readout — would add the board's first pointer handler and is a
separate plan.

**2026-08-11 — `scrape-gold` fix scope.** Option 2 (re-layer from sources) over option 3 (a tier tag
on the basin): option 3 fixes basins only and leaves all ten `_ASPECTS` frozen, which the defect
report's own measurement showed is most of the bug. Option 1 (source-attributed rows) is the schema
change [[data-sourcing-rule]] defers.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/board-order-and-defects.md` (what EXISTS now, not what was intended).
