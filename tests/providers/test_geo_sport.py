"""geo_sport reference adapter: happy path via a recorded cassette (record-once/replay),
error paths via MockTransport (deterministic, no network).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from swimzh.core.errors import HttpStatus, ParseError, SchemaMismatch
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.core.result import Err, Ok
from swimzh.domain.models import PoolKind
from swimzh.providers.geo_sport import POOL_LAYERS, GeoPool, fetch_indoor_pools, parse_pools
from tests.providers.wfs_snapshot import WFS_FIXTURES


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


# --- roster URL scheme normalization -------------------------------------------------------
#
# `www.sportamt.ch` publishes `https` URLs but serves no TLS (see `_normalize_roster_url`), so
# the provider repairs the scheme on the way in. This field had NO test at all before: the
# golden roster test projects `url` away and the API test asserts only non-nullness, so either
# a correct or a catastrophic rewrite would have shipped green. These tests drive the PUBLIC
# `parse_pools` (never the private helper) with crafted FeatureCollections.


def _collection(*urls: str | None) -> bytes:
    features = [
        {
            "type": "Feature",
            "id": f"poi_freibad_view.{i}",
            "geometry": {"type": "Point", "coordinates": [8.5, 47.4]},
            "properties": {"name": f"Pool {i}", "www": url},
        }
        for i, url in enumerate(urls)
    ]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode("utf-8")


def _urls(*raw: str | None) -> list[str | None]:
    result = parse_pools(_collection(*raw), PoolKind.OUTDOOR)
    assert isinstance(result, Ok), result
    return [p.url for p in result.value]


# The one sportamt slug that needs a PATH repair as well as a scheme one: it 302s to a
# stadt-zuerich page that 404s, and the city's live slug carries `-den-`.
_DEAD_SLUG = "https://www.sportamt.ch/freibad-zwischen-hoelzern"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # the ONE dead slug: scheme AND path repaired (a 404 here aborts the whole build, since
        # seasonal-hours S3 made this outdoor pool a declared source)
        (_DEAD_SLUG, "http://www.sportamt.ch/freibad-zwischen-den-hoelzern"),
        # …on the already-plaintext form too: the path repair is not conditional on the scheme
        (
            "http://www.sportamt.ch/freibad-zwischen-hoelzern",
            "http://www.sportamt.ch/freibad-zwischen-den-hoelzern",
        ),
        # …and NOT on another host that happens to use the same slug
        (
            "https://www.stadt-zuerich.ch/freibad-zwischen-hoelzern",
            "https://www.stadt-zuerich.ch/freibad-zwischen-hoelzern",
        ),
        # the repair, with every URL component preserved
        (
            "https://www.sportamt.ch/freibad-letzigraben",
            "http://www.sportamt.ch/freibad-letzigraben",
        ),
        (
            "https://www.sportamt.ch/a/b?x=1&y=2#frag",
            "http://www.sportamt.ch/a/b?x=1&y=2#frag",
        ),
        ("https://sportamt.ch/maennerbad", "http://sportamt.ch/maennerbad"),  # apex host
        # host match is case-insensitive; the netloc itself is left byte-identical
        ("https://WWW.SportAmt.CH/seebad", "http://WWW.SportAmt.CH/seebad"),
        # already plaintext (seebad-katzensee is published this way) -> untouched
        ("http://www.sportamt.ch/seebad-katzensee", "http://www.sportamt.ch/seebad-katzensee"),
        # a host that merely CONTAINS the string is not the broken host
        ("https://sportamt.ch.example.com/x", "https://sportamt.ch.example.com/x"),
        ("https://notsportamt.ch/x", "https://notsportamt.ch/x"),
        # every other host is byte-identical, https included
        ("https://www.stadt-zuerich.ch/freibad", "https://www.stadt-zuerich.ch/freibad"),
        ("https://www.bad-altstetten.ch/", "https://www.bad-altstetten.ch/"),
        # an unparseable value survives rather than exploding the parse
        ("https://[oops/x", "https://[oops/x"),
        (None, None),
    ],
)
def test_roster_url_normalization(raw: str | None, expected: str | None) -> None:
    assert _urls(raw) == [expected]


def test_normalization_is_per_feature() -> None:
    # Several features in one collection: only the broken host moves.
    assert _urls(
        "https://www.sportamt.ch/a",
        "https://www.stadt-zuerich.ch/b",
        None,
    ) == [
        "http://www.sportamt.ch/a",
        "https://www.stadt-zuerich.ch/b",
        None,
    ]


# --- WFS null sentinel ----------------------------------------------------------------------
#
# The WFS uses the literal token "NULL" (case-sensitive) as its null sentinel: an absent
# `infrastruktur` (and potentially any other text property) arrives as the STRING "NULL", not
# JSON null. Before claim-audit S4 the provider passed it through, and 50 of 57 committed
# catalog entries served `"description": "NULL"` — absence served as a definite value. ONE rule
# at the boundary now turns exactly that token into absence, for the description, the address
# parts, and every other cleaned field alike. These tests drive the PUBLIC `parse_pools`.


def _parse_one(**properties: object) -> GeoPool:
    body = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "poi_hallenbad_view.1",
                    "geometry": {"type": "Point", "coordinates": [8.5, 47.4]},
                    "properties": {"name": "Pool X", **properties},
                }
            ],
        }
    ).encode("utf-8")
    result = parse_pools(body, PoolKind.INDOOR)
    assert isinstance(result, Ok), result
    (pool,) = result.value
    return pool


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # the sentinel: the source's "no prose" token parses to absence, not a value
        ("NULL", None),
        # a real value passes (cleaned as before)
        ("25m Becken, Sauna", "25m Becken, Sauna"),
        # a value merely CONTAINING "NULL" as a substring is real data — untouched
        ("Becken NULL Sauna", "Becken NULL Sauna"),
        ("NULLARBOR", "NULLARBOR"),
        # case-sensitive: only the source's exact token is the sentinel
        ("null", "null"),
        ("Null", "Null"),
        # the rule reads the CLEANED value: whitespace around the bare token is still absence
        ("  NULL  ", None),
        (None, None),
    ],
)
def test_description_null_sentinel_parses_to_absence(raw: str | None, expected: str | None) -> None:
    assert _parse_one(infrastruktur=raw).description == expected


def test_address_null_sentinel_parts_are_absent() -> None:
    # A "NULL" street is an ABSENT street, not a street named NULL: the remaining real parts
    # still compose (same joining as before — the rule only removes the sentinel).
    pool = _parse_one(strasse="NULL", hausnummer="NULL", plz="8038", ort="Zürich")
    assert pool.address == "8038 Zürich"
    # …and an all-sentinel address composes to the empty catalog sentinel, exactly like the
    # real-JSON-null case below.
    assert _parse_one(strasse="NULL", hausnummer="NULL", plz="NULL", ort="NULL").address == ""


def test_address_from_real_json_nulls_is_empty_without_the_sentinel_rule() -> None:
    # planschbecken-pfingstweid's shape: every address part is a real JSON null. Its empty
    # address predates the sentinel rule and must NOT change under it (no 51st catalog diff).
    assert _parse_one().address == ""


def test_every_other_cleaned_field_takes_the_same_rule() -> None:
    # ONE rule for every cleaned property, not a description special case.
    pool = _parse_one(namenzus="NULL", tel="NULL", kategorie="NULL", poi_id="NULL", www="NULL")
    assert pool.name == "Pool X"  # a sentinel namenzus is never appended to the name
    assert pool.phone is None
    assert pool.category is None
    assert pool.poi_id is None
    assert pool.url is None


def test_committed_wfs_fixtures_keep_raw_sentinels_and_parse_to_absence() -> None:
    """The raw-asymmetry pin: the committed fixtures KEEP the WFS's literal "NULL" values (50 of
    them, all on `infrastruktur`), and parsing them yields NO field anywhere whose value is the
    string "NULL" — the exact 50 pools whose catalog entry loses its description."""
    raw_sentinels = 0
    parsed_absent = 0
    for path in sorted(WFS_FIXTURES.glob("*.json")):
        raw = path.read_bytes()
        result = parse_pools(raw, POOL_LAYERS[path.stem])
        assert isinstance(result, Ok), result
        features = json.loads(raw)["features"]
        for feature, pool in zip(features, result.value, strict=True):
            if feature["properties"].get("infrastruktur") == "NULL":
                raw_sentinels += 1
                assert pool.description is None, pool.source_id
                parsed_absent += 1
            for value in (
                pool.poi_id,
                pool.name,
                pool.address,
                pool.url,
                pool.category,
                pool.description,
                pool.phone,
            ):
                assert value != "NULL", pool.source_id
    assert raw_sentinels == parsed_absent == 50


def test_committed_wfs_snapshot_urls_are_repaired_or_byte_identical() -> None:
    """Over the FULL committed per-layer snapshot (all ~57 pools, not a sample): every
    sportamt.ch entry comes out on `http` with the rest of the URL untouched — except the ONE
    dead slug, whose path is repaired too — and every other entry comes out byte-identical to
    what the WFS published."""
    seen_sportamt = 0
    seen_other = 0
    seen_slug_repair = 0
    for path in sorted(WFS_FIXTURES.glob("*.json")):
        raw = path.read_bytes()
        result = parse_pools(raw, POOL_LAYERS[path.stem])
        assert isinstance(result, Ok), result
        published = [f["properties"].get("www") for f in json.loads(raw)["features"]]
        assert len(published) == len(result.value)
        for source, pool in zip(published, result.value, strict=True):
            if source == _DEAD_SLUG:
                assert pool.url == "http://www.sportamt.ch/freibad-zwischen-den-hoelzern"
                seen_slug_repair += 1
            elif source is not None and source.startswith("https://www.sportamt.ch/"):
                assert pool.url == "http://" + source.removeprefix("https://")
                seen_sportamt += 1
            else:
                assert pool.url == source
                seen_other += 1
    assert seen_sportamt == 15, seen_sportamt  # 17 sportamt entries − katzensee (http) − the slug
    assert seen_slug_repair == 1, seen_slug_repair
    assert seen_other > 0
