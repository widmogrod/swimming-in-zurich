"""The per-source refresh policy, decision by decision, over a real lake directory and a fetch
closure the test controls. The build tests prove the same policy end to end; these pin each
branch of the table in `etl/refresh`'s docstring on its own."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from swimzh.core.cache_tiers import CachePolicy
from swimzh.core.errors import (
    ConnectionFailed,
    HttpStatus,
    ParseError,
    ProviderError,
    SchemaMismatch,
    Timeout,
)
from swimzh.core.result import Err, Ok, Result
from swimzh.etl.refresh import (
    POLICY_SOURCE,
    RefreshFailure,
    refresh_source,
    silver_policy,
    transient,
)
from swimzh.storage.lake import SILVER_SOURCES, Lake, SilverStatus

_ZURICH = ZoneInfo("Europe/Zurich")
_T0 = datetime(2026, 8, 31, 5, 0, tzinfo=_ZURICH)
_POLICY = CachePolicy("static", ttl_s=7 * 86400, max_stale_s=30 * 86400)
_DOWN: ProviderError = HttpStatus(url="https://x", status=500, body_snippet="")


def _encode(value: int) -> dict[str, Any]:
    return {"v": value}


def _decode(payload: dict[str, Any]) -> int:
    return int(payload["v"])


class _Fetch:
    """A fetch closure that records whether it was called and answers what it is told to."""

    def __init__(self, answer: Result[int, ProviderError]) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> Result[int, ProviderError]:
        self.calls += 1
        return self.answer


def _run(lake: Lake, fetch: _Fetch, *, now: datetime, force: bool = False):  # type: ignore[no-untyped-def]
    return refresh_source(
        lake,
        "roster",
        now=now,
        fetch=fetch,
        encode=_encode,
        decode=_decode,
        force=force,
        policy=_POLICY,
    )


def test_every_silver_source_has_a_governing_policy() -> None:
    assert set(POLICY_SOURCE) == set(SILVER_SOURCES)
    for source in SILVER_SOURCES:
        assert silver_policy(source).ttl_s > 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (Timeout(url="u", after_s=5.0), True),
        (ConnectionFailed(url="u", detail="refused"), True),
        (HttpStatus(url="u", status=500, body_snippet=""), True),
        (HttpStatus(url="u", status=503, body_snippet=""), True),
        (HttpStatus(url="u", status=404, body_snippet=""), False),
        (ParseError(source="s", detail="bad", raw_snippet=""), False),
        (SchemaMismatch(source="s", detail="drift"), False),
    ],
)
def test_transient_is_network_or_5xx_never_our_contract(
    error: ProviderError, expected: bool
) -> None:
    assert transient(error) is expected


def test_first_run_fetches_and_writes_a_fresh_document(tmp_path: Path) -> None:
    lake = Lake(tmp_path)
    fetch = _Fetch(Ok(7))
    result = _run(lake, fetch, now=_T0)
    assert isinstance(result, Ok)
    assert result.value.value == 7 and result.value.fetched and not result.value.stale
    assert result.value.header.status is SilverStatus.FRESH
    assert fetch.calls == 1
    stored = lake.read("roster")
    assert stored is not None and stored.payload == {"v": 7}


def test_a_document_younger_than_the_ttl_is_reused_without_the_network(tmp_path: Path) -> None:
    lake = Lake(tmp_path)
    lake.write("roster", {"v": 7}, fetched_at=_T0)
    fetch = _Fetch(Err(_DOWN))  # would fail — must never be called
    result = _run(lake, fetch, now=_T0 + timedelta(days=1))
    assert isinstance(result, Ok)
    assert result.value.value == 7 and not result.value.fetched and not result.value.stale
    assert fetch.calls == 0


def test_force_refetches_even_inside_the_ttl(tmp_path: Path) -> None:
    lake = Lake(tmp_path)
    lake.write("roster", {"v": 7}, fetched_at=_T0)
    fetch = _Fetch(Ok(8))
    result = _run(lake, fetch, now=_T0 + timedelta(hours=1), force=True)
    assert isinstance(result, Ok) and result.value.value == 8 and result.value.fetched
    assert fetch.calls == 1


def test_past_the_ttl_a_transient_failure_keeps_the_previous_document_as_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lake = Lake(tmp_path)
    lake.write("roster", {"v": 7}, fetched_at=_T0)
    result = _run(lake, _Fetch(Err(_DOWN)), now=_T0 + timedelta(days=10))
    assert isinstance(result, Ok)
    assert result.value.value == 7 and not result.value.fetched and result.value.stale
    assert result.value.header.fetched_at == _T0  # the REAL fetch time, not now
    on_disk = lake.read("roster")
    assert on_disk is not None and on_disk.header.status is SilverStatus.STALE
    err = capsys.readouterr().err
    assert "roster" in err and "STALE" in err and "10.0 d old" in err


def test_past_max_stale_a_transient_failure_aborts(tmp_path: Path) -> None:
    lake = Lake(tmp_path)
    lake.write("roster", {"v": 7}, fetched_at=_T0)
    result = _run(lake, _Fetch(Err(_DOWN)), now=_T0 + timedelta(days=31))
    assert isinstance(result, Err)
    assert result.error.reason == "too_stale"
    assert "31.0 d old" in result.error.describe()
    # The previous document is NOT touched: it stays fresh-labelled for a later, luckier run.
    on_disk = lake.read("roster")
    assert on_disk is not None and on_disk.header.status is SilverStatus.FRESH


def test_a_transient_failure_with_nothing_to_keep_aborts(tmp_path: Path) -> None:
    result = _run(Lake(tmp_path), _Fetch(Err(_DOWN)), now=_T0)
    assert isinstance(result, Err)
    assert result.error.reason == "first_run"
    assert "first run" in result.error.describe()


def test_a_non_transient_failure_aborts_even_with_a_young_stale_candidate(tmp_path: Path) -> None:
    # A 200 that will not parse is schema drift: last week's facts must not paper over it.
    lake = Lake(tmp_path)
    lake.write("roster", {"v": 7}, fetched_at=_T0)
    drift: ProviderError = SchemaMismatch(source="wfs", detail="layer renamed")
    result = _run(lake, _Fetch(Err(drift)), now=_T0 + timedelta(days=10))
    assert isinstance(result, Err)
    assert result.error == RefreshFailure(source="roster", reason="not_transient", cause=drift)
    assert result.error.describe() == "roster: schema mismatch from wfs: layer renamed"


def test_a_stale_keep_is_retried_on_the_very_next_run(tmp_path: Path) -> None:
    """Reviewer finding 2026-09-06: a stale doc younger than the TTL must not be reused as if it
    were fresh — the source may be back, and a store that cannot heal is worse than a slow one."""
    lake = Lake(tmp_path)
    lake.write("roster", {"v": 7}, fetched_at=_T0)
    kept = _run(lake, _Fetch(Err(_DOWN)), now=_T0 + timedelta(days=10))
    assert isinstance(kept, Ok) and kept.value.stale
    healed = _Fetch(Ok(8))
    result = _run(lake, healed, now=_T0 + timedelta(days=10, hours=1))
    assert isinstance(result, Ok)
    assert healed.calls == 1
    assert result.value.value == 8 and result.value.fetched and not result.value.stale
