"""The merge seam: fold curated + scraped aspects into one facility per pool.

``compose`` groups reconciled aspects by ``PoolId`` and folds them into a single ``Facility``
using a **declarative aspect → precedence map** (``_ASPECTS``), not per-provider ``if`` arms.
Every aspect today is *curated-wins* (``CURATED_WINS``); a future scraped-authoritative aspect
flips only its own precedence tuple — the fold engine stays provider-agnostic.

This replaces ``etl/silver.drop_curated_duplicates``. Crucially, unlike that whole-row filter
(which dropped a scraped facility *entirely* when a curated pool already existed, discarding its
scraped price), compose merges **per aspect**: a curated pool keeps its curated schedule AND
gains a scraped price the curated data lacked. A build note records every aspect both sources
supplied.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any

from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import (
    Basin,
    Facility,
    Notice,
    PoolId,
    PoolIdentity,
    PoolKind,
    Provenance,
)
from swimzh.domain.pricing import PriceTable
from swimzh.domain.schedule import ClosureRange, HolidayPolicy

_SCRAPE_SOURCE = "schedule_scraper"


@dataclass(frozen=True, slots=True)
class ScrapedAspects:
    """The identity-free payload a schedule scrape emits, paired with a ``SourceRef``.

    Carries only *aspects* (never a canonical id): the basins/rules parsed from a pool's
    timetable, plus notices, closures, and the shared admission price for city-run pools.
    ``compose`` turns it into a scraped ``Facility`` once ``reconcile`` has produced the
    ``PoolId`` — the id is never minted here.
    """

    name: str
    kind: PoolKind
    address: str
    geo: GeoPoint | None
    basins: tuple[Basin, ...]
    closures: tuple[ClosureRange, ...]
    notices: tuple[Notice, ...]
    prices: PriceTable | None
    fetched_at: datetime


class Source(Enum):
    """A provider class whose facts compose folds together (per-aspect precedence)."""

    CURATED = "curated"
    SCRAPED = "scraped"


# Curated-wins precedence: consult curated first, fall back to scraped. Every aspect uses this
# today; a scraped-authoritative aspect would declare ``(SCRAPED, CURATED)`` instead.
CURATED_WINS: tuple[Source, ...] = (Source.CURATED, Source.SCRAPED)


@dataclass(frozen=True, slots=True)
class _Aspect:
    """One mergeable ``Facility`` field: how to read it, whether a value counts as present,
    and the source precedence order to apply."""

    field: str
    present: Callable[[Any], bool]
    precedence: tuple[Source, ...]


def _has_schedule(basins: tuple[Basin, ...]) -> bool:
    return any(basin.rules for basin in basins)


def _is_not_none(value: Any) -> bool:
    return value is not None


def _is_nonempty(value: tuple[Any, ...]) -> bool:
    return bool(value)


# The declarative precedence map — the single place aspect merge policy is stated. No aspect is
# merged by a hand-written provider ``if``; adding one means one row here.
_ASPECTS: tuple[_Aspect, ...] = (
    _Aspect("basins", _has_schedule, CURATED_WINS),
    _Aspect("prices", _is_not_none, CURATED_WINS),
    _Aspect("closures", _is_nonempty, CURATED_WINS),
    _Aspect("notices", _is_nonempty, CURATED_WINS),
    _Aspect("geo", _is_not_none, CURATED_WINS),
)


@dataclass(frozen=True, slots=True)
class Composition:
    """The folded facilities plus per-pool build notes (every aspect both sources supplied)."""

    facilities: tuple[Facility, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


def _scraped_facility(pool_id: PoolId, aspects: ScrapedAspects) -> Facility:
    """Assemble a scraped ``Facility`` from an already-reconciled ``PoolId`` (never minted here)."""
    return Facility(
        identity=PoolIdentity(facility_id=pool_id, name=aspects.name, kind=aspects.kind),
        address=aspects.address,
        provenance=Provenance(
            source=_SCRAPE_SOURCE,
            curated=False,
            valid_as_of=aspects.fetched_at.date(),
            fetched_at=aspects.fetched_at,
        ),
        basins=aspects.basins,
        geo=aspects.geo,
        closures=aspects.closures,
        public_holiday_policy=HolidayPolicy.NORMAL,
        prices=aspects.prices,
        notices=aspects.notices,
    )


def _fold(by_source: dict[Source, Facility]) -> tuple[Facility, tuple[str, ...]]:
    """Fold one pool's per-source facilities into one, applying each aspect's precedence."""
    # The base carries identity + all un-merged fields; prefer curated (its crosswalk/lane
    # plans are richer), else the scraped facility.
    base = by_source.get(Source.CURATED) or by_source[Source.SCRAPED]
    changes: dict[str, Any] = {}
    notes: list[str] = []
    for aspect in _ASPECTS:
        present = [
            source
            for source in aspect.precedence
            if source in by_source and aspect.present(getattr(by_source[source], aspect.field))
        ]
        if not present:
            continue
        winner = present[0]
        changes[aspect.field] = getattr(by_source[winner], aspect.field)
        if len(present) > 1:
            also = ", ".join(source.value for source in present[1:])
            notes.append(
                f"{base.identity.name}: {aspect.field} kept from {winner.value} "
                f"(also supplied by {also})"
            )
    return replace(base, **changes), tuple(notes)


def compose(
    curated: Iterable[Facility],
    scraped: Iterable[tuple[PoolId, ScrapedAspects]],
) -> Composition:
    """Fold curated facilities + reconciled scraped aspects into one facility per pool.

    Curated and scraped facts for the same ``PoolId`` merge per aspect (curated-wins); a pool
    present in only one source passes through. Output is ordered by canonical id so a re-run
    yields equal rows.
    """
    curated_by_id: dict[str, Facility] = {str(f.identity.facility_id): f for f in curated}
    scraped_by_id: dict[str, tuple[PoolId, ScrapedAspects]] = {}
    for pool_id, aspects in scraped:
        scraped_by_id[str(pool_id)] = (pool_id, aspects)

    facilities: list[Facility] = []
    notes: list[str] = []
    for pool_key in sorted(curated_by_id.keys() | scraped_by_id.keys()):
        by_source: dict[Source, Facility] = {}
        if pool_key in curated_by_id:
            by_source[Source.CURATED] = curated_by_id[pool_key]
        if pool_key in scraped_by_id:
            pool_id, aspects = scraped_by_id[pool_key]
            by_source[Source.SCRAPED] = _scraped_facility(pool_id, aspects)
        merged, pool_notes = _fold(by_source)
        facilities.append(merged)
        notes.extend(pool_notes)

    return Composition(facilities=tuple(facilities), notes=tuple(notes))
