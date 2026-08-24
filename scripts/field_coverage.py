"""Generate the iOS field-coverage contract from the web response models.

The iOS app re-renders what `/swim` and `/pools` serve. Nothing about the two clients makes
them notice when the other grows a field — the web adds `OptionOut.foo`, the phone silently
keeps not showing it, and the gap is discovered by a user rather than by a gate.

So the field list is GENERATED from the pydantic models, committed, and asserted from both
sides:

* :mod:`apps.web.tests.test_field_coverage_contract` asserts the committed JSON still equals
  what the models generate. Adding a field to ``OptionOut`` fails there — that is the
  staleness gate, and without it the whole mechanism would be decorative.
* ``apps/ios/Tests/SwimZHKitTests/FieldCoverageTests.swift`` asserts that
  ``renderedFields ∪ deliberatelyOmitted`` equals exactly this file's fields and that the two
  sets are disjoint. A new field therefore has to be *classified* — rendered, or omitted with
  a stated reason — before the Swift suite goes green again.

`renderedFields` is a hand-maintained declaration, so this proves **drift detection against
the web models**, not that any pixel is drawn.

IMPORT RULE, and it is load-bearing: this module imports the MODEL modules only, never
``apps.web.main``. The app fails fast without ``SWIMZH_GOLD_DB``, so importing it would make
the generator unrunnable on a fresh checkout — the exact situation the committed fixture
exists for. The model modules import pydantic and nothing else.

Field names are QUALIFIED (``OptionOut.facility``), which is what lets the four models share
one flat set: ``OptionOut`` and ``StatusOut`` both declare ``facility``, and an unqualified
union would silently collapse them into one entry that either side could satisfy by covering
the wrong model.

Run it with ``make ios-field-coverage``, or through the staleness gate::

    SWIMZH_REGENERATE_FIELD_COVERAGE=1 uv run pytest \\
        apps/web/tests/test_field_coverage_contract.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from apps.web.api.pools.model import FacilityDetailOut, PoolOut  # noqa: E402
from apps.web.api.swim.model import OptionOut, StatusOut  # noqa: E402
from pydantic import BaseModel  # noqa: E402

#: Where the Swift suite reads it from. Under `Tests/`, beside the other generated contracts,
#: and `exclude`d from the SwiftPM target so it is read from the repository by path rather
#: than copied into a bundle where it could go stale.
FIXTURE = _ROOT / "apps/ios/Tests/SwimZHKitTests/Fixtures/field_coverage.json"

#: The four response models the iOS app must reproduce. `FacilityDetailOut` is here even
#: though S3a does not render it: the S3b detail sheet must be governed by the mechanism from
#: the slice before it, so its fields start life in `deliberatelyOmitted` and the Swift test
#: enforces the move.
MODELS: tuple[type[BaseModel], ...] = (OptionOut, StatusOut, PoolOut, FacilityDetailOut)

_NOTE = (
    "GENERATED from the pydantic response models by scripts/field_coverage.py — do NOT "
    "hand-edit. The staleness gate is apps/web/tests/test_field_coverage_contract.py; the "
    "consumer is apps/ios/Tests/SwimZHKitTests/FieldCoverageTests.swift, which asserts "
    "renderedFields u deliberatelyOmitted == fields and that the two are disjoint. "
    "Regenerate with SWIMZH_REGENERATE_FIELD_COVERAGE=1 uv run pytest "
    "apps/web/tests/test_field_coverage_contract.py"
)


def model_fields(model: type[BaseModel]) -> list[str]:
    """One model's declared field names, sorted.

    `model_fields` is pydantic v2's own view of the model, so a field that is renamed,
    dropped or aliased moves here without anyone remembering to update a list.
    """
    return sorted(model.model_fields)


def contract() -> dict[str, Any]:
    """The whole contract: per-model field names plus the flat, qualified union."""
    models = {model.__name__: model_fields(model) for model in MODELS}
    fields = sorted(f"{name}.{field}" for name, fs in models.items() for field in fs)
    return {"_note": _NOTE, "models": models, "fields": fields}


def render() -> str:
    return json.dumps(contract(), indent=2, ensure_ascii=False) + "\n"


def write(path: Path = FIXTURE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - the make target's entry point
    write()
    print(f"wrote {FIXTURE.relative_to(_ROOT)}")
