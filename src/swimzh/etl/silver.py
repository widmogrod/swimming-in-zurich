"""Silver stage: reconcile Belegungsplan lane plans to canonical basins by URL-origin.

Reconciliation is a **deterministic URL-keyed inner join**, not a fuzzy title match. A basin
declares where its lane document lives (`Basin.lane_plan_source`, url + optional section); the
parse fetch-set is derived from those declarations, and each parsed plan carries the
`source_url` it was fetched from. `attach_lane_plans` builds a `url -> binding` index from the
model and joins each parsed plan straight back to the basin whose URL it came from — the parsed
header's `basin_hint` is IGNORED for a single-basin sheet (header-independence). The old
`normalise("<facility> <basin word>")` index is gone.

Failures are typed values, never guesses:
  * a URL no basin claims  -> a non-fatal `UnboundPlan` (audited, reported to stderr);
  * a duplicate `(url, section)` binding, or two plans bound to one basin -> a fatal `Err`;
  * a declared source that FAILED to fetch/parse -> its basin gets `LanePlanUnavailable(cause)`,
    first-class persisted state, never a silent `None`.
`PoolId`/`BasinId` are READ off the loaded facilities (never minted here).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
    LanePlanUnavailable,
    PoolId,
)
from swimzh.providers.belegungsplan import ParsedPlan

_SOURCE = "silver"

_BasinRef = tuple[PoolId, BasinId]


# --- URL-keyed binding index --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Binding:
    """One declared `(pool, basin)` a source URL/section resolves to. Read off the model — the
    `PoolId`/`BasinId` already exist on the loaded facility, so this mints no identity."""

    pool_id: PoolId
    basin_id: BasinId
    section: str | None


@dataclass(frozen=True, slots=True)
class BoundPlan:
    """A parsed plan joined to the basin that declared its source URL."""

    pool_id: PoolId
    basin_id: BasinId
    plan: LanePlan


@dataclass(frozen=True, slots=True)
class UnboundPlan:
    """A parsed plan that no declared basin claims — non-fatal, audited. `basin_hint` is the PDF
    header title, kept only for the operator report (never an identity key)."""

    source_url: str
    basin_hint: str
    reason: str


def build_url_bindings(
    facilities: Sequence[Facility],
) -> Result[dict[str, tuple[_Binding, ...]], ProviderError]:
    """Index every declared `lane_plan_source` as `url -> (binding, ...)`.

    A duplicate `(url, section)` — two basins claiming the same sheet section — is a **fatal**
    `Err(SchemaMismatch)` naming the offenders: it would make routing ambiguous, so we never
    guess. Distinct sections of one stacked sheet legitimately share a URL (each keyed by its
    own section token)."""
    bindings: dict[str, list[_Binding]] = defaultdict(list)
    seen: dict[tuple[str, str | None], _BasinRef] = {}
    for facility in facilities:
        for basin in facility.basins:
            source = basin.lane_plan_source
            if source is None:
                continue
            ref: _BasinRef = (facility.identity.facility_id, basin.basin_id)
            key = (source.url, source.section)
            existing = seen.get(key)
            if existing is not None:
                return Err(
                    SchemaMismatch(
                        source=_SOURCE,
                        detail=(
                            f"duplicate lane_plan_source binding "
                            f"(url={source.url!r}, section={source.section!r}) claimed by "
                            f"basins {existing} and {ref}"
                        ),
                    )
                )
            seen[key] = ref
            bindings[source.url].append(
                _Binding(pool_id=ref[0], basin_id=ref[1], section=source.section)
            )
    return Ok({url: tuple(bs) for url, bs in bindings.items()})


def bind_plans(
    parsed_plans: Sequence[ParsedPlan],
    url_bindings: Mapping[str, tuple[_Binding, ...]],
) -> tuple[tuple[BoundPlan, ...], tuple[UnboundPlan, ...]]:
    """Join parsed plans to bindings, keyed on `source_url`. S1 implements the **single-basin**
    arm only (one binding, no `section`): the plan binds directly and the `basin_hint` is
    ignored. A URL no basin claims, a stacked binding (deferred to S2 section routing), or a
    parser split that produced a count other than the single claimed basin all surface as a
    non-fatal `UnboundPlan` — never a silent positional misbind."""
    by_url: dict[str, list[ParsedPlan]] = defaultdict(list)
    for plan in parsed_plans:
        by_url[plan.source_url].append(plan)

    bound: list[BoundPlan] = []
    unbound: list[UnboundPlan] = []
    for url, plans in by_url.items():
        bindings = url_bindings.get(url, ())
        if not bindings:
            unbound.extend(
                UnboundPlan(url, p.basin_hint, "no basin declares this source url") for p in plans
            )
            continue
        if len(bindings) == 1 and bindings[0].section is None:
            if len(plans) == 1:
                binding = bindings[0]
                bound.append(BoundPlan(binding.pool_id, binding.basin_id, plans[0].plan))
            else:
                # Structural count-guard: a single-basin binding but the sheet split into several
                # sections — never positionally misbind, surface every fragment as unbound.
                unbound.extend(
                    UnboundPlan(
                        url,
                        p.basin_hint,
                        f"single-basin source split into {len(plans)} parsed sections",
                    )
                    for p in plans
                )
            continue
        # Stacked (N bindings with section tokens): section routing lands in S2.
        unbound.extend(
            UnboundPlan(url, p.basin_hint, "stacked-sheet section routing not available")
            for p in plans
        )
    return tuple(bound), tuple(unbound)


# --- attachment ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LanePlanAttachment:
    """The result of attaching lane plans: the augmented facilities, any non-fatal staleness
    warnings (a plan older than the schedule it refines), and the parsed plans that bound to no
    declared basin (reported, not fatal — e.g. an uncurated basin/pool)."""

    facilities: tuple[Facility, ...]
    warnings: tuple[str, ...]
    unbound: tuple[UnboundPlan, ...] = ()


def index_bound_plans(
    bound: Sequence[BoundPlan],
) -> Result[dict[_BasinRef, LanePlan], ProviderError]:
    """Index bound plans by `(pool, basin)`. Two plans bound to one basin is a **fatal** `Err` —
    never a silent overwrite of one basin's lane plan by another. (The URL-keyed join makes this
    unreachable for single-basin sheets — each basin declares one source — so it is a structural
    guard for stacked routing.)"""
    by_basin: dict[_BasinRef, LanePlan] = {}
    for bp in bound:
        ref = (bp.pool_id, bp.basin_id)
        if ref in by_basin:
            return Err(
                SchemaMismatch(source=_SOURCE, detail=f"two lane plans bound to one basin {ref}")
            )
        by_basin[ref] = bp.plan
    return Ok(by_basin)


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
    misses: Mapping[str, ProviderError],
    fetched_at: datetime,
) -> Result[LanePlanAttachment, ProviderError]:
    """Reconcile parsed plans to basins by URL-origin and attach them, stamping the run's
    `fetched_at`; record every extraction failure as first-class `LanePlanUnavailable` state.

    A declared source whose fetch/parse failed (`misses[url]`) stamps `LanePlanUnavailable(cause)`
    on every basin that declared it — a scoped failure that never touches the facility or its
    schedule. Two plans bound to one basin is a **fatal** `Err` (never a wrong overwrite). A plan
    that binds to no declared basin is reported in `LanePlanAttachment.unbound`, not fatal."""
    bindings_result = build_url_bindings(facilities)
    if isinstance(bindings_result, Err):
        return bindings_result
    url_bindings = bindings_result.value

    bound, unbound = bind_plans(parsed_plans, url_bindings)

    by_basin_result = index_bound_plans(bound)
    if isinstance(by_basin_result, Err):
        return by_basin_result
    by_basin = by_basin_result.value

    # A failed source stamps LanePlanUnavailable on every basin that declared it (keyed by URL).
    unavailable: dict[_BasinRef, LanePlanUnavailable] = {}
    for url, cause in misses.items():
        for binding in url_bindings.get(url, ()):
            unavailable[(binding.pool_id, binding.basin_id)] = LanePlanUnavailable(
                source_url=url,
                section=binding.section,
                cause=cause,
                observed_at=fetched_at,
            )

    warnings: list[str] = []
    merged: list[Facility] = []
    for facility in facilities:
        new_basins: list[Basin] = []
        changed = False
        for basin in facility.basins:
            ref = (facility.identity.facility_id, basin.basin_id)
            if ref in by_basin:
                changed = True
                plan = replace(by_basin[ref], fetched_at=fetched_at)
                warning = _staleness_warning(facility, basin, plan.valid_from)
                if warning is not None:
                    warnings.append(warning)
                new_basins.append(replace(basin, lane_plan=plan))
            elif ref in unavailable:
                changed = True
                new_basins.append(replace(basin, lane_plan=unavailable[ref]))
            else:
                new_basins.append(basin)
        merged.append(replace(facility, basins=tuple(new_basins)) if changed else facility)

    return Ok(
        LanePlanAttachment(
            facilities=tuple(merged),
            warnings=tuple(warnings),
            unbound=unbound,
        )
    )
