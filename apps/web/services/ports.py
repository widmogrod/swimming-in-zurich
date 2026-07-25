"""Ports (boundaries) as Protocols. Business code depends on these, never on a concrete
adapter. `main.py` is the only module that wires a concrete implementation.
"""

from __future__ import annotations

from typing import Protocol

from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import RosterEntry
from swimzh.domain.models import Facility

# The live water-temperature port lives in the domain (`domain.query`); re-exported here so the
# app's boundary surface names it in one place (business code depends on this Protocol, never on
# a concrete adapter). `main.py` is the only module that wires a concrete implementation.
from swimzh.domain.query import TemperatureProvider as TemperatureProvider


class SwimStore(Protocol):
    """The one gold store the app reads: curated facilities (schedules), the full pool roster
    (all ~57 pools with their derived curation status), one pool's schedule by canonical id,
    and the Zürich calendar — all joinable on `pool.id`. However sourced (the SQLite gold store
    today), `/swim` and `/pools` share this single read surface."""

    def facilities(self) -> tuple[Facility, ...]: ...

    def calendar(self) -> ZurichCalendar: ...

    def roster(self) -> tuple[RosterEntry, ...]: ...

    def facility(self, facility_id: str) -> Facility | None: ...
