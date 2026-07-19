"""Request/response models for the swim endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class OptionOut(BaseModel):
    facility: str
    kind: str  # facility kind (indoor/outdoor/…), for the glance badge context
    basin: str
    length_m: float | None  # basin length — the fat left badge; None degrades gracefully
    lanes: int | None  # basin lane count — the badge's "N lane" sub-line; None => length-only
    start: str
    end: str
    access: str
    eligible: bool
    reason: str
    price: str | None
    distance_km: float | None
    open_now: bool
    valid_as_of: str | None
    source: str  # provenance source (e.g. stadt-zuerich.ch), for the ⓘ stamp
    curated: bool  # True = hand-curated, False = scraped


class StatusOut(BaseModel):
    facility: str
    status: str  # "closed" | "uncurated"
    detail: str


class NoticeOut(BaseModel):
    facility: str
    text: str


class AnswerOut(BaseModel):
    options: list[OptionOut]
    statuses: list[StatusOut]
    warnings: list[str]
    notices: list[NoticeOut]
