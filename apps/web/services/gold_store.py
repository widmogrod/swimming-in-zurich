"""A `SwimStore` adapter backed by the SQLite gold store.

Every read the app needs comes from one gold store (built by `swimzh build`): curated
facilities via `GoldRepository.load_all`, the full pool roster via `load_roster`, and the
Zürich calendar via `load_calendar`. `/swim` and `/pools` join on the canonical `pool.id`.
Nothing is read from the curated `data/` tree at runtime — the gold DB is the single source
of truth.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.catalog import RosterEntry
from swimzh.domain.models import Facility
from swimzh.storage.sqlite_repo import GoldRepository, load_calendar, load_roster, open_db


class GoldSwimStore:
    def __init__(
        self,
        facilities: tuple[Facility, ...],
        roster: tuple[RosterEntry, ...],
        calendar: ZurichCalendar,
    ) -> None:
        self._facilities = facilities
        self._roster = roster
        self._calendar = calendar
        # Index curated facilities by canonical id so `/pools/{id}` resolves a catalog pool to
        # its schedule with a lookup, not a scan.
        self._by_id = {str(f.identity.facility_id): f for f in facilities}

    @staticmethod
    def open(gold_db: Path) -> GoldSwimStore:
        conn = open_db(gold_db)
        facilities = GoldRepository(conn).load_all()
        if not facilities:
            raise RuntimeError(
                f"gold store {gold_db} is empty; build it first (run `swimzh build`)"
            )
        roster = load_roster(conn)
        calendar = load_calendar(conn)
        return GoldSwimStore(facilities, roster, calendar)

    def facilities(self) -> tuple[Facility, ...]:
        return self._facilities

    def calendar(self) -> ZurichCalendar:
        return self._calendar

    def roster(self) -> tuple[RosterEntry, ...]:
        return self._roster

    def facility(self, facility_id: str) -> Facility | None:
        return self._by_id.get(facility_id)
