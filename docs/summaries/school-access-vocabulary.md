---
type: summary
name: school-access-vocabulary
created: 2026-08-06
links: ["[[session-access]]", "[[2026-08-05-school-access-vocabulary-plan]]"]
---

# School-pool access vocabulary — what exists now

## The scrape set is chosen by a predicate, not a kind

`etl.scrape.declared_sources` selects a roster entry when its `kind` is `INDOOR`,
`THERMAL` or `SCHOOL` **and** it owns a URL no other entry shares. That is **11** pools:
the 7 previously scraped plus `schulschwimmanlage-{aemtler,altweg,riedtli,tannenrauch}`.

The conjunction is load-bearing. The unshared-URL test **alone** selects 28 entries, 21 of
them outdoor/lake/river whose pages fail to parse today — and under the fail-fast contract
each would abort the build. The 14 pools sharing the generic `hallenbaeder.html` (13 with no
public swimming, plus `borrweg`) are excluded by construction: neither fetched nor recorded
as failures. `scrape_declared_sources` is the function's name; `scrape_indoor_facilities` is
gone.

**`freshness_of` still answers by kind alone** (`INDOOR`/`THERMAL`). Adding `SCHOOL` would
flip all 14 rule-less school pools from `NO_SOURCE` to `AWAITING_SCRAPE`. Its correctness
therefore rests on all four declared school sources happening to carry rules; a declared
school source that yielded none would read `no_source` rather than `awaiting_scrape`. The
honest fix needs a URL or a declared-source flag on `Facility`.

## The access vocabulary says what the city says

`SessionAccess` gained three members — see [[session-access]] for the governing rules.
Seven published `Angebot` strings now map distinctly instead of collapsing into
`PublicSwim`. Two traps are pinned by tests: cells contain a **non-breaking space**
(`für\xa0Erwachsene`), and the classifier must test `Frauen` before `Mädchen` and
`Kinder nur mit Erwachsenen` before `Erwachsene`, or the longer string loses.

School pages encode a multi-session day as rows with a bare `\xa0` weekday cell;
`_rules_from_rows` now inherits the previous row's weekdays. aemtler went 3 rules → 7.

**No member invents an age bound.** Only `GenderDiverse.min_age` carries one, because the
page states it. `GirlsOnly` denies a non-female person and answers *not determinable* for a
female one; `GenderDiverse` never hard-denies above its stated age (being trans is not a
value of `Person.gender`); `AccompaniedChildren` is always *not determinable*. None of the
three ever returns `allowed=True` — the honest answer, since the city publishes no cutoffs.

## The browser cannot drift from the domain

`apps/web/tests/test_eligibility_ui_contract.py` **generates** a 440-case fixture
(11 access kinds × 4 genders × 10 ages) from `domain.access.eligibility`;
`eligibility.test.js` replays the same file, bridged into pytest by `test_static_js.py`.
Both chains go red if either side moves. The age grid deliberately includes 16, 18, 59 and
60 — without on-threshold cases a `>=` → `>` off-by-one passed the whole contract.

`eligForAccess`'s unknown-access fallback is `ELIG_CHK`, not `ELIG_IN`. The old fail-open
default is what would have drawn a ✓ on a girls-only session.

## Known gaps

- The browser's `GENDER_DIVERSE_MIN_AGE` / `SENIORS_MIN_AGE` / `ADULTS_MIN_AGE` mirrors are
  **unguarded**: the contract pins `REPRESENTATIVE_ACCESS`'s hand-written instances, never a
  parsed bound. A page publishing a different age leaves both chains green while the badge
  disagrees with the server. The fix is carrying `min_age` on `OptionOut`.
- `/swim` defaults `eligible_only=true`, and all three new kinds are `allowed=False`, so on
  the API default these sessions vanish rather than showing as *check with the pool*. The UI
  always sends `false`, so it is unaffected. Pinned by a test so a change is deliberate.
- A trans/non-binary cell **without** a published age falls through to `PublicSwim` — the
  union has no "restricted, bound unknown" member.
- `borrweg` runs public swimming but shares the overview URL, so it is not a declared source.
  Its fixture is committed but unreachable; recovering it needs index discovery.
- `--fam-girls` and `--fam-accompanied` alias existing hues, so three legend rows are not
  colour-distinguishable. `blocks/poolrank.ts` still keys on `eligible === false`, so its
  mobile verdict does not follow the board's check state.
- `data/catalog.json` is stale against live WFS (snapshot `isengrind`, live `wolfsblick`).
  Both are URL-sharers, so no count moves.
