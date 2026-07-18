"""Shared pytest config. The `vcr_config` fixture governs cassette recording/replay for
any `@pytest.mark.vcr` test (pytest-recording).

Record mode `once`: the first run with an absent cassette records real HTTP ("paid"); every
run thereafter replays from the committed cassette, offline and deterministic. Sensitive
headers are scrubbed so cassettes are safe to commit.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def vcr_config() -> dict[str, object]:
    return {
        "record_mode": "once",
        "filter_headers": ["authorization", "cookie", "set-cookie"],
        "decode_compressed_response": True,
    }
