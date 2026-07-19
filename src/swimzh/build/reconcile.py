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

from dataclasses import dataclass
from typing import NewType, assert_never

from swimzh.build.normalize import normalize
from swimzh.core.errors import ProviderError, SchemaMismatch
from swimzh.core.result import Err, Ok, Result

PoolId = NewType("PoolId", str)

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
