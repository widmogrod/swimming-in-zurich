#!/usr/bin/env python3
"""The compile-time plural guarantee `plurals.ts` gives the web, rebuilt for Xcode.

WHY THIS SCRIPT EXISTS AT ALL.
`apps/web/static/js/plurals.ts` is load-bearing precisely because a Polish message missing
`many` is a `tsc` ERROR: `Plural<'pl'>` is a record keyed by the four categories CLDR says
Polish uses, so the compiler refuses a catalog that would silently fall back. Xcode has no
counterpart. There is no build error and no documented build warning for a `.xcstrings`
plural variation that omits a category: at runtime Foundation falls back to `other`, which
in Polish is the DECIMAL form ("1,5 basenu"), so `5 basenu` is printed where `5 basenów`
belongs. That is exactly the broken grammar the whole design exists to prevent, and it is
invisible to everything Apple ships.

So the guarantee is rebuilt as a Run Script build phase on the app target: this script
walks the catalog JSON and emits `error:` lines Xcode surfaces as build errors. A missing
category fails the build, which is where the TypeScript side fails too.

WHAT IS CHECKED, and why it is CONFORMANCE rather than a bug hunt.
`PLURAL_CATEGORIES` in `plurals.ts` is itself asserted against `Intl.PluralRules`
(`plurals.test.ts`), so it cannot drift from CLDR. This script therefore does not re-derive
the rules — it pins the SAME table and asserts the `.xcstrings` carries exactly those sets.
Equality, not containment: a stray `two` on a Polish entry means a translator invented a
form the language does not select, which will never be shown and is a translation lost.

Also checked, because both are silent at runtime and fatal in a different way:
  * a plural form that does not interpolate its count -- `xcstringstool` rejects this
    ("Plural variation requires referencing the number in the string"), but it rejects it
    only for the locales it happens to compile, and the message it gives names one locale;
  * a locale missing entirely from a key, which renders as the raw key on a phone.

PATH. `python3` rather than node: Xcode's Run Script environment is not a login shell and
node is not guaranteed on its PATH, whereas `/usr/bin/python3` ships with the Command Line
Tools. `scripts/ios_budget.py` (the size ratchet phase) made the same call.

Usage:
    python3 scripts/xcstrings_plural_gate.py [path/to/Localizable.xcstrings]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "apps/ios/Sources/SwimZHKit/Resources/Localizable.xcstrings"

# The SAME table as `apps/web/static/js/plurals.ts:23-31`, which `plurals.test.ts` asserts
# against `Intl.PluralRules(...).resolvedOptions().pluralCategories`. Duplicated here rather
# than imported because this runs inside an Xcode build phase with no node and no `dist/`;
# `tests/scripts/test_xcstrings_plural_gate.py` asserts the two copies still agree.
PLURAL_CATEGORIES: dict[str, frozenset[str]] = {
    "en": frozenset({"one", "other"}),
    "de": frozenset({"one", "other"}),
    "fr": frozenset({"one", "many", "other"}),
    "it": frozenset({"one", "many", "other"}),
    "pl": frozenset({"one", "few", "many", "other"}),
}

# The specifier a plural form must carry for Foundation to select a category from it. `%@`
# does not select: it prints an object and the variation is chosen from nothing.
COUNT_SPECIFIER = "lld"


def _count_is_referenced(value: str) -> bool:
    """Does `value` interpolate an integer the plural rule can select on?

    `%1$lld`, `%lld` and `%2$lld` all qualify; `%@` alone does not.
    """
    return COUNT_SPECIFIER in value


def check(catalog: dict[str, object]) -> list[str]:
    """Every violation in `catalog`, as human-readable lines. Empty means conformant."""
    problems: list[str] = []
    strings = catalog.get("strings")
    if not isinstance(strings, dict):
        return ["catalog has no `strings` object — not an .xcstrings document?"]
    if not strings:
        return ["catalog is empty — the gate would pass on anything"]

    expected_languages = set(PLURAL_CATEGORIES)
    for key in sorted(strings):
        entry = strings[key]
        if not isinstance(entry, dict):
            problems.append(f"{key}: entry is not an object")
            continue
        localizations = entry.get("localizations")
        if not isinstance(localizations, dict):
            problems.append(f"{key}: no `localizations`")
            continue
        missing = expected_languages - set(localizations)
        if missing:
            problems.append(f"{key}: no translation for {sorted(missing)}")

        for language in sorted(expected_languages & set(localizations)):
            unit = localizations[language]
            if not isinstance(unit, dict):
                problems.append(f"{key}/{language}: localization is not an object")
                continue
            variations = unit.get("variations")
            if variations is None:
                # A plain string. Every locale of a key must agree on being plural or not:
                # a Polish entry that lost its variations reads as one hard-coded form.
                continue
            plural = variations.get("plural") if isinstance(variations, dict) else None
            if not isinstance(plural, dict):
                problems.append(f"{key}/{language}: `variations` with no `plural`")
                continue
            expected = PLURAL_CATEGORIES[language]
            got = set(plural)
            if got != expected:
                lacks = sorted(expected - got)
                extra = sorted(got - expected)
                detail = []
                if lacks:
                    detail.append(f"missing {lacks}")
                if extra:
                    detail.append(f"unexpected {extra}")
                problems.append(
                    f"{key}/{language}: plural categories {', '.join(detail)} "
                    f"(CLDR: {sorted(expected)})"
                )
            for category in sorted(got):
                form = plural[category]
                value = form.get("stringUnit", {}).get("value") if isinstance(form, dict) else None
                if not isinstance(value, str):
                    problems.append(f"{key}/{language}/{category}: no string value")
                elif not _count_is_referenced(value):
                    problems.append(
                        f"{key}/{language}/{category}: the form does not interpolate "
                        f"its count (%{COUNT_SPECIFIER}) — Foundation cannot select on it"
                    )

        # Plural-ness must be uniform across locales, or one language silently loses its
        # grammar while the rest keep theirs.
        shapes = {
            language: "plural" if "variations" in localizations[language] else "plain"
            for language in sorted(expected_languages & set(localizations))
            if isinstance(localizations[language], dict)
        }
        if len(set(shapes.values())) > 1:
            problems.append(f"{key}: plural in some locales and plain in others: {shapes}")

    return problems


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_CATALOG
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # `error:` is the prefix Xcode turns into a build error.
        print(f"error: no string catalog at {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    problems = check(catalog)
    for problem in problems:
        print(f"{path}: error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{path}: plural categories conform to CLDR for all 5 locales")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
