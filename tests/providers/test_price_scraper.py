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


def test_parses_admission_prices() -> None:
    result = parse_prices(FIXTURE.read_text(encoding="utf-8"), AS_OF)
    assert isinstance(result, Ok), result
    amounts = {e.category: e.amount_chf for e in result.value.entries}
    assert amounts[PriceCategory.ADULT] == Decimal("8.00")
    assert amounts[PriceCategory.YOUTH] == Decimal("6.00")
    assert amounts[PriceCategory.CHILD] == Decimal("4.00")
    assert result.value.source_url
    assert result.value.valid_as_of == AS_OF


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
