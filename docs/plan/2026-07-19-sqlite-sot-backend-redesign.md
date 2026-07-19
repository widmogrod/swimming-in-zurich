---
type: plan
status: draft            # PROPOSED — REVISITED 2026-07-19 (see §0): SoT refactor landed; scope narrowed to the id/normalization delta; open-decisions #1/#2 settled
created: 2026-07-19
feature: sqlite-sot-backend-redesign
origin: greenfield design panel (frame -> 3 independent architectures -> adversarial scoring -> synthesis)
gates:
  qa: full
  review: adversarial
scope: full backend rewrite (strangler) around SQLite as the single RUNTIME source of truth
links: ["[[2026-07-19-ux-usability-pass]]", "[[ux-presentation]]", "[[fastapi-service-integration]]"]
---

# Proposed design contract — SQLite-SoT backend redesign

> Produced by a multi-agent design panel (11 agents): a shared requirements frame, three
> independent from-scratch architectures (migrations-as-SoT / typed-source-import / DB-native+CQRS),
> two adversarial critics scoring each, and this synthesized contract. **Status: draft** — the four
> Open Decisions (§6) are the owner's to make before this becomes an approved implementation plan.
> The concurrent `lane-reservations` refactor has already moved CLAUDE.md toward runtime-SoT; this
> contract builds on that (Phase 4 rebases onto it).

# swimzh Backend Redesign — Target Design Contract

## 0. REVISITED (2026-07-19) — current state after the SoT refactor landed

The concurrent `single-source-of-truth` refactor has **shipped** and moved the runtime to one gold
SQLite store. Re-scoping this contract against the *actual* code (README + a freshly-built DB):

**Already done by the refactor (drop from this contract's scope):**
- One runtime store; the app reads **only** the gold `.sqlite` (`GoldSwimData.load_all` + `load_catalog`
  + `load_calendar`); `data/` is never read at runtime. → **crux #7 done.**
- Offline `swimzh build` compiles committed `data/` YAML → the DB; `.db` git-ignored; fail-fast if
  missing/empty. → **crux #1 (runtime SoT), #5 (read-only), open-decisions #1 (build-on-deploy) and
  #2 (no write path) all effectively SETTLED.**
- The DB now holds all ~57 pools (a `catalog` table) alongside curated/scraped `facility` rows.

**NOT fixed — and arguably hardened (this is the remaining, valuable delta):**
- **The split-brain is now two un-joinable tables in the one store.** Verified on a fresh build:
  `facility.facility_id ∈ {aemtler, bungertwies, city, oerlikon}` (short) vs
  `catalog.pool_id ∈ {hallenbad-city, flussbad-…}` (long); **intersection = ∅**. `city` and
  `hallenbad-city` are the same pool in two rows sharing no key.
- `/swim` (reads `facility`) and `/pools` (reads `catalog`) are **disjoint** — no id path from a
  catalog pool to its schedule.
- **`uncurated` still not produced at runtime.** The `SwimData` port is unchanged
  (`facilities()`+`calendar()`, stale docstring); `find_swim_options` still gets no registry; the UI
  derives "uncurated"/"location only" client-side by *name* (fragile).
- **`scrape-gold` still bypasses `silver.reconcile`** (`cli.py` → `write_gold(...)` directly) and
  writes *long* catalog ids into the short-id `facility` PK → the gold-internal PK split-brain is live.
- Schema is still a **`doc` blob per row** (`facility.doc`, `catalog.doc`) — not normalized; that
  opacity is exactly what lets two builders write incompatible ids into one PK.

**Re-scoped target (the delta that carries the value):** collapse `facility`+`catalog` into ONE
`pool` table that IS the registry — all ~57 pools under one canonical id, a **derived** `curation_status`,
`pool_alias`/`pool_xref` for the legacy short/long ids — so `uncurated` becomes a `SELECT`, `/swim`↔`/pools`
join, `scrape-gold` routes through one reconciling builder, and the blob is normalized away. Sections 1–5
below still describe this target; **Phases 0–1 (id unification + normalized store) are now the critical
path**, and Phase 4's "flip the app to read only SQLite" is largely **already done** — it reduces to
wiring the unified `pool`/registry roster into `find_swim_options(..., uncurated=...)` and pointing
`/pools` + `/swim` at the one table.

## 1. Recommendation

**Build Design B (typed-text → deterministic import → one normalized SQLite where the `pool` table IS the registry), hardened with the specific fixes both its critics demanded, and grafted with two structural ideas from the runner-ups.** The scores make this the floor, not the ceiling: B took the top single score (31) and the honesty invariant "cleanest win" in both its reviews; A tied at 31 on the strength of typed, mypy-checked curation diffs; C's DB-native authoring (30/27) was uniformly judged over-built for 57 pools and *lost the tie-breaker* because its curation loop is "mutate local DB → export → commit generated YAML," strictly slower than editing text. Every reviewer across all three designs independently converged on the same winning primitive — **the `pool` table is the registry: all ~57 pools as rows under one slug PK with a `status`/`curation` column, so `uncurated` becomes an ordinary `SELECT` and `find_swim_options(uncurated=...)` retires the dead `registry=None` path** — so that is non-negotiable in the target. We reject C's write-model/audit/projection layering and we reject the committed `gold.sql` + `--check` byte-equality gate that both of B's critics flagged as re-importing the exact dual-maintenance ceremony the rewrite exists to delete.

**Crux #1 answered definitively.** SQLite is the **runtime** single source of truth: the app opens exactly one store, read-only, and reads nothing else — no `catalog.json`, no YAML, at runtime. Curation stays reviewable because the **authoring** source is typed, pydantic-validated YAML under `data/`, and a single deterministic **offline** `build` compiles that YAML plus committed scrape snapshots into the normalized SQLite file. The `.db` is a disposable build artifact (git-ignored), regenerable in seconds from committed text; a reviewer sees a schedule change as a one-line YAML diff (`time_start: "09:00"` → `"09:30"`). There is **no committed SQL dump and no byte-equality CI gate** — the reviewable SoT is the YAML, and determinism is guarded by an in-suite "build twice, assert equal rows" test, not a cross-machine serialization gate. This honors the mandate at the layer that matters (one store, one read path, cannot be assembled two ways) without pretending a binary is the review surface.

---

## 2. The target architecture

### Module / package layout

```
swimzh/
├─ data/                                   # THE reviewable authoring SoT (typed text, git)
│  ├─ catalog/pools.yaml                   # all ~57: canonical slug id + WFS facts (generated, reviewable)
│  ├─ crosswalk.yaml                       # id → {aliases, geo_sport_id, crowdmonitor_keys, legacy ids}
│  ├─ pools/<id>.yaml                      # hand-curated schedules/basins/prices, keyed by canonical id
│  ├─ calendar/zurich.yaml                 # public + school holidays, seeded years
│  └─ snapshots/<source>/<id>.json         # FROZEN, id-resolved scrape output (text only; see §5 PDF note)
│                                          #   + manifest.yaml (fetched_at, source_url, sha256)
├─ src/swimzh/
│  ├─ core/                                # CARRY OVER: result.py, errors.py (closed union), http.py, clock.py
│  ├─ domain/                              # CARRY OVER ~verbatim — the pure core (§4)
│  │  ├─ resolver.py access.py schedule.py calendar.py    # the correctness heart
│  │  ├─ models.py pricing.py geo.py person.py lane_plan.py lockers.py query.py catalog.py(slug)
│  ├─ seed/
│  │  ├─ schema.py                         # pydantic v2 DTOs per YAML file (extra="forbid")
│  │  └─ load.py                           # YAML tree → domain objects, Result-typed
│  ├─ ingest/                              # providers: parsing kept; two-phase network/offline
│  │  ├─ refresh.py                        # NETWORK-ONLY: fetch → resolve id (lookup) → write snapshot
│  │  ├─ geo_sport.py schedule_scraper.py price_scraper.py infrastruktur.py belegungsplan.py
│  ├─ build/                               # the ONE builder (offline, deterministic, no network)
│  │  ├─ reconcile.py                      # identity resolution by LOOKUP (silver discipline)
│  │  ├─ compose.py                        # compose(pool_id) -> Facility  (THE merge seam, §crux 6)
│  │  ├─ materialize.py                    # domain Facility → normalized rows
│  │  └─ pipeline.py                       # build(): seed+snapshots → reconcile → compose → materialize
│  ├─ store/                              # the SQLite layer (sole sqlite3 importer)
│  │  ├─ schema.sql                        # single head schema (no migration graph, §crux 4)
│  │  ├─ connect.py                        # open_ro (mode=ro, query_only) / open_rw; user_version assert
│  │  ├─ rows.py                           # TOTAL row↔domain mappers (access union, weekday mask)
│  │  └─ read_model.py                     # SqliteSwimStore : implements SwimStore
│  └─ cli.py                               # refresh <src> | build | verify
└─ apps/web/
   ├─ main.py                              # sole composition root; open_ro; Registry(store.roster())
   ├─ config.py                            # env only here (SWIMZH_DB), fail-fast at lifespan
   ├─ services/ports.py                    # SwimStore Protocol (replaces SwimData)
   └─ api/{swim,pools,access,health,ui}/router.py
```

Deleted: `storage/sqlite_repo.py` (blob), `storage/codec.py`, `storage/catalog_json.py`, `etl/pipeline.py`+`silver.py`, `etl/scrape.py`+`cli.scrape_gold`+`write_gold`, `domain/registry.py` as an authored file (it becomes rows), `data/registry.yaml`, `data/catalog.json`.

### Canonical SQLite schema (DDL sketch)

Fully normalized down to schedule-rule rows (no per-facility `doc` blob — that opacity is what let two builders write incompatible ids into one PK). The **one** deliberate blob is `basin.lane_plan_json`: a derived Belegungsplan artifact read whole, never queried by column. Identity integrity is a **write-time constraint**, grafted from Design C.

```sql
-- identity: THE registry. all ~57 pools. one canonical id. status is DERIVED at build, stored for SELECT.
CREATE TABLE pool (
  id              TEXT PRIMARY KEY,          -- canonical slug: 'hallenbad-city' (slug() mints it once)
  name            TEXT NOT NULL,
  kind            TEXT NOT NULL,             -- PoolKind.value
  address         TEXT NOT NULL DEFAULT '',
  lat REAL, lon REAL, website TEXT, phone TEXT, description TEXT,
  holiday_policy  TEXT NOT NULL DEFAULT 'normal'
                    CHECK (holiday_policy IN ('normal','sunday_schedule','closed')),
  curation_status TEXT NOT NULL             -- 'curated' | 'uncurated'; DERIVED: curated iff ≥1 basin w/ rules
                    CHECK (curation_status IN ('curated','uncurated'))
) STRICT;

CREATE TABLE pool_alias (                    -- names/legacy short ids collapse here, LOSSLESS
  pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
  alias TEXT NOT NULL, norm TEXT NOT NULL,
  UNIQUE (norm)                              -- two pools claiming one name = write-time violation (kills split-brain)
) STRICT;
CREATE TABLE pool_xref (                      -- external namespaces as VALUES, never PKs
  pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
  namespace TEXT NOT NULL CHECK (namespace IN
    ('geo_sport','crowdmonitor','legacy_registry','legacy_catalog','wfs_name')),
  ext_id TEXT NOT NULL,
  UNIQUE (namespace, ext_id)                  -- 'city' & 'hallenbad-city' & 'City' all resolve to ONE pool.id
) STRICT;

-- provenance at SOURCE-ASPECT granularity (fixes B's pool-coarse flattening critique)
CREATE TABLE provenance (
  pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
  aspect  TEXT NOT NULL CHECK (aspect IN ('schedule','price','geo','physical','notice')),
  source  TEXT NOT NULL, curated INTEGER NOT NULL,
  valid_as_of TEXT, fetched_at TEXT,          -- FROZEN literals from snapshot manifest, NEVER build-clock
  PRIMARY KEY (pool_id, aspect)
) STRICT;

CREATE TABLE pool_amenity (pool_id TEXT REFERENCES pool(id) ON DELETE CASCADE, amenity TEXT,
                           PRIMARY KEY (pool_id, amenity)) STRICT;

CREATE TABLE basin (
  id TEXT PRIMARY KEY, pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
  name TEXT NOT NULL, kind TEXT NOT NULL,      -- BasinKind.value
  length_m TEXT, width_m TEXT,                 -- Decimal-as-text (exact, fractional prose dims)
  lanes INTEGER, nominal_temp_c TEXT,
  physical_source TEXT NOT NULL CHECK (physical_source IN ('curated','parsed_prose')),
  lane_plan_json TEXT                          -- the ONE blob: validated LanePlan or NULL
) STRICT;

CREATE TABLE feature (                          -- non-swim; MUST NOT leak into find_swim_options
  id INTEGER PRIMARY KEY, pool_id TEXT REFERENCES pool(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, name TEXT NOT NULL, surcharge_chf TEXT, temp_c TEXT, note TEXT NOT NULL DEFAULT ''
) STRICT;

-- ONE rule table serves basins AND feature-hours (both resolve through resolve_hours).
CREATE TABLE schedule_rule (
  id INTEGER PRIMARY KEY,
  basin_id   TEXT REFERENCES basin(id)   ON DELETE CASCADE,
  feature_id INTEGER REFERENCES feature(id) ON DELETE CASCADE,
  weekday_mask INTEGER NOT NULL,               -- frozenset[Weekday] ⇄ int, total bijection over 0..127
  start_min INTEGER NOT NULL, end_min INTEGER NOT NULL,   -- minutes since midnight
  scope TEXT NOT NULL DEFAULT 'always' CHECK (scope IN ('always','school_term','school_holiday')),
  -- SessionAccess tagged union, inlined; CHECK ties min_age to the two age-bearing arms:
  access_kind TEXT NOT NULL CHECK (access_kind IN
    ('public','lane_swim','family','women_only','seniors_only','school_reserved','club_reserved','adults_only')),
  min_age INTEGER, note TEXT NOT NULL DEFAULT '', club TEXT NOT NULL DEFAULT '',
  CHECK ((basin_id IS NULL) <> (feature_id IS NULL)),      -- exactly one owner
  CHECK (start_min < end_min),
  CHECK ((access_kind IN ('seniors_only','adults_only')) = (min_age IS NOT NULL))
) STRICT;

CREATE TABLE schedule_exception (
  id INTEGER PRIMARY KEY, basin_id TEXT NOT NULL REFERENCES basin(id) ON DELETE CASCADE,
  on_date TEXT NOT NULL, closed INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '',
  UNIQUE (basin_id, on_date)
) STRICT;
CREATE TABLE exception_session (                 -- replacement sessions when closed=0
  id INTEGER PRIMARY KEY, exception_id INTEGER NOT NULL REFERENCES schedule_exception(id) ON DELETE CASCADE,
  start_min INTEGER NOT NULL, end_min INTEGER NOT NULL,
  access_kind TEXT NOT NULL, min_age INTEGER, note TEXT DEFAULT '', club TEXT DEFAULT ''
) STRICT;

CREATE TABLE closure (                           -- facility multi-day (Revision/seasonal)
  id INTEGER PRIMARY KEY, pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
  start_date TEXT NOT NULL, end_date TEXT NOT NULL, reason TEXT NOT NULL DEFAULT ''
) STRICT;
CREATE TABLE notice (id INTEGER PRIMARY KEY, pool_id TEXT REFERENCES pool(id) ON DELETE CASCADE,
                     text TEXT NOT NULL, active_from TEXT, active_to TEXT) STRICT;
CREATE TABLE price (id INTEGER PRIMARY KEY, pool_id TEXT REFERENCES pool(id) ON DELETE CASCADE,
                    category TEXT NOT NULL, amount_chf TEXT NOT NULL, display TEXT NOT NULL,
                    valid_as_of TEXT, source_url TEXT, UNIQUE (pool_id, category)) STRICT;
CREATE TABLE locker (id INTEGER PRIMARY KEY, pool_id TEXT REFERENCES pool(id) ON DELETE CASCADE,
                     category TEXT, fee_chf TEXT, deposit_chf TEXT, period TEXT, raw TEXT NOT NULL) STRICT;

CREATE TABLE calendar_public_holiday (on_date TEXT PRIMARY KEY, name TEXT NOT NULL) STRICT;
CREATE TABLE calendar_school_holiday (id INTEGER PRIMARY KEY, name TEXT, start_date TEXT, end_date TEXT) STRICT;
CREATE TABLE calendar_year (year INTEGER PRIMARY KEY) STRICT;   -- covers() boundary

CREATE INDEX ix_basin_pool ON basin(pool_id);
CREATE INDEX ix_rule_basin ON schedule_rule(basin_id);
-- schema version = PRAGMA user_version (§crux 4). Occupancy READINGS never persisted;
-- only crowdmonitor KEYS live, as pool_xref(namespace='crowdmonitor') rows.
```

### Data-flow

```
   NETWORK (only in `refresh`, human-initiated, reviewed)      GIT-COMMITTED TEXT (the reviewable SoT)
  ┌────────────────────────────┐   ingest/refresh.py   ┌───────────────────────────────────────────┐
  │ stadt-zuerich pages / WFS   │ ───────────────────▶  │ data/snapshots/<src>/<id>.json (+manifest) │
  │ Belegungsplan PDF           │  fetch → resolve id   │ data/catalog/pools.yaml   (57, slug ids)   │
  └────────────────────────────┘  (LOOKUP, loud Err)    │ data/pools/<id>.yaml      (curated)        │
                                   PDF→extracted JSON    │ data/crosswalk.yaml · data/calendar/*.yaml │
                                                          └───────────────────┬────────────────────────┘
                                                                              │  swimzh build  (OFFLINE, deterministic, NO network)
                              seed/load.py (pydantic) + ingest parsers ───────┤
                                                                              ▼
                                       reconcile (id by lookup) → compose(pool_id)->Facility  [curated > scraped]
                                                                              ▼
                                                     materialize → normalized rows → swimzh.sqlite
                                                                              │  (git-ignored, disposable)
                                                                              ▼  open_ro(mode=ro, query_only)
                          apps/web  SqliteSwimStore ──► Registry(store.roster()) ──► find_swim_options (PURE)
                                                                              ▼
                              /swim (open · closed(reason) · uncurated, provenance)   /pools   /pools/{id}
```

**Grafted from the runner-ups:** from **Design C** — the `pool_alias UNIQUE(norm)` + `pool_xref UNIQUE(namespace, ext_id)` constraints that make split-brain a *write-time constraint violation* (the strongest G1 expression), the `roster()`/`facilities()` port split, and `CHECK`-constrained enums as a compiler-adjacent integrity net. From **Design A** — the explicit `compose(pool_id) -> Facility` build-time reconciler (closing the "two writers per pool" hole both A and B critics named), **frozen** `fetched_at`/`valid_as_of` literals sourced from the snapshot manifest (never the build clock), and the "single head schema, rebuild-don't-migrate" stance (dropping A's own forward-migration graph, which its critics called speculative for a disposable DB).

---

## 3. Crux decisions — resolved

| # | Crux | Resolved answer | One-line why |
|---|------|-----------------|--------------|
| 1 | SoT vs reviewability | SQLite is the **runtime** SoT (one store, read-only); **authoring** SoT is pydantic-validated YAML under `data/`; one offline `swimzh build` compiles YAML+snapshots → normalized DB. `.db` git-ignored, no committed SQL dump. | Reviewer diffs a YAML line; runtime cannot be assembled two ways; no cross-machine byte-gate to flake. |
| 2 | One id namespace | `pool.id` = `slug(name)` (from `domain/catalog.py`), minted once when `data/catalog/pools.yaml` is generated from WFS; legacy `city`/`hallenbad-city` become `pool_alias`/`pool_xref` rows. | `UNIQUE(norm)`/`UNIQUE(namespace,ext_id)` make a second id scheme a constraint violation — split-brain unrepresentable. |
| 3 | Schema ↔ domain | Fully normalized; `frozenset[Weekday]`⇄`weekday_mask` bijection; `SessionAccess`⇄`(access_kind,min_age,note,club)` via `match`+`assert_never` in `store/rows.py`; one `lane_plan_json` blob exception. | Rows diff cleanly, union crosses totally, compiler is the completeness gate; blob only for the derived, never-queried artifact. |
| 4 | Migrations | Single `store/schema.sql`; `PRAGMA user_version` asserted at startup (fail-fast); upgrade = rebuild from committed text. No numbered migration graph. | The DB is disposable — a migration ledger is ceremony for a scenario that never occurs. |
| 5 | Read vs write at runtime | **Read-only** (`mode=ro`, `query_only=1`). No admin/write path in `apps/web`; all writes offline in `build`/`refresh`. | Runtime cannot mutate "truth"; every row traces to committed text; a correction is a PR. |
| 6 | ETL → DB reproducibly | Two-phase: `refresh` (network-only, resolves id by lookup, writes committed snapshot) severed from `build` (offline, deterministic, snapshot bytes only). `compose(pool_id)` merges curated+scraped with **curated-wins** precedence; unresolved name = `Err(SchemaMismatch)`. | Kills non-reproducible `scrape-gold`; one builder, one PK, defined merge seam; errors stay values. |
| 7 | App reads only SQLite | `SwimStore` Protocol replaces `SwimData`: `facilities()`/`roster()`/`catalog()`/`facility(id)`/`calendar()`. `main.py` builds `Registry(store.roster())` and calls `find_swim_options(..., uncurated=...)`. | `/swim`+`/pools*` share one read path; `uncurated` goes live in prod; resolver still gets pure in-memory `Facility`. |
| 8 | Testing | Resolver/eligibility unit-tested off-DB on hand-built `Facility`; store tests via `:memory:`+`schema.sql` round-trip; property tests on mask/access; ETL against committed snapshot fixtures; injected `Clock`; "build-twice-equal" determinism test. | Purity preserved (G3); reviewability testable; QA chain (ruff→mypy→pytest≥91→crap) stays green. |

---

## 4. What carries over vs rebuilt

**Carry over ~verbatim — the crown jewels (pure, DB-free, do not touch behavior):**
- Entire `domain/`: `resolver.py` (priority-ordered `resolve_hours` — the correctness heart), `access.py` (`SessionAccess` union + explainable `eligibility` + `ACCESS_TYPES` completeness test), `schedule.py`, `calendar.py` (`covers()` honesty), `pricing.py`, `geo.py`, `person.py`, `lane_plan.py`, `lockers.py`, `models.py`, `catalog.py` (`slug()` — now the id minter), and `query.py`'s `find_swim_options`/`facility_detail` three-state + occupancy-only-for-~now logic (incl. the "occupancy never persisted" regression guard).
- `core/result.py`, `core/errors.py` (closed `ProviderError` union + `retriable`/`describe`+`assert_never`), `http.py`.
- Provider **parsing** logic (`geo_sport`, `schedule_scraper`, `price_scraper`, `infrastruktur`, `belegungsplan`) — re-pointed from live bytes to snapshot bytes.
- `silver.reconcile`'s lookup-not-fuzzy discipline → relocated to `build/reconcile.py`.
- Curated pydantic DTOs → repurposed as `seed/schema.py` (the YAML boundary), no longer duplicated in a storage codec.

**Rebuilt fresh:**
- Storage: `storage/sqlite_repo.py` blob + `codec.py` + `catalog_json.py` → normalized `store/` (`schema.sql` + `rows.py` + `read_model.py`).
- Builders: the dual `etl/pipeline.py`+`silver` vs `cli.scrape_gold`+`etl/scrape.py` → one `build/pipeline.py` + offline `ingest/refresh.py`.
- Identity: `domain/registry.py` + `data/registry.yaml` → the `pool` table (`+ pool_alias/pool_xref`), hydrated at runtime as `Registry(store.roster())`.
- Wiring: `SwimData` → `SwimStore`; `find_swim_options(..., registry=None)` → `(..., uncurated=...)` always populated; `/pools` reads the store, not `catalog.json`.

---

## 5. Build plan (strangler, each phase shippable + gated)

Run the whole effort in a dedicated **git worktree** (e.g. `../swimzh-sqlite-sot`) — the concurrent lane-reservations refactor touches `lane_plan.py`/`belegungsplan.py`/`basin.lane_plan_json`, so keep those the **last-composed seam** and rebase the worktree onto their landing before Phase 4.

| Phase | Scope | Effort | Gate to ship |
|---|---|---|---|
| **0 — Id unification (unblocks all)** | Regenerate `data/catalog/pools.yaml` with `slug()` ids for all 57; rewrite the 3 curated `pools/*.yaml` + new `crosswalk.yaml` to slug ids, old short ids preserved as aliases. Pure data + rename script; domain untouched. | **S** | Old app still green; a script asserts every legacy id lands as an alias/xref (lossless). |
| **1 — Normalized store, parallel** | Land `store/schema.sql`, `rows.py`, `read_model.py`, `connect.py`; property tests (mask/access round-trip) + `:memory:` materialize→hydrate equality. Old blob store still runs. | **M** | New store green in isolation; QA chain passes; no app change yet. |
| **2 — One builder + compose seam** | Land `seed/`, `build/{reconcile,compose,materialize,pipeline}.py`. `swimzh build` produces `swimzh.sqlite` from YAML (4 curated + 57 identities). Implement **curated-wins** precedence in `compose`. Retire `etl/pipeline.py`/`silver`. | **L** | `build` yields exactly 57 `pool` rows, 4 curated; determinism test (build twice, equal rows) green. |
| **3 — Quarantine scrapes** | `ingest/refresh.py` fetches → resolves id by lookup → writes committed `data/snapshots/*.json` (+manifest with frozen `fetched_at`). Re-point parsers at snapshots. Delete `scrape_gold`/`write_gold`/`etl/scrape.py`. PDF → committed extracted JSON (never the binary). | **M** | `build` runs fully offline (`block_network` in suite); snapshot golden tests green. |
| **4 — Flip the app** | `SwimData`→`SwimStore`; `find_swim_options(..., uncurated=...)`; `main.py` wires `Registry(store.roster())`; `/pools*` read the store. Delete `registry.py`, `catalog_json.py`, `sqlite_repo.py`, `codec.py`, `data/registry.yaml`, `data/catalog.json`. Rebase onto lane-reservations landing first. | **M** | `/swim` emits all three states live; `/pools` returns 57 from one path; coverage floor held/ratcheted. |

**Top risks + mitigations:**
1. **Compose precedence ambiguity** (curated vs scraped overwriting a hand fix) — the split-brain's last hiding place. → `compose(pool_id)` has one explicit rule: hand-curated `pools/<id>.yaml` sections override snapshot-derived sections at the aspect level; a section present in both emits a build-time note. Tested with a fixture pool curated *and* scraped.
2. **`status` minting drift** — if hand-set it can lie. → `curation_status` is **derived** at materialize (`curated` iff ≥1 basin carries ≥1 rule), never authored. A test asserts a schedule-less pool is `uncurated`.
3. **Snapshot staleness masquerading as truth** — frozen HTML serves old hours. → `provenance.fetched_at`/`valid_as_of` are frozen manifest literals surfaced on every answer; `swimzh verify` warns when an aspect's `valid_as_of` exceeds a threshold. Staleness stays *visible*, never faked.
4. **Build non-determinism** (set/dict ordering, Decimal/tz) — flaky rows. → canonical ordering in `materialize` (`ORDER BY` id, Decimal-as-text, minutes-as-int); a build-twice-equal test, not a cross-machine byte gate.

---

## 6. Open decisions for the owner

1. **Commit `swimzh.sqlite`, or build-on-deploy?** — *Recommend build-on-deploy (git-ignore the `.db`).* It is regenerable from committed text in seconds; committing a binary re-introduces a review-opaque artifact and a sync obligation. Ship the build step in the deploy/CI pipeline.
2. **Runtime write/admin path — yes or no?** — *Recommend no.* Read-only runtime defends both honesty (app can't mutate truth) and reproducibility (every row traces to committed text). Curation is a git PR workflow, not an API. Revisit only if non-technical editors need a live console (then add a separate offline admin tool that writes YAML, still PR-gated).
3. **Authoring format: typed YAML (chosen) vs typed-Python seeds (Design A)?** — *Recommend YAML + pydantic `extra="forbid"`.* It keeps a validation boundary distinct from the loader and is editable by non-Python contributors; Design A's mypy-checked Python seeds are marginally stronger at author-time typing but couple curation to executable build code. If the team is Python-only and values compile-time seed checking over accessibility, A's seeds are a defensible swap — decide once, don't mix.
4. **PDF Belegungsplan provenance** — *Recommend committing the extracted-text/JSON intermediate as the reviewable snapshot and treating the source PDF as a build-time-only dev fetch (not committed).* Confirm this is acceptable for the legal/source register in `data/sources.md`, since the original binary won't live in git.
