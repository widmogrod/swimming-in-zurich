#!/usr/bin/env python3
"""CRAP gate: flag functions whose CRAP score exceeds the threshold.

    CRAP(f) = cc(f)^2 * (1 - cov(f))^3 + cc(f)

High complexity with low test coverage = change risk. Complexity comes from
``radon cc`` (dev dependency); per-function coverage is derived from the
``coverage.json`` that pytest-cov writes — so run pytest FIRST, this gate is
stale without it.

Config in pyproject.toml (CLI flags override):

    [tool.crap]
    threshold = 30.0        # functions scoring above this fail the gate
    min-complexity = 5      # functions at or below this cc are never flagged

Exits 1 when any function has cc > min-complexity AND crap > threshold.
Fix = add tests or reduce complexity.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 30.0
DEFAULT_MIN_COMPLEXITY = 5


@dataclass(frozen=True)
class Score:
    path: str
    lineno: int
    name: str
    complexity: int
    coverage: float
    crap: float


def crap_score(complexity: int, coverage: float) -> float:
    """Return ``cc**2 * (1 - cov)**3 + cc``."""
    uncovered = 1.0 - coverage
    return complexity**2 * uncovered**3 + complexity


def load_config(pyproject: Path) -> tuple[float, int]:
    if not pyproject.exists():
        return DEFAULT_THRESHOLD, DEFAULT_MIN_COMPLEXITY
    data = tomllib.loads(pyproject.read_text())
    cfg = data.get("tool", {}).get("crap", {})
    return (
        float(cfg.get("threshold", DEFAULT_THRESHOLD)),
        int(cfg.get("min-complexity", DEFAULT_MIN_COMPLEXITY)),
    )


def load_coverage(coverage_json: Path) -> dict[str, tuple[set[int], set[int]]]:
    """Map posix path -> (executed_lines, missing_lines)."""
    data = json.loads(coverage_json.read_text())
    out: dict[str, tuple[set[int], set[int]]] = {}
    for path, info in data.get("files", {}).items():
        out[Path(path).as_posix()] = (
            set(info.get("executed_lines", [])),
            set(info.get("missing_lines", [])),
        )
    return out


def run_radon(targets: list[str]) -> dict:
    proc = subprocess.run(
        ["radon", "cc", "--json", *targets],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def function_coverage(executed: set[int], missing: set[int], lineno: int, endline: int) -> float:
    span = range(lineno, endline + 1)
    covered = sum(1 for ln in span if ln in executed)
    uncovered = sum(1 for ln in span if ln in missing)
    statements = covered + uncovered
    if statements == 0:
        return 1.0  # no measurable statements => treated as fully covered
    return covered / statements


def collect_scores(radon_data: dict, coverage: dict) -> list[Score]:
    scores: list[Score] = []
    for path, blocks in radon_data.items():
        posix = Path(path).as_posix()
        executed, missing = coverage.get(posix, (set(), set()))
        for block in blocks:
            if block.get("type") not in ("function", "method"):
                continue
            name = block["name"]
            if block.get("type") == "method" and block.get("classname"):
                name = f"{block['classname']}.{name}"
            comp = block["complexity"]
            cov = function_coverage(executed, missing, block["lineno"], block["endline"])
            scores.append(Score(posix, block["lineno"], name, comp, cov, crap_score(comp, cov)))
    return scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", default=["src"])
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--min-complexity", type=int, default=None)
    parser.add_argument("--coverage-json", type=Path, default=Path("coverage.json"))
    parser.add_argument("--top", type=int, default=10, help="also show the N riskiest functions")
    args = parser.parse_args(argv)

    threshold, min_complexity = load_config(Path("pyproject.toml"))
    if args.threshold is not None:
        threshold = args.threshold
    if args.min_complexity is not None:
        min_complexity = args.min_complexity

    if not args.coverage_json.exists():
        print(
            f"{args.coverage_json} not found — run pytest first "
            "(this gate reads the coverage it writes).",
            file=sys.stderr,
        )
        return 2

    scores = collect_scores(run_radon(args.targets), load_coverage(args.coverage_json))
    scores.sort(key=lambda s: s.crap, reverse=True)
    offenders = [s for s in scores if s.complexity > min_complexity and s.crap > threshold]

    if args.top and scores:
        print(f"Top {min(args.top, len(scores))} riskiest functions:")
        for s in scores[: args.top]:
            print(
                f"  {s.path}:{s.lineno} {s.name} "
                f"(CRAP={s.crap:.1f}, CC={s.complexity}, cov={s.coverage:.0%})"
            )

    if offenders:
        print(
            f"\nFAIL: {len(offenders)} function(s) exceed "
            f"CRAP {threshold:g} with CC > {min_complexity}:"
        )
        for s in offenders:
            print(
                f"  {s.path}:{s.lineno} {s.name} "
                f"(CRAP={s.crap:.1f}, CC={s.complexity}, cov={s.coverage:.0%})"
            )
        print("Add tests or reduce complexity to bring these down.")
        return 1

    print(f"\nOK: no function exceeds CRAP {threshold:g} (with CC > {min_complexity}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
