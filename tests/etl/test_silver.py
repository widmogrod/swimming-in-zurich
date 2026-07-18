"""Silver reconciliation: canonical-id lookup with loud failure on unmatched names."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.errors import SchemaMismatch
from swimzh.core.result import Err, Ok
from swimzh.domain.geo import GeoPoint
from swimzh.domain.models import FacilityId
from swimzh.etl.silver import reconcile
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.providers.geo_sport import GeoPool

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FETCHED_AT = datetime(2026, 7, 18, 9, 0, tzinfo=ZoneInfo("Europe/Zurich"))


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def _pool(source_id: str, name: str, lat: float, lon: float) -> GeoPool:
    return GeoPool(
        source_id=source_id,
        poi_id=None,
        name=name,
        address="",
        geo=GeoPoint(lat=lat, lon=lon),
        url=None,
        category=None,
    )


def test_reconcile_merges_geo_and_stamps_provenance(dataset: Dataset) -> None:
    pools = [
        _pool("poi_hallenbad_view.2", "Hallenbad City", 47.3723, 8.5330),
        _pool("poi_hallenbad_view.5", "Hallenbad Oerlikon", 47.4104, 8.5567),
    ]
    result = reconcile(dataset, pools, FETCHED_AT)
    assert isinstance(result, Ok), result

    by_id = {f.identity.facility_id: f for f in result.value}
    city = by_id[FacilityId("city")]
    assert city.geo == GeoPoint(lat=47.3723, lon=8.5330)
    assert city.identity.geo_sport_id == "poi_hallenbad_view.2"
    assert city.provenance.fetched_at == FETCHED_AT

    # A curated facility without a matching geo pool still gets its provenance stamped.
    bungertwies = by_id[FacilityId("bungertwies")]
    assert bungertwies.provenance.fetched_at == FETCHED_AT


def test_unresolved_pool_name_is_loud_failure(dataset: Dataset) -> None:
    pools = [
        _pool("poi_hallenbad_view.2", "Hallenbad City", 47.3723, 8.5330),
        _pool("poi_hallenbad_view.99", "Hallenbad Nonexistent", 47.0, 8.0),
    ]
    result = reconcile(dataset, pools, FETCHED_AT)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)
    assert "Hallenbad Nonexistent" in result.error.detail
