---
type: summary
feature: website-sourced-providers
status: done
created: 2026-07-31
links: ["[[discovery-driven-providers]]", "[[lane-plan-url-binding]]", "[[gold-store]]", "[[2026-07-28-website-sourced-providers-plan]]", "[[2026-07-29-delete-curated-schedule-tier-plan]]"]
---

# Website-sourced providers — every authoritative fact is scraped; YAML is a thin crosswalk

**What & why.** The pool data used to live in hand-authored `data/pools/*.yaml` (schedules, prices,
physicals, address, geo) — a curated source of truth that goes stale and whose origin is unknowable.
Two plans replaced that: `website-sourced-providers` (S1–S5) built a provider for every fact and
made the build fail-fast + atomic; `delete-curated-schedule-tier` (S1–S4) then **deleted** the
curated payload, reducing the YAML to a thin crosswalk, folded the whole provider chain into one
atomic `swimzh build`, and replaced the `is_curated` boolean with a three-state freshness model.
End result: **the sourced data is the sole authority**; curated YAML carries only facts that live on
no web page. See [[discovery-driven-providers]] for the design stance (now `implemented`).

## What exists now

- **Sourced pipeline (providers → `compose` → `facility_doc`).** Identity, geo, `geo_sport_id`,
  address, and the ~57-pool roster come from the **live WFS** (`etl/roster.py`, `providers/
  geo_sport.py`); schedules from the page scraper (`providers/schedule_scraper.py`); prices from
  `providers/price_scraper.py`; closures from notice parsing; basin physicals from `infrastruktur`
  prose (`apply_physicals`); lane plans from **discovered** Belegungsplan links (`providers/
  page_provider.py` discovers, `providers/belegungsplan.py` + `etl/silver.py` bind). Every
  authoritative `facility_doc` field is sourced or a recorded drop, proven by the
  `etl/field_sourcing.py` audit.
- **Thin crosswalk (the only authoritative YAML left).** `data/pools/*.yaml` reduces to
  `facility_id` + basins carrying only `lane_plan_source` (url + optional `section`) — the URL→basin
  binding, a fact on no page. `data/registry.yaml` keeps aliases, `baditicker_poiid`,
  `crowdmonitor_keys`, and kind overrides (e.g. Käferberg `thermal`). Guarded by
  `tests/etl/test_pool_yaml_allowlist.py` (parsed-YAML key-set allowlist per level).
- **Three-state `ScheduleFreshness`** (`storage/codec.schedule_freshness`, enum in
  `domain/catalog.py`), derived at read from the blob — replaces `is_curated`:
  `scraped` (≥1 rule) / `awaiting_scrape` (scrapeable indoor|thermal, no schedule yet) /
  `no_source` (not scrapeable). Surfaced on `/pools` (`freshness`), `/swim` (status), and the UI's
  three ghost states. A schedule-less pool is **never** rendered "closed".
- **One atomic build.** `swimzh build` (`cli.build`) runs roster → `build_store` →
  `_compose_schedules(+prices)` → `_attach_lanes` → `compose` inside a single temp-DB + `os.replace`
  swap (`storage/atomic.py`). A mid-chain provider failure aborts non-zero, prior gold
  **content-unchanged** (iterdump-digest pinned). `build` is network-dependent; `scrape-gold` /
  `scrape-lanes` remain as thin re-layer commands over the same extracted phase functions.
- **`compose` carries the binding + honest provenance** (`build/compose.py`). When the scraped
  timetable wins (the post-strip world), each curated basin's `lane_plan_source` is **carried** onto
  the scraped basins (`_carry_bindings`) so the crosswalk survives and `_attach_lanes` finds an owner
  (no `attached == 0` abort), and the composed facility adopts the scrape's provenance so
  `provenance.curated` reads **False** (source/`valid_as_of` name the scrape). `freshness` is the
  primary signal; the boolean no longer lies.

## Run flow

```sh
uv run python -m swimzh.cli build --db gold.sqlite          # atomic, NETWORK-dependent
# per-cadence refresh onto the built store:  scrape-gold | scrape-lanes  --db gold.sqlite
SWIMZH_GOLD_DB=gold.sqlite uv run python -m apps.web.main    # app reads only the gold DB
```

## Key decisions

- **Fail-fast, all-or-nothing.** Any fatal provider failure aborts the whole atomic build rather
  than writing a partial/stale-but-green store. One deliberate exception: the price scrape is
  best-effort (the single non-fatal chain link).
- **Freshness enum, not a boolean.** A schedule-less pool is a first-class honest state, distinct
  from "closed" and from "hand-verified".
- **Merge, not replace, at compose.** The scraped schedule wins the timetable but the curated lane
  binding is preserved alongside it.

## Accepted limitation (owner, 2026-07-31)

The flat schedule scraper emits **one synthetic basin** (`Hauptbecken`) per pool — it cannot split
the timetable per basin. So a scraped pool's schedule lives on the synthetic basin while its lane
binding + physicals ride the carried named basin; the two never coexist. Consequence: the
**per-basin lane-availability panel is inert for scraped pools** (it renders only where genuine
per-basin data exists — the illustrative fixtures, or a future per-basin schedule source), and a
scraped `/swim` option carries no length/lanes (physicals survive on `/pools`). Owner accepted this
flat-endpoint cost rather than funding a per-basin schedule source.

## Backlog (tech debt carried out of the two plans)

1. **Per-basin lane panel parked** — needs a per-basin schedule source to un-inert it in production
   (root cause: the flat timetable endpoint; the S5c drop, now concrete).
2. **Physicals name-match fragility** — `apply_physicals` binds prose→basin by exact normalized
   name; oerlikon's WFS prose is `"NULL"` so its physicals are a **recorded DROP**, and city's
   `Lehrschwimmbecken` was dropped. Stripped basins had to be renamed to the WFS prose names.
3. **`baditicker_poiid → poi_id` collapse** deferred (needs a live multi-layer WFS cassette).
4. **Live occupancy / `measured_temp_c`** still unwritten.

See [[2026-07-28-website-sourced-providers-plan]] and [[2026-07-29-delete-curated-schedule-tier-plan]]
for the full ledgers and dated divergences.
