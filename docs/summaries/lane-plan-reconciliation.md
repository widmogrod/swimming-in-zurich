---
type: summary
created: 2026-07-22
feature: lane-plan-reconciliation
links: ["[[lane-plan-url-binding]]", "[[lane-data-availability]]", "[[2026-07-21-lane-plan-reconciliation-plan]]", "[[richer-data-fidelity]]", "[[gold-store]]"]
---

# Lane-plan reconciliation — by URL-origin identity, not fuzzy PDF-title text

## The problem

The Belegungsplan parser read 8/8 published sheets, but only **2 of 8 reached a swimmer**: attachment
fuzzy-matched each PDF's internal header title against a `normalise("<facility> <basin-word>")` index. That
failed for real curated basins whose header omits the facility (stacked "Nichtschwimmer"/"Sprungbecken") or the
basin (single-basin "Hallenbad Bungertwies"). A genuine reconciliation defect, not curation debt.

## What shipped

- **`lane_plan_source` is a first-class `Basin` attribute** — `LanePlanSource(url, section=None)`, authored in
  `data/pools/*.yaml`, riding the `facility_doc` blob (no gold DDL). Identity is known where the URL is authored,
  so a binding can never reference a missing basin; no second identity store.
- **The ETL is driven by the domain.** The parse fetch-set is a projection of the declared sources
  (`etl/lane_plans.py::declared_source_urls`). The hardcoded `CITY_BELEGUNGSPLAN_URLS` / `PENDING_BELEGUNGSPLAENE`
  lists, the fuzzy `_basin_hint_index`, and the `BasinHint` `SourceRef` arm (+ `build_basin_hint_index`,
  `Crosswalk.basin_hint`/`ambiguous_hints`) are **deleted**.
- **Reconciliation is a deterministic URL-keyed inner join** (`etl/silver.py`): the fetch loop stamps
  `ParsedPlan.source_url`; `attach_lane_plans` joins a parsed plan back to the basin whose URL it came from. Pure
  id-join for single-basin sheets; for **stacked** multi-basin sheets (one URL, N bindings) each section routes
  by the declared `section` token contained in `normalize(basin_hint)` — **fail-safe: an ambiguous/overlapping
  token → `UnboundPlan`, never a misbind** (critic-verified against real headers).
- **Extraction outcomes are first-class persisted state** — `Basin.lane_plan: LanePlan | LanePlanUnavailable |
  None`. `LanePlanUnavailable(source_url, section, cause: ProviderError, observed_at)` carries the real
  closed-union cause **losslessly** (enabled by narrowing `ProviderSpecific.detail: object → JsonValue`). A
  fetch/parse failure fails **only** that basin's `lane_plan`, never the pool build; partial extraction loses
  nothing; recovery can partition failures by error class (`retriable()`), enabling a deferred selective-retry
  command.
- **Honest stderr audit** (`scrape-lanes`) — per-basin `unavailable` cause (`describe(cause)`), per-URL
  `unbound` reason, and `unmatched section` (a curated token that matched no parsed header — a likely parser
  regression, not a silent `None`).

## Result

`scrape-lanes` now attaches City-50m, Oerlikon-50m, **Oerlikon-Sprungbecken**, **Bungertwies**, and
**leimbach/blaesi/kaeferberg** (a new curated-but-schedule-less pool class). Oerlikon Nichtschwimmer is an honest
`UnboundPlan`; a failed source is a persisted `LanePlanUnavailable`.

## Deliberately out of scope

View/download "fallback" links (a maintenance liability — rejected), Hallenbad Altstetten's rotating-URL PNG
(needs vision + discovery), a discovery crawler (the published stadt-zuerich universe is a proven-closed 8
sheets — see [[lane-data-availability]]), a gold DDL/migration, and the selective-retry command (the data model
enables it; the CLI is a follow-up).

## Entry points

- Domain: `domain/models.py` — `LanePlanSource`, `LanePlanUnavailable`, `Basin.lane_plan`/`lane_plan_source`.
- Join: `etl/silver.py` — `build_url_bindings`, `bind_plans` (`_bind_single`/`_bind_stacked`),
  `attach_lane_plans`, `find_unmatched_sections`, `BoundPlan`/`UnboundPlan`/`UnmatchedSection`.
- Fetch-set: `etl/lane_plans.py` — `declared_source_urls`, `scrape_lane_plans`.
- Codec: `boundary/curated_dto.py` + `boundary/mapping.py` — tag-discriminated `ProviderError` DTO, lossless.
- Audit: `cli.py` — `_report_lane_audit`.

## Note for future work

The concept [[lane-plan-url-binding]] is the durable design record. Two non-blocking follow-ups tracked in the
plan's Decisions: `resolve_all`'s now-unreachable `Err` arm (revisit when a new fatal `SourceRef` cause appears),
and the phrase-narrow doc-reversal grep-guard. The **selective-retry** command is the natural next slice — the
`LanePlanUnavailable(cause)` state already supports partitioning by error class.
