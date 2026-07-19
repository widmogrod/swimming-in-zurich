"""A `SwimData` adapter backed by the SQLite gold store.

Both facilities and the Zürich calendar come from one gold store (built by `swimzh build`):
facilities via `GoldRepository.load_all`, the calendar via `load_calendar`. Nothing is read
from the curated `data/` tree at runtime — the gold DB is the single source of truth.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.models import Facility
from swimzh.storage.sqlite_repo import GoldRepository, load_calendar, open_db


class GoldSwimData:
    def __init__(self, facilities: tuple[Facility, ...], calendar: ZurichCalendar) -> None:
        self._facilities = facilities
        self._calendar = calendar

    @staticmethod
    def open(gold_db: Path) -> GoldSwimData:
        conn = open_db(gold_db)
        facilities = GoldRepository(conn).load_all()
        if not facilities:
            raise RuntimeError(
                f"gold store {gold_db} is empty; build it first (run `swimzh build`)"
            )
        calendar = load_calendar(conn)
        return GoldSwimData(facilities, calendar)

    def facilities(self) -> tuple[Facility, ...]:
        return self._facilities

    def calendar(self) -> ZurichCalendar:
        return self._calendar
