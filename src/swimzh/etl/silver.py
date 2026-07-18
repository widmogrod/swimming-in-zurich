"""Silver stage: normalise + reconcile sources to canonical facility ids.

Reconciliation is **lookup, not fuzzy match**: every geo_sport pool name must resolve to a
canonical id via the registry. Any name that does not is a **loud failure** (an error value
naming the offenders) — never a silent drop or a guessed match. Matched geo is merged into
the curated facilities (coordinates + geo_sport_id crosswalk), and provenance is stamped
with the run's `fetched_at`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import Facility, FacilityId
from swimzh.providers.curated import Dataset
from swimzh.providers.geo_sport import GeoPool

_SOURCE = "silver"


def reconcile(
    dataset: Dataset, geo_pools: list[GeoPool], fetched_at: datetime
) -> Result[tuple[Facility, ...], ProviderError]:
    registry = dataset.registry
    resolved: dict[FacilityId, GeoPool] = {}
    unmatched: list[str] = []
    for pool in geo_pools:
        facility_id = registry.resolve_name(pool.name)
        if facility_id is None:
            unmatched.append(pool.name)
        else:
            resolved[facility_id] = pool

    if unmatched:
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"unresolved geo_sport pools (not in registry): {sorted(unmatched)}",
            )
        )

    merged: list[Facility] = []
    for facility in dataset.facilities:
        provenance = replace(facility.provenance, fetched_at=fetched_at)
        matched = resolved.get(facility.identity.facility_id)
        if matched is not None:
            merged.append(
                replace(
                    facility,
                    identity=replace(facility.identity, geo_sport_id=matched.source_id),
                    geo=matched.geo,
                    provenance=provenance,
                )
            )
        else:
            merged.append(replace(facility, provenance=provenance))
    return Ok(tuple(merged))
