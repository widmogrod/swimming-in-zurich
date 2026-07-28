"""S1 fidelity spike (GO/NO-GO) regeneration test.

Builds ``PoolMeasurement``s for the 7 currently-curated pools by running the real providers
over committed fixtures (WFS ``infrastruktur`` prose from ``data/catalog.json``; saved pool
pages from ``tests/providers/fixtures/``), then asserts that both artifacts — the per-pool
schedule diff and the fact-class gap report — regenerate **byte-for-byte** from those fixtures.
The committed ``*.golden.md`` files are the artifacts the S1 human gate reads.

Only ``hallenbad-city`` currently has a saved page fixture; the other six curated pools have
none, so their schedule fidelity is honestly recorded as *not measured* rather than fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path

from swimzh.core.result import Ok
from swimzh.domain.models import Facility
from swimzh.etl.fidelity_report import (
    DiffClass,
    PoolMeasurement,
    Sourcing,
    build_gap_report,
    diff_schedule,
    measure_pool,
    render_gap_report,
    render_schedule_diff,
)
from swimzh.providers.curated import load_dataset

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA = _REPO_ROOT / "data"
_PAGE_FIXTURES = _REPO_ROOT / "tests" / "providers" / "fixtures"
_GOLDEN = Path(__file__).resolve().parent / "fidelity"

# The 7 currently-curated pools -> their saved page fixture (None = no fixture committed yet).
_PAGE_FIXTURE_BY_POOL: dict[str, str | None] = {
    "schulschwimmanlage-aemtler": None,
    "hallenbad-blaesi": None,
    "hallenbad-bungertwies": None,
    "hallenbad-city": "hallenbad_city.html",
    "waermebad-kaeferberg": None,
    "hallenbad-leimbach": None,
    "hallenbad-oerlikon": None,
}


def _wfs_prose() -> dict[str, str]:
    entries = json.loads((_DATA / "catalog.json").read_text(encoding="utf-8"))["entries"]
    return {e["pool_id"]: e["description"] for e in entries if e.get("description") is not None}


def _curated_by_id() -> dict[str, Facility]:
    dataset = load_dataset(_DATA)
    assert isinstance(dataset, Ok), dataset
    return {f.identity.facility_id: f for f in dataset.value.facilities}


def _build_measurements() -> tuple[PoolMeasurement, ...]:
    prose = _wfs_prose()
    curated = _curated_by_id()
    out: list[PoolMeasurement] = []
    for pool_id, page_name in _PAGE_FIXTURE_BY_POOL.items():
        page_html = (
            (_PAGE_FIXTURES / page_name).read_text(encoding="utf-8")
            if page_name is not None
            else None
        )
        out.append(
            measure_pool(
                pool_id=pool_id,
                curated=curated[pool_id],
                wfs_prose=prose.get(pool_id),
                page_html=page_html,
            )
        )
    return tuple(out)


def _render_diff(measurements: tuple[PoolMeasurement, ...]) -> str:
    return render_schedule_diff(tuple(diff_schedule(m) for m in measurements))


def _render_gap(measurements: tuple[PoolMeasurement, ...]) -> str:
    return render_gap_report(build_gap_report(measurements))


# --- regeneration / determinism ----------------------------------------------------------


def test_schedule_diff_regenerates_from_fixtures() -> None:
    expected = (_GOLDEN / "schedule_diff.golden.md").read_text(encoding="utf-8")
    assert _render_diff(_build_measurements()) == expected


def test_gap_report_regenerates_from_fixtures() -> None:
    expected = (_GOLDEN / "gap_report.golden.md").read_text(encoding="utf-8")
    assert _render_gap(_build_measurements()) == expected


def test_both_artifacts_are_deterministic() -> None:
    # Independent builds must produce identical bytes — no set-ordering / dict-ordering leak.
    assert _render_diff(_build_measurements()) == _render_diff(_build_measurements())
    assert _render_gap(_build_measurements()) == _render_gap(_build_measurements())


# --- the findings the human gate depends on ----------------------------------------------


def test_city_is_the_only_measured_pool_the_rest_are_fixture_gaps() -> None:
    measured = {m.pool_id for m in _build_measurements() if m.source_rules is not None}
    assert measured == {"hallenbad-city"}


def test_city_schedule_has_zero_overlap_with_illustrative_curated_data() -> None:
    # The real city page and the illustrative curated YAML share NO facility-level rule: every
    # entry is source-poorer or source-richer, none matched. This is the core GO/NO-GO signal.
    diff = next(diff_schedule(m) for m in _build_measurements() if m.pool_id == "hallenbad-city")
    assert diff.source_available
    assert diff.count(DiffClass.MATCHED) == 0
    assert diff.count(DiffClass.SOURCE_POORER) > 0
    assert diff.count(DiffClass.SOURCE_RICHER) > 0


def test_missing_fixture_pool_is_recorded_not_fabricated() -> None:
    measurements = _build_measurements()
    diff = next(diff_schedule(m) for m in measurements if m.pool_id == "hallenbad-oerlikon")
    assert not diff.source_available
    assert diff.entries == ()
    assert diff.curated_rule_count > 0  # curated rules exist; they are simply not verifiable


def _gap_by_class() -> dict[str, Sourcing]:
    report = build_gap_report(_build_measurements())
    return {e.fact_class: e.sourcing for e in report.entries}


def test_infrastruktur_sources_kind_dimensions_lanes() -> None:
    gaps = _gap_by_class()
    assert gaps["basin.kind"] is Sourcing.SOURCED_BY_INFRASTRUKTUR
    assert gaps["basin.dimensions"] is Sourcing.SOURCED_BY_INFRASTRUKTUR
    assert gaps["basin.lanes"] is Sourcing.SOURCED_BY_INFRASTRUKTUR


def test_closures_are_sourced_by_the_notice_scraper() -> None:
    assert _gap_by_class()["facility.closures"] is Sourcing.SOURCED_BY_SCHEDULE


def test_residue_classes_are_not_in_source() -> None:
    gaps = _gap_by_class()
    for residue in (
        "access.lane_swim",
        "access.family",
        "access.adults_only",
        "basin.schedule-split",
        "facility.prices (admission)",
        "facility.public_holiday_policy",
        "schedule.scope (school_term/school_holiday)",
    ):
        assert gaps[residue] is Sourcing.NOT_IN_SOURCE, residue


def test_amenities_are_derivable_with_a_rule() -> None:
    assert _gap_by_class()["facility.amenities"] is Sourcing.DERIVABLE_WITH_RULE


def test_unparseable_page_is_a_source_error_not_a_missing_fixture() -> None:
    # A page that exists but yields no timetable is a *parse failure* (source_error set),
    # distinct from source_rules is None meaning "no fixture committed" — the diff still marks
    # it unavailable, but the cause is recorded for the human gate.
    city = _curated_by_id()["hallenbad-city"]
    measurement = measure_pool(
        pool_id="hallenbad-city",
        curated=city,
        wfs_prose=None,
        page_html="<html><body>no timetable here</body></html>",
    )
    assert measurement.source_rules is None
    assert measurement.source_error is not None
    assert not diff_schedule(measurement).source_available
