#!/usr/bin/env python3
"""Size budget gate for the iOS app — TWO numbers, ratcheted separately.

    uv run python scripts/ios_budget.py <path to SwimZH.app>

`app_minus_sqlite` is the **unsigned proxy**: every Mach-O image's `__TEXT` segment
(via `size -m`, the same number Apple's executable limit is stated in) plus every
bundled resource, minus the store. `sqlite` is the store's own size.

Two numbers rather than one, because a weekly data refresh must never mask a code
regression: `ios.sqlite` grows with the horizon, the binary grows with the app, and
one combined figure would let either hide inside the other.

**A proxy, deliberately.** The number that matters to a user is the thinned,
compressed download, and Apple is blunt that the `.app`, `.xcarchive` and `.ipa` all
carry files nobody receives. But that figure comes from `xcodebuild -exportArchive`,
which needs a signing identity and profile CI has not got, and bringing signing into
scope to police a 1-3 MB app against a 30 MB ceiling is not worth it. The proxy
tracks CODE GROWTH faithfully, which is what a ratchet is for. The real thinned
number is read once from App Store Connect at the first upload; a material
divergence between the two is a finding, not a gate failure.

It is measured on whatever configuration built the bundle — the gate's
`xcodebuild … test` builds Debug — so the absolute number is larger than a release
build's. That is fine and is the point: a ratchet compares like with like across
runs, it does not predict the store listing.

Run by a Run Script build phase on the app target, so it fires inside the chain's
closing `xcodebuild … test` with no extra step to forget. Exits 1 on a regression.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: The bundled pre-resolved export, wherever the resource bundle puts it.
STORE_NAME = "ios.sqlite"

#: Mach-O magics: 64-bit LE/BE, 32-bit LE/BE, and both fat headers.
MACHO_MAGICS = (
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
)

_TEXT_SEGMENT = re.compile(r"^Segment __TEXT: (\d+)", re.MULTILINE)

#: Test-injection artifacts, which `xcodebuild … test` copies INTO the app bundle and no
#: user ever downloads. Measured: they add ~8.8 MB of `__TEXT` — twice the whole ratchet —
#: so counting them would make the gate meaningless in the one command that runs it.
#: A `.xctest` bundle is excluded wherever it appears; inside `Frameworks/` only the XCTest
#: support family is, so a REAL embedded framework added later is still measured.
TEST_SUPPORT = re.compile(r"^(XC|libXCTest|Testing\.framework)")


def is_test_artifact(relative: Path) -> bool:
    """True for a file `xcodebuild … test` injected that a shipped build would not have."""
    parts = relative.parts
    if any(part.endswith(".xctest") for part in parts):
        return True
    return len(parts) > 1 and parts[0] == "Frameworks" and bool(TEST_SUPPORT.match(parts[1]))


@dataclass(frozen=True)
class Measurement:
    """What one built `.app` weighs, split so a data refresh cannot mask code growth."""

    app_minus_sqlite: int
    sqlite: int
    text_bytes: int
    resource_bytes: int


def is_macho(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) in MACHO_MAGICS


def text_size(path: Path) -> int:
    """The `__TEXT` segment size(s) `size -m` reports for a Mach-O file.

    Summed across slices, so a fat binary is counted whole rather than once.
    """
    proc = subprocess.run(["size", "-m", str(path)], capture_output=True, text=True, check=True)
    return sum(int(match) for match in _TEXT_SEGMENT.findall(proc.stdout))


def measure(app: Path) -> Measurement:
    """Walk the bundle once, splitting it into code, resources and the store."""
    text = resources = store = 0
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if is_test_artifact(path.relative_to(app)):
            continue
        if path.name == STORE_NAME:
            store += path.stat().st_size
        elif is_macho(path):
            text += text_size(path)
        else:
            resources += path.stat().st_size
    return Measurement(
        app_minus_sqlite=text + resources,
        sqlite=store,
        text_bytes=text,
        resource_bytes=resources,
    )


def check(measurement: Measurement, budgets: dict) -> list[str]:
    """The budget lines that regressed, as human-readable failures (empty == green)."""
    actual = {"app_minus_sqlite": measurement.app_minus_sqlite, "sqlite": measurement.sqlite}
    failures = []
    for name, value in actual.items():
        limit = int(budgets[name]["limit_bytes"])
        if value > limit:
            over = value - limit
            failures.append(
                f"{name}: {value:,} B exceeds the {limit:,} B ratchet by {over:,} B "
                f"({value / limit:.2f}x). Reduce it, or raise the ratchet DELIBERATELY "
                f"in apps/ios/budgets.json and say why."
            )
    return failures


def record(measurement: Measurement, budgets: dict) -> dict:
    """Write today's measurement back into the budget file (never during a build)."""
    budgets["app_minus_sqlite"]["measured_bytes"] = measurement.app_minus_sqlite
    budgets["sqlite"]["measured_bytes"] = measurement.sqlite
    return budgets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="the built SwimZH.app bundle")
    parser.add_argument(
        "--budgets",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "apps" / "ios" / "budgets.json",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="update `measured_bytes` in the budget file (a human action, never a build's)",
    )
    args = parser.parse_args(argv)

    if not args.app.is_dir():
        print(f"budget gate: {args.app} is not a built .app bundle", file=sys.stderr)
        return 2

    budgets = json.loads(args.budgets.read_text())
    measurement = measure(args.app)
    print(
        f"iOS size budget: app_minus_sqlite={measurement.app_minus_sqlite:,} B "
        f"(__TEXT {measurement.text_bytes:,} + resources {measurement.resource_bytes:,}), "
        f"sqlite={measurement.sqlite:,} B"
    )

    if args.record:
        args.budgets.write_text(json.dumps(record(measurement, budgets), indent=2) + "\n")
        print(f"budget gate: recorded into {args.budgets}")

    failures = check(measurement, budgets)
    for failure in failures:
        print(f"budget gate: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
