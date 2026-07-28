"""Fetch + parse the per-basin Belegungsplan PDFs — DRIVEN BY DISCOVERY.

What to extract is a projection of the DISCOVERED links: the upstream ``page_provider`` emits the
Belegungsplan URLs it finds on each pool page (each stamped with its parent ``PoolId``), and that
set of links IS the fetch-set here. There is no hardcoded URL list and no hand-authored
``lane_plan_source`` URL driving extraction any more — a source exists to be extracted iff a pool
page advertises it, so the fetch-set is re-derived every run and cannot go stale.

Errors-as-values, then fail-fast (S4): each discovered URL is fetched + parsed independently. A
success yields one or more ``ParsedPlan``s (a stacked sheet stacks several basins) stamped with
the URL they came from. A fetch/parse failure is NOT swallowed and is NOT persisted as a hole: it
is recorded as a typed ``LanePlanMiss(source_url, cause)`` which ``scrape-lanes`` turns into a
whole-run **abort** (non-zero, gold left content-unchanged), carrying the real ``ProviderError``.
There is no longer a ``LanePlanUnavailable`` written for a failed source.

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
from swimzh.domain.models import Facility, PoolId
from swimzh.providers.belegungsplan import ParsedPlan, scrape_belegungsplan_sheet
from swimzh.providers.page_provider import DiscoveredLink


@dataclass(frozen=True, slots=True)
class UndiscoveredSource:
    """An authored ``lane_plan_source.url`` that its pool page FAILED to advertise, so discovery
    never fetched it (``authored − discovered``). Under S4 fail-fast this is a HARD abort — a
    declared fact gone missing, never a silent drop (the S2-surfaced case). Carries the owning
    ``PoolId`` so the operator can find the stale/stranded binding."""

    pool_id: PoolId
    url: str


def undiscovered_authored(
    facilities: Sequence[Facility], discovered_links: Sequence[DiscoveredLink]
) -> tuple[UndiscoveredSource, ...]:
    """The authored ``lane_plan_source`` URLs that discovery did NOT surface — ``authored −
    discovered``.

    Every basin's declared ``lane_plan_source.url`` must appear among the links its pool page
    advertises this run; one that does not is a declared source discovery can no longer produce —
    either the page stopped listing it, or the page itself failed to fetch (its links are absent).
    This is the stale-store fetch-set invariant made LOUD: editing a basin's source (or a page
    dropping a link) without it being re-discoverable can no longer pass as a silent stale read.
    Deduped per ``(pool_id, url)`` in first-seen order."""
    discovered = {link.url for link in discovered_links}
    seen: set[tuple[PoolId, str]] = set()
    out: list[UndiscoveredSource] = []
    for facility in facilities:
        for basin in facility.basins:
            source = basin.lane_plan_source
            if source is None or source.url in discovered:
                continue
            key = (facility.identity.facility_id, source.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(UndiscoveredSource(pool_id=facility.identity.facility_id, url=source.url))
    return tuple(out)


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
    URL. Under S4 this drives a whole-run ``scrape-lanes`` abort (not a persisted
    ``LanePlanUnavailable``), so a declared lane source can never silently vanish from the store."""

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
