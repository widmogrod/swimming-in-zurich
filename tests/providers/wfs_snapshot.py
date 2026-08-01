"""Recorded-WFS test doubles — replayed offline, never a live request.

`data/catalog.json` IS a Stadt-Zürich WFS snapshot (produced by `swimzh build-catalog`). Since
the environment forbids re-recording the live WFS, the per-layer GeoJSON the WFS would return is
reconstructed from that committed snapshot into `tests/providers/fixtures/wfs/<typename>.json`
(one FeatureCollection per `geo_sport.POOL_LAYERS` layer, whose properties round-trip each
catalog entry: name→`name`, address→`strasse`, description→`infrastruktur`, url→`www`,
phone→`tel`, geo→coordinates). Feeding these back through `geo_sport.fetch_all_pools` +
`build_catalog` reproduces the committed catalog EXACTLY — the round-trip the golden test pins.

**CAVEAT — do NOT re-derive `www` from `data/catalog.json`.** That round-trip is no longer
symmetric: the snapshot holds the **repaired** url (`_normalize_roster_url` rewrites the dead-TLS
`www.sportamt.ch` host `https`→`http` at the provider boundary), so reconstructing `www` from it
would bake the repaired `http` form into the fixtures. These fixtures must keep the WFS's **raw**
`https` values — that asymmetry IS the end-to-end pinning: with raw `https` in, the golden test
fails the moment the normalizer is weakened; with `http` in, it would pass even if the normalizer
were deleted.

`recorded_wfs_client()` serves those fixtures via `httpx.MockTransport` (the project's
established no-network adapter double, see `tests/providers/test_geo_sport.py`), keyed on the
`TYPENAME` query param. `unreachable_wfs_client()` raises `httpx.ConnectError` for the
WFS-down abort path — no recorded interaction exists for a failed connection.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import yaml

from swimzh.core.http import HttpClient, RetryPolicy

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WFS_FIXTURES = FIXTURES / "wfs"

# The composite build client's page routing: each indoor pool's roster `url` (its filename, or the
# third-party bad-altstetten host) → the saved page fixture whose timetable `_compose_schedules`
# scrapes and whose Belegungsplan links `_attach_lanes` discovers. Every INDOOR pool the WFS roster
# carries has a parseable fixture here, so the atomic `build`'s fail-fast scrape completes.
_PAGE_BY_FILENAME: dict[str, str] = {
    "city.html": "hallenbad_city.html",
    "oerlikon.html": "hallenbad_oerlikon.html",
    "bungertwies.html": "hallenbad_bungertwies.html",
    "blaesi.html": "hallenbad_blaesi.html",
    "leimbach.html": "hallenbad_leimbach.html",
    "kaeferberg.html": "waermebad_kaeferberg.html",
    "aemtler.html": "schulschwimmanlage_aemtler.html",
}
# A valid single-basin Belegungsplan sheet; the URL-keyed lane join binds by URL, not by content,
# so serving one good plan for every discovered PDF attaches each authored single-basin source.
_LANE_PDF = "city-schwimmerbecken.pdf"
_PRICE_FIXTURE = "preise_abos.html"

# The reconstructed per-layer snapshot above carries `poi_id: null` (catalog.json, from which it
# was reshaped, never captured `poi_id`). The one place a REAL WFS `poi_id` is recorded is the
# indoor `geo_sport` cassette (hb001–hb007) — the fixture S5b's `geo_sport_id`-from-`poi_id`
# sourcing test replays to prove the id flows onto the spine.
_GEO_SPORT_INDOOR_CASSETTE = (
    Path(__file__).resolve().parent
    / "cassettes"
    / "test_geo_sport"
    / "test_fetch_indoor_pools_happy.yaml"
)


def recorded_indoor_client_with_poi_ids() -> HttpClient:
    """An `HttpClient` replaying the recorded indoor WFS layer, which carries the real `poi_id`s.

    Serves the single interaction committed in the `geo_sport` cassette (the live-recorded indoor
    `poi_hallenbad_view` layer, whose properties include `poi_id` hb001–hb007) via `MockTransport`
    — offline, no VCR record-mode dependence — so a test can drive `fetch_indoor_pools` and assert
    the poi_id reaches the built spine's `geo_sport_id`.
    """
    cassette = yaml.safe_load(_GEO_SPORT_INDOOR_CASSETTE.read_text(encoding="utf-8"))
    body: str = cassette["interactions"][0]["response"]["body"]["string"]

    def _serve(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"))

    inner = httpx.Client(transport=httpx.MockTransport(_serve))
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def _wfs_handler(request: httpx.Request) -> httpx.Response:
    typename = request.url.params.get("TYPENAME", "")
    body = (WFS_FIXTURES / f"{typename}.json").read_bytes()
    return httpx.Response(200, content=body)


def recorded_wfs_client() -> HttpClient:
    """An `HttpClient` that replays the committed per-layer WFS snapshot (all ~57 pools)."""
    inner = httpx.Client(transport=httpx.MockTransport(_wfs_handler))
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def unreachable_wfs_transport() -> httpx.MockTransport:
    """A transport that refuses every connection — the WFS-down abort case."""

    def _refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("WFS unreachable")

    return httpx.MockTransport(_refuse)


def unreachable_wfs_client() -> HttpClient:
    """An `HttpClient` whose transport refuses every connection — the WFS-down abort case."""
    inner = httpx.Client(transport=unreachable_wfs_transport())
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def _build_handler(request: httpx.Request) -> httpx.Response:
    """Route ONE request across every provider the atomic `build` reaches, offline:

    * a WFS layer request (has ``TYPENAME``) → the committed per-layer snapshot;
    * the shared price page (``preise-abos``) → the price fixture;
    * a Belegungsplan ``.pdf`` → a valid single-basin lane sheet (URL-keyed join binds by URL);
    * a pool page (mapped filename, or the ``bad-altstetten`` host) → its saved timetable fixture;
    * any other roster page (a location-only pool) → an empty page (no schedule, no links).
    """
    url = str(request.url)
    if request.url.params.get("TYPENAME"):
        return _wfs_handler(request)
    if url.endswith(".pdf"):
        return httpx.Response(200, content=(FIXTURES / _LANE_PDF).read_bytes())
    if "preise-abos" in url:
        return httpx.Response(200, content=(FIXTURES / _PRICE_FIXTURE).read_bytes())
    if "bad-altstetten" in url:
        return httpx.Response(200, content=(FIXTURES / "hallenbad_altstetten.html").read_bytes())
    fixture = _PAGE_BY_FILENAME.get(url.rsplit("/", 1)[-1])
    if fixture is not None:
        return httpx.Response(200, content=(FIXTURES / fixture).read_bytes())
    return httpx.Response(200, content=b"<html></html>")


def recorded_build_transport(
    override: Callable[[httpx.Request], httpx.Response | None] | None = None,
) -> httpx.MockTransport:
    """The composite offline transport for the ONE-command atomic `build`.

    Routes WFS layers, pool pages, Belegungsplan PDFs, and the price page from committed fixtures
    (see `_build_handler`), so `build(...)` reproduces the whole pipeline — roster → schedule
    scrape → lane scrape → compose — with no network. `override` lets a test inject a per-request
    failure (return a `Response` to pre-empt routing, or `None` to fall through to the default) —
    e.g. a 503 on one pool page to prove the atomic abort.

    Handed out as a *transport* (not a finished client) so a cache test can wrap it: the disk
    cache is itself a transport, and it must sit between httpx and this one.
    """

    def _serve(request: httpx.Request) -> httpx.Response:
        if override is not None:
            injected = override(request)
            if injected is not None:
                return injected
        return _build_handler(request)

    return httpx.MockTransport(_serve)
