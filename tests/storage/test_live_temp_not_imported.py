"""Live-only guard for the water-temperature reading (import-token scan).

Water temperature is LIVE-ONLY: the reading types (`TempReading`/`LiveTemp`/`TempUnavailable`)
live in `domain/query.py` and are resolved at request time — they must NEVER reach the gold
codec. This mirrors the occupancy live-only discipline.

Why a token scan and NOT a string-in-dump check (as the occupancy/lane-availability guard uses):
`identity.baditicker_poiid` — the *key* — IS deliberately persisted, so scanning `codec.dumps`
output for the substring "temp" would false-positive on the persisted key (and on the basin's
`nominal_temp_c`/`measured_temp_c`). The real invariant is that `storage/codec.py` never imports
the live reading types at all; an actual `from swimzh.domain.query import LiveTemp` line is the
violation, not a coincidental substring.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "swimzh"

_CODEC = SRC / "storage" / "codec.py"

# The live-only reading types that must not be imported by the gold codec. `baditicker_poiid` is
# NOT here — it is a persisted key, not a live reading.
_FORBIDDEN = ("TempReading", "LiveTemp", "TempUnavailable")


def test_codec_does_not_import_live_temp_types() -> None:
    source = _CODEC.read_text(encoding="utf-8")
    for name in _FORBIDDEN:
        # An actual import token, anchored — never a comment/docstring mention of the name.
        pattern = re.compile(rf"^(?:from|import)\s+.*\b{re.escape(name)}\b", re.MULTILINE)
        offending = [line for line in source.splitlines() if pattern.match(line.strip())]
        assert not offending, f"codec.py must not import the live-only type {name}: {offending}"


def test_codec_still_imports_query_nothing() -> None:
    # Falsifiability: the codec must not import from `domain.query` at all (that module is where
    # the live-only types live). If a future edit pulls query into the codec, this fires even for
    # a not-yet-listed live type.
    source = _CODEC.read_text(encoding="utf-8")
    offending = [
        line
        for line in source.splitlines()
        if re.match(r"^(?:from|import)\s+swimzh\.domain\.query\b", line.strip())
    ]
    assert not offending, f"codec.py must not import swimzh.domain.query (live-only): {offending}"
