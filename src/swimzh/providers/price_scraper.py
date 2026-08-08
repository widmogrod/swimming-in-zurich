"""Scrape the central admission-price page into the city's admission tariffs.

Zürich pool admission is published once for the whole city (not per pool), and the page prints
**two** single-entry rates: the general `Einzeleintritte` row at the top, and a separate
`Einzeleintritt` under the `Eintritte Schulschwimmanlagen` section — the rate the city charges at
a Schulschwimmanlage. `parse_prices` returns both as a `CityTariffs` pair; `etl.scrape.tariff_for`
picks the one a given pool is served.

*Whether* the city tariff governs a pool at all is likewise a page-stated fact, not a hostname:
`states_city_tariff` reports whether a pool's own page links this tariff page.

Both rows are taken from the **same** `<stzh-datatable>` element — the one carrying the
`Eintritte Schulschwimmanlagen` section — because a row means nothing without the column headers
printed above it, and the page carries two elements (summer + winter) whose leading
`Einzeleintritte` rows look alike. Mixing one row from each would silently mix two header sets.

Row selection is **section-anchored**, not positional: three rows in that element begin with
`Einzeleintritt` (general, school, and the sauna's Fr. 12.– surcharge), so "the first match" is
correct only by accident of row order. A grouping row — one whose price cells are all blank —
opens a section; a row's section is the last grouping row above it, or `None` for the leading rows.
Same embedded-JSON-table format as the pool pages.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import NamedTuple
from urllib.parse import urlsplit

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

#: The tariff page's own path tail — the tail, never the whole URL. Across the committed pool-page
#: fixtures the link is written 22× RELATIVE (`/web/de/stadtleben/…/preise-abos.html`) and once
#: ABSOLUTE (`https://www.stadt-zuerich.ch/de/stadtleben/…/preise-abos.html`): the two disagree on
#: `web/de/` vs `de/`, so equality with `PRICES_URL` would recognise neither reliably.
#: Leading slash included deliberately: a bare tail would also match a GLUED segment such as
#: `/foo/xsport-und-badeanlagen/preise-abos.html`, which is a different page.
_TARIFF_PATH_TAIL = "/sport-und-badeanlagen/preise-abos.html"
#: Any `href`, single- or double-quoted. Matched on the RAW page for the same reason the table
#: attributes are: the document's own attribute boundaries are what delimit a URL.
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

#: The TIGHT free-admission sentence four pool pages print ("Der Eintritt ins Flussbad Au-Höngg
#: ist gratis"), plus the ANCHORED "Gratisbad" predication ("Tagsüber ist es ein Gratisbad" —
#: the privately run Männerbad). Deliberately NOT bare `gratis`: the Ausstattung/locker rows
#: print it on 21 of the 26 declared pages ("Garderobenkasten … gratis", "gratis, plus Depot
#: Fr. 5.–"), so a loose match would declare almost every priced pool free. And NOT bare
#: `Gratisbad` either: the page must PREDICATE it of itself ("ist [es] ein Gratisbad"), so a mere
#: mention of another facility's Gratisbad can never assert this pool free. `[^.<]` keeps the
#: sentence arm inside one sentence and one text node.
_FREE_SENTENCE_RE = re.compile(
    r"Der Eintritt[^.<]{0,80}ist\s+gratis|ist\s+(?:es\s+)?ein\s+Gratisbad"
)

#: The section heading (a grouping row) under which the city prints the Schulschwimmanlage rate.
_SCHOOL_SECTION = "eintritte schulschwimmanlagen"
#: Both tariff rows are labelled `Einzeleintritte` / `Einzeleintritt`.
_SINGLE_ENTRY = "einzeleintritt"


@dataclass(frozen=True, slots=True)
class CityTariffs:
    """The two single-admission rates the city publishes, read from one table.

    `general` is the unsectioned `Einzeleintritte` row (every city pool); `school` is the row
    under `Eintritte Schulschwimmanlagen` (the 4 Schulschwimmanlagen that open to the public).
    Both share the element's column headers, hence the same published age bounds.
    """

    general: PriceTable
    school: PriceTable


def states_city_tariff(page_html: str) -> bool:
    """Does this pool's own page state that the city tariff governs it — by LINKING that tariff?

    The binding is a link the upstream page emits and we re-derive every run, not a curated host
    list that rots when a WFS URL drifts ([[discovery-driven-providers]] rule 2). It is also the
    only correct discriminator: 4 of the pools on the city's own `sportamt.ch` pages publish *"Der
    Eintritt … ist gratis"* and `maennerbad-schanzengraben` *"wird privat betrieben"*, so a
    host-keyed fan-out would invent a Fr. 8.00 charge at pools the city publishes as free.

    Matched on the URL's **path tail** (`_TARIFF_PATH_TAIL`), not on a substring of the whole href:
    `hallenbad-altstetten` (a private operator) carries 9 hrefs containing `preise` across 3
    targets of its own (`/schwimmen-2#preise`, `/schwimmen-2#schwimmpreise`, `/sauna#saunapreise`)
    and states no city tariff.
    """
    return any(
        urlsplit(html.unescape(match.group(1))).path.endswith(_TARIFF_PATH_TAIL)
        for match in _HREF_RE.finditer(page_html)
    )


def states_free_admission(page_html: str) -> bool:
    """Does this pool's own page STATE that admission is free?

    The page-stated fact, read from the tight sentence only (`_FREE_SENTENCE_RE`): *"Der
    Eintritt … ist gratis"* or *"… ein Gratisbad"*. Never inferred from a missing tariff link,
    a hostname, or a kind — and never from a bare `gratis`, which the locker/Ausstattung rows
    print on most priced pages ("Garderobenkasten … gratis").
    """
    return _FREE_SENTENCE_RE.search(page_html) is not None


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


class _Tariffed(NamedTuple):
    """One `<stzh-datatable>`'s headers plus the two single-entry rows read out of it."""

    headers: list[str]
    general: list[str]
    school: list[str]


def _sectioned(rows: list[list[str]]) -> list[tuple[str | None, list[str]]]:
    """Pair each priced row with the section heading above it (`None` for the leading rows).

    A grouping row is one whose price cells are all blank — it opens a section and carries no
    price of its own.
    """
    section: str | None = None
    out: list[tuple[str | None, list[str]]] = []
    for row in rows:
        if len(row) < 4:
            continue
        if not any(cell for cell in row[1:]):
            section = row[0]
            continue
        out.append((section, row))
    return out


def _single_entry_row(
    sectioned: list[tuple[str | None, list[str]]], section: str | None
) -> list[str] | None:
    """The `Einzeleintritt*` row under exactly `section` — matched by heading, not by row order."""
    for row_section, row in sectioned:
        matches = row_section is None if section is None else _in_section(row_section, section)
        if matches and row[0].lower().startswith(_SINGLE_ENTRY):
            return row
    return None


def _in_section(row_section: str | None, section: str) -> bool:
    return row_section is not None and row_section.lower() == section


def _tariff_table(page_html: str) -> _Tariffed | None:
    """The ONE `<stzh-datatable>` carrying the school section, with both its tariff rows.

    Scoped per element: the page carries two (summer + winter) whose leading `Einzeleintritte`
    rows are identical, and only the first has a school section. Taking one row from each would
    silently mix two header sets, so a table without the school section is skipped entirely.
    """
    for chunk in page_html.split(_TABLE_SPLIT)[1:]:
        columns, rows = _COLUMNS_ATTR.search(chunk), _ROWS_ATTR.search(chunk)
        if columns is None or rows is None:
            continue
        headers, decoded = _headers(columns.group(1)), _cells(rows.group(1))
        if headers is None or decoded is None or len(headers) < 4:
            continue
        sectioned = _sectioned(decoded)
        general = _single_entry_row(sectioned, None)
        school = _single_entry_row(sectioned, _SCHOOL_SECTION)
        if general is not None and school is not None:
            return _Tariffed(headers=headers, general=general, school=school)
    return None


def _price_table(
    headers: list[str], row: list[str], valid_as_of: date
) -> Result[PriceTable, ProviderError]:
    entries: list[PriceEntry] = []
    for index, category in enumerate(_COLUMN_CATEGORIES, start=1):
        header, amount = headers[index], _money(row[index])
        bound = _MIN_AGE_RE.search(header)
        if amount is None or bound is None:
            # Fail rather than serve an amount we cannot attach to an age. A price without its
            # published bound is exactly the guess this parser exists to stop making.
            return Err(
                ParseError(
                    source=_SOURCE,
                    detail=f"unbounded or unparseable price column: {header!r} / {row[index]!r}",
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


def parse_prices(page_html: str, valid_as_of: date) -> Result[CityTariffs, ProviderError]:
    """Both published single-admission tariffs, or a typed `ParseError`.

    A page that states no school section is an `Err`, never a silent fallback that serves the
    Hallenbad rate at a Schulschwimmanlage — the defect this parser exists to stop making.
    """
    found = _tariff_table(page_html)
    if found is None:
        return Err(
            ParseError(
                source=_SOURCE,
                detail=(
                    "no <stzh-datatable> carrying both an unsectioned Einzeleintritte row and an "
                    f"{_SCHOOL_SECTION!r} one"
                ),
                raw_snippet=page_html[:200],
            )
        )
    general = _price_table(found.headers, found.general, valid_as_of)
    if isinstance(general, Err):
        return general
    school = _price_table(found.headers, found.school, valid_as_of)
    if isinstance(school, Err):
        return school
    return Ok(CityTariffs(general=general.value, school=school.value))


def scrape_prices(client: HttpClient, valid_as_of: date) -> Result[CityTariffs, ProviderError]:
    match client.get(PRICES_URL):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return parse_prices(resp.content.decode("utf-8", "replace"), valid_as_of)
