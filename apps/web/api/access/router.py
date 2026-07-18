"""Access-types endpoint — human-readable explanations of each session access type."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from swimzh.domain.access import ACCESS_TYPES


class AccessTypeOut(BaseModel):
    key: str
    label: str
    description: str


class AccessTypesOut(BaseModel):
    types: list[AccessTypeOut]


router = APIRouter()


@router.get("/access-types", response_model=AccessTypesOut)
def access_types() -> AccessTypesOut:
    return AccessTypesOut(
        types=[
            AccessTypeOut(key=a.key, label=a.label, description=a.description) for a in ACCESS_TYPES
        ]
    )
