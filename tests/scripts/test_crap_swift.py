"""The Swift CRAP gate's own tests — the four verified traps, and the token scan.

`scripts/` is a tool tree, not project source: it is outside `[tool.coverage.run]`
and outside mypy's `files`, so it is loaded here by path rather than imported. What
is asserted is what a broken gate would silently get wrong — an export with no
`functions` array, a per-function percentage that does not exist, a `var body` no
complexity tool but this one can see, and a complexity that can reach 0.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "crap_swift.py"


def _load(name: str, path: Path) -> Any:
    """Import a `scripts/` tool by path, registering it so `@dataclass` can resolve it."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


crap_swift = _load("crap_swift", GATE)


def declarations(source: str) -> dict[str, Any]:
    """The scan's result for one snippet, keyed by declaration name."""
    return {d.name: d for d in crap_swift.declarations(source, "Probe.swift")}


# --------------------------------------------------------------------------- #
# Trap 1 — the two flags that delete the `functions` array
# --------------------------------------------------------------------------- #


def test_llvm_cov_is_never_asked_to_drop_the_functions_array() -> None:
    args = crap_swift.llvm_cov_args(Path("/bin/Tests"), Path("/bin/default.profdata"))
    for flag in crap_swift.FORBIDDEN_COV_FLAGS:
        assert flag not in args, f"{flag} strips `functions` — the gate would score nothing"
    assert "-format=text" in args, "the text format IS the full JSON this gate needs"
    assert args[:3] == ["xcrun", "llvm-cov", "export"]
    assert str(Path("/bin/default.profdata")) in args


def test_an_export_without_functions_is_refused_rather_than_scored_as_clean() -> None:
    """A `--summary-only` export still parses and still carries files and totals."""
    summary_only = {"data": [{"files": [{"filename": "x.swift"}], "totals": {}}]}
    with pytest.raises(ValueError, match="no `functions` array"):
        crap_swift.functions_of(summary_only)
    with pytest.raises(ValueError, match="no `functions` array"):
        crap_swift.coverage_index(summary_only, "apps/ios")


# --------------------------------------------------------------------------- #
# Trap 2 — there is no per-function summary, so the fraction comes from regions
# --------------------------------------------------------------------------- #


def _region(line: int, count: int, kind: int = 0) -> list[int]:
    return [line, 1, line, 20, count, 0, 0, kind]


def test_the_fraction_comes_from_kind_zero_regions_not_from_a_summary() -> None:
    regions = [_region(10, 3), _region(11, 0), _region(12, 0), _region(13, 7, kind=2)]
    # 3 code regions, 1 of them executed. The `kind=2` region is NOT code and must
    # not dilute the fraction, either way.
    assert crap_swift.function_coverage(regions) == (1, 3)


def test_a_function_with_no_code_regions_is_not_invented_a_fraction_for() -> None:
    assert crap_swift.function_coverage([_region(4, 9, kind=1)]) is None


def test_a_function_entry_is_read_as_regions_and_nothing_else() -> None:
    """Guards the reason this gate does region arithmetic at all.

    There is no per-function `summary` and no per-function percentage in an llvm-cov
    export, so the whole fraction has to come out of the regions. This drives the real
    path — `coverage_index` — over a function entry carrying ONLY regions, which is what
    llvm-cov actually emits.
    """
    export = {
        "data": [
            {
                "functions": [
                    {
                        "name": "$s5Probe1fyyF",
                        "filenames": ["/repo/apps/ios/Sources/SwimZHKit/Probe.swift"],
                        "regions": [_region(7, 1), _region(8, 0)],
                        "count": 1,
                    }
                ]
            }
        ]
    }
    index = crap_swift.coverage_index(export, "apps/ios/Sources/SwimZHKit")
    assert index == {("apps/ios/Sources/SwimZHKit/Probe.swift", 7): (1, 2, "$s5Probe1fyyF")}


def test_functions_sharing_a_start_line_are_merged_not_overwritten() -> None:
    """A closure written on its enclosing body's brace line is a real shape."""
    export = {
        "data": [
            {
                "functions": [
                    {
                        "name": "$sBody",
                        "filenames": ["/repo/apps/ios/Sources/SwimZHKit/Probe.swift"],
                        "regions": [_region(7, 1)],
                    },
                    {
                        "name": "$sClosure",
                        "filenames": ["/repo/apps/ios/Sources/SwimZHKit/Probe.swift"],
                        "regions": [_region(7, 0), _region(8, 0)],
                    },
                ]
            }
        ]
    }
    index = crap_swift.coverage_index(export, "apps/ios/Sources/SwimZHKit")
    assert index[("apps/ios/Sources/SwimZHKit/Probe.swift", 7)] == (1, 3, "$sBody")


# --------------------------------------------------------------------------- #
# Trap 3 — a `var body` IS scored (SwiftLint's blind spot, and SwiftUI's home)
# --------------------------------------------------------------------------- #


BODY_PROPERTY = """\
struct RibbonRow: View {
  var body: some View {
    if session.isPublic && !session.isClosed {
      Text(session.title)
    } else if session.isClosed {
      Text("closed")
    }
  }

  func sameThing(_ session: Session) -> String {
    if session.isPublic && !session.isClosed {
      return session.title
    } else if session.isClosed {
      return "closed"
    }
    return ""
  }
}
"""


def test_a_var_body_is_scored_exactly_like_the_func_with_the_same_body() -> None:
    """The specific thing SwiftLint cannot see — and llvm-cov emits as a function.

    A getter-blind complexity source would let every rule in a SwiftUI project hide
    inside a computed property while the gate reported nothing.
    """
    found = declarations(BODY_PROPERTY)
    assert "body" in found, f"the `var body` was not scored: {sorted(found)}"
    assert found["body"].complexity == found["sameThing"].complexity
    assert found["body"].complexity == 4  # 1 + two `if` + one `&&`


def test_get_and_set_accessors_are_scored_separately_as_llvm_cov_reports_them() -> None:
    source = """\
struct Box {
  var value: Int {
    get {
      if cached { return stored }
      return compute()
    }
    set {
      stored = newValue
    }
  }
}
"""
    found = declarations(source)
    assert sorted(found) == ["value.get", "value.set"]
    assert found["value.get"].complexity == 2
    assert found["value.set"].complexity == 1
    # The join key is each accessor's own brace line, which is what llvm-cov reports.
    assert found["value.get"].line == 3
    assert found["value.set"].line == 7


def test_a_protocol_requirement_has_no_body_and_is_not_scored() -> None:
    source = """\
protocol Clocked {
  var now: Date { get }
  func advance(by seconds: Int) -> Date
}
"""
    assert declarations(source) == {}


# --------------------------------------------------------------------------- #
# Trap 4 — complexity starts at 1, so cc == 0 is impossible by construction
# --------------------------------------------------------------------------- #


def test_straight_line_code_scores_one_not_zero() -> None:
    """SwiftLint counts from 0: `0**2 * (1-0)**3 + 0 == 0` — a perfect score, forever.

    Starting at McCabe's 1 is what keeps completely untested code visible.
    """
    found = declarations("func trivial() -> Int {\n  return 41 + 1\n}\n")
    assert found["trivial"].complexity == 1
    assert crap_swift.crap_score(0, 0.0) == 0.0  # the number this gate must never emit
    assert crap_swift.crap_score(found["trivial"].complexity, 0.0) == 2.0


def test_no_declaration_can_ever_score_below_one() -> None:
    source = (REPO_ROOT / "apps/ios/Sources/SwimZHKit/Store.swift").read_text()
    decls = crap_swift.declarations(source, "Store.swift")
    assert decls, "the scan found nothing in Store.swift"
    assert min(d.complexity for d in decls) >= 1


# --------------------------------------------------------------------------- #
# The token scan itself
# --------------------------------------------------------------------------- #


def test_every_listed_decision_token_is_counted_once() -> None:
    source = """\
func everything(_ xs: [Int]) throws -> Int {
  guard !xs.isEmpty else { return 0 }
  for x in xs where x > 0 {
    while x < 10 {
      switch x {
      case 1: break
      case 2: break
      default: break
      }
    }
  }
  do {
    try risky()
  } catch {
    return -1
  }
  if a && b || c {
    return a ? 1 : 2
  }
  return 0
}
"""
    # 1 base + guard + for + while + 2 case + catch + if + && + || + ternary = 11
    assert declarations(source)["everything"].complexity == 11


def test_comments_and_string_literals_contribute_nothing() -> None:
    source = '''\
func quiet() -> String {
  // if guard for while case catch && || ? :
  /* if && || */
  let sql = "if guard && || ? : { case }"
  let multi = """
  if && || case
  """
  return sql + multi
}
'''
    assert declarations(source)["quiet"].complexity == 1


def test_optionals_and_argument_labels_are_not_decisions() -> None:
    """Every one of these is a `?` or a keyword that is NOT a branch."""
    source = """\
func noise(_ p: Person?) -> Int? {
  let a: Int? = p?.age
  let b = try? compute()
  let c = a ?? 0
  let d = store.each(for: day, if: flag)
  let e = value as? Int
  return c + d + (e ?? 0) + (b ?? 0)
}
"""
    assert declarations(source)["noise"].complexity == 1


def test_a_ternary_with_spaces_is_a_decision() -> None:
    source = "func pick(_ a: Bool) -> Int {\n  return a ? 1 : 2\n}\n"
    assert declarations(source)["pick"].complexity == 2


def test_a_nested_helper_is_scored_once_not_twice() -> None:
    source = """\
func outer(_ xs: [Int]) -> Int {
  func inner(_ x: Int) -> Int {
    if x > 0 { return x }
    return 0
  }
  if xs.isEmpty { return 0 }
  return xs.map(inner).reduce(0, +)
}
"""
    found = declarations(source)
    assert found["inner"].complexity == 2
    assert found["outer"].complexity == 2, "the nested `if` was counted twice"


def test_a_multi_line_signature_joins_on_its_body_brace_not_its_func_keyword() -> None:
    """Measured against llvm-cov: `Store.answer` is declared at 143, reported at 149."""
    source = """\
struct S {
  func answer(
    on day: Date,
    at instant: Date,
    for person: Person
  ) throws -> Answer {
    return Answer()
  }
}
"""
    assert declarations(source)["answer"].line == 6


def test_stored_properties_are_not_mistaken_for_computed_ones() -> None:
    source = """\
final class Model {
  private(set) var state: State = .loading
  private var store: Store?
  var cached = [String: Int]()

  func load() {
    state = .ready
  }
}
"""
    assert sorted(declarations(source)) == ["load"]


def test_an_init_is_scored_but_a_dot_init_reference_is_not() -> None:
    source = """\
struct Point {
  init?(text: String) {
    guard let value = Double(text) else { return nil }
    self.value = value
  }

  static func parse(_ xs: [String]) -> [Point] {
    return xs.compactMap(Point.init)
  }
}
"""
    found = declarations(source)
    assert sorted(found) == ["init", "parse"]
    assert found["init"].complexity == 2
    assert found["parse"].complexity == 1


# --------------------------------------------------------------------------- #
# Gate wiring
# --------------------------------------------------------------------------- #


def test_the_formula_is_the_one_scripts_crap_py_uses() -> None:
    """FORMULA parity is the claim this gate makes; metric parity it explicitly does not."""
    crap_py = _load("crap_py_gate", REPO_ROOT / "scripts" / "crap.py")
    for complexity, coverage in [(1, 0.0), (7, 0.5), (14, 1.0), (20, 0.83)]:
        assert crap_swift.crap_score(complexity, coverage) == pytest.approx(
            crap_py.crap_score(complexity, coverage)
        )


def test_the_configured_bar_is_the_same_thirty_over_five() -> None:
    threshold, min_complexity = crap_swift.load_config(REPO_ROOT / "pyproject.toml")
    assert (threshold, min_complexity) == (30.0, 5)


def test_the_gate_scores_the_kit_and_not_the_app_target() -> None:
    assert crap_swift.SOURCES.as_posix() == "apps/ios/Sources/SwimZHKit"
    scanned, escaped = crap_swift.scan(REPO_ROOT / crap_swift.SOURCES, REPO_ROOT)
    assert scanned, "the gate found no declarations to score"
    assert not any("App/SwimZH" in d.path for d in scanned)
    # No body escapes the scan in the kit as it stands. If a later slice adds one, the
    # gate PRINTS it and this test says so — the escape must be a decision, not a drift.
    assert escaped == [], f"unscanned bodies in SwimZHKit: {escaped}"


def test_a_property_whose_value_is_a_body_is_reported_not_silently_dropped() -> None:
    """`_body_brace` stops at the `=`, so these are never scored. They must be LOUD.

    Both shapes below have a real body and no `Decl`: a gate that dropped them without
    a word would report a shrinking, cleaner-looking kit while measuring less of it.
    """
    source = """\
struct Model {
  let transform: (Int) -> Int = { value in
    if value > 0 { return value }
    return 0
  }

  var count: Int = 0 {
    didSet {
      if count < 0 { count = 0 }
    }
  }

  func scored() -> Int { return count }
}
"""
    assert sorted(declarations(source)) == ["scored"]
    escaped = crap_swift.escaped_bodies(source, "Model.swift")
    assert [(name, line) for _, name, line in escaped] == [("transform", 2), ("count", 7)]


def test_an_ordinary_stored_property_is_not_reported_as_an_escape() -> None:
    """The report is only useful if it stays empty in the normal case."""
    source = """\
final class Model {
  private(set) var state: State = .loading
  let name: String = "swimzh"
  var cached = [String: Int]()
}
"""
    assert crap_swift.escaped_bodies(source, "Model.swift") == []


def test_the_offender_path_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    """The gate FAILING is the half that matters, and it is proved here, not only e2e.

    Driven through `main` with a threshold low enough that the kit's real functions
    offend, so the exit code, the FAIL banner and the offender lines are all exercised.
    """
    if not (REPO_ROOT / "apps/ios/.build").exists():
        pytest.skip("no `swift test --enable-code-coverage` output to read")
    assert crap_swift.main(["--threshold", "1", "--min-complexity", "1"]) == 1
    out = capsys.readouterr().out
    assert "FAIL:" in out
    assert "Add tests or reduce complexity" in out


def test_an_unjoined_declaration_is_scored_at_zero_percent_and_flagged() -> None:
    decl = crap_swift.Decl("apps/ios/Sources/SwimZHKit/Probe.swift", "orphan", 4, 6)
    [score] = crap_swift.collect_scores([decl], {}, "apps/ios/Sources/SwimZHKit")
    assert score.coverage == 0.0
    assert not score.joined
    assert score.crap == crap_swift.crap_score(6, 0.0)


def test_the_gate_is_green_against_the_committed_kit() -> None:
    """Runs the real gate end to end, so a regression in the join shows up here too.

    Skipped where the Swift toolchain is absent (the Python chain also runs on Linux
    CI); on a machine with Xcode this is the same command the Swift chain runs.
    """
    if not (REPO_ROOT / "apps/ios/.build").exists():
        pytest.skip("no `swift test --enable-code-coverage` output to read")
    proc = subprocess.run(
        [sys.executable, str(GATE)], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Every declaration the scan finds must join to an llvm-cov function. A join that
    # silently stopped matching would score the whole kit at 0% and read as a real
    # coverage collapse, so it is asserted rather than left to be puzzled over.
    assert "(0 with no llvm-cov entry, 0 unscanned bodies)" in proc.stdout, (
        f"the line join broke, or a body escaped the scan:\n{proc.stdout}"
    )
