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
| 2026-07-26 | S1 | done | `kind`/geo served by the `/pools` list, not the detail body (deferred to S2, which owns `model.py`); the prose mint now also reuses the registry identity (additive) | none | yes |
| 2026-07-26 | S2 | done | `config.py`/`mapping.py`/`seed.py` untouched (no work needed — adjudicated acceptable); added `apps/web/deps.py` accessor (idiomatic) | placeholder poiids `hb_city`/`hb_oerlikon` for 2 indoor pools (S3/S4 verify vs. the real feed) | yes |
| 2026-07-26 | S3 | done | saved-fixture pin instead of a vcrpy cassette (offline by construction, matches house convention); single `SWIMZH_BADITICKER_URL` (presence=enabled) | `parse()` fails the whole snapshot on one malformed bath (vs. `schedule_scraper`'s skip-and-report) — wide blast radius; no explicit errors-not-cached test | yes |
| 2026-07-26 | S4 | done | mapped 20 pools to real poiids; Bungertwies withheld-for-test → critic-blocking, fixed (mapped `hb002`, no-key test repointed to genuinely-keyless `altstetten`); UI suite is `node:test` (not vitest `.ts`), gated via the pytest node bridge | Flussbad Unterer Letten unmapped (two feed poiids `flb6940`/`flb8803` for two catalog pools, undisambiguable — needs a human decision) | yes |

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

- **2026-07-26 (S1 implementation)** — `_prose_facility` was replaced by
  `_location_only_facility`, which ALWAYS mints a schedule-less `Facility` (prose
  `PARSED_PROSE` basins when the description names any, else **zero basins**), with provenance
  `source="catalog"` for pure location-only pools. Result: `GoldRepository` now returns all 57
  facilities (was 9); the 53 rule-less ones are correctly skipped by `find_swim_options`
  (`continue` on `not basin.rules`) — so the request path now iterates the full roster for
  detail (noted for S2/S3 `read_temperature` wiring). A `freibad-heuried` outdoor entry was
  added to `data/registry.yaml` (`crowdmonitor_keys: []`) to exercise the registry-identity
  seam. **Divergence adjudicated (critic, non-blocking):** `kind`/`lat`/`lon` are NOT on
  `FacilityDetailOut` — they come from `PoolOut` on `/pools`; adding them to the detail body is
  an S2 change (S2 owns `model.py`). Accepted as consistent with the plan's own slicing.
- **2026-07-26 (S1 process)** — Known worktree-isolation trap hit: the slice/critic subagents'
  cwd was pinned to the session launch dir (main checkout `feat/new-ui`), so S1 landed there,
  not in the plan worktree. Relocated by `git diff` → `git apply` into the worktree, restored
  the main checkout clean, and re-ran the FULL QA chain **in the worktree** myself (a
  cwd-pinned `qa-gate` subagent would re-hit the trap). All green there before commit.

- **2026-07-26 (S2 implementation)** — Live-only types + `read_temperature` added to
  `domain/query.py` mirroring the occupancy scaffold; `PoolIdentity.baditicker_poiid` threaded
  DTO → `curated.py` → `codec.py` (gold persists only the key, guarded by a new import-token
  test `tests/storage/test_live_temp_not_imported.py`). Facility-level `live_water_temp` on
  `FacilityDetailOut` (per-basin `measured_temp_c` untouched). Fail-open wiring: `main.py`
  sets `app.state.temperature = None` → `TempUnavailable("live temperature not configured")`,
  never a 500. **Divergences adjudicated (critic, non-blocking):** `config.py` untouched (env
  belongs to S3's real adapter), `mapping.py` untouched (it holds no identity codec),
  `seed.py` untouched (S1's registry-identity reuse already carries the key onto uncurated
  pools — proven by the uncurated round-trip arm). No `at≈now` gate on the detail temp
  (correctly deferred — the reading is always live-now and honestly labelled with `age`).
  **Tech debt:** `hallenbad-city`/`hallenbad-oerlikon` carry placeholder poiids
  (`hb_city`/`hb_oerlikon`), commented in `registry.yaml`; S3/S4 verify every declared poiid
  against the recorded feed. Worktree isolation held this slice (forced absolute worktree
  paths in the subagent prompt) — no relocation needed.

- **2026-07-26 (S3 implementation)** — Real `providers/baditicker.py`: `fetch(client, url)` +
  `parse(bytes) -> Mapping[poiid, TempReading]` (regex extraction, house style — no XML lib),
  and a `BaditickerProvider` `TemperatureProvider` with an injectable-clock TTL cache (~120 s;
  errors never cached). Empty `<temperatureWater>` → `celsius=None`; German `dateModified`
  CDATA parsed to tz-aware Europe/Zurich. Errors-as-values: timeout/connection → typed
  `ProviderError`, malformed → `ParseError`, wrong shape / missing `<poiid>` →
  `SchemaMismatch`, unknown poiid → existing `ProviderSpecific` (no new cause). Wired behind
  `SWIMZH_BADITICKER_URL` (presence = enabled) in `config.py`/`main.build_temperature_provider`;
  unset → `None` → S2 fail-open. Pinned by the real saved feed fixture
  `tests/providers/fixtures/baditicker.xml` (mirrors `schedule_scraper`). Corrected the S2
  placeholder poiids to real values (`hb001`/`hb004`). `data/sources.md` marked implemented.
  **Divergences adjudicated (critic, non-blocking):** saved-fixture pin vs. vcrpy cassette
  (offline by construction), single presence-gated env var. **Tech debt:** (1) `parse()` fails
  the whole snapshot on one malformed bath — a single bad hand-typed feed entry drops live temp
  for ALL pools; the house convention for brittle scrapers is skip-and-report per item. Worth a
  follow-up to make parsing best-effort (skip + audit a bad bath). (2) The "errors are not
  cached / a failed fetch doesn't poison later reads" behavior is correct in code but not
  directly asserted by a test.

- **2026-07-26 (S4 implementation)** — Mapped `baditicker_poiid` for the reconcilable roster
  (added 16 minimal registry identities for outdoor/river/lake pins + poiids on the curated
  indoor pools), each `facility_id` cross-checked against `catalog.json` (no orphans). Detail
  panel (`detailpanel.js`) renders the facility-level `live_water_temp` honestly: reading →
  "N °C · measured M ago", empty cell → "not yet measured" (never a number), unavailable →
  reason (never a stale number), stale > limit → visibly marked. No-dangling-keys test pins
  every declared poiid to the saved feed fixture. **Critic-blocking, fixed (round 1):**
  `hallenbad-bungertwies` had been left unmapped solely to preserve an S2 no-key test exemplar
  — production data kept wrong for a test; fixed by mapping it to its real `hb002` and
  repointing the no-key test to `hallenbad-altstetten`, which is genuinely absent from the feed.
  **Deferred (needs a human decision):** Flussbad Unterer Letten has two feed poiids
  (`flb6940`/`flb8803`) for two catalog pools with nothing to disambiguate them — skipped
  rather than guessed; the poiid-uniqueness test keeps this honest.

## Summary

The gold store now materializes a detail for **every** catalog pool (universal `/pools/{id}`,
no 404s — Freibad Heuried and all outdoor/lake pins are viewable), and the pool detail carries
a **facility-level live water temperature** attached at request time from the OGD Baditicker
feed — a freshness-bearing `LiveTemp(reading, age)` that mirrors the occupancy scaffold and is
**never persisted** to gold (only the `baditicker_poiid` key is). The feed is read through
`providers/baditicker.py` (fetch/parse, errors-as-values, saved-fixture-pinned, TTL-cached),
wired into the composition root behind `SWIMZH_BADITICKER_URL` and fail-open (unset or provider
error → `TempUnavailable`, never a 500). The detail UI renders the reading with honest
freshness/empty/stale/unavailable states. `measured_temp_c` (per-basin, design/curated) and
`nominal_temp_c` are untouched; the live temp is additive at facility level.

Open follow-ups (tech debt, non-blocking): make `parse()` best-effort per bath (one malformed
feed entry currently drops live temp for all pools); add a direct "errors-not-cached" test;
disambiguate Flussbad Unterer Letten's two feed poiids; optionally add an `at≈now` gate on the
detail temp for future-dated queries.
