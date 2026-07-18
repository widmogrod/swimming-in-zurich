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
from swimzh.providers import geo_sport
from swimzh.storage import catalog_json

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swimzh")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gold = subparsers.add_parser("build-gold", help="build the SQLite gold store")
    gold.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    gold.add_argument("--data", default="data", help="curated data directory (default: data)")

    catalog = subparsers.add_parser("build-catalog", help="build the pool catalog from the WFS")
    catalog.add_argument("--out", default="data/catalog.json", help="catalog JSON to write")

    args = parser.parse_args(argv)

    # The network wiring below is exercised live; the per-command functions are unit-tested
    # with an injected client.
    import httpx  # pragma: no cover

    with httpx.Client(timeout=30.0) as inner:  # pragma: no cover - live network path
        client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
        now = datetime.now(_ZURICH)
        if args.command == "build-gold":
            return build_gold(
                db_path=Path(args.db), data_dir=Path(args.data), client=client, fetched_at=now
            )
        return build_catalog_file(out=Path(args.out), client=client, generated_at=now)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
