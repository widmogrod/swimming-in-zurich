"""Command-line entry point. `build-gold` runs the medallion pipeline against the live WFS
and writes the SQLite gold store the web app can then serve from.

Run: `uv run python -m swimzh.cli build-gold --db gold.sqlite`
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swimzh")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-gold", help="build the SQLite gold store")
    build.add_argument("--db", required=True, help="path to the gold SQLite file to write")
    build.add_argument("--data", default="data", help="curated data directory (default: data)")
    args = parser.parse_args(argv)

    # build-gold is the only (required) subcommand; the network wiring is exercised live,
    # while build_gold() itself is unit-tested with an injected client.
    import httpx  # pragma: no cover

    with httpx.Client(timeout=30.0) as inner:  # pragma: no cover - live network path
        client = HttpClient(inner, source="geo_sport", timeout_s=30.0)
        return build_gold(
            db_path=Path(args.db),
            data_dir=Path(args.data),
            client=client,
            fetched_at=datetime.now(_ZURICH),
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
