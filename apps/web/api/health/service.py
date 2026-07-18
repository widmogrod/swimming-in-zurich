from apps.web.api.health.model import HealthResponse


def check_health() -> HealthResponse:
    return HealthResponse(status="ok")
