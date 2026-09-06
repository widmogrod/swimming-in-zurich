from pydantic import BaseModel


class SourceFreshnessOut(BaseModel):
    """Where one source's facts came from: when they were fetched, whether this store kept them
    STALE (the source was unreachable at build time), and how old they were at build time."""

    source: str
    fetched_at: str
    status: str
    age_days: float


class HealthResponse(BaseModel):
    status: str
    #: Empty on a store built before the lake existed — an honest "unknown", never fabricated.
    sources: list[SourceFreshnessOut] = []
