"""Shared app-test fixtures.

The app now reads exclusively from the SQLite gold store, so every test needs a built gold DB and
`SWIMZH_GOLD_DB` pointing at it. Since S2 (`delete-curated-schedule-tier`) `build` is a SINGLE
ATOMIC PIPELINE — WFS roster → curated assemble → schedule scrape → lane scrape → compose — so the
session gold DB is produced by ONE offline `build(...)` driven by a composite `MockTransport`
(`recorded_build_clients`): WFS layers, pool pages, Belegungsplan PDFs, and the price page all come
from committed fixtures, no network. That means the served store carries REAL scraped schedules for
the indoor pools (not just curated ones), so the web suite asserts against the same pipeline the
app ships. Tests that need a bespoke store override `SWIMZH_GOLD_DB` themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.pipeline_clients import recorded_build_clients  # noqa: E402

from swimzh.cli import build  # noqa: E402
from swimzh.core.result import Ok  # noqa: E402
from swimzh.etl.build import build_store  # noqa: E402
from swimzh.storage import catalog_json  # noqa: E402

DATA_DIR = _REPO_ROOT / "data"
# The committed catalog.json IS the WFS snapshot — the recorded roster double for the offline base.
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def gold_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A COMPLETE gold DB from one offline atomic `build`: WFS-roster spine + curated facilities +
    scraped schedules/lane plans, all replayed from committed fixtures via `recorded_build_clients`.

    An unresolved extra scrape name would make `build` exit 1 (non-fatal), so we assert 0 to catch
    a fixture-vs-crosswalk drift rather than silently serving a partial store.
    """
    db = tmp_path_factory.mktemp("gold") / "gold.sqlite"
    code = build(db_path=db, data_dir=DATA_DIR, clients=recorded_build_clients())
    assert code == 0, f"atomic build failed with exit {code}"
    return db


@pytest.fixture(scope="session")
def offline_gold_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The PRE-SCRAPE store: `build_store` alone (no folded scrape), so indoor pools that the
    atomic `build` would scrape stay schedule-less. This is the store a few S1-acceptance tests
    need — the ones demonstrating `awaiting_scrape`/prose-only pools, or the absence of a scraped
    lane plan — states the fully-built `gold_db` no longer carries once the scrape folds in.
    """
    db = tmp_path_factory.mktemp("gold-offline") / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    return db


@pytest.fixture(autouse=True)
def _point_app_at_gold_db(gold_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aim the app at the session gold DB by default (tests may override)."""
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(gold_db))
    # Hermetic against a developer's local `.env`: neutralise the live-feed URL so the
    # composition root never wires a real `BaditickerProvider` (and never hits the network)
    # during tests. `config.from_env()` calls `load_dotenv(override=False)`, which respects
    # this already-set value; tests that want a provider set `app.state.temperature` directly.
    monkeypatch.setenv("SWIMZH_BADITICKER_URL", "")
