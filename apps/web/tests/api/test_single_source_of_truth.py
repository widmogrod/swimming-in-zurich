"""S3 invariant: the app reads exclusively from one SQLite gold store.

- No `apps/web/**` module opens `data/*.yaml` or `catalog.json` at runtime (grep-assertable).
- `/swim`, `/pools`, `/access-types` all serve from one gold-DB fixture.
- A missing gold DB fails fast at startup with a clear "run `swimzh build`" message.
- `/swim` and `/pools` read the same store.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.config import Config
from apps.web.main import app, startup_error

APP_SRC = Path(__file__).resolve().parents[2]  # apps/web
FORBIDDEN = ("catalog.json", ".yaml", "load_dataset")


def _config(gold_db: Path) -> Config:
    return Config(gold_db=gold_db, host="127.0.0.1", port=8000, reload=False)


def _runtime_source_files() -> list[Path]:
    return [p for p in APP_SRC.rglob("*.py") if "tests" not in p.parts]


def test_no_app_module_reads_curated_data_at_runtime() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _runtime_source_files():
        text = path.read_text(encoding="utf-8")
        hits = [token for token in FORBIDDEN if token in text]
        if hits:
            offenders[str(path.relative_to(APP_SRC))] = hits
    assert not offenders, f"runtime app modules must not read curated data: {offenders}"


def test_missing_gold_db_fails_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(tmp_path / "absent.sqlite"))
    with pytest.raises(RuntimeError, match=r"swimzh\.cli build"), TestClient(app):
        pass


def test_startup_error_reports_missing_db_cleanly(tmp_path: Path) -> None:
    # The clean preflight (used by `python -m apps.web.main`) returns an actionable message
    # instead of raising — so the entrypoint can print one line and exit, no ASGI traceback.
    msg = startup_error(_config(tmp_path / "absent.sqlite"))
    assert msg is not None
    assert "not found" in msg and "swimzh.cli build" in msg


def test_startup_error_reports_empty_db_cleanly(tmp_path: Path) -> None:
    from swimzh.storage.sqlite_repo import open_db

    empty = tmp_path / "empty.sqlite"
    open_db(empty)  # schema, no rows
    msg = startup_error(_config(empty))
    assert msg is not None and "empty" in msg


def test_startup_error_none_when_store_ready(gold_db: Path) -> None:
    assert startup_error(_config(gold_db)) is None


def test_swim_pools_and_access_types_serve_from_one_gold_db(gold_db: Path) -> None:
    # `gold_db` (via the autouse fixture) is the single configured source for the app.
    with TestClient(app) as client:
        swim = client.get("/swim", params={"at": "2026-09-14T20:30", "gender": "female", "age": 34})
        pools = client.get("/pools")
        access = client.get("/access-types")
    assert swim.status_code == 200
    assert pools.status_code == 200
    assert access.status_code == 200
    assert pools.json()["count"] >= 50
    assert swim.json()["options"]
    assert access.json()["types"]


def test_swim_and_pools_read_the_same_store(gold_db: Path) -> None:
    """A facility surfaced by `/swim` resolves as a facility detail under `/pools/{id}` from
    the same store — the schedules and the catalog are one gold DB, not two sources."""
    with TestClient(app) as client:
        swim = client.get("/swim", params={"at": "2026-09-14T20:30", "gender": "female", "age": 34})
        detail = client.get("/pools/hallenbad-city", params={"at": "2026-09-14T20:30"})
    assert swim.status_code == 200
    assert any(o["facility"] == "Hallenbad City" for o in swim.json()["options"])
    assert detail.status_code == 200
    assert detail.json()["facility_name"] == "Hallenbad City"


def test_swim_emits_uncurated_statuses_live_for_catalog_pools(gold_db: Path) -> None:
    """S3 acceptance: `/swim` returns `uncurated` statuses at runtime for catalog pools that
    have no curated schedule — `uncurated = roster − scheduled`, identity known via the roster.
    The three states stay un-merged: a curated pool never appears as `uncurated`."""
    with TestClient(app) as client:
        response = client.get(
            "/swim",
            params={
                "at": "2026-09-14T20:30",
                "gender": "female",
                "age": 34,
                "eligible_only": "false",
            },
        )
    assert response.status_code == 200
    statuses = response.json()["statuses"]
    uncurated = {s["facility"] for s in statuses if s["status"] == "uncurated"}
    # Most of the ~57 catalog pools carry no curated timetable → many live `uncurated` rows.
    assert len(uncurated) >= 40
    # A curated pool (City appears among the options) is never also reported `uncurated`.
    assert "Hallenbad City" not in uncurated
    # The states are distinct labels, never merged.
    assert {s["status"] for s in statuses} <= {"closed", "uncurated"}


def test_pools_expose_the_derived_curation_flag(gold_db: Path) -> None:
    """S3: `/pools` reads the one `pool` table and surfaces each pool's derived `curated` flag,
    so the UI reads schedule status from the API rather than guessing it by name."""
    with TestClient(app) as client:
        response = client.get("/pools")
    pools = {p["pool_id"]: p for p in response.json()["pools"]}
    assert all(isinstance(p["curated"], bool) for p in pools.values())
    # City is curated; the vast majority of catalog pools are locations only.
    assert pools["hallenbad-city"]["curated"] is True
    assert "hallenbad-altstetten" in pools and pools["hallenbad-altstetten"]["curated"] is False
    assert sum(1 for p in pools.values() if not p["curated"]) >= 40
