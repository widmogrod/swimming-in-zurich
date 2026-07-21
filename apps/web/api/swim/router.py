"""Swim endpoint — HTTP concerns only: parse/validate query params, delegate to service."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from apps.web.api.swim.model import AnswerOut
from apps.web.api.swim.service import build_answer
from apps.web.deps import get_swim_data
from swimzh.domain.geo import GeoPoint
from swimzh.domain.person import Gender

router = APIRouter()

_GENDERS = {"female": Gender.FEMALE, "male": Gender.MALE, "diverse": Gender.DIVERSE}


@router.get("/swim", response_model=AnswerOut)
def swim(
    request: Request,
    # `at` is OPTIONAL: an absent moment means "now" — the service materialises server time
    # (Europe/Zurich) once at the boundary, so a bare /swim answers instead of 422-ing.
    at: datetime | None = None,
    gender: str | None = None,
    age: int | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    eligible_only: bool = True,
) -> AnswerOut:
    parsed_gender: Gender | None = None
    if gender is not None:
        parsed_gender = _GENDERS.get(gender.lower())
        if parsed_gender is None:
            raise HTTPException(
                status_code=400, detail=f"invalid gender {gender!r}; use female|male|diverse"
            )

    near: GeoPoint | None = None
    if lat is not None and lon is not None:
        near = GeoPoint(lat=lat, lon=lon)
    elif (lat is None) != (lon is None):
        raise HTTPException(status_code=400, detail="provide both lat and lon, or neither")

    return build_answer(
        get_swim_data(request),
        gender=parsed_gender,
        age=age,
        at=at,
        near=near,
        radius_km=radius_km,
        eligible_only=eligible_only,
    )
