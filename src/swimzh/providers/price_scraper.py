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

# Element-scoped, and read off the RAW page. Both payloads are HTML-ESCAPED attributes, so
# unescaping the document first would put bare `"` inside them and destroy the very attribute
# boundaries this matches on — the same trap the schedule scraper documents.
_TABLE_SPLIT = "<stzh-datatable"
_COLUMNS_ATTR = re.compile(r'\scolumns="([^"]*)"')
_ROWS_ATTR = re.compile(r'\srows="([^"]*)"')
# "Erwachsene (ab 20 J.)" — the tariff printing its own lower bound.
_MIN_AGE_RE = re.compile(r"\bab\s+(\d{1,2})\s*J", re.IGNORECASE)

# The `Einzeleintritte` row is `Ticketart | Erwachsene | Jugendliche | Kinder`; the header at
# each index carries that column's published bound. Position fixes only the CATEGORY LABEL —
# every age bound is read from the header, never assumed here.
_COLUMN_CATEGORIES = (PriceCategory.ADULT, PriceCategory.YOUTH, PriceCategory.CHILD)


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


def _cells(attr_value: str) -> list[list[str]] | None:
    """Decode one escaped `rows="…"` attribute into rows of plain cell text."""
    try:
        payload = json.loads(html.unescape(attr_value))
    except json.JSONDecodeError:
        return None
    return [[_text(str(cell.get("value", ""))) for cell in row] for row in payload]


def _headers(attr_value: str) -> list[str] | None:
    try:
        payload = json.loads(html.unescape(attr_value))
    except json.JSONDecodeError:
        return None
    return [_text(str(column.get("text", ""))) for column in payload]


def _single_entry_table(page_html: str) -> tuple[list[str], list[str]] | None:
    """The `Einzeleintritte` row WITH the headers of its own table.

    Scoped per `<stzh-datatable>` element: the page carries several, and a row means nothing
    without the column bounds printed above it.
    """
    for chunk in page_html.split(_TABLE_SPLIT)[1:]:
        columns, rows = _COLUMNS_ATTR.search(chunk), _ROWS_ATTR.search(chunk)
        if columns is None or rows is None:
            continue
        headers, decoded = _headers(columns.group(1)), _cells(rows.group(1))
        if headers is None or decoded is None:
            continue
        for row in decoded:
            if len(row) >= 4 and len(headers) >= 4 and "einzeleintritt" in row[0].lower():
                return headers, row
    return None


def parse_prices(page_html: str, valid_as_of: date) -> Result[PriceTable, ProviderError]:
    found = _single_entry_table(page_html)
    if found is None:
        return Err(
            ParseError(
                source=_SOURCE,
                detail="Einzeleintritte row not found",
                raw_snippet=page_html[:200],
            )
        )
    headers, single = found

    entries: list[PriceEntry] = []
    for index, category in enumerate(_COLUMN_CATEGORIES, start=1):
        header, amount = headers[index], _money(single[index])
        bound = _MIN_AGE_RE.search(header)
        if amount is None or bound is None:
            # Fail rather than serve an amount we cannot attach to an age. A price without its
            # published bound is exactly the guess this parser exists to stop making.
            return Err(
                ParseError(
                    source=_SOURCE,
                    detail=f"unbounded or unparseable price column: {header!r} / {single[index]!r}",
                    raw_snippet="",
                )
            )
        entries.append(
            PriceEntry(
                category=category,
                amount_chf=amount,
                display=f"{header} Fr. {amount}",
                min_age=int(bound.group(1)),
            )
        )
    return Ok(PriceTable(entries=tuple(entries), valid_as_of=valid_as_of, source_url=PRICES_URL))


def scrape_prices(client: HttpClient, valid_as_of: date) -> Result[PriceTable, ProviderError]:
    match client.get(PRICES_URL):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return parse_prices(resp.content.decode("utf-8", "replace"), valid_as_of)
