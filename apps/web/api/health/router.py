"""`/health`: liveness plus the store's per-source provenance (which source each fact came
from, fetched when, kept stale or not). Thin: the accessor lives in `deps.py`, the shaping in
`service.py`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.web.api.health.model import HealthResponse
from apps.web.api.health.service import check_health
from apps.web.deps import get_swim_data_or_none
from apps.web.services.ports import SwimStore

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(store: Annotated[SwimStore | None, Depends(get_swim_data_or_none)]) -> HealthResponse:
    return check_health(store)
