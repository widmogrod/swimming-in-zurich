---
type: concept
name: data-layer-architecture
status: partially-implemented   # identity spine + reconcile/compose landed via [[2026-07-19-pool-identity-unification]]; row-normalization + snapshots still proposed
updated: 2026-07-19
links: ["[[gold-store]]", "[[2026-07-19-pool-identity-unification]]", "[[2026-07-19-sqlite-sot-backend-redesign]]", "[[fastapi-service-integration]]"]
---

# Data layer architecture — provider extract → clean/normalize/reconcile → gold

> Output of a 9-agent design panel (Data-Eng / ETL / ELT / Backend perspectives, then
> simplicity / loose-coupling / modularity / poka-yoke scrutiny, then synthesis). This is the
> **proposed** agreed design that feeds a `/dev:plan`; open questions at the end are the owner's.

## Executive summary

The split-brain is not a data bug but a redundant-writer bug: `cli.scrape_gold` bypasses `silver.reconcile`, letting `etl/scrape._facility` mint `FacilityId(entry.pool_id)` (a slug like `hallenbad-city`) straight into the short-id `facility` PK, while `pipeline.run` writes canonical short ids (`city`) — two un-joinable rows for one pool in opaque `doc` blobs that enforce nothing. The recommended fix is the minimal slice every scrutiny lens converged on, and no more. (1) Promote the crosswalk that already exists in `domain/registry.py` (it already raises on duplicate aliases) into a DB-enforced identity spine: a `pool` table that IS the registry (all ~57 pools, one `slug()` PK), plus `pool_alias UNIQUE(norm)` and `pool_xref UNIQUE(namespace, ext_id)` — so "same entity → two ids" is a write-time IntegrityError, not a convention. (2) Collapse the two promotion paths into ONE offline builder and DELETE the scrape bypass and `drop_curated_duplicates`. (3) Make one `reconcile` seam the sole producer of a canonical id; providers emit only a `SourceRef` (never an id), and the store's write side is typed to accept only reconciled ids. Cleaning lives in one `build/normalize.py`; merge precedence is declarative curated-wins in `build/compose.py`. Reject the raw/stg/gold warehouse and don't gate the id-fix on the full snapshot/manifest/verify apparatus — those are separable later phases.

---

## swimzh data layer — recommended architecture

The problem is verified in code, not assumed. There are two promotion paths into the one gold store and they mint identifiers independently:

- `etl/pipeline.run` → `etl/silver.reconcile` → `etl/gold.write_gold`: geo is resolved to **canonical short ids** (`city`) via `domain/registry.py`.
- `cli.scrape_gold` (cli.py:75) → `providers/schedule_scraper` + `etl/scrape._facility`, which does `FacilityId(entry.pool_id)` (scrape.py:66) minting the **long catalog slug** (`hallenbad-city`), then `drop_curated_duplicates` (a name-match patch, silver.py:51) → `write_gold` **bypassing reconcile entirely**.

Both land in `storage/sqlite_repo.py`'s three `doc`-blob tables (`facility`, `catalog`, `calendar`) whose disjoint PK namespaces enforce nothing. `city` and `hallenbad-city` are the same pool in two rows sharing no key; `/swim` (reads `facility`) and `/pools` (reads `catalog`) cannot join.

The design below makes that class of bug **unrepresentable by construction** (DB UNIQUE constraints + a single id-minting seam), honoring the owner's typed/DB-enforced-correctness preference, while dropping the over-engineering three adversarial lenses flagged (no raw/stg/gold warehouse, no uniform generic port churn, no dual-maintained enums, no snapshot apparatus as a prerequisite of the id fix).

---

### 1. Semantic blocks (responsibility + inputs/outputs)

Each block is one obvious home. Real modules named; carry-over vs rebuilt marked.

| Block | Responsibility | Inputs → Outputs |
|---|---|---|
| **`providers/*` — Extract adapters** (carry over parsing; change return type) | Fetch + parse only. Each existing adapter (`geo_sport`, `schedule_scraper`, `price_scraper`, `belegungsplan`, `infrastruktur`, `curated`) turns bytes into its typed payload **paired with a `SourceRef`** describing its native key. **Forbidden from constructing a canonical id.** `etl/scrape._facility`'s `FacilityId(entry.pool_id)` is **deleted**. | live/frozen bytes, boundary DTOs → `Result[tuple[Extract, ...], ProviderError]` where `Extract = (ref: SourceRef, payload)`. `SourceRef` is a small closed union: `Xref(namespace, ext_id)` (geo_sport `poi_hallenbad_view.2`, crowdmonitor key), `Name(display_name)` (WFS name), `BasinHint(text)` (Belegungsplan header), or `Global` (price table — identity-free). |
| **`boundary/` — ingest DTO boundary** (carry over) | pydantic v2 (`extra="forbid"`) validation of curated authoring YAML + any snapshot JSON, before anything becomes a domain object. `curated_dto` repurposed as the seed schema. | YAML/JSON text → validated DTOs or `SchemaMismatch`. |
| **`build/normalize.py` — the ONE cleaning home** (new; consolidates duplication) | The single, discoverable place for value + match-key normalization: hoist the byte-identical `_normalise` (registry.py:16 == silver.py:47), and house `geo_sport._clean`, `price_scraper._money`, `infrastruktur._decimal`, `schedule_scraper` day/time parsers as plain, pure, **idempotent** functions dispatched in one module. *(The `frozenset[Weekday]⇄weekday_mask` and `SessionAccess⇄(access_kind,min_age)` bijections live in `store/rows.py` — they are row↔domain encoding, not source cleaning.)* | raw payload fields → canonical values (casefolded match keys, `Decimal`-as-text, minutes-since-midnight ints). |
| **`build/reconcile.py` — the identity seam (SOLE PoolId producer)** (relocates `silver.reconcile` + `registry` + `attach_lane_plans`) | `resolve(ref: SourceRef) -> Result[PoolId, ProviderError]` by **lookup, never fuzzy**: `pool_xref[(namespace, ext_id)]`, else `pool_alias[norm(name)]`, else basin-hint index (facility-name × `BasinKind` German word, preserving silver's ambiguous-hint-never-resolves rule). Unresolved/ambiguous → loud `Err` naming offenders, surfaced as an **inspectable unmatched list** (borrowed from the warehouse lens's observability, without its tables). `PoolId = NewType("PoolId", str)`; this module is the only place it is constructed. | `Extract`s + the crosswalk (pool/alias/xref rows) → `tuple[Keyed]` where `Keyed = (PoolId, payload)`, or `Err`. |
| **`build/compose.py` — the merge seam** (new; closes the two-writers hole) | Group `Keyed` by `PoolId`, fold curated + scraped aspects into one `Facility`, applying **curated-wins precedence from a declarative aspect-precedence map** (not hardcoded arms). Derive `curation_status` (curated iff ≥1 basin has ≥1 rule) — **never authored**. *(As implemented, the shared price is fanned out to city-run pools at scrape time by host-match — `providers`/`etl.scrape` emit `Name`, not `Global` — so `compose` folds an already-attached price aspect rather than distributing a `Global` one; the `Global` `SourceRef` variant is currently unused. Behaviour matches; the fan-out just lives one step earlier.)* Emits a build note when both sources supply one aspect. Replaces `drop_curated_duplicates`. | `Keyed` aspects grouped by pool → one `Facility` per pool + per-aspect provenance. |
| **`store/` — schema.sql + rows.py + read_model.py** (rebuilt; replaces `sqlite_repo.py`+`codec.py`+`catalog_json.py`+`calendar_codec.py`) | Sole `sqlite3` importer. `rows.py` = total `match`/`assert_never` mappers `Facility ↔ normalized rows` with the two bijections. **Write functions are typed on `PoolId`** so a caller holds no id-typed value without going through reconcile. Single head schema (`PRAGMA user_version`, fail-fast, no migration graph). `SqliteSwimStore` implements the read port `roster()/facilities()/facility(id)/catalog()/calendar()`. Runtime opens `mode=ro, query_only=1`. | composed `Facility`s (write, offline); `PoolId`/query (read) → the one gold `.sqlite`; rehydrated `Facility` + `Registry(store.roster())`. |
| **`build/pipeline.py` + `cli.py` — ONE offline builder** (replaces `etl/pipeline.py`, `etl/build.py`, `cli.scrape_gold`/`build_gold`/`scrape_lanes`, `etl/gold.py`) | Deterministic, offline: seed + inputs → normalize → reconcile → compose → materialize → write. No second door to a gold row. cli reduces to `build` (offline) and (later) `refresh <source>` (network) + `verify`. | `data/` YAML + optional frozen inputs, injected clock → the gold SQLite; nonzero exit on any typed stage failure. |
| **`domain/` — pure correctness core** (carry over ~verbatim) | `resolver`, `access`, `schedule`, `calendar`, `query.find_swim_options`, `pricing`, `geo`, `lane_plan`, `catalog.slug` (now the id minter). Only change: `find_swim_options` always receives the full roster, retiring the dead `registry=None` path so the three-state (open/closed/uncurated) answer goes live. | `Facility`s + calendar + roster (in-memory from store) → `QueryResult`. |
| **`apps/web` — composition root over one store** (rewire) | `main.py` lifespan opens one SQLite read-only, wires a `SwimStore` Protocol into `app.state`, fails fast if missing/empty. `/swim` and `/pools` share one read path joined on `pool.id`. Env only in `config.py`. | `SWIMZH_GOLD_DB` → `/swim`, `/pools`, `/pools/{id}`, `/access-types`, `/health`, `/`. |

---

### 2. End-to-end data flow (EXTRACT → CLEAN/NORMALIZE/RECONCILE → GOLD)

```
EXTRACT     providers/<source>.parse(bytes) -> tuple[Extract=(SourceRef, payload)]
            curated YAML -> boundary DTOs (the always-present, hand-verified extract)
                 |   (no adapter constructs a canonical id — it emits a SourceRef only)
                 v
NORMALIZE   build/normalize.py : pure idempotent cleaning of every payload field
            (casefold match keys, German-comma -> Decimal-as-text, times -> minutes-int)
                 |
RECONCILE   build/reconcile.resolve(SourceRef) -> Result[PoolId]   [LOOKUP, never fuzzy]
            xref(namespace,ext_id) -> alias(norm) -> basin-hint index; unresolved = loud Err
            (THE only place a PoolId is minted; unmatched refs are an inspectable list)
                 |   tuple[Keyed=(PoolId, payload)]
                 v
COMPOSE     build/compose.py : group by PoolId, fold aspects into one Facility,
            curated-wins from a declarative precedence map, derive curation_status,
            fan Global price aspects to city-run pools
                 |
MATERIALIZE store/rows.py : Facility -> normalized rows (weekday_mask/access bijections)
                 |
GOLD        store/schema.sql : rows land under FK/UNIQUE/CHECK; identity spine first
            (pool, then alias/xref/basin/schedule_rule whose FKs target pool.id)
                 |   one git-ignored, disposable swimzh.sqlite
                 v
SERVE       apps/web opens it read-only; SqliteSwimStore.roster() -> Registry;
            /swim and /pools both read the one store, joined on pool.id
```

`build/pipeline.build()` runs steps NORMALIZE→GOLD offline and deterministically. Network (the EXTRACT fetch half) is a **separate, later** `refresh` concern — the identity guarantee does not depend on it.

---

### 3. Identity + constraint model — why same-entity/different-ids is impossible

**One canonical namespace.** `pool.id = slug(name)` (existing `domain/catalog.slug`), minted exactly once when the catalog is generated from the WFS. Every *other* identifier is a **value that points at `pool.id`**, never a primary key:

```sql
CREATE TABLE pool (id TEXT PRIMARY KEY, name, kind, ..., curation_status TEXT NOT NULL
                   CHECK (curation_status IN ('curated','uncurated'))) STRICT;   -- IS the registry, all ~57
CREATE TABLE pool_alias (pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
                         alias TEXT NOT NULL, norm TEXT NOT NULL, UNIQUE(norm)) STRICT;
CREATE TABLE pool_xref  (pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
                         namespace TEXT NOT NULL, ext_id TEXT NOT NULL,
                         UNIQUE(namespace, ext_id)) STRICT;
```

The three real-world ids for one pool — `city` (legacy_registry), `hallenbad-city` (legacy_catalog + canonical), `poi_hallenbad_view.2` (geo_sport) — become three rows all resolving to ONE `pool.id`.

**Four enforcement layers, weakest to strongest:**

1. **Providers emit no id.** `SourceRef` carries only `(namespace, ext_id)` / a name / a basin hint. There is no code path from a provider to a canonical id.
2. **One minting seam.** `build/reconcile.py` is the sole constructor of `PoolId`, by lookup only. An unresolved ref is a loud `Err`, never a guess (the discipline `silver.reconcile` and `registry.resolve_name` already prove).
3. **The store write side is typed on `PoolId`.** `write_pools(rows: tuple[Keyed, ...])` — a rogue second builder (today's `scrape_gold`) cannot call the store without first passing through reconcile, because `FacilityId` as a constructible store key ceases to exist.
4. **The DB rejects the bad row.** `UNIQUE(pool_alias.norm)` and `UNIQUE(pool_xref.namespace, ext_id)` make two pools claiming one name/ext_id a **write-time `IntegrityError`** — the exact duplicate-row bug `drop_curated_duplicates` was patching after the fact. Orphans are impossible: `basin.pool_id`/`schedule_rule.basin_id` are `NOT NULL` FKs with `ON DELETE CASCADE`. `CHECK` constraints encode enum domains, `start_min < end_min`, exactly-one-owner on `schedule_rule`, and the `access_kind ↔ min_age` coupling.

**Honesty note (departs from an over-claim in the panel):** a Python `NewType` has **no** private constructor — `mypy` accepts `PoolId("anything")` from anywhere. Layer 3 is real (the *store's parameter types* force callers through reconcile) but is **not** an airtight compile-time lock. The un-bypassable guarantee is layer 4 (DB UNIQUE). Back layers 1–3 with a **grep/lint test forbidding `PoolId(...)` construction outside `build/reconcile.py`**, reusing the repo's existing "no `data/` reads at runtime" grep-guard pattern. Document the enforcement boundary as grep + DB, not "the compiler forbids it" — an overstated poka-yoke is itself a hazard.

**Derived, never authored:** `curation_status` is computed at materialize, so `/swim`'s three-state answer is a `SELECT` and no writer can set it to lie. A test asserts a schedule-less pool materializes `uncurated`.

**One deliberate blob:** `basin.lane_plan_json` (a derived Belegungsplan artifact, identity-free and read whole, never joined). The rule "blob only if identity-free AND never joined" is written down so a future contributor cannot over-apply it.

**Single head schema, rebuild-don't-migrate:** `PRAGMA user_version` asserted at open; the `.db` is a disposable, git-ignored artifact rebuilt from committed text. No migration graph, no committed `.sql` dump, no byte-equality CI gate — determinism guarded by an in-suite build-twice-equal-rows test.

---

### 4. Junior playbook

#### A. Add a new provider

1. **Write the parser.** Add `providers/<name>.py` with a pure `parse(bytes) -> Result[tuple[Extract, ...], ProviderError]` and (if networked) a `fetch(client) -> Result[bytes, ProviderError]`. Copy `geo_sport.py` (its `fetch_raw`/`parse_pools` split is the reference). On bad shape return `SchemaMismatch`/`ParseError`. **Never construct a `FacilityId`/`PoolId`.**
2. **Emit a `SourceRef`, don't invent an id.** Tag each `Extract` with `Xref(namespace, ext_id)`, `Name(display_name)`, `BasinHint(text)`, or `Global`. If it is a new external id kind, add one value to the **single** `Namespace` enum in code (see the departure note below — do not also hand-edit a SQL `CHECK` list).
3. **Classify any new error cause** inside the closed `ProviderError` union and in `retriable()`/`describe()` — `mypy`/`assert_never` will insist.
4. **Map its ids** by adding rows to `data/crosswalk.yaml` linking its ext_ids/names to existing `pool.id`s (or add a genuinely new pool to the catalog, minting one slug). Unresolved refs fail the build loudly until you do — never guess.
5. **Compose.** If the aspect is new, add its arm to `build/compose.py`'s fold and one entry to the declarative precedence map (curated-wins by default).
6. **Materialize.** If it needs storage, add a normalized table with an FK to `pool.id` and appropriate `CHECK`/`UNIQUE`; extend `store/rows.py`'s total mappers (the compiler flags the missing arm).
7. **Test.** Adapter test (cassette or `MockTransport`); a reconcile test proving every `SourceRef` resolves to exactly one `pool.id`; the build-twice-equal determinism assertion. Run `ruff → mypy → pytest → crap`.

*You never call the store, never mint an id, never edit another provider — reconcile's lookup + the store's `PoolId`-typed write side + the DB UNIQUE constraints do the rest.*

#### B. Add a cleaning / normalization rule

1. **One home: `build/normalize.py`.** Add a pure, **idempotent** function (`normalize(normalize(x)) == normalize(x)`). Value-interpretation of source bytes goes here; row↔domain encoding (mask/access bijections) goes in `store/rows.py`. There is no third choice — this removes proposal-1's two-homes ambiguity.
2. **If it touches match-key normalization** (the `_normalise` used for `pool_alias.norm` and reconcile lookup), edit the single hoisted helper so alias-norm generation and lookup can never diverge.
3. **Test** with a before/after fixture and an idempotency property test. A cleaning change **cannot re-point identity** — identity is only ever the reconcile lookup, which runs after normalize on already-canonical keys.

#### C. Integrate a new kind of information (a new aspect)

1. **Model it** in `domain/models.py` (or reuse an existing type) as pure data. Keep non-swim amenities out of `Basin` (see `Feature`).
2. **Add a normalized table** in `store/schema.sql` with an FK to `pool.id` (or `basin.id`) and the `CHECK`/`UNIQUE` constraints that make its bad states unrepresentable. Only use a blob if the data is identity-free AND never queried by column (document why).
3. **Extend `store/rows.py`** total mappers — `match`/`assert_never` makes the missing arm a compile error.
4. **Add a compose arm + precedence entry** so the aspect merges deterministically with curated-wins.
5. **Extend the read model** (`SqliteSwimStore`) and, if user-facing, the query surface and one API field.
6. **Test** a `:memory:` round-trip (materialize → hydrate equality) and the build-twice-equal assertion.

---

### 5. Agreement vs departure from `docs/plan/2026-07-19-sqlite-sot-backend-redesign.md`

**Agrees with (adopt as-is):** the `pool` table IS the registry (all ~57, one slug PK); `pool_alias UNIQUE(norm)` + `pool_xref UNIQUE(namespace, ext_id)` as the anti-split-brain pair; fully normalized store with the single `lane_plan_json` blob exception; ONE offline builder with a `compose(pool_id) -> Facility` seam and curated-wins; derived `curation_status`; single head schema (`PRAGMA user_version`, no migration graph, no committed SQL dump / byte-gate); read-only runtime; `SwimData → SwimStore`; deleting `sqlite_repo.py` blob + `codec.py` + `catalog_json.py` + the `scrape_gold`/`write_gold` bypass + `drop_curated_duplicates`; carrying `domain/` over verbatim; `slug()` as the id minter.

**Departs from / sharpens it:**
1. **Sequence identity-spine-first; do NOT gate the id fix on the snapshot/manifest/sha256/`verify` apparatus.** The plan's Phase 3 bundles committed snapshots into the rewrite. The split-brain is cured by the three constrained tables + one builder + deleting the bypass. Two-phase `refresh`/frozen snapshots is a **separable, later** determinism/audit decision — ship the id fix first (the simplicity lens's central objection to all bundled proposals).
2. **Do not dual-maintain the namespace list.** The plan hardcodes `namespace IN (...)` in the `CHECK` *and* implies a mirrored code enum. Drive it from **one** Python `Namespace` enum; validate the value in `rows.py` before insert (or generate the `CHECK` list from the enum at schema-apply). A new provider edits one place, not two in lockstep.
3. **Precedence is declarative data, not code arms.** The plan's compose "one explicit rule per aspect" risks becoming per-provider `if` arms — the split-brain's last hiding place. Make it an aspect→precedence map so the merge engine stays provider-agnostic.
4. **No uniform generic port refactor.** Do not force all six heterogeneous providers into one `Extract[T]` generic (the modularity/simplicity lenses' churn objection, and the fact that `price_scraper` is identity-free and `belegungsplan` is basin-granular). Keep each parser's shape; the thin `(SourceRef, payload)` pairing + the `PoolId`-typed store write side deliver the guarantee without the plumbing.
5. **State the enforcement honestly.** The `PoolId` newtype is not a private constructor; the real lock is DB `UNIQUE` + the grep guard. Say so.
6. **Reject the raw/stg/gold warehouse outright** (it was a competing panel proposal, not the plan's choice, but worth recording): over-built for 57 pools/6 sources; keep only its "unmatched refs are an inspectable list" observability idea, achievable in-memory.

## Open questions (owner decisions)

1. Snapshots: adopt committed frozen snapshots + manifest (deterministic, offline, replayable for the brittle scrapers/PDFs) now, or keep live-fetch-then-build and defer? Recommendation is to ship the identity spine first and decide snapshots on their own merits — but the owner must confirm the id fix is allowed to land without them.
2. Namespace domain: drive the pool_xref namespace set from a single Python `Namespace` enum (validated in rows.py) versus a SQL CHECK IN(...) list — pick one source of truth to avoid dual-maintenance. Recommendation: Python enum is the source; generate/verify the CHECK from it.
3. Legacy-id migration gate: confirm a one-shot script must assert every current short id (`city`) and catalog slug (`hallenbad-city`) resolves to exactly one pool as an alias/xref before the blob tables are deleted (lossless cutover).
4. Belegungsplan PDF provenance: commit the extracted-text/JSON intermediate as the reviewable snapshot and treat the source PDF as a build-time-only dev fetch (not committed)? Needs sign-off against `data/sources.md` legal register.
5. Authoring format for the crosswalk and curated pools: typed YAML + pydantic `extra=forbid` (accessible, chosen by the plan) versus typed-Python seeds (stronger author-time typing). Decide once, do not mix.
6. Occupancy/crowdmonitor: confirm the existing 'occupancy readings never persisted' regression guard is extended to the new schema so only crowdmonitor KEYS live (as pool_xref rows), never live readings.
