---
type: summary
feature: pool-identity-unification
status: done
created: 2026-07-20
links: ["[[data-layer-architecture]]", "[[gold-store]]", "[[2026-07-19-pool-identity-unification]]", "[[fastapi-service-integration]]"]
---

# Pool-identity unification — the split-brain, cured and made unrepresentable

**What & why.** The single-source-of-truth refactor put everything in one gold DB but left the
pool identity split-brain: curated facilities keyed by short ids (`city`) vs the catalog keyed by
long slugs (`hallenbad-city`), intersection ∅, so `/swim` (facility) and `/pools` (catalog) could
not join, `uncurated` was guessed client-side by name, and `scrape-gold` bypassed reconcile and
wrote long ids into the short-id PK (producing duplicate rows, patched by hand). This feature made
one canonical identity **DB-enforced** so that class of bug cannot recur.

## What exists now (verified live: build → scrape-gold → scrape-lanes)

- **One canonical namespace** — `pool.id = slug(name)`; curated data re-keyed to it, legacy short
  ids preserved as lossless aliases.
- **Identity spine (DB-enforced)** — `pool` table IS the registry (57 pools, `curation_status`
  DERIVED: 4 curated / 53 uncurated) + `pool_alias(UNIQUE norm)` + `pool_xref(UNIQUE namespace,
  ext_id)` STRICT, FK `ON DELETE CASCADE`. A duplicate identity is a write-time `IntegrityError`
  (proven). `catalog` table retired.
- **One id-minting seam** — the `build/` package: `normalize` (one cleaning home), `reconcile`
  (`SourceRef = Xref | Name | BasinHint | Global`; `resolve`/`resolve_all` the SOLE `PoolId`
  producer, lookup-only, loud on miss), `seed` (spine), `compose` (declarative `_ASPECTS`
  curated-wins merge). Grep-guard forbids `PoolId(...)` outside `reconcile`/`seed`. Enforcement is
  **DB UNIQUE + grep**, not a private constructor.
- **`uncurated` live + `/swim` ↔ `/pools` joined** — `SwimStore` roster; `find_swim_options` emits
  `uncurated = roster − scheduled`; UI reads the derived `curated` flag from the API. Three states
  (open / closed(reason) / uncurated) never merged.
- **Scrape hole closed** — providers emit `(SourceRef, payload)`; `scrape-gold` runs
  `reconcile → compose`; `drop_curated_duplicates` deleted. City is no longer duplicated and keeps
  its curated schedule **and** gains the scraped price (per-aspect merge).

## Run flow (unchanged surface, one builder underneath)

```sh
uv run python -m swimzh.cli build --db gold.sqlite          # offline: spine + curated
uv run python -m swimzh.cli scrape-gold  --db gold.sqlite   # network: reconcile + compose onto the spine
uv run python -m swimzh.cli scrape-lanes --db gold.sqlite   # network: lane plans
SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main
```
`scrape-gold` now requires a pre-built store (it resolves names against the spine).

## Backlog (carried tech debt, not regressions)

1. Transitional `facility` table — composed blob lives in both `pool.facility_doc` and
   `facility.doc`; collapse it (its retirement + full row-normalization is the
   `schedule-schema-normalization` follow-up plan).
2. `domain`/`etl` import `build.normalize` — backwards layer direction; move `normalize` to `core/`
   or add an import guard.
3. `scrape-gold` whole-batch abort on one unmatched name (consider partial-with-report).
4. `scrape-gold` does not update `pool.curation_status` (scraped-only pool stays `uncurated` in the
   roster while gaining a `/swim` schedule).
5. `Global` `SourceRef` variant vestigial (price fanned out at scrape time, not in `compose`).

See [[2026-07-19-pool-identity-unification]] for the full ledger and dated decisions, and
[[data-layer-architecture]] for the block design this executed.
