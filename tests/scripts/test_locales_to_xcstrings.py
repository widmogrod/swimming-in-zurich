"""S4 acceptance 1: the iOS catalog IS the web catalogs, projected.

The claim "every key in `locales/en.ts` exists in the `.xcstrings` for all five locales"
is a claim about a TypeScript module, and re-parsing TypeScript from Python or Swift would
be a second, worse parser. So it is asserted where the projection is made: the converter
regenerates the catalog from the compiled `dist/locales/*.js` and diffs it against the
committed file. If a key is added to `en.ts` and the catalog is not regenerated, `--check`
fails here — the same staleness discipline `test_field_coverage_contract.py` gives the
field-coverage fixture and `test_eligibility_ui_contract.py` gives the eligibility one.

WHY IT SKIPS RATHER THAN FAILS without `dist/`: the TypeScript build output is git-ignored,
and the Python chain does not build it. `make ios-qa` builds it and runs this, which is
where the gate has teeth; a fresh checkout running `uv run pytest` alone should not fail on
an artifact it was never asked to produce. The skip message names the command.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONVERTER = REPO_ROOT / "scripts" / "locales_to_xcstrings.mjs"
DIST = REPO_ROOT / "apps/web/static/dist/locales"
CATALOG = REPO_ROOT / "apps/ios/Sources/SwimZHKit/Resources/Localizable.xcstrings"
TABLE = REPO_ROOT / "apps/ios/Sources/SwimZHKit/Catalog.generated.swift"
LOCALES = ["en", "de", "fr", "it", "pl"]

# The RESOLVED path, not the bare name: a bare "node" is a partial executable path (ruff
# S607), and resolving it once here also makes the skip below and the call sites agree about
# which interpreter they mean.
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
needs_dist = pytest.mark.skipif(
    not (DIST / "en.js").exists(),
    reason="apps/web/static/dist is not built — run `npm --prefix apps/web/static/js run build`",
)


def _node(*arguments: str) -> str:
    """Run node with `arguments` and return its stdout. Fails loudly on a non-zero exit."""
    assert NODE is not None
    result = subprocess.run([NODE, *arguments], capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _english_keys() -> list[str]:
    """The key set of `dist/locales/en.js`, read by node because it is an ES module."""
    keys = json.loads(
        _node(
            "-e",
            "import(process.argv[1]).then(m => console.log(JSON.stringify(Object.keys(m.en))))",
            str(DIST / "en.js"),
        )
    )
    assert isinstance(keys, list)
    return [str(key) for key in keys]


def _catalog_strings() -> dict[str, object]:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    strings = document["strings"]
    assert isinstance(strings, dict)
    return strings


@needs_node
@needs_dist
def test_the_committed_catalog_is_not_stale() -> None:
    """The gate. Regenerate from the web catalogs; the committed files must be identical."""
    assert NODE is not None
    result = subprocess.run(
        [NODE, str(CONVERTER), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        "the iOS catalog is stale — regenerate with "
        f"`node scripts/locales_to_xcstrings.mjs`\n{result.stderr}"
    )


@needs_node
@needs_dist
def test_every_english_key_reaches_the_catalog_in_all_five_locales() -> None:
    """Acceptance 1, stated as itself rather than as a diff.

    The staleness check above would already catch a missing key, but only by reporting
    "the file differs" — which is true of a comment change too. This says which key.
    """
    keys = _english_keys()
    assert len(keys) > 200, f"only {len(keys)} keys in en.ts — is dist stale?"

    catalog = _catalog_strings()
    missing = [key for key in keys if key not in catalog]
    assert not missing, f"absent from Localizable.xcstrings: {missing}"
    for key in keys:
        entry = catalog[key]
        assert isinstance(entry, dict)
        localizations = set(entry["localizations"])
        assert localizations >= set(LOCALES), f"{key} lacks {set(LOCALES) - localizations}"


@needs_node
@needs_dist
def test_the_catalog_carries_nothing_the_web_does_not() -> None:
    """The other direction: no iOS-only key may accumulate.

    It is what keeps "the phone renders THIS catalog" true. A key added straight to the
    `.xcstrings` would be untranslated by every gate the web has — its plural categories
    unchecked by `tsc`, its placeholders unchecked by `parity.test.ts`.
    """
    keys = set(_english_keys())
    catalog = set(_catalog_strings())
    assert catalog - keys == set(), f"iOS-only keys: {sorted(catalog - keys)}"


@needs_node
@needs_dist
def test_the_generated_swift_table_is_regenerated_too() -> None:
    """Two outputs, one pass. A hand-edited table would renumber arguments silently."""
    assert TABLE.exists()
    text = TABLE.read_text(encoding="utf-8")
    assert "GENERATED by scripts/locales_to_xcstrings.mjs" in text
    # Every key in the catalog appears in the table, spelled the same way.
    for key in _catalog_strings():
        assert f'"{key}": Entry(' in text, f"{key} is missing from Catalog.generated.swift"


@needs_node
def test_the_converter_refuses_a_plural_entry_with_no_count() -> None:
    """`xcstringstool` rejects one too — but only after a build, and only by locale.

    This is the converter's own guard, and it is the one that caught `panel.clubSlot`:
    a plural entry naming lanes without counting them cannot compile, and Apple's own
    advice is two top-level keys instead.
    """
    script = (
        f"import {{ buildDocument }} from {json.dumps(str(CONVERTER))};"
        "const one = { 'k': { one: 'a lane', other: 'lanes' } };"
        "try { buildDocument({ en: one, de: one, fr: one, it: one, pl: one });"
        "  console.log('NO ERROR'); } catch (e) { console.log(e.message); }"
    )
    assert "must interpolate {count}" in _node("--input-type=module", "-e", script)


@needs_node
def test_the_converter_numbers_placeholders_by_the_english_order() -> None:
    """A translation may reorder its placeholders; the ARGUMENTS must not move with them."""
    script = (
        f"import {{ buildDocument }} from {json.dumps(str(CONVERTER))};"
        "const en = { 'k': 'opens {hhmm} at {place}' };"
        "const de = { 'k': 'im {place} ab {hhmm}' };"
        "const doc = buildDocument({ en, de, fr: en, it: en, pl: en });"
        "console.log(JSON.stringify({"
        "  en: doc.strings.k.localizations.en.stringUnit.value,"
        "  de: doc.strings.k.localizations.de.stringUnit.value }));"
    )
    out = json.loads(_node("--input-type=module", "-e", script))
    assert out["en"] == "opens %1$@ at %2$@"
    # The German puts the PLACE first, and it is still argument 2.
    assert out["de"] == "im %2$@ ab %1$@"


@needs_node
def test_a_literal_percent_is_escaped() -> None:
    """Unescaped, `%` is read as a specifier and prints whatever is next on the stack."""
    script = (
        f"import {{ toFormat }} from {json.dumps(str(CONVERTER))};"
        "console.log(toFormat('50% of lanes', [], false));"
    )
    assert _node("--input-type=module", "-e", script).strip() == "50%% of lanes"


def test_infoplist_purpose_strings_are_generated_in_every_language() -> None:
    """The permission purpose string ships localised, not in English for everyone.

    iOS renders a purpose string in the SYSTEM's language, so the build setting that declares
    it can only ever be one language. `InfoPlist.xcstrings` is what makes the other four real,
    and it is generated from the same web catalogs as every other sentence — a hand-edited one
    would be the second catalog this whole bridge exists to prevent.
    """
    path = REPO_ROOT / "apps/ios/App/SwimZH/InfoPlist.xcstrings"
    if not path.exists():
        pytest.skip("InfoPlist.xcstrings not generated; run `make ios-locales`")
    document = json.loads(path.read_text(encoding="utf-8"))
    entry = document["strings"]["NSLocationWhenInUseUsageDescription"]
    assert set(entry["localizations"]) == {"en", "de", "fr", "it", "pl"}
    for language, unit in entry["localizations"].items():
        value = unit["stringUnit"]["value"]
        assert value.strip(), f"{language} has an empty purpose string"
        # A purpose string is one plain sentence: iOS has nowhere to put an argument in it,
        # and a stray placeholder would be shown to the reader verbatim.
        assert "{" not in value, f"{language} purpose string carries a placeholder"


def test_the_base_infoplist_key_matches_the_english_catalog() -> None:
    """The Info.plist build setting and the catalog cannot drift apart.

    Both are needed and they are written in different places. `InfoPlist.xcstrings` OVERRIDES a
    value per language; it does not DECLARE one, so without the key in Info.plist itself iOS
    treats the permission as undeclared and the prompt never appears at all. The build setting
    is therefore the English original, and this is what stops someone editing `en.ts` and
    shipping a phone that asks in the old words.
    """
    path = REPO_ROOT / "apps/ios/App/SwimZH/InfoPlist.xcstrings"
    if not path.exists():
        pytest.skip("InfoPlist.xcstrings not generated; run `make ios-locales`")
    english = json.loads(path.read_text(encoding="utf-8"))["strings"][
        "NSLocationWhenInUseUsageDescription"
    ]["localizations"]["en"]["stringUnit"]["value"]
    project = (REPO_ROOT / "apps/ios/App/SwimZH.xcodeproj/project.pbxproj").read_text(
        encoding="utf-8"
    )
    setting = f'INFOPLIST_KEY_NSLocationWhenInUseUsageDescription = "{english}";'
    # COUNTED, not merely `in`: the key is written once per build configuration (Debug and
    # Release), and a substring test over the whole file passes when only ONE of the two
    # matches — which is exactly the silent one-config drift this test exists to catch. Xcode
    # edits a single configuration readily, and a Release build asking in the old words while
    # Debug asks in the new ones is invisible to a developer running Debug.
    configurations = project.count("INFOPLIST_KEY_NSLocationWhenInUseUsageDescription = ")
    assert configurations == 2, (
        "expected the purpose string in exactly 2 build configurations (Debug + Release), "
        f"found {configurations}"
    )
    assert project.count(setting) == 2, (
        "the Info.plist purpose string differs from the English catalog in at least one build "
        f"configuration — expected BOTH to read:\n  {setting}"
    )


def test_xcode_does_not_regenerate_the_infoplist_catalog() -> None:
    """`SWIFT_EMIT_LOC_STRINGS` is off in every app configuration — and off exactly once.

    `InfoPlist.xcstrings` is GENERATED by `scripts/locales_to_xcstrings.mjs`. With this setting
    on, Xcode rewrites it during a build, which dirties the tree on every build and fails
    `make ios-locales-check` for a change nobody made.

    The count is the point. A pbxproj dict may carry the same key twice and the LAST one wins,
    so an added `= NO` beside a surviving `= YES` resolves to YES while reading, in a diff, as
    if the setting had been turned off. Both configurations must say NO and nothing may say
    YES.
    """
    project = (REPO_ROOT / "apps/ios/App/SwimZH.xcodeproj/project.pbxproj").read_text(
        encoding="utf-8"
    )
    assert project.count("SWIFT_EMIT_LOC_STRINGS = YES;") == 0, (
        "SWIFT_EMIT_LOC_STRINGS = YES lets Xcode rewrite the generated InfoPlist.xcstrings"
    )
    assert project.count("SWIFT_EMIT_LOC_STRINGS = NO;") == 2, (
        "expected SWIFT_EMIT_LOC_STRINGS = NO in exactly 2 build configurations (Debug + "
        "Release) of the app target"
    )


def test_the_project_needs_no_signing_identity() -> None:
    """The build chain must run on a machine with no keychain identity and no account.

    Xcode rewrites these settings behind an author the moment the project is opened in the
    IDE — it did once already (ae265a2), stamping `CODE_SIGN_IDENTITY = "Apple Development"`
    and a personal `DEVELOPMENT_TEAM` onto every target. A CI runner has neither, so the
    simulator build stops at signing with an error about a missing profile that says nothing
    about the developer's IDE having edited a committed file.

    Every signable target — app, unit tests, UI tests — or none: the UI-test target once had
    the team and style without the identity, which is the same defect half-applied.
    """
    project = (REPO_ROOT / "apps/ios/App/SwimZH.xcodeproj/project.pbxproj").read_text(
        encoding="utf-8"
    )
    assert "DEVELOPMENT_TEAM" not in project, (
        "a hardcoded DEVELOPMENT_TEAM belongs to one developer's account, not to this repo"
    )
    assert "CODE_SIGN_STYLE" not in project, (
        "automatic signing needs an account; the chain signs nothing"
    )
    signable = 6  # app, unit tests, UI tests — Debug and Release each
    for setting in ("CODE_SIGNING_ALLOWED = NO;", "CODE_SIGNING_REQUIRED = NO;"):
        assert project.count(setting) == signable, (
            f"expected `{setting}` in all {signable} signable build configurations"
        )
    assert project.count('CODE_SIGN_IDENTITY = "";') == signable
