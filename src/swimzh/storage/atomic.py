"""Atomic gold-store writes: build into a temp file, swap over the live store only on success.

Every build/scrape command assembles its result in a temp DB **beside** the target and, ONLY on
full success (`staging.commit()`), atomically ``os.replace``s it over the live file. Any mid-run
abort — a typed provider failure returned as a value, or an exception — discards the temp and
leaves the prior gold store **content-unchanged**: the fail-fast, all-or-nothing-fresh invariant
(owner decision 2026-07-28). This is the mechanism S4 uses to guarantee "no partial write": the
live file is never mutated in place, so a build that fails halfway never holds a half-written or
stale-but-green dataset.

The temp always starts EMPTY: every command that writes a store is a from-scratch build composed
from the lake (`swimzh build`, and the `scrape-gold` / `scrape-lanes` wrappers over it), so there
is no "layer onto a byte-copy of the live store" mode any more — a store is only ever a pure
function of the lake's silver plus `data/`.

``os.replace`` is atomic only within one filesystem, so the temp is always created in the
target's own directory (never ``/tmp``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkstemp


@dataclass(slots=True)
class Staging:
    """A pending atomic write. ``path`` is the temp DB the command writes into; the live target is
    replaced with it at context exit **iff** ``commit()`` was called and no exception escaped."""

    path: Path
    _committed: bool = False

    def commit(self) -> None:
        """Mark the staged store good: the atomic swap happens on clean context exit."""
        self._committed = True

    @property
    def committed(self) -> bool:
        return self._committed


@contextmanager
def atomic_swap(target: str | Path) -> Iterator[Staging]:
    """Yield a :class:`Staging` whose temp DB atomically replaces ``target`` only on ``commit()``.

    On any exception, or if ``commit()`` was never called, the temp is discarded and ``target`` is
    left content-unchanged (for a from-scratch build of a not-yet-existing target, it stays
    absent).
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    staging = Staging(path=tmp)
    try:
        yield staging
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if staging.committed:
        os.replace(tmp, target)
    else:
        tmp.unlink(missing_ok=True)
