"""The pool identity registry: the single source of canonical `PoolIdentity` records.

Built from the curated identities, it enforces that no two pools claim the same
`facility_id` or the same normalised alias (a duplicate is a loud `ValueError` at
construction, never a silently-overwritten crosswalk), and serves identities by canonical id.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from swimzh.core.normalize import normalize as _normalise
from swimzh.domain.models import PoolId, PoolIdentity


class Registry:
    def __init__(self, identities: Iterable[PoolIdentity]) -> None:
        self._by_id: dict[PoolId, PoolIdentity] = {}
        self._alias_index: dict[str, PoolId] = {}
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

    @property
    def identities(self) -> Mapping[PoolId, PoolIdentity]:
        return self._by_id

    def get(self, facility_id: PoolId) -> PoolIdentity | None:
        return self._by_id.get(facility_id)
