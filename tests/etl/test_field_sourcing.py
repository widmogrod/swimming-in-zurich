"""S5a acceptance (scoped to the audit): the field→producer table covers EXACTLY the serialized
``facility_doc`` fields — no field unlisted, no stale entry.

``facility_doc`` == ``storage.codec.dumps(f)`` == ``StoredFacilityDTO.model_dump_json()``. The two
roots whose fields carry independently-sourced facts are ``StoredFacilityDTO`` (facility level) and
the nested ``BasinDTO`` (basin level). Introspecting their pydantic ``model_fields`` and comparing
to the table's field set makes the coverage claim mechanical: adding a field to either DTO breaks
this test until it is classified, and deleting one breaks it until the stale entry is removed.
"""

from __future__ import annotations

from swimzh.boundary.curated_dto import BasinDTO
from swimzh.etl.field_sourcing import (
    FACILITY_FIELD_SOURCING,
    ProducerKind,
    classified_fields,
)
from swimzh.storage.codec import StoredFacilityDTO


def _serialized_field_names() -> frozenset[str]:
    """The qualified names of every serialized ``facility_doc`` field, from the DTOs themselves."""
    facility = {f"facility.{name}" for name in StoredFacilityDTO.model_fields}
    basin = {f"basin.{name}" for name in BasinDTO.model_fields}
    return frozenset(facility | basin)


def test_table_covers_exactly_the_serialized_facility_doc_fields() -> None:
    expected = _serialized_field_names()
    actual = classified_fields()

    missing = expected - actual  # a serialized field with no classification
    stale = actual - expected  # a classification for a field that is not serialized
    assert not missing, f"unclassified serialized facility_doc fields: {sorted(missing)}"
    assert not stale, f"table classifies non-serialized fields: {sorted(stale)}"
    assert actual == expected


def test_every_entry_is_internally_consistent() -> None:
    """A SOURCED field names its producing module; every other kind names none — so a row can never
    claim 'sourced' without pointing at the module, nor carry a stray module while unsourced."""
    for entry in FACILITY_FIELD_SOURCING:
        if entry.producer is ProducerKind.SOURCED:
            assert entry.module, f"{entry.field}: SOURCED but no producing module named"
        else:
            assert entry.module is None, (
                f"{entry.field}: {entry.producer.value} must not name a module"
            )
        assert entry.coverage, f"{entry.field}: coverage note is empty"
        assert entry.note, f"{entry.field}: evidence note is empty"


def test_field_names_are_unique() -> None:
    fields = [entry.field for entry in FACILITY_FIELD_SOURCING]
    assert len(fields) == len(set(fields)), "duplicate field entries in the sourcing table"


def test_residue_and_crosswalk_are_recorded() -> None:
    """Guard the audit's key conclusions so a later edit can't silently reclassify them: the
    irreducible crosswalk facts stay crosswalk, and the known not-in-source residue stays a
    drop-candidate."""
    by_field = {entry.field: entry for entry in FACILITY_FIELD_SOURCING}

    for crosswalk_field in (
        "facility.crowdmonitor_keys",
        "facility.baditicker_poiid",
        "facility.aliases",
        "basin.lane_plan_source",
    ):
        assert by_field[crosswalk_field].producer is ProducerKind.CURATED_CROSSWALK

    # S5b: `geo_sport_id` LEFT the crosswalk — it is now SOURCED from the WFS `poi_id` by the
    # roster/spine build, so it must name the roster as its producer (guard against a regression
    # that folds it back into the crosswalk).
    geo_sport = by_field["facility.geo_sport_id"]
    assert geo_sport.producer is ProducerKind.SOURCED
    assert geo_sport.module == "etl.roster"

    for drop_field in ("basin.exceptions", "basin.measured_temp_c"):
        assert by_field[drop_field].producer is ProducerKind.DROP_CANDIDATE

    # `lockers` LEFT the unbuilt bucket in mietobjekt-extraction S1: `parse_mietobjekte`
    # reads the pool pages' `Mietobjekt|Preis` table and the scrape fills the compose slot,
    # so it is SOURCED and names its provider (guard against a regression that files real,
    # produced data back under residue).
    lockers = by_field["facility.lockers"]
    assert lockers.producer is ProducerKind.SOURCED
    assert lockers.module == "providers.mietobjekt"

    # `rentals` is BORN sourced in S2 — the non-locker half of the same table, from the same
    # provider (never a residue bucket: the rows were on the page all along).
    rentals = by_field["facility.rentals"]
    assert rentals.producer is ProducerKind.SOURCED
    assert rentals.module == "providers.mietobjekt"

    # Sourced since 2026-08-04 from the timetable's "(und Feiertage)" Sunday row.
    assert by_field["facility.public_holiday_policy"].producer is ProducerKind.SOURCED

    # `last_admission_before` LEFT the unbuilt bucket in seasonal-hours S3: the scraper reads the
    # sentence and `compose` folds it onto the facility, so it is SOURCED and names its provider.
    last_admission = by_field["facility.last_admission_before"]
    assert last_admission.producer is ProducerKind.SOURCED
    assert last_admission.module == "providers.schedule_scraper"

    # The already-sourced claims S5a exists to ground-truth.
    assert by_field["facility.prices"].module == "providers.price_scraper"
    assert by_field["facility.closures"].module == "providers.schedule_scraper"
    assert by_field["basin.lane_plan"].module == "providers.belegungsplan"
