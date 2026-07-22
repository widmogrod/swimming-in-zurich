"""The shared curation rule: `codec.is_curated` derives curated/uncurated from the schedule
blob, never a stored column.

Curated iff the blob is present (NOT NULL) AND the decoded facility has at least one basin
carrying at least one rule. A NULL blob and a blob whose basins carry no rules both derive
uncurated — the two edge cases B3's read-path derivation must honor.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from swimzh.core.result import Ok
from swimzh.domain.models import Facility
from swimzh.providers.curated import load_dataset
from swimzh.storage import codec

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def curated_facility() -> Facility:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    facility = next(f for f in result.value.facilities if any(b.rules for b in f.basins))
    return facility


def test_null_blob_is_uncurated() -> None:
    assert codec.is_curated(None) is False


def test_blob_with_a_ruled_basin_is_curated(curated_facility: Facility) -> None:
    assert codec.is_curated(codec.dumps(curated_facility)) is True


def test_blob_without_any_basin_is_uncurated(curated_facility: Facility) -> None:
    stripped = replace(curated_facility, basins=())
    assert codec.is_curated(codec.dumps(stripped)) is False


def test_blob_whose_basins_carry_no_rules_is_uncurated(curated_facility: Facility) -> None:
    ruleless = replace(
        curated_facility,
        basins=tuple(replace(b, rules=()) for b in curated_facility.basins),
    )
    assert codec.is_curated(codec.dumps(ruleless)) is False
