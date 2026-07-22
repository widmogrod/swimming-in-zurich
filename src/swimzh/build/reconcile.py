"""The identity seam — the SOLE producer of a canonical ``PoolId``.

Providers emit a ``SourceRef`` (never an id); ``resolve`` turns one into a ``PoolId`` by
**lookup, never fuzzy match**: xref ``(namespace, ext_id)`` → alias ``norm(name)``. An
unresolved ref is a loud ``Err`` naming the offender — never a guess that silently attaches
data to the wrong pool. (The former ``BasinHint`` arm — a fuzzy Belegungsplan-title lookup —
was retired: lane plans now reconcile by URL-origin identity in ``etl/silver``, not by title.)

Honesty note (see docs/concepts/data-layer-architecture.md §3): ``PoolId`` is a ``NewType``,
which has **no** private constructor — mypy accepts ``PoolId("anything")`` from anywhere. The
airtight lock is the DB ``UNIQUE`` constraint on ``pool_alias.norm`` /
``pool_xref(namespace, ext_id)``. This seam plus a grep-guard test (``PoolId(`` may appear
only here and in the seed loader) are the by-convention layers above that DB guarantee, not a
compile-time forbidding. State the enforcement as *grep + DB*, never "the compiler forbids it".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import assert_never

from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.normalize import normalize
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import PoolId

_SOURCE = "reconcile"


# --- SourceRef: the closed union a provider emits instead of an id --------------------


@dataclass(frozen=True, slots=True)
class Xref:
    """A native external key (geo_sport ``poi_hallenbad_view.2``, a crowdmonitor key)."""

    namespace: str
    ext_id: str


@dataclass(frozen=True, slots=True)
class Name:
    """A human display name / alias (a WFS pool name, a curated alias)."""

    display: str


SourceRef = Xref | Name


# --- the crosswalk (lookup tables) and the resolve seam -------------------------------


@dataclass(frozen=True, slots=True)
class Crosswalk:
    """The lookup tables reconcile consults — built from the identity spine by the seed
    loader. Every value is a ``PoolId`` that already exists in the ``pool`` table."""

    xref: dict[tuple[str, str], PoolId]
    alias: dict[str, PoolId]

    def resolve(self, ref: SourceRef) -> Result[PoolId, ProviderError]:
        return resolve(ref, self)


# --- resolution classification (the matched/not-found distinction) --------------------
#
# ``resolve`` collapses the outcome to ``Ok | Err`` for its single-ref callers; ``resolve_all``
# needs to tell a *benign* miss (a ref with no crosswalk entry — reportable, not fatal) apart
# from a match, without parsing an error string. ``_classify`` carries that distinction as a
# typed value. ``Xref``/``Name`` are dict lookups (a key maps to a single pool by construction),
# so a ref either matches exactly one pool or misses benignly — there is no ambiguous class.


@dataclass(frozen=True, slots=True)
class _Matched:
    """The ref resolved to exactly one pool."""

    pool_id: PoolId


@dataclass(frozen=True, slots=True)
class _NotFound:
    """A benign miss — no crosswalk entry for this ref. Reportable, not fatal."""

    error: ProviderError


_Resolution = _Matched | _NotFound


def _classify(ref: SourceRef, crosswalk: Crosswalk) -> _Resolution:
    """Look a ``SourceRef`` up, distinguishing a match from a benign miss."""
    match ref:
        case Xref(namespace, ext_id):
            pool_id = crosswalk.xref.get((namespace, ext_id))
            if pool_id is None:
                return _NotFound(
                    SchemaMismatch(
                        source=_SOURCE,
                        detail=f"unresolved xref: namespace={namespace!r} ext_id={ext_id!r}",
                    )
                )
            return _Matched(pool_id)
        case Name(display):
            pool_id = crosswalk.alias.get(normalize(display))
            if pool_id is None:
                return _NotFound(
                    SchemaMismatch(
                        source=_SOURCE, detail=f"unresolved name (no alias): {display!r}"
                    )
                )
            return _Matched(pool_id)
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(ref)


def resolve(ref: SourceRef, crosswalk: Crosswalk) -> Result[PoolId, ProviderError]:
    """Resolve a ``SourceRef`` to exactly one ``PoolId`` by lookup, or a loud ``Err`` on a miss."""
    resolution = _classify(ref, crosswalk)
    match resolution:
        case _Matched(pool_id):
            return Ok(pool_id)
        case _NotFound(error):
            return Err(error)
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(resolution)


def _ref_label(ref: SourceRef) -> str:
    """A short human label for a ref, for the inspectable unmatched list."""
    match ref:
        case Xref(namespace, ext_id):
            return f"{namespace}:{ext_id}"
        case Name(display):
            return display
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(ref)


@dataclass(frozen=True, slots=True)
class ReconcileOutcome[Payload]:
    """The result of resolving a batch of extracts: the pools we could key, and the benign
    misses we could not (their display labels).

    ``unresolved`` is a **required** field with no default — a caller cannot construct an
    outcome that silently swallows a miss, and every consumer must decide what to do with the
    unmatched labels. An *ambiguous* ref never lands here: it aborts the whole batch as an
    ``Err`` (see ``resolve_all``), preserving never-attach-to-the-wrong-pool by type.
    """

    resolved: tuple[tuple[PoolId, Payload], ...]
    unresolved: tuple[str, ...]


def resolve_all[Payload](
    extracts: Iterable[tuple[SourceRef, Payload]], crosswalk: Crosswalk
) -> Result[ReconcileOutcome[Payload], ProviderError]:
    """Resolve every provider extract's ``SourceRef`` to a ``PoolId`` — resilient to benign
    misses.

    A benign miss (a ``Name``/``Xref`` with no crosswalk entry) is collected into
    ``ReconcileOutcome.unresolved`` (its display label) rather than aborting the batch, so one
    unmatched WFS name no longer discards every good scrape. On success returns the keyed
    payloads, which ``compose`` then folds per pool. The ``Err`` arm is retained for the callers
    that treat a caller-supplied fatal reconcile error uniformly (see ``cli.scrape_gold``)."""
    keyed: list[tuple[PoolId, Payload]] = []
    unresolved: list[str] = []
    for ref, payload in extracts:
        resolution = _classify(ref, crosswalk)
        match resolution:
            case _Matched(pool_id):
                keyed.append((pool_id, payload))
            case _NotFound(_):
                unresolved.append(_ref_label(ref))
            case _:  # pragma: no cover - exhaustiveness guard
                assert_never(resolution)
    return Ok(ReconcileOutcome(resolved=tuple(keyed), unresolved=tuple(unresolved)))


# --- crosswalk construction (the SOLE PoolId minting for lookup tables) ----------------


def crosswalk_from_rows(
    alias_rows: Iterable[tuple[str, str]],
    xref_rows: Iterable[tuple[str, str, str]],
) -> Crosswalk:
    """Assemble a ``Crosswalk`` from stored spine rows.

    ``alias_rows`` are ``(norm, pool_id)``; ``xref_rows`` are ``(namespace, ext_id, pool_id)``
    — the plain-string projections of the ``pool_alias`` / ``pool_xref`` tables. This seam mints
    the ``PoolId`` values (legal here — reconcile is one of the two allowed minting sites), so a
    later builder (``scrape-gold``) resolves against the very spine ``build`` laid down, never a
    second id namespace.
    """
    return Crosswalk(
        xref={(namespace, ext_id): PoolId(pool_id) for namespace, ext_id, pool_id in xref_rows},
        alias={norm: PoolId(pool_id) for norm, pool_id in alias_rows},
    )
