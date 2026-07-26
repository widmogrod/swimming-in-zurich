"""Access-types endpoint — human-readable explanations of each session access type."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from swimzh.domain.access import ACCESS_TYPES


class AccessTypeOut(BaseModel):
    """One access type, as a KEY only.

    The English `label`/`description` prose was retired in S5: the client renders both
    from its own catalogue (`access.*`), so this endpoint no longer decides what language
    the explanation is in. The key is the contract.
    """

    key: str


class AccessTypesOut(BaseModel):
    types: list[AccessTypeOut]


router = APIRouter()


@router.get("/access-types", response_model=AccessTypesOut)
def access_types() -> AccessTypesOut:
    return AccessTypesOut(types=[AccessTypeOut(key=a.key) for a in ACCESS_TYPES])
