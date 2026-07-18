"""Ports (boundaries) as Protocols. Business code depends on these, never on a concrete
adapter. `main.py` is the only module that wires a concrete implementation.
"""

from __future__ import annotations

from typing import Protocol

from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.models import Facility


class SwimData(Protocol):
    """The facilities + calendar the query surface needs, however they are sourced
    (curated YAML today, the SQLite gold store tomorrow)."""

    def facilities(self) -> tuple[Facility, ...]: ...

    def calendar(self) -> ZurichCalendar: ...
