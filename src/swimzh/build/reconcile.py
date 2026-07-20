"""The identity seam — the SOLE producer of a canonical ``PoolId``.

Providers emit a ``SourceRef`` (never an id); ``resolve`` turns one into a ``PoolId`` by
**lookup, never fuzzy match**, in a fixed order: xref ``(namespace, ext_id)`` → alias
``norm(name)`` → basin-hint index. An unresolved or ambiguous ref is a loud ``Err`` naming
the offender — never a guess that silently attaches data to the wrong pool.

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
from typing import NewType, assert_never

from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.normalize import normalize
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.models import BasinKind, Facility

PoolId = NewType("PoolId", str)

_SOURCE = "reconcile"

# German basin-type words used to build the lane-plan / basin-hint index — the single home
# for this vocabulary (previously duplicated in ``build/seed`` and ``etl/silver``). Mirrors
# the ``BasinKind`` prose the Belegungsplan headers use ("… Schwimmerbecken"); ``OTHER`` has
# no meaningful word and is deliberately absent so it never seeds an over-broad key.
BASIN_KIND_WORDS: dict[BasinKind, str] = {
    BasinKind.LAP: "Schwimmerbecken",
    BasinKind.NON_SWIMMER: "Nichtschwimmerbecken",
    BasinKind.DIVING: "Sprungbecken",
    BasinKind.VARIO: "Variobecken",
    BasinKind.TEACHING: "Lehrschwimmbecken",
    BasinKind.CHILDREN: "Kinderbecken",
    BasinKind.OUTDOOR: "Aussenbecken",
}


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


@dataclass(frozen=True, slots=True)
class BasinHint:
    """A Belegungsplan header title, e.g. ``"Hallenbad City Schwimmerbecken"``."""

    text: str


@dataclass(frozen=True, slots=True)
class Global:
    """An identity-free payload (a city-wide price table) — belongs to no single pool."""


SourceRef = Xref | Name | BasinHint | Global


# --- the crosswalk (lookup tables) and the resolve seam -------------------------------


@dataclass(frozen=True, slots=True)
class Crosswalk:
    """The lookup tables reconcile consults — built from the identity spine by the seed
    loader. Every value is a ``PoolId`` that already exists in the ``pool`` table."""

    xref: dict[tuple[str, str], PoolId]
    alias: dict[str, PoolId]
    basin_hint: dict[str, PoolId]
    ambiguous_hints: frozenset[str]

    def resolve(self, ref: SourceRef) -> Result[PoolId, ProviderError]:
        return resolve(ref, self)


def resolve(ref: SourceRef, crosswalk: Crosswalk) -> Result[PoolId, ProviderError]:
    """Resolve a ``SourceRef`` to exactly one ``PoolId`` by lookup, or a loud ``Err``."""
    match ref:
        case Xref(namespace, ext_id):
            pool_id = crosswalk.xref.get((namespace, ext_id))
            if pool_id is None:
                return Err(
                    SchemaMismatch(
                        source=_SOURCE,
                        detail=f"unresolved xref: namespace={namespace!r} ext_id={ext_id!r}",
                    )
                )
            return Ok(pool_id)
        case Name(display):
            pool_id = crosswalk.alias.get(normalize(display))
            if pool_id is None:
                return Err(
                    SchemaMismatch(
                        source=_SOURCE, detail=f"unresolved name (no alias): {display!r}"
                    )
                )
            return Ok(pool_id)
        case BasinHint(text):
            key = normalize(text)
            if key in crosswalk.ambiguous_hints:
                return Err(SchemaMismatch(source=_SOURCE, detail=f"ambiguous basin hint: {text!r}"))
            pool_id = crosswalk.basin_hint.get(key)
            if pool_id is None:
                return Err(
                    SchemaMismatch(source=_SOURCE, detail=f"unresolved basin hint: {text!r}")
                )
            return Ok(pool_id)
        case Global():
            return Err(
                SchemaMismatch(
                    source=_SOURCE,
                    detail="Global ref is identity-free; it resolves to many pools via compose, "
                    "never to a single PoolId",
                )
            )
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(ref)


def _ref_label(ref: SourceRef) -> str:
    """A short human label for a ref, for the inspectable unmatched list."""
    match ref:
        case Xref(namespace, ext_id):
            return f"{namespace}:{ext_id}"
        case Name(display):
            return display
        case BasinHint(text):
            return text
        case Global():
            return "<global>"
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(ref)


def resolve_all[Payload](
    extracts: Iterable[tuple[SourceRef, Payload]], crosswalk: Crosswalk
) -> Result[tuple[tuple[PoolId, Payload], ...], ProviderError]:
    """Resolve every provider extract's ``SourceRef`` to a ``PoolId`` — loud on any miss.

    Mirrors the discipline of ``silver.reconcile``: a single unresolved ref aborts the batch
    with a typed ``Err`` naming *all* the offenders, so a scrape can never silently attach its
    payload to the wrong pool (or drop it unnoticed). On success returns the keyed payloads,
    which ``compose`` then folds per pool.
    """
    keyed: list[tuple[PoolId, Payload]] = []
    unresolved: list[str] = []
    for ref, payload in extracts:
        match resolve(ref, crosswalk):
            case Ok(pool_id):
                keyed.append((pool_id, payload))
            case Err(_):
                unresolved.append(_ref_label(ref))
    if unresolved:
        return Err(
            SchemaMismatch(
                source=_SOURCE,
                detail=f"unresolved scrape refs (no pool matched): {sorted(unresolved)}",
            )
        )
    return Ok(tuple(keyed))


# --- crosswalk construction (the SOLE PoolId minting for lookup tables) ----------------


def build_basin_hint_index(
    facilities: Iterable[Facility],
) -> tuple[dict[str, PoolId], set[str]]:
    """Build a normalized ``basin_hint -> PoolId`` index (facility name/alias × basin word).

    Keys are (facility name or alias) × (basin name or its ``BasinKind`` German word). A key
    that would map to two *different* pools is recorded as ambiguous and never used to resolve —
    a hint can only ever land on a single, unambiguous pool. The sole home for this index
    (previously duplicated in ``build/seed``); ``etl/silver`` keeps a basin-*granular* variant
    for lane-plan attachment.
    """
    index: dict[str, PoolId] = {}
    ambiguous: set[str] = set()
    for facility in facilities:
        pool_id = PoolId(str(facility.identity.facility_id))
        facility_names = (facility.identity.name, *facility.identity.aliases)
        for basin in facility.basins:
            terms = [basin.name]
            word = BASIN_KIND_WORDS.get(basin.kind)
            if word is not None:
                terms.append(word)
            for facility_name in facility_names:
                for term in terms:
                    key = normalize(f"{facility_name} {term}")
                    existing = index.get(key)
                    if existing is not None and existing != pool_id:
                        ambiguous.add(key)
                    else:
                        index[key] = pool_id
    return index, ambiguous


def crosswalk_from_rows(
    alias_rows: Iterable[tuple[str, str]],
    xref_rows: Iterable[tuple[str, str, str]],
    curated: Iterable[Facility],
) -> Crosswalk:
    """Assemble a ``Crosswalk`` from stored spine rows + the curated facilities.

    ``alias_rows`` are ``(norm, pool_id)``; ``xref_rows`` are ``(namespace, ext_id, pool_id)``
    — the plain-string projections of the ``pool_alias`` / ``pool_xref`` tables. This seam mints
    the ``PoolId`` values (legal here — reconcile is one of the two allowed minting sites), so a
    later builder (``scrape-gold``) resolves against the very spine ``build`` laid down, never a
    second id namespace.
    """
    basin_hint, ambiguous = build_basin_hint_index(curated)
    return Crosswalk(
        xref={(namespace, ext_id): PoolId(pool_id) for namespace, ext_id, pool_id in xref_rows},
        alias={norm: PoolId(pool_id) for norm, pool_id in alias_rows},
        basin_hint=basin_hint,
        ambiguous_hints=frozenset(ambiguous),
    )
