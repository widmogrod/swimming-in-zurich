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
    """S1/S2 invariant #1: open / closed-with-reason / uncurated are never merged. The page's
    render code must carry a distinct branch (and CSS class) for each. S2 rewords the third
    state in plain language ("Hours not listed yet") but MUST keep it a distinct branch/class,
    never folded into "closed"."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Open: closing-time treatment.
    assert "OPEN · closes" in page
    assert "state open" in page
    # Closed: a reason, its own glyph + class.
    assert "CLOSED —" in page
    assert "status closed" in page
    # Uncurated third state: plain wording (no dev token "UNCURATED"), its own branch + class.
    assert "UNCURATED" not in page  # dev vocabulary killed
    assert "Hours not listed yet" in page
    assert "may well be open, we just don't have its timetable" in page
    assert "status uncurated" in page
    assert "s.status === 'uncurated'" in page  # still a distinct render branch


def test_page_carries_the_unified_glyph_legend_and_badge() -> None:
    """S1: the shared legend (two orthogonal glyph axes), the length badge, and the
    provenance stamp are part of the visual language. S2 keeps the glyph axes but rewords the
    provenance stamp in plain language (no ``valid_as_of`` dev token)."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Both orthogonal axes appear in the legend.
    assert "ACCESS" in page and "≈ lane" in page and "◇ public" in page
    assert "FOR YOU" in page and "✓ in" in page and "? unknown" in page
    # Length badge + provenance stamp scaffolding, now in plain words.
    assert "lenbadge" in page
    assert "ⓘ" in page
    # The user-facing freshness phrase is plain; the old "valid as of" label is gone.
    # (``o.valid_as_of`` still appears as an API property read in the inline script — that is
    # the JSON contract field, not rendered label text.)
    assert "valid as of" not in page
    assert "Schedule last checked" in page


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
    """S1/S3: the newcomer tab leads with a plain-language primer — one always-visible
    how-to-enter line, then a glossary (pool types keyed off `kind`, slots from
    /access-types) tucked into a default-closed <details>."""
    with TestClient(app) as client:
        page = client.get("/").text
    # A distinct nav tab + its own section for the newcomer.
    assert 'data-tab="visit"' in page
    assert "First time here?" in page
    assert 'id="visit"' in page
    # The one always-visible how-to-enter line (replaces the old ~19-row TO ENTER block).
    assert "Just walk in and pay in CHF at the door" in page
    # The collapsed glossary's teaching sections.
    assert "POOL TYPES" in page and "THE SLOTS" in page
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
    # Starter pools are distinct FACILITIES taken from the distance-ordered options.
    assert "if (!byFacility.has(o.facility)) byFacility.set(o.facility, o)" in page
    assert "[...byFacility.values()].slice(0, 3)" in page


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


def test_week_planner_busyness_is_a_single_plain_line_no_column() -> None:
    """S2 #8 / invariant #2: busyness is un-wired. The old ``[fc]`` grid column and its two
    captions are gone, replaced by a single plain line "Busyness: not available yet." — the
    honesty invariant satisfied with words, the grid column reclaimed."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The bracketed dev placeholder and its column are gone everywhere.
    assert "[fc]" not in page
    assert 'class="fc"' not in page
    assert ".weekgrid td.fc" not in page  # dead CSS rule removed too
    # A single plain honesty line replaces the column + captions.
    assert "Busyness: not available yet." in page


def test_week_planner_pool_switcher_is_distance_sorted() -> None:
    """S4: the pool switcher lists nearby pools sorted by distance, nearest selected."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert 'id="poolSwitch"' in page
    # Distance drives the ordering; the nearest OPEN pool is the default selection.
    assert "distance_km ?? Infinity) - (b.distance_km ?? Infinity)" in page
    assert "planSelected = openPools.length ? openPools[0].facility" in page


def test_week_planner_surfaces_closed_pools_and_explains_the_catalog_gap() -> None:
    """A pool closed all week produces no options, so it would silently vanish from the
    switcher — invariant #1 forbids that. Closed pools are surfaced as struck-through chips,
    and a note explains why the plannable set is smaller than the ~57-pool "All pools" catalog."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Closed-all-week pools (from `statuses`) are added to the switcher, not dropped.
    assert "s.status === 'closed' && !dist.has(s.facility)" in page
    assert "closedchip" in page and "(closed)" in page
    # An honesty note reconciles the plannable set with the full catalog count from /pools.
    assert 'id="planNote"' in page
    assert "only pools with a curated timetable can be planned" in page
    assert "catalog locations" in page
    assert "await fetch('/pools')" in page  # catalog total drives the note


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


def test_tourist_starters_are_distinct_facilities_not_sessions() -> None:
    """S1 #1: slicing raw sessions surfaced the same pool twice (Oerlikon appeared as two of
    the three "starter pools"). Options are distance-then-time ordered, so keeping the FIRST
    (earliest) session per facility and taking three yields three DISTINCT pools — never the
    old ``a.options.slice(0, 3)`` on sessions."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Dedupe by facility, keeping the FIRST session seen per pool (earliest/next window). A
    # Map built from entries keeps the LAST, so we guard on `.has` before setting.
    assert "if (!byFacility.has(o.facility)) byFacility.set(o.facility, o)" in page
    assert "[...byFacility.values()].slice(0, 3)" in page
    # The old session-level slice is gone.
    assert "a.options.slice(0, 3)" not in page


def test_tourist_primer_is_a_default_closed_details() -> None:
    """S1 #3: the oversized (~19-row) always-open primer collapses to one always-visible
    how-to-enter line plus a default-closed <details> for the POOL TYPES / THE SLOTS
    glossary — so the starter pools, not a glossary wall, are what a newcomer meets first."""
    with TestClient(app) as client:
        page = client.get("/").text
    # One always-visible line carries the essential how-to-enter fact.
    assert "primerlead" in page
    assert "Just walk in and pay in CHF at the door" in page
    # The glossary lives in a <details> that is NOT force-opened (no `open` attribute).
    assert '<details class="primerdetails">' in page
    assert '<details class="primerdetails" open' not in page
    # POOL TYPES / THE SLOTS are inside that collapsed block.
    assert "POOL TYPES" in page and "THE SLOTS" in page


def test_tourist_primer_pool_types_keyed_to_present_kinds_not_all_seven() -> None:
    """S1 #3: POOL TYPES is built from the kinds actually present in the results
    (``a.options``), not the full 7-category catalog — a tourist browsing indoor pools does
    not read river/lake/thermal glosses."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The type list is derived from the options' distinct kinds, not pools.kinds.
    assert "new Set(options.map(o => o.kind)" in page
    # And the primer is rendered from the /swim options, driven by the results.
    assert "renderPrimer(a.options)" in page


def test_tourist_starter_pools_render_above_the_primer() -> None:
    """S1 #3: starter pools move above the fold — the ``#visitOut`` results container is
    placed before the collapsed ``#primer`` in document order."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert '<div id="visitOut"></div>' in page
    assert '<div class="primer" id="primer"></div>' in page
    assert page.index('<div id="visitOut"></div>') < page.index(
        '<div class="primer" id="primer"></div>'
    )


def test_tourist_primer_keeps_inline_decode_on_starter_cards() -> None:
    """S1 keeps the good model: the inline decode-at-point-of-need line on each starter card
    (``This slot is <b>…</b>``) survives the primer collapse."""
    with TestClient(app) as client:
        page = client.get("/").text
    assert "This slot is <b>" in page
    assert "decodeAccess(o.access)" in page


def test_find_card_renders_the_english_access_word_not_only_a_glyph() -> None:
    """S2 #4: a swim card's access must READ AS A WORD (via ``accessLabel``), not rely on the
    bare glyph alone. The scannable glyph stays, but the word is rendered beside it."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The card body renders the access word from the helper, adjacent to the access glyph.
    assert "accessLabel(o.access)" in page
    assert "axis-access" in page  # the glyph is kept for the scannable grid/badge language
    # The tourist starter card carries the word too, via the inline decode line.
    assert "This slot is <b>" in page


def test_glyph_legend_moved_below_results_into_closed_details_on_find_and_plan() -> None:
    """S2 #4: the monospace glyph legend moves from ABOVE the results to BELOW them, tucked
    into a default-closed "What do the symbols mean?" <details> on both the Find and Plan
    tabs — so a first read meets the results, not a decoder wall."""
    with TestClient(app) as client:
        page = client.get("/").text
    # The legend now sits inside a symbols expander, not force-open.
    assert '<details class="symbols"><summary>What do the symbols mean?</summary>' in page
    assert '<details class="symbols" open' not in page
    # Two expanders — one per tab (Find + Plan).
    assert page.count('<details class="symbols">') == 2
    # On Find the legend follows the results container (below, not above).
    assert page.index('<div id="findOut"></div>') < page.index('<details class="symbols">')
    # On Plan the legend follows the grid output container.
    assert page.index('<div id="planOut"></div>') < page.rindex('<details class="symbols">')
    # The glyph legend content is still present (moved, not deleted).
    assert '<pre class="glyphlegend">' in page


def test_provenance_stamp_uses_plain_language_not_dev_tokens() -> None:
    """S2 #5: the provenance stamp reports freshness + source in plain words. The developer
    ``(curated)/(scraped)/(mixed)`` tokens become "official schedule" / "read from the pool's
    website" / "mixed sources", and ``valid_as_of`` becomes "Schedule last checked {date}"."""
    with TestClient(app) as client:
        page = client.get("/").text
    # Plain-language provenance phrases replace the raw curated/scraped/mixed tokens.
    assert "official schedule" in page
    assert "read from the pool's website" in page
    assert "mixed sources" in page
    # And the freshness wording is plain, not the API field name.
    assert "Schedule last checked" in page
    # The raw dev tokens no longer render as the provenance mode.
    assert "(curated)" not in page and "(scraped)" not in page and "(mixed)" not in page
