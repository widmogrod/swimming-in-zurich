"""Scrape the central admission-price page into a domain PriceTable.

Zürich pool admission is a single city-wide tariff, published once (not per pool). The
`Einzeleintritte` (single-entry) row gives adult / reduced / child prices; we map those to
a PriceTable applied to city-run pools. Same embedded-JSON-table format as the pool pages.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from decimal import Decimal

from swimzh.core.errors import ParseError, ProviderError
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.pricing import PriceCategory, PriceEntry, PriceTable

_SOURCE = "price_scraper"

PRICES_URL = (
    "https://www.stadt-zuerich.ch/web/de/stadtleben/sport-und-erholung/"
    "sport-und-badeanlagen/preise-abos.html"
)

_ROW_RE = re.compile(r'\[\{"value":"(?:[^"\\]|\\.)*"\}(?:,\{"value":"(?:[^"\\]|\\.)*"\})*\]')


def _text(cell_html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell_html)).strip()


def _money(cell: str) -> Decimal | None:
    token = cell.replace("Fr.", "").replace("\xa0", " ").strip()
    match = re.match(r"(\d+)(?:[.,](\d{2}|–|-))?", token)
    if match is None:
        return None
    fraction = match.group(2)
    cents = "00" if fraction in (None, "–", "-") else fraction
    return Decimal(f"{match.group(1)}.{cents}")


def parse_prices(page_html: str, valid_as_of: date) -> Result[PriceTable, ProviderError]:
    decoded = html.unescape(page_html)
    rows: list[list[str]] = []
    for match in _ROW_RE.findall(decoded):
        try:
            rows.append([_text(c["value"]) for c in json.loads(match)])
        except json.JSONDecodeError:
            continue

    single = next((r for r in rows if len(r) >= 4 and "einzeleintritt" in r[0].lower()), None)
    if single is None:
        return Err(
            ParseError(
                source=_SOURCE, detail="Einzeleintritte row not found", raw_snippet=decoded[:200]
            )
        )
    adult, reduced, child = _money(single[1]), _money(single[2]), _money(single[3])
    if adult is None or reduced is None or child is None:
        return Err(
            ParseError(source=_SOURCE, detail=f"unparseable prices: {single}", raw_snippet="")
        )

    entries = (
        PriceEntry(PriceCategory.ADULT, adult, f"Erwachsene Fr. {adult}"),
        PriceEntry(PriceCategory.YOUTH, reduced, f"Jugendliche/ermässigt Fr. {reduced}"),
        PriceEntry(PriceCategory.SENIOR, reduced, f"Senior:innen/ermässigt Fr. {reduced}"),
        PriceEntry(PriceCategory.CHILD, child, f"Kinder Fr. {child}"),
    )
    return Ok(PriceTable(entries=entries, valid_as_of=valid_as_of, source_url=PRICES_URL))


def scrape_prices(client: HttpClient, valid_as_of: date) -> Result[PriceTable, ProviderError]:
    match client.get(PRICES_URL):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return parse_prices(resp.content.decode("utf-8", "replace"), valid_as_of)
