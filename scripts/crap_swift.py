#!/usr/bin/env python3
"""CRAP gate for the Swift rule layer — FORMULA parity with ``scripts/crap.py``.

    CRAP(f) = cc(f)**2 * (1 - cov(f))**3 + cc(f)

Scores ``apps/ios/Sources/SwimZHKit/**`` ONLY. The thin Xcode app target is
deliberately excluded: a 36-line SwiftUI file reports ~48 executable lines, a view
body cannot be unit-tested headlessly, and calling one in-process crashes the test
runner — scoring it would poison the gate. It is the same stance ``vitest.config.ts``
takes when it excludes the four browser entrypoints while ``appdata.ts`` carries the
measured rules. ``SwimZHKit`` is this project's ``appdata.ts``: every rule lives
there, so the exclusion hides nothing.

Two inputs, joined on the function's BODY-BRACE line.

**Complexity** is this script's own token scan — ``if`` ``guard`` ``for`` ``while``
``case`` ``catch`` ``&&`` ``||`` ``? :``, starting at 1 (McCabe), walking ``func``,
``init``, ``subscript`` and brace-matched accessor bodies including ``var body``.

It is deliberately NOT a SwiftSyntax walker: that would add ``swift-syntax`` to the
package, toolchain-pinned and recompiled on every ``swift build``/``swift test`` in
the chain, to police one or two thousand lines. It is deliberately NOT SwiftLint
either, and that is a correctness argument rather than a dependency one — measured
against probe files, SwiftLint's ``cyclomatic_complexity`` counts decision points
from **0** rather than McCabe's 1 (so untested straight-line code scores
``0**2 * 1 + 0 = 0``, a perfect zero, forever), counts neither ``&&``/``||`` nor
ternaries, is **func-only** so it cannot see a ``var body``, and exposes the number
only inside a prose string. llvm-cov, meanwhile, emits computed-property getters as
first-class functions: the two tools would disagree about what a function *is*,
exactly where SwiftUI complexity lives.

Parity with the Python and TypeScript gates is FORMULA parity, not metric parity —
the count only has to be stable and honest, so ``[tool.crap-swift]`` is its own
no-regression ratchet, exactly as ``[tool.crap-ts]`` already is.

**Coverage** comes from ``swift test --enable-code-coverage`` + ``llvm-cov export
-format=text`` (which IS the full JSON). Four verified traps, each pinned by a test
in ``tests/scripts/test_crap_swift.py``:

* ``--summary-only`` and ``--skip-functions`` each strip the ``functions`` array
  entirely, so neither may ever be passed (see :func:`llvm_cov_args`).
* There is no per-function ``summary`` and no per-function percentage. The fraction
  is derived from the function's own code regions: ``kind == 0`` (region tuple index
  7), covered when the execution count (index 4) is non-zero.
* Function names are mangled; they are demangled with ``swift-demangle --compact``
  for the report only — the join never uses a name.
* The join key is the function's start line, which for a multi-line signature is the
  line of the body's opening brace, NOT the ``func`` keyword (measured:
  ``Store.answer`` is declared at 143 and reported by llvm-cov at 149).

Run it AFTER ``swift test --enable-code-coverage``. Like pytest->crap.py and
vitest->crap_ts.mjs, this gate is stale without the coverage that run writes.

Config in pyproject.toml (CLI flags override):

    [tool.crap-swift]
    threshold = 30.0        # functions scoring above this fail the gate
    min-complexity = 5      # functions at or below this cc are never flagged

Exits 1 when any function has cc > min-complexity AND crap > threshold.

Two known, deliberate limitations. Both are REPORTED rather than silent, because a
measurement that quietly stops covering something is worse than one that admits a
hole — the summary line counts each, and every instance is named:

* the scan is textual, so a declaration inside an ``#if os(...)`` block this host
  does not compile is scanned but has no coverage entry, and is scored at 0%
  ("no llvm-cov entry"). Platform-conditional code in ``SwimZHKit`` is kept trivial
  (cc 1-2) so it can never reach the gate on that account;
* a property whose value IS a body — ``let f: (Int) -> Int = { … }``, or a stored
  property with observers, ``var x: Int = 0 { didSet { … } }`` — is not scored at
  all, because :func:`_body_brace` stops at the ``=`` rather than risk swallowing a
  stored property's initialiser. :func:`escaped_bodies` finds those and the report
  names them ("unscanned body"). ``SwimZHKit`` has none today.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 30.0
DEFAULT_MIN_COMPLEXITY = 5

#: The only tree this gate scores (see the module docstring).
SOURCES = Path("apps/ios/Sources/SwimZHKit")
PACKAGE = Path("apps/ios")

#: Flags that silently strip the `functions` array out of an llvm-cov export.
#: Verified: either one alone leaves a JSON of files-and-totals with nothing to
#: score, which would make this gate pass vacuously.
FORBIDDEN_COV_FLAGS = ("--summary-only", "--skip-functions")

#: McCabe decision-point keywords. `else` is NOT among them (it adds no path its
#: `if` has not already counted), and neither is a `switch`'s `default`.
DECISION_WORDS = ("if", "guard", "for", "while", "case", "catch")


@dataclass(frozen=True)
class Decl:
    """A function-like declaration found by the token scan."""

    path: str
    name: str
    line: int  # the body's opening-brace line — the join key
    complexity: int


@dataclass(frozen=True)
class Score:
    path: str
    lineno: int
    name: str
    complexity: int
    coverage: float
    crap: float
    #: llvm-cov's MANGLED symbol for the joined function, or None when the scan found
    #: a declaration llvm-cov never reported. Demangled only for the report.
    symbol: str | None

    @property
    def joined(self) -> bool:
        return self.symbol is not None


def crap_score(complexity: int, coverage: float) -> float:
    """Return ``cc**2 * (1 - cov)**3 + cc`` — identical to ``scripts/crap.py``."""
    uncovered = 1.0 - coverage
    return complexity**2 * uncovered**3 + complexity


def load_config(pyproject: Path) -> tuple[float, int]:
    if not pyproject.exists():
        return DEFAULT_THRESHOLD, DEFAULT_MIN_COMPLEXITY
    data = tomllib.loads(pyproject.read_text())
    cfg = data.get("tool", {}).get("crap-swift", {})
    return (
        float(cfg.get("threshold", DEFAULT_THRESHOLD)),
        int(cfg.get("min-complexity", DEFAULT_MIN_COMPLEXITY)),
    )


# --------------------------------------------------------------------------- #
# Complexity: a token scan over source with comments and string literals masked
# --------------------------------------------------------------------------- #


def _blank(text: str) -> str:
    """`text` with every character replaced by a space, newlines preserved."""
    return "".join("\n" if ch == "\n" else " " for ch in text)


def _end_of_block_comment(source: str, start: int) -> int:
    """Index just past the `*/` closing the (nestable) comment opened at `start`."""
    depth, i, n = 1, start + 2, len(source)
    while i < n and depth:
        if source.startswith("/*", i):
            depth += 1
            i += 2
        elif source.startswith("*/", i):
            depth -= 1
            i += 2
        else:
            i += 1
    return i


def _end_of_string(source: str, start: int) -> int:
    """Index just past the `"` closing the literal opened at `start`."""
    i, n = start + 1, len(source)
    while i < n:
        if source[i] == "\\":
            i += 2
        elif source[i] == '"':
            return i + 1
        elif source[i] == "\n":
            return i
        else:
            i += 1
    return n


def mask(source: str) -> str:
    """Return `source` with comments and string literals blanked out.

    Line numbers and brace structure survive, so the scan can both brace-match and
    report real line numbers. Masking is what keeps a `//` comment explaining a
    `guard` from counting as one, and a `{` inside a string from derailing the
    matcher. Raw string literals (`#"..."#`) are not special-cased: `SwimZHKit` has
    none, and the failure mode would be a mis-masked line, never a silent zero.
    """
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
        elif source.startswith("/*", i):
            end = _end_of_block_comment(source, i)
        elif source.startswith('"""', i):
            end = source.find('"""', i + 3)
            end = n if end < 0 else end + 3
        elif source[i] == '"':
            end = _end_of_string(source, i)
        else:
            out.append(source[i])
            i += 1
            continue
        out.append(_blank(source[i:end]))
        i = end
    return "".join(out)


_TERNARY = re.compile(r"(?<=\s)\?(?=\s)")
_WORDS = re.compile(r"\b(" + "|".join(DECISION_WORDS) + r")\b(?!\s*:)")


def decision_points(code: str) -> int:
    r"""Count McCabe decision points in already-masked `code`.

    The `(?!\s*:)` on the keywords is what stops an argument label — `answer(for: p)`,
    `each(for: day)` — from being counted as a `for` loop; a `case` pattern is
    unaffected, because its colon never follows the keyword directly.

    The ternary is matched as a `?` with whitespace on BOTH sides, which is exactly
    what separates it from `Int?`, `a?.b`, `try? f()` and `??` (whose second `?` is
    preceded by a `?`, and whose first is followed by one).
    """
    words = len(_WORDS.findall(code))
    return words + code.count("&&") + code.count("||") + len(_TERNARY.findall(code))


_DECL = re.compile(r"(?<![\w.])(func|init|subscript|var)\b")
_NAME = re.compile(r"\s*([A-Za-z_]\w*|[-+*/<>=!%&|^~?]+)")
_ACCESSOR = re.compile(r"(get|set|willSet|didSet)\b")
#: A property block holding only these is a protocol requirement, not a body.
_REQUIREMENT = re.compile(r"\b(get|set|throws|async|mutating|nonmutating)\b|\s")


def _match_brace(code: str, open_index: int) -> int:
    """Index of the `}` matching the `{` at `open_index`, or len(code)."""
    depth, i, n = 0, open_index, len(code)
    while i < n:
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _body_brace(code: str, start: int) -> int | None:
    """Index of the `{` opening the body of the declaration starting at `start`.

    The brace must arrive before the declaration ends — that is, before the first
    newline or `=` seen OUTSIDE `(`/`[`. That one rule covers every shape at once: a
    multi-line signature keeps its newlines inside its parens, a stored property
    stops at its `=`, and a body-less `var` stops at the end of its own line instead
    of swallowing the next declaration's brace. Angle brackets are deliberately NOT
    tracked: `->` and `<` are not always brackets, and a generic parameter list
    contains no braces to be confused by.
    """
    depth, i, n = 0, start, len(code)
    while i < n:
        ch = code[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth <= 0:
            if ch == "{":
                return i
            if ch in "\n=":
                return None
        i += 1
    return None


def _accessor_bodies(code: str, brace: int, close: int) -> list[tuple[str, int, int]]:
    """The `get`/`set`/`willSet`/`didSet` bodies directly inside a property block.

    llvm-cov reports a simple computed property as ONE function starting at the
    property's own brace, but `var x: T { get { … } set { … } }` as TWO, each at its
    own accessor brace. Mirroring that is what makes the line join work either way.

    An accessor keyword counts only at statement position — right after the block's
    `{`, or after the previous accessor's `}` — so a `dict.get(k)` inside an implicit
    getter can never be mistaken for one.
    """
    found: list[tuple[str, int, int]] = []
    i = brace + 1
    while i < close:
        if code[i].isspace():
            i += 1
            continue
        match = _ACCESSOR.match(code, i)
        if match is None:
            break
        inner = code.find("{", match.end())
        if inner < 0 or inner >= close:
            break
        end = _match_brace(code, inner)
        found.append((match.group(1), inner, end))
        i = end + 1
    return found


def _property_spans(
    code: str, name: str, brace: int, close: int
) -> list[tuple[str, int, int, int]]:
    """The scored bodies of one `var`: its accessors, or the block itself."""
    accessors = _accessor_bodies(code, brace, close)
    if accessors:
        return [(f"{name}.{a}", b, c, code.count("\n", 0, b) + 1) for a, b, c in accessors]
    if not _REQUIREMENT.sub("", code[brace + 1 : close]):
        return []  # `var x: Int { get }` — a requirement, with no body to score
    return [(name, brace, close, code.count("\n", 0, brace) + 1)]


def _spans(code: str) -> list[tuple[str, int, int, int]]:
    """(name, body brace index, body close index, brace line) for every declaration."""
    spans: list[tuple[str, int, int, int]] = []
    for match in _DECL.finditer(code):
        kind = match.group(1)
        name_match = _NAME.match(code, match.end())
        name = name_match.group(1) if name_match and kind != "init" else kind
        brace = _body_brace(code, match.end())
        if brace is None:
            continue
        close = _match_brace(code, brace)
        if kind == "var":
            spans.extend(_property_spans(code, name, brace, close))
        else:
            spans.append((name, brace, close, code.count("\n", 0, brace) + 1))
    return spans


def _own_points(code: str, brace: int, close: int, spans: list[tuple[str, int, int, int]]) -> int:
    """Decision points in [brace, close) less those of the declarations nested in it."""
    total = decision_points(code[brace:close])
    for _, inner_brace, inner_close, _ in spans:
        if brace < inner_brace and inner_close <= close:
            total -= decision_points(code[inner_brace:inner_close])
    return total


def declarations(source: str, path: str) -> list[Decl]:
    """Every function-like declaration in `source`, with its OWN complexity.

    "Own": a nested `func` or computed property is scored as its own entry and its
    decision points are subtracted from the enclosing one, so a helper is never
    counted twice. Closures deliberately stay with their enclosing declaration —
    llvm-cov does emit them as separate functions, but at lines this scan has no
    declaration for, so leaving them in the parent is the honest attribution.
    """
    code = mask(source)
    spans = _spans(code)
    return [
        Decl(path, name, line, 1 + _own_points(code, brace, close, spans))
        for name, brace, close, line in spans
    ]


#: Declaration modifiers that may precede a stored property. The `(set)` spellings come
#: first, or the bare word would match and leave `(set)` behind.
_MODIFIER = (
    r"(?:@\w+(?:\([^)]*\))?|private\(set\)|public\(set\)|internal\(set\)"
    r"|public|private|internal|fileprivate|open|static|class|final|lazy|weak|unowned"
    r"|nonisolated|override)"
)

#: A property whose value IS a body: `let f: (Int) -> Int = { … }`, or a stored property
#: with observers, `var x: Int = 0 { didSet { … } }`. `_body_brace` stops at the `=` in
#: both, by design — the alternative is swallowing a stored property's initialiser — so
#: neither is scored. That is a silent escape, and this is what makes it loud.
#:
#: Anchored to the start of a line (through the modifiers) so an optional binding —
#: `guard let pool = pools[id] else { … }`, of which `Store.swift` has many — cannot be
#: mistaken for a declaration with a body: `guard` is not a modifier, so the anchor fails.
_ESCAPED_BODY = re.compile(
    rf"^[ \t]*(?:{_MODIFIER}\s+)*(?:let|var)\s+([A-Za-z_]\w*)[^\n=]*=\s*"
    r"(?:\{|[^\n{]*\{\s*(?:will|did)Set)",
    re.MULTILINE,
)


def escaped_bodies(source: str, path: str) -> list[tuple[str, str, int]]:
    """(path, name, line) for property bodies the scan walks past without scoring.

    Reported, never scored: scoring them would mean deciding where a closure's body ends
    versus its enclosing initialiser, which is the ambiguity `_body_brace` exists to
    refuse. `SwimZHKit` has none today; the point is that adding one is visible in the
    gate's own output rather than as a function that quietly stopped being measured.

    Exactly the two shapes above are detected. A trailing-closure initialiser —
    `let x = Foo(a: 1) { … }` — is not, because its brace is an ARGUMENT rather than the
    property's body, and llvm-cov emits it as an ordinary closure like any other.
    """
    code = mask(source)
    return [
        (path, match.group(1), code.count("\n", 0, match.start()) + 1)
        for match in _ESCAPED_BODY.finditer(code)
    ]


def scan(root: Path, relative_to: Path) -> tuple[list[Decl], list[tuple[str, str, int]]]:
    """Every declaration under `root`, RECURSIVELY, and every body that escaped it.

    Recursion is load-bearing: a new `Sources/SwimZHKit/Store/` subdirectory must not
    slip out of the gate simply by being one level down.
    """
    found: list[Decl] = []
    escaped: list[tuple[str, str, int]] = []
    for path in sorted(root.rglob("*.swift")):
        source = path.read_text()
        relative = path.relative_to(relative_to).as_posix()
        found.extend(declarations(source, relative))
        escaped.extend(escaped_bodies(source, relative))
    return found, escaped


# --------------------------------------------------------------------------- #
# Coverage: llvm-cov export, joined on the body-brace line
# --------------------------------------------------------------------------- #


def llvm_cov_args(binary: Path, profdata: Path) -> list[str]:
    """The exact `llvm-cov export` argv this gate uses.

    Factored out so a test can assert what it must never contain: `--summary-only`
    and `--skip-functions` each drop the `functions` array, leaving a JSON this gate
    would happily score as zero findings.
    """
    return [
        "xcrun",
        "llvm-cov",
        "export",
        "-format=text",
        "-instr-profile",
        str(profdata),
        str(binary),
    ]


def code_regions(regions: list[list[int]]) -> list[list[int]]:
    """The CODE regions of a function: tuple index 7 (`kind`) == 0."""
    return [r for r in regions if len(r) > 7 and r[7] == 0]


def function_coverage(regions: list[list[int]]) -> tuple[int, int] | None:
    """(covered, total) over a function's CODE regions, or None when it has none.

    There is no per-function `summary` and no per-function percentage in an llvm-cov
    export — this arithmetic is the only route to a per-function fraction. A region
    tuple is [lineStart, colStart, lineEnd, colEnd, execCount, fileID,
    expandedFileID, kind]; execCount > 0 means the region was covered.
    """
    code = code_regions(regions)
    if not code:
        return None
    return sum(1 for r in code if r[4] > 0), len(code)


def functions_of(export: dict) -> list[dict]:
    """The export's `functions` array — the thing the two forbidden flags delete.

    An export made with `--summary-only` or `--skip-functions` still parses, still
    carries `files` and `totals`, and would score as zero findings. Refusing it is
    the difference between a gate and a green light.
    """
    functions = export["data"][0].get("functions")
    if not functions:
        raise ValueError(
            "the llvm-cov export carries no `functions` array — it was produced with "
            f"one of {FORBIDDEN_COV_FLAGS}, and there is nothing to score"
        )
    return functions


def coverage_index(export: dict, marker: str) -> dict[tuple[str, int], tuple[int, int, str]]:
    """Map (path from `marker` onwards, start line) -> (covered, total, mangled name).

    Entries sharing a start line — a closure written on the same line as the body it
    lives in — are merged, rather than one silently overwriting the other; the first
    name at that line is kept, which is the enclosing function's own.
    """
    index: dict[tuple[str, int], tuple[int, int, str]] = {}
    for function in functions_of(export):
        filename = next((f for f in function["filenames"] if marker in f), None)
        counts = function_coverage(function["regions"]) if filename else None
        if filename is None or counts is None:
            continue
        start = min(r[0] for r in code_regions(function["regions"]))
        key = (filename[filename.index(marker) :], start)
        covered, total, name = index.get(key, (0, 0, function["name"]))
        index[key] = (covered + counts[0], total + counts[1], name)
    return index


def demangle(names: list[str]) -> list[str]:
    """Swift names as written, for the report. The join never uses them."""
    if not names:
        return []
    proc = subprocess.run(
        ["xcrun", "swift-demangle", "--compact"],
        input="\n".join(names),
        capture_output=True,
        text=True,
        check=False,
    )
    lines = proc.stdout.splitlines()
    return lines if len(lines) == len(names) else names


def collect_scores(
    decls: list[Decl], coverage: dict[tuple[str, int], tuple[int, int, str]], marker: str
) -> list[Score]:
    """Join the scan to the coverage on (file, start line) and score each declaration."""
    scores: list[Score] = []
    for decl in decls:
        relative = decl.path[decl.path.index(marker) :] if marker in decl.path else decl.path
        counts = coverage.get((relative, decl.line))
        # A declaration llvm-cov never reported was never compiled into the tested
        # binary — platform-conditional, or dead. 0% is the honest score, and the
        # missing symbol makes it visible in the report instead of silent.
        cov = (counts[0] / counts[1]) if counts and counts[1] else 0.0
        scores.append(
            Score(
                path=decl.path,
                lineno=decl.line,
                name=decl.name,
                complexity=decl.complexity,
                coverage=cov,
                crap=crap_score(decl.complexity, cov),
                symbol=counts[2] if counts else None,
            )
        )
    return scores


# --------------------------------------------------------------------------- #


def _run(args: list[str], cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_binary(bin_path: Path) -> Path:
    """The built test bundle's executable (macOS wraps it in the bundle, Linux does not)."""
    bundles = sorted(bin_path.glob("*.xctest"))
    if not bundles:
        raise FileNotFoundError(f"no .xctest bundle in {bin_path} — run `swift test` first")
    inner = bundles[0] / "Contents" / "MacOS" / bundles[0].stem
    return inner if inner.exists() else bundles[0]


def load_export(package: Path) -> dict:
    """Run `llvm-cov export` over what `swift test --enable-code-coverage` wrote.

    The profdata path is DERIVED from `swift test --show-codecov-path` rather than
    hardcoded: it carries the build triple (`.build/arm64-apple-macosx/debug/...`),
    which differs per host and would silently miss on a CI runner.
    """
    codecov = Path(_run(["swift", "test", "--show-codecov-path"], package))
    profdata = codecov.parent / "default.profdata"
    if not profdata.exists():
        raise FileNotFoundError(
            f"{profdata} not found — run `swift test --enable-code-coverage` first "
            "(this gate reads the coverage that run writes)."
        )
    binary = test_binary(Path(_run(["swift", "build", "--show-bin-path"], package)))
    export: dict = json.loads(_run(llvm_cov_args(binary, profdata), package))
    functions_of(export)  # fail loudly rather than score an export with nothing in it
    return export


def readable(scores: list[Score]) -> list[str]:
    """Report names: llvm-cov's mangled symbol demangled, or the scan's own name."""
    written = demangle([s.symbol or s.name for s in scores])
    return [
        w if s.joined else f"{s.name} (not in the coverage export)"
        for s, w in zip(scores, written, strict=True)
    ]


def _line(score: Score, name: str) -> str:
    return (
        f"  {score.path}:{score.lineno} {name} "
        f"(CRAP={score.crap:.1f}, CC={score.complexity}, cov={score.coverage:.0%})"
    )


def _report(scores: list[Score], escaped: list[tuple[str, str, int]], top: int) -> None:
    unjoined = [s for s in scores if not s.joined]
    print(
        f"Scored {len(scores)} declarations "
        f"({len(unjoined)} with no llvm-cov entry, {len(escaped)} unscanned bodies)."
    )
    for s in unjoined:
        print(f"  no llvm-cov entry: {s.path}:{s.lineno} {s.name} (CC={s.complexity}, scored 0%)")
    for path, name, line in escaped:
        print(f"  unscanned body: {path}:{line} {name} (a `= {{ … }}` property — NOT scored)")
    shown = scores[:top]
    if not shown:
        return
    print(f"Top {len(shown)} riskiest functions:")
    for score, name in zip(shown, readable(shown), strict=True):
        print(_line(score, name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRAP gate for apps/ios/Sources/SwimZHKit")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--min-complexity", type=int, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--top", type=int, default=10, help="also show the N riskiest functions")
    args = parser.parse_args(argv)

    threshold, min_complexity = load_config(args.repo_root / "pyproject.toml")
    if args.threshold is not None:
        threshold = args.threshold
    if args.min_complexity is not None:
        min_complexity = args.min_complexity

    marker = SOURCES.as_posix()
    decls, escaped = scan(args.repo_root / SOURCES, args.repo_root)
    if not decls:
        print(f"FAIL: no Swift declarations found under {marker}", file=sys.stderr)
        return 2

    index = coverage_index(load_export(args.repo_root / PACKAGE), marker)
    scores = sorted(collect_scores(decls, index, marker), key=lambda s: s.crap, reverse=True)
    offenders = [s for s in scores if s.complexity > min_complexity and s.crap > threshold]
    _report(scores, escaped, args.top)

    if offenders:
        print(f"\nFAIL: {len(offenders)} exceed CRAP {threshold:g} with CC > {min_complexity}:")
        for score, name in zip(offenders, readable(offenders), strict=True):
            print(_line(score, name))
        print("Add tests or reduce complexity to bring these down.")
        return 1

    print(f"\nOK: no function exceeds CRAP {threshold:g} (with CC > {min_complexity}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
