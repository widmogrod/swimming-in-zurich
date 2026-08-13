"""The lane-plan attachment, pinned over PRODUCTION `data/` and each sheet's OWN committed PDF.

board-order-and-defects S4 AC2. The plan asked for "the build attaches 7 lane plans and
`unmatched_sections` is empty", because one observed build attached 6 and reported
`unmatched section (oerlikon-sprungbecken <- …): declared section 'sprungbecken' matched no
parsed header` while the next attached 7 — a discrepancy that made a silent drop undetectable.

**The discrepancy was diagnosed, and it is not a production defect.** The shared offline build
double (`tests/providers/wfs_snapshot.py`, `_LANE_PDF`) serves ONE sheet —
`city-schwimmerbecken.pdf` — for every `.pdf` URL, on the reasoning that the lane join is
URL-keyed and so binds regardless of content. That holds for the five SINGLE-basin sources and
fails for the one STACKED source: `oerlikon.yaml` declares `oerlikon-sprungbecken` with
`section: "sprungbecken"`, and `_bind_stacked` routes a section by containment against the
sheet's PARSED HEADER. Served City's sheet, the only header is `Hallenbad City Schwimmerbecken`,
so the token matches nothing and the basin is silently left `None`. The "6" was the double; the
"7" was a build over the real sheets.

So this module does NOT read the shared double. It serves each declared URL the committed sheet
of the SAME NAME, which is the production pairing, and pins what the real join does. The
double's own (artifact) numbers are pinned separately and explicitly as artifacts, in
`tests/test_cli.py::test_the_offline_build_doubles_lane_attachment_is_pinned_as_an_artifact` —
read the two together, because they coincidentally BOTH total six for entirely different
reasons.

WHAT THIS MODULE CANNOT CATCH, stated up front so it is not mistaken for a stronger fence than
it is: with the real sheets nothing is unmatched and nothing is stale, so the assertions
`unmatched_sections == ()` and `warnings == ()` are satisfied both by correct code and by code
that has stopped reporting. Emptying `find_unmatched_sections` leaves this whole module green;
the artifact test in `tests/test_cli.py` and
`tests/etl/test_silver.py::test_declared_section_absent_from_parsed_headers_is_audited` are what
kill that mutant. This module's discriminating power is over ROUTING — which sheet reached which
basin — and that was verified by mutation: token-blind binding, a dropped attach, and serving
one sheet for every URL each redden it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Ok
from swimzh.domain.lane_plan import LanePlan
from swimzh.domain.models import PoolId
from swimzh.etl.lane_plans import LanePlanReport, scrape_lane_plans
from swimzh.etl.silver import LanePlanAttachment, attach_lane_plans
from swimzh.providers.curated import Dataset, load_dataset
from swimzh.providers.page_provider import DiscoveredLink

_REPO = Path(__file__).resolve().parents[2]
DATA_DIR = _REPO / "data"
SHEETS = _REPO / "tests" / "providers" / "fixtures"

FETCHED_AT = datetime(2026, 8, 12, 9, 0, tzinfo=ZoneInfo("Europe/Zurich"))

# The lane counts each declared basin gets from ITS OWN committed sheet. Measured, not assumed —
# and they are exactly the shapes a live build records (the base checkout's rebuilt `gold.sqlite`
# carries Bläsi 5, City 6, Leimbach 5, Oerlikon 50m 8, Sprungbecken 2, Käferberg 4).
EXPECTED_LANE_COUNTS = {
    ("hallenbad-blaesi", "blaesi-25m"): 5,
    ("hallenbad-city", "city-50m"): 6,
    ("hallenbad-leimbach", "leimbach-25m"): 5,
    ("hallenbad-oerlikon", "oerlikon-50m"): 8,
    ("hallenbad-oerlikon", "oerlikon-sprungbecken"): 2,
    ("waermebad-kaeferberg", "kaeferberg-mehrzweckbecken"): 4,
}

# The ONE declared source with no committed sheet. `bungertwies.pdf` is declared by
# `data/pools/bungertwies.yaml`, but the sheet is not in the repo and may not be invented, so
# nothing here can measure it. (The plan's Design table records Bungertwies at 4 lanes; that is
# an attribution, not something this suite verifies.) It is named rather than hidden inside a
# range: commit the real sheet and this test goes RED, demanding a re-pin to seven.
UNCOMMITTED_SHEET = "bungertwies.pdf"


def _serve_its_own_sheet(request: httpx.Request) -> httpx.Response:
    """Each Belegungsplan URL → the committed fixture of the SAME FILENAME (the production
    pairing). A URL with no committed sheet 404s, which is what makes its absence assertable
    rather than silently substituted."""
    name = str(request.url).rsplit("/", 1)[-1]
    sheet = SHEETS / name
    if not sheet.exists():
        return httpx.Response(404)
    return httpx.Response(200, content=sheet.read_bytes())


def _lane_client() -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(_serve_its_own_sheet))
    return HttpClient(inner, source="belegungsplan", retry=RetryPolicy(max_attempts=1))


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    result = load_dataset(DATA_DIR)
    assert isinstance(result, Ok), result
    return result.value


def _declared_sources(dataset: Dataset) -> dict[tuple[str, str], str]:
    return {
        (str(facility.identity.facility_id), str(basin.basin_id)): basin.lane_plan_source.url
        for facility in dataset.facilities
        for basin in facility.basins
        if basin.lane_plan_source is not None
    }


class _Run(NamedTuple):
    """One production-shaped lane run: what the fetch reported, and what attached."""

    report: LanePlanReport
    attachment: LanePlanAttachment


@pytest.fixture(scope="module")
def run(dataset: Dataset) -> _Run:
    """Discovery → fetch → attach, over production `data/` and the real per-URL sheets."""
    links = [
        DiscoveredLink(pool_id=PoolId(pool_id), url=url)
        for (pool_id, _basin), url in _declared_sources(dataset).items()
    ]
    report = scrape_lane_plans(_lane_client(), links)
    result = attach_lane_plans(dataset.facilities, report.plans, FETCHED_AT)
    assert isinstance(result, Ok), result
    return _Run(report, result.value)


def test_the_seven_declared_lane_sources_are_exactly_these(dataset: Dataset) -> None:
    """The universe the counts below are relative to. Seven basins declare a lane source; six
    have a committed sheet. Naming the set means a new declaration reddens this rather than
    silently changing what "all of them attached" means."""
    assert set(_declared_sources(dataset)) == set(EXPECTED_LANE_COUNTS) | {
        ("hallenbad-bungertwies", "bungertwies-25m")
    }


def test_only_bungertwies_lacks_a_committed_sheet(run: _Run) -> None:
    """Pinned as an equality, never a floor: exactly one declared source fails to fetch, and it
    is the one whose sheet the repo does not carry. In the real pipeline a miss ABORTS the run
    fail-fast, so this is also the reason the production build's number is seven, not six."""
    report = run.report
    assert [miss.source_url.rsplit("/", 1)[-1] for miss in report.misses] == [UNCOMMITTED_SHEET]


def test_every_declared_basin_with_a_sheet_attaches_with_its_own_lane_count(run: _Run) -> None:
    """AC2's count, pinned as the full `(pool, basin) -> lane_count` MAP rather than a bare
    total. A total of six survives any permutation that loses one plan and gains another; the
    map does not — and it is the map that catches the failure that started this, where five
    distinct pools all served City's six-lane plan."""
    result = run.attachment
    attached = {
        (str(facility.identity.facility_id), str(basin.basin_id)): basin.lane_plan.lane_count
        for facility in result.facilities
        for basin in facility.basins
        if isinstance(basin.lane_plan, LanePlan)
    }
    assert attached == EXPECTED_LANE_COUNTS


def test_no_declared_section_token_goes_unmatched(run: _Run) -> None:
    """The stacked-routing half of AC2, and the assertion the whole diagnosis turned on.

    `oerlikon-sprungbecken` is the ONE stacked declaration in the repo. Against its own sheet —
    which parses to two sections, `Nichtschwimmer` and `Sprungbecken` — the declared token
    matches, so nothing is unmatched and the basin gets its 2-lane plan. A parser-header
    regression that stopped producing the `Sprungbecken` header would leave the basin silently
    `None`.

    NOTE on what this module does NOT catch: `find_unmatched_sections` returning `()`
    unconditionally leaves every test here GREEN — with the real sheets there is nothing to
    report, so an emptied report is indistinguishable from a correct one. The mutant that
    silences it is killed by the DOUBLE's test
    (`tests/test_cli.py::test_the_offline_build_doubles_lane_attachment_is_pinned_as_an_artifact`,
    where a section genuinely IS unmatched) and by
    `tests/etl/test_silver.py::test_declared_section_absent_from_parsed_headers_is_audited`.
    Verified by mutation, not assumed. What this test does catch is the routing itself: binding
    that ignores the token, or a sheet substituted for another, reddens the assertions below.
    """
    result = run.attachment
    assert result.unmatched_sections == ()
    # The consequence of the token matching, read off the ACTUAL run rather than off the
    # module-level table: the stacked basin really did receive its own sheet's 2-lane section.
    attached = {
        (str(facility.identity.facility_id), str(basin.basin_id)): basin.lane_plan
        for facility in result.facilities
        for basin in facility.basins
        if isinstance(basin.lane_plan, LanePlan)
    }
    sprungbecken = attached[("hallenbad-oerlikon", "oerlikon-sprungbecken")]
    assert sprungbecken.lane_count == 2
    # …and it is NOT the 50m sheet's plan, which is what a token-blind bind would have given it.
    assert attached[("hallenbad-oerlikon", "oerlikon-50m")].lane_count == 8


def test_the_one_unbound_section_is_the_uncurated_half_of_the_stacked_sheet(run: _Run) -> None:
    """The stacked Oerlikon sheet carries a section no basin declares. That is a real, expected
    audit line — a sheet publishing more than the crosswalk claims — so it is NAMED, not allowed
    to hide in an unasserted list."""
    result = run.attachment
    assert [(u.basin_hint, u.source_url.rsplit("/", 1)[-1]) for u in result.unbound] == [
        ("Nichtschwimmer", "oerlikon-nichtschwimmer-sprungbecken.pdf")
    ]


def test_the_attachment_reports_no_staleness_warning(run: _Run) -> None:
    """Production `data/pools/*.yaml` are thin crosswalks with no curated `valid_as_of`, so no
    plan can predate its schedule. Asserted so a re-introduced curated schedule tier surfaces
    here instead of printing warnings nobody reads."""
    result = run.attachment
    assert result.warnings == ()
