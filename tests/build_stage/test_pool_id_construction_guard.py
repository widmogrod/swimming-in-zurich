"""Grep-guard: a canonical `PoolId` may be constructed ONLY at the two minting seams.

Honesty (docs/concepts/data-layer-architecture.md §3): `PoolId` is a `NewType` with no
private constructor — mypy accepts `PoolId("anything")` anywhere. The real lock is the DB
`UNIQUE` constraint (see tests/storage/test_pool_spine.py); this grep is the by-convention
layer above it, reusing the repo's existing "no `data/` reads at runtime" guard pattern. It
fails loudly if a third site starts minting ids, keeping reconcile + seed the only doors.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "swimzh"

# `PoolId(` but not `PoolIdentity(` — the char after the id must be an open paren.
_CONSTRUCT = re.compile(r"\bPoolId\(")

# The only two sites allowed to mint a canonical id.
ALLOWED = {Path("build") / "reconcile.py", Path("build") / "seed.py"}


def test_pool_id_is_constructed_only_in_reconcile_and_seed() -> None:
    offenders: dict[str, int] = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if rel in ALLOWED:
            continue
        hits = len(_CONSTRUCT.findall(path.read_text(encoding="utf-8")))
        if hits:
            offenders[str(rel)] = hits
    assert not offenders, (
        f"PoolId(...) constructed outside the seed loader + reconcile: {offenders}. "
        "Route ids through build.reconcile.resolve or build.seed instead."
    )


def test_the_allowed_seams_actually_mint_pool_ids() -> None:
    # Guard the guard: if the minting moved and these files stopped constructing PoolId, the
    # test above would pass vacuously. Assert the seams still are where ids are made.
    for rel in ALLOWED:
        assert _CONSTRUCT.search((SRC / rel).read_text(encoding="utf-8")), rel
