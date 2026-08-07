"""Admission-price scraper tested against the saved real central price page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

from swimzh.core.errors import HttpStatus, ParseError
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.pricing import PriceCategory
from swimzh.providers.price_scraper import parse_prices, scrape_prices

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "preise_abos.html"
AS_OF = date(2026, 7, 19)


def _page() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parses_admission_prices() -> None:
    result = parse_prices(_page(), AS_OF)
    assert isinstance(result, Ok), result
    amounts = {e.category: e.amount_chf for e in result.value.general.entries}
    assert amounts[PriceCategory.ADULT] == Decimal("8.00")
    assert amounts[PriceCategory.YOUTH] == Decimal("6.00")
    assert amounts[PriceCategory.CHILD] == Decimal("4.00")
    assert result.value.general.source_url
    assert result.value.general.valid_as_of == AS_OF


def test_parses_the_published_age_bounds_from_the_column_headers() -> None:
    """The page prints its own bands; three columns, three entries, no invented senior rate."""
    result = parse_prices(_page(), AS_OF)
    assert isinstance(result, Ok), result
    assert [(e.min_age, e.amount_chf) for e in result.value.general.entries] == [
        (20, Decimal("8.00")),
        (16, Decimal("6.00")),
        (6, Decimal("4.00")),
    ]
    # The bound reaches the reader, not just the resolver.
    assert result.value.general.entries[0].display == "Erwachsene (ab 20 J.) Fr. 8.00"


def test_the_school_section_is_read_as_its_own_tariff() -> None:
    """The city prints a separate Schulschwimmanlagen rate; it is no longer skipped over.

    The school row shares the general row's column headers (same `<stzh-datatable>`), so the
    published bounds are identical and only the amounts differ.
    """
    result = parse_prices(_page(), AS_OF)
    assert isinstance(result, Ok), result
    assert [(e.min_age, e.amount_chf) for e in result.value.school.entries] == [
        (20, Decimal("5.00")),
        (16, Decimal("5.00")),
        (6, Decimal("2.50")),
    ]
    assert result.value.school.entries[2].display == "Kinder (ab 6 J.) Fr. 2.50"
    assert result.value.school.valid_as_of == AS_OF


def _without_school_section(page: str) -> str:
    """Drop the `Eintritte Schulschwimmanlagen` grouping row from the escaped `rows="…"` payload.

    Deleting the HEADING (not the priced row under it) is the honest simulation of the page
    dropping the section: the rate row would then read as just another `Einzeleintritt`.
    """
    q = "&#34;"  # the fixture escapes the JSON payload's quotes
    heading = f"{{{q}value{q}:{q}&lt;strong>Eintritte Schulschwimmanlagen&lt;/strong>{q}}}"
    blank = f",{{{q}value{q}:{q}\xa0{q}}}"  # the page fills a grouping row's cells with nbsp
    row = f"[{heading}{blank * 3}],"
    assert row in page, "fixture no longer carries the school grouping row verbatim"
    return page.replace(row, "", 1)


def test_a_page_without_the_school_section_is_a_parse_error() -> None:
    """A missing school tariff is refused, never silently served as the general (Hallenbad) one.

    This — not an amount assertion — is what proves the anchoring: the amounts parse identically
    under a first-match-wins parser that has no notion of sections at all.
    """
    result = parse_prices(_without_school_section(_page()), AS_OF)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_both_tariffs_come_from_the_same_datatable_element() -> None:
    """The page carries two `<stzh-datatable>`s (summer + winter) with identical headers and an
    identical leading `Einzeleintritte 8/6/4` row; only the first has a school section. With the
    first element removed the parser must FAIL rather than fall through to the winter table and
    pair its general row with nothing."""
    page = _page()
    first, second = (
        page.index("<stzh-datatable"),
        page.index("<stzh-datatable", page.index("<stzh-datatable") + 1),
    )
    winter_only = page[:first] + page[second:]
    assert winter_only.count("<stzh-datatable") == 1
    assert "Eintritte Schulschwimmanlagen" not in winter_only
    result = parse_prices(winter_only, AS_OF)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_an_unreadable_school_amount_fails_rather_than_serving_the_general_rate() -> None:
    """The school row parses independently of the general one: if the city ever prints a word
    where a franc amount belongs, that is an `Err`, not a silent fall-back to Fr. 8.–."""
    page = _page().replace("&#34;Fr. 2.50&#34;", "&#34;gratis&#34;", 1)
    assert "gratis" in page, "fixture no longer carries the school child amount verbatim"
    result = parse_prices(page, AS_OF)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_a_column_with_no_published_bound_is_a_parse_error() -> None:
    """An amount we cannot attach to an age is refused, not stored under a guessed band."""
    page = _page().replace("Erwachsene (ab 20 J.)", "Erwachsene")
    result = parse_prices(page, AS_OF)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_missing_price_row_is_parse_error() -> None:
    result = parse_prices("<html>no prices</html>", AS_OF)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="price_scraper", retry=RetryPolicy(max_attempts=1))


def test_scrape_prices_fetches_and_parses() -> None:
    body = FIXTURE.read_bytes()
    result = scrape_prices(_client(lambda _r: httpx.Response(200, content=body)), AS_OF)
    assert isinstance(result, Ok)


def test_scrape_prices_http_error_propagates() -> None:
    result = scrape_prices(_client(lambda _r: httpx.Response(500, text="x")), AS_OF)
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)
