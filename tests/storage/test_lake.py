"""The lake's silver directory: atomic per-source documents with a provenance header, plus the
two runtime seams (`pull` from a directory or an http origin, `export` to a directory)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from swimzh.storage.lake import SILVER_SOURCES, Lake, SilverHeader, SilverStatus

_ZURICH = ZoneInfo("Europe/Zurich")
_T0 = datetime(2026, 8, 31, 5, 0, tzinfo=_ZURICH)


def test_an_empty_lake_has_no_documents(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake")
    assert all(lake.read(source) is None for source in SILVER_SOURCES)
    assert lake.headers() == ()


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
    assert set(obj["silver"]) == {"source", "fetched_at", "status", "content_sha"}
    assert obj["silver"]["fetched_at"] == _T0.isoformat()


def test_a_naive_fetched_at_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SilverHeader.from_json_obj(
            {
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
    assert target.pull(str(out)) == ("roster", "prices")
    pulled = target.read("roster")
    assert pulled is not None and pulled.header == source_lake.read("roster").header  # type: ignore[union-attr]
    assert target.read("schedules") is None


def test_pull_over_http_skips_404_and_adopts_200(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        pulled = target.pull("https://example.test/lake/", client=client)
    assert pulled == ("roster",)
    assert target.read("roster") is not None
    err = capsys.readouterr().err
    assert "skipping prices" in err and "HTTP 500" in err
    assert "schedules" not in err  # a 404 is first-run, not an error worth a line


def test_pull_skips_an_unreadable_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin = tmp_path / "origin" / "silver"
    origin.mkdir(parents=True)
    (origin / "roster.json").write_text("{not json", encoding="utf-8")
    (origin / "prices.json").write_text(json.dumps({"silver": {"source": "roster"}, "payload": {}}))
    target = Lake(tmp_path / "lake")
    assert target.pull(str(tmp_path / "origin")) == ()
    assert "skipping roster" in capsys.readouterr().err
    assert target.read("roster") is None and target.read("prices") is None


def test_pull_over_http_reports_a_transport_error_and_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    target = Lake(tmp_path / "lake")
    with httpx.Client(transport=httpx.MockTransport(refuse)) as client:
        assert target.pull("http://down.test", client=client) == ()
    assert capsys.readouterr().err.count("skipping") == len(SILVER_SOURCES)
