"""Import-direction guard: the layering is `core -> domain -> storage -> build -> etl -> apps`.

A wrong (upward) edge is a module in a LOW layer importing a HIGH one. Plan A removed the two
backwards edges into `build`:

- `domain/** -> swimzh.build`  (forbidden — domain sits below build)
- `storage/** -> swimzh.build` (forbidden — storage sits below build)

`etl/** -> swimzh.build` is a legitimate DOWNWARD edge (`etl` is above `build`) and is ALLOWED —
`etl/build.py` and `etl/scrape.py` import from `swimzh.build` on purpose.

The scan matches the actual import *tokens* (`from swimzh.build ...` / `import swimzh.build ...`),
not a bare substring, so a docstring mentioning the `swimzh build-catalog` CLI (see
`storage/catalog_json.py`) is never a false hit. A violation looks like a real
`from swimzh.build.seed import build_spine` line appearing under `domain/` or `storage/`.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "swimzh"

# Matches an actual import statement pulling in the `swimzh.build` package (or a submodule),
# anchored at the start of a (stripped) line — never a comment or a docstring mention.
_IMPORTS_BUILD = re.compile(r"^(?:from|import)\s+swimzh\.build(?:\.|\s|$)")


def _modules_importing_build(package_dir: Path) -> list[str]:
    offenders: list[str] = []
    for path in package_dir.rglob("*.py"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            if _IMPORTS_BUILD.match(raw.strip()):
                offenders.append(str(path.relative_to(SRC)))
                break
    return offenders


def test_domain_does_not_import_build() -> None:
    offenders = _modules_importing_build(SRC / "domain")
    assert not offenders, f"domain/** must not import swimzh.build (backwards edge): {offenders}"


def test_storage_does_not_import_build() -> None:
    offenders = _modules_importing_build(SRC / "storage")
    assert not offenders, f"storage/** must not import swimzh.build (backwards edge): {offenders}"


def test_etl_may_import_build() -> None:
    # etl sits ABOVE build, so etl -> build is a legitimate downward edge; the guard must not
    # forbid it. This asserts the token matcher actually fires on the real etl import sites, so
    # the guard above is genuinely scanning source (falsifiable), not vacuously passing.
    assert _modules_importing_build(SRC / "etl"), "expected etl/** to import swimzh.build"
