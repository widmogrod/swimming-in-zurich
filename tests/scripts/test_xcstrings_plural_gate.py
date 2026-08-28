"""The plural gate's own tests — and the golden that pins the `.xcstrings` shape.

Apple publishes no format specification for `.xcstrings`. The gate walks
`strings.<key>.localizations.<lang>.variations.plural.<category>` because that is what
`xcstringstool` emits and reads, which is an observation rather than a contract — so a
GOLDEN FIXTURE records the exact shape being parsed. If Apple ever changes it, the golden
diverges from the committed catalog and this file says so, instead of the gate silently
finding no plural entries and passing on everything.

The rest is the usual anti-vacuity work: a gate that never fails is worse than no gate,
so each failure mode it is supposed to catch is constructed and asserted to fail.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "xcstrings_plural_gate.py"
CATALOG = REPO_ROOT / "apps/ios/Sources/SwimZHKit/Resources/Localizable.xcstrings"
PLURALS_TS = REPO_ROOT / "apps/web/static/js/plurals.ts"


def _load() -> Any:
    """Import the gate by path — `scripts/` is a tool tree, not project source."""
    spec = importlib.util.spec_from_file_location("xcstrings_plural_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _catalog() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(CATALOG.read_text(encoding="utf-8"))
    return document


def _plural_key(catalog: dict[str, Any]) -> str:
    """The first key that actually carries plural variations."""
    for key, entry in sorted(catalog["strings"].items()):
        localizations = entry["localizations"]
        if any("variations" in unit for unit in localizations.values()):
            return str(key)
    raise AssertionError("the catalog carries no plural entry at all")


# --------------------------------------------------------------------------- the golden


def test_the_committed_catalog_has_the_shape_the_gate_parses() -> None:
    """The golden. Every path the gate walks, asserted to exist in the real file."""
    catalog = _catalog()
    assert catalog["sourceLanguage"] == "en"
    assert isinstance(catalog["strings"], dict) and catalog["strings"]

    key = _plural_key(catalog)
    entry = catalog["strings"][key]
    assert set(entry) >= {"extractionState", "localizations"}
    polish = entry["localizations"]["pl"]
    # The exact nesting `xcstringstool` produces, spelled out rather than traversed.
    assert set(polish["variations"]["plural"]) == {"one", "few", "many", "other"}
    form = polish["variations"]["plural"]["many"]
    assert set(form) == {"stringUnit"}
    assert set(form["stringUnit"]) == {"state", "value"}
    assert form["stringUnit"]["state"] == "translated"
    assert "%" in form["stringUnit"]["value"]

    # ...and a PLAIN entry's shape, which is the other half of what the gate skips over.
    plain = next(
        e for e in catalog["strings"].values() if "variations" not in e["localizations"]["en"]
    )
    assert set(plain["localizations"]["en"]["stringUnit"]) == {"state", "value"}


def test_the_real_catalog_passes_the_gate() -> None:
    assert gate.check(_catalog()) == []


def test_the_gate_runs_as_a_command_and_reports_the_path() -> None:
    """It is a build phase, so the EXIT CODE and the `error:` prefix are the interface."""
    result = subprocess.run(
        [sys.executable, str(GATE), str(CATALOG)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "conform to CLDR" in result.stdout


# ------------------------------------------------------------------- the CLDR table


def test_the_gates_cldr_table_matches_plurals_ts() -> None:
    """The gate keeps its own copy of `PLURAL_CATEGORIES`; this is what stops it drifting.

    It cannot import `plurals.ts` — it runs inside an Xcode build phase with no node and
    no `dist/` — so the copy is checked against the TypeScript source directly. A crude
    parse, deliberately: anything cleverer would be a TypeScript parser, and the shape it
    reads is five lines long and pinned by `plurals.test.ts` on the other side.
    """
    text = PLURALS_TS.read_text(encoding="utf-8")
    body = text.split("export const PLURAL_CATEGORIES = {", 1)[1].split("} as const", 1)[0]
    declared: dict[str, set[str]] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, categories = line.split(":", 1)
        declared[name.strip()] = {
            part.strip().strip('",') for part in categories.strip(" [],").split(",")
        }
    assert declared, "could not read PLURAL_CATEGORIES out of plurals.ts"
    assert {k: set(v) for k, v in gate.PLURAL_CATEGORIES.items()} == declared


# --------------------------------------------------------------- what the gate catches


def test_a_missing_polish_category_fails() -> None:
    """The whole reason this script exists: `many` gone, silently, in Polish."""
    catalog = deepcopy(_catalog())
    key = _plural_key(catalog)
    del catalog["strings"][key]["localizations"]["pl"]["variations"]["plural"]["many"]
    problems = gate.check(catalog)
    assert any("missing ['many']" in p and key in p for p in problems), problems


def test_an_extra_category_fails() -> None:
    """A form the language never selects is a translation written and never shown."""
    catalog = deepcopy(_catalog())
    key = _plural_key(catalog)
    catalog["strings"][key]["localizations"]["en"]["variations"]["plural"]["few"] = {
        "stringUnit": {"state": "translated", "value": "%1$lld"}
    }
    problems = gate.check(catalog)
    assert any("unexpected ['few']" in p for p in problems), problems


def test_a_form_that_does_not_interpolate_its_count_fails() -> None:
    """`xcstringstool` rejects this too, but only for the locale it happens to name."""
    catalog = deepcopy(_catalog())
    key = _plural_key(catalog)
    catalog["strings"][key]["localizations"]["de"]["variations"]["plural"]["one"] = {
        "stringUnit": {"state": "translated", "value": "eine Bahn"}
    }
    problems = gate.check(catalog)
    assert any("does not interpolate" in p for p in problems), problems


def test_a_missing_language_fails() -> None:
    catalog = deepcopy(_catalog())
    key = next(iter(catalog["strings"]))
    del catalog["strings"][key]["localizations"]["fr"]
    assert any("no translation for ['fr']" in p for p in gate.check(catalog))


def test_plural_in_one_locale_and_plain_in_another_fails() -> None:
    """One language silently loses its grammar while the rest keep theirs."""
    catalog = deepcopy(_catalog())
    key = _plural_key(catalog)
    catalog["strings"][key]["localizations"]["it"] = {
        "stringUnit": {"state": "translated", "value": "%1$lld corsie"}
    }
    assert any("plural in some locales" in p for p in gate.check(catalog))


def test_an_empty_catalog_fails_rather_than_passing_on_nothing() -> None:
    """A gate that reports success on an empty file is a gate that has stopped gating."""
    assert gate.check({"sourceLanguage": "en", "strings": {}}) == [
        "catalog is empty — the gate would pass on anything"
    ]
    assert gate.check({"nope": 1}) == [
        "catalog has no `strings` object — not an .xcstrings document?"
    ]


def test_a_missing_file_is_an_error_not_a_crash(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GATE), str(tmp_path / "nope.xcstrings")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("error: no string catalog")


def test_malformed_json_is_an_error_not_a_crash(tmp_path: Path) -> None:
    broken = tmp_path / "Localizable.xcstrings"
    broken.write_text("{not json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(GATE), str(broken)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "is not valid JSON" in result.stderr


def test_the_build_phase_really_invokes_this_script() -> None:
    """An instrument nothing calls measures nothing — the same check the launch signpost has."""
    project = REPO_ROOT / "apps/ios/App/SwimZH.xcodeproj/project.pbxproj"
    text = project.read_text(encoding="utf-8")
    assert "xcstrings_plural_gate.py" in text
    assert "Plural categories" in text
    # Before `Sources`, so a broken catalog is reported before anything else in the build.
    phases = text.split("buildPhases = (", 1)[1].split(");", 1)[0]
    assert phases.index("Plural categories") < phases.index("Sources")


@pytest.mark.parametrize("language", sorted(gate.PLURAL_CATEGORIES))
def test_every_language_is_present_in_the_committed_catalog(language: str) -> None:
    catalog = _catalog()
    for key, entry in catalog["strings"].items():
        assert language in entry["localizations"], f"{key} lacks {language}"
