"""The pool identity registry: the single source of canonical IDs and the crosswalk into
other sources' names.

Providers map *into* canonical IDs by **lookup here** — never by fuzzy matching. A name we
cannot resolve is returned as `None` so the caller can fail loudly / queue it for review,
rather than guessing and silently attaching data to the wrong pool.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from swimzh.core.normalize import normalize as _normalise
from swimzh.domain.models import FacilityId, PoolIdentity


class Registry:
    def __init__(self, identities: Iterable[PoolIdentity]) -> None:
        self._by_id: dict[FacilityId, PoolIdentity] = {}
        self._alias_index: dict[str, FacilityId] = {}
        self._geo_sport_index: dict[str, FacilityId] = {}
        self._crowdmonitor_index: dict[str, FacilityId] = {}
        for identity in identities:
            self._register(identity)

    def _register(self, identity: PoolIdentity) -> None:
        fid = identity.facility_id
        if fid in self._by_id:
            raise ValueError(f"duplicate facility_id in registry: {fid}")
        self._by_id[fid] = identity
        for alias in (identity.name, *identity.aliases):
            key = _normalise(alias)
            existing = self._alias_index.get(key)
            if existing is not None and existing != fid:
                raise ValueError(f"alias {alias!r} maps to both {existing} and {fid}")
            self._alias_index[key] = fid
        if identity.geo_sport_id is not None:
            self._geo_sport_index[identity.geo_sport_id] = fid
        for key in identity.crowdmonitor_keys:
            self._crowdmonitor_index[key] = fid

    @property
    def identities(self) -> Mapping[FacilityId, PoolIdentity]:
        return self._by_id

    def get(self, facility_id: FacilityId) -> PoolIdentity | None:
        return self._by_id.get(facility_id)

    def resolve_name(self, name: str) -> FacilityId | None:
        """Resolve a display name / alias to a canonical id, or None if unknown."""
        return self._alias_index.get(_normalise(name))

    def resolve_geo_sport(self, geo_sport_id: str) -> FacilityId | None:
        return self._geo_sport_index.get(geo_sport_id)

    def resolve_crowdmonitor(self, key: str) -> FacilityId | None:
        return self._crowdmonitor_index.get(key)
