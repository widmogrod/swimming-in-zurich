"""lane-stack-board S2: a `/swim` option carries the lane DAY VIEW, not just lane counts.

`lane_timeline` answers "how many lanes are public" — it cannot answer "which lane, and whose",
which is exactly what the board's lane stack paints. S2 puts the per-lane day view, the day's
best public window, and the basin's stable id on `OptionOut`.

A caveat this suite is deliberately built around: `tests/providers/wfs_snapshot.py:89-91` serves
the SAME `city-schwimmerbecken.pdf` for every `.pdf` URL, so in the built test store Bungertwies
and Käferberg carry byte-identical lane plans to City. No assertion here may claim that a given
club owns a given POOL's lane — that would read a shared fixture and prove nothing. Ownership is
therefore asserted structurally (an owner is present, non-empty, and paired with a reserved
access) for the City option alone.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from apps.web.main import app
from apps.web.services.gold_store import GoldSwimStore
from swimzh.domain.person import Gender, Person
from swimzh.domain.query import SwimQuery, find_swim_options

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# Wednesday — Hallenbad City's lane basin is open and its plan is rich (five distinct owners).
AT = "2026-08-12T12:00"
_AT_DT = datetime(2026, 8, 12, 12, 0, tzinfo=ZoneInfo("Europe/Zurich"))
# 2026-05-20: the date Hallenbad Oerlikon is open, so `oerlikon-sprungbecken` — the one basin
# that DECLARES a `lane_plan_source` but whose section matched no parsed header, so no plan
# attached — reaches `/swim` and can be asserted as the plan-less case.
AT_OERLIKON = "2026-05-20T12:00"
# Tuesday 2026-05-05: `leimbach-25m` serves TWO sessions (06:00–08:00 and 12:00–21:00) from one
# plan. Any derivation that is a property of the WEEKDAY rather than of the SESSION collapses
# them, so this date is the fence for anything attached per option.
AT_MULTI_SESSION = "2026-05-05T12:00"


def _options(at: str) -> list[dict[str, Any]]:
    """Every option the wire serves at `at` — `eligible_only=false`, and the same person the
    domain-side comparison uses, so the two option SETS are directly comparable."""
    with TestClient(app) as client:
        response = client.get(
            "/swim",
            params={"at": at, "gender": "female", "age": 34, "eligible_only": "false"},
        )
    assert response.status_code == 200
    options: list[dict[str, Any]] = response.json()["options"]
    assert options
    return options


def _city_lane_options(at: str = AT) -> list[dict[str, Any]]:
    lane = [o for o in _options(at) if o["basin_id"] == "city-50m"]
    assert lane, "Hallenbad City's lane basin produced no option"
    return lane


def test_the_city_lane_option_carries_a_six_lane_day_view_with_named_owners() -> None:
    """AC1: `lane_day_view` is on the wire with one strip per lane and real owner labels.

    The owner assertion is structural on purpose (see the module docstring): a reserved segment
    must NAME someone, because an unlabelled reserved block is indistinguishable from a public
    one on the stack.
    """
    for option in _city_lane_options():
        view = option["lane_day_view"]
        assert view is not None, "the plan-bearing option carries no lane day view"
        assert view["lane_count"] == 6
        assert [strip["lane"] for strip in view["strips"]] == [1, 2, 3, 4, 5, 6]
        assert view["weekday"] == _AT_DT.date().weekday()
        segments = [seg for strip in view["strips"] for seg in strip["segments"]]
        assert segments, "every lane's day is empty — the day view carries no reservations"
        # A public segment names no owner; a reserved one must.
        for seg in segments:
            if seg["access"] == "PublicSwim":
                assert seg["owner"] is None
            else:
                assert isinstance(seg["owner"], str) and seg["owner"].strip()
        owners = {seg["owner"] for seg in segments if seg["owner"] is not None}
        assert owners, "no segment names an owner — the stack cannot say whose lane it is"


def test_a_lane_segment_spans_a_real_time_range_within_the_day() -> None:
    """AC1, the half that makes a strip paintable: each segment is an ordered HH:MM range."""
    for option in _city_lane_options():
        for strip in option["lane_day_view"]["strips"]:
            starts = [seg["start"] for seg in strip["segments"]]
            assert starts == sorted(starts), "a lane's segments are not time-ordered"
            for seg in strip["segments"]:
                assert seg["start"] < seg["end"]


def test_a_basin_with_a_binding_but_no_parsed_plan_carries_neither_lane_field() -> None:
    """AC2: `oerlikon-sprungbecken` declares a `lane_plan_source` whose section matched no
    parsed header, so no plan attached. Both new fields must be null — asserted, not assumed —
    and null must mean "not published", never "no lanes free".

    WHY it matched no header is a property of the DOUBLE, not of production
    (board-order-and-defects S4): the shared fixture serves City's sheet for this URL, so the
    `'sprungbecken'` token has nothing to match. Against the real sheet it matches and the basin
    gets a 2-lane plan — see `tests/etl/test_lane_attachment_pin.py`. The INVARIANT under test
    here is unaffected and still worth pinning: whatever leaves a basin plan-less, all four lane
    fields must degrade to null together.
    """
    sprung = [o for o in _options(AT_OERLIKON) if o["basin_id"] == "oerlikon-sprungbecken"]
    assert sprung, "the plan-less lane basin produced no option to assert against"
    for option in sprung:
        assert option["lane_day_view"] is None
        assert option["lane_best_public"] is None
        # Its sibling count fields degrade the same way — the three stay consistent.
        assert option["lane_timeline"] is None
        assert option["lane_availability"] is None


def test_every_option_carries_the_basin_id_the_domain_resolved(gold_db: Path) -> None:
    """AC3: `basin_id` is present on every option and is exactly `SwimOption.basin_id` — the
    board's row key, compared against the domain rather than against itself."""
    store = GoldSwimStore.open(gold_db)
    result = find_swim_options(
        SwimQuery(person=Person(gender=Gender.FEMALE, age=34), at=_AT_DT),
        store.facilities(),
        store.calendar(),
    )
    expected = sorted(
        (str(o.facility_id), str(o.basin_id), o.session.time.start.strftime("%H:%M"))
        for o in result.options
    )
    served_options = _options(AT)
    served = sorted((o["facility_id"], o["basin_id"], o["start"]) for o in served_options)
    assert served == expected
    for option in served_options:
        assert isinstance(option["basin_id"], str) and option["basin_id"]


def test_best_public_agrees_with_the_peak_of_every_options_own_timeline() -> None:
    """AC4, as a fence over the WHOLE answer rather than one hand-picked option.

    Both fields derive from the same stored plan, so the "best time to come" window must report
    the same public-lane count as the busiest segment of THAT option's timeline — and must lie
    inside that option's own hours, because S4 paints it as a band behind that option's row.

    Restricting this to `city-50m` (whose Wednesday session runs 06:00–22:00) would make it pass
    by coincidence of hours: the property held there while failing for 116 of 752 plan-bearing
    options measured across 120 dates. It is asserted on multi-session dates for that reason.
    """
    checked = 0
    for at in (AT, AT_MULTI_SESSION, AT_OERLIKON):
        for option in _options(at):
            if option["lane_timeline"] is None:
                continue
            best = option["lane_best_public"]
            peak = max(seg["public_lanes"] for seg in option["lane_timeline"]["segments"])
            if peak == 0:
                # No lane is public anywhere in this session: the honest answer is "no best
                # time", never a zero-lane window S4 would paint as an empty band.
                assert best is None
                continue
            assert best is not None, (
                f"{option['basin_id']} @ {at}: a plan-bearing option carries no best-public "
                f"window, though its own timeline peaks at {peak} public lanes"
            )
            assert best["start"] < best["end"]
            # Inside the option's own hours — the band must not advertise a time the row is shut.
            assert option["start"] <= best["start"] < best["end"] <= option["end"], (
                f"{option['basin_id']} @ {at}: best-public {best['start']}–{best['end']} "
                f"falls outside the session {option['start']}–{option['end']}"
            )
            assert best["public_lanes"] == peak, (
                f"{option['basin_id']} @ {at}: best-public says {best['public_lanes']} lanes, "
                f"its own timeline peaks at {peak}"
            )
            checked += 1
    # PINNED, not a floor. The store is a deterministic offline build and the three dates are
    # fixed, so the exact count is knowable and was measured: 4 on 2026-08-12, 8 on 2026-05-05,
    # 7 on 2026-05-20 (bungertwies serves two sessions on each date, leimbach two on 05-05). A
    # floor would let the fence quietly shed most of its own coverage and still pass.
    assert checked == 19, f"{checked} plan-bearing options checked, expected 19 — the fence moved"


def test_a_pools_two_sessions_each_get_their_own_best_public_window() -> None:
    """The regression the whole-answer fence above was written for, pinned by name.

    `leimbach-25m` on 2026-05-05 has two scraped sessions, 06:00–08:00 and 12:00–21:00. The
    whole-weekday derivation stamped `09:00–12:00, 6 lanes` onto BOTH — so the morning row would
    have advertised "best 09:00–12:00" on a row whose hours end at 08:00, carrying a lane count
    its own timeline (peak 5) contradicted. Bounding the derivation by the session fixes both
    halves, which is why the two sessions must now hold DIFFERENT windows.
    """
    leimbach = [o for o in _options(AT_MULTI_SESSION) if o["basin_id"] == "leimbach-25m"]
    by_start = {o["start"]: o for o in leimbach}
    assert set(by_start) == {"06:00", "12:00"}, f"expected two sessions, got {sorted(by_start)}"

    morning = by_start["06:00"]
    assert morning["end"] == "08:00"
    best = morning["lane_best_public"]
    assert best is not None
    assert "06:00" <= best["start"] < best["end"] <= "08:00"
    morning_peak = max(seg["public_lanes"] for seg in morning["lane_timeline"]["segments"])
    assert best["public_lanes"] == morning_peak

    # The afternoon session keeps its own, different window — proof the field is derived per
    # session rather than one shared answer clipped after the fact.
    afternoon_best = by_start["12:00"]["lane_best_public"]
    assert afternoon_best is not None
    assert afternoon_best != best


def test_the_existing_lane_count_fields_are_byte_identical_to_before_s2() -> None:
    """AC5: `lane_availability` and `lane_timeline` are UNCHANGED. `poolrank.ts` and
    `insightbar.ts` read them and this slice does not disturb those readers.

    The reference is a fixture dumped from the SAME offline build at commit 659c76a (S1, before
    any S2 code existed), so it is independent of the code under test — the S1 baseline pattern.
    Never regenerate it to make this test pass.

    Two captures: City's single all-day session, and Leimbach's TWO sessions on 2026-05-05 — so
    a change that happens to preserve a day-spanning session cannot pass while breaking a split
    one. That is exactly the gap the best-public defect lived in.
    """
    doc = json.loads((_FIXTURES / "swim_lane_fields_pre_s2.json").read_text(encoding="utf-8"))
    assert doc["generated_at_commit"] == "659c76a"
    assert len(doc["captures"]) == 2
    for capture in doc["captures"]:
        served = [
            {
                "start": o["start"],
                "end": o["end"],
                "lane_availability": o["lane_availability"],
                "lane_timeline": o["lane_timeline"],
            }
            for o in _options(capture["at"])
            if o["facility"] == capture["facility"] and o["basin"] == capture["basin"]
        ]
        assert served, f"no option served for {capture['facility']} @ {capture['at']}"
        assert served == capture["options"], f"{capture['facility']} @ {capture['at']} drifted"
