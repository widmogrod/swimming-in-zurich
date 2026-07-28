"""Fetch + parse the per-basin Belegungsplan PDFs — DRIVEN BY DISCOVERY.

What to extract is a projection of the DISCOVERED links: the upstream ``page_provider`` emits the
Belegungsplan URLs it finds on each pool page (each stamped with its parent ``PoolId``), and that
set of links IS the fetch-set here. There is no hardcoded URL list and no hand-authored
``lane_plan_source`` URL driving extraction any more — a source exists to be extracted iff a pool
page advertises it, so the fetch-set is re-derived every run and cannot go stale.

Best-effort and errors-as-values: each discovered URL is fetched + parsed independently. A
success yields one or more ``ParsedPlan``s (a stacked sheet stacks several basins) stamped with
the URL they came from. A fetch/parse failure is NOT swallowed: it is recorded as a typed
``LanePlanMiss(source_url, cause)`` so silver can persist a ``LanePlanUnavailable`` on the
declared basin(s), keyed by the real ``ProviderError``.

The URL->basin binding is NOT made here: this module only fetches + parses and stamps the
``source_url``. Binding is a deterministic URL-keyed join performed in ``etl/silver.py`` against
the basin's declared source; ``ParsedPlan.basin_hint`` is only a stacked-sheet section
discriminator + audit string, never an identity key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.providers.belegungsplan import ParsedPlan, scrape_belegungsplan_sheet
from swimzh.providers.page_provider import DiscoveredLink


def fetch_set(discovered_links: Sequence[DiscoveredLink]) -> tuple[str, ...]:
    """The parse fetch-set: every distinct discovered URL, in first-seen order, deduped. This IS
    the extraction universe — a projection of the pages' discovered links, nothing hardcoded and
    nothing read from ``lane_plan_source`` — so the fetch loop can never drift from what the
    pages advertise."""
    seen: dict[str, None] = {}
    for link in discovered_links:
        seen.setdefault(link.url, None)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class LanePlanMiss:
    """A discovered source whose fetch/parse FAILED — the real typed cause, mapped back to its
    URL so silver can stamp a ``LanePlanUnavailable`` on every basin that declared it."""

    source_url: str
    cause: ProviderError


@dataclass(frozen=True, slots=True)
class LanePlanReport:
    """The outcome of extracting the discovered sources: the parsed plans (each stamped
    with its ``source_url``) and the per-URL failures (typed causes)."""

    plans: tuple[ParsedPlan, ...]
    misses: tuple[LanePlanMiss, ...]


def scrape_lane_plans(
    client: HttpClient, discovered_links: Sequence[DiscoveredLink]
) -> LanePlanReport:
    """Fetch + parse every DISCOVERED source, stamping each parsed plan with the URL it came
    from and recording each failure as a typed miss."""
    plans: list[ParsedPlan] = []
    misses: list[LanePlanMiss] = []
    for url in fetch_set(discovered_links):
        # One sheet may stack several basins (Oerlikon's Nichtschwimmer-/Sprungbecken): the
        # sheet parser returns one `ParsedPlan` per basin; a single-basin sheet returns one.
        match scrape_belegungsplan_sheet(client, url):
            case Ok(parsed):
                plans.extend(replace(p, source_url=url) for p in parsed)
            case Err(cause):
                misses.append(LanePlanMiss(source_url=url, cause=cause))
    return LanePlanReport(plans=tuple(plans), misses=tuple(misses))
