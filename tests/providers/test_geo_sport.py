"""geo_sport reference adapter: happy path via a recorded cassette (record-once/replay),
error paths via MockTransport (deterministic, no network).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from swimzh.core.errors import HttpStatus, ParseError, SchemaMismatch
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.providers.geo_sport import fetch_indoor_pools


@pytest.mark.vcr
def test_fetch_indoor_pools_happy() -> None:
    # Replays tests/providers/cassettes/test_fetch_indoor_pools_happy.yaml; the first
    # ever run recorded it against the live WFS.
    with httpx.Client(timeout=30.0) as inner:
        client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
        result = fetch_indoor_pools(client)

    assert isinstance(result, Ok), result
    pools = result.value
    assert len(pools) == 7
    assert any(p.name.startswith("Hallenbad City") for p in pools)

    city = next(p for p in pools if p.name.startswith("Hallenbad City"))
    assert 47.30 < city.geo.lat < 47.45
    assert 8.45 < city.geo.lon < 8.60
    assert city.source_id.startswith("poi_hallenbad_view")
    assert city.address  # non-empty


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def test_malformed_body_is_parse_error() -> None:
    client = _mock_client(lambda _r: httpx.Response(200, content=b"{ not json"))
    result = fetch_indoor_pools(client)
    assert isinstance(result, Err)
    assert isinstance(result.error, ParseError)


def test_wrong_shape_is_schema_mismatch() -> None:
    # Valid JSON, but missing the required `features` array.
    client = _mock_client(lambda _r: httpx.Response(200, json={"type": "FeatureCollection"}))
    result = fetch_indoor_pools(client)
    assert isinstance(result, Err)
    assert isinstance(result.error, SchemaMismatch)


def test_http_error_propagates_from_core() -> None:
    client = _mock_client(lambda _r: httpx.Response(500, text="upstream boom"))
    result = fetch_indoor_pools(client)
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)
    assert result.error.status == 500
