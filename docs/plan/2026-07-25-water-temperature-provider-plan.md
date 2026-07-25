---
type: plan
status: in-progress
created: 2026-07-25
feature: pool-detail-and-live-water-temp
branch: plan/pool-detail-and-live-water-temp
worktree: .claude/worktrees/plan-pool-detail-and-live-water-temp
base_branch: feat/new-ui
gates:
  qa: full
  review: adversarial
pause_after: ["S1"]
links: ["[[water-temperature-provider]]", "[[data-layer-architecture]]", "[[fastapi-service-integration]]", "[[basin]]"]
---

# Every pool gets a detail page + live water temperature (Baditicker)

## Context

Freibad Heuried shows no data because it has **no detail page at all**: it is an uncurated
catalog pin with `facility_doc IS NULL` (verified: absent from `data/registry.yaml`, no file
in `data/pools/`, `catalog.json` description `"NULL"`), so `GET /pools/{id}` 404s
(`sqlite_repo.py:231` serves detail only `WHERE facility_doc IS NOT NULL`;
`pools/router.py:41` raises 404 on None). The `/pools` **list** already serves all ~57 pools
(`list_pools` over `roster()`), but the **detail** serves only curated/prose facilities. Per
owner decision (2026-07-25): **every pool should get a real detail page.** That is the
foundation; live water temperature then attaches to it.

`Basin.measured_temp_c` is plumbed end-to-end (`pools/service.py:128` → `detailpanel.js`) but
**nothing writes it** (verified: no writer in `src/` or ETL). The open, OGD-licensed
Baditicker feed (`stadt-zuerich.ch/stzh/bathdatadownload`, no ToS gate) carries a current,
timestamped water temp per bath keyed by `poiid` (Heuried = `fb012`), covering indoor and
outdoor. The design decision (recorded in [[water-temperature-provider]]) is **live attach,
not a static gold column**: the reading is timestamped and seasonal, so a `TemperatureProvider`
port is read at request time returning a freshness-bearing `LiveTemp(reading, age)`, mirroring
the `OccupancyProvider`/`LiveOccupancy` scaffold in `domain/query.py`; gold stores only the
`baditicker` key, never the reading. This is the **first** live provider wired into the
composition root (nothing is wired today — `main.py:85` wires only the `SwimStore`).

## Design (signature altitude)

**S1 — universal detail as a generalization of prose-only facilities.** Today
`seed._prose_facility` mints a schedule-less `PARSED_PROSE` facility for pools *with* WFS
prose and returns `None` otherwise (→ NULL `facility_doc` → 404). Change: when there is no
prose, still mint a **location-only** `facility_doc` (zero basins) so every catalog pool has a
non-NULL `facility_doc`. **Its `PoolIdentity` is built from `registry.get(pool_id)` when a
registry entry exists** (carrying external keys like `baditicker_poiid`), falling back to the
bare `PoolIdentity(facility_id, name, kind)` only when there is no registry entry — so an
*uncurated* pool (Heuried) still carries its live-data keys, not just name/kind/geo. (Today
the mint at `seed.py:154` ignores the registry identity — that is the exact gap this fixes;
the registry identity is already in hand at `seed.py:67`.) Invariants preserved:
`codec.is_curated` stays
False (no basin has rules), and `find_swim_options` still yields **no `/swim` option** for a
basin-less/rule-less facility (it `continue`s on `not basin.rules`). So universal detail does
**not** turn uncurated pins into swim results — it only gives them a viewable detail card.

**Live-temp granularity.** Baditicker is **facility-granular** (one `temperatureWater` per
bath); `Basin.measured_temp_c` is **per-basin**. The live reading surfaces as a
**facility-level** `live_water_temp` field on the pool detail response — it does NOT overwrite
per-basin `measured_temp_c`. Per-basin `nominal_temp_c` (design target) stays; live temp is
additive and labelled.

Live-only domain types (in `domain/query.py`, never imported into `models.py`/the gold codec):

```python
@dataclass(frozen=True, slots=True)
class TempReading:                 # the adapter NEVER constructs a PoolId — keyed by poiid
    measured_at: datetime          # tz-aware Europe/Zurich; guard naive in __post_init__
    celsius: Decimal | None        # None when the feed cell is empty (measured nothing yet)
    is_open: bool                  # from openClosedTextPlain
    source: str                    # "baditicker"

@dataclass(frozen=True, slots=True)
class LiveTemp:
    reading: TempReading
    age: timedelta                 # now - measured_at, computed at attach
    def is_stale(self, limit: timedelta = timedelta(hours=6)) -> bool: ...

@dataclass(frozen=True, slots=True)
class TempUnavailable:
    reason: str                    # "no baditicker key" | provider describe(); NOT empty-cell

type TempResult = LiveTemp | TempUnavailable

class TemperatureProvider(Protocol):
    def read(self, poiid: str) -> Result[TempReading, ProviderError]: ...

def read_temperature(provider: TemperatureProvider, identity: PoolIdentity,
                     now: datetime) -> TempResult: ...   # fills nothing with a PoolId;
                     # returns TempUnavailable("no baditicker key") if identity.baditicker_poiid
                     # is None; else Ok→LiveTemp(age=now-measured_at), Err→TempUnavailable(describe)
```

**Empty-cell behavior is pinned:** an empty feed temp cell → `LiveTemp` with `celsius=None`
(we still know open/closed + freshness) — NOT `TempUnavailable`. `TempUnavailable` is reserved
for "no key" and provider errors. So the UI distinguishes "measured nothing yet" from "no data
source."

Identity key (mirrors `crowdmonitor_keys`): `PoolIdentity.baditicker_poiid: str | None`,
authored in `data/registry.yaml`, threaded through `curated_dto` → `providers/curated.py`
(identity build) / `boundary/mapping.py` → `seed` → `codec` → gold → rehydrated identity. A
single stable id (not a fuzzy name tuple) because the feed is poiid-keyed. **Critical for
uncurated pools:** the key reaches the identity via *curated_dto* only for curated pools; an
uncurated pool (Heuried) gets its facility identity from the S1 location-only mint, which
therefore MUST reuse `registry.get(pool_id)` (above) — otherwise `identity.baditicker_poiid`
is `None` and no temp attaches. This is why Heuried needs a `registry.yaml` entry
(`facility_id`, `name`, `kind`, `baditicker_poiid: fb012`) even though it has no curated
schedule. (The crowdmonitor precedent never hit this because occupancy attaches to `/swim`
options, which uncurated pools never produce; temperature attaches to `/pools/{id}`, which
now serves them.)

Adapter `providers/baditicker.py`: `fetch(client) -> Result[bytes, ProviderError]` +
`parse(bytes) -> Result[Mapping[str, TempReading], ProviderError]` (poiid → reading). Empty
`temperatureWater` → `celsius=None` (not an error); unreadable → `ParseError`; wrong shape →
`SchemaMismatch`; `dateModified` parsed to tz-aware Europe/Zurich. A TTL cache (~120 s) so
per-request `/pools/{id}` hits don't re-fetch the whole feed each time.

Attach point: `pools/service.py` resolves `read_temperature(provider, identity, now)` once per
facility → facility-level `live_water_temp` on the detail response (`pools/model.py`). Wired in
`main.py`/`config.py`, fail-open (provider error → `TempUnavailable`, never an exception).
Optional: unset config → `None` provider → `TempUnavailable("live temperature not configured")`.

## Out of scope

- **`/swim` option-level live temp** (`SwimOption.water_temp_c` stays `nominal_temp_c`); temp
  shows on the `/pools/{id}` detail. Follow-up may add it to `/swim`.
- **Occupancy / people count** — blocked on the countee.ch/ASE ToS check; separate plan.
- **Turning uncurated pins into `/swim` options** — universal detail explicitly does NOT do
  this (invariant above).
- **Live open/closed override** of the schedule resolver (`is_open` is stored but does not
  override the resolver).
- **Per-basin measured temp** from a single facility reading (granularity mismatch).
- Curating real schedules for outdoor pools; unifying the occupancy + temp live ports.

## Slices

### S1 — Universal pool detail (every catalog pool returns a detail, no 404)

- **Goal**: `GET /pools/{id}` returns a location-only detail for every catalog pool that has
  no curated/prose facility, so Heuried and all outdoor pins are viewable — without becoming
  `/swim` options or flipping to `curated`.
- **Touches**: `src/swimzh/build/seed.py` (mint a location-only `facility_doc` when
  `_prose_facility` yields none, building its `PoolIdentity` from `registry.get(pool_id)` when
  present so external keys survive — not a bare `PoolIdentity(facility_id, name, kind)`);
  possibly `storage/sqlite_repo.py` detail query if the NOT-NULL filter needs revisiting;
  `apps/web/api/pools/{service,router}.py` + `detailpanel.js` (render a basin-less detail
  gracefully — no crash on zero basins).
- **Acceptance**:
  - `TestClient GET /pools/freibad-heuried` returns **200** with name/kind/location and an
    empty basins list (was 404).
  - A regression test asserts a location-only pool materializes `is_curated == False` and
    produces **zero** `/swim` options (query returns it in neither options nor a spurious
    "closed" status) — the uncurated invariant holds.
  - The count of `is_curated == True` pools is **unchanged** from before S1 (the mint must not
    accidentally introduce a rule-bearing basin).
  - An *uncurated* pool that has a `registry.yaml` entry carries that entry's identity fields
    (e.g. `crowdmonitor_keys`) through the location-only mint and gold round-trip — proving the
    seam that S2's `baditicker_poiid` will ride on.
  - `build-twice-equal` determinism test still passes; every one of the ~57 catalog pools has
    a non-NULL `facility_doc` after build (count assertion).
  - Detail panel renders a basin-less pool without error (UI test).
  - Full QA chain green (ruff, ruff format, mypy, pytest+coverage ≥ floor, crap).
- **Depends on**: —

### S2 — Live-temp walking skeleton on the detail (fake provider)

- **Goal**: prove the whole live-attach path (first live provider in the request path,
  facility-level granularity, freshness, fail-open) with a fake provider, on top of S1's
  universal detail — so `/pools/freibad-heuried` shows a live temp.
- **Touches**: `domain/query.py` (`TempReading`/`LiveTemp`/`TempUnavailable`/`TempResult`/
  `TemperatureProvider`/`read_temperature`); `domain/models.py` + `boundary/curated_dto.py` +
  `providers/curated.py` + `boundary/mapping.py` + `build/seed.py` + `storage/codec.py` +
  `data/registry.yaml` (`baditicker_poiid`; set `freibad-heuried: fb012`, `hallenbad-city`,
  `hallenbad-oerlikon`); `apps/web/api/pools/{service,model,router}.py`;
  `apps/web/{config,main}.py` + `apps/web/services/ports.py` (optional `TemperatureProvider`
  in `app.state`; a fake for tests).
- **Acceptance**:
  - `read_temperature(fake, identity, now)` unit tests: reading → `LiveTemp` with correct
    `age`; empty `celsius` → `LiveTemp(celsius=None)`; `baditicker_poiid=None` →
    `TempUnavailable("no baditicker key")`; provider `Err` → `TempUnavailable` (no exception).
  - Gold round-trip for **both** a curated pool (`hallenbad-city`) and an **uncurated** pool
    (`freibad-heuried`, via its new `registry.yaml` entry): `registry.yaml baditicker_poiid` →
    gold → rehydrated `identity.baditicker_poiid` equal. The uncurated case is the one the
    round-2 review flagged — it exercises the S1 location-only mint reusing the registry
    identity. `build-twice-equal` holds.
  - `TestClient GET /pools/freibad-heuried` (fake @ 23 °C, known ts) → facility-level
    `live_water_temp` with a numeric `age`; a pool with no key → the unavailable reason.
  - A layering-style **import-token** test asserts `TempReading`/`LiveTemp`/`TempUnavailable`
    are not imported by `storage/codec.py` (mirrors the occupancy live-only rule; NOT a
    string-in-dump check, since `baditicker_poiid` IS deliberately persisted).
  - Full QA chain green.
- **Depends on**: S1.

### S3 — Real Baditicker adapter (fetch + parse + TTL cache)

- **Goal**: replace the fake with `providers/baditicker.py` against the real OGD feed,
  errors-as-values, cassette-pinned.
- **Touches**: `providers/baditicker.py` (new), a boundary DTO if needed, `core/errors` only
  if unavoidable (prefer existing causes), `main.py` (wire the real adapter behind config),
  `data/sources.md` (mark implemented).
- **Acceptance**:
  - Cassette test on a saved feed: Heuried `fb012` → ~23 °C, `is_open` from `geschlossen`/
    `offen`, `measured_at` tz-aware; a bath with an empty temp cell → `celsius=None`.
  - `MockTransport`: timeout/connection error → typed `ProviderError`; malformed body →
    `ParseError`; valid-but-wrong-shape → `SchemaMismatch`; new causes (if any) classified in
    `retriable()`/`describe()` (assert_never exhaustive).
  - TTL cache: N `/pools/{id}` requests within the TTL → exactly ONE upstream fetch (assert
    via injected transport call count).
  - Full QA chain green.
- **Depends on**: S2.

### S4 — Full roster keys + freshness in the detail UI

- **Goal**: map `baditicker_poiid` for every reconcilable pool (indoor + outdoor) and render
  the live temp honestly in the detail panel.
- **Touches**: `data/registry.yaml` (poiids for all mappable pools from the feed);
  `apps/web/static/js/blocks/detailpanel.js` + test (render `live_water_temp`: value +
  "measured N min ago"; stale/empty/absent states distinct); `apps/web/static/dist/` rebuilt.
- **Acceptance**:
  - Every `baditicker_poiid` in `registry.yaml` matches a real feed `poiid` (test asserts each
    declared poiid is present in the recorded feed fixture — no dangling keys).
  - Detail panel for Heuried shows "23 °C · measured N min ago"; empty cell → "not yet
    measured" (open) / closed; unavailable → the reason, not a stale number; a stale reading
    (> limit) is visibly marked.
  - TS QA chain green (`npm --prefix apps/web/static/js run qa`); Python QA green.
- **Depends on**: S3.

## Ledger

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

- **2026-07-25 (planning)** — Owner decision: **all pools get real detail pages**, not just
  baditicker-covered outdoor ones. Universal detail (S1) is a generalization of the existing
  prose-only-facility path (location-only `facility_doc` when there is no prose), preserving
  the uncurated/no-`/swim`-option invariant. Chosen after the plan-critic found Heuried 404s
  on `/pools/{id}` (no `facility_doc`), making the original Heuried-detail acceptance criteria
  unsatisfiable.
- **2026-07-25 (planning)** — Live reading is **facility-level** (`live_water_temp` on the
  detail), not per-basin `measured_temp_c` (Baditicker is facility-granular). Refines the
  [[water-temperature-provider]] concept wording.
- **2026-07-25 (planning, pre-approval review)** — Pinned empty-cell → `LiveTemp(celsius=None)`
  (not `TempUnavailable`); `TempReading` carries **no** `PoolId` (adapter never mints one —
  `read_temperature` attaches to a known `identity`); the live-only guard is an import-token
  scan, not a serialization string check (because `baditicker_poiid` is persisted).
- **2026-07-25 (planning, pre-approval review round 2)** — Round-2 critic found that the S1
  location-only mint (`seed.py:154`) built a bare `PoolIdentity(facility_id, name, kind)`,
  dropping registry external keys — so an *uncurated* pool's `identity.baditicker_poiid` would
  be `None` and Heuried (the exemplar) would show no temp, contradicting S2/S4. Resolved by
  having the mint reuse `registry.get(pool_id)` for the facility identity, with an S1
  acceptance criterion proving an uncurated pool's registry identity survives the round-trip.
  Chose keys-on-identity (matching the crowdmonitor precedent) over the critic's resolve-via-
  xref alternative, which would add a new read-side xref query to the request path.

## Summary

_(written when the plan reaches `done`)_
