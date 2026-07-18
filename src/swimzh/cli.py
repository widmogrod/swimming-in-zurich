"""Command-line entry point.

  swimzh build-gold    --db gold.sqlite     # raw→silver→gold SQLite the web app serves from
  swimzh build-catalog --out data/catalog.json  # full pool catalog from the WFS (committed)

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
from swimzh.etl.scrape import scrape_indoor_facilities
from swimzh.providers import geo_sport
from swimzh.providers.price_scraper import scrape_prices
from swimzh.storage import catalog_json
from swimzh.storage.sqlite_repo import open_db

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
        return build_catalog_file(out=Path(args.out), client=client, generated_at=now)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
