"""The person asking the question: how we model gender and age for eligibility.

Both fields are optional — the user may not want to specify them. Absent information is
modelled as `None` and surfaces as "not determinable" in eligibility, never as a silent
assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Gender(Enum):
    """Only distinctions that actually gate access are modelled. Zürich runs some
    women-only ("Frauenbad") sessions; that is the single gender-based access rule, so we
    represent the axis it turns on. `DIVERSE` covers non-binary identities."""

    FEMALE = "female"
    MALE = "male"
    DIVERSE = "diverse"


@dataclass(frozen=True, slots=True)
class Person:
    gender: Gender | None = None
    age: int | None = None
