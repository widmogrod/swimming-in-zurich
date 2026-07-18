"""Request/response models for the swim endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class OptionOut(BaseModel):
    facility: str
    basin: str
    start: str
    end: str
    access: str
    eligible: bool
    reason: str
    price: str | None
    distance_km: float | None
    open_now: bool
    valid_as_of: str | None


class StatusOut(BaseModel):
    facility: str
    status: str  # "closed" | "uncurated"
    detail: str


class AnswerOut(BaseModel):
    options: list[OptionOut]
    statuses: list[StatusOut]
    warnings: list[str]
