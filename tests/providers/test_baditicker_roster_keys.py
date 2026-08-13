"""S4 acceptance — the Baditicker roster has NO dangling keys: every `baditicker_poiid`
declared in `data/registry.yaml` is a real `<poiid>` in the recorded feed fixture. A registry
key that the feed does not carry would silently resolve to `TempUnavailable`/no reading at
runtime — this test fails loudly at build/CI time instead."""

from __future__ import annotations

from pathlib import Path

import yaml

from swimzh.providers.baditicker import parse

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO / "data" / "registry.yaml"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "baditicker.xml"


def _declared_poiids() -> list[tuple[str, str]]:
    """(facility_id, baditicker_poiid) for every registry entry that declares a poiid."""
    doc = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    return [
        (str(f["facility_id"]), str(f["baditicker_poiid"]))
        for f in doc["facilities"]
        if f.get("baditicker_poiid") is not None
    ]


def _feed_poiids() -> set[str]:
    result = parse(_FIXTURE.read_bytes())
    assert result.is_ok(), result
    return set(result.unwrap_or_raise().keys())


def test_every_declared_poiid_exists_in_the_feed_fixture() -> None:
    feed = _feed_poiids()
    dangling = [(fid, poiid) for fid, poiid in _declared_poiids() if poiid not in feed]
    assert dangling == [], f"registry poiids absent from the recorded feed: {dangling}"


def test_declared_poiids_are_unique() -> None:
    # One poiid must not be claimed by two facilities (Baditicker is facility-granular): a
    # duplicate would mean two pools show the same reading. This is the guard that keeps the
    # deliberately-skipped "Flussbad Unterer Letten" (flb6940 + flb8803) honest.
    poiids = [poiid for _fid, poiid in _declared_poiids()]
    assert len(poiids) == len(set(poiids)), "a baditicker_poiid is claimed by two facilities"
