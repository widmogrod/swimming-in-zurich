from __future__ import annotations

from fastapi.testclient import TestClient

from apps.web.main import app


def test_index_serves_html_page() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Swimming in Zürich" in response.text
    assert "All pools" in response.text  # the browse-all tab


def test_page_renders_the_three_terminal_states_distinctly() -> None:
    """S1 invariant #1: open / closed-with-reason / uncurated are never merged. The page's
    render code must carry a distinct branch (and CSS class) for each."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Open: closing-time treatment.
    assert "OPEN · closes" in page
    assert "state open" in page
    # Closed: a reason, its own glyph + class.
    assert "CLOSED —" in page
    assert "status closed" in page
    # Uncurated: explicitly "NOT closed", its own class — the never-conflated third state.
    assert "UNCURATED" in page and "NOT closed" in page
    assert "status uncurated" in page


def test_page_carries_the_unified_glyph_legend_and_badge() -> None:
    """S1: the shared legend (two orthogonal glyph axes), the length badge, and the
    provenance stamp are part of the visual language."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Both orthogonal axes appear in the legend.
    assert "ACCESS" in page and "≈ lane" in page and "◇ public" in page
    assert "FOR YOU" in page and "✓ in" in page and "? unknown" in page
    # Length badge + provenance stamp scaffolding.
    assert "lenbadge" in page
    assert "ⓘ" in page and "valid_as_of" in page


def test_badge_renders_lane_count_subline_conditionally() -> None:
    """S2: the badge carries a "N lane" sub-line driven by OptionOut.lanes, rendered only
    when the lane count is known (o.lanes != null) so an unknown count degrades to
    length-only rather than fabricating a number."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The render branch reads the lanes field and gates on its presence.
    assert "o.lanes != null" in page
    assert "lane</span>" in page
    # Its own badge sub-line class exists in the stylesheet.
    assert ".lenbadge .lanes" in page


def test_tourist_tab_renders_primer_and_glossary() -> None:
    """S3: the newcomer tab leads with a plain-language primer — pool types keyed off the
    catalog `kind`, a how-to-enter section, and a slot glossary sourced from /access-types."""
    with TestClient(app) as client:
        page = client.get("/").text
    # A distinct nav tab + its own section for the newcomer.
    assert 'data-tab="visit"' in page
    assert "First time here?" in page
    assert 'id="visit"' in page
    # The primer's teaching sections.
    assert "POOL TYPES" in page and "TO ENTER" in page and "THE SLOTS" in page
    # Pool types are keyed off `kind`; the slot glossary is sourced from /access-types.
    assert "POOL_TYPES" in page  # the kind -> plain-language map
    assert "fetch('/access-types')" in page
    # Jargon is decoded inline (German term -> what it lets you do).
    assert "Bahnenschwimmen" in page and "Öffentlich" in page


def test_tourist_starter_pools_keep_closed_pools_visible() -> None:
    """S3 invariant: a tourist at a locked door is the worst outcome, so closed/uncurated
    pools are always kept visible below the distance-ranked starter pools — never hidden."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The tourist output renders the status lines, reusing the closed/uncurated branches.
    assert "a.statuses.map(statusLine)" in page
    assert "NOT necessarily shut" in page
    # It reuses the shared honesty language: the provenance stamp over the same options.
    assert "provStamp(a.options)" in page
    # Starter pools are the distance-ranked options (the service sorts by distance).
    assert "a.options.slice(0, 3)" in page


def test_tourist_tab_shows_distance_only_never_walk_time() -> None:
    """S3 / gap #4: with no routing model, the tourist view shows km only — walk / transit
    time is deliberately never rendered."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Distance in km is surfaced in the starter card; walk-time never is.
    assert "o.distance_km + ' km'" in page
    assert "min walk" not in page.lower()
    assert "walk time" not in page.lower()


def test_week_planner_tab_and_grid_scaffolding() -> None:
    """S4: a distinct "Plan my week" nav tab + section carrying the days×time grid."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert 'data-tab="plan"' in page
    assert "Plan my week" in page
    assert 'id="plan"' in page
    # The weekly grid table + its seven day columns.
    assert "weekgrid" in page
    assert "['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']" in page


def test_week_planner_assembles_seven_swim_calls_option_a() -> None:
    """S4 discovery (Option A): the grid needs 7 days but /swim takes one moment, so the
    client issues one call per weekday (find_swim_options returns the whole day's sessions)
    and assembles the week — no API change."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Seven weekday labels drive seven /swim requests, gathered with Promise.all.
    assert "WEEKDAYS.map" in page or "days.map(async" in page
    assert "Promise.all(days.map" in page
    assert "fetch('/swim?'" in page
    # The discovery rationale is documented in-code (Option A, no API change).
    assert "Option A" in page


def test_week_planner_cells_use_both_orthogonal_glyph_axes() -> None:
    """S4: each grid cell carries the unified access glyph (≈◇⌂WSX·) plus a SEPARATE
    eligibility axis (✓✗?), reusing the shared helpers — one glyph pair per cell."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Cells reuse the shared access-glyph map and the eligibility axis helper.
    assert "accessGlyph(o.access)" in page
    assert "eligAxis(o)" in page
    assert "cell-elig" in page
    # "One glyph pair per cell" — lane is preferred when a slot stacks sessions.
    assert "one glyph pair per cell" in page


def test_week_planner_busyness_is_bracketed_forecast_placeholder() -> None:
    """S4 / invariant #2: busyness is un-wired, so it may only appear as a bracketed [fc]
    forecast caption — never a plain value and never a top sort key."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert "[fc]" in page
    # It is explicitly captioned as a forecast, not a live count.
    assert "live occupancy is not wired" in page
    assert "forecast" in page.lower()


def test_week_planner_pool_switcher_is_distance_sorted() -> None:
    """S4: the pool switcher lists nearby pools sorted by distance, nearest selected."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert 'id="poolSwitch"' in page
    # Distance drives the ordering; the nearest pool is the default selection.
    assert "distance_km ?? Infinity) - (b.distance_km ?? Infinity)" in page
    assert "planSelected = planPools.length ? planPools[0].facility" in page


def test_week_planner_never_blanks_closed_or_unknown_days() -> None:
    """S4 invariant #1: the three terminal states stay un-merged in the grid — an OPEN day's
    empty slot (·), a CLOSED day (· + reason), and an UNKNOWN day (?) are distinct, and a
    day with no data is a ? (unknown), never a blank that reads as "closed"."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The day-state resolver distinguishes open / closed / unknown explicitly.
    assert "state: 'open'" in page
    assert "state: 'closed'" in page
    assert "state: 'unknown'" in page
    # Unknown days render a ? with its own class — never a silent blank.
    assert "unknown-day" in page
    assert "NOT closed" in page
    # Closed days keep their reason surfaced below the grid.
    assert "daynote closed" in page and "daynote unknown" in page


def test_week_planner_is_read_only_no_routine_persistence() -> None:
    """S4 scope: the grid is READ-ONLY. The "pick 3 / save routine" tray is deferred to
    gap #5 (Routine entity) — there must be no persistence action wired in."""
    with TestClient(app) as client:
        page = client.get("/").text
    # No save-routine control and no write request from the planner.
    assert "save routine" not in page.lower()
    assert "method: 'POST'" not in page
    # The read-only intent is stated to the user.
    assert "Read-only" in page or "read-only" in page.lower()
