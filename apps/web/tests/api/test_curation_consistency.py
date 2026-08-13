"""Plan B (retire-facility-table) consistency guard: `curation_status` cannot desync from the
served schedule.

Because curation is a read-time derivation (``codec.schedule_freshness`` over
``pool.facility_doc``) and enrichment is routed through the single ``write_schedules`` door,
landing a schedule on a previously-schedule-less pool must, in one write, (a) flip the derived
``freshness`` to ``scraped`` on the roster and ``/pools`` AND (b) put that schedule on the
``/swim`` read path — there is no separate status writer that could lag. This test locks that: it
fails on any world where the derivation and the served schedule can disagree (e.g. a return to a
stored ``curation_status`` column, or a write path that bypasses ``pool.facility_doc``). It reuses
the B4 scraped-only-pool pattern
(``hallenbad-altstetten``: in the catalog, absent from the curated dataset).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app
from swimzh.core.result import Ok
from swimzh.domain.catalog import ScheduleFreshness
from swimzh.domain.models import reconstruct_pool_id
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import GoldRepository, load_roster, open_db, write_schedules

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
# Since S3 the roster is a `build_store` argument sourced from the WFS; the committed catalog.json
# IS that WFS snapshot, so it is the recorded roster double here.
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
_SWIM = {"at": "2026-09-14T20:30", "gender": "female", "age": 34, "eligible_only": "false"}


def _freshness(db: Path) -> dict[str, ScheduleFreshness]:
    return {r.entry.pool_id: r.freshness for r in load_roster(open_db(db))}


def _schedule_less_facilities(swim: dict[str, object]) -> set[str]:
    statuses = swim["statuses"]
    assert isinstance(statuses, list)
    return {s["facility"] for s in statuses if s["status"] in {"awaiting_scrape", "no_source"}}


def _option_facilities(swim: dict[str, object]) -> set[str]:
    options = swim["options"]
    assert isinstance(options, list)
    return {o["facility"] for o in options}


def test_scraping_a_schedule_flips_curation_and_serves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, illustrative_data_dir: Path
) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)
    altstetten = reconstruct_pool_id("hallenbad-altstetten")

    # Precondition — schedule-less everywhere: freshness is NOT `scraped`, `/swim` reports it as a
    # freshness status (never an option). Altstetten is an indoor stadt-zuerich pool with a
    # SCHEDULE-LESS prose blob (auto-extracted PARSED_PROSE basins, no rule), so it derives
    # `awaiting_scrape` and Decision #5 keeps it out of `/swim`.
    assert _freshness(db)["hallenbad-altstetten"] is ScheduleFreshness.AWAITING_SCRAPE
    pre = GoldRepository(open_db(db)).get(altstetten)
    assert pre is not None and not any(b.rules for b in pre.basins)
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        before = client.get("/swim", params=_SWIM).json()
    assert "Hallenbad Altstetten" in _schedule_less_facilities(before)
    assert "Hallenbad Altstetten" not in _option_facilities(before)

    # Land a real schedule on that previously-schedule-less pool through the SINGLE write door,
    # exactly as a scrape does — donor is a scheduled City re-identified as Altstetten, carrying
    # scraped (non-curated) provenance so nothing else could have set a status flag. Production
    # `data/pools/*.yaml` carry no schedule since delete-curated-schedule-tier S3, so the donor
    # schedule comes from the committed illustrative pools (shared `illustrative_data_dir`).
    dataset = load_dataset(illustrative_data_dir)
    assert isinstance(dataset, Ok)
    donor = next(f for f in dataset.value.facilities if f.identity.name == "Hallenbad City")
    scraped = replace(
        donor,
        identity=replace(donor.identity, facility_id=altstetten, name="Hallenbad Altstetten"),
        provenance=replace(donor.provenance, curated=False),
    )
    write_schedules(open_db(db), ((altstetten, scraped),))

    # The one write flips the DERIVED freshness on the roster to `scraped` (no status writer)…
    assert _freshness(db)["hallenbad-altstetten"] is ScheduleFreshness.SCRAPED

    # …and the same flip shows on `/pools` (freshness field), while `/swim` now serves the schedule
    # and stops reporting a freshness status — the derivation and the served fact move together.
    with TestClient(app) as client:
        pools = {p["pool_id"]: p for p in client.get("/pools").json()["pools"]}
        after = client.get("/swim", params=_SWIM).json()
    assert pools["hallenbad-altstetten"]["freshness"] == "scraped"
    assert "Hallenbad Altstetten" in _option_facilities(after)
    assert "Hallenbad Altstetten" not in _schedule_less_facilities(after)
