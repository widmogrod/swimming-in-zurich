"""Recorded-WFS test doubles — replayed offline, never a live request.

`data/catalog.json` IS a Stadt-Zürich WFS snapshot (produced by `swimzh build-catalog`). Since
the environment forbids re-recording the live WFS, the per-layer GeoJSON the WFS would return is
reconstructed from that committed snapshot into `tests/providers/fixtures/wfs/<typename>.json`
(one FeatureCollection per `geo_sport.POOL_LAYERS` layer, whose properties round-trip each
catalog entry: name→`name`, address→`strasse`, description→`infrastruktur`, url→`www`,
phone→`tel`, geo→coordinates). Feeding these back through `geo_sport.fetch_all_pools` +
`build_catalog` reproduces the committed catalog EXACTLY — the round-trip the golden test pins.

`recorded_wfs_client()` serves those fixtures via `httpx.MockTransport` (the project's
established no-network adapter double, see `tests/providers/test_geo_sport.py`), keyed on the
`TYPENAME` query param. `unreachable_wfs_client()` raises `httpx.ConnectError` for the
WFS-down abort path — no recorded interaction exists for a failed connection.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml

from swimzh.core.http import HttpClient, RetryPolicy

WFS_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wfs"

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


def unreachable_wfs_client() -> HttpClient:
    """An `HttpClient` whose transport refuses every connection — the WFS-down abort case."""

    def _refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("WFS unreachable")

    inner = httpx.Client(transport=httpx.MockTransport(_refuse))
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))
