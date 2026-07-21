"""The `infrastruktur` prose parser: partial by design. It extracts what the free text
reveals (kind, fractional dimensions as Decimal, lanes, nominal temp), leaves missing
facts `None`, skips non-basin segments (sauna), and marks enriched basins PARSED_PROSE."""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from swimzh.domain.access import PublicSwim
from swimzh.domain.models import (
    Basin,
    BasinId,
    BasinKind,
    BasinSource,
    Dimensions,
    FeatureKind,
)
from swimzh.domain.schedule import ScheduleRule, TimeRange, Weekday
from swimzh.providers.infrastruktur import (
    apply_physicals,
    basin_from_physical,
    parse_features,
    parse_infrastruktur,
)

# The real sample from the plan (Hallenbad-style WFS prose).
SAMPLE = (
    "Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C, "
    "Nichtschwimmerbecken 10,5 x 7 m 30°C, "
    "Variobecken … 30°C, "
    "gemischte Sauna 8-22 Uhr Eintritt Fr. 10.-"
)


def test_sample_prose_yields_expected_partial_basins() -> None:
    swimmer, non_swimmer, vario = parse_infrastruktur(SAMPLE)

    assert swimmer.name == "Schwimmerbecken"
    assert swimmer.kind is BasinKind.LAP
    assert swimmer.dimensions == Dimensions(length_m=Decimal("50"), width_m=Decimal("15"))
    assert swimmer.lanes == 6
    assert swimmer.nominal_temp_c == Decimal("28")

    # German decimal comma "10,5" must survive as a fractional Decimal, not split segments.
    assert non_swimmer.name == "Nichtschwimmerbecken"
    assert non_swimmer.kind is BasinKind.NON_SWIMMER
    assert non_swimmer.dimensions == Dimensions(length_m=Decimal("10.5"), width_m=Decimal("7"))
    assert non_swimmer.lanes is None
    assert non_swimmer.nominal_temp_c == Decimal("30")

    # Partial by nature: the prose says nothing about the Vario basin's size or lanes.
    assert vario.name == "Variobecken"
    assert vario.kind is BasinKind.VARIO
    assert vario.dimensions is None
    assert vario.lanes is None
    assert vario.nominal_temp_c == Decimal("30")


def test_sauna_segment_is_not_a_basin() -> None:
    names = [p.name for p in parse_infrastruktur(SAMPLE)]
    assert not any("Sauna" in n for n in names)


def test_raw_segment_is_preserved_for_audit() -> None:
    swimmer = parse_infrastruktur(SAMPLE)[0]
    assert swimmer.raw == "Schwimmerbecken 50 x 15 m (6 Bahnen) 28°C"


def test_fractional_standalone_length_and_teaching_kind() -> None:
    (basin,) = parse_infrastruktur("Lehrschwimmbecken 16,66 m 29°C")
    assert basin.kind is BasinKind.TEACHING
    assert basin.dimensions == Dimensions(length_m=Decimal("16.66"))
    assert basin.nominal_temp_c == Decimal("29")


def test_unrecognised_becken_falls_back_to_other_kind() -> None:
    (basin,) = parse_infrastruktur("Solebecken 34°C")
    assert basin.kind is BasinKind.OTHER
    assert basin.nominal_temp_c == Decimal("34")
    assert basin.dimensions is None


def test_prose_without_basins_yields_nothing() -> None:
    assert parse_infrastruktur("Sauna, Dampfbad, Restaurant") == ()
    assert parse_infrastruktur("") == ()


def test_apply_physicals_marks_parsed_prose_and_keeps_schedule() -> None:
    rule = ScheduleRule(
        weekdays=frozenset({Weekday.MONDAY}),
        time=TimeRange(start=time(8, 0), end=time(20, 0)),
        access=PublicSwim(),
    )
    basin = Basin(basin_id=BasinId("city-50m"), name="50m-Becken", rules=(rule,))
    (parsed, *_rest) = parse_infrastruktur(SAMPLE)

    enriched = apply_physicals(basin, parsed)

    assert enriched.physical_source is BasinSource.PARSED_PROSE
    assert enriched.kind is BasinKind.LAP
    assert enriched.dimensions == Dimensions(length_m=Decimal("50"), width_m=Decimal("15"))
    assert enriched.lanes == 6
    assert enriched.nominal_temp_c == Decimal("28")
    # The schedule (and identity) must be untouched by enrichment.
    assert enriched.rules == basin.rules
    assert enriched.basin_id == basin.basin_id
    assert enriched.name == basin.name


def test_diving_platform_heights_parsed_and_not_read_as_a_dimension() -> None:
    (basin,) = parse_infrastruktur("Sprungbecken 1/3/5m")
    assert basin.kind is BasinKind.DIVING
    assert basin.diving_platforms_m == (Decimal("1"), Decimal("3"), Decimal("5"))
    # The "5m" of the slash-list must NOT be misread as a basin length.
    assert basin.dimensions is None


def test_basin_from_physical_is_schedule_less_and_parsed_prose() -> None:
    (parsed, *_rest) = parse_infrastruktur(SAMPLE)
    basin = basin_from_physical(parsed, BasinId("altstetten-prose-0"))
    # Decision #5 gate lives in the data: a prose basin carries NO rules, so it can never yield a
    # /swim session, while its physicals + PARSED_PROSE tag survive for the detail view.
    assert basin.rules == ()
    assert basin.physical_source is BasinSource.PARSED_PROSE
    assert basin.kind is BasinKind.LAP
    assert basin.lanes == 6
    assert basin.nominal_temp_c == Decimal("28")
    assert basin.basin_id == BasinId("altstetten-prose-0")


def test_parse_features_extracts_non_basin_amenities() -> None:
    prose = (
        "Nichtschwimmerbecken 30°C, Wärme-Innenbad mit Sprudelliegen, "
        "Rutschbahn 110m, Gartensauna, Dampfbad, Sonnenterrasse, Restaurant"
    )
    kinds = {f.kind for f in parse_features(prose)}
    # The basin segment is NOT a feature; the amenity segments each map to a FeatureKind.
    assert FeatureKind.HOT_TUB in kinds  # Sprudelliegen
    assert FeatureKind.SLIDE in kinds  # Rutschbahn
    assert FeatureKind.SAUNA in kinds  # Gartensauna
    assert FeatureKind.STEAM_BATH in kinds  # Dampfbad
    assert FeatureKind.TERRACE in kinds  # Sonnenterrasse
    assert FeatureKind.GASTRONOMY in kinds  # Restaurant


def test_parse_features_ignores_noise() -> None:
    assert parse_features("Nichtschwimmerbecken 30°C, Volleyballnetz, 3 Flosse") == ()
