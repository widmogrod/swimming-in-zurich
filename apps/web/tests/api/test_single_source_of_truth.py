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

from apps.web.main import app

APP_SRC = Path(__file__).resolve().parents[2]  # apps/web
FORBIDDEN = ("catalog.json", ".yaml", "load_dataset")


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
    with pytest.raises(RuntimeError, match="swimzh build"), TestClient(app):
        pass


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
        detail = client.get("/pools/city", params={"at": "2026-09-14T20:30"})
    assert swim.status_code == 200
    assert any(o["facility"] == "Hallenbad City" for o in swim.json()["options"])
    assert detail.status_code == 200
    assert detail.json()["facility_name"] == "Hallenbad City"
