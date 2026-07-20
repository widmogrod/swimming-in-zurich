"""Silver stage: reconcile Belegungsplan lane plans to canonical basins.

Reconciliation is **lookup, not fuzzy match**, applied at **basin granularity**: a parsed
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
from swimzh.core.normalize import normalize as _normalise
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import (
    BASIN_KIND_WORDS,
    Basin,
    BasinId,
    Facility,
    PoolId,
)
from swimzh.providers.belegungsplan import ParsedPlan

_SOURCE = "silver"


# --- basin-granular lane-plan reconciliation ----------------------------------------


_BasinRef = tuple[PoolId, BasinId]


@dataclass(frozen=True, slots=True)
class LanePlanAttachment:
    """The result of attaching parsed lane plans: the augmented facilities, any non-fatal
    staleness warnings (a plan older than the schedule it refines), and the hints that matched
    no curated basin (reported, not fatal — e.g. an uncurated basin/pool)."""

    facilities: tuple[Facility, ...]
    warnings: tuple[str, ...]
    unmatched: tuple[str, ...] = ()


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
            kind_word = BASIN_KIND_WORDS.get(basin.kind)
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
    run's `fetched_at`.

    An **ambiguous** hint (matches more than one basin) is a loud failure — attaching it could
    put a plan on the wrong basin. A hint that matches **no** basin (an uncurated basin/pool)
    is reported in `LanePlanAttachment.unmatched`, not fatal: a batch scrape of every published
    PDF should still attach the ones it can, not abort because one basin isn't curated."""
    index, ambiguous = _basin_hint_index(facilities)

    resolved: dict[_BasinRef, ParsedPlan] = {}
    unmatched: list[str] = []
    ambiguous_hits: list[str] = []
    for parsed in parsed_plans:
        key = _normalise(parsed.basin_hint)
        if key in ambiguous:
            ambiguous_hits.append(parsed.basin_hint)
        elif (ref := index.get(key)) is not None:
            resolved[ref] = parsed
        else:
            unmatched.append(parsed.basin_hint)

    if ambiguous_hits:
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"ambiguous belegungsplan basin hints: {sorted(ambiguous_hits)}",
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

    return Ok(
        LanePlanAttachment(
            facilities=tuple(merged),
            warnings=tuple(warnings),
            unmatched=tuple(sorted(unmatched)),
        )
    )
