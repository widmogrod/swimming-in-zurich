"""`SILVER_SCHEMA` must move when a silver payload's SHAPE moves.

A silver document written under one schema is decoded by the codec of that schema only
(`storage/lake.read` treats any other schema as absent). That guarantee is worth nothing if a
codec can change what it carries while the number stays put — which is exactly how the
2026-09-06 audit's `poi_id` loss would have hidden behind a published lake. So the key-shape of
every payload is pinned here against a committed fixture, together with the schema number.

Changing a payload deliberately: bump `SILVER_SCHEMA`, then regenerate the fixture with
`SILVER_SHAPE_WRITE=1 uv run pytest tests/etl/test_silver_schema.py`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from swimzh.cli import build
from swimzh.storage.lake import SILVER_SCHEMA, SILVER_SOURCES, Lake
from tests.pipeline_clients import recorded_build_clients

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "silver_shape.json"
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_T0 = datetime(2026, 8, 31, 5, 0, tzinfo=ZoneInfo("Europe/Zurich"))


def _shape(value: Any, prefix: str = "") -> set[str]:
    """Every key path a payload can carry, list items merged (a list is one shape)."""
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= _shape(child, path)
        return paths
    if isinstance(value, list):
        paths = set()
        for item in value:
            paths |= _shape(item, f"{prefix}[]")
        return paths
    return set()


@pytest.fixture(scope="module")
def silver_shapes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[str]]:
    root = tmp_path_factory.mktemp("silver-shape")
    lake = Lake(root / "lake")
    code = build(
        db_path=root / "gold.sqlite",
        data_dir=_DATA_DIR,
        clients=recorded_build_clients(),
        lake=lake,
        now=_T0,
    )
    assert code == 0
    shapes: dict[str, list[str]] = {}
    for source in SILVER_SOURCES:
        doc = lake.read(source)
        assert doc is not None, source
        shapes[source] = sorted(_shape(doc.payload))
    return shapes


def test_every_payload_shape_is_pinned_to_the_schema_number(
    silver_shapes: dict[str, list[str]],
) -> None:
    current = {"schema": SILVER_SCHEMA, "shapes": silver_shapes}
    if os.environ.get("SILVER_SHAPE_WRITE") == "1":
        _FIXTURE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pinned = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for source in SILVER_SOURCES:
        added = sorted(set(silver_shapes[source]) - set(pinned["shapes"][source]))
        removed = sorted(set(pinned["shapes"][source]) - set(silver_shapes[source]))
        assert not added and not removed, (
            f"silver payload {source!r} changed shape (added {added}, removed {removed}) — "
            f"bump SILVER_SCHEMA and regenerate: SILVER_SHAPE_WRITE=1 uv run pytest {__file__}"
        )
    assert pinned["schema"] == SILVER_SCHEMA, (
        f"SILVER_SCHEMA is {SILVER_SCHEMA} but the pinned shapes are schema {pinned['schema']}; "
        f"regenerate: SILVER_SHAPE_WRITE=1 uv run pytest {__file__}"
    )


def test_the_pinned_roster_shape_carries_the_wfs_poi_id() -> None:
    # The specific field whose loss the schema exists to catch.
    pinned = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert "entries[].poi_id" in pinned["shapes"]["roster"]
