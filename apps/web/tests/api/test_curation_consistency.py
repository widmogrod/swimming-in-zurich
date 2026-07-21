"""Plan B (retire-facility-table) consistency guard: `curation_status` cannot desync from the
served schedule.

Because B3 made curation a read-time derivation (``codec.is_curated`` over ``pool.facility_doc``)
and B4 routed enrichment through the single ``write_schedules`` door, landing a schedule on a
previously-uncurated pool must, in one write, (a) flip the derived ``curated`` flag on the roster
and ``/pools`` AND (b) put that schedule on the ``/swim`` read path — there is no separate status
writer that could lag. This test locks that: it fails on any world where the flag and the served
schedule can disagree (e.g. a return to a stored ``curation_status`` column, or a write path that
bypasses ``pool.facility_doc``). It reuses the B4 scraped-only-pool pattern
(``hallenbad-altstetten``: in the catalog, absent from the curated dataset).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.web.main import app
from swimzh.core.result import Ok
from swimzh.domain.models import reconstruct_pool_id
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage.sqlite_repo import GoldRepository, load_roster, open_db, write_schedules

DATA_DIR = Path(__file__).resolve().parents[4] / "data"
_SWIM = {"at": "2026-09-14T20:30", "gender": "female", "age": 34, "eligible_only": "false"}


def _curated_flags(db: Path) -> dict[str, bool]:
    return {r.entry.pool_id: r.curated for r in load_roster(open_db(db))}


def _uncurated_facilities(swim: dict[str, object]) -> set[str]:
    statuses = swim["statuses"]
    assert isinstance(statuses, list)
    return {s["facility"] for s in statuses if s["status"] == "uncurated"}


def _option_facilities(swim: dict[str, object]) -> set[str]:
    options = swim["options"]
    assert isinstance(options, list)
    return {o["facility"] for o in options}


def test_scraping_a_schedule_flips_curation_and_serves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db), Ok)
    altstetten = reconstruct_pool_id("hallenbad-altstetten")

    # Precondition — uncurated everywhere: roster flag False, `/swim` reports it `uncurated` (never
    # an option). Slice F gives it a SCHEDULE-LESS prose blob (auto-extracted PARSED_PROSE basins),
    # so the blob is present but carries no rule — curation still derives False, Decision #5 keeps
    # it out of `/swim`.
    assert _curated_flags(db)["hallenbad-altstetten"] is False
    pre = GoldRepository(open_db(db)).get(altstetten)
    assert pre is not None and not any(b.rules for b in pre.basins)
    monkeypatch.setenv("SWIMZH_GOLD_DB", str(db))
    with TestClient(app) as client:
        before = client.get("/swim", params=_SWIM).json()
    assert "Hallenbad Altstetten" in _uncurated_facilities(before)
    assert "Hallenbad Altstetten" not in _option_facilities(before)

    # Land a real schedule on that previously-uncurated pool through the SINGLE write door,
    # exactly as a scrape does — donor is City's curated schedule re-identified as Altstetten,
    # carrying scraped (non-curated) provenance so nothing else could have set a status flag.
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    donor = next(f for f in dataset.value.facilities if f.identity.name == "Hallenbad City")
    scraped = replace(
        donor,
        identity=replace(donor.identity, facility_id=altstetten, name="Hallenbad Altstetten"),
        provenance=replace(donor.provenance, curated=False),
    )
    write_schedules(open_db(db), ((altstetten, scraped),))

    # The one write flips the DERIVED flag on the roster (no status writer touched it)…
    assert _curated_flags(db)["hallenbad-altstetten"] is True

    # …and the same flip shows on `/pools`, while `/swim` now serves the schedule and stops
    # reporting the pool `uncurated` — the flag and the served fact move together, never desync.
    with TestClient(app) as client:
        pools = {p["pool_id"]: p for p in client.get("/pools").json()["pools"]}
        after = client.get("/swim", params=_SWIM).json()
    assert pools["hallenbad-altstetten"]["curated"] is True
    assert "Hallenbad Altstetten" in _option_facilities(after)
    assert "Hallenbad Altstetten" not in _uncurated_facilities(after)
