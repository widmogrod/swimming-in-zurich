"""The `DaySchedule` exhaustiveness meta-test (sharedsource-fanout S1).

`DaySchedule` is a closed union that consumers destructure with statement-level `match` — and
statement matches have NO implicit exhaustiveness: before this slice, `mypy .` was green with
every site unguarded, so a new variant would have fallen through silently (empty hours, a
dropped status). mypy alone therefore proves nothing here; what makes the NEXT variant a
compile error is that every match ends in `case _ as unreachable: assert_never(unreachable)` —
once the wildcard exists, mypy must prove it unreachable, which fails the moment the union
grows. This test walks the AST of every module under `src/` and `apps/` and asserts exactly
that shape on every match that names a `DaySchedule` variant in any of its case patterns.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = (_REPO / "src", _REPO / "apps")
_VARIANTS = frozenset({"OpenDay", "OpenUnscheduledDay", "ClosedDay"})

# The three sites the plan names (plus any the scan finds beyond them). Paths are
# repo-relative; each must contain at least one guarded DaySchedule match.
_NAMED_SITES = {
    "src/swimzh/domain/query.py",
    "apps/web/api/pools/service.py",
}


def _pattern_names(pattern: ast.pattern) -> set[str]:
    """Every class name a case pattern mentions (MatchClass, incl. nested/Or patterns)."""
    names: set[str] = set()
    for node in ast.walk(pattern):
        if isinstance(node, ast.MatchClass):
            cls = node.cls
            if isinstance(cls, ast.Name):
                names.add(cls.id)
            elif isinstance(cls, ast.Attribute):
                names.add(cls.attr)
    return names


def _is_assert_never_wildcard(case: ast.match_case) -> bool:
    """`case _ as unreachable:` (or a bare capture) whose body calls `assert_never`.

    `_ as x` parses as `MatchAs(pattern=MatchAs(pattern=None, name=None), name='x')` — the
    wildcard `_` is itself a nameless `MatchAs` — so accept both the bare capture and the
    wildcard-wrapping form.
    """
    pattern = case.pattern
    if not isinstance(pattern, ast.MatchAs):
        return False
    inner = pattern.pattern
    is_wildcard_as = isinstance(inner, ast.MatchAs) and inner.pattern is None and inner.name is None
    if not (inner is None or is_wildcard_as):
        return False
    for stmt in ast.walk(case):
        if isinstance(stmt, ast.Call):
            func = stmt.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "assert_never":
                return True
    return False


def _dayschedule_matches(tree: ast.Module) -> list[ast.Match]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Match)
        and any(_pattern_names(case.pattern) & _VARIANTS for case in node.cases)
    ]


def test_every_dayschedule_match_in_src_and_apps_ends_in_assert_never() -> None:
    offenders: list[str] = []
    guarded_files: set[str] = set()
    for root in _SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for match in _dayschedule_matches(tree):
                rel = str(path.relative_to(_REPO))
                if _is_assert_never_wildcard(match.cases[-1]):
                    guarded_files.add(rel)
                else:
                    offenders.append(f"{rel}:{match.lineno}")
    assert not offenders, (
        "DaySchedule match without a terminal `case _ as unreachable: assert_never(...)` — "
        f"a new variant would fall through silently at: {offenders}"
    )
    # The scan must actually SEE the named sites: a refactor that stops matching on the
    # union (or moves the files) has to be looked at, not silently pass an empty scan.
    assert guarded_files >= _NAMED_SITES, f"expected guarded matches missing: {guarded_files}"


def test_the_scanner_recognises_an_unguarded_match() -> None:
    """The meta-test's own trap: prove the scanner FAILS an unguarded site, so a green run
    means 'every site is guarded', not 'the scanner matched nothing'."""
    bad = ast.parse(
        "def f(s):\n"
        "    match s:\n"
        "        case OpenDay(sessions):\n"
        "            return sessions\n"
        "        case ClosedDay():\n"
        "            return ()\n"
    )
    matches = _dayschedule_matches(bad)
    assert len(matches) == 1
    assert not _is_assert_never_wildcard(matches[0].cases[-1])

    good = ast.parse(
        "def f(s):\n"
        "    match s:\n"
        "        case OpenDay(sessions):\n"
        "            return sessions\n"
        "        case OpenUnscheduledDay() | ClosedDay():\n"
        "            return ()\n"
        "        case _ as unreachable:\n"
        "            assert_never(unreachable)\n"
    )
    assert _is_assert_never_wildcard(_dayschedule_matches(good)[0].cases[-1])
