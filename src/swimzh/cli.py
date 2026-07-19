"""Command-line entry point.

  swimzh build-gold    --db gold.sqlite     # raw→silver→gold SQLite the web app serves from
  swimzh build-catalog --out data/catalog.json  # full pool catalog from the WFS (committed)
  swimzh scrape-lanes  --db gold.sqlite     # attach per-basin Belegungsplan lane plans

Run via: `uv run python -m swimzh.cli <command> ...`
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from swimzh.core.errors import describe
from swimzh.core.http import HttpClient
from swimzh.core.result import Err, Ok
from swimzh.etl import pipeline
from swimzh.etl.catalog import build_catalog
from swimzh.etl.gold import write_gold
from swimzh.etl.lane_plans import CITY_BELEGUNGSPLAN_URLS, scrape_lane_plans
from swimzh.etl.scrape import scrape_indoor_facilities
from swimzh.etl.silver import attach_lane_plans
from swimzh.providers import geo_sport
from swimzh.providers.price_scraper import scrape_prices
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import GoldRepository, open_db

_ZURICH = ZoneInfo("Europe/Zurich")


def build_gold(*, db_path: Path, data_dir: Path, client: HttpClient, fetched_at: datetime) -> int:
    """Run raw→silver→gold into `db_path`. Returns a process exit code."""
    match pipeline.run(data_dir=data_dir, db_path=db_path, client=client, fetched_at=fetched_at):
        case Ok(repo):
            print(f"gold store written to {db_path} ({repo.count()} facilities)")
            return 0
        case Err(error):
            print(f"ETL failed: {describe(error)}", file=sys.stderr)
            return 1


def build_catalog_file(*, out: Path, client: HttpClient, generated_at: datetime) -> int:
    """Fetch every pool category from the WFS and write the catalog JSON. Exit code."""
    match geo_sport.fetch_all_pools(client):
        case Ok(pools):
            entries = build_catalog(pools)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(catalog_json.dumps(entries, generated_at), encoding="utf-8")
            print(f"catalog written to {out} ({len(entries)} pools)")
            return 0
        case Err(error):
            print(f"catalog build failed: {describe(error)}", file=sys.stderr)
            return 1


def scrape_gold(
    *, db_path: Path, catalog_path: Path, client: HttpClient, fetched_at: datetime
) -> int:
    """Scrape indoor-pool schedules into a gold store the web app can serve from. Exit code."""
    if not catalog_path.exists():
        print(f"catalog not found at {catalog_path}; run build-catalog first", file=sys.stderr)
        return 1
    catalog = catalog_json.loads(catalog_path.read_text(encoding="utf-8"))
    prices_result = scrape_prices(client, fetched_at.date())
    prices = prices_result.value if isinstance(prices_result, Ok) else None
    report = scrape_indoor_facilities(client, catalog, fetched_at, prices=prices)
    if not report.facilities:
        print("no schedules could be scraped", file=sys.stderr)
        return 1
    write_gold(open_db(db_path), report.facilities)
    msg = f"scraped {len(report.facilities)} indoor pools into {db_path}"
    msg += " (with prices)" if prices is not None else " (prices unavailable)"
    if report.skipped:
        msg += f"; skipped {len(report.skipped)}: {', '.join(report.skipped)}"
    print(msg)
    return 0


def scrape_lanes(
    *,
    db_path: Path,
    client: HttpClient,
    fetched_at: datetime,
    urls: tuple[str, ...] = CITY_BELEGUNGSPLAN_URLS,
) -> int:
    """Fetch the per-basin Belegungsplan PDFs and attach the parsed lane plans onto the
    matching basins of an existing gold store. Best-effort on fetch/parse; loud on a hint
    that cannot be reconciled to a basin. Exit code."""
    if not db_path.exists():
        print(f"gold store not found at {db_path}; build it first", file=sys.stderr)
        return 1
    conn = open_db(db_path)
    facilities = GoldRepository(conn).load_all()
    if not facilities:
        print(f"gold store {db_path} is empty; build it first", file=sys.stderr)
        return 1

    report = scrape_lane_plans(client, urls)
    if not report.plans:
        skipped = f"; skipped {len(report.skipped)}" if report.skipped else ""
        print(f"no Belegungsplan PDFs could be parsed{skipped}", file=sys.stderr)
        return 1

    match attach_lane_plans(facilities, report.plans, fetched_at):
        case Err(error):
            print(f"lane-plan reconcile failed: {describe(error)}", file=sys.stderr)
            return 1
        case Ok(attachment):
            write_gold(conn, attachment.facilities)
            attached = sum(
                1 for f in attachment.facilities for b in f.basins if b.lane_plan is not None
            )
            msg = f"attached {attached} lane plan(s) into {db_path}"
            if report.skipped:
                msg += f"; skipped {len(report.skipped)}: {', '.join(report.skipped)}"
            print(msg)
            for warning in attachment.warnings:
                print(f"warning: {warning}", file=sys.stderr)
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swimzh")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gold = subparsers.add_parser("build-gold", help="build the SQLite gold store")
    gold.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    gold.add_argument("--data", default="data", help="curated data directory (default: data)")

    catalog = subparsers.add_parser("build-catalog", help="build the pool catalog from the WFS")
    catalog.add_argument("--out", default="data/catalog.json", help="catalog JSON to write")

    scrape = subparsers.add_parser(
        "scrape-gold", help="scrape indoor-pool schedules into a gold store"
    )
    scrape.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    scrape.add_argument("--catalog", default="data/catalog.json", help="catalog JSON to read")

    lanes = subparsers.add_parser(
        "scrape-lanes", help="attach per-basin Belegungsplan lane plans to a gold store"
    )
    lanes.add_argument("--db", required=True, help="path to the existing gold SQLite file")

    args = parser.parse_args(argv)

    # The network wiring below is exercised live; the per-command functions are unit-tested
    # with an injected client.
    import httpx  # pragma: no cover

    # follow_redirects: some pool pages (e.g. bad-altstetten.ch) redirect http→https.
    with httpx.Client(timeout=30.0, follow_redirects=True) as inner:  # pragma: no cover - live
        client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
        now = datetime.now(_ZURICH)
        if args.command == "build-gold":
            return build_gold(
                db_path=Path(args.db), data_dir=Path(args.data), client=client, fetched_at=now
            )
        if args.command == "scrape-gold":
            return scrape_gold(
                db_path=Path(args.db),
                catalog_path=Path(args.catalog),
                client=client,
                fetched_at=now,
            )
        if args.command == "scrape-lanes":
            return scrape_lanes(db_path=Path(args.db), client=client, fetched_at=now)
        return build_catalog_file(out=Path(args.out), client=client, generated_at=now)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
