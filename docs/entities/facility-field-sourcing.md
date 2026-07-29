---
type: entity
created: 2026-07-29
links: ["[[2026-07-28-website-sourced-providers-plan]]", "[[discovery-driven-providers]]", "[[basin]]"]
---

# Facility field sourcing (S5a audit)

The **machine-checkable** source of truth is `src/swimzh/etl/field_sourcing.py`
(`FACILITY_FIELD_SOURCING`); this page is the human-readable narrative. A test
(`tests/etl/test_field_sourcing.py`) asserts the table covers **exactly** the serialized
`facility_doc` fields — no field unlisted, no stale entry.

`facility_doc` == `storage.codec.dumps(facility)` == `StoredFacilityDTO.model_dump_json()`. The
serialization boundary is therefore the fields of two pydantic roots: `StoredFacilityDTO` (facility
level) and the nested `BasinDTO` (basin level — the one list whose members carry independently
sourced facts). Leaves below those (`RuleDTO`/`AccessDTO`/`PriceEntryDTO`/`LanePlanDTO` sub-fields)
inherit their parent field's producer and are not enumerated separately.

## Producer kinds

- **sourced-by-`<module>`** — a website provider already produces the fact.
- **curated-crosswalk** — an irreducible correlation/binding fact on **no** website (thin retained
  crosswalk, S3/S6).
- **drop-candidate** — genuine residue: curated fact with no website producer today (source-or-drop
  decided by S5c/S5d).
- **build-metadata** — provenance / honesty tag produced by the build itself, not a data provider.
  A fourth bucket beyond the plan's three; forcing provenance fields into a data-provider bucket
  would be dishonest and "producer" (S5a's word) legitimately includes the composer/codec.

## Facility-level (`StoredFacilityDTO`)

| field | producer | scope | note |
|-------|----------|-------|------|
| `facility_id` | sourced · `etl.roster` | 7/7 | WFS identity spine (S3) |
| `name` | sourced · `etl.roster` | 7/7 | WFS display name |
| `kind` | sourced · `etl.roster` | 7/7 | WFS facility PoolKind (kaeferberg `thermal` override rides the registry crosswalk) |
| `address` | sourced · `etl.roster` | 7/7 | WFS address |
| `source` | build-metadata | n/a | provenance.source string |
| `curated` | build-metadata | n/a | serialized from `Provenance.curated` by build/codec (not `codec.is_curated`, a separate read-time derivation) |
| `valid_as_of` | build-metadata | n/a | provenance freshness |
| `fetched_at` | build-metadata | n/a | provenance freshness |
| `geo_sport_id` | curated-crosswalk | crosswalk | occupancy key; **S5b sources it from WFS `poi_id`** |
| `crowdmonitor_keys` | curated-crosswalk | crosswalk | occupancy keys, on no website |
| `baditicker_poiid` | curated-crosswalk | crosswalk | water-temp feed poiid, on no website |
| `aliases` | curated-crosswalk | crosswalk | reconcile alias strings |
| `geo` | sourced · `etl.roster` | 7/7 | WFS lat/lon (live since S3) |
| `amenities` | drop-candidate | 0/7 | curated-only; `infrastruktur` emits structured `features`, not this string-set |
| `public_holiday_policy` | drop-candidate | 0/7 | not in source (S1); recorded-drop candidate (S5d) |
| `prices` | sourced · `providers.price_scraper` | city-run | **already wired** into scrape-gold; see the compose finding |
| `closures` | sourced · `providers.schedule_scraper` | 3/7 observed | `parse_notices` → closures |
| `basins` | sourced · `providers.schedule_scraper` | 7/7 facility-level | single `Hauptbecken`; see basin-level rows |
| `notices` | sourced · `providers.schedule_scraper` | 7/7 | `parse_notices` |
| `website` | sourced · `etl.roster` | 7/7 | WFS `www` |
| `features` | sourced · `providers.infrastruktur` | 2/7 prose | `parse_features` over WFS prose; 5/7 NULL → S5d |
| `lockers` | drop-candidate | 0/7 | curated-only; no provider |
| `accessibility` | drop-candidate | 0/7 | curated-only; no provider |
| `last_admission_before` | drop-candidate | 0/7 | curated-only; no provider |

## Basin-level (`BasinDTO`)

| field | producer | scope | note |
|-------|----------|-------|------|
| `basin_id` | sourced · `providers.schedule_scraper` | 7/7 facility-level | `<pool_id>-main`; per-basin ids are split residue |
| `name` | sourced · `providers.schedule_scraper` | 7/7 facility-level | `Hauptbecken`; per-basin names are split residue |
| `rules` | sourced · `providers.schedule_scraper` | 7/7 facility-level | facility-level rules; **per-basin split + richer access ride here** (below) |
| `exceptions` | drop-candidate | 0/7 | per-date session overrides; curated-only |
| `kind` | sourced · `providers.infrastruktur` | 2/7 prose | 5/7 NULL prose → S5d |
| `dimensions` | sourced · `providers.infrastruktur` | 2/7 prose | 5/7 NULL prose → S5d |
| `lanes` | sourced · `providers.infrastruktur` | 2/7 prose | 5/7 NULL prose → S5d |
| `nominal_temp_c` | sourced · `providers.infrastruktur` | 2/7 prose | 5/7 NULL prose → S5d |
| `measured_temp_c` | drop-candidate | 0/7 | live reading; out of scope, never written |
| `diving_platforms_m` | sourced · `providers.infrastruktur` | 2/7 prose | 5/7 NULL prose → S5d |
| `physical_source` | build-metadata | n/a | curated vs parsed_prose honesty tag |
| `lane_plan_source` | curated-crosswalk | crosswalk | per-basin URL→basin binding key (irreducible, S2) |
| `lane_plan` | sourced · `providers.belegungsplan` | basins with a lane PDF | `parse_belegungsplan` via scrape-lanes |

## Prices compose finding (ground-truthed)

`price_scraper` **is** wired: `cli.scrape_gold` calls `scrape_prices(client, …)` → the central
city-wide `Einzeleintritte` tariff, attached in `etl/scrape._aspects` **only to `stadt-zuerich.ch`
pools** (`_CITY_HOST in entry.url`), then folded by `build/compose`. Two facts matter:

1. **The base `swimzh build` does not scrape prices** — only the `scrape-gold` layer does. A store
   built but never scraped carries only curated prices.
2. **Compose precedence is `CURATED_WINS`** (`_Aspect("prices", _is_not_none, CURATED_WINS)`). So
   the scraped price does **not** override a curated `prices:` block — curated wins, the scrape only
   fills a pool that has no curated price ("keeps its schedule AND gains a scraped price"). The
   website producer is nonetheless `price_scraper`; once S6 deletes the authoritative curated
   payload, it becomes the sole producer. **No new price provider is needed** (de-risks S5).

## Belegungsplan feasibility verdict (the genuine residue)

Read from the parser's output shape (`providers/belegungsplan.py`, `domain/lane_plan.py`):

- **Per-basin session times → SOURCEABLE (S5c).** `parse_belegungsplan_sheet` returns **one
  `ParsedPlan` per basin**, each `LanePlan` carrying `LaneReservation`s = weekdays × `TimeRange` ×
  lanes × access, bound to a specific basin by the URL-keyed join (S2). The public-swim reservations
  aggregated per basin give per-basin public windows with real session times — i.e. the per-basin
  *schedule* split can be sourced from the per-basin lane PDFs. **Caveat:** only for basins that
  *have* a Belegungsplan PDF; basins without one (many Nichtschwimmer-/Kinderbecken) get no split.
- **Richer access (`lane_swim`/`family`/`adults_only`) → DROP (S5d).** The parser's
  `_code_to_access` maps every legend code to exactly `{PublicSwim, SchoolReserved, ClubReserved}`,
  and `LaneReservation` documents "Only PublicSwim, SchoolReserved, and ClubReserved are emitted by
  the parser (enforced there)." The Belegungsplan legend encodes lane **ownership**
  (public/club/school), not the public-session **subtype** (lane-swim/family/adults-only), so it
  cannot yield the richer vocabulary. Combined with S1's finding that the flat timetable's category
  vocabulary is likewise closed (public/women/seniors/school), richer access is **not-in-source**
  from either channel → a recorded drop after this demonstrated-infeasible extraction.
