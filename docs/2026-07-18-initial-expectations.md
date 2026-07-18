# Initial expectations & design decisions — 2026-07-18

This document is the human-readable companion to the implementation plan. It records
what the project owner asked for, what the research found, how two adversarial design
reviews reshaped the approach, and the decisions taken. It is the onboarding doc for
the repository.

---

## 1. The question the app must answer

> Given **who I am** (gender, age), **where I am** (location), and a **date/time**
> (current *or* future) — where can I go swimming in a Zürich **indoor** pool, when,
> under what **access rules** (public swim / women-only / seniors / school-reserved),
> and at what **price**?

The owner wants an easy way to answer "where can I go swim?" for themselves, with the
person modelled by gender, age, location, and a date that may be in the future.

---

## 2. Owner's initial expectations (verbatim intent)

Captured from the owner's own framing, preserved so later decisions can be traced back:

- **Design first**: define **contracts, clean data models, and the surface of
  services/interfaces** before implementation.
- **Data providers as adapters**: implement providers that supply information, whether
  from an **API** or via **web scraping / parsing**.
- **Record-once / replay integration tests**: low-level data providers with integration
  tests that capture HTTP responses locally — the **first run is "paid"** (real network),
  the **second run replays from file**, so runs are reproducible and testable. Implies a
  **caching library that saves files to disk**.
- **Well-typed + well-tested contracts**, especially around **network issues**.
- **Standardised errors across providers** — a `provider/core` layer so downstream systems
  know what to expect on error paths.
- **Errors as values, not exceptions** — typed values. Use **`Either(Ok, Err)`**, with
  `Err` a **union** allowing **exhaustive pattern matching** on the consumer side and
  better compile-time type checking. (Success payloads may differ per provider; the
  **error union is standardised**.)
- **Build datasets from providers**: store data in **SQLite or LanceDB** as the source of
  truth, updated by an **ETL / scheduled process** following a **raw → silver → gold**
  (medallion) pattern that reads and cleans data.
- **Orchestration**: use **Dagster**, run with **uv**; install **Claude skills for Dagster
  best practices** (newest version) to guide the modelling.
- **UI last**: once clean data is in the database, any UI can be built on top.
- **Review**: delegate the design to a subagent for scrutiny before finalising.

---

## 3. Data landscape (research findings)

Zürich swimming-pool data splits into three tiers:

| Data | Availability | Source |
|------|--------------|--------|
| Pool **locations + facility metadata** | ✅ Clean open data (CC0, JSON/GeoJSON) | `geo_sport` dataset, data.stadt-zuerich.ch (CKAN API) |
| **Live occupancy** (Auslastung), incl. indoor | ⚠️ Live but risky | *CrowdMonitor* commercial sensor feed surfaced via city pages — ToS unclear, coverage intermittent; only relevant when query time ≈ now |
| **Opening hours, public-swim windows, women-only / senior / school-reserved slots, prices, maintenance closures** | ❌ Not machine-readable anywhere | HTML/PDF on stadt-zuerich.ch (+ semi-structured third-party badi-info.ch) |

**Indoor pools (v1 universe)**: Altstetten, Bläsi, Bungertwies, **City** (50 m, longest hours),
Leimbach, **Oerlikon** (50 m), Wärmebad Käferberg, plus five school pools with public hours.

**Baditicker API**: official, JSON, but covers **outdoor** pools (water temp + open/closed)
and is **seasonal** (off in winter). Not useful for indoor availability.

### Existing apps (the gap)

Live-occupancy dashboards already exist and are numerous: **badifrei.ch**, **welchebadi.ch**
("Züri Badi"), **hallenbad-auslastung.ch**, **badinow.ch**, **züribadi.ch**, **badi-info.ch**.
They answer *"how full is the pool right now."* **None** answer the eligibility/schedule/price
question filtered by **who you are** and a **future date**. That gap is the product.

---

## 4. The reframing (two adversarial reviews)

Two independent review subagents critiqued the first design. Both converged on one point:

> The original plan **over-invested in *fetching*** (providers, orchestration, caching) and
> **under-modelled the actual hard problem**: resolving a pool's schedule for an **arbitrary
> concrete date**. A weekly grid cannot answer future dates, because real schedules are
> governed by **school-term vs school-holiday (Ferien) calendars, public holidays,
> maintenance "Revision" weeks, and one-off exceptions**.

So the **schedule resolver** and an **explicit pool-identity registry** are the core, and the
typed-adapter / error machinery is applied where it earns its keep — not uniformly.

---

## 5. Decisions taken

**Contracts & types**
- **Hand-rolled `Ok[T]/Err[E]`** frozen-dataclass union (PEP 695 `type` aliases) instead of the
  `returns` library. Gives real pyright-strict exhaustiveness via `assert_never`, no mypy-plugin
  dependence, and puts the **error union directly in the match position** — which is exactly what
  the owner cares about. Better fit than `returns`' opaque `Success/Failure` wrapper.
- **Closed, standardised `ProviderError` union** with a **`ProviderSpecific` escape-hatch**
  variant — *not* per-provider `A | B` widening (which would break `assert_never` exhaustiveness
  and the "one standardised union" promise).
- **Retriability encoded in the type** (`Transient` vs terminal), not inferred at call sites.
- Error variants: `Timeout, ConnectionFailed, HttpStatus, RateLimited, DecodeError, ParseError,
  SchemaMismatch, TooLarge, Redirect, ProviderSpecific`. **Not** errors: seasonal-off and empty-200
  (domain state, returned as `Ok`), and `304 NotModified` (cache-hit success).
- **Two type systems only**: pydantic v2 at the ingest boundary; frozen dataclasses in the domain
  (incl. `Result`). `returns` dropped; msgspec noted as a future option, not v1.

**Domain**
- **Schedule resolver is the core**: `ScheduleRule + DayContext (calendar overlays) + ClosureRange
  + ScheduleException` → `resolve(pool, date) -> DaySchedule`. Makes future-date answers correct.
- **Explicit identity registry**: canonical `PoolId` with crosswalk (`geo_sport_id`,
  `crowdmonitor_key[]`, `aliases[]`) and **basin-level** sub-IDs. Providers map by **lookup, not
  fuzzy match**; unmatched names are a **loud failure**, never a silent guess.
- **Facility → Basin** modelled explicitly (one facility can have basins with independent schedules).
- **Explainable eligibility**: returns *why* (which rule + source text), not a bare bool.
- **Provenance on every answer** (`source`, `fetched_at`, `valid_as_of`, `curated|scraped`); results
  distinguish **closed** from **unknown/uncurated**.
- **Prices** stored as a dated display value + `valid_as_of` — not a tariff engine (avoids liability
  from stale computed prices).
- All datetimes **tz-aware `Europe/Zurich`** (DST + midnight-crossing slots handled).

**Testing**
- **vcrpy + pytest-recording** cassettes for recorded HTTP (200/500/429/malformed); `block_network`
  guarantees offline determinism; header/PII scrubbing on.
- **`httpx.MockTransport`** for timeouts/connection errors (no recorded interaction exists for those)
  — a separate seam from cassettes.
- **pyright --strict** in CI is the compile-time proof of exhaustive matching.

**Sequencing (owner-chosen)**
- **Library core + tests first** — no user-facing surface until the data model is proven.
- **Medallion built as pure functions first**; **Dagster wraps them later**, once a live feed
  (occupancy) makes orchestration/observability earn its cost.
- Start with **2–3 pools curated well** (City, Oerlikon, + one), then expand.
- **Occupancy deferred** behind a flag until CrowdMonitor's vendor terms are checked.
- **v1 avoids scraping entirely** (hand-curated YAML); a `data/sources.md` legal register tracks each
  source's license/ToS. Action noted: **email Open Data Zürich** to request machine-readable
  schedules — may remove the need to scrape at all.

**Tooling / skills**
- **uv** for env/deps; **ruff**, **pyright --strict**, **pytest**.
- Dagster skills to install (owner runs; plugin install is interactive):
  ```
  /plugin marketplace add dagster-io/skills
  /plugin install dagster-expert@dagster-skills
  /plugin install dignified-python@dagster-skills
  ```

---

## 6. Top risks

1. **Stale curated data → confidently-wrong typed answers** (worst failure mode). Mitigated by
   `valid_as_of` provenance on every answer + refresh cadence tracked in `data/sources.md`.
2. **Scraping / ToS** exposure. Mitigated by curated-YAML-only v1 and the legal register; occupancy
   deferred until vendor terms verified.
3. **Identity mismatch** across sources. Mitigated by explicit registry + lookup + loud failure.
4. **Future-date correctness.** Mitigated by the resolver + calendar overlays, tested on a
   holiday/term/Revision date matrix.

---

*See the implementation plan for the concrete repository layout, milestones, and verification steps.*
