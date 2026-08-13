---
type: concept
name: data-sourcing-rule
status: proposed
created: 2026-08-10
updated: 2026-08-10
links: ["[[gold-store]]", "[[data-layer-architecture]]", "[[techdebt-remediation-roadmap]]", "[[2026-08-10-scrape-gold-recompose-defect]]", "[[lane-data-availability]]"]
---

# Where application data comes from

**Status: proposed.** One clause (normalization) is an **open decision awaiting the requester** —
see [Open decisions](#open-decisions). Nothing here is settled.

## What was asked (verbatim)

The requester's own words, unedited — the anchor this document is measured against. Same rule as a
plan's Intent block: no agent may paraphrase it.

**2026-08-10**

> so we have to define new rule that data used in the application cannot be take from silver or
> scrape; only from golden tables; exception to this may be data providers that needs fres data like
> temperature, number of people; gold sqlite tables must be normalize and hold all data that we have;
> and api and backend and frontend must source from it; please challgen this rule

### Disposition of each clause

The request was to **challenge** the rule. A challenge produces a recommendation; it does not
transfer the decision. Where this document departs from what was asked, the departure is named here
rather than buried in the prose.

| # | As asked | Disposition | Where |
|---|---|---|---|
| a | app data only from gold, not silver/scrape | **carried** — and already true and enforced | Rule 1 |
| b | exception for providers needing fresh data (temperature, people) | **reframed** — criterion changed from "fresh" to build cadence | Rule 2 |
| c1 | gold holds all data we have | **narrowed** — all *source facts*; derivations explicitly excluded | Rule 3 |
| c2 | gold tables must be **normalized** | **DECLINED — recommendation only, decision open** | [Open decisions](#open-decisions) |
| d | api + backend + frontend must source from it | **carried, with a bound added** | Rules 4 and 6 |

## The rules

1. **The application reads domain facts only from gold.** No runtime read of `data/*.yaml`,
   `catalog.json`, or any silver/scrape artefact.
2. **One exemption: values that change faster than the build cadence can bake them.** Such a value is
   served through a typed provider port whose return type carries an explicit *unavailable* arm —
   never a bare optional, never a silent zero.
3. **Gold holds every source fact, each attributed to exactly one producer. Gold holds no
   derivation.** Derived values stay pure and query-time.
4. **The API and backend serve domain facts only from gold; the frontend takes domain facts only
   from the API.** No layer introduces a domain fact of its own.
5. **Each ETL phase writes only the facts it owns, and re-running it is idempotent.** No phase
   composes over another phase's composed output.
6. **Presentation configuration is not a domain fact** and does not belong in gold. This bounds
   rule 4; it does not weaken it.

## Why each rule is worded the way it is

### 1 — already true, and already enforced

[[gold-store]] is the single source of truth the app reads; the composition root opens nothing under
`data/` at runtime and a missing DB fails fast. `apps/web/tests/api/test_single_source_of_truth.py`
enforces it mechanically:

```python
FORBIDDEN = ("catalog.json", ".yaml", "load_dataset")
```

Recorded for completeness, not as a change. **The test is the enforcement** — strengthen it, not this
prose.

**Known gap in that enforcement:** `_runtime_source_files()` rglobs `apps/web` only. An `apps/web`
module that reaches curated data through a `swimzh` helper containing none of the three tokens would
pass — `src/swimzh/providers/curated.py:20,146` (`import yaml`, `load_dataset`) is unscanned. The
rule is stronger than its guard.

### 2 — the criterion is cadence, not "freshness" *(a reframe of what was asked)*

The request said "data providers that needs fres data". That criterion does not separate water
temperature from timetables: seasons re-cut schedules too, and the project already refreshes those by
re-layering `scrape-gold` / `scrape-lanes` on their own cadence. The distinction that holds is
**whether a value's useful lifetime is shorter than the interval between builds**. Occupancy at
minute granularity cannot be usefully baked; a seasonal timetable can, and therefore must be.

The required shape already exists — `OccupancyResult = LiveOccupancy | OccupancyUnavailable`
(`query.py:128`), and the water-temp provider's `LiveTemp` / `TempUnavailableCode` (`query.py:174,186`).
Phrased as "fresh data may bypass gold", the exemption would licence bypassing gold for anything an
author called fresh; phrased as a cadence test plus a mandatory *unavailable* arm, it does not.

### 3 — "all the data we have", narrowed to exclude derivations *(a narrowing of what was asked)*

**Every source fact, attributed.** The gap today is not that facts are missing but that a stored
`Facility` does not record *which tier* supplied each part of it. That is what makes
[[2026-08-10-scrape-gold-recompose-defect]] possible: the blob cannot distinguish "curated states
these hours" from "we scraped these hours last Tuesday", so a re-composition mistakes its own output
for an input.

`etl/field_sourcing.py` is adjacent but is **not** this: it assigns each serialized `facility_doc`
field to exactly one producer, and its own docstring calls it *"an AUDIT artifact, not a runtime data
path"* — a static field→producer table, not per-record provenance in the store. Rule 3 needs the
latter, so most of it is unbuilt.

**No derivation, ever.** The domain states this at nine sites under `src/swimzh/domain/`
(ten repo-wide, counting `storage/codec.py:84`) and depends on it:

```
lane_plan.py:88   # --- Derived (query-time, DTO-free, never stored) ---
lane_plan.py:100  A pure derivation of the stored `LanePlan` — never stored, never serialised.
query.py:275      pure derivation of the stored plan — never stored.
```

`lane_availability_at`, `lane_day_view`, `club_roster`, `best_public_time` and live-occupancy
freshness are computed per query. That is *why* they answer correctly for a future date. Storing them
would bake one date's answer into the store and make the week planner stale or
invalidation-dependent. "Gold holds all data we have", read literally, would be cited to store
exactly these — hence the carve-out.

### 4 and 6 — the layer clause, and its bound

Rule 4 is the request's clause (d) as asked. Rule 6 exists because the frontend legitimately holds
data that is *not* a domain fact: the locale files, and the landmark presets (`app.ts:75-79`,
`PLACE_PRESETS`) introduced by [[2026-07-19-ux-ascii-design]] S3. A strict reading of clause (d)
would force those into gold, which would be wrong.

Where the line is unclear, the test is whether a swimmer could observe the value being *wrong*: a
pool's hours can be wrong; a dropdown's default cannot.

### 5 — idempotent phases, which is the actual defect

`scrape-gold` loads the composed blob as its `curated` input, re-composes, and writes back. On a
second run `_has_schedule(curated_basins)` (`compose.py:216`, defined `:103`) is `True`, the branch
flips to curated-wins-wholesale, and the freshly scraped timetable is discarded with exit code `0`.
Reproduced end to end in [[2026-08-10-scrape-gold-recompose-defect]].

The general form: **storing the result of a fold and then feeding that result back into the same fold
is unsound unless the stored form distinguishes inputs from outputs.** Rule 3's attribution is what
makes rule 5 achievable; rule 5 is the property worth testing.

## Open decisions

### Normalization (clause c2) — SETTLED 2026-08-10: amended, not declined

**Resolution.** The requester asked for normalization; an earlier revision of this document
recommended declining it outright. A 12-agent design study ([[gold-schema-design]] — four rival
schemas, adversarial critique each, three independent judges, synthesis) produced a **third answer,
which is the one adopted**:

> **Normalize the write door, not the whole aggregate.** The re-compose defect is a *write-door*
> defect — fixed by producer partitioning plus deleting the `Facility`-accepting write signature,
> roughly **three** tables. Row-normalizing the join surface (~16 tables) is a **separable second
> investment**, not a prerequisite. The long tail stays typed JSON, justified by measured row counts:
> lockers 42, rentals 85, schedule exceptions 0, provider-error arms 0, feature hours 0.

So [[techdebt-remediation-roadmap]] item **#6a-rows is amended, not reversed** — the requester's
instinct that the blob was the problem was right; the scope was larger than the problem required.

The counter-case the study was told to state fairly, and the judges' disagreement (domain-purist
picked full 3NF; operator and consumer picked the hybrid), are recorded in [[gold-schema-design]]
rather than summarized here. Read that before acting on this.

**Superseded below.** The argument that follows is the earlier recommendation-to-decline, kept
because its evidence is still the reason the *large* version is not adopted.

Arguments against, with their weaknesses stated:

- **Little read-side benefit.** `GoldRepository.load_all` runs **once at startup**
  (`gold_store.py:37` ← `main.py:127`); per-request lookups hit an in-memory dict
  (`gold_store.py:31,56`). So there is no per-query SQL to optimize at all — normalization would not
  change the read path, because the read path is already RAM. *(Correction: an earlier draft of this
  document claimed the app "loads every facility on every query". That was wrong. The conclusion is
  unchanged and arguably stronger; the error is recorded because it ran in this argument's favour.)*
  *Weakness:* `sqlite_repo.py:230` `get()` does do a selective `WHERE id = ?` read, so the schema is
  not wholly join-free today.
- **The domain is sum-typed.** 75 domain dataclasses; `SessionAccess` is an **11**-variant closed
  union (`access.py:102-114`; `REPRESENTATIVE_ACCESS` at `:205-216` has 11 entries, with a
  completeness test pinning the two together); `Basin.lane_plan` is
  `LanePlan | LanePlanUnavailable | None` (`models.py:185`) carrying a `ProviderError` union
  losslessly. *(Correction: an earlier draft said 13 variants. Also wrong, also in this argument's
  favour.)* Today `mypy --strict` plus `assert_never` guards enforce exhaustiveness at compile time.
  *Weakness:* the usual encodings — table-per-variant with a discriminator, or one wide nullable
  table — are not the only options; a discriminator table paired with a codec-level exhaustiveness
  test is a real third path this document does not cost out.
- **The write-side win may be obtainable more cheaply.** The genuine case for normalization is
  targeted updates instead of read-modify-write over a whole aggregate — which is exactly
  [[2026-08-10-scrape-gold-recompose-defect]]. **Expectation, not fact:** rules 3 and 5 should
  deliver that without a schema migration. Neither is built, so this is a prediction.

Prior art, not a verdict: [[techdebt-remediation-roadmap]] lists this as **#6a-rows** and left it
as-is (`techdebt-remediation-roadmap.md:59`). That was a decision taken before the re-compose defect
was known, so it is evidence, not precedent — the defect is new information that cuts the other way.

**To settle this, the requester picks one:** (i) accept the recommendation and close c2; (ii) reject
it and open a normalization plan; (iii) defer until rules 3 and 5 are built and re-evaluate with
evidence.

### Enforcement

Rules 3–6 have no test behind them. Rule 1 shows the pattern worth copying — a grep-assertion is what
has kept it true. Rule 5 is the most valuable to mechanize: "re-running a phase with changed source
data changes the store" is directly testable, and its absence is exactly why
[[2026-08-10-scrape-gold-recompose-defect]] shipped.
