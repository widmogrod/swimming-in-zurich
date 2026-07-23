"""These tests pin the content of the LEGACY four-tab page string (`_RENDERED_PAGE`).

S4 retired the four-tab model at `/` (now the unified two-mode shell — see
``test_shell.py``), but kept the legacy `_PAGE`/`_RENDERED_PAGE` string as DEAD code so
this slice's diff stays reviewable. These assertions therefore read the string DIRECTLY
rather than fetching `/`; S5 deletes the legacy string and this file together.
"""

from __future__ import annotations

from apps.web.api.ui.router import _RENDERED_PAGE


def test_legacy_page_string_is_a_complete_html_document() -> None:
    page = _RENDERED_PAGE
    assert page.startswith("<!doctype html>")
    assert "Swimming in Zürich" in page
    assert "All pools" in page  # the browse-all tab


def test_page_renders_the_three_terminal_states_distinctly() -> None:
    """S1/S2 invariant #1: open / closed-with-reason / uncurated are never merged. The page's
    render code must carry a distinct branch (and CSS class) for each. S2 rewords the third
    state in plain language ("Hours not listed yet") but MUST keep it a distinct branch/class,
    never folded into "closed"."""
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
    # The render branch reads the lanes field and gates on its presence.
    assert "o.lanes != null" in page
    assert "lane</span>" in page
    # Its own badge sub-line class exists in the stylesheet.
    assert ".lenbadge .lanes" in page


def test_lane_availability_badge_renders_conditionally() -> None:
    """S3: the lane-availability glance badge ("5/6 lanes public · until 18:00") is driven by
    OptionOut.lane_availability, rendered only when the basin has a parsed plan (absent =>
    no badge, an honest degrade) and flags `partial` when a lane is unresolved."""
    page = _RENDERED_PAGE
    # The render branch reads the lane_availability field and gates on its presence.
    assert "o.lane_availability" in page
    assert "lanes public" in page
    assert "until ${esc(la.public_until)}" in page
    assert "la.partial" in page
    # Its own badge class exists in the stylesheet.
    assert ".lanebadge" in page


def test_facility_detail_lane_panel_renders_conditionally() -> None:
    """S4: the facility-detail lane panel (per-lane timeline, best public time, club roster) is
    an expander shown only on cards whose basin has a parsed plan (o.lane_availability present).
    It lazy-loads the /pools/{id} facility detail on first open."""
    page = _RENDERED_PAGE
    # The expander is gated on a parsed plan and carries the facility id for the fetch.
    assert "function laneSchedHTML(o)" in page
    assert "if (!o.lane_availability) return ''" in page
    assert "Lane schedule this week" in page
    assert "data-facility-id" in page
    # It fetches the facility-detail endpoint and renders the three derivations.
    assert "'/pools/' + encodeURIComponent(id)" in page
    assert "function basinPanelHTML(bp)" in page
    assert "Best time to come" in page
    assert "Per-lane timeline" in page
    assert "Club roster" in page
    assert "function rosterHTML(roster)" in page
    # Its own panel classes exist in the stylesheet.
    assert ".lanepanel" in page and ".besttime" in page and ".lanestrip" in page


def test_pool_detail_panel_renders_basins_features_lockers_prices() -> None:
    """Slice C: the /pools/{id} detail panel renders the physical statics — basin cards with a
    prominent water-temperature badge + size/lane chips + a PARSED_PROSE caveat where the
    physicals were auto-extracted, a feature "open now?" pill with hours, lockers, and prices."""
    page = _RENDERED_PAGE
    # The panel composes basins/features/lockers/prices, then lane plans.
    assert "function facilityDetailHTML(d)" in page
    assert "box.innerHTML = facilityDetailHTML(d);" in page
    # Basin cards: a temperature badge gated on the datum, size/lane chips, the PARSED_PROSE caveat.
    assert "function basinCardHTML(b)" in page
    assert "b.nominal_temp_c != null" in page
    assert "tempbadge" in page and ".tempbadge" in page  # render + its own style
    assert "sizechip" in page and "lane${b.lanes === 1 ? '' : 's'}" in page
    assert "b.physical_source === 'parsed_prose'" in page
    assert "PARSED_PROSE" in page and "parsedcaveat" in page
    # Feature "open now?" pill (green open / grey closed), driven by open_now, with hours.
    assert "function featureRowHTML(fe)" in page
    assert "fe.open_now === true" in page
    assert "openpill open" in page and "openpill closed" in page
    assert ".openpill.open { background: var(--elig-in); }" in page
    # Lockers and prices each render from the detail response.
    assert "function lockerRowHTML(l)" in page
    assert "function priceTableHTML(pt)" in page
    assert "Prices checked" in page


def test_tourist_tab_renders_primer_and_glossary() -> None:
    """S1/S3: the newcomer tab leads with a plain-language primer — one always-visible
    how-to-enter line, then a glossary (pool types keyed off `kind`, slots from
    /access-types) tucked into a default-closed <details>."""
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
    # The tourist output renders the status lines, reusing the closed/uncurated branches.
    assert "a.statuses.map(statusLine)" in page
    assert "NOT necessarily shut" in page
    # It reuses the shared honesty language: the consolidated footer (provenance + coverage)
    # over the same options (S6 #10 folded provStamp + the amber banner into one footer).
    assert "footerHTML(a.options)" in page
    # Starter pools are distinct FACILITIES taken from the distance-ordered options.
    assert "if (!byFacility.has(o.facility)) byFacility.set(o.facility, o)" in page
    assert "[...byFacility.values()].slice(0, 3)" in page


def test_tourist_tab_shows_distance_only_never_walk_time() -> None:
    """S3 / gap #4: with no routing model, the tourist view shows km only — walk / transit
    time is deliberately never rendered."""
    page = _RENDERED_PAGE
    # Distance in km is surfaced in the starter card; walk-time never is.
    assert "o.distance_km + ' km'" in page
    assert "min walk" not in page.lower()
    assert "walk time" not in page.lower()


def test_week_planner_tab_and_grid_scaffolding() -> None:
    """S4: a distinct "Plan my week" nav tab + section carrying the days×time grid."""
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
    # Seven weekday labels drive seven /swim requests, gathered with Promise.all.
    assert "WEEKDAYS.map" in page or "days.map(async" in page
    assert "Promise.all(days.map" in page
    assert "fetch('/swim?'" in page
    # The discovery rationale is documented in-code (Option A, no API change).
    assert "Option A" in page


def test_week_planner_cells_use_both_orthogonal_glyph_axes() -> None:
    """S4: each grid cell carries the unified access glyph (≈◇⌂WSX·) plus a SEPARATE
    eligibility axis (✓✗?), reusing the shared helpers — one glyph pair per cell."""
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
    # The bracketed dev placeholder and its column are gone everywhere.
    assert "[fc]" not in page
    assert 'class="fc"' not in page
    assert ".weekgrid td.fc" not in page  # dead CSS rule removed too
    # A single plain honesty line replaces the column + captions.
    assert "Busyness: not available yet." in page


def test_week_planner_pool_switcher_is_distance_sorted() -> None:
    """S4: the pool switcher lists nearby pools sorted by distance, nearest selected."""
    page = _RENDERED_PAGE
    assert 'id="poolSwitch"' in page
    # Distance drives the ordering; the nearest OPEN pool is the default selection.
    assert "distance_km ?? Infinity) - (b.distance_km ?? Infinity)" in page
    assert "planSelected = openPools.length ? openPools[0].facility" in page


def test_week_planner_surfaces_closed_pools_and_explains_the_catalog_gap() -> None:
    """A pool closed all week produces no options, so it would silently vanish from the
    switcher — invariant #1 forbids that. Closed pools are surfaced as struck-through chips,
    and a note explains why the plannable set is smaller than the ~57-pool "All pools" catalog."""
    page = _RENDERED_PAGE
    # Closed-all-week pools (from `statuses`) are added to the switcher, not dropped.
    assert "s.status === 'closed' && !dist.has(s.facility)" in page
    assert "closedchip" in page and "(closed)" in page
    # An honesty note reconciles the plannable set with the full catalog count from /pools.
    assert 'id="planNote"' in page
    assert "only pools with a curated timetable can be planned" in page
    assert "catalog locations" in page
    # The catalog total comes from the memoized /pools fetch (S5 folded the last raw
    # `await fetch('/pools')` — the All-pools tab's — onto loadPoolsData()).
    assert "if (catalogCount === null) catalogCount = catalog.count;" in page


def test_week_planner_never_blanks_closed_or_unknown_days() -> None:
    """S4 invariant #1: the three terminal states stay un-merged in the grid — an OPEN day's
    empty slot (·), a CLOSED day (· + reason), and an UNKNOWN day (?) are distinct, and a
    day with no data is a ? (unknown), never a blank that reads as "closed"."""
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
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
    page = _RENDERED_PAGE
    # The type list is derived from the options' distinct kinds, not pools.kinds.
    assert "new Set(options.map(o => o.kind)" in page
    # And the primer is rendered from the /swim options, driven by the results.
    assert "renderPrimer(a.options)" in page


def test_tourist_starter_pools_render_above_the_primer() -> None:
    """S1 #3: starter pools move above the fold — the ``#visitOut`` results container is
    placed before the collapsed ``#primer`` in document order."""
    page = _RENDERED_PAGE
    assert '<div id="visitOut"></div>' in page
    assert '<div class="primer" id="primer"></div>' in page
    assert page.index('<div id="visitOut"></div>') < page.index(
        '<div class="primer" id="primer"></div>'
    )


def test_tourist_primer_keeps_inline_decode_on_starter_cards() -> None:
    """S1 keeps the good model: the inline decode-at-point-of-need line on each starter card
    (``This slot is <b>…</b>``) survives the primer collapse."""
    page = _RENDERED_PAGE
    assert "This slot is <b>" in page
    assert "decodeAccess(o.access)" in page


def test_find_card_renders_the_english_access_word_not_only_a_glyph() -> None:
    """S2 #4: a swim card's access must READ AS A WORD (via ``accessLabel``), not rely on the
    bare glyph alone. The scannable glyph stays, but the word is rendered beside it."""
    page = _RENDERED_PAGE
    # The card body renders the access word from the helper, adjacent to the access glyph.
    assert "accessLabel(o.access)" in page
    assert "axis-access" in page  # the glyph is kept for the scannable grid/badge language
    # The tourist starter card carries the word too, via the inline decode line.
    assert "This slot is <b>" in page


def test_glyph_legend_moved_below_results_into_closed_details_on_find_and_plan() -> None:
    """S2 #4: the monospace glyph legend moves from ABOVE the results to BELOW them, tucked
    into a default-closed "What do the symbols mean?" <details> on both the Find and Plan
    tabs — so a first read meets the results, not a decoder wall."""
    page = _RENDERED_PAGE
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


def test_pool_catalog_is_fetched_once_and_memoized_into_a_join_map() -> None:
    """S3 spine: /swim carries only the facility NAME; /pools carries url/phone/address/geo.
    The page fetches /pools ONCE into a name->record map (shared by every tab) and exposes a
    poolInfo(name) helper — stop discarding the array."""
    page = _RENDERED_PAGE
    # A single memoized fetch guarded so it runs at most once, building a name->record map.
    assert "function loadPoolsData()" in page
    assert "if (!poolsPromise) poolsPromise = fetch('/pools')" in page
    assert "poolMap = new Map((a.pools || []).map(p => [p.name, p]))" in page
    # The join helper returns the catalog record or null (never throws on a miss).
    assert "function poolInfo(name) { return poolMap.get(name) || null; }" in page
    # The Find and tourist renders await the memoized data before building cards.
    assert page.count("await loadPoolsData();") >= 2
    # The plan tab reuses the SAME memoized fetch for its catalog count (not a second /pools).
    assert "const catalog = await loadPoolsData();" in page


def test_facility_name_is_a_link_when_catalog_url_exists_else_plain_text() -> None:
    """S3 #2: every facility name becomes an <a href> when the catalog carries a url, and
    degrades to plain escaped text otherwise — never a broken or empty href."""
    page = _RENDERED_PAGE
    # The name helper: an anchor when a url exists, plain esc(name) when it does not.
    assert "info && info.url" in page
    assert '<a href="${esc(info.url)}" target="_blank" rel="noopener">${esc(name)}</a>' in page
    assert ": esc(name);" in page  # graceful degrade branch
    # Every card renderer routes its facility name through the link helper (Find, tourist, plan).
    # S4 renamed the card's name container to the hero `.cardname`; the link helper is unchanged.
    assert "${poolNameHTML(o.facility)} · ${esc(o.basin)}" in page  # Find + tourist cards
    assert 'class="cardname">' in page or 'class="cardname"><span' in page
    assert "const badgePool = poolNameHTML(planSelected);" in page  # plan grid heading
    # The old always-plain span is gone from the cards.
    assert 'class="name">${esc(o.facility)}' not in page


def test_card_carries_a_one_line_detail_address_tel_and_official_link() -> None:
    """S3 #2: a compact one-line detail — address, a tel: phone link, and an official ↗ link —
    rides under each card, sourced from the joined catalog record."""
    page = _RENDERED_PAGE
    assert "function poolDetailHTML(name)" in page
    # Address, a tel: link (spaces stripped from the dialable number), and the official link.
    assert "if (info.address) parts.push(esc(info.address));" in page
    assert "<a href=\"tel:${esc(info.phone.replaceAll(' ', ''))}\">${esc(info.phone)}</a>" in page
    assert "official ↗" in page
    # A no-match facility yields '' (no detail line), never a broken row.
    assert "if (!info) return '';" in page
    # The detail line is emitted on Find, tourist, and plan renders.
    assert page.count("${poolDetailHTML(o.facility)}") == 2  # Find + tourist cards
    assert "poolDetailHTML(planSelected)" in page  # plan grid


def test_closed_and_uncurated_status_lines_carry_an_official_link() -> None:
    """S3 #6: the closed AND uncurated status lines join s.facility to the catalog and append
    an official link, so "we don't know its hours" resolves to "here's where to find out"."""
    page = _RENDERED_PAGE
    # A links helper feeds both non-open status branches.
    assert "function poolLinksHTML(name)" in page
    assert "const links = poolLinksHTML(s.facility);" in page
    # Both the closed and the uncurated branch interpolate the links.
    assert 'status closed">⊘ ${name} CLOSED — ${esc(s.detail)}${links}' in page
    assert "we just don't have its timetable.${links}" in page
    # The status name itself is also linked (the pool is a first-class object here too).
    assert "const name = poolNameHTML(s.facility);" in page


def test_directions_link_is_built_from_lat_lon_and_omitted_without_geo() -> None:
    """S3 #14: a 🗺 directions ↗ link is built from lat/lon (Google Maps directions), opening
    in a new tab, and omitted when geo is absent."""
    page = _RENDERED_PAGE
    assert "function directionsHTML(info)" in page
    # Built from lat/lon, only when both are present.
    assert "info && info.lat != null && info.lon != null" in page
    maps_url = (
        "https://www.google.com/maps/dir/?api=1&amp;destination=${esc(info.lat)},${esc(info.lon)}"
    )
    assert maps_url in page
    assert "🗺 directions ↗" in page
    # New tab + safe rel, and an empty string when geo is missing (no broken link).
    assert 'target="_blank" rel="noopener">🗺 directions ↗</a>' in page
    assert "    : '';" in page


def test_all_pool_object_links_are_new_tab_and_noopener_safe() -> None:
    """S3 safety: every outbound pool link (name, official, directions) opens in a new tab with
    rel=noopener, and dynamic values flow through esc()."""
    page = _RENDERED_PAGE
    # No target=_blank without a matching rel=noopener anywhere in the pool-object helpers.
    assert 'target="_blank">' not in page  # every new-tab anchor must also carry rel=noopener
    # The catalog url and geo are escaped at every interpolation.
    assert "${esc(info.url)}" in page
    assert "${esc(info.lat)},${esc(info.lon)}" in page


def test_provenance_stamp_uses_plain_language_not_dev_tokens() -> None:
    """S2 #5: the provenance stamp reports freshness + source in plain words. The developer
    ``(curated)/(scraped)/(mixed)`` tokens become "official schedule" / "read from the pool's
    website" / "mixed sources", and ``valid_as_of`` becomes "Schedule last checked {date}"."""
    page = _RENDERED_PAGE
    # Plain-language provenance phrases replace the raw curated/scraped/mixed tokens.
    assert "official schedule" in page
    assert "read from the pool's website" in page
    assert "mixed sources" in page
    # And the freshness wording is plain, not the API field name.
    assert "Schedule last checked" in page
    # The raw dev tokens no longer render as the provenance mode.
    assert "(curated)" not in page and "(scraped)" not in page and "(mixed)" not in page


def test_s4_card_hierarchy_leads_with_the_answer_not_the_filter() -> None:
    """S4 #7: the Find card is reordered so the eye lands on the ANSWER — the facility name is
    the hero, THEN the status pill + eligibility word, and the length badge is demoted to a
    small tag last, no longer the big left-hand hero column it was."""
    page = _RENDERED_PAGE
    # Scope to the optionCard function body (its own unique substrings).
    block = page[page.index("function optionCard(o)") : page.index("function statusLine")]
    # Order within the card: name (hero) -> status pill + eligibility -> length tag (demoted).
    assert block.index("cardname") < block.index("statusrow") < block.index("lenTagHTML(o)")
    # The name is the big hero; the old flex "badge column first" layout is gone.
    assert ".card .cardname { font-size: 1.15rem; font-weight: 700" in page
    assert "flex: 0 0 auto; min-width: 5.5rem" not in page  # old hero badge column removed
    assert ".lenbadge .len { font-size: 1.5rem" not in page  # old 1.5rem/700 length hero gone


def test_s4_open_vs_later_is_a_bold_colored_pill_not_opacity() -> None:
    """S4 #7: open-vs-later becomes a bold COLORED status pill (open = green, an upcoming window
    = amber), not the opacity-only treatment (which reads as disabled / washes out)."""
    page = _RENDERED_PAGE
    # A shared statePill helper, used by both the Find and tourist starter cards.
    assert "function statePill(o)" in page
    assert page.count("${statePill(o)}") == 2
    # Both states carry a background colour; neither is opacity-only anymore.
    assert ".state.open { background: var(--elig-in); }" in page
    assert ".state.upcoming { background: var(--elig-unk); }" in page
    assert ".state.upcoming { opacity" not in page  # the old opacity-only treatment is gone
    # The distinct open branch (with closing time) survives.
    assert "OPEN · closes" in page


def test_s4_eligibility_is_paired_with_a_plain_word() -> None:
    """S4 #7: the ✓/✗/? eligibility glyph is paired with a plain WORD derived (via eligAxis,
    which reads o.reason) from the option — "you're in" / "not for you" / "check" — so the
    signal does not rely on a single glyph."""
    page = _RENDERED_PAGE
    assert "function eligWord(o) { return ELIG_WORD[eligAxis(o).cls]; }" in page
    assert "in: \"you're in\", out: 'not for you', unk: 'check'" in page
    # The word rides beside the glyph on the card (Find + tourist).
    assert page.count("${esc(eligWord(o))}") == 2
    assert 'class="eligword' in page


def test_s4_access_word_is_sentence_cased_not_shouty() -> None:
    """S4 #7 (S2/S3 note): accessLabel returns shouty upper-case (LANE/PUBLIC); the card now
    sentence-cases it so it reads "Lane", not "LANE" — the glyph axis is kept for scanning."""
    page = _RENDERED_PAGE
    assert "const sentence = s =>" in page
    assert "${esc(sentence(accessLabel(o.access)))}" in page
    assert "axis-access" in page  # the scannable glyph is kept


def test_s4_length_lanes_badge_is_kept_but_demoted_to_a_small_tag() -> None:
    """S4 #7 / KEEP invariant: the length + lane badge is a real lap-swimmer filter, so it is
    KEPT — only its size/priority is demoted to a compact secondary tag. Lanes still render
    only when known (honest degrade), and the redundant `indoor` kind is dropped from the card."""
    page = _RENDERED_PAGE
    # The badge concept survives via a shared compact tag helper.
    assert "function lenTagHTML(o)" in page
    assert "o.length_m != null" in page  # length still shown
    assert "o.lanes != null" in page and "lane</span>" in page  # lanes only when known
    # Demoted styling: a small inline tag, not the old hero column.
    assert ".lenbadge { display: inline-block; font-family: var(--mono); font-size: .74rem" in page
    # The redundant `indoor` kind is no longer rendered on the Find card.
    block = page[page.index("function optionCard(o)") : page.index("function statusLine")]
    assert "o.kind" not in block


def test_s4_week_grid_scrolls_horizontally_on_a_phone() -> None:
    """S4 #9: the week grid is wrapped in an overflow-x:auto container with a sensible min-width
    so it stays a usable grid on a phone (persona 2 plans on mobile) rather than collapsing."""
    page = _RENDERED_PAGE
    # The render wraps the table in a scroll container that is opened and closed around it.
    assert '<div class="gridscroll"><table class="weekgrid">' in page
    assert "</tbody></table></div>" in page
    # The container scrolls horizontally; the grid keeps a sensible minimum width.
    assert ".gridscroll { overflow-x: auto;" in page
    assert "min-width: 40rem" in page


def test_s4_grid_cells_show_visible_times_not_hover_only() -> None:
    """S4 #9: session time ranges render as VISIBLE cell text (a .celltime span), not the
    title=-hover-only treatment that is invisible on touch. The glyphs stay for scannability
    and the full stacked-session detail stays in title=."""
    page = _RENDERED_PAGE
    # The visible time range is rendered as cell text, from the session's own start/end.
    assert '<span class="celltime">${esc(o.start)}–${esc(o.end)}</span>' in page
    assert ".weekgrid .celltime { display: block;" in page
    # The scannable glyph pair is still there, and the hover title is kept for full detail.
    assert '<span class="cellglyphs">' in page
    assert '<td title="${esc(title)}">' in page


def test_s5_all_pools_fetches_pools_once_via_the_memoized_path() -> None:
    """S5 debt paydown: the All-pools tab no longer runs its own `await fetch('/pools')`; it
    folds onto the memoized loadPoolsData() so /pools is fetched at most once for the whole page.
    The only raw /pools fetch that survives is the guarded memoization inside loadPoolsData."""
    page = _RENDERED_PAGE
    # The single memoization site remains; no other raw /pools fetch exists.
    assert "if (!poolsPromise) poolsPromise = fetch('/pools')" in page
    assert page.count("fetch('/pools')") == 1
    # loadPools consumes the memoized catalog, not a fresh fetch (and no longer a second
    # /swim call to guess the scheduled set — S3 retired that name-join).
    assert "async function loadPools()" in page
    assert "const a = await loadPoolsData();" in page


def test_s5_schedule_indicator_reads_curation_from_the_api_not_by_name() -> None:
    """S3: each All-pools row carries a schedule indicator read from the API's `curated` flag
    (the store's derived curation_status on /pools), NOT guessed by name-matching a second /swim
    call. The retired name-join (`loadScheduledFacilities`/`scheduledPools`) is gone; a pool
    without a timetable reads "location only — no timetable yet" (honest per invariant #1),
    never "closed"."""
    page = _RENDERED_PAGE
    # The name-join workaround is retired entirely — no /swim call, no name-matched set.
    assert "loadScheduledFacilities" not in page
    assert "scheduledPools" not in page
    # Curation is read straight from the /pools record's `curated` flag.
    assert "const scheduled = p.curated;" in page
    assert "scheduledCount = (a.pools || []).filter(p => p.curated).length;" in page
    # The row renders the two honest states — ✓ schedule vs. location-only (never "closed").
    assert "✓ schedule" in page
    assert "location only — no timetable yet" in page
    assert "<th>Schedule</th>" in page


def test_s5_name_filter_narrows_the_all_pools_list() -> None:
    """S5 #13: a client-side name filter box sits above the list and narrows the rendered rows
    via a case-insensitive `includes` on p.name — the same box is the jump-to-schedule entry."""
    page = _RENDERED_PAGE
    # The filter input exists above the results.
    assert 'id="poolFilter"' in page
    assert page.index('id="poolFilter"') < page.index('id="allOut"')
    # Its handler lower-cases the query and re-renders; the render filters by includes on name.
    assert "nameFilter = e.target.value.trim().toLowerCase();" in page
    assert "items = items.filter(p => p.name.toLowerCase().includes(nameFilter));" in page


def test_s5_scheduled_rows_wire_a_jump_to_the_plan_tab() -> None:
    """S5 #11: rows WITH a schedule carry a "Plan ›" button that switches to the Plan tab and
    asks the planner to preselect that pool; the plan's submit consumes the pending preselect."""
    page = _RENDERED_PAGE
    # The action button and its wiring.
    assert 'class="jump" data-pool="${esc(p.name)}">Plan ›</button>' in page
    assert "b.addEventListener('click', () => jumpToPlan(b.dataset.pool))" in page
    # The jump switches tabs and stores the pending selection.
    assert "function jumpToPlan(facility)" in page
    assert "planPreselect = facility;" in page
    assert "activateTab('plan');" in page
    # The planner honours the pending preselect when the pool resolves within place/radius.
    preselect = (
        "if (planPools.some(p => p.facility === planPreselect)) planSelected = planPreselect;"
    )
    assert preselect in page


def test_s6_one_shared_context_bar_above_the_tabs_drives_every_tab() -> None:
    """S6 #12: place/gender/age/radius are lifted into ONE persistent context bar (``#ctx``)
    ABOVE the tabs. The three per-tab forms no longer duplicate these fields — each shared
    field name appears exactly once (in the bar) — and every tab reads them via ``ctxState()``."""
    page = _RENDERED_PAGE
    # A single shared context bar, positioned above the tab nav.
    assert '<form id="ctx" class="ctxbar">' in page
    assert page.index('<form id="ctx"') < page.index("<nav>")
    # The four shared inputs live ONCE (the old Find/Plan/Tourist duplication is gone).
    assert page.count('name="place"') == 1
    assert page.count('name="radius_km"') == 1
    assert page.count('name="gender"') == 1
    assert page.count('name="age"') == 1
    # A single reader helper exposes the shared state as {lat, lon, gender, age, radius_km}.
    assert "function ctxState()" in page
    assert "const [lat, lon] = ctx.place.value.split(',');" in page
    assert (
        "return { lat, lon, gender: ctx.gender.value, age: ctx.age.value,"
        " radius_km: ctx.radius_km.value };" in page
    )
    # All three query tabs consume the shared state (Find, Plan, Tourist each call ctxState()).
    assert page.count("const c = ctxState();") == 3


def test_s6_find_keeps_only_its_when_control_place_moves_to_the_bar() -> None:
    """S6 #12: Find's own form keeps only its tab-specific controls (When + the eligible
    toggle); it no longer carries place/gender/age/radius — those come from the shared bar,
    and Find now passes the bar's lat/lon so its cards gain distance."""
    page = _RENDERED_PAGE
    # Find's form still owns "When" and the eligible toggle.
    assert '<input type="datetime-local" name="at" required>' in page
    assert 'name="eligible_only"' in page
    # Find now sources place/gender/age/radius from the shared context, not a per-tab field.
    find = page[page.index("f.addEventListener('submit'") : page.index("// access legend")]
    assert "const c = ctxState();" in find
    assert "p.append('lat', c.lat); p.append('lon', c.lon);" in find
    assert "if (c.gender) p.append('gender', c.gender);" in find


def test_s6_changing_shared_context_reruns_the_active_tab_continuing_the_session() -> None:
    """S6 #12: switching tabs carries the shared inputs (they are never re-entered per tab),
    and changing any shared input re-runs whichever tab is active — the session CONTINUES
    rather than resetting."""
    page = _RENDERED_PAGE
    # The active tab is tracked and a shared-context change re-runs it.
    assert "let activeTab = 'find';" in page
    assert "activeTab = tab;" in page  # activateTab records the current tab
    assert "ctx.addEventListener('change', rerunActiveTab);" in page
    assert "function rerunActiveTab()" in page
    # Each query tab is re-run through its own runner when it is the active one.
    find_rerun = (
        "if (activeTab === 'find') { if (findLoaded) f.dispatchEvent(new Event('submit')); }"
    )
    assert find_rerun in page
    assert "else if (activeTab === 'plan') { if (planLoaded) runPlan(); }" in page
    assert "else if (activeTab === 'visit') { if (visitLoaded) runVisit(); }" in page
    # Plan and Tourist became context-driven runners (no per-tab submit form remains).
    assert "async function runPlan()" in page
    assert "async function runVisit()" in page


def test_s6_footer_is_consolidated_and_coverage_line_is_neutral_not_amber() -> None:
    """S6 #10: the trailing meta-stack (provenance stamp + a separate amber "Only 7 of ~57"
    ``.warn`` banner) is consolidated into ONE footer per tab, and the amber banner is demoted
    to a NEUTRAL data-coverage line that reuses the real ``catalogCount`` + scheduled set."""
    page = _RENDERED_PAGE
    # One footer helper folds provenance + coverage together, used on Find and Tourist.
    assert "function footerHTML(options) { return provStamp(options) + coverageHTML(); }" in page
    assert page.count("footerHTML(a.options)") == 2  # Find + Tourist
    # The coverage line is NEUTRAL (a muted line, never the amber .warn class) and honest.
    assert "function coverageHTML()" in page
    assert '<div class="coverage muted">' in page
    assert "which is not the same as closed." in page
    assert ".coverage { margin-top:" in page  # its own neutral style exists
    # It reuses the REAL counts, not a hardcoded number — the curated-timetable count and the
    # catalog size, both from the one /pools read (no second /swim name-join).
    assert "${scheduledCount} of ~${catalogCount}" in page
    assert "if (catalogCount == null) return '';" in page
    # The old amber "Only 7 of ~57 …" .warn banner is gone.
    assert "Only 7 of ~57" not in page
    assert 'class="warn">⚠ Only' not in page


def test_s6_tourist_tab_is_kept_not_demoted_onboarding_preserved() -> None:
    """S6 #15 DECISION: keep the "First time here?" tab rather than demoting it to a
    collapsible "New here? ▸" panel on Find. The tourist tab carries onboarding the Find tab
    does not (the plain-language primer, distinct starter pools, the inline decode, and the
    kept-visible closed pools); demoting it would regress newcomer onboarding, so — per the
    plan's "prefer keeping the tab unless demotion is clearly a net win" — it stays a tab."""
    page = _RENDERED_PAGE
    # The tourist tab survives as a first-class tab (four tabs total, in the nav spine).
    assert 'data-tab="visit"' in page
    assert "First time here?" in page
    assert '<section id="visit">' in page
    assert page.count("data-tab=") == 4  # Find · Plan · First-time · All-pools
    # The onboarding the tab exists FOR is intact: primer, distinct starters, inline decode.
    assert 'id="primer"' in page
    assert "renderPrimer(a.options)" in page
    assert "[...byFacility.values()].slice(0, 3)" in page
    assert "This slot is <b>" in page
    # The rejected demotion artifact ("New here? ▸" panel on Find) was NOT built.
    assert "New here? ▸" not in page
