"""The swim endpoint over the SCRAPED pipeline — the eligibility differentiator must survive the
whole HTTP round-trip. Since delete-curated-schedule-tier S3 the served City schedule is the
scraped one (a flat `Hauptbecken` timetable): a women-only session runs Thursday 18:00–22:00 (and
Tuesday morning), so the eligibility round-trip is asserted at a Thursday evening."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from apps.web.main import app

# Monday 2026-09-14 20:30: the scraped City schedule is open (public), a generic "some option" time.
MONDAY_EVENING = "2026-09-14T20:30"
# Thursday 2026-09-17 18:30: the scraped City schedule runs a women-only session 18:00–22:00.
THURSDAY_EVENING = "2026-09-17T18:30"


def test_woman_sees_women_only_session() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/swim", params={"at": THURSDAY_EVENING, "gender": "female", "age": 34}
        )
    assert response.status_code == 200
    accesses = {o["access"] for o in response.json()["options"]}
    assert "WomenOnly" in accesses


def test_man_excluded_from_women_only_session() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": THURSDAY_EVENING, "gender": "male", "age": 34})
    assert response.status_code == 200
    accesses = {o["access"] for o in response.json()["options"]}
    assert "WomenOnly" not in accesses


def test_options_carry_price_and_provenance() -> None:
    # The scraped City schedule serves options that carry the scraped admission price and a
    # provenance `source`. (`valid_as_of` is `None` for a scraped schedule composed onto a
    # source-less curated blob — the recorded S2 honest-provenance debt — so it is not required.)
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    options = response.json()["options"]
    assert options
    assert any(o["price"] for o in options)
    assert all(o["source"] for o in options)


def test_options_expose_length_kind_and_source() -> None:
    """S1: the glance badge needs basin length + facility kind, and the ⓘ stamp needs the
    provenance source/curated flag, surfaced through the swim service into OptionOut."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    options = response.json()["options"]
    assert options
    for o in options:
        assert set(o) >= {"length_m", "kind", "source", "curated"}
        assert isinstance(o["kind"], str) and o["kind"]
        assert isinstance(o["source"], str) and o["source"]
        assert isinstance(o["curated"], bool)
        assert o["length_m"] is None or isinstance(o["length_m"], (int, float))
    # The scraped schedule is a flat basin with no physicals, so `length_m` degrades to None on the
    # option (the real per-basin dimensions surface on `/pools`, not on a scraped `/swim` option).


def test_options_expose_lane_count_and_degrade_when_unknown() -> None:
    """S2: the badge's "N lane" sub-line needs a per-basin lane count on OptionOut. The scraped
    schedule's flat basin carries no lane count, so `lanes` must degrade to None (present as a key)
    rather than being invented — the real per-basin lane count surfaces on `/pools`, not here.

    Narrowed by lane-stack-board S1: City now serves a SECOND option, from the carried
    `Schwimmerbecken` lane basin, whose 6 lanes are real WFS-sourced physicals. The rule this test
    pins is unchanged — the flat scraped `Hauptbecken` still invents nothing — so it is asserted per
    basin instead of per facility.
    """
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "female", "age": 34})
    options = response.json()["options"]
    assert options
    for o in options:
        assert "lanes" in o
        assert o["lanes"] is None or isinstance(o["lanes"], int)
    city = [o for o in options if o["facility"] == "Hallenbad City"]
    # The flat scraped basin degrades its lane count to None, never an invented number.
    assert {o["lanes"] for o in city if o["basin"] == "Hauptbecken"} == {None}
    # The carried lane basin reports its real, sourced count.
    assert {o["lanes"] for o in city if o["basin"] == "Schwimmerbecken"} == {6}


def test_invalid_gender_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "gender": "other"})
    assert response.status_code == 400


def test_missing_at_defaults_to_server_time() -> None:
    # `at` is optional: a bare /swim answers using server time (Europe/Zurich) instead of
    # 422-ing. The answer shape is the same as an explicit `at`.
    with TestClient(app) as client:
        response = client.get("/swim")
    assert response.status_code == 200
    body = response.json()
    assert {"options", "statuses", "warnings", "notices"} <= set(body)


def test_lat_without_lon_is_400() -> None:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "lat": 47.37})
    assert response.status_code == 400


def test_future_year_surfaces_calendar_warning() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/swim", params={"at": "2030-03-12T18:00", "gender": "male", "age": 40}
        )
    assert response.status_code == 200
    assert any("calendar data not available" in w for w in response.json()["warnings"])


# --- S2: machine-readable codes on the wire (additive; prose stays until S5) --------------


def _women_only_option(client: TestClient, gender: str) -> dict[str, object]:
    """The City women-only session as seen by `gender`, with eligibility annotated."""
    response = client.get(
        "/swim",
        params={"at": THURSDAY_EVENING, "gender": gender, "age": 34, "eligible_only": "false"},
    )
    assert response.status_code == 200
    options: list[dict[str, object]] = response.json()["options"]
    women = [o for o in options if o["access"] == "WomenOnly"]
    assert women, f"no WomenOnly option for gender={gender}"
    return women[0]


def test_options_carry_a_reason_code_and_no_prose() -> None:
    """S5: the English `reason` is GONE from the wire.

    The server states WHICH outcome; only the client turns that into words, so one API
    serves every locale and no response is implicitly English.
    """
    with TestClient(app) as client:
        option = _women_only_option(client, "female")
    assert option["reason_code"] == "women_only_welcome"
    assert "reason" not in option


def test_the_reason_code_discriminates_what_rule_could_not() -> None:
    """The whole point of S2: female and male see the SAME access type and the same
    `rule`, but opposite outcomes. A client keying on the access type alone would render
    "you're welcome" to someone who is excluded."""
    with TestClient(app) as client:
        welcome = _women_only_option(client, "female")
        excluded = _women_only_option(client, "male")
    assert welcome["access"] == excluded["access"] == "WomenOnly"
    assert welcome["reason_code"] == "women_only_welcome"
    assert excluded["reason_code"] == "women_only_excluded"
    assert welcome["eligible"] is True
    assert excluded["eligible"] is False


def test_reason_params_carry_interpolation_values_not_baked_prose() -> None:
    """Any code whose sentence mentions a number/name must ship that value separately, or
    a translation cannot place it. Params are always present (possibly empty)."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "eligible_only": "false"})
    for option in response.json()["options"]:
        assert isinstance(option["reason_params"], dict)
        if option["reason_code"].startswith(("seniors_only", "adults_only")):
            assert "min_age" in option["reason_params"]


def test_statuses_carry_codes_and_no_mixed_language_prose() -> None:
    """`detail` used to be English in one branch and curated German in the other — the
    seam the whole plan existed to close. It is gone; the codes replace it."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": MONDAY_EVENING, "eligible_only": "false"})
    statuses = response.json()["statuses"]
    assert statuses, "expected at least one closed / schedule-less facility"
    for status in statuses:
        # `open_unscheduled` joined the closed set when sharedsource-fanout S3 wrote the first
        # `operating_season` blobs (mid-September is inside the Planschbecken Mai–Sep window).
        assert status["detail_code"] in {
            "closed_reason",
            "awaiting_scrape",
            "no_source",
            "open_unscheduled",
        }
        assert "detail" not in status, "the mixed-language prose is retired (S5)"
        if status["detail_code"] == "closed_reason":
            # S4: WHICH closure, as a code the client can translate.
            assert status["closure_code"]


def test_access_types_key_is_sufficient_to_render_without_server_prose() -> None:
    """S2 asserts `/access-types` needs no new field: `key` already identifies each type,
    so the client can render label+description from its own catalog. The prose here is
    what S5 removes."""
    with TestClient(app) as client:
        types = client.get("/access-types").json()["types"]
    keys = [t["key"] for t in types]
    assert len(keys) == len(set(keys)), "keys must be unique to be a message id"
    assert set(keys) == {
        "public",
        "lane-swim",
        "family",
        "women-only",
        "seniors-only",
        "school-reserved",
        "club-reserved",
        "adults-only",
        # The school-pool vocabulary: sessions the timetable publishes but the domain could
        # not express, so the client must be able to render them from its own catalog too.
        "girls-only",
        "gender-diverse",
        "accompanied-children",
    }


# Wednesday 2026-07-15 15:00 — inside Heuried's published `30. Mai–16. August` window, and
# inside its FAIR-WEATHER-only afternoon block. The city publishes 09:00–14:00 under
# "Öffnungszeiten bei jedem Wetter" and 14:00–21:00 under "bei schönem Wetter".
JULY_AFTERNOON = "2026-07-15T15:00"


def test_heuried_returns_both_blocks_and_marks_only_the_conditional_one() -> None:
    """seasonal-hours S4: a fair-weather session is REAL but conditional, and the
    guaranteed one alongside it must stay unqualified.

    Weather rides on the SESSION, never the day: rendering the whole pool as
    weather-dependent would launder the certainly-open morning into an unknown, and
    dropping the marker would present 14:00–21:00 as a promise the city never made."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": JULY_AFTERNOON, "eligible_only": "false"})
    assert response.status_code == 200
    heuried = [o for o in response.json()["options"] if o["facility"] == "Freibad Heuried"]
    blocks = {(o["start"], o["end"]): o["weather"] for o in heuried}
    assert blocks == {("09:00", "14:00"): "any", ("14:00", "21:00"): "fair_only"}


# Thursday 2026-08-13 10:00 — inside Heuried's season and inside its any-weather morning block,
# and inside Oberer Letten's published summer hours. One instant, two pools, opposite prices.
AUGUST_MORNING = "2026-08-13T10:00"


def _options_for(facility_id: str, at: str, age: int) -> list[dict[str, object]]:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": at, "age": age, "eligible_only": "false"})
    assert response.status_code == 200, response.text
    return [o for o in response.json()["options"] if o["facility_id"] == facility_id]


def test_an_outdoor_pool_that_links_the_tariff_now_carries_the_city_price() -> None:
    """The fan-out gated on the literal host `stadt-zuerich.ch`, so the 15 pools the city
    publishes on sportamt.ch — Heuried among them — served no price at all. It links the tariff
    page, so it is served the general rate the city prints."""
    options = _options_for("freibad-heuried", AUGUST_MORNING, age=30)
    assert options, "Freibad Heuried has no option at its own August morning"
    assert all(str(o["price"]).startswith("Erwachsene (ab 20 J.) Fr. 8.00") for o in options)


def test_a_pool_the_city_publishes_as_free_is_never_assigned_a_rate() -> None:
    """*"Der Eintritt ins Flussbad Oberer Letten ist gratis."* Its page links no tariff, so it
    carries none — the invariant a host-keyed widening would have broken at four pools. Under
    the admission union the store now records it as `Free`, and the `/swim` option still carries
    `price: null` (rendering free-ness is UI, deferred) — the RESPONSE is unchanged; only the
    stored data stopped conflating free with unknown."""
    options = _options_for("flussbad-oberer-letten", AUGUST_MORNING, age=30)
    assert options, "Flussbad Oberer Letten has no option at its own August morning"
    assert all(o["price"] is None for o in options)


def test_an_unknown_admission_pool_still_serves_its_option_with_no_price() -> None:
    """Regression pin for the union's third arm: `hallenbad-altstetten` (a private operator whose
    page states neither tariff nor gratis) is `Unknown` — its `/swim` response is byte-identical
    to the pre-union one: the option is served, `price` stays null. A September instant, because
    its operator page announces a Revision closure over `AUGUST_MORNING` (Jul 30 – Aug 16)."""
    options = _options_for("hallenbad-altstetten", "2026-09-15T10:00", age=30)
    assert options, "Hallenbad Altstetten has no option on a Tuesday morning"
    assert all(o["price"] is None for o in options)


def test_every_option_carries_a_weather_value_from_the_closed_set() -> None:
    """The field is required on the wire (no `None`, no missing key): a client that has to
    guess whether a session is conditional will guess "guaranteed"."""
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": JULY_AFTERNOON, "eligible_only": "false"})
    options = response.json()["options"]
    assert options
    assert {o["weather"] for o in options} <= {"any", "fair_only"}
    # An INDOOR pool has no weather condition at all — the marker must not spread.
    indoor = [o for o in options if o["kind"] == "indoor"]
    assert indoor
    assert all(o["weather"] == "any" for o in indoor)


def test_the_season_gate_covers_exactly_the_thirteen_planschbecken(gold_db: Path) -> None:
    """sharedsource-fanout S3, replacing the S1 inertness pin (whose `seasoned == 0` premise
    died at this slice's rebuild): exactly 13 blobs carry `operating_season` — the 13
    Planschbecken the one shared page states it for — and all 13 are stored free."""
    with sqlite3.connect(gold_db) as conn:
        seasoned = {
            row[0]
            for row in conn.execute(
                "select id from pool"
                " where json_extract(facility_doc,'$.operating_season') is not null"
            )
        }
        free = {
            row[0]
            for row in conn.execute(
                "select id from pool where json_extract(facility_doc,'$.admission_state') = 'free'"
            )
        }
    assert len(seasoned) == 13, sorted(seasoned)
    assert all(pool_id.startswith("planschbecken-") for pool_id in seasoned)
    assert seasoned <= free


def _planschbecken_statuses(at: str) -> list[dict[str, object]]:
    with TestClient(app) as client:
        response = client.get("/swim", params={"at": at, "eligible_only": "false"})
    assert response.status_code == 200
    return [
        s for s in response.json()["statuses"] if str(s["facility"]).startswith("Planschbecken")
    ]


def test_a_planschbecken_is_open_unscheduled_in_july_with_the_pinned_params() -> None:
    """In season `/swim` serves the honest fourth state: `open_unscheduled`, carrying the season
    + weather under the EXACT param keys S1 pinned for this slice's acceptance —
    {"weather", "season_start_month", "season_end_month", "season_precision"}; day keys ride
    only at DAY precision, and the page states months, so none here. Each pool appears exactly
    once in `statuses` — never also as a `no_source` ghost."""
    statuses = _planschbecken_statuses("2026-07-15T14:00:00+02:00")
    assert len(statuses) == 13
    assert len({s["facility"] for s in statuses}) == 13  # once each — replaced, never doubled
    for status in statuses:
        assert status["status"] == "open_unscheduled"
        params = status["detail_params"]
        assert isinstance(params, dict)
        assert set(params) == {
            "weather",
            "season_start_month",
            "season_end_month",
            "season_precision",
        }
        assert params["weather"] == "fair_only"
        assert (params["season_start_month"], params["season_end_month"]) == ("5", "9")
        assert params["season_precision"] == "month"


def test_a_planschbecken_is_out_of_season_in_january() -> None:
    """Out of season the same pool serves the SAME closed pair a seasonal scraped pool (Heuried
    in January) already serves — `"closed"` + `closure_code: "out_of_season"` — no new closed
    shape on the wire. (The "never rendered closed" invariant protects pools whose schedule is
    UNKNOWN; a pool whose own page states its season is knowably shut outside it.)"""
    statuses = _planschbecken_statuses("2026-01-15T14:00")
    assert len(statuses) == 13
    assert len({s["facility"] for s in statuses}) == 13  # exactly once each, in January too
    for status in statuses:
        assert status["status"] == "closed"
        assert status["closure_code"] == "out_of_season"
