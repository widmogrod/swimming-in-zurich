"""The pool catalog: flat metadata for every Zürich swimming facility.

Distinct from `Facility` (which carries schedules): a catalog entry is just what the WFS
publishes — identity, location, official link, description. It answers "show me all pools",
independent of whether we have that pool's timetable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import Facility, PoolKind

_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def slug(name: str) -> str:
    """A stable, url-safe canonical id derived from a pool name.

    e.g. "Hallenbad City" -> "hallenbad-city", "Wärmebad Käferberg" -> "waermebad-kaeferberg".
    """
    lowered = name.strip().lower().translate(_TRANSLIT)
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


@dataclass(frozen=True, slots=True)
class PoolCatalogEntry:
    pool_id: str
    name: str
    kind: PoolKind
    address: str
    geo: GeoPoint | None
    url: str | None
    description: str | None
    phone: str | None
    # The WFS `poi_id` (e.g. "hb001") — the stable geo_sport occupancy key. Sourced onto the
    # roster so the build can stamp it as the facility's `geo_sport_id` (S5b), replacing the
    # retired registry-crosswalk placeholder. `None` when the WFS layer carries no poi_id.
    poi_id: str | None = None


class ScheduleFreshness(StrEnum):
    """A pool's schedule state, derived at read from its `facility_doc` blob (kind + rules) —
    the three-state model that replaced the `is_curated` boolean (delete-curated-schedule-tier S1).

    * `SCRAPED` — the blob carries a real schedule (≥1 basin has ≥1 rule).
    * `AWAITING_SCRAPE` — no rule yet AND *every* pool of this kind is a declared source (an
      indoor stadt-zuerich pool, incl. its `thermal` display-override), so a schedule is expected
      once `scrape-gold` runs.
    * `NO_SOURCE` — no rule AND not in that set (e.g. `schulschwimmanlage-hardau`, a `school`):
      permanently schedule-less, no website timetable source at all.

    `SCHOOL` is deliberately absent from the kind test in `freshness_of`: only 4 of the 18
    Schulschwimmanlagen are declared sources (`etl.scrape.declared_sources` — the other 14 share
    one overview URL). Those 4 carry rules and so read `SCRAPED` from the blob itself; adding
    `SCHOOL` here would flip the other 14 to a promise no scrape will ever keep. The URL-sharing
    test that would decide it properly is unavailable here — `Facility` carries no URL.

    A non-`SCRAPED` pool is a first-class honest state, never "closed" and never a `/swim` option.
    """

    SCRAPED = "scraped"
    AWAITING_SCRAPE = "awaiting_scrape"
    NO_SOURCE = "no_source"


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One row of the pool roster: the catalog metadata for a pool plus its **derived**
    `ScheduleFreshness` (from the gold `pool` table's `facility_doc` blob).

    The roster is the full set of ~57 published pools; `freshness` distinguishes the handful with
    a real schedule (`SCRAPED`) from those awaiting a scrape or with no source. `find_swim_options`
    subtracts the actually-scheduled facilities from the roster to emit the freshness status, and
    `/pools` surfaces `freshness` so the UI reads schedule status from the store, never by name.
    """

    entry: PoolCatalogEntry
    freshness: ScheduleFreshness


def freshness_of(facility: Facility) -> ScheduleFreshness:
    """The three-state rule itself, over a **decoded** `Facility` — the one place it lives.

    `storage.codec.schedule_freshness` decodes the `facility_doc` blob and delegates here, so the
    roster (`/pools`, `/swim`) and any caller holding an already-resolved facility (`/pools/{id}`)
    cannot answer the same question differently. A detail response that said "illustrative" while
    the list row beside it said `scraped` is exactly the divergence this closes.
    """
    if any(basin.rules for basin in facility.basins):
        return ScheduleFreshness.SCRAPED
    # A `Wärmebad` (THERMAL) is WFS-`indoor` but registry-overridden for display, so it IS
    # scraped. These two kinds are the ones where EVERY pool is a declared source; `SCHOOL` is
    # not (4 of 18) and must stay out — see ScheduleFreshness.
    if facility.identity.kind in (PoolKind.INDOOR, PoolKind.THERMAL):
        return ScheduleFreshness.AWAITING_SCRAPE
    return ScheduleFreshness.NO_SOURCE
