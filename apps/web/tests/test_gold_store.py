"""GoldSwimStore reads facilities, the roster, and the calendar from the SQLite gold store and
fails fast when the store is empty. No curated `data/` tree is read at runtime."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from tests.declared_fixtures import LOCKER_NOUN, PAGE_FIXTURES, page_of

from apps.web.services.gold_store import GoldSwimStore
from swimzh.core.result import Ok
from swimzh.domain.admission import Free, Tariff, Unknown
from swimzh.domain.catalog import ScheduleFreshness
from swimzh.etl.build import build_store
from swimzh.providers.curated import load_dataset
from swimzh.storage import catalog_json, codec
from swimzh.storage.sqlite_repo import open_db

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
# Since S3 the roster is a `build_store` argument sourced from the WFS; the committed catalog.json
# IS that WFS snapshot, so it is the recorded roster double for these gold-store tests.
_ROSTER = catalog_json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


def test_reads_facilities_and_calendar(tmp_path: Path) -> None:
    dataset = load_dataset(DATA_DIR)
    assert isinstance(dataset, Ok)
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)

    data = GoldSwimStore.open(db)
    # Every curated facility reaches the read path; Slice F adds schedule-less prose pools too, so
    # the served set is a superset of the curated dataset.
    served_ids = {str(f.identity.facility_id) for f in data.facilities()}
    curated_ids = {str(f.identity.facility_id) for f in dataset.value.facilities}
    assert curated_ids <= served_ids
    assert len(data.facilities()) >= len(dataset.value.facilities)
    # The calendar is sourced from the gold `calendar` table, never from data/.
    assert data.calendar().covers(date(2026, 3, 10))


def test_roster_holds_the_full_catalog_with_curation(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)

    data = GoldSwimStore.open(db)
    roster = data.roster()
    # The roster is the whole catalog (~57 pools), far more than the handful of curated ones.
    assert len(roster) >= 50
    # A pool derives `SCRAPED` freshness iff a facility with a SCHEDULE backs it.
    # `data.facilities()` also includes schedule-less prose pools (NOT scraped) — filter to those.
    scheduled_ids = {
        str(f.identity.facility_id) for f in data.facilities() if any(b.rules for b in f.basins)
    }
    assert {
        r.entry.pool_id for r in roster if r.freshness is ScheduleFreshness.SCRAPED
    } == scheduled_ids


def test_facility_resolves_a_catalog_pool_to_its_schedule(tmp_path: Path) -> None:
    db = tmp_path / "gold.sqlite"
    assert isinstance(build_store(DATA_DIR, db, _ROSTER), Ok)

    data = GoldSwimStore.open(db)
    # A curated catalog id resolves to its facility (schedule) via the canonical-id join.
    facility = data.facility("hallenbad-city")
    assert facility is not None and facility.identity.name == "Hallenbad City"
    # S1: a pure location-only pool (no prose describing a basin) now resolves to a SCHEDULE-LESS,
    # ZERO-basin facility (viewable detail, no 404) — not None. Only an UNKNOWN id is None (→ 404).
    hardau = data.facility("schulschwimmanlage-hardau")
    assert hardau is not None and hardau.basins == () and not hardau.provenance.curated
    assert data.facility("does-not-exist") is None
    # Slice F: a location-only pool whose WFS prose names basins resolves to a SCHEDULE-LESS
    # facility (auto-extracted PARSED_PROSE basins) — surfaced in detail, but never a /swim option.
    altstetten = data.facility("hallenbad-altstetten")
    assert altstetten is not None
    assert altstetten.basins and not any(b.rules for b in altstetten.basins)


def test_empty_store_fails_fast(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite"
    open_db(db)  # creates the schema but no rows
    with pytest.raises(RuntimeError, match="empty"):
        GoldSwimStore.open(db)


def test_the_priced_pool_count_is_the_coverage_ratchet(gold_db: Path) -> None:
    """The literal gate the city-tariff plan states, against a fully-built store.

    Price coverage moved 10 -> 21 when the fan-out stopped keying on a hostname and started
    following the tariff link each pool's page publishes. The remaining 5 declared sources link
    no tariff (4 published free, 1 privately run) and must stay unpriced. Pinning the number here
    makes a coverage change a line someone edits on purpose, never a side effect nobody noticed.
    """
    count = (
        open_db(gold_db)
        .execute(
            "select count(*) from pool where json_extract(facility_doc,'$.prices') is not null"
        )
        .fetchone()[0]
    )
    assert count == 21

    # No regression: the widening ADDS pools, it never drops one. These 10 were the whole of
    # price coverage under the deleted host gate (6 city-host indoor/thermal + the 4 school pools).
    priced = {
        str(f.identity.facility_id)
        for f in GoldSwimStore.open(gold_db).facilities()
        if isinstance(f.admission, Tariff)
    }
    assert {
        "hallenbad-city",
        "hallenbad-oerlikon",
        "hallenbad-bungertwies",
        "hallenbad-blaesi",
        "hallenbad-leimbach",
        "waermebad-kaeferberg",
        "schulschwimmanlage-aemtler",
        "schulschwimmanlage-altweg",
        "schulschwimmanlage-riedtli",
        "schulschwimmanlage-tannenrauch",
    } <= priced
    # …and the five the city publishes as free / privately run stay unpriced — but no longer as
    # one indistinguishable null: the four free pools now carry `Free`, altstetten the honest
    # `Unknown` (a private operator whose tariff no source states).
    assert (
        priced
        & {
            "hallenbad-altstetten",
            "flussbad-au-hoengg",
            "flussbad-oberer-letten",
            "seebad-katzensee",
            "maennerbad-schanzengraben",
        }
        == set()
    )
    admission_of = {
        str(f.identity.facility_id): f.admission for f in GoldSwimStore.open(gold_db).facilities()
    }
    for free_pool in (
        "flussbad-au-hoengg",
        "flussbad-oberer-letten",
        "seebad-katzensee",
        "maennerbad-schanzengraben",
    ):
        assert admission_of[free_pool] == Free(), free_pool
    assert admission_of["hallenbad-altstetten"] == Unknown()


def test_the_store_splits_twenty_one_tariff_seventeen_free_nineteen_unknown(
    gold_db: Path,
) -> None:
    """The union, counted by LITERAL SQL over `facility_doc`. The admission-union plan pinned
    21/4/32; sharedsource-fanout S3 fans `Free` out to the 13 Planschbecken (their one shared
    page states "Die Nutzung der Planschbecken ist kostenlos"), so the citywide free count is
    now 17 (4 + 13) and the honest unknowns 19. `prices` stays non-null on exactly the 21
    tariffed pools — the fan-out priced no pool and unpriced none."""
    conn = open_db(gold_db)
    total = conn.execute("select count(*) from pool").fetchone()[0]
    tariff = conn.execute(
        "select count(*) from pool where json_extract(facility_doc,'$.prices') is not null"
    ).fetchone()[0]
    free = conn.execute(
        "select count(*) from pool where json_extract(facility_doc,'$.admission_state') is not null"
    ).fetchone()[0]
    free_ids = {
        row[0]
        for row in conn.execute(
            "select id from pool where json_extract(facility_doc,'$.admission_state') = 'free'"
        )
    }
    assert (tariff, free, total - tariff - free) == (21, 17, 19)
    fanout_free = {pool_id for pool_id in free_ids if pool_id.startswith("planschbecken-")}
    assert len(fanout_free) == 13
    assert free_ids == fanout_free | {
        "flussbad-au-hoengg",
        "flussbad-oberer-letten",
        "seebad-katzensee",
        "maennerbad-schanzengraben",
    }


def test_locker_carrying_pools_after_a_rebuild_are_the_fixture_derived_twenty(
    gold_db: Path,
) -> None:
    """Mietobjekt-extraction S1 acceptance: after a full (offline) atomic build, EXACTLY the
    pools whose committed page carries a locker noun serve non-empty `lockers` — the expected
    id set derived by the shared, parser-independent `LOCKER_NOUN` scan over the DECLARED
    fixtures (`tests.declared_fixtures`), so this cannot collapse into comparing the parser
    with itself. Measured count: 20 of the 26 declared sources."""
    expected = {pool_id for pool_id in PAGE_FIXTURES if LOCKER_NOUN.search(page_of(pool_id))}
    carrying = {
        str(f.identity.facility_id) for f in GoldSwimStore.open(gold_db).facilities() if f.lockers
    }
    assert carrying == expected
    assert len(carrying) == 20
    # The case a Garderobenkasten-only grep misses: mythenquai's table opens with
    # `Wertsachenfach` and has no Garderobenkasten row — it must still carry lockers.
    assert "strandbad-mythenquai" in carrying


def test_a_pool_without_the_mietobjekt_table_keeps_a_byte_stable_blob(gold_db: Path) -> None:
    """S1 touches no codec/DTO code, so a pool whose page carries no Mietobjekt table
    serializes exactly as before: `lockers` stays the pre-existing (unconditional) empty
    list, and the stored blob round-trips byte-identically through the codec."""
    doc = (
        open_db(gold_db)
        .execute("select facility_doc from pool where id = 'maennerbad-schanzengraben'")
        .fetchone()[0]
    )
    assert '"lockers":[]' in doc
    assert codec.dumps(codec.loads(doc)) == doc


def test_the_school_pools_are_served_the_school_tariff(gold_db: Path) -> None:
    """The city prints `Eintritte Schulschwimmanlagen` at 5.-/5.-/2.50, not the Hallenbad
    8.-/6.-/4.-. Asserted on the STORE, so it covers scrape -> compose -> codec end to end."""
    priced = {
        str(f.identity.facility_id): f.admission.table
        for f in GoldSwimStore.open(gold_db).facilities()
        if isinstance(f.admission, Tariff)
    }
    school = {k: v for k, v in priced.items() if k.startswith("schulschwimmanlage-")}
    assert len(school) == 4, sorted(school)
    for pool_id, table in school.items():
        assert [e.amount_chf for e in table.entries] == [
            Decimal("5.00"),
            Decimal("5.00"),
            Decimal("2.50"),
        ], pool_id
        # Both rows share the table's column headers, so the bounds are the same published ones.
        assert [e.min_age for e in table.entries] == [20, 16, 6], pool_id
    for pool_id, table in priced.items():
        if pool_id.startswith("schulschwimmanlage-"):
            continue
        assert [e.amount_chf for e in table.entries] == [
            Decimal("8.00"),
            Decimal("6.00"),
            Decimal("4.00"),
        ], pool_id
