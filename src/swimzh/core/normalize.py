"""The ONE cleaning home: pure, idempotent value / match-key normalization.

Hoists the byte-identical `_normalise` that was duplicated in `domain/registry.py` and
`etl/silver.py`, so alias-norm generation and reconcile lookup can never diverge — the
same key is produced wherever a name is matched.
"""

from __future__ import annotations


def normalize(text: str) -> str:
    """Canonical match key: strip, casefold, collapse internal whitespace.

    Idempotent by construction: ``normalize(normalize(x)) == normalize(x)``.
    """
    return " ".join(text.strip().casefold().split())
