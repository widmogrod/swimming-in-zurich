"""Pools endpoint — list all catalog pools, optionally filtered by kind."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from apps.web.api.pools.model import PoolsOut
from apps.web.api.pools.service import list_pools
from apps.web.deps import get_catalog
from swimzh.domain.models import PoolKind

router = APIRouter()

_KINDS = {k.value for k in PoolKind}


@router.get("/pools", response_model=PoolsOut)
def pools(request: Request, kind: str | None = None) -> PoolsOut:
    if kind is not None and kind not in _KINDS:
        raise HTTPException(
            status_code=400, detail=f"invalid kind {kind!r}; one of {sorted(_KINDS)}"
        )
    return list_pools(get_catalog(request), kind)
