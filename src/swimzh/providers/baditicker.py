"""The Baditicker provider: live water temperature per Zürich bath from the OGD feed.

`GET https://www.stadt-zuerich.ch/stzh/bathdatadownload` returns one XML record per bath
(`title`, `temperatureWater`, `poiid`, `dateModified`, `openClosedTextPlain`, …). The feed is
open OGD (no ToS gate). Parsing follows the house provider style — defensive regex extraction
over the flat markup (like `schedule_scraper`/`price_scraper`), never an XML library, so there
is no external-entity/billion-laughs surface to guard.

Error mapping:
  * transport / non-2xx / timeout    -> already a `ProviderError` from `HttpClient`
  * bytes that are not UTF-8 text     -> `ParseError`
  * text with no `<baths>` / a bath
    with no `<poiid>`                  -> `SchemaMismatch`
  * a non-numeric temp / unparseable
    `dateModified`                     -> `ParseError`
  * empty `<temperatureWater>` cell    -> `celsius=None` (NOT an error — measured nothing yet)

`BaditickerProvider` implements the `TemperatureProvider` port (`read(poiid) -> Result[...]`)
with a short TTL cache: one upstream `fetch`+`parse` populates a `poiid -> TempReading` map that
is reused for the TTL window, so many per-request `/pools/{id}` reads cause a single fetch. The
clock and `HttpClient` are injected so the cache is deterministic under test (no real sleeping).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from swimzh.core.errors import ParseError, ProviderError, ProviderSpecific, SchemaMismatch
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok, Result
from swimzh.domain.query import TempReading

_SOURCE = "baditicker"
_ZURICH = ZoneInfo("Europe/Zurich")

FEED_URL = "https://www.stadt-zuerich.ch/stzh/bathdatadownload"

_DEFAULT_TTL = timedelta(seconds=120)

type Clock = Callable[[], datetime]

_BATH_RE = re.compile(r"<bath\b[^>]*>(.*?)</bath>", re.IGNORECASE | re.DOTALL)
_POIID_RE = re.compile(r"<poiid\b[^>]*>(.*?)</poiid>", re.IGNORECASE | re.DOTALL)
_TEMP_RE = re.compile(
    r"<temperatureWater\b[^>]*>(.*?)</temperatureWater>", re.IGNORECASE | re.DOTALL
)
_DATE_RE = re.compile(r"<dateModified\b[^>]*>(.*?)</dateModified>", re.IGNORECASE | re.DOTALL)
_OPEN_RE = re.compile(
    r"<openClosedTextPlain\b[^>]*>(.*?)</openClosedTextPlain>", re.IGNORECASE | re.DOTALL
)
_CDATA_RE = re.compile(r"^<!\[CDATA\[(.*?)\]\]>$", re.DOTALL)
# German feed timestamp: an optional weekday token ("Sa., ") then `DD.MM.YYYY HH:MM`.
_DATE_TOKEN_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})")


def _cell(block: str, pattern: re.Pattern[str]) -> str | None:
    """The inner text of one element in a bath block, CDATA-unwrapped and stripped.

    `None` when the element is absent; `""` when it is present but empty (an empty
    `<temperatureWater></temperatureWater>` cell must stay distinguishable from a missing one)."""
    match = pattern.search(block)
    if match is None:
        return None
    inner = match.group(1).strip()
    cdata = _CDATA_RE.match(inner)
    return (cdata.group(1) if cdata else inner).strip()


def _parse_date(text: str | None) -> datetime | None:
    """Parse the feed's `dateModified` to a tz-aware `Europe/Zurich` datetime, ignoring the
    redundant weekday token. `None` when absent or unparseable."""
    if not text:
        return None
    match = _DATE_TOKEN_RE.search(text)
    if match is None:
        return None
    day, month, year, hour, minute = (int(g) for g in match.groups())
    try:
        return datetime(year, month, day, hour, minute, tzinfo=_ZURICH)
    except ValueError:
        return None


def _parse_bath(block: str) -> Result[tuple[str, TempReading], ProviderError]:
    poiid_text = _cell(block, _POIID_RE)
    if not poiid_text:
        return Err(SchemaMismatch(source=_SOURCE, detail="bath entry missing <poiid>"))

    temp_text = _cell(block, _TEMP_RE)
    celsius: Decimal | None
    if not temp_text:  # absent or empty cell -> measured nothing yet (not an error)
        celsius = None
    else:
        try:
            celsius = Decimal(temp_text)
        except InvalidOperation:
            return Err(
                ParseError(
                    source=_SOURCE,
                    detail=f"non-numeric temperatureWater {temp_text!r} for poiid {poiid_text!r}",
                    raw_snippet=block[:200],
                )
            )

    measured_at = _parse_date(_cell(block, _DATE_RE))
    if measured_at is None:
        return Err(
            ParseError(
                source=_SOURCE,
                detail=f"unparseable dateModified for poiid {poiid_text!r}",
                raw_snippet=block[:200],
            )
        )

    is_open = (_cell(block, _OPEN_RE) or "").lower() == "offen"
    reading = TempReading(measured_at=measured_at, celsius=celsius, is_open=is_open, source=_SOURCE)
    return Ok((poiid_text, reading))


def fetch(client: HttpClient, url: str = FEED_URL) -> Result[bytes, ProviderError]:
    """The raw stage: fetch the feed's bytes (transport/status/timeout errors as values)."""
    match client.get(url):
        case Err(error):
            return Err(error)
        case Ok(resp):
            return Ok(resp.content)


def parse(raw: bytes) -> Result[Mapping[str, TempReading], ProviderError]:
    """The parse stage: feed bytes -> `poiid -> TempReading`. Undecodable bytes -> `ParseError`;
    a body with no `<baths>` (or a bath with no `<poiid>`) -> `SchemaMismatch`."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return Err(
            ParseError(
                source=_SOURCE,
                detail=str(exc),
                raw_snippet=raw[:200].decode("utf-8", "replace"),
            )
        )
    if "<baths" not in text:
        return Err(SchemaMismatch(source=_SOURCE, detail="feed has no <baths> element"))
    readings: dict[str, TempReading] = {}
    for block in _BATH_RE.findall(text):
        match _parse_bath(block):
            case Err(error):
                return Err(error)
            case Ok((poiid, reading)):
                readings[poiid] = reading
    return Ok(readings)


class BaditickerProvider:
    """A `TemperatureProvider` over the Baditicker feed with a TTL cache.

    One upstream `fetch`+`parse` populates a `poiid -> TempReading` snapshot reused for `ttl`, so
    a burst of `/pools/{id}` reads collapses to a single fetch. The `HttpClient` and `clock` are
    injected, so the TTL window is deterministic under test (no wall-clock sleeping)."""

    def __init__(
        self,
        client: HttpClient,
        *,
        url: str = FEED_URL,
        ttl: timedelta = _DEFAULT_TTL,
        clock: Clock | None = None,
    ) -> None:
        self._client = client
        self._url = url
        self._ttl = ttl
        self._clock: Clock = clock or (lambda: datetime.now(_ZURICH))
        self._cached: Mapping[str, TempReading] | None = None
        self._cached_at: datetime | None = None

    def read(self, poiid: str) -> Result[TempReading, ProviderError]:
        """One bath's live reading, keyed by `poiid` (errors as values, per house convention).

        A `poiid` absent from an otherwise-valid feed is a `ProviderSpecific` error (kept inside
        the closed union) — `read_temperature` turns it into an explainable `TempUnavailable`."""
        match self._snapshot():
            case Err(error):
                return Err(error)
            case Ok(readings):
                reading = readings.get(poiid)
                if reading is None:
                    return Err(
                        ProviderSpecific(provider=_SOURCE, detail=f"no reading for poiid {poiid!r}")
                    )
                return Ok(reading)

    def _snapshot(self) -> Result[Mapping[str, TempReading], ProviderError]:
        """The current `poiid -> TempReading` map, from cache within the TTL else a fresh fetch.
        Only a successful fetch+parse is cached — an error is never cached, so the next read
        retries (fail-open upstream in `read_temperature`)."""
        now = self._clock()
        cached, cached_at = self._cached, self._cached_at
        if cached is not None and cached_at is not None and now - cached_at < self._ttl:
            return Ok(cached)
        match fetch(self._client, self._url):
            case Err(error):
                return Err(error)
            case Ok(raw):
                match parse(raw):
                    case Err(error):
                        return Err(error)
                    case Ok(readings):
                        self._cached = readings
                        self._cached_at = now
                        return Ok(readings)
