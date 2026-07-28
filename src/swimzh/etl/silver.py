"""Silver stage: reconcile Belegungsplan lane plans to canonical basins by URL-origin.

Reconciliation is a **deterministic URL-keyed inner join**, not a fuzzy title match. A basin
declares where its lane document lives (`Basin.lane_plan_source`, url + optional section); the
parse fetch-set is derived from those declarations, and each parsed plan carries the
`source_url` it was fetched from. `attach_lane_plans` builds a `url -> binding` index from the
model and joins each parsed plan straight back to the basin whose URL it came from. The old
fuzzy `normalise("<facility> <basin word>")` title index is gone.

  * a SINGLE-BASIN sheet (one binding, `section is None`) binds by URL alone — the parsed
    header's `basin_hint` is IGNORED (header-independence);
  * a STACKED multi-basin sheet shares one URL across sections, so each parsed section is routed
    to the binding whose declared `section` token is contained in `normalize(basin_hint)` — a
    scoped text match. It fails SAFE: a parsed section matching zero OR more-than-one declared
    token is surfaced as `UnboundPlan`, never positionally misbound.

Failures are typed values, never guesses:
  * a URL no basin claims, or a parsed section no declared token matches -> non-fatal
    `UnboundPlan` (audited, reported to stderr). An unbound plan is an *undeclared* extra fact
    (a discovered sheet no basin authored), not a missing declared one, so it stays non-fatal;
  * a declared `section` token that matched NONE of a fetched sheet's parsed headers -> non-fatal
    `UnmatchedSection` (audited: a likely parser-header regression that dropped a curated section,
    surfaced loud rather than left silently `None`);
  * a duplicate `(url, section)` binding, or two plans bound to one basin -> a fatal `Err`.

**Fail-fast (S4):** a declared source that FAILED to fetch/parse is **no longer** reconciled here
into a persisted `LanePlanUnavailable` that lets the facility build with a hole. That green-exit
posture is gone (owner decision 2026-07-28): the `scrape-lanes` orchestration aborts the whole run
non-zero on any such fetch/parse miss, before this attach ever runs, so `attach_lane_plans`
only ever sees successfully-parsed plans. The typed `ProviderError` *value* still rides the abort
message; only the persist-a-hole path is removed.
`PoolId`/`BasinId` are READ off the loaded facilities (never minted here).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.normalize import normalize
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import (
    Basin,
    BasinId,
    Facility,
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


@dataclass(frozen=True, slots=True)
class UnmatchedSection:
    """A basin that declared a stacked-sheet `section` token whose token matched NONE of its
    (successfully fetched) sheet's parsed headers, so the basin was left silently `None`. Almost
    always a parser header regression that dropped a curated section — audited (non-fatal) so the
    drop is loud rather than invisible. `pool_id`/`basin_id` are READ off the model, not minted."""

    source_url: str
    section: str
    pool_id: PoolId
    basin_id: BasinId


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


def _bind_single(
    url: str,
    plans: Sequence[ParsedPlan],
    binding: _Binding,
    bound: list[BoundPlan],
    unbound: list[UnboundPlan],
) -> None:
    """Single-basin arm: one whole-sheet binding (`section is None`). The plan binds directly and
    `basin_hint` is IGNORED (header-independence). Structural count-guard: if the sheet split into
    several parsed sections, never positionally misbind — surface every fragment as unbound."""
    if len(plans) == 1:
        bound.append(BoundPlan(binding.pool_id, binding.basin_id, plans[0].plan))
        return
    unbound.extend(
        UnboundPlan(
            url, p.basin_hint, f"single-basin source split into {len(plans)} parsed sections"
        )
        for p in plans
    )


def _bind_stacked(
    url: str,
    plans: Sequence[ParsedPlan],
    bindings: Sequence[_Binding],
    bound: list[BoundPlan],
    unbound: list[UnboundPlan],
) -> None:
    """Stacked arm: a multi-basin sheet shares one URL across sections, so the URL alone cannot
    discriminate. Route each parsed section to the binding whose declared `section` token appears
    (containment) in `normalize(basin_hint)` — a scoped text match, not a pure id join.

    Fail-safe on every ambiguity, never a silent misbind:
      * a parsed section matching no declared token  -> UnboundPlan (the structural count-guard:
        parser-split sections beyond the claimed bindings surface here, never positionally bound);
      * a parsed section matching more than one token -> UnboundPlan (overlapping tokens — one is a
        substring of the header — are ambiguous, so we decline to guess);
      * a declared section token matching no parsed header contributes nothing (the binding is
        simply absent from `bound`).
    """
    tokens: list[tuple[str, _Binding]] = []
    for binding in bindings:
        if binding.section is not None:
            tokens.append((normalize(binding.section), binding))
    for p in plans:
        hint = normalize(p.basin_hint)
        matches = [b for token, b in tokens if token and token in hint]
        if len(matches) == 1:
            bound.append(BoundPlan(matches[0].pool_id, matches[0].basin_id, p.plan))
        elif not matches:
            unbound.append(
                UnboundPlan(
                    url, p.basin_hint, "no declared section token matches this parsed header"
                )
            )
        else:
            unbound.append(
                UnboundPlan(
                    url, p.basin_hint, "parsed header matches multiple section tokens (ambiguous)"
                )
            )


def bind_plans(
    parsed_plans: Sequence[ParsedPlan],
    url_bindings: Mapping[str, tuple[_Binding, ...]],
) -> tuple[tuple[BoundPlan, ...], tuple[UnboundPlan, ...]]:
    """Join parsed plans to bindings, keyed on `source_url`.

    * single-basin (one binding, `section is None`) -> bind directly, `basin_hint` ignored;
    * stacked (any binding carries a `section` token) -> route each parsed section to the binding
      whose token appears in `normalize(basin_hint)`, with the structural count-guard;
    * a URL no basin claims -> every plan is a non-fatal `UnboundPlan`.

    Never a silent positional misbind: a count/token mismatch always surfaces as a typed
    `UnboundPlan`, and a token that matches no section simply contributes no binding."""
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
        elif len(bindings) == 1 and bindings[0].section is None:
            _bind_single(url, plans, bindings[0], bound, unbound)
        else:
            _bind_stacked(url, plans, bindings, bound, unbound)
    return tuple(bound), tuple(unbound)


# --- attachment ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LanePlanAttachment:
    """The result of attaching lane plans: the augmented facilities, any non-fatal staleness
    warnings (a plan older than the schedule it refines), the parsed plans that bound to no
    declared basin (`unbound` — e.g. an uncurated basin/pool), and declared stacked `section`
    tokens that matched no parsed header of their fetched sheet (`unmatched_sections` — a likely
    parser-header regression). All three are reported, not fatal."""

    facilities: tuple[Facility, ...]
    warnings: tuple[str, ...]
    unbound: tuple[UnboundPlan, ...] = ()
    unmatched_sections: tuple[UnmatchedSection, ...] = ()


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


def find_unmatched_sections(
    url_bindings: Mapping[str, tuple[_Binding, ...]],
    parsed_plans: Sequence[ParsedPlan],
) -> tuple[UnmatchedSection, ...]:
    """Declared stacked `section` tokens that matched NO parsed header of a sheet that DID parse.

    Mirrors the containment test `_bind_stacked` routes on (`token in normalize(basin_hint)`): a
    token present in none of its sheet's parsed headers produces no `BoundPlan`, leaving the basin
    silently `None`. Surfaced here so a parser-header regression that drops a curated section is
    auditable. Scoped to URLs that actually parsed — a whole-sheet fetch failure is recorded as
    `LanePlanUnavailable`, and a URL not fetched this run has no headers to compare against."""
    headers_by_url: dict[str, list[str]] = defaultdict(list)
    for plan in parsed_plans:
        headers_by_url[plan.source_url].append(normalize(plan.basin_hint))

    unmatched: list[UnmatchedSection] = []
    for url, bindings in url_bindings.items():
        headers = headers_by_url.get(url)
        if not headers:
            continue
        for binding in bindings:
            if binding.section is None:
                continue
            token = normalize(binding.section)
            if token and not any(token in header for header in headers):
                unmatched.append(
                    UnmatchedSection(url, binding.section, binding.pool_id, binding.basin_id)
                )
    return tuple(unmatched)


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
    """Reconcile SUCCESSFULLY-parsed plans to basins by URL-origin and attach them, stamping the
    run's `fetched_at`.

    Fail-fast (S4): a declared source whose fetch/parse FAILED never reaches here — the
    `scrape-lanes` orchestration aborts the whole run on any such miss first — so this only ever
    binds parsed plans, and no basin is left with a persisted `LanePlanUnavailable` hole. Two
    plans bound to one basin is a **fatal** `Err` (never a wrong overwrite). A plan that binds to
    no declared basin is reported in `LanePlanAttachment.unbound`, and a declared stacked `section`
    whose token matched no parsed header in `unmatched_sections` — both audited, not fatal."""
    bindings_result = build_url_bindings(facilities)
    if isinstance(bindings_result, Err):
        return bindings_result
    url_bindings = bindings_result.value

    bound, unbound = bind_plans(parsed_plans, url_bindings)
    unmatched_sections = find_unmatched_sections(url_bindings, parsed_plans)

    by_basin_result = index_bound_plans(bound)
    if isinstance(by_basin_result, Err):
        return by_basin_result
    by_basin = by_basin_result.value

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
            else:
                new_basins.append(basin)
        merged.append(replace(facility, basins=tuple(new_basins)) if changed else facility)

    return Ok(
        LanePlanAttachment(
            facilities=tuple(merged),
            warnings=tuple(warnings),
            unbound=unbound,
            unmatched_sections=unmatched_sections,
        )
    )
