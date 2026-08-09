"""S3 golden: the WFS-sourced roster (and the spine built from it) reproduces the committed
catalog on the identity + geo + url fields.

`data/catalog.json` IS a WFS snapshot as the provider emits it — a **repaired** one: the roster
`url` passes through `_normalize_roster_url`, which rewrites the dead-TLS `www.sportamt.ch` host
from `https` to `http` (see `providers/geo_sport.py`). So the snapshot is not byte-for-byte what
the WFS published; it is what the provider boundary yields, which is exactly what a cassette-built
roster MUST match. The happy path replays a VCR cassette (the reconstructed WFS layers); the
WFS-down path uses `MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from swimzh.core.errors import ConnectionFailed, HttpStatus
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.etl.build import build_store
from swimzh.etl.roster import fetch_roster
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import open_db
from tests.providers.wfs_snapshot import recorded_wfs_client, unreachable_wfs_client

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _committed_catalog() -> dict[str, tuple[object, ...]]:
    entries = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    return {
        e.pool_id: (
            e.name,
            e.kind,
            e.geo.lat if e.geo else None,
            e.geo.lon if e.geo else None,
            e.url,
        )
        for e in entries
    }


@pytest.mark.vcr
def test_roster_spine_matches_committed_catalog(tmp_path: Path) -> None:
    # Replays tests/providers/cassettes/test_roster/…yaml — the reconstructed WFS layers.
    with httpx.Client(timeout=30.0) as inner:
        client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
        result = fetch_roster(client)

    assert isinstance(result, Ok), result
    roster = result.value
    provider = {
        e.pool_id: (
            e.name,
            e.kind,
            e.geo.lat if e.geo else None,
            e.geo.lon if e.geo else None,
            e.url,
        )
        for e in roster
    }
    committed = _committed_catalog()
    # The full ~57-pool roster matches the committed catalog on pool_id, name, kind, lat, lon, url.
    assert provider == committed

    # `url` is in that comparison because it is user-visible (the "Official" chip) and was
    # previously projected away — a rewrite of every roster URL would have shipped green. It also
    # pins the sportamt repair end-to-end: the cassette carries the WFS's `https` form, so these
    # entries only match the snapshot because the provider normalized them.
    sportamt = [e.url for e in roster if "sportamt.ch" in (e.url or "")]
    assert len(sportamt) == 17, sportamt
    assert all(u is not None and u.startswith("http://") for u in sportamt), sportamt

    # …and the spine built from that provider roster carries the same geo onto every pool row.
    assert isinstance(build_store(DATA_DIR, tmp_path / "gold.sqlite", roster), Ok)
    conn = open_db(tmp_path / "gold.sqlite")
    rows = conn.execute("SELECT id, name, lat, lon FROM pool").fetchall()
    assert len(rows) == 57
    spine = {r[0]: (r[1], r[2], r[3]) for r in rows}
    for pool_id, (name, _kind, lat, lon, _url) in committed.items():
        assert spine[pool_id] == (name, lat, lon), pool_id


def test_recorded_wfs_client_reproduces_catalog_via_mock_transport() -> None:
    # The MockTransport double (used by the build-orchestration tests) reproduces the same roster
    # as the cassette — so those tests build the identical 57-pool spine offline. Since claim-audit
    # S4 this golden compares FULL entries (description, address, phone included), because the raw
    # fixtures deliberately keep the WFS's literal "NULL" sentinels (50 of them, on
    # `infrastruktur`) while the committed snapshot records their ABSENCE: the provider's sentinel
    # rule is the only thing that makes the two sides equal, so weakening it fails here.
    result = fetch_roster(recorded_wfs_client())
    assert isinstance(result, Ok), result
    committed = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    provider = {e.pool_id: e for e in result.value}
    assert provider == {e.pool_id: e for e in committed}

    # Exactly 50 entries lost their description to the sentinel rule; the other 7 keep real
    # prose verbatim; no committed description is the string "NULL" any more.
    descriptions = [e.description for e in committed]
    assert sum(1 for d in descriptions if d is None) == 50
    assert sum(1 for d in descriptions if d is not None) == 7
    assert "NULL" not in descriptions

    # Guard: planschbecken-pfingstweid's empty address comes from real JSON nulls in every WFS
    # address part, NOT from the sentinel — the rule must not produce a 51st catalog diff. Its
    # absent-address RENDERING is a wire-layer concern (see apps/web tests), not a catalog one.
    assert provider["planschbecken-pfingstweid"].address == ""


def test_fetch_roster_aborts_on_unreachable_wfs() -> None:
    # An unreachable WFS is a typed ProviderError value, not an exception — the roster step's
    # local fail-fast that the CLI build turns into a non-zero exit.
    result = fetch_roster(unreachable_wfs_client())
    assert isinstance(result, Err)
    assert isinstance(result.error, ConnectionFailed)


def test_build_store_does_not_read_committed_catalog_json() -> None:
    # Invariant: since S3 the build sources its roster from the WFS provider; `build_store` must
    # not fall back to reading the committed catalog.json — the `catalog_json` codec is no longer
    # imported or called anywhere in the build module (docstrings may still explain the reversal).
    source = (
        Path(__file__).resolve().parents[2] / "src" / "swimzh" / "etl" / "build.py"
    ).read_text(encoding="utf-8")
    assert "catalog_json" not in source


def _mock_layer_error_client(status: int) -> HttpClient:
    inner = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(status)))
    return HttpClient(inner, source="geo_sport", retry=RetryPolicy(max_attempts=1))


def test_fetch_roster_propagates_layer_http_error() -> None:
    # A non-2xx on any WFS layer is surfaced as a typed error value (fail-fast, no partial roster).
    result = fetch_roster(_mock_layer_error_client(500))
    assert isinstance(result, Err)
    assert isinstance(result.error, HttpStatus)
