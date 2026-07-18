"""A `SwimData` adapter backed by the curated dataset.

Loads facilities + calendar once at startup (fail-fast if the data is unreadable). This is
the offline, no-network source of truth; swapping to the SQLite gold store later means
adding a second adapter that satisfies the same `SwimData` port.
"""

from __future__ import annotations

from pathlib import Path

from swimzh.core.errors import describe
from swimzh.core.result import Err, Ok
from swimzh.domain.calendar import ZurichCalendar
from swimzh.domain.models import Facility
from swimzh.providers.curated import Dataset, load_dataset


class CuratedSwimData:
    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset

    @staticmethod
    def load(data_dir: Path) -> CuratedSwimData:
        match load_dataset(data_dir):
            case Ok(dataset):
                return CuratedSwimData(dataset)
            case Err(error):
                raise RuntimeError(f"failed to load swim data from {data_dir}: {describe(error)}")

    def facilities(self) -> tuple[Facility, ...]:
        return self._dataset.facilities

    def calendar(self) -> ZurichCalendar:
        return self._dataset.calendar
