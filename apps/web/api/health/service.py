from apps.web.api.health.model import HealthResponse, SourceFreshnessOut
from apps.web.services.ports import SwimStore


def check_health(store: SwimStore | None = None) -> HealthResponse:
    """`ok` plus, when a store is wired, its per-source provenance — so an operator (or a
    monitor) can see "roster from 08-31, stale" without opening the SQLite file."""
    if store is None:
        return HealthResponse(status="ok")
    return HealthResponse(
        status="ok",
        sources=[
            SourceFreshnessOut(
                source=row.header.source,
                fetched_at=row.header.fetched_at.isoformat(),
                status=row.header.status.value,
                age_days=round(row.age_days, 2),
            )
            for row in store.source_freshness()
        ],
    )
