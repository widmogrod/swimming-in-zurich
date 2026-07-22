"""Fetch + parse the per-basin Belegungsplan PDFs — DRIVEN BY the domain.

What to extract is a projection of the model: a source exists to be extracted *iff a basin
declares a `lane_plan_source`. There is no hardcoded URL list (the old
`CITY_BELEGUNGSPLAN_URLS` / `PENDING_BELEGUNGSPLAENE` constants are deleted); the fetch-set is
derived from the loaded facilities, so adding a source is one YAML edit on the owning basin.

Best-effort and errors-as-values: each declared source URL is fetched + parsed independently.
A success yields one or more `ParsedPlan`s (a stacked sheet stacks several basins) stamped with
the URL they came from. A fetch/parse failure is NOT swallowed: it is recorded as a typed
`LanePlanMiss(source_url, cause)` so silver can persist a `LanePlanUnavailable` on the declared
basin(s), keyed by the real `ProviderError`.

The URL->basin binding is NOT made here: this module only fetches + parses and stamps the
`source_url`. Binding is a deterministic URL-keyed join performed in `etl/silver.py` against the
declared `lane_plan_source`s; `ParsedPlan.basin_hint` is only a stacked-sheet section
discriminator + audit string, never an identity key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.domain.models import Facility
from swimzh.providers.belegungsplan import ParsedPlan, scrape_belegungsplan_sheet


def declared_source_urls(facilities: Sequence[Facility]) -> tuple[str, ...]:
    """The parse fetch-set: every distinct `lane_plan_source.url` declared by a basin, in first-
    seen order. This IS the extraction universe — nothing hardcoded — so the fetch loop can never
    drift from what the domain declares."""
    seen: dict[str, None] = {}
    for facility in facilities:
        for basin in facility.basins:
            if basin.lane_plan_source is not None:
                seen.setdefault(basin.lane_plan_source.url, None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class LanePlanMiss:
    """A declared source whose fetch/parse FAILED — the real typed cause, mapped back to its
    URL so silver can stamp a `LanePlanUnavailable` on every basin that declared it."""

    source_url: str
    cause: ProviderError


@dataclass(frozen=True, slots=True)
class LanePlanReport:
    """The outcome of extracting the domain-declared sources: the parsed plans (each stamped
    with its `source_url`) and the per-URL failures (typed causes)."""

    plans: tuple[ParsedPlan, ...]
    misses: tuple[LanePlanMiss, ...]


def scrape_lane_plans(client: HttpClient, facilities: Sequence[Facility]) -> LanePlanReport:
    """Fetch + parse every source the loaded facilities declare, stamping each parsed plan with
    the URL it came from and recording each failure as a typed miss."""
    plans: list[ParsedPlan] = []
    misses: list[LanePlanMiss] = []
    for url in declared_source_urls(facilities):
        # One sheet may stack several basins (Oerlikon's Nichtschwimmer-/Sprungbecken): the
        # sheet parser returns one `ParsedPlan` per basin; a single-basin sheet returns one.
        match scrape_belegungsplan_sheet(client, url):
            case Ok(parsed):
                plans.extend(replace(p, source_url=url) for p in parsed)
            case Err(cause):
                misses.append(LanePlanMiss(source_url=url, cause=cause))
    return LanePlanReport(plans=tuple(plans), misses=tuple(misses))
