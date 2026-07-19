"""Silver stage: normalise + reconcile sources to canonical facility ids.

Reconciliation is **lookup, not fuzzy match**: every geo_sport pool name must resolve to a
canonical id via the registry. Any name that does not is a **loud failure** (an error value
naming the offenders) — never a silent drop or a guessed match. Matched geo is merged into
the curated facilities (coordinates + geo_sport_id crosswalk), and provenance is stamped
with the run's `fetched_at`.

The same discipline applies at **basin granularity** for Belegungsplan lane plans: a parsed
plan carries only a `basin_hint` (the PDF header title, e.g. "Hallenbad City
Schwimmerbecken"). `attach_lane_plans` resolves that hint to exactly one `Basin` by a
built-from-the-model lookup index (facility name/alias × basin name/kind German word) — an
exact normalised match, never fuzzy. A hint that resolves to nothing, or ambiguously to two
basins, is a loud failure naming the offenders; the plan is **never** attached to a guessed
basin. Resolved plans are stamped with the run's `fetched_at`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import Basin, BasinId, BasinKind, Facility, FacilityId
from swimzh.providers.belegungsplan import ParsedPlan
from swimzh.providers.curated import Dataset
from swimzh.providers.geo_sport import GeoPool

_SOURCE = "silver"

# German basin-type words used to build a lane-plan hint index. Mirrors the `BasinKind`
# prose the PDF headers use ("… Schwimmerbecken"); `OTHER` has no meaningful word and is
# deliberately absent so it never seeds an over-broad key.
_BASIN_KIND_WORDS: dict[BasinKind, str] = {
    BasinKind.LAP: "Schwimmerbecken",
    BasinKind.NON_SWIMMER: "Nichtschwimmerbecken",
    BasinKind.DIVING: "Sprungbecken",
    BasinKind.VARIO: "Variobecken",
    BasinKind.TEACHING: "Lehrschwimmbecken",
    BasinKind.CHILDREN: "Kinderbecken",
    BasinKind.OUTDOOR: "Aussenbecken",
}


def _normalise(text: str) -> str:
    return " ".join(text.strip().casefold().split())


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


# --- basin-granular lane-plan reconciliation ----------------------------------------


_BasinRef = tuple[FacilityId, BasinId]


@dataclass(frozen=True, slots=True)
class LanePlanAttachment:
    """The result of attaching parsed lane plans: the augmented facilities plus any
    non-fatal staleness warnings (a plan older than the schedule it refines)."""

    facilities: tuple[Facility, ...]
    warnings: tuple[str, ...]


def _basin_hint_index(
    facilities: Sequence[Facility],
) -> tuple[dict[str, _BasinRef], set[str]]:
    """Build a normalised `basin_hint -> (facility, basin)` lookup from the model.

    Keys are (facility name or alias) × (basin name or its `BasinKind` German word). A key
    that would map to two *different* basins is recorded as ambiguous and never used to
    resolve — so a hint can only ever land on a single, unambiguous basin.
    """
    index: dict[str, _BasinRef] = {}
    ambiguous: set[str] = set()
    for facility in facilities:
        facility_names = (facility.identity.name, *facility.identity.aliases)
        for basin in facility.basins:
            ref: _BasinRef = (facility.identity.facility_id, basin.basin_id)
            basin_terms = [basin.name]
            kind_word = _BASIN_KIND_WORDS.get(basin.kind)
            if kind_word is not None:
                basin_terms.append(kind_word)
            for facility_name in facility_names:
                for basin_term in basin_terms:
                    key = _normalise(f"{facility_name} {basin_term}")
                    existing = index.get(key)
                    if existing is not None and existing != ref:
                        ambiguous.add(key)
                    else:
                        index[key] = ref
    return index, ambiguous


def _staleness_warning(
    facility: Facility, basin: Basin, plan_valid_from: date | None
) -> str | None:
    valid_as_of = facility.provenance.valid_as_of
    if plan_valid_from is not None and valid_as_of is not None and plan_valid_from < valid_as_of:
        return (
            f"{facility.identity.name} / {basin.name}: lane plan valid_from "
            f"{plan_valid_from.isoformat()} predates schedule valid_as_of "
            f"{valid_as_of.isoformat()} (lane data may be stale)"
        )
    return None


def attach_lane_plans(
    facilities: Sequence[Facility],
    parsed_plans: Sequence[ParsedPlan],
    fetched_at: datetime,
) -> Result[LanePlanAttachment, ProviderError]:
    """Reconcile each parsed plan's `basin_hint` to a `Basin` and attach it, stamping the
    run's `fetched_at`. Unmatched or ambiguous hints are a loud failure naming them."""
    index, ambiguous = _basin_hint_index(facilities)

    resolved: dict[_BasinRef, ParsedPlan] = {}
    unmatched: list[str] = []
    for parsed in parsed_plans:
        key = _normalise(parsed.basin_hint)
        ref = index.get(key)
        if ref is None or key in ambiguous:
            unmatched.append(parsed.basin_hint)
        else:
            resolved[ref] = parsed

    if unmatched:
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"unresolved belegungsplan basin hints: {sorted(unmatched)}",
            )
        )

    warnings: list[str] = []
    merged: list[Facility] = []
    for facility in facilities:
        new_basins: list[Basin] = []
        changed = False
        for basin in facility.basins:
            match = resolved.get((facility.identity.facility_id, basin.basin_id))
            if match is None:
                new_basins.append(basin)
                continue
            changed = True
            plan = replace(match.plan, fetched_at=fetched_at)
            warning = _staleness_warning(facility, basin, plan.valid_from)
            if warning is not None:
                warnings.append(warning)
            new_basins.append(replace(basin, lane_plan=plan))
        merged.append(replace(facility, basins=tuple(new_basins)) if changed else facility)

    return Ok(LanePlanAttachment(facilities=tuple(merged), warnings=tuple(warnings)))
