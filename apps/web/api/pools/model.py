"""Request/response models for the pools listing."""

from __future__ import annotations

from pydantic import BaseModel


class PoolOut(BaseModel):
    pool_id: str
    name: str
    kind: str
    address: str
    lat: float | None
    lon: float | None
    url: str | None
    description: str | None
    phone: str | None


class PoolsOut(BaseModel):
    count: int
    kinds: list[str]  # kinds present, for filter UIs
    pools: list[PoolOut]
