---
status: proposed
supersedes: none
informs: docs/concepts/data-sourcing-rule.md (Open decisions — "normalization"), docs/concepts/techdebt-remediation-roadmap.md item #6a-rows
motivated-by: docs/2026-08-10-scrape-gold-recompose-defect.md
---

# Gold schema design — producer-partitioned storage with selective row-normalization

## 1. Recommendation

**Do not do full row-normalization. Do producer partitioning, then normalize only the
join-and-filter surface.** The re-compose defect is a *write-door* defect — gold persists the
output of a fold and the next run feeds it back as an input — and it is fixed by two changes that
need almost no new tables: (a) key the store by `(pool_id, producer)` so a re-layer replaces one
producer's partition and can never consult another's, and (b) delete the write signature that
accepts a composed `Facility`, so "persist the fold's output" becomes a visible hundred-line
addition rather than a one-line call at `cli.py:346`. Row-normalization buys something different
and smaller: SQL-enforced invariants on the ~15 tables that are actually joined, filtered or
ordered (basins, schedule rules, lane plans, reservations, access, prices, notices, closures), and
it should be taken as a *second, optional* stage gated on that value being wanted for its own sake.
The long tail — lockers, rentals, feature hours, schedule exceptions, the 10-arm `ProviderError` —
stays as typed JSON, because at 42/85/0/0/0 rows those tables would be pure ceremony. **The decision
this implies: reverse `#6a-rows` only partially, and say so in the roadmap.** Stage A ships the
defect fix; Stage B is a real but separable investment; Stage C is declined.

Concretely: ~16 new tables, not 55 (`full-3nf`), not 37 (`fact-ledger`), not 32 (`cqrs`).

---

## 2. Where the judges disagreed — and why it matters

The three lenses did **not** agree, and the disagreement is the most informative part of the
exercise. Averaging their totals (40.5 / 40 / 40 / 39 / 38 / 38 / 37 …) produces mush; the *shape*
of the split does not.

| Lens | Winner | The single reason |
|---|---|---|
| Domain purist | `full-3nf` | It is the only design whose union encoding cannot drift: FK'd vocabulary tables generated from `typing.get_args(SessionAccess)`, plus an exclusive arc (`UNIQUE(id, kind)` + constant-`CHECK` + composite FK) so an arm's payload physically cannot attach to a row of another kind. |
| Operator | `hybrid-spine` | It is the only design that *spends a budget*: a written rule for columns-vs-JSON, ~25 tables instead of 55, Step 0 shippable on day one, steps 0–3 revert-by-commit, one one-way door explicitly gated. |
| Consumer | `hybrid-spine` | It is the only design whose read surface *composes* (`PoolFilter.__and__`, `AsOf` as a separate axis) rather than enumerating nine fixed specs, and it enforces C1 mechanically via `get_type_hints` introspection over every `Q.*` return type. |

Two of three picked `hybrid-spine`; all three ranked `cqrs-readmodel` last. But the majority is not
the interesting fact. **The purist's objection is correct and survives the vote.** `hybrid-spine`
states "enum domains are never hand-written `CHECK IN (...)` lists" in its thesis and then writes
five of them, including the SessionAccess payload coupling. I verified the consequence: its note
whitelist reads `access_kind IN ('lane_swim','family_time','women_only','adults_only')`, but the
project's own discriminator for `FamilyTime` is **`"family"`** (`boundary/curated_dto.py:71`), so
that CHECK forbids a note on every real `FamilyTime` row in the store. That is exactly the drift the
purist lens exists to catch, and it appeared in the operator's and consumer's winner.

The reconciliation this document takes: **the operator/consumer skeleton with the purist's union
encoding, upgraded so that even the purist's hand-written arc constants disappear** (§4, the
generated-column FK). Where a lens was outvoted, its objection is answered rather than absorbed.

Three further judge claims I checked against the repo, because they were doing work in the scoring:

- **The `write_pools` cascade is real and hits every design equally.** `src/swimzh/storage/sqlite_repo.py:93` is `conn.execute("DELETE FROM pool")  # FK ON DELETE CASCADE clears alias/xref too`. Any schema hanging facts off `pool(id) ON DELETE CASCADE` loses them on the next `build`. Three critiques called this fatal for their target and silently forgave the fourth. It is a shared prerequisite (Slice 0 below), not a differentiator.
- **The fabricated-enum charge against `cqrs-readmodel` is true, and `fact-ledger` commits the same sin.** Verified: `ClosureCode` is `{seasonal_break, seasonal_break_maintenance, maintenance, operational_break, christmas_eve, public_holiday, no_sessions, out_of_season, special, unmapped}`; `LockerCategory` is `{wardrobe, valuables, laundry}`; `RentalKind` is `{towel, swimwear, goggles, cabin, sunlounger, parasol, other}`; `DatePrecision` is `{day, month}`; `BasinKind` is `{lap, non_swimmer, diving, vario, teaching, children, outdoor, other}`. Both designs' `CHECK` lists are inventions. Only `cqrs`'s critique said so. **This is the empirical case for seeding vocabularies from Python rather than writing them in DDL** — two of four independent authors got them wrong by hand.
- **The `club` de-duplication payoff does not exist as advertised.** `core/normalize.py` is `" ".join(text.strip().casefold().split())` — no punctuation handling. So `"Limmat-Sharks"` and `"Limmat Sharks"` produce *different* norms; the flagship duplicate pair is not detected by the normalizer three designs cited. The `club` table is still worth building (it makes the 50 strings *visible* and gives an alias seam), but as a data-quality affordance, not as a fix.

One structural problem that **no** design solved, and the recommendation must confront: `compose.py::_carry_bindings` (`compose.py:172-190`) is a **union across tiers keyed on `lane_plan_source.url`**, not a precedence winner —

```python
scraped_urls = {b.lane_plan_source.url for b in scraped_basins if b.lane_plan_source is not None}
carried = tuple(b for b in curated_basins
                if b.lane_plan_source is not None and b.lane_plan_source.url not in scraped_urls)
return scraped_basins + carried
```

`compose.py:120-124` says so explicitly: *"`basins` is NOT here: it is not a plain
replace-the-winner field."* Every candidate proposed an `aspect_precedence(aspect, tier, rank)`
table with a strict `MIN(rank)` winner, and every one of them therefore either drops the scraped
timetable or drops the curated lane binding for the 6 pools that have lane data. §4 handles this
with an explicit binding table instead of pretending precedence covers it.

---

## 3. What is *not* being proposed, and why

| Rejected | Row count today | Why |
|---|---:|---|
| `locker_option`, `rental_item` as tables | 42 / 85 | Never joined, never filtered, no cross-record invariant. `RentalFee`'s 3 arms are display-only. Stay in one `amenities_doc` per (pool, producer), pydantic-validated on both sides. *(rule and shape from `hybrid-spine`)* |
| `provider_error` arm tables | **0** | `LanePlanUnavailable` has no writer any more (`CLAUDE.md`: a failed declared lane source is fatal). C3 still binds, and the existing `ProviderErrorDTO` + `assert_never` at `mapping.py:423/449` already prove the round-trip. 11 tables for zero rows is not a schema, it is a monument. |
| `schedule_exception`, `exception_session`, `*_param` | **0** each | `etl/field_sourcing.py` marks the field a `DROP_CANDIDATE`. Keep the shape inside the basin's JSON leaf until a row exists. |
| `feature`-owned `schedule_rule` (polymorphic owner) | **0** | The two-owner arc is the single most complex constraint in three of the four designs and it guards nothing. Features keep their hours in the amenities doc. |
| A materialized read model (`rm_*`) | — | `cqrs-readmodel`'s one-way projection is the right *idea* about direction, but nothing forces reprojection: `rm_build.fact_digest` is a recorded hash, not a constraint, so a successful scrape followed by a skipped/failed `project()` serves last week's data at exit 0 — the defect's exact observable symptom, relocated. |
| `curation_status` / `ScheduleFreshness` column | — | Deleted once already for being derived (`docs/concepts/gold-store.md`). Do not re-add. |
| `basin.measured_temp_c`, occupancy, water temperature | — | C4. Faster-moving than the rebuild cadence; they route through `TemperatureProvider` / `OccupancyProvider`, whose return types have explicit unavailable arms. |

**There is no performance argument anywhere in this document.** The whole store is ~1,900 rows and
173 KB of JSON. Every query is already instant. The case is write-side correctness and constraint
enforcement, or it is nothing.

---

## 4. The recommended schema

Conventions, applied without exception: dates/datetimes as ISO-8601 `TEXT`; clock times as
`INTEGER` minutes since midnight; `Decimal` as canonical `TEXT` (never `REAL`); `frozenset[Weekday]`
as a 7-bit `INTEGER` mask; `frozenset[int]` lanes as a lane mask; every table `STRICT`;
`PRAGMA user_version` asserted at open.

### 4.0 Head + vocabulary — *seeded from Python, never written in DDL*

**Graft: `hybrid-spine`** (`*_vocab` tables seeded at schema-apply from the Python `Enum`s) —
adopted because four independent authors hand-transcribed these lists and three got them wrong.
**Graft: `cqrs-readmodel`** (vocabulary rows carrying *shape flags*, not just names) — its one
genuinely reusable idea, and the load-bearing piece of §4.2.

```sql
PRAGMA foreign_keys = ON;
-- PRAGMA user_version = 1;  asserted at open; the store is disposable, so there is no
-- migration graph. Today user_version is 0 and the assertion in data-layer-architecture.md
-- was never implemented.

-- One table per domain Enum. Contents are TRUNCATE+INSERTed by store/vocab.py::seed(conn)
-- from [m.value for m in TheEnum]. tests/store/test_vocabulary.py asserts set(db) == set(enum)
-- for every one of them, so an added member without a seed run is a red gate, and a DDL
-- author cannot introduce a value the domain does not have.
CREATE TABLE vocab_pool_kind       (code TEXT PRIMARY KEY) STRICT;  -- 7
CREATE TABLE vocab_basin_kind      (code TEXT PRIMARY KEY) STRICT;  -- 8
CREATE TABLE vocab_basin_source    (code TEXT PRIMARY KEY) STRICT;  -- 2
CREATE TABLE vocab_day_scope       (code TEXT PRIMARY KEY) STRICT;  -- 3
CREATE TABLE vocab_weather         (code TEXT PRIMARY KEY) STRICT;  -- 2
CREATE TABLE vocab_date_precision  (code TEXT PRIMARY KEY) STRICT;  -- 2
CREATE TABLE vocab_holiday_policy  (code TEXT PRIMARY KEY) STRICT;  -- 3
CREATE TABLE vocab_closure_code    (code TEXT PRIMARY KEY) STRICT;  -- 10
CREATE TABLE vocab_price_category  (code TEXT PRIMARY KEY) STRICT;  -- 3
CREATE TABLE vocab_plan_confidence (code TEXT PRIMARY KEY) STRICT;  -- 2
CREATE TABLE vocab_xref_namespace  (code TEXT PRIMARY KEY) STRICT;
```

### 4.1 Producer partitioning — the defect fix

**Graft: `hybrid-spine`/`fact-ledger`** (producer-scoped partitions with `UNIQUE(pool_id, producer,
…)` and delete-then-insert of one partition). **Graft: `cqrs-readmodel`** (`producer_run` with
`input_digest`, which makes a no-op re-layer a visible row rather than an exit code).

```sql
CREATE TABLE producer (
    producer_id TEXT PRIMARY KEY,   -- 'curated','schedule_scraper','price_scraper',
                                    -- 'belegungsplan','infrastruktur','page_provider',
                                    -- 'geo_sport','seed'
    tier        TEXT NOT NULL CHECK (tier IN ('curated','scraped','seed'))
) STRICT;

CREATE TABLE producer_run (
    run_id       INTEGER PRIMARY KEY,
    producer_id  TEXT NOT NULL REFERENCES producer(producer_id),
    started_at   TEXT NOT NULL,      -- injected clock, never wall-clock in tests
    finished_at  TEXT,
    input_digest TEXT NOT NULL,      -- sha256 over this producer's fetched bytes
    status       TEXT NOT NULL CHECK (status IN ('running','ok','failed')),
    rows_written INTEGER NOT NULL DEFAULT 0,
    UNIQUE (producer_id, run_id)
) STRICT;

-- The per-(pool, producer, aspect) partition header. Deleting one row cascades that
-- producer's facts for that aspect and NOTHING else.
CREATE TABLE layer (
    layer_id    INTEGER PRIMARY KEY,
    pool_id     TEXT    NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
    producer_id TEXT    NOT NULL,
    run_id      INTEGER NOT NULL,
    aspect      TEXT    NOT NULL CHECK (aspect IN
                  ('identity','geo','basins','schedule','lane_plan','admission',
                   'notices','closures','amenities','season','holiday_policy',
                   'last_admission')),
    observed_at TEXT NOT NULL,
    valid_as_of TEXT,
    source_url  TEXT,
    UNIQUE (pool_id, producer_id, aspect),
    FOREIGN KEY (producer_id, run_id) REFERENCES producer_run(producer_id, run_id)
) STRICT;
CREATE INDEX ix_layer_pool_aspect ON layer(pool_id, aspect);
```

Precedence is **not** a table. It stays in `src/swimzh/storage/store/precedence.py` as
`Mapping[Aspect, tuple[Tier, ...]]`, the direct descendant of `compose.py::_ASPECTS`, because
`aspect_precedence` rows tempted every candidate design into believing basins are a
winner-takes-all fold — and they are not (§2).

### 4.2 `SessionAccess` — an eleven-arm union with **no hand-written coupling**

This is the synthesis. `full-3nf` was right that the coupling must not be hand-written; its answer
(seven payload tables behind an exclusive arc) still hand-writes eleven constant `CHECK (kind =
'…')` clauses. Generated columns give the same guarantee with one FK and zero literals.

Each arm's *presence signature* is a fact about its dataclass — verified in `domain/access.py`:
`PublicSwim()`, `SchoolReserved()`, `GirlsOnly()`, `AccompaniedChildren()` are fieldless;
`LaneSwim/FamilyTime/WomenOnly` declare `note`; `SeniorsOnly`/`GenderDiverse` declare `min_age`
(the latter with **no default**); `AdultsOnly` declares both; `ClubReserved` declares `club`.
A declared field is always non-`NULL` in storage (it has a value, possibly `""`); an undeclared
field is always `NULL`. That signature is therefore derivable by `dataclasses.fields()`.

```sql
-- Seeded by store/vocab.py::seed_access_shapes(): for each arm in typing.get_args(SessionAccess),
-- one row whose flags are {f.name for f in dataclasses.fields(arm)}. Raises if an arm is missing
-- a discriminator, so a 12th arm fails `swimzh build` rather than being silently unstorable.
CREATE TABLE vocab_access_shape (
    kind        TEXT PRIMARY KEY,          -- the SAME literal as curated_dto (note: 'family')
    has_min_age INTEGER NOT NULL CHECK (has_min_age IN (0,1)),
    has_note    INTEGER NOT NULL CHECK (has_note    IN (0,1)),
    has_club    INTEGER NOT NULL CHECK (has_club    IN (0,1)),
    UNIQUE (kind, has_min_age, has_note, has_club)
) STRICT;

CREATE TABLE access (
    access_id INTEGER PRIMARY KEY,
    kind      TEXT NOT NULL,
    min_age   INTEGER CHECK (min_age IS NULL OR min_age BETWEEN 0 AND 120),
    note      TEXT,
    club_id   INTEGER REFERENCES club(club_id),
    -- the presence signature, computed by the engine, not asserted by the author:
    has_min_age INTEGER GENERATED ALWAYS AS (min_age IS NOT NULL) VIRTUAL,
    has_note    INTEGER GENERATED ALWAYS AS (note    IS NOT NULL) VIRTUAL,
    has_club    INTEGER GENERATED ALWAYS AS (club_id IS NOT NULL) VIRTUAL,
    -- ONE constraint replaces eleven hand-written CHECK clauses, and its right-hand side
    -- is data seeded from the Python union:
    FOREIGN KEY (kind, has_min_age, has_note, has_club)
        REFERENCES vocab_access_shape(kind, has_min_age, has_note, has_club)
) STRICT;
```

Consequences, all engine-enforced: a `public` row cannot carry a club; a `gender_diverse` row
cannot omit `min_age`; a `girls_only` row cannot carry a note; a 12th arm added to `SessionAccess`
without a seeded shape makes every row of that arm an `IntegrityError` at the *build* that first
emits it, not at read. Nothing about the coupling is written twice.

`ClubReserved.club` interns into a `club` table — **graft: every design proposed it, and the honest
framing comes from `hybrid-spine`'s `canonical_id`**: it makes the 50 distinct strings visible and
gives a curated merge seam, and it fixes nothing on its own (§2).

```sql
CREATE TABLE club (
    club_id      INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL UNIQUE,
    norm         TEXT NOT NULL,            -- core.normalize; NOT unique — see §2
    canonical_id INTEGER REFERENCES club(club_id),   -- NULL == is itself canonical
    CHECK (canonical_id IS NULL OR canonical_id <> club_id)
) STRICT;
```

`norm` is deliberately **not** `UNIQUE`: a build must not break because two genuinely distinct
clubs collide, and `normalize` is too weak for the collisions that matter anyway.

### 4.3 Identity spine

```sql
CREATE TABLE pool (
    id      TEXT PRIMARY KEY,               -- domain.catalog.slug(name)
    name    TEXT NOT NULL,
    kind    TEXT NOT NULL REFERENCES vocab_pool_kind(code),
    address TEXT NOT NULL,
    lat REAL CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
    lon REAL CHECK (lon IS NULL OR lon BETWEEN -180 AND 180),
    CHECK ((lat IS NULL) = (lon IS NULL)),  -- GeoPoint is atomic
    url TEXT, description TEXT, phone TEXT
) STRICT;

CREATE TABLE pool_alias (
    pool_id TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
    ord     INTEGER NOT NULL,
    alias   TEXT NOT NULL,
    norm    TEXT NOT NULL UNIQUE,           -- global: split-brain stays a write-time error
    PRIMARY KEY (pool_id, ord)
) STRICT;

CREATE TABLE pool_xref (                    -- the SOLE home of every external id
    pool_id   TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL REFERENCES vocab_xref_namespace(code),
    ext_id    TEXT NOT NULL,
    UNIQUE (namespace, ext_id),
    UNIQUE (pool_id, namespace, ext_id)
) STRICT;
CREATE UNIQUE INDEX ux_xref_singleton ON pool_xref(pool_id, namespace)
    WHERE namespace IN ('geo_sport','baditicker');   -- 0..1 each; crowdmonitor is 0..N
```

`baditicker_poiid` becomes a real xref row, and `PoolCatalogEntry.poi_id` — silently dropped today
at `sqlite_repo.py:181-193` — becomes a join rather than a column the hydrator forgot. *(Graft:
noticed independently by all four designs; the xref-singleton index is `full-3nf`'s.)*

`pool_alias.norm` keeps its **global** `UNIQUE`. `cqrs-readmodel` weakened it to
`UNIQUE(norm, producer)` and re-asserted it post-fold; that trades write-time error locality for
nothing, and `data-layer-architecture.md` §3 names the global constraint as enforcement layer 4.
The identity spine is the one place where multi-producer generality is deliberately switched off.

### 4.4 Basins, and the cross-producer binding no precedence table can express

**This is the part every candidate got wrong.** Basins are producer-scoped (the scraper emits a
synthetic `Hauptbecken`, `etl/scrape.py:180`; curated authors emit `bungertwies-25m` and friends),
so `basin_id` is *not* a cross-producer identity. The thing that *is* stable across producers is
the lane-plan binding key — `(pool_id, source_url, section)` — which is exactly what
`_carry_bindings` matches on. So the schema gives that key its own table, and lane plans hang off
**it**, not off any producer's basin rows.

*(Graft: `fact-ledger`, which alone keyed lane plans on `(pool_id, source_url, section)` and
explicitly refused to parent them on another producer's basins.)*

```sql
CREATE TABLE basin (
    basin_pk        INTEGER PRIMARY KEY,
    layer_id        INTEGER NOT NULL REFERENCES layer(layer_id) ON DELETE CASCADE, -- aspect='basins'
    ord             INTEGER NOT NULL,
    basin_id        TEXT NOT NULL,          -- domain BasinId, stable WITHIN a producer
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL REFERENCES vocab_basin_kind(code),
    length_m        TEXT, width_m TEXT,     -- Dimensions; Decimal-as-text
    lanes           INTEGER CHECK (lanes IS NULL OR lanes BETWEEN 1 AND 63),
    nominal_temp_c  TEXT,                   -- design target. measured_temp_c HAS NO COLUMN (C4).
    diving_platforms_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(diving_platforms_json)),
    physical_source TEXT NOT NULL REFERENCES vocab_basin_source(code),
    lane_src_url    TEXT,                   -- LanePlanSource — the binding key
    lane_src_section TEXT,
    exceptions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(exceptions_json)),  -- 0 rows today
    CHECK (width_m IS NULL OR length_m IS NOT NULL),
    CHECK (lane_src_section IS NULL OR lane_src_url IS NOT NULL),
    UNIQUE (layer_id, ord),
    UNIQUE (layer_id, basin_id)
) STRICT;

-- Cross-producer basin identity, made explicit instead of assumed. One row per declared lane
-- source in a pool; both a curated basin and a scraped basin may point at it.
CREATE TABLE lane_binding (
    binding_id INTEGER PRIMARY KEY,
    pool_id    TEXT NOT NULL REFERENCES pool(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    section    TEXT NOT NULL DEFAULT '',    -- '' not NULL: SQLite UNIQUE treats NULLs as distinct
    UNIQUE (pool_id, source_url, section)
) STRICT;
```

The `section TEXT NOT NULL DEFAULT ''` is deliberate and load-bearing: `fact-ledger` keyed the same
tuple with a nullable `section` and, because SQLite's `UNIQUE` treats `NULL`s as distinct, permitted
duplicate rows for exactly the shape 6 of 7 live plans have — which would have made the 3-state
`lane_plan` decode into an unhandled `N rows` case. The same trap voids `hybrid-spine`'s
`schedule_rule UNIQUE (layer_id, basin_key, feature_id, ord)` and `full-3nf`'s interning index.
**Rule for this schema: no `NULL` may appear in any `UNIQUE` tuple.**

```sql
CREATE TABLE schedule_rule (
    rule_id     INTEGER PRIMARY KEY,
    basin_pk    INTEGER NOT NULL REFERENCES basin(basin_pk) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    weekday_mask INTEGER NOT NULL CHECK (weekday_mask BETWEEN 1 AND 127),
    start_min   INTEGER NOT NULL CHECK (start_min BETWEEN 0 AND 1439),
    end_min     INTEGER NOT NULL CHECK (end_min   BETWEEN 1 AND 1440),
    CHECK (start_min < end_min),                    -- TimeRange invariant, schedule.py:43-45
    access_id   INTEGER NOT NULL REFERENCES access(access_id),
    scope       TEXT NOT NULL REFERENCES vocab_day_scope(code),
    weather     TEXT NOT NULL REFERENCES vocab_weather(code),
    source_text TEXT NOT NULL DEFAULT '',
    season_start_month INTEGER, season_start_day INTEGER,
    season_end_month   INTEGER, season_end_day   INTEGER,
    season_precision   TEXT REFERENCES vocab_date_precision(code),
    -- AnnualWindow is all-or-nothing and YEAR-FREE: start > end legally wraps New Year
    -- (schedule.py:99-108), so there is deliberately NO ordering CHECK here.
    CHECK ((season_precision IS NULL) = (season_start_month IS NULL)
       AND (season_precision IS NULL) = (season_start_day   IS NULL)
       AND (season_precision IS NULL) = (season_end_month   IS NULL)
       AND (season_precision IS NULL) = (season_end_day     IS NULL)),
    CHECK (season_start_month IS NULL OR (season_start_month BETWEEN 1 AND 12
        AND season_start_day BETWEEN 1 AND (CASE season_start_month WHEN 2 THEN 29
            WHEN 4 THEN 30 WHEN 6 THEN 30 WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END))),
    CHECK (season_end_month IS NULL OR (season_end_month BETWEEN 1 AND 12
        AND season_end_day BETWEEN 1 AND (CASE season_end_month WHEN 2 THEN 29
            WHEN 4 THEN 30 WHEN 6 THEN 30 WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END))),
    UNIQUE (basin_pk, ord)
) STRICT;
CREATE INDEX ix_rule_basin ON schedule_rule(basin_pk);
```

The `_DAYS_IN_MONTH` `CASE` expressions are `full-3nf`'s and `hybrid-spine`'s (they wrote the same
thing independently); February is 29 because a year-free date must stay constructible in a leap
year, matching `schedule.py:78`.

### 4.5 Lane plans — the 3-state, with the arc anchored on the binding

```sql
CREATE TABLE lane_plan (
    plan_id     INTEGER PRIMARY KEY,
    binding_id  INTEGER NOT NULL UNIQUE REFERENCES lane_binding(binding_id) ON DELETE CASCADE,
    layer_id    INTEGER NOT NULL REFERENCES layer(layer_id) ON DELETE CASCADE,  -- aspect='lane_plan'
    outcome     TEXT NOT NULL CHECK (outcome IN ('plan','unavailable')),
    -- 'plan' arm
    lane_count  INTEGER CHECK (lane_count IS NULL OR lane_count BETWEEN 1 AND 63),
    valid_from  TEXT,
    fetched_at  TEXT,
    confidence  TEXT REFERENCES vocab_plan_confidence(code),
    cells_total    INTEGER CHECK (cells_total    IS NULL OR cells_total >= 0),
    cells_resolved INTEGER CHECK (cells_resolved IS NULL OR cells_resolved >= 0),
    unresolved_lane_mask INTEGER,
    weekday_lanes_stated INTEGER CHECK (weekday_lanes_stated IN (0,1)),  -- None != {}
    -- 'unavailable' arm (C3): the ProviderError round-trips through the EXISTING pydantic DTO
    source_url  TEXT, section TEXT, observed_at TEXT,
    cause_json  TEXT CHECK (cause_json IS NULL OR json_valid(cause_json)),
    CHECK ((outcome = 'plan') = (lane_count     IS NOT NULL)),
    CHECK ((outcome = 'plan') = (confidence     IS NOT NULL)),
    CHECK ((outcome = 'plan') = (cells_total    IS NOT NULL)),
    CHECK ((outcome = 'plan') = (cells_resolved IS NOT NULL)),
    CHECK ((outcome = 'plan') = (weekday_lanes_stated IS NOT NULL)),
    CHECK ((outcome = 'unavailable') = (cause_json  IS NOT NULL)),
    CHECK ((outcome = 'unavailable') = (observed_at IS NOT NULL)),
    CHECK (cells_resolved IS NULL OR cells_resolved <= cells_total),
    UNIQUE (plan_id, outcome)
) STRICT;
```

**No row for a binding ⇒ `None`.** `outcome='plan'` ⇒ `LanePlan`. `outcome='unavailable'` ⇒
`LanePlanUnavailable`. Three domain states, three storage states, no fourth representable, because
`binding_id` is `UNIQUE`.

Note what is deliberately **absent**: a `CHECK ((confidence='complete') = (cells_resolved =
cells_total))`. Three of the four designs wrote that constraint and all three got it wrong. The
producer computes (`providers/belegungsplan.py:816`, verified):

```python
complete = resolved.cells_resolved == resolved.cells_total and not resolved.unresolved_lanes
```

Dropping the second conjunct makes the constraint disagree with the producer for any plan whose
cells are *fully* resolved but which still has `unresolved_lanes` — the domain calls that `PARTIAL`,
the `CHECK` demands `complete`, and the insert becomes an `IntegrityError`.

**Correction (verified 2026-08-10).** An earlier revision of this document claimed those schemas
"fail on live data" and named `hallenbad-bungertwies` as the failing row. **That is wrong.**
Bungertwies is `partial` with `cells_resolved = 782`, `cells_total = 896` — so both sides of the
equality are false and the `CHECK` is satisfied. All seven live plans pass it: the six `partial`
rows are partial on cell count alone, and `hallenbad-city` is `complete` with `1344 = 1344`. The
constraint is a **latent** trap, not a live failure — it bites the first time a sheet resolves every
cell but leaves a lane unresolved. The argument for omitting it stands; the evidence offered for it
did not.

Storing a derivation *and getting it wrong* is the failure mode C1 exists to prevent;
the answer is not a better `CHECK`, it is no `CHECK`. `confidence` stays stored because deleting it
would collapse *closed* into *unknown* (`lane_plan.py:9-12`), and it is a fact about the parse
event, not a query-time derivation.

```sql
CREATE TABLE lane_plan_weekday_lanes (
    plan_id INTEGER NOT NULL REFERENCES lane_plan(plan_id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    lanes   INTEGER NOT NULL CHECK (lanes BETWEEN 1 AND 63),
    PRIMARY KEY (plan_id, weekday)
) STRICT;

CREATE TABLE lane_reservation (
    reservation_id INTEGER PRIMARY KEY,
    plan_id   INTEGER NOT NULL,
    outcome   TEXT NOT NULL DEFAULT 'plan' CHECK (outcome = 'plan'),
    ord       INTEGER NOT NULL,
    weekday_mask INTEGER NOT NULL CHECK (weekday_mask BETWEEN 1 AND 127),
    lane_mask INTEGER NOT NULL CHECK (lane_mask > 0),
    start_min INTEGER NOT NULL CHECK (start_min BETWEEN 0 AND 1439),
    end_min   INTEGER NOT NULL CHECK (end_min   BETWEEN 1 AND 1440),
    CHECK (start_min < end_min),
    access_id INTEGER NOT NULL REFERENCES access(access_id),
    section   TEXT,
    UNIQUE (plan_id, ord),
    -- reservations cannot hang off an 'unavailable' plan: engine-enforced, not conventional
    FOREIGN KEY (plan_id, outcome) REFERENCES lane_plan(plan_id, outcome) ON DELETE CASCADE
) STRICT;
```

*(Graft: the constant-discriminator + composite-FK arc is `full-3nf`'s, applied here once where it
earns its keep rather than eleven times where it does not.)*

The RLE form is preserved — 410 reservation rows, not a ~5,000-row dense per-lane-per-weekday grid.
`cqrs-readmodel` materialized that grid and dropped `PlanCoverage` with it, collapsing *closed* into
*unknown*: the exact honesty distinction `lane_plan.py` exists to defend.

### 4.6 Facility-level facts

```sql
CREATE TABLE notice (
    layer_id    INTEGER NOT NULL REFERENCES layer(layer_id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    active_from TEXT, active_to TEXT,
    CHECK (active_from IS NULL OR active_to IS NULL OR active_from <= active_to),
    PRIMARY KEY (layer_id, ord)
) STRICT;

CREATE TABLE closure (
    closure_id INTEGER PRIMARY KEY,
    layer_id   INTEGER NOT NULL REFERENCES layer(layer_id) ON DELETE CASCADE,
    ord        INTEGER NOT NULL,
    start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    CHECK (start_date <= end_date),                 -- inclusive
    reason     TEXT NOT NULL DEFAULT '',
    code       TEXT NOT NULL REFERENCES vocab_closure_code(code),
    params_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(params_json)),
    UNIQUE (layer_id, ord)
) STRICT;

CREATE TABLE price_table (
    price_table_id INTEGER PRIMARY KEY,
    layer_id       INTEGER NOT NULL REFERENCES layer(layer_id) ON DELETE CASCADE,
    valid_as_of    TEXT, source_url TEXT
) STRICT;

CREATE TABLE price_entry (
    price_table_id INTEGER NOT NULL REFERENCES price_table(price_table_id) ON DELETE CASCADE,
    ord        INTEGER NOT NULL,
    category   TEXT NOT NULL REFERENCES vocab_price_category(code),
    amount_chf TEXT NOT NULL CHECK (length(amount_chf) > 0),
    display    TEXT NOT NULL,
    min_age    INTEGER CHECK (min_age IS NULL OR min_age BETWEEN 0 AND 120),
    PRIMARY KEY (price_table_id, ord)
) STRICT;

CREATE TABLE admission (
    layer_id       INTEGER PRIMARY KEY REFERENCES layer(layer_id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('free','tariff','unknown')),
    price_table_id INTEGER REFERENCES price_table(price_table_id),
    CHECK ((kind = 'tariff') = (price_table_id IS NOT NULL))
) STRICT;

CREATE TABLE facility_scalars (
    layer_id INTEGER PRIMARY KEY REFERENCES layer(layer_id) ON DELETE CASCADE,
    public_holiday_policy TEXT REFERENCES vocab_holiday_policy(code),  -- NULL != NORMAL
    last_admission_before_min INTEGER CHECK (last_admission_before_min IS NULL
                                             OR last_admission_before_min > 0),
    season_start_month INTEGER, season_start_day INTEGER,
    season_end_month INTEGER, season_end_day INTEGER,
    season_precision TEXT REFERENCES vocab_date_precision(code),
    season_weather   TEXT REFERENCES vocab_weather(code),
    CHECK ((season_precision IS NULL) = (season_start_month IS NULL)),
    CHECK ((season_precision IS NULL) = (season_weather IS NULL))
) STRICT;

-- The declared JSON leaves. Identity-free, never joined, never filtered — the project's own
-- written rule ("blob only if identity-free AND never joined", data-layer-architecture.md).
-- tests/store/test_json_leaves.py asserts the set of columns ending in `_json` equals exactly:
--   basin.diving_platforms_json, basin.exceptions_json, closure.params_json,
--   lane_plan.cause_json, amenities.doc
CREATE TABLE amenities (                    -- lockers (42) + rentals (85) + feature hours (0)
    layer_id   INTEGER PRIMARY KEY REFERENCES layer(layer_id) ON DELETE CASCADE,
    schema_tag TEXT NOT NULL,               -- 'amenities/v1' — the codec version
    doc        TEXT NOT NULL CHECK (json_valid(doc) AND json_type(doc) = 'object')
) STRICT;

CREATE TABLE feature (
    feature_id INTEGER PRIMARY KEY,
    layer_id   INTEGER NOT NULL REFERENCES layer(layer_id) ON DELETE CASCADE,
    ord        INTEGER NOT NULL,
    kind       TEXT NOT NULL,               -- FK'd to vocab_feature_kind (seeded, 8 members)
    name       TEXT NOT NULL DEFAULT '',
    surcharge_chf TEXT, temp_c TEXT, note TEXT NOT NULL DEFAULT '',
    hours_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(hours_json)),
    UNIQUE (layer_id, ord)
) STRICT;
```

### 4.7 Calendar (singleton, now `STRICT`)

```sql
CREATE TABLE calendar_public_holiday (on_date TEXT PRIMARY KEY, name TEXT NOT NULL) STRICT;
CREATE TABLE calendar_school_holiday (
    ord INTEGER PRIMARY KEY, name TEXT NOT NULL,
    start_date TEXT NOT NULL, end_date TEXT NOT NULL, CHECK (start_date <= end_date)
) STRICT;
CREATE TABLE calendar_known_year (year INTEGER PRIMARY KEY CHECK (year BETWEEN 2000 AND 2100)) STRICT;
```

The calendar is city-wide, single-sourced, and has no producer contest. It gets no `layer` — which
is a deliberate, named C5 exception (§6), not an oversight: three of the four candidate designs
claimed universal attribution and then quietly exempted the same tables.

**Table count: 16 fact/spine tables + 12 vocabulary tables + 3 calendar tables.**

---

## 5. The Query abstraction

Location: `src/swimzh/storage/store/query.py`. Structure is `hybrid-spine`'s (composable filter
value + `AsOf` as a separate axis + two adapters bound by one contract suite); the C1 guard and the
`Result`-typed decode are `hybrid-spine`'s and `fact-ledger`'s respectively.

```python
# ---- what a Query IS -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Query[T]:
    """A declarative read request for SOURCE FACTS. Holds no SQL, no connection, no clock.
    `T` is always a persistable domain type — never a derived view (see the C1 guard)."""
    spec:   QuerySpec
    decode: Callable[[FactRows], Result[T, StoreError]]

    def map[U](self, f: Callable[[T], U]) -> Query[U]: ...

type QuerySpec = FacilitiesSpec | BasinsSpec | RosterSpec | CalendarSpec | LayerAuditSpec

# ---- composable selection (NOT string concatenation) ---------------------------------
@dataclass(frozen=True, slots=True)
class PoolFilter:
    ids:          frozenset[PoolId] | None = None
    kinds:        frozenset[PoolKind] | None = None
    near:         tuple[GeoPoint, float] | None = None
    has_schedule: bool | None = None        # EXISTS(schedule_rule) — a source fact
    has_lane_plan: bool | None = None

    def ids_in(self, *ids: PoolId) -> PoolFilter: ...
    def kind_in(self, *kinds: PoolKind) -> PoolFilter: ...
    def within(self, centre: GeoPoint, radius_m: float) -> PoolFilter: ...
    def with_schedule(self, yes: bool = True) -> PoolFilter: ...
    def with_lane_plan(self, yes: bool = True) -> PoolFilter: ...
    def __and__(self, other: PoolFilter) -> PoolFilter: ...      # total, commutative

@dataclass(frozen=True, slots=True)
class AsOf:
    """WHICH LAYERS compose — never a content filter, and never a domain moment."""
    only_producers: frozenset[ProducerId] | None = None   # None == fold by precedence
    run_id: RunId | None = None                           # None == latest

# ---- the ONLY constructor surface ----------------------------------------------------
class Q:
    @staticmethod
    def facilities(where: PoolFilter = PoolFilter(), as_of: AsOf = AsOf()
                   ) -> Query[tuple[Facility, ...]]: ...
    @staticmethod
    def facility(pool_id: PoolId, as_of: AsOf = AsOf()) -> Query[Facility | None]: ...
    @staticmethod
    def basins(where: PoolFilter = PoolFilter(), as_of: AsOf = AsOf()
               ) -> Query[tuple[tuple[PoolId, Basin], ...]]: ...
    @staticmethod
    def roster(as_of: AsOf = AsOf()) -> Query[tuple[RosterEntry, ...]]: ...
    @staticmethod
    def calendar() -> Query[ZurichCalendar]: ...
    @staticmethod
    def layer_audit(pool_id: PoolId | None = None) -> Query[tuple[LayerRow, ...]]: ...

# ---- the port + errors as values -----------------------------------------------------
@dataclass(frozen=True, slots=True) class SchemaVersionMismatch: found: int; expected: int
@dataclass(frozen=True, slots=True) class DecodeFailure:         table: str; detail: str
@dataclass(frozen=True, slots=True) class StoreUnavailable:      path: str; detail: str
type StoreError = SchemaVersionMismatch | DecodeFailure | StoreUnavailable

class GoldQueryRunner(Protocol):        # src/swimzh/storage/store/ports.py
    def run[T](self, query: Query[T]) -> Result[T, StoreError]: ...
```

**Why one abstraction genuinely serves both consumers.** The Query layer returns *source facts*;
the domain computes *answers*. Both `/swim` and the board therefore ask the same thing and differ
only in which pure domain function they apply:

```python
# /swim — per-moment eligibility
facs = runner.run(Q.facilities(PoolFilter().with_schedule().within(here, 3000)))
options = find_swim_options(facs.unwrap_or(()), calendar, moment)   # domain/query.py, unchanged

# board BFF — per-basin day views / lane strips
pool = runner.run(Q.facility(pool_id)).unwrap()
panels = tuple(lane_panel(b, on=day) for b in pool.basins)          # domain/lane_plan.py, unchanged
```

Two notes that matter, both learned from the candidates' failures:

- **`Q.facilities()` returns whole `Facility` aggregates, and the board uses it too.** `cqrs-readmodel` built a per-basin-per-weekday read model and then discovered it had no closures, no exceptions and no holiday policy, so its board would render sessions on a Revision day while `/swim` fell back to the blob anyway. A day view needs the whole facility. `Q.basins()` exists for narrow diagnostics, not as the board's path.
- **No constructor takes a `date`, a `datetime`, or a `Person`.** That is the mechanical C1 test: *if a proposed read needs a moment, it belongs in `domain/`, not here.* `AsOf` is about which producer layers compose, not about when the swimmer wants to swim.

**Faking.** Two adapters, both production code (clean-architecture skill §3 — the repo has no
in-memory `SwimStore` today, which is why `apps/web/tests/conftest.py:37-47` builds a real DB to
test a router):

```python
class SqliteGoldQueryRunner:            # storage/store/sqlite_runner.py — the sole SQL author
    @staticmethod
    def open(path: Path) -> Result[SqliteGoldQueryRunner, StoreError]: ...   # mode=ro&query_only=1
class InMemoryGoldQueryRunner:          # storage/store/memory_runner.py
    @staticmethod
    def of(facilities: tuple[Facility, ...], calendar: ZurichCalendar,
           layers: tuple[LayerRow, ...] = ()) -> InMemoryGoldQueryRunner: ...
```

bound by `tests/store/test_query_runner_contract.py`, parameterized over both, asserting identical
`Result` values for every spec × filter combination. Plus `test_every_query_compiles.py`, which
`EXPLAIN`s every `Q.*` against the head schema — *(graft: `cqrs-readmodel`, its second good idea)*.

**Execution model does not change.** `GoldSwimStore` keeps the `SwimStore` Protocol and its four
methods; `open()` still runs `Q.facilities()/roster()/calendar()` once inside `lifespan`
(`main.py:123-133`) and serves `/pools/{id}` from `_by_id`. `apps/web/deps.py` is untouched. This is
a change of *storage*, not of *execution model* — and any claim to the contrary should be treated
as scope creep.

---

## 6. C1–C5, with enforcement sites

| # | Constraint | How it is satisfied | **Enforcement site** |
|---|---|---|---|
| **C1** | Derived values never stored | No table or column for `lane_availability`, `lane_day_view`, `club_roster`, `best_public_time`, `day_schedule`, `swim_option`, `curation_status`, `ScheduleFreshness`. `PlanCoverage` counts are stored because they are facts about the *parse event*, unrecoverable from RLE rows (`lane_plan.py:9-12`) — and pointedly carry **no** `confidence`-derivation `CHECK`, because `belegungsplan.py:816` includes an `unresolved_lanes` conjunct that three candidate designs dropped and would have rejected live `bungertwies` data. | `tests/store/test_query_returns_source_facts_only.py` — introspects `get_type_hints` on every public `Q.*`, flattens the `Query[...]` parameter, asserts every named class ∈ `PERSISTABLE` and ∉ `DERIVED` (imported by name from `lane_plan.py:88-282`, `schedule.py:252-296`, `query.py` view types). *(graft: `hybrid-spine`)* Plus `tests/store/test_forbidden_tables.py` on the schema text. *(graft: `fact-ledger`)* |
| **C2** | Closed unions survive; illegal states unrepresentable | `SessionAccess`: discriminator + **generated-column FK into `vocab_access_shape`**, seeded from `dataclasses.fields()` over `typing.get_args(SessionAccess)` — zero hand-written coupling literals (§4.2). `Basin.lane_plan`: 3 storage states, `binding_id UNIQUE`, no fourth representable. `Admission`: biconditional `CHECK`. **No `NULL` in any `UNIQUE` tuple**, so interning and 3-state decoding cannot degrade into an `N rows` case. | **Primary: the compiler.** `store/rows.py` holds `access_to_row` / `access_from_row` as a total bijection, both ending in `assert_never`, under `mypy --strict` — the same mechanism as `mapping.py:245/273`. The decode side parses the TEXT discriminator into `AccessKind` (a `StrEnum`) *first*, so `assert_never` narrows properly. **Secondary:** `tests/store/test_vocabulary.py` (`set(db) == set(enum)` for all 12 vocabularies + the 11 access shapes). **Tertiary:** round-trip over `REPRESENTATIVE_ACCESS`, itself already pinned to the union at `tests/domain/test_eligibility.py:102`. The DB is a *net under* the type checker, never a replacement — anyone reading this as "the database now enforces the union" is wrong. |
| **C3** | Errors are values | `LanePlanUnavailable` is a first-class `outcome` arm with `cause_json` round-tripped through the **existing** `ProviderErrorDTO`, whose 10-arm `assert_never` guards at `mapping.py:423/449` already prove losslessness today. Zero tables invented for zero rows. `QueryRunner.run` returns `Result[T, StoreError]` over a closed 3-arm error union. | `tests/boundary/` round-trip (existing, unchanged) + a new parameterized round-trip over all 10 `ProviderError` arms through `lane_plan.cause_json`. `StoreError` exhaustiveness: `assert_never` in every consumer, `mypy --strict`. |
| **C4** | Cadence rule | No `occupancy`, no `water_temperature`, **no `basin.measured_temp_c`** — it is a live reading living inside a stored dataclass (`models.py:174`, `None` on all 33 basins), and creating the column would re-open the bypass `docs/concepts/water-temperature-provider.md:110` closed. `nominal_temp_c` *is* stored: `models.py:169` calls it a design target, a different fact. `feature.temp_c` is stored on the same footing as the rest of `Feature`, which `models.py:205` documents as static. | `tests/store/test_forbidden_tables.py` asserts the schema text matches none of `occupancy`, `measured_temp`, `water_temp`, `freshness`, `curation_status`, `lane_availability`, `day_view`, `club_roster`, `best_public_time` — with `nominal_temp_c` explicitly allowlisted and the reason written next to it. Turns C1 and C4 from prose into a red gate. |
| **C5** | Source attribution | Every fact table's parent is a `layer(pool_id, producer_id, aspect)` row with a `NOT NULL` FK, so an unattributed fact is a write-time `IntegrityError`. `layer` FKs `producer_run`, so `fetched_at`/`run_id`/`input_digest` are per-partition rather than facility-granular as `Provenance` is today. **Three named exceptions, stated rather than hidden:** `pool`/`pool_alias`/`pool_xref` (identity is deliberately single-truth, §4.3); `club` (a shared dictionary, no producer contest); the three `calendar_*` tables (city-wide singleton, one source). | `tests/store/test_attribution.py` — parses `schema.sql`, asserts every table not on the three-name exception list has a `layer_id` column with a `NOT NULL … REFERENCES layer` clause. The exception list is a literal in the test, so adding an unattributed table is a review-visible diff, not a silent drift. Every one of the four candidate designs claimed universal C5 and quietly exempted its dictionary tables; this one names them. |

**The defect itself** (structurally impossible, four independent mechanisms):

1. **Type-level.** `write_schedules(conn, keyed: tuple[tuple[PoolId, Facility], ...])` — today the sole writer of `facility_doc` and the mouth the fold's output goes back into — is *deleted*. Its replacement is `write_layer(conn, *, run: RunId, producer: ProducerId, pool_id: PoolId, facts: AspectFacts) -> Result[LayerId, StoreError]`, where `AspectFacts` is a closed union and `Facility` is not a member. **No `Facility → rows` mapper exists anywhere in the tree.** `cli.py:346`'s `compose(curated, outcome.resolved)` has nothing to persist and `cli.py:338`'s `GoldRepository(conn).load_all()` has no consumer. *(graft: `fact-ledger`, the single best idea in the set — and it needs none of the 37 tables it was packaged with.)*
2. **Key-level.** `layer UNIQUE(pool_id, producer_id, aspect)`, and `write_layer` is `DELETE FROM layer WHERE pool_id=? AND producer_id=? AND aspect=?` followed by an insert. A producer replaces its own partition and cannot see, let alone overwrite, another's. `_has_schedule(curated_basins)` has nothing to fire on: for a scraped-only pool, `EXISTS(curated basins claim)` is false on every run, forever.
3. **Layer-level.** `tests/test_layering.py` — which already forbids `domain/** → swimzh.build` by import-token regex — gains: `build/**` and `etl/**` may not import `swimzh.storage.store.read_model` or `…store.query`. The composing half is walled off from the writing half. This is grep, not the compiler, and it is stated as such.
4. **Observability.** `producer_run(input_digest, rows_written, status)` makes a no-op re-layer a *visible row*. `swimzh verify` fails when a producer's latest successful run wrote zero rows for a pool that declares a source for that aspect. Today the defect exits 0 with no read-path signal at all.

**And the guard the defect fix creates, which no candidate design had:** replace-my-partition
converts silent staleness into silent *deletion*. If the City page changes and the parser yields
zero rules, `write_layer` deletes 171 rows and inserts none; `/swim` empties; status `ok`. Today's
`CURATED_WINS` accidentally protects against this. **`write_layer` must therefore take a
`FactsOutcome = Facts(rows) | NothingFound | Failed(ProviderError)` rather than a bare row tuple,
and only `Facts` may replace a non-empty partition; `NothingFound` against a previously non-empty
partition is a build error.** This is not optional garnish — it is the price of mechanism 2.

---

## 7. Migration — sliced to ship incrementally

The store is git-ignored and rebuilt from committed text, so "migration" means *pipeline*
migration, never data migration of a precious database. Slices 0–3 are additive and revert-by-commit.

**Slice 0 — prerequisites, no new tables. Ship this regardless of everything else.**
- Assert `PRAGMA user_version` at open (it is `0` today; `data-layer-architecture.md` specifies it and it was never implemented). Make `calendar` `STRICT` like its three siblings.
- **Convert `write_pools` from `DELETE FROM pool` + insert to upsert + delete-missing.** This is a hard prerequisite for *any* design that hangs facts off `pool(id) ON DELETE CASCADE`, and it is the single most-missed dependency across all four candidates.
- Fix the stale docstring at `sqlite_repo.py:216-219` (the `facility_doc IS NOT NULL` filter is a no-op — all 57 rows carry a blob).
- Add `producer` / `producer_run`, stamp every existing writer with a run row. **This alone gives the first real signal on the defect**: two consecutive `scrape-gold` runs producing identical `input_digest` with no downstream change is currently invisible.

**Slice 1 — the defect fix, on the current storage shape.** Add `layer` and one blob column per
partition (`layer_doc`, using the *existing* `StoredFacilityDTO` codec). Re-point `cli.py:338`'s
curated input at `data/` YAML through `boundary/curated_dto`. Delete `write_schedules`; add
`write_layer` with the `FactsOutcome` union. Move `_ASPECTS` to `store/precedence.py` and fold at
read. Land the regression test the defect report asks for as its option-4 minimum: *mutate a
fixture's notice text **and** a price entry (both non-basin aspects), re-layer, assert the stored
values changed and `fetched_at` advanced.* **The defect is dead at the end of this slice, with
roughly three new tables.** If the project stops here, it has bought the fix and none of the cost.

**Slice 2 — normalize the join surface.** Add §4.2–4.6's tables. Write `store/rows.py`. Dual-write
(partition blob **and** rows) with two gates: `hydrate(materialize(f)) == f` for all 57 live
facilities, and every `layer_doc` reproducible from its rows. Nothing reads the rows yet.

**Slice 3 — flip the read.** Implement both runners plus the contract suite; shadow-test
`Q.facilities()` against `GoldRepository.load_all()` element-wise on the live DB; flip one line in
`lifespan`. `/swim`, `/pools`, `/pools/{id}`, `/access-types` responses must be byte-identical
under the existing API snapshot tests. Free fix that lands here: `PoolCatalogEntry.poi_id` stops
being dropped. Widen `apps/web/tests/api/test_single_source_of_truth.py::_runtime_source_files()`
to rglob `src/swimzh/**` — otherwise this slice *widens* the enforcement hole recorded at
`data-sourcing-rule.md` §1 before closing it.

**Slice 4 — delete the blobs.** Drop `pool.facility_doc` and `layer_doc`; delete `storage/codec.py`
and `calendar_codec.py`; keep `boundary/curated_dto.py`'s *ingest* half (curated YAML still
validates through pydantic) and its `ProviderErrorDTO` (still the `cause_json` codec). Bump
`user_version`.

**Sequencing against work in flight.** `docs/plan/2026-08-09-lane-stack-board-plan.md` (draft,
`pause_after: [S1, S3]`) edits `compose.py::_carry_bindings`. **Land it first, unchanged, on the
current code.** Its invariants — I1 (rules copied from *the single* rules-bearing scraped basin,
loud failure on >1) and I2 (the carried basin keeps its own `basin_id`, `name`, `lanes`,
`dimensions`, `lane_plan_source`, `lane_plan`; only `rules` is added) — then transfer into the
read-time fold as `lane_binding`-keyed tests. Slices 0 and 2 are parallel-safe with it; slice 1
conflicts textually with `compose.py` and should wait.

---

## 8. What this costs, and what could still go wrong

**The strongest argument against doing any of this, stated fairly.** `techdebt-remediation-roadmap.md`
item **#6a-rows** declined full row-normalization as *"additive structure, not on the simplicity
path."* That judgement is still substantially correct, and the new information does not overturn all
of it. The store is ~1,900 rows and 173 KB — every performance argument is void; the entire case
rests on write-side attribution. And the defect report itself ranks **option 2** (re-layer from
`data/` sources instead of from the store) as *most contained*: that is roughly a two-file change to
`cli.py:338` that fixes the same bug this week, and it is what Slice 1 is. **If the owner takes
Slice 0 + Slice 1 and stops, they will have fixed the defect and #6a-rows will still stand,
correctly.** Slices 2–4 buy DB-enforced invariants, per-aspect freshness observability, the
`poi_id` fix, the `Unknown`-vs-absent distinction and visibility of the 50 dirty club strings —
real things, none of them urgent, none of them a bug. Anyone who says "you proposed 16 tables to
fix a bug a two-file change fixes" is right about slices 2–4 and wrong only about slice 1. The
honest framing is: **#6a-rows should be amended, not reversed** — from "declined" to "declined for
the long tail; accepted for the join surface, contingent on the producer partitioning landing
first."

Other costs, without decoration:

1. **The type checker remains the real C2 guard; the DB is a weaker net.** The generated-column FK is the strongest SQL-level union encoding available in SQLite, and it still cannot express "exactly one arm row exists" for anything requiring cross-table assertion. A direct `sqlite3` session can leave a store that hydrates into a crash. C2 lives in `rows.py` under `mypy --strict`, exactly as it lives in `mapping.py` today.
2. **Generated columns + composite FK is the least-travelled part of this design.** It works, but it is unusual enough that it needs a dedicated test proving all eleven arms are accepted and eleven mismatched shapes are rejected, and a comment explaining it, or the next reader will "simplify" it back into hand-written `CHECK` lists — which is precisely how three of the four candidate designs acquired wrong enum literals.
3. **Ordinal columns are the blob's revenge.** `basin`, `schedule_rule`, `notice`, `closure`, `feature`, `price_entry`, `lane_reservation`, `pool_alias` carry `ord` purely so `hydrate(materialize(f)) == f` holds. Order was free in JSON.
4. **Read-time composition moves the fold onto the startup path.** A `precedence.py` bug is now a bug everywhere, where today the codec is dumb. Mitigated by the contract suite and the shadow-read oracle; the risk is real and is new.
5. **Debuggability regresses.** `SELECT facility_doc … | jq` shows a human everything. A `layer_audit` view is not the same affordance. This cost is permanent.
6. **`Decimal`-as-TEXT cancels part of the queryability being sold.** You cannot `SUM(amount_chf)` or `WHERE surcharge_chf > 5` without a `CAST` that is wrong on exotic values. Prices, fees, deposits, temperatures and dimensions are opaque to SQL.
7. **Bitmasks are paid for twice.** `weekday_mask` keeps `schedule_rule` at 171 rows instead of 806, but no index answers "which rules include Wednesday"; that query is a scan (fine at this size) and ad-hoc SQL becomes unpleasant. A 64-lane pool needs a schema change; the `CHECK` at least makes it loud.
8. **Invariants are now stated in two languages.** `start_min < end_min` lives in `TimeRange.__post_init__` *and* in a `CHECK`. Every one of those is a second place to change and to get out of sync. The vocabulary tests catch enum drift; they do not catch a relaxed dataclass invariant.
9. **`crap.py` will fire on the fold and the mappers** (`cc > 5 AND crap > 30`). Both must be decomposed one-function-per-type, and `fail_under=95` coverage over all of it is real, tedious work.
10. **Cross-producer basin identity is improved but not solved.** `lane_binding` makes the lane crosswalk survive as a real key rather than a URL string match inside a fold. Everything *else* about basin identity — the synthetic `Hauptbecken` flattening at `etl/scrape.py:180`, 32 of 33 basins sharing one name — is untouched. Normalization makes the failure visible as an orphaned row instead of invisible inside a blob; it does not fix identity.
11. **`FactsOutcome` is a new discipline that can be got wrong.** If a producer reports `Facts(())` where it means `NothingFound`, the partition empties and the pool disappears from `/swim` at exit 0. The guard exists; the burden is on every producer author to use the right arm.
12. **Slices 1 and 4 are the one-way doors.** After slice 1, `compose.py`'s write-time fold is gone and reverting means reverting the slice. After slice 4, the blob is gone.

---

## 9. Open questions only a human can settle

1. **Do slices 2–4 happen at all?** Slice 1 fixes the defect. Everything after it is an investment in constraint enforcement and observability with no bug attached. This is a values call about how much the project wants its invariants in the engine versus in `mypy`, and only the owner can make it.
2. **Should `#6a-rows` be amended in the roadmap before any code lands?** A design document silently overriding a recorded decision is worse than the decision being wrong. Proposed amendment text is in §8; it needs an owner's signature.
3. **`club` canonicalization is a curation decision with no source of truth.** Is `"SV Zürileu"` the same club as `"Schwimmverein Zürileu"`? Is `"Behinderten-Sport Club"` the same as `"…Club Zürich"`? No normalizer decides this. Someone must either author `club_alias` rows or accept that `club_roster` keeps double-counting.
4. **Snapshots / history.** Every candidate design proposed bitemporal columns (`valid_from`/`valid_to`) and every one admitted the dimension is degenerate on today's data. This document omits them. If "what did the schedule say last month" is ever a requirement, that is a different schema and should be decided *before* slice 2, not retrofitted.
5. **Two producers claiming the same aspect within one tier.** Precedence is by `tier`, mirroring `compose.Source` exactly. A second scraped producer for `notices` has undefined ordering. Extending to `producer_id` granularity is easy but should be a deliberate decision, not a surprise.
6. **`ScheduleException` is a `DROP_CANDIDATE` with 0 rows.** This design parks it in `basin.exceptions_json`. Should it be *deleted from the domain* instead? That is a domain decision, not a storage one.
7. **How aggressively should `swimzh verify` fail?** "This producer ran and its `fetched_at` did not advance" is the signal the defect report wanted. Whether that is a warning or a non-zero exit determines whether a flaky upstream page breaks the weekly build.
