"""The roster provider: the ~57-pool identity spine + geo, sourced LIVE from the WFS.

S3 retires the committed ``data/catalog.json`` as a build input. The roster — pool id, name,
facility ``kind``, address, geo, url, description, phone — now originates from the Stadt Zürich
WFS (``geo_sport.fetch_all_pools``), shaped into ``PoolCatalogEntry`` rows by ``build_catalog``.
A WFS failure surfaces as a typed ``ProviderError`` value: the build's **local abort at the
roster step** (the general abort-orchestration / atomic-swap is S4).

The WFS carries roster IDENTITY + GEO and, via each layer's ``poi_id``, the ``geo_sport_id`` that
S5b now SOURCES onto the spine (``build_spine`` stamps ``poi_id`` → ``geo_sport_id``). The remaining
external-correlation crosswalk keys (``baditicker_poiid``, ``crowdmonitor_keys``, human ``aliases``)
are on no website and stay irreducibly curated in ``data/registry.yaml`` — the disclosed crosswalk
exception, exactly as S2 kept ``lane_plan_source`` as the per-basin binding key. ``build_store`` no
longer reads ``registry.yaml`` for the roster's identity/geo (or for ``geo_sport_id``); it consults
it only for that remaining crosswalk.

This is the ONE place the build reaches the network for the roster, reversing the previous
offline/no-network build guarantee (recorded in the plan's Decisions; CLAUDE.md updated in S6).
"""

from __future__ import annotations

from swimzh.core.errors import ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.etl.catalog import build_catalog
from swimzh.providers import geo_sport


def fetch_roster(client: HttpClient) -> Result[tuple[PoolCatalogEntry, ...], ProviderError]:
    """Fetch every published WFS pool layer and shape it into the canonical roster.

    Fails fast on the first layer error (``fetch_all_pools`` already refuses a partial catalog
    that would silently hide a missing category) — the error is returned as a value for the
    caller to turn into the build's non-zero, roster-step abort.
    """
    match geo_sport.fetch_all_pools(client):
        case Err(error):
            return Err(error)
        case Ok(pools):
            return Ok(build_catalog(pools))
