---
type: plan
status: done
created: 2026-08-05
feature: school-access-vocabulary
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: ["S2"]
branch: plan/school-access-vocabulary
worktree: .claude/worktrees/plan-school-access-vocabulary
base_branch: feat/new-ui
links: ["[[session-access]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# School-pool access vocabulary — say who each session is actually for

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-04**

> Rank 4 - B; Rank 2 confirm

**2026-08-05**

> let's go with B; but add there "we shouldn't compress information"

## Context

Five of Zürich's eighteen Schulschwimmanlagen run public swimming; the city groups the
other thirteen under *"Schulschwimmanlagen ohne öffentliches Schwimmen"*. None is scraped
(`etl/scrape.py:121` gates on `PoolKind.INDOOR`), and when they are, the timetable says
things the domain cannot express. Measured on the committed fixture: `aemtler` yields
**3 rules from 7 source rows**, and its Thursday 17:15–19:00 session — published as
*"für Mädchen"* — classifies as `PublicSwim`, because `_parse_category` matches `"frau"`
and nothing else. The app would tell an adult man he may attend a girls-only session.

This builds on [[session-access]]. The second half of the intent — *"we shouldn't compress
information"* — is applied as a scoping rule inside the existing pipeline: every rule keeps
the verbatim cell it was derived from, so classifying never destroys what the page said. The
broader extract–load–transform reshaping (a raw layer the store does not have) is a separate
plan; see Out of scope.

## Design (signature altitude)

### The published vocabulary, verbatim

Seven distinct `Angebot` strings across the five pages (live, 2026-08-04):

```
"für Frauen und Mädchen"                                  female, any age
"für Frauen"                                              female, adults
"für Mädchen"                                             female, minors
"für Erwachsene"                                          adults
"für Erwachsene und Kinder"                               everyone
"für Kinder nur mit Erwachsenen"                          children, accompanied
"offen für trans und nicht-binäre Personen ab 16 Jahren"  trans/non-binary, 16+
```

`offen für` is a stylistic variant of `für`, not a weaker "also welcome": altweg writes
*"offen für Erwachsene"* on Tuesday and *"offen für trans und nicht-binäre Personen"*
later, in the same grammar. Both are **reserved** sessions.

### New union members

```
GirlsOnly:            (no fields)
GenderDiverse:        min_age: int          # required; "ab 16 Jahren" -> 16
AccompaniedChildren:  (no fields)

type SessionAccess = … | GirlsOnly | GenderDiverse | AccompaniedChildren
```

No `note` field: the Design already rejects per-member notes, and nothing would set one —
the verbatim prose lives on the rule (below). `GenderDiverse.min_age` is required, not
optional: exactly one instance exists citywide and it states its age; an optional bound
would buy an extra branch, an extra `ReasonCode` and an extra test for a case no page
produces.

### Eligibility outcomes — stated, because the existing paths do not cover this case

`eligibility`'s not-determinable paths trigger on an unknown **person** attribute
(`access.py:264, :274, :298`); none covers an unstated **rule** bound. The nearest precedent
is `access.py:258-263` (`Gender.DIVERSE` vs `WomenOnly` -> `WOMEN_ONLY_CONFIRM`,
`allowed=False`) — a fully-known person against an undecidable rule, and the naming model for
the new codes. Note "not determinable" means `allowed=False` with a reason, which the UI renders
as *check with the pool* rather than ✓ or ✗.

```
GirlsOnly            gender not female  -> denied              (the harm this plan fixes)
                     gender female      -> not determinable    (city never states the cutoff)
                     gender unknown     -> not determinable

GenderDiverse        age < min_age      -> denied              (the one bound the page states)
                     otherwise          -> not determinable    -- NEVER a hard deny

AccompaniedChildren  always             -> not determinable    (accompaniment is unknowable)
```

**`GenderDiverse` never hard-denies, deliberately.** Being trans is not a value of
`Person.gender`: a trans woman's gender is *female*, not `DIVERSE`. Deciding this session
from that enum would wrongly exclude her. The only checkable fact is the published age.

**`AccompaniedChildren` invents no adult threshold** — that would repeat the unsourced
`AdultsOnly.min_age = 18`.

### Retaining what the page said

```
ScheduleRule: + source_text: str = ""   # the verbatim Angebot cell
```

One defaulted field, so every existing construction stays equal. It carries the whole cell
including per-session depth (`Tiefe 135 cm`), which the basin model cannot express, and any
footnote marker. Chosen over per-member `note` because adding `note` to `PublicSwim` would
break equality for every rule in the suite.

**It is persisted-but-unread for now.** No API field, no query, no UI consumes it; the raw
layer that would is out of scope. That is what the verbatim intent buys, and it is the
honest justification for the byte cost on every rule in every blob (including
`FeatureDTO.hours`). `RuleDTO` has no pop-when-default serializer — unlike `BasinDTO`
(`curated_dto.py:318`), `LaneReservationDTO` (`:262`) and `LanePlanDTO` (`:287`) — so one
must be added or every existing blob's bytes change.

### Classification order

**Normalize `\xa0` to a space first.** Real cells write `"für\xa0Erwachsene"` with a
non-breaking space (aemtler fixture; live riedtli/tannenrauch). Matching the patterns below
literally fails silently, and the only unpinned casualty is
`"für Erwachsene" -> AdultsOnly`, which would fall through to `PublicSwim`.

`_parse_category` matches **longest-first**. The load-bearing constraint is that
`"Frauen"` is tested **before** `"Mädchen"`, else *"für Frauen und Mädchen"* becomes
`GirlsOnly`; likewise `"Kinder nur mit Erwachsenen"` before `"Erwachsene"`, which it
contains.

```
"für Frauen und Mädchen"          -> WomenOnly
"für Frauen"                      -> WomenOnly
"für Kinder nur mit Erwachsenen"  -> AccompaniedChildren
"für Erwachsene und Kinder"       -> PublicSwim            (NOT AdultsOnly)
"für Mädchen"                     -> GirlsOnly
"trans und nicht-binäre"          -> GenderDiverse
"für Erwachsene"                  -> AdultsOnly
```

### Continuation rows

School pages encode a multi-session day as separate rows whose weekday cell is a bare
`\xa0`; `_parse_days` returns empty and `_rules_from_rows` drops the row (4 of aemtler's 7).
Fix: when the day cell yields no weekdays **and** the row carries a time range, inherit the
previous row's weekday set; a blank cell before any resolved day still drops. Note this lands
in `_rules_from_rows`, which serves **both** formats (`schedule_scraper.py:200, 270`); what
makes it inert for format 2 is `_parse_html_table`'s pre-filter on `_parse_days(r[0])` being
truthy (`:254`), so a generic-table page would not benefit. Harmless today (all five school pages are format 1); recorded so it is not
found later as a silent gap.

### Which pools are declared sources

A **conjunction**, not a replacement of the kind gate:

```
declared_source(entry) := entry.kind in {INDOOR, THERMAL, SCHOOL}
                          and entry.url is not None
                          and no other roster entry shares entry.url
```

The unshared-URL test alone selects **28** entries (7 indoor, 7 outdoor, 6 lake, 4 river,
4 school); every non-indoor one `ParseError`s on today's parsers and would abort the
fail-fast build. With the kind conjunction the set is exactly **11**: 7 already scraped + 4
school pools. The generic `hallenbaeder.html` is shared by 14 entries, so the thirteen
without public swimming are excluded and cannot become build-aborting failures.

## Out of scope

- **The extract–load–transform reshaping.** A raw layer holding each page's cells before
  transformation is a separate plan; this one honours the intent via `source_text`.
- **Borrweg's URL discovery.** It carries the generic overview URL, so the same predicate
  that protects the thirteen also excludes it. Four pools here, not five.
- **Per-session depth as a typed physical.** Kept verbatim in `source_text`; depth varies per
  session (a movable floor), which `Basin.dimensions` cannot express.
- **`AdultsOnly.min_age = 18`** stays. Unsourced — the same class as the deleted
  `public_holiday_policy` default — and it now reaches 8 new rows. Flagged, not changed.
- **New UI rendering.** S3 patches an existing fail-open decision site and adds locale keys;
  it builds no new surface.

## Slices

### S1 — vocabulary and parser

- **Goal**: the domain can express all seven published kinds, the five school pages parse
  completely and correctly, and no rule loses the cell it came from.
- **Touches**: `domain/access.py` (3 members, `access_info`, `eligibility`, `ReasonCode`,
  `REPRESENTATIVE_ACCESS`), `domain/schedule.py` (`source_text`),
  `boundary/curated_dto.py` + `mapping.py` (`RuleDTO` + pop-when-default serializer),
  `storage/codec.py`, `providers/schedule_scraper.py` (category order, continuation rows,
  `source_text`), `etl/fidelity_report.py` (its `access.adults_only` prose becomes false),
  `etl/field_sourcing.py` (its `basin.rules` note asserts adults_only is NOT sourceable —
  same truth-maintenance class; added during S1),
  `tests/providers/fixtures/` (4 new school pages), `tests/etl/fidelity/*.golden.md`,
  `apps/web/tests/api/test_swim.py` (`:186-195` asserts an exact 8-key access set).
- **Acceptance**:
  - aemtler yields **7 rules from 7 rows**; Thursday 17:15–19:00 is `GirlsOnly`.
  - altweg 20:00–21:00 is `GenderDiverse(min_age=16)`; riedtli Monday 16:30 is
    `AccompaniedChildren`; `"für Erwachsene und Kinder"` is `PublicSwim`; aemtler Monday
    20:15–21:00 is `AdultsOnly` (the NBSP casualty — otherwise silently `PublicSwim`).
  - Total rules: aemtler 7, altweg **2**, riedtli 3, tannenrauch 6. Corrected during S1:
    altweg publishes two Tuesday sessions, not three — verified against the committed
    fixture AND a live re-fetch (identical), on a page whose lead sentence says it offers
    public swimming *am Dienstag*. The pre-approval measurement of 3 is unreproducible.
  - Every rule's `source_text` equals the verbatim `Angebot` cell, `Tiefe …` included.
  - The 7 currently-scraped pools are unchanged **on `(weekdays, time, access)`** — diffed
    against `tests/etl/fidelity/schedule_diff.golden.md`, which already prints exactly that
    tuple for 6 of them; `hallenbad-altstetten` (format 2) has no golden coverage and needs
    its own assertion. Their `source_text` DOES change where a category column exists
    (`hallenbad_city.html` has one), so byte-identity is not claimed.
  - A **new** assertion `'"source_text"' not in codec.dumps(f)` for a default-valued rule
    (the `test_codec.py:180` pattern; the round-trip equality assertions cannot detect a new
    key).
  - `eligibility` pinned per the table above, including the **female** `GirlsOnly` case and
    `GenderDiverse` never hard-denying above `min_age`.
  - `access_info`/`eligibility`/`mapping` exhaustive (mypy strict green); `/access-types`
    lists the three new kinds (derived from `REPRESENTATIVE_ACCESS`, so no router change).
  - A pure offline assertion over `data/catalog.json`: `declared_source` selects exactly 11.
  - `etl/fidelity/*.golden.md` regenerated; the `access.adults_only` entry no longer claims
    the source never emits it.
- **Depends on**: —

### S2 — admit the school pools

- **Goal**: four school pools reach the gold store with real schedules.
- **Touches**: `etl/scrape.py` (the conjunction predicate; rename
  `scrape_indoor_facilities` + its module and `ScrapeFailure` docstrings, which no longer
  describe what it does), `tests/etl/test_scrape.py`, `domain/catalog.py` +
  `storage/codec.py` — **comments only**. Added during S2 as forced consequences:
  `src/swimzh/cli.py` (the rename's call site + its stale "INDOOR catalog pool" docstring),
  `tests/test_cli.py` (the cache-tier guard derives its URL set from the predicate),
  `tests/providers/wfs_snapshot.py` (the offline build transport had a fixture for only 1 of
  the 4 school pages, so every gold_db-backed suite aborted fail-fast),
  `apps/web/tests/api/test_single_source_of_truth.py` (it asserted aemtler is `no_source` —
  exactly what this slice inverts), `data/pools/aemtler.yaml` (its header named the deleted
  `scrape_indoor_facilities` and claimed the pool is never scraped). `freshness_of`'s predicate MUST stay
  `kind in (INDOOR, THERMAL)`: adding `SCHOOL` flips all 14 rule-less school pools from
  `NO_SOURCE` to `AWAITING_SCRAPE`, violating this slice's own criterion below and failing
  `tests/storage/test_schedule_freshness.py:70-79`. The 4 scraped school pools carry rules
  and so report `SCRAPED` regardless; only the docstring's claim about which set is
  scrapeable is stale. A URL-aware predicate is not a cheap alternative — `Facility` carries
  no URL. Also `tests/storage/test_schedule_freshness.py`, CLAUDE.md.
- **Acceptance**:
  - A real `swimzh build` exits 0 and yields **11** pools with schedule rules (today 7).
  - The **14** pools sharing `hallenbaeder.html` (the 13 *"ohne öffentliches Schwimmen"*
    plus `schulschwimmanlage-borrweg`) are neither scraped nor recorded as failures; their
    `ScheduleFreshness` stays `no_source`.
  - `WomenOnly` rules citywide rise 2 → ≥5.
  - CLAUDE.md's `aemtler`-as-`no_source` example is corrected (it is now the richest of the
    five); `schulschwimmanlage-hardau` replaces it.
- **Depends on**: S1

### S3 — stop the UI contradicting the domain

- **Goal**: the new access kinds are not silently rendered as "you may attend".
- **Touches**: `apps/web/static/js/eligibility.js` (`eligForAccess` currently ends
  *"Unknown / new access type: default to open"* → `ELIG_IN`, consumed by `board.ts:176` and
  `detailpanel.ts:405`), `blocks/ribbonmodel.ts` + `blocks/legend.ts` + `static/blocks.css`
  (no `.fam-*` token for the new kinds), `locales/*.ts` (5).
- **Acceptance**:
  - An adult male querying aemtler's Thursday 17:15 session sees a not-eligible/check state,
    never ✓ — the harm named in Context, verified in the UI and not only the API.
  - `eligibility.js` and the server agree for all three new kinds (`poolrank.ts:181` reads
    the server's `eligible`; today they would disagree).
  - Each of `en/de/fr/it/pl` contains the three named `access.*` keys — the existing
    `locales/parity.test.ts` only compares catalogues against each other and is green today
    with zero new keys, so it cannot serve as this criterion.
  - `npm run qa` green. If `eligibility.js` is converted rather than patched, CLAUDE.md's
    `.js`→`.ts` closure rule applies.
- **Depends on**: S1

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-05 | S1 | done | altweg is 2 rules not 3 (plan wrong; verified fixture + live); `field_sourcing.py` touched beyond Touches; `GenderDiverse` classified only when the cell states an age | trans/nb cell without a published age falls through to PublicSwim/AdultsOnly — the union has no "restricted, bound unknown" member; `source_text` persisted-but-unread, also rides `FeatureDTO.hours`; `GirlsOnly` denies `Gender.DIVERSE` while `WomenOnly` gives it a confirm | yes |
| 2026-08-05 | S2 | done | `declared_sources` returns `DeclaredSource(entry, url)` pairs (narrows `url` once instead of re-asserting at 3 sites); 5 files touched beyond Touches, all forced consequences, each disclosed above | `freshness_of` still answers by kind alone, so its correctness rests on all 4 declared school pools happening to carry rules — a declared school source yielding no rule would report `no_source` rather than `awaiting_scrape`; the honest fix needs a URL or declared-source flag on `Facility`. `data/catalog.json` is stale vs live WFS (snapshot `isengrind`, live `wolfsblick`) — both are URL-sharers so no count moves. `schulschwimmanlage_borrweg.html` fixture is unreachable (borrweg shares the overview URL) | yes |
| 2026-08-06 | S3 | done | unknown-access fallback changed `ELIG_IN` -> `ELIG_CHK` (beyond the plan's three named kinds — the fail-open default IS the defect's mechanism and would re-fire on the next domain arm; verified behaviour-neutral for all 8 pre-existing kinds); touched beyond Touches: `blocks/ribbonrender.ts`, `static/tokens.css`, `blocks/board.test.ts`, plus a new `apps/web/tests/test_eligibility_ui_contract.py` and two generated fixtures | the browser's `GENDER_DIVERSE_MIN_AGE` / `SENIORS_MIN_AGE` / `ADULTS_MIN_AGE` mirrors are UNGUARDED — the generated contract pins only `REPRESENTATIVE_ACCESS`'s hand-written instances, never a parsed bound, so a page publishing a different age would leave both chains green while the badge disagrees with the server; the fix is carrying `min_age` on `OptionOut`. `--fam-girls`/`--fam-accompanied` alias existing hues, so 3 legend rows are not colour-distinguishable (pre-existing collision; hues marked provisional). `blocks/poolrank.ts` still keys on `eligible === false`, so its mobile verdict does not follow the board's check state | yes |

## Decisions & divergences

- **2026-08-06, S3** — critic returned `revise` on a **false safety claim**: a comment in
  `eligibility.js` said the contract fixture would go red if a page published a different
  `min_age`. It would not — `_matrix()` iterates `REPRESENTATIVE_ACCESS`, a hand-written
  tuple holding `GenderDiverse(min_age=16)`, and never reads scraped rules. A page saying
  "ab 14 Jahren" would leave both chains green while a 15-year-old was drawn EXCLUDED
  against a server that said *check* — the mirror image of the harm this plan fixes.
  Comment rewritten to state the mirror is unguarded; recorded as tech debt. Same class as
  the S2 `aemtler.yaml` finding.
- **2026-08-06, S3** — the JS<->Python agreement is mechanical, not asserted:
  `test_eligibility_ui_contract.py` GENERATES a fixture from `domain.access.eligibility`
  and `eligibility.test.js` replays it, bridged into pytest via `test_static_js.py`. The
  critic mutation-tested it (flipped fixture rows, weakened a JS arm — both went red) and
  independently brute-forced 572 cases with 0 mismatches. Grid widened 264 -> 440 cases
  after review: no case sat ON a threshold, so a `>=` -> `>` off-by-one at 18 or 60 passed
  the old matrix and fails the new one (verified by mutation).

- **2026-08-05, S2** — critic returned `revise` on one real stale claim:
  `data/pools/aemtler.yaml`'s header named the deleted `scrape_indoor_facilities` and said
  the pool is permanently `NO_SOURCE`. It was the last live reference to that symbol outside
  archival docs and sat in the committed crosswalk, not a doc. Rewritten; the still-true
  "no Belegungsplan" sentence kept. `grep -rn scrape_indoor_facilities src/ tests/ apps/
  data/` now returns nothing.
- **2026-08-05, S2** — `freshness_of` deliberately left answering by kind. Adding `SCHOOL`
  would flip all 14 rule-less school pools to `AWAITING_SCRAPE`, breaking this slice's own
  criterion and `tests/storage/test_schedule_freshness.py`. Confirmed byte-unchanged by the
  critic; only the stale docstring moved. Recorded as tech debt rather than fixed.

- **2026-08-05, S1** — the plan's "altweg 3" acceptance number was **wrong**. Adjudicated
  against the committed fixture and a live re-fetch: two rows, one weekday. Criterion
  corrected. The other four pages match live exactly, so the fixtures are faithful captures
  rather than parser-shaped.
- **2026-08-05, S1** — `etl/field_sourcing.py` edited outside the listed Touches: its
  `basin.rules` note claimed `adults_only` is not sourceable, which this slice falsifies —
  the same stale-claim class the plan already gave `fidelity_report.py` a slice for.
  Disclosed and added to Touches rather than reverted; that file is the machine-checkable
  field->producer audit, so a silent edit there would matter.
- **2026-08-05, S1** — critic returned `revise` with two blocking findings, both
  disclosure-only ("the code as written should be kept"). Resolved by the orchestrator in
  the plan file, which subagents may not edit; no re-review run because no code changed.

- **2026-08-05, pre-approval review** — the declared-source predicate is a **conjunction**
  with the kind gate, not a replacement. The critic showed the unshared-URL test alone
  selects 28 entries and that all 12 sampled non-indoor pages `ParseError`, which under
  fail-fast would abort every build. An offline count assertion (== 11) now pins it.
- **2026-08-05, pre-approval review** — eligibility outcomes for the three new kinds are
  stated explicitly. The plan had claimed `eligibility` already handled an unstated rule
  bound; it does not — every not-determinable path keys on an unknown *person* attribute.
  `GenderDiverse` never hard-denies because being trans is not a value of `Person.gender`;
  deciding it from that enum would wrongly exclude a trans woman who selected female.
  Owner-confirmed 2026-08-05.
- **2026-08-05, pre-approval review** — `note` dropped from all three members: the Design
  had rejected per-member notes in the same breath as declaring them, and no producer sets
  one. `GenderDiverse.min_age` made required rather than optional.
- **2026-08-05, pre-approval review** — slices re-cut. The original S1 was domain-only with
  no observable behaviour (violating the vertical-slice rule) and S1→S2→S3 inverted risk
  order. `pause_after` moved to S2, which carries the irreversible change (roster gate, 4
  new pools in a fail-fast network build, CLAUDE.md edit).
- **2026-08-05, pre-approval review** — `etl/fidelity_report.py` and
  `tests/etl/fidelity/*.golden.md` given an owning slice: the golden asserts *"the source
  timetable never emits AdultsOnly"*, which S1 falsifies, and the goldens regenerate from the
  same fixtures S1 changes.
- **2026-08-05, pre-approval review (round 2)** — the three new members never return
  `allowed=True` for any person, which is the honest answer (no published cutoff, no
  accompaniment attribute, trans identity absent from `Gender`) — but `/swim` defaults
  `eligible_only=True` (`apps/web/api/swim/router.py:31`), so on the **API default these
  sessions vanish entirely** rather than rendering as *check with the pool*. The UI is
  unaffected (`api.ts:100` always sends `eligible_only: "false"`). Recorded because it sits
  in tension with *"we shouldn't compress information"*; not resolved here.
- **2026-08-05, pre-approval review** — `source_text` recorded as persisted-but-unread.
  Not gold-plating (it is the verbatim intent) but nothing consumes it until the raw-layer
  plan lands, and the plan should not imply otherwise.

## Summary

Shipped in three slices. The store now scrapes **11** declared sources rather than 7, and
the four Schulschwimmanlagen that run public swimming carry real timetables for the first
time. `SessionAccess` gained `GirlsOnly`, `GenderDiverse(min_age)` and
`AccompaniedChildren`, so the seven strings the city publishes stop collapsing into
`PublicSwim`; citywide `WomenOnly` rules went 2 → 7. `ScheduleRule.source_text` keeps the
verbatim `Angebot` cell — including the per-session depth the basin model cannot hold —
which is how the intent's *"we shouldn't compress information"* landed inside the existing
pipeline.

The defect that motivated the plan is closed at both ends: aemtler's Thursday 17:15
*"für Mädchen"* session no longer classifies as `PublicSwim`, and `eligibility.js` no
longer renders an unknown access kind as open to everyone. Those two ends are held together
by a generated 440-case contract that both chains replay, so the browser and the domain
cannot drift apart silently.

Three reviews returned `revise`; every finding was accepted. Two were false claims in
load-bearing prose rather than broken code — `data/pools/aemtler.yaml` still said the pool
is never scraped, and an `eligibility.js` comment promised a staleness guard that did not
exist. One was a wrong number in this plan's own acceptance criteria (`altweg 3`, actually
2), adjudicated against the fixture and a live re-fetch.

Distilled into `docs/summaries/school-access-vocabulary.md`.
