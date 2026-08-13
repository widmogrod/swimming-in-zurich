"""Pins the private-operator closure extractor against a saved page.

The fixture is a real `bad-altstetten.ch` snapshot and happens to carry the operator's two
*different* announcement grammars at once — a stale 2025 one and the live 2026 one — which is
exactly the variance a page-wide date scan would get wrong.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from swimzh.domain.closure import ClosureCode
from swimzh.providers.operator_pages import parse_maintenance_closures

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_ALTSTETTEN = FIXTURES / "hallenbad_altstetten.html"


def test_extracts_both_announcement_grammars() -> None:
    """`30. Juli – Sonntag, 16. August 2026` (year stated once, at the end) and
    `28. Juli 2025 bis Sonntag,17. August 2025` (year on both, `bis`, no space after comma)."""
    closures = parse_maintenance_closures(FIXTURE_ALTSTETTEN.read_text(encoding="utf-8"))

    assert [(c.start, c.end) for c in closures] == [
        (date(2025, 7, 28), date(2025, 8, 17)),
        (date(2026, 7, 30), date(2026, 8, 16)),
    ]


def test_closure_is_classified_as_maintenance_not_unmapped() -> None:
    """The reason is the German keyword, so the EXISTING `classify_closure` table maps it —
    this module deliberately does not carry a second closure vocabulary."""
    closures = parse_maintenance_closures(FIXTURE_ALTSTETTEN.read_text(encoding="utf-8"))

    assert closures
    assert all(c.code is ClosureCode.MAINTENANCE for c in closures)


def test_the_live_shutdown_covers_a_date_inside_it() -> None:
    """The regression this whole slice exists for: on 2 August 2026 the store said the pool
    was open 08:00-18:00 while the operator was announcing an 18-day shutdown."""
    closures = parse_maintenance_closures(FIXTURE_ALTSTETTEN.read_text(encoding="utf-8"))

    covering = [c for c in closures if c.contains(date(2026, 8, 2))]
    assert len(covering) == 1
    assert covering[0].start == date(2026, 7, 30)
    assert covering[0].end == date(2026, 8, 16)


def test_a_page_with_no_maintenance_notice_yields_nothing() -> None:
    """A normal outcome, not an error: most of the year there is no Revision announced."""
    assert parse_maintenance_closures("<html><body><p>Wir haben offen.</p></body></html>") == ()


def test_date_ranges_far_from_a_maintenance_keyword_are_ignored() -> None:
    """Section-anchoring is the whole safety property. These pages carry unrelated ranges
    (events, courses, restaurant weeks); a page-wide scan would return one of those."""
    page = "<p>Sommerfest 3. Juli – 9. Juli 2026.</p>" + ("<p>fill</p>" * 200) + "<p>Revision</p>"

    assert parse_maintenance_closures(page) == ()


def test_an_impossible_date_is_dropped_rather_than_guessed() -> None:
    page = "<p>Revision 31. Februar 2026 bis 5. März 2026</p>"

    assert parse_maintenance_closures(page) == ()


def test_a_reversed_range_is_dropped() -> None:
    page = "<p>Revision 16. August 2026 bis 30. Juli 2026</p>"

    assert parse_maintenance_closures(page) == ()


def test_betriebsferien_classifies_as_operational_break() -> None:
    page = "<p>Betriebsferien 24. Dezember 2026 bis 2. Januar 2027</p>"

    closures = parse_maintenance_closures(page)

    assert len(closures) == 1
    assert closures[0].code is ClosureCode.OPERATIONAL_BREAK
    assert closures[0].start == date(2026, 12, 24)
    assert closures[0].end == date(2027, 1, 2)
