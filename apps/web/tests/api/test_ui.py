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
