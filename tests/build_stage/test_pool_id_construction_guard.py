"""Grep-guard: a canonical `PoolId` may be constructed ONLY at three sanctioned doors.

Honesty (docs/concepts/data-layer-architecture.md §3): `PoolId` is a `NewType` with no
private constructor — mypy accepts `PoolId("anything")` anywhere. The real lock is the DB
`UNIQUE` constraint (see tests/storage/test_pool_spine.py); this grep is the by-convention
layer above it, reusing the repo's existing "no `data/` reads at runtime" guard pattern.

Two doors *mint* an id from an external ref: `build/reconcile.py` (lookup by `SourceRef`) and
`build/seed.py` (the catalog loader). One door *reconstructs* an id already minted upstream —
`domain/models.py`, whose `reconstruct_pool_id(str) -> PoolId` shim re-wraps a canonical id read
back from a persisted gold row / validated DTO; its body constructs a `PoolId`, so its home is
in the allow-set. Trusted call-sites (codec, curated provider, query) route through that shim by
NAME (`reconstruct_pool_id(...)`, lowercase — not matched here), so they never construct a raw
`PoolId(...)` themselves. The guard fails loudly if any *other* site starts minting ids.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "swimzh"

# `PoolId(` but not `PoolIdentity(` — the char after the id must be an open paren. Note
# `reconstruct_pool_id(` is lowercase and deliberately does NOT match: the shim's callers are
# routing through the boundary, not constructing an id.
_CONSTRUCT = re.compile(r"\bPoolId\(")

# The only sites allowed to construct a canonical id: the two minting seams + the single
# reconstruction shim's home.
ALLOWED = {
    Path("build") / "reconcile.py",
    Path("build") / "seed.py",
    Path("domain") / "models.py",
}


def test_pool_id_is_constructed_only_in_reconcile_seed_and_shim() -> None:
    offenders: dict[str, int] = {}
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if rel in ALLOWED:
            continue
        hits = len(_CONSTRUCT.findall(path.read_text(encoding="utf-8")))
        if hits:
            offenders[str(rel)] = hits
    assert not offenders, (
        f"PoolId(...) constructed outside the minting seams + reconstruction shim: {offenders}. "
        "Mint via build.reconcile.resolve / build.seed, or reconstruct via "
        "domain.models.reconstruct_pool_id instead."
    )


def test_the_allowed_seams_actually_construct_pool_ids() -> None:
    # Guard the guard: if construction moved and these files stopped constructing PoolId, the
    # test above would pass vacuously. Assert the sanctioned doors still are where ids are made.
    for rel in ALLOWED:
        assert _CONSTRUCT.search((SRC / rel).read_text(encoding="utf-8")), rel
