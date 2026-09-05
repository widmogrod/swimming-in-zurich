from fastapi import APIRouter, Request

from apps.web.api.health.model import HealthResponse
from apps.web.api.health.service import check_health
from apps.web.services.ports import SwimStore

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    # Read defensively: `/health` must answer even on a launch path that never wired a store.
    store: SwimStore | None = getattr(request.app.state, "swim_data", None)
    return check_health(store)
