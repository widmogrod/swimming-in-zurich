"""A `SwimData` adapter backed by the SQLite gold store.

Facilities come from the gold `GoldRepository`; the Zürich calendar (not a per-facility
thing) is loaded from the curated data dir. Same `SwimData` port as `CuratedSwimData`, so
`main.py` can pick either with no change to endpoints or services.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.core.errors import describe
from swimzh.core.result import Err, Ok
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.models import Facility
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import GoldRepository, open_db


class GoldSwimData:
    def __init__(self, facilities: tuple[Facility, ...], calendar: ZurichCalendar) -> None:
        self._facilities = facilities
        self._calendar = calendar

    @staticmethod
    def open(gold_db: Path, data_dir: Path) -> GoldSwimData:
        match load_dataset(data_dir):
            case Ok(dataset):
                calendar = dataset.calendar
            case Err(error):
                raise RuntimeError(f"failed to load calendar from {data_dir}: {describe(error)}")

        facilities = GoldRepository(open_db(gold_db)).load_all()
        if not facilities:
            raise RuntimeError(f"gold store {gold_db} is empty; build it first (swimzh build-gold)")
        return GoldSwimData(facilities, calendar)

    def facilities(self) -> tuple[Facility, ...]:
        return self._facilities

    def calendar(self) -> ZurichCalendar:
        return self._calendar
