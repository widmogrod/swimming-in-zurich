"""The lake's silver directory: atomic per-source documents with a provenance header, plus the
two runtime seams (`pull` from a directory or an http origin, `export` to a directory)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.core.errors import ConnectionFailed, HttpStatus, SchemaMismatch
from swimzh.core.http import HttpClient, RetryPolicy
from swimzh.storage.lake import (
    SILVER_SCHEMA,
    SILVER_SOURCES,
    Lake,
    PullReport,
    SilverHeader,
    SilverStatus,
)

_ZURICH = ZoneInfo("Europe/Zurich")
_T0 = datetime(2026, 8, 31, 5, 0, tzinfo=_ZURICH)


def _client_over(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
    """The production shape (`HttpClient` over one `httpx.Client`) with a MockTransport inside,
    the same wiring as `tests/pipeline_clients.py`; one attempt so a refused connection is not
    retried three times."""
    inner = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return HttpClient(inner, source="lake", retry=RetryPolicy(max_attempts=1))


def test_an_empty_lake_has_no_documents(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    assert all(lake.read(source) is None for source in SILVER_SOURCES)


def test_write_then_read_round_trips_payload_and_a_fresh_header(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    doc = lake.write("roster", {"entries": [{"pool_id": "x"}]}, fetched_at=_T0)
    back = lake.read("roster")
    assert back is not None
    assert back.payload == {"entries": [{"pool_id": "x"}]}
    assert back.header == doc.header
    assert back.header.status is SilverStatus.FRESH
    assert back.header.fetched_at == _T0
    assert len(back.header.content_sha) == 64


def test_the_content_sha_is_a_function_of_the_payload_only(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    first = lake.write("prices", {"a": 1, "b": [1, 2]}, fetched_at=_T0)
    later = datetime(2026, 9, 7, 5, 0, tzinfo=_ZURICH)
    second = lake.write("prices", {"b": [1, 2], "a": 1}, fetched_at=later)
    assert first.header.content_sha == second.header.content_sha
    assert lake.write("prices", {"a": 2}, fetched_at=later).header.content_sha != (
        first.header.content_sha
    )


def test_mark_stale_rewrites_only_the_header(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    fresh = lake.write("schedules", {"facilities": []}, fetched_at=_T0)
    stale = lake.mark_stale("schedules")
    assert stale.header.status is SilverStatus.STALE
    assert stale.header.fetched_at == fresh.header.fetched_at
    assert stale.header.content_sha == fresh.header.content_sha
    assert stale.payload == fresh.payload
    on_disk = lake.read("schedules")
    assert on_disk is not None and on_disk.header.status is SilverStatus.STALE


def test_mark_stale_on_an_absent_source_raises(tmp_path: Path) -> None:
    with pytest.raises(LookupError):
        Lake(tmp_path / "lake").mark_stale("lane_plans")


def test_the_file_on_disk_is_the_documented_envelope(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    lake.write("roster", {"entries": []}, fetched_at=_T0)
    obj = json.loads(lake.path_for("roster").read_text(encoding="utf-8"))
    assert set(obj) == {"silver", "payload"}
    assert set(obj["silver"]) == {"schema", "source", "fetched_at", "status", "content_sha"}
    assert obj["silver"]["schema"] == SILVER_SCHEMA
    assert obj["silver"]["fetched_at"] == _T0.isoformat()


def test_a_naive_fetched_at_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SilverHeader.from_json_obj(
            {
                "schema": SILVER_SCHEMA,
                "source": "roster",
                "fetched_at": "2026-08-31T05:00:00",
                "status": "fresh",
                "content_sha": "x",
            }
        )


def test_a_file_claiming_another_source_is_refused(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    lake.write("roster", {"entries": []}, fetched_at=_T0)
    lake.path_for("prices").write_text(lake.path_for("roster").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="claims source"):
        lake.read("prices")


def test_export_then_pull_from_a_directory_round_trips_every_present_source(tmp_path: Path) -> None:
    source_lake = Lake(tmp_path / "a")
    source_lake.write("roster", {"entries": []}, fetched_at=_T0)
    source_lake.write("prices", {"general": {}, "school": {}}, fetched_at=_T0)
    out = tmp_path / "dist"
    assert source_lake.export(out) == ("roster", "prices")
    assert (out / "silver" / "roster.json").exists()

    target = Lake(tmp_path / "b")
    assert target.pull(str(out)) == PullReport(
        pulled=("roster", "prices"), absent=("schedules", "lane_plans")
    )
    pulled = target.read("roster")
    assert pulled is not None and pulled.header == source_lake.read("roster").header  # type: ignore[union-attr]
    assert target.read("schedules") is None


def test_pull_over_http_adopts_200_reports_404_as_absent_and_500_as_typed(tmp_path: Path) -> None:
    published = Lake(tmp_path / "published")
    published.write("roster", {"entries": []}, fetched_at=_T0)
    body = published.path_for("roster").read_text(encoding="utf-8")

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/silver/roster.json"):
            return httpx.Response(200, text=body)
        if request.url.path.endswith("/silver/prices.json"):
            return httpx.Response(500, text="down")
        return httpx.Response(404)

    target = Lake(tmp_path / "lake")
    report = target.pull("https://example.test/lake/", client=_client_over(serve))
    assert report.pulled == ("roster",)
    assert report.absent == ("schedules", "lane_plans")  # a 404 is first-run, not an error
    assert report.failed == (
        (
            "prices",
            HttpStatus(
                url="https://example.test/lake/silver/prices.json", status=500, body_snippet="down"
            ),
        ),
    )
    assert target.read("roster") is not None
    assert target.read("prices") is None


def test_pull_reports_an_unreadable_document_as_a_schema_mismatch(tmp_path: Path) -> None:
    origin = Lake(tmp_path / "origin")
    origin.write("roster", {"entries": []}, fetched_at=_T0)
    valid = json.loads(origin.path_for("roster").read_text(encoding="utf-8"))
    origin.path_for("roster").write_text("{not json", encoding="utf-8")
    origin.path_for("prices").write_text(json.dumps(valid), encoding="utf-8")  # claims roster
    valid["silver"]["source"] = "schedules"
    valid["payload"] = []
    origin.path_for("schedules").write_text(json.dumps(valid), encoding="utf-8")
    target = Lake(tmp_path / "lake")
    report = target.pull(str(origin.root))
    assert report.pulled == () and report.absent == ("lane_plans",)
    reasons = {source: error for source, error in report.failed}
    assert list(reasons) == ["roster", "prices", "schedules"]
    assert all(isinstance(error, SchemaMismatch) for error in reasons.values())
    details = {
        source: error.detail for source, error in report.failed if isinstance(error, SchemaMismatch)
    }
    assert "unreadable" in details["roster"]
    assert "claims source 'roster'" in details["prices"]
    assert "not an object" in details["schedules"]
    assert all(target.read(source) is None for source in SILVER_SOURCES)


def test_pull_over_http_reports_a_transport_error_and_continues(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    target = Lake(tmp_path / "lake")
    report = target.pull("http://down.test", client=_client_over(refuse))
    assert report.pulled == () and report.absent == ()
    assert [source for source, _ in report.failed] == list(SILVER_SOURCES)
    assert all(isinstance(error, ConnectionFailed) for _, error in report.failed)


def test_pull_over_http_without_a_client_builds_an_uncached_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default client is a plain `httpx.Client` (no disk cache in between): a pull must
    never be served from last week's cached bytes."""
    seen: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.extensions.get("cache_tier", "default") == "default"
        return httpx.Response(404)

    real_client = httpx.Client

    def plain_client(**kwargs: object) -> httpx.Client:
        assert "transport" not in kwargs and kwargs.get("follow_redirects") is True
        return real_client(transport=httpx.MockTransport(serve), follow_redirects=True)

    monkeypatch.setattr(httpx, "Client", plain_client)
    report = Lake(tmp_path / "lake").pull("https://example.test")
    assert report == PullReport(absent=SILVER_SOURCES)
    assert seen == [f"/silver/{s}.json" for s in SILVER_SOURCES]


def test_a_document_under_another_schema_is_absent_not_decoded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A silver written by an older codec (the pre-fix roster without `poi_id`) must never be
    decoded with today's codec: it reads as a first run, and `pull` will not adopt it either."""
    lake = Lake(tmp_path / "lake")
    lake.write("roster", {"entries": []}, fetched_at=_T0)
    obj = json.loads(lake.path_for("roster").read_text(encoding="utf-8"))
    obj["silver"]["schema"] = SILVER_SCHEMA - 1
    lake.path_for("roster").write_text(json.dumps(obj), encoding="utf-8")
    assert lake.read("roster") is None
    assert "silver schema" in capsys.readouterr().err
    other = Lake(tmp_path / "other")
    report = other.pull(str(tmp_path / "lake"))
    assert report.pulled == ()
    assert [source for source, _ in report.failed] == ["roster"]
    _, error = report.failed[0]
    assert isinstance(error, SchemaMismatch) and "silver schema" in error.detail
    # No `schema` key at all (a hand-made file) is schema 0: absent too.
    del obj["silver"]["schema"]
    lake.path_for("roster").write_text(json.dumps(obj), encoding="utf-8")
    assert lake.read("roster") is None
