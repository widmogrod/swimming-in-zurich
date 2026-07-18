"""Health endpoint — HTTP concerns only; logic lives in service.py."""

from fastapi import APIRouter

from apps.web.api.health.model import HealthResponse
from apps.web.api.health.service import check_health

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return check_health()
