"""The seed loader: assemble the DB-enforced identity spine from committed inputs.

The catalog is the **roster authority** — every one of the ~57 published pools becomes one
``pool`` row, its canonical id minted once as ``PoolId(catalog.pool_id)`` (already the name
slug, per S1). Curated authoring layers on top: a hand-authored ``kind`` overrides the WFS
``kind`` (curated-wins — e.g. *Wärmebad Käferberg* is ``thermal`` here, not the WFS ``indoor``),
the curated schedule payload rides along as a typed blob, and ``curation_status`` is **derived**
(``curated`` iff the pool has ≥1 basin with ≥1 rule) — never authored.

Every *other* identifier becomes a value pointing at the canonical id: names/aliases →
``pool_alias`` rows (deduped by ``norm``), external keys (crowdmonitor, geo_sport) →
``pool_xref`` rows. Those, plus the curated basins' hint index, are the ``Crosswalk`` that
``reconcile.resolve`` consults.

``PoolId`` is minted in exactly two places — here and ``build/reconcile`` — guarded by a
grep test. See ``docs/concepts/data-layer-architecture.md`` §3 for the enforcement model.
"""

from __future__ import annotations

from dataclasses import dataclass

from swimzh.build.normalize import normalize
from swimzh.build.reconcile import Crosswalk, PoolId
from swimzh.domain.catalog import PoolCatalogEntry
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import BasinKind, Facility, FacilityId, PoolKind
from swimzh.domain.registry import Registry
from swimzh.storage import codec

# German basin-type words used to build the lane-plan hint index (mirrors the PDF headers'
# prose, e.g. "… Schwimmerbecken"). `OTHER` has no meaningful word and is deliberately absent.
_BASIN_KIND_WORDS: dict[BasinKind, str] = {
    BasinKind.LAP: "Schwimmerbecken",
    BasinKind.NON_SWIMMER: "Nichtschwimmerbecken",
    BasinKind.DIVING: "Sprungbecken",
    BasinKind.VARIO: "Variobecken",
    BasinKind.TEACHING: "Lehrschwimmbecken",
    BasinKind.CHILDREN: "Kinderbecken",
    BasinKind.OUTDOOR: "Aussenbecken",
}

CURATED = "curated"
UNCURATED = "uncurated"


@dataclass(frozen=True, slots=True)
class PoolRow:
    """One roster row: canonical identity + catalog metadata + the (optional) curated blob."""

    id: PoolId
    name: str
    kind: PoolKind
    address: str
    geo: GeoPoint | None
    url: str | None
    description: str | None
    phone: str | None
    curation_status: str  # CURATED | UNCURATED — DERIVED, never authored
    facility_doc: str | None  # curated Facility JSON (codec), else None


@dataclass(frozen=True, slots=True)
class PoolAliasRow:
    pool_id: PoolId
    alias: str
    norm: str


@dataclass(frozen=True, slots=True)
class PoolXrefRow:
    pool_id: PoolId
    namespace: str
    ext_id: str


@dataclass(frozen=True, slots=True)
class PoolSpine:
    """The identity spine: the ``pool`` rows plus the alias/xref crosswalk that points at them."""

    pools: tuple[PoolRow, ...]
    aliases: tuple[PoolAliasRow, ...]
    xrefs: tuple[PoolXrefRow, ...]


def _is_curated(facility: Facility) -> bool:
    """Derived curation: a pool is curated iff it has at least one basin with a rule."""
    return any(basin.rules for basin in facility.basins)


def build_spine(
    catalog: tuple[PoolCatalogEntry, ...],
    facilities: tuple[Facility, ...],
    registry: Registry,
) -> PoolSpine:
    """Fold the roster (catalog) + curated authoring (facilities, registry) into the spine.

    Deterministic: rows are emitted in catalog order, aliases/xrefs deduped by their unique
    keys so the DB ``UNIQUE`` constraints are satisfiable and a re-build yields equal rows.
    """
    curated_by_id: dict[str, Facility] = {str(f.identity.facility_id): f for f in facilities}

    pools: list[PoolRow] = []
    aliases: list[PoolAliasRow] = []
    xrefs: list[PoolXrefRow] = []
    seen_norms: set[str] = set()
    seen_xrefs: set[tuple[str, str]] = set()

    for entry in sorted(catalog, key=lambda e: e.pool_id):
        pool_id = PoolId(entry.pool_id)
        identity = registry.get(FacilityId(entry.pool_id))
        facility = curated_by_id.get(entry.pool_id)

        # Curated-wins on kind: a hand-authored registry kind (richer/verified) overrides the
        # generic WFS catalog kind; catalog is the authority only where no curation exists.
        kind = identity.kind if identity is not None else entry.kind
        curation_status = CURATED if facility is not None and _is_curated(facility) else UNCURATED
        facility_doc = codec.dumps(facility) if facility is not None else None

        pools.append(
            PoolRow(
                id=pool_id,
                name=entry.name,
                kind=kind,
                address=entry.address,
                geo=entry.geo,
                url=entry.url,
                description=entry.description,
                phone=entry.phone,
                curation_status=curation_status,
                facility_doc=facility_doc,
            )
        )

        # Aliases: catalog name + registry name/aliases, deduped by normalized key.
        alias_terms = [entry.name]
        if identity is not None:
            alias_terms.extend((identity.name, *identity.aliases))
        for term in alias_terms:
            key = normalize(term)
            if key in seen_norms:
                continue
            seen_norms.add(key)
            aliases.append(PoolAliasRow(pool_id=pool_id, alias=term, norm=key))

        # Xrefs: external namespace keys pointing at this pool.
        if identity is not None:
            ext: list[tuple[str, str]] = []
            if identity.geo_sport_id is not None:
                ext.append(("geo_sport", identity.geo_sport_id))
            ext.extend(("crowdmonitor", key) for key in identity.crowdmonitor_keys)
            for namespace, ext_id in ext:
                if (namespace, ext_id) in seen_xrefs:
                    continue
                seen_xrefs.add((namespace, ext_id))
                xrefs.append(PoolXrefRow(pool_id=pool_id, namespace=namespace, ext_id=ext_id))

    return PoolSpine(pools=tuple(pools), aliases=tuple(aliases), xrefs=tuple(xrefs))


def build_crosswalk(spine: PoolSpine, facilities: tuple[Facility, ...]) -> Crosswalk:
    """The lookup tables ``reconcile.resolve`` consults, built from the spine + curated basins."""
    xref = {(x.namespace, x.ext_id): x.pool_id for x in spine.xrefs}
    alias = {a.norm: a.pool_id for a in spine.aliases}
    basin_hint, ambiguous = _basin_hint_index(facilities)
    return Crosswalk(
        xref=xref, alias=alias, basin_hint=basin_hint, ambiguous_hints=frozenset(ambiguous)
    )


def _basin_hint_index(
    facilities: tuple[Facility, ...],
) -> tuple[dict[str, PoolId], set[str]]:
    """Build a normalized ``basin_hint -> PoolId`` index (facility name/alias × basin word).

    A key that would map to two *different* pools is recorded as ambiguous and never used to
    resolve — a hint can only ever land on a single, unambiguous pool.
    """
    index: dict[str, PoolId] = {}
    ambiguous: set[str] = set()
    for facility in facilities:
        pool_id = PoolId(str(facility.identity.facility_id))
        facility_names = (facility.identity.name, *facility.identity.aliases)
        for basin in facility.basins:
            terms = [basin.name]
            word = _BASIN_KIND_WORDS.get(basin.kind)
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
