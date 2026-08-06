---
type: plan
status: in-progress
created: 2026-08-06
feature: seasonal-hours
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: ["S3"]
branch: plan/seasonal-hours
worktree: .claude/worktrees/plan-seasonal-hours
base_branch: feat/new-ui
links: ["[[annual-window]]", "[[session-access]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# Seasonal hours — model a season the city publishes, and the weather it depends on

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-04**

> Rank 4 - B; Rank 2 confirm

**2026-08-05**

> for me feature is to collect as much accurate data and facts from websites; and then in ETL process clean and load them to SQL database that is golden set. Key is that we can model in simple way every type of pool or port swiming object; any sezonal opening hours; info about availability; lanes; depth; temputre; geneder restrictions etc. We shoudn't compress information; we should think about it as extract; load; transform pipeline

**2026-08-06**

> ok do A and B.

## Context

Zürich's outdoor, lake and river pools publish hours as a **seasonal** table
(`Zeitraum` × hours), not a weekly one. `_parse_time_range` returns `None` on a cell like
`9–16 Uhr Mai–September`, so the row is dropped. Two live consequences:

- **17 outdoor/lake/river pools return nothing, all summer.** They are not even fetched:
  `etl.scrape.declared_sources` admits only `{INDOOR, THERMAL, SCHOOL}`.
- **Two pools we already scrape have no weekend.** `hallenbad-blaesi` resolves Mon–Fri and
  `waermebad-kaeferberg` Tue–Fri, because their weekend rows carry a trailing month range.

The intent names *"any sezonal opening hours"* directly, and *"we shouldn't compress
information"* governs how: the fair-weather column, the `Zeitraum` text and the footnote's
last-admission rule are kept, not flattened away. Builds on [[annual-window]] and the
`source_text` carrier from the school-access-vocabulary plan.

## Design (signature altitude)

### The two new types

```
MonthDay:      month: int; day: int
AnnualWindow:  start: MonthDay; end: MonthDay; precision: DAY | MONTH
               def contains(d: date) -> bool     # year-free; start > end wraps New Year

class Weather:  ANY | FAIR_ONLY
```

**Year-free by construction.** The city states the year once per page, in a heading
(`Öffnungszeiten 2026`) whose DOM position varies — never in a `Zeitraum` cell. A year-bound
range expires silently; a year-free one resolves correctly next season, with the scraped year
kept as provenance rather than as a bound.

**`precision` is required by pools in THIS plan, not a future one**: blaesi and kaeferberg
publish `Mai–September` with no day numbers, while the outdoor tables publish
`30. Mai–16. August`. `precision=MONTH` means whole months inclusive — 1 May through
30 September — and `contains` must be pinned to that semantics so the test needs no
judgement call.

### Where they attach

```
ScheduleRule:    + season: AnnualWindow | None = None
                 + weather: Weather = ANY
ResolvedSession: + weather: Weather = ANY
```

**Byte-invisibility is work, not a freebie.** `RuleDTO._serialize`
(`boundary/curated_dto.py:130-137`) pops `"source_text"` **by name**; it does not pop
arbitrary defaulted fields, so it must be extended. And `ResolvedSessionDTO`
(`curated_dto.py:140`, reached via `ExceptionDTO.sessions`, mapped at `mapping.py:284-289`)
has **no serializer at all** — a bare `weather` field there adds a key to every
exception-bearing blob.

### Resolver — a filter inside layer 4, not a fifth layer

```
rule.season ──filters──▶ layer 4 weekday matching   (resolver.py:114)
rule.weather ─rides on─▶ ResolvedSession ──▶ SwimOption

layers 1-3 (closures / exceptions / holiday policy) are UNTOUCHED
```

When every rule is seasoned and none is in season, the day resolves to
`ClosedDay(ClosureCode.SEASONAL_BREAK)` rather than `NO_SESSIONS`. `SEASONAL_BREAK` exists
(`domain/closure.py:29`), is translated in all five locales, and **has no producer** —
`_closures_from_notices` passes full prose (→ `UNMAPPED`) and `operator_pages` emits only
`Revision`/`Betriebsferien`. This plan gives it one rather than minting a second code.
`NO_SESSIONS` renders as *"No sessions scheduled"*, a lie for a lido in October.

### Weather is per-session, never per-day

The fair-weather window is **provably additive**: all-weather `end` == fair-weather `start`
in **46 of 46** rows across the 12 both-weather pages. So on a summer day Heuried is
*certainly* open 09:00–14:00 and *conditionally* open 14:00–21:00. `DaySchedule` stays
`OpenDay | ClosedDay` — a day-level "maybe" would launder a known fact into an unknown and
force a fourth UI terminal state past `test_honesty`.

### What the parser must survive

Measured across the **16 city pages** that publish a table:

```
3 Zeitraum header shapes  both weather columns (12) | all-weather only (3)
                          | FAIR-WEATHER ONLY (1, maennerbad)
plus mythenquai's 2nd table: Badbereich | Zeit (open-ended, no Zeitraum)
2 Zeitraum grammars       "9.–29. Mai" (month once)  "30. Mai–16. August" (both)
2 indoor grammars         "9–16 Uhr Mai–September" (BARE, blaesi)
                          "9–16 Uhr (Mai–September)" (PARENTHESISED, kaeferberg)
separator                 EN DASH U+2013 throughout; no hyphen-minus
continuation              maennerbad row 2's Zeitraum is a bare U+00A0
weekday-in-cell           "11–18.30 Uhr (Sonntag–Freitag)" / "(Samstag)"
minute separator          a DOT: "14–19.30 Uhr"
footnote markers          <sup>1</sup> | <sup>1,2</sup> | <sup>1, 2</sup> (delimiter varies)
```

**`_ROW_RE` is page-wide and table-blind** (`schedule_scraper.py:64`). Two consequences the
parser must handle, and neither is an attribute-escaping problem — `_parse_stadtzurich` never
scans attributes and recovers rows on 16/16 pages today:

1. mythenquai's per-area rows (`['Strandabschnitt', 'Täglich ab 7 Uhr geöffnet', '\xa0']`)
   land in the same flat bucket as its `Zeitraum` rows and would inherit carried weekdays.
2. `_ROW_RE` matches only cells shaped exactly `{"value":"…"}`. Käferberg's **Monday** cell
   is `{"value":"<p>11–15 Uhr</p>","style":…,"valign":…}` and is therefore invisible to the
   parser *before* any time parsing — no season work restores it.

**Last-admission is published, and the marker is NOT a reliable anchor.** Three sets,
measured, that must not be conflated:

```
13 pages carry a last-admission SENTENCE
11 of those carry it inside footnote ¹
 2 (frauenbad, maennerbad) carry it as standalone prose with NO <sup> on the page
 1 (au-hoengg) carries ¹ whose whole body is the daylight caveat, NO last-admission
wording varies: "erfolgt bis 30 Minuten" vs frauenbad's "erfolgt spätestens 30 Minuten"
```

So an extractor anchored on ¹ silently loses frauenbad and maennerbad; one anchored on the
exact string loses frauenbad. `Facility.last_admission_before: timedelta | None`
(`domain/models.py:235`) exists with no producer, so dropping this would be the compression
the Intent forbids — it is extracted, anchored on the sentence rather than the marker.

## Out of scope

- **`Facility.operating_season`.** The agreed two-place design has a facility-level season for
  hours-less pools (paddling, Gap 5; enge, Gap 7). Verified: every in-scope page publishes
  hours alongside its season, so nothing here produces or reads it. Deferred to the plan that
  needs it.
- **`seebad-enge` and `freibad-dolder`.** Both hold *unshared* URLs
  (`tonttu.ch`, `doldersports.com`), so widening the kind gate would admit them — and both
  return `ParseError('no HTML schedule table')`, which under fail-fast aborts the build. S3
  excludes them explicitly. They are Gap 7 (enge needs a guaranteed-core window nested inside
  a conditional one; dolder a date-range exception).
- **`flussbad-unterer-letten` + `-flussteil`.** They share one URL, so `declared_sources`
  never selects them even though the page publishes a full 4-row table. Disambiguating a
  shared URL across two pools is its own problem.
- **The 13 paddling pools** (month-granular shared-page season, Gap 5).
- **mythenquai's per-area hours.** `Täglich ab 7 Uhr geöffnet` is open-ended and `TimeRange`
  requires `start < end`. **Dropped, and this is a real loss** — no slice here produces a
  `Notice` for it, so the cell survives nowhere. Recorded rather than papered over: inventing
  a closing time would be worse, and the raw-layer plan is where an unparsed cell gets a home.
- **Prices for the newly admitted pools** — plan B. Note `_CITY_HOST in url`
  (`etl/scrape.py:181`) already yields `prices=None` for the sportamt hosts, so nothing
  leaks in by accident.
- **The raw/extract layer.** The Intent's ELT shape is honoured here inside the existing
  pipeline, via `source_text`, `Notice` and `last_admission_before`.

## Slices

### S1 — the season model, proven on pools we already scrape

- **Goal**: blaesi and kaeferberg regain their weekends, using the real season model against
  pages already in the fixture set.
- **Touches**: `domain/schedule.py` (`MonthDay`, `AnnualWindow`, `Weather`, two
  `ScheduleRule` fields, `ResolvedSession.weather`), `domain/resolver.py` (season filter in
  layer 4; `SEASONAL_BREAK` when all rules are out of season), `boundary/curated_dto.py` +
  `mapping.py` (`RuleDTO._serialize` extended to pop the new defaults; **a serializer added
  to `ResolvedSessionDTO`**), `storage/codec.py`, `providers/schedule_scraper.py`
  (`_parse_time_range`/`_slots` read a trailing month range in **both** grammars — bare and
  parenthesised — and `_ROW_RE` widened to accept cells carrying keys besides `value`),
  `tests/etl/fidelity/schedule_diff.golden.md` (it pins `hallenbad-blaesi … source rules: 5`,
  which this slice makes 7 — `test_fidelity_report.py:95` byte-compares it), tests.

  **The parenthesised season must match on MONTH NAMES, not on parentheses.** The same page
  family writes `(Sonntag–Freitag)` and `(Samstag)` as weekday qualifiers (maennerbad, S2); a
  bare `(...)`-anchored rule would eat those too.
- **Acceptance**:
  - blaesi resolves Sat **and** Sun (today Mon–Fri).
  - kaeferberg resolves Sat and Sun; its Monday row also returns once `_ROW_RE` accepts the
    richer cell shape, so `days == {MON..SUN}` — if the `_ROW_RE` widening is dropped, the
    criterion is `days ⊇ {SAT, SUN}` and the divergence is recorded.
  - Blaesi's **Saturday** resolves `09:00–16:00` on **2026-07-18** and `09:00–18:00` on
    **2026-01-17** (both verified Saturdays) — the `Mai–September` / `Oktober–April` split.
  - A facility whose rules are all seasoned and none in season →
    `ClosedDay(SEASONAL_BREAK)`, not `NO_SESSIONS`.
  - Every other pool is unchanged on `(weekdays, time, access)` — diffed across the 12
    indoor/school page fixtures in `tests/providers/fixtures/` (a different set from the
    12 both-weather city pages above).
  - `schedule_diff.golden.md` regenerated; the diff is exactly blaesi's and kaeferberg's
    recovered weekend rows.
  - `'"season"'`, `'"weather"'` absent from `codec.dumps(f)` for default-valued rules **and**
    for a facility carrying a `ScheduleException` with sessions (the `ResolvedSessionDTO`
    path) — the `test_codec.py:180` pattern.
  - `AnnualWindow.contains` pinned for a wrap-around window (Oct→Apr) across New Year and for
    `precision=MONTH` (whole months inclusive).
- **Depends on**: —

### S2 — the Zeitraum parser, offline (+ the out-of-season code)

- **Goal**: every published table shape parses correctly from saved fixtures. No pool is
  admitted yet, so this slice needs no network and cannot abort a build.
- **Touches**: `providers/schedule_scraper.py` (a `Zeitraum` parser in `_PARSERS`; **column-header**
  awareness — heading position alone cannot do it, see the S1 finding on `hallenbad-city`;
  footnote → `last_admission_before`), `domain/closure.py` + `domain/resolver.py`
  (`ClosureCode.OUT_OF_SEASON`), `apps/web/static/js/locales/*.ts` (5),
  `tests/providers/fixtures/` (the 16 city pages), tests.
- **Acceptance**:
  - All three Zeitraum header shapes parse, including maennerbad (**fair-weather only**) and
    its `\xa0` continuation row inheriting the range above.
  - Heuried yields `09:00–14:00 ANY` and `14:00–21:00 FAIR_ONLY` for a date inside
    `30. Mai–16. August`, and no sessions for 2026-10-01.
  - maennerbad's weekday-in-cell forms yield two rules with different weekdays.
  - **No non-`Zeitraum`/non-`Wochentag` table contributes a rule.** Generalised from
    mythenquai because S1's `_ROW_RE` widening is page-wide: `auhof`'s `Mietobjekt|Preis`
    rows also become visible (they carry `style`/`valign` cells) and must stay inert.
  - `last_admission_before == timedelta(minutes=30)` on the **13** pages carrying a
    last-admission sentence (11 via footnote ¹, 2 as standalone prose), accepting both the
    `bis` and `spätestens` wordings; **`au-hoengg` yields `None`** — its ¹ is the daylight
    caveat alone. `source_text` keeps the cell verbatim.
  - The 11 currently-scraped pools are unchanged on `(weekdays, time, access)` **relative to
    their post-S1 output** — S1 deliberately changes 2 of the 11.
  - An out-of-season day resolves `ClosedDay(OUT_OF_SEASON)`, **not** `SEASONAL_BREAK`.
    Each of `en/de/fr/it/pl` carries the new key by name, worded season-neutrally
    ("Closed for the season"); `closure.seasonal_break` still says *Summer break* for the
    curated/notice path.
  - The four school fixtures (altweg, borrweg, riedtli, tannenrauch) gain a parse test, so a
    future `_ROW_RE`/attribution change cannot move them silently.
  - Fixtures may be harvested from `.cache/swimzh/static/www.stadt-zuerich.ch/*.json`
    (`response.body` is plain HTML) rather than re-fetched — 15 of the 16 pages are there.
- **Depends on**: S1

### S3 — admit the pools

- **Goal**: the outdoor, lake and river pools with their own page return real hours from a
  real build.
- **Touches**: `etl/scrape.py` (`_SCRAPEABLE_KINDS` gains `OUTDOOR`, `LAKE`, `RIVER`; an
  explicit exclusion for enge/dolder with the reason recorded; the stale comment at `:150`
  says "21 of them outdoor/lake/river" — it is **17**), `domain/catalog.py` +
  `tests/storage/test_schedule_freshness.py` (see the trap), `tests/etl/test_scrape.py`
  (`:233` asserts `len(declared) == 11`), `tests/etl/fidelity/*.golden.md`,
  `data/sources.md`, and the roster URL repair in
  `providers/geo_sport.py:98 _normalize_roster_url` (the only place a roster URL is
  rewritten today).
- **The `freshness_of` trap** — the same shape as the previous plan's, and it must be
  written down rather than discovered: adding `OUTDOOR`/`LAKE`/`RIVER` to `freshness_of`'s
  kind test would flip **`flussbad-unterer-letten` and `-flussteil`** to `AWAITING_SCRAPE`
  *forever*, because they share a URL and can never be declared sources. It also breaks
  `test_blob_without_any_basin_is_no_source_when_not_indoor`.
  **Default: leave the predicate alone and fix only the docstring** — a pool that carries
  rules reports `SCRAPED` from the blob regardless, so the widening buys nothing. The
  alternative (adding the URL-awareness `Facility` lacks, contradicting
  `domain/catalog.py:60`) is a domain change; taking it would be a Ledger divergence.
- **Acceptance**:
  - A real `swimzh build` exits 0 and yields **26** pools with schedule rules (11 today + 15
    newly admitted).
  - **The `freibad-zwischen-hoelzern` roster URL repair is mandatory, not optional.** Its
    stored URL 302s to a stadt-zuerich slug that **404s** (the live slug carries `-den-`), and
    once `OUTDOOR` is in the kind gate that entry IS a declared source — `cli.py:293-301`
    aborts the phase on the first declared-source fetch failure, so "25 pools and exit 0" is
    unreachable. Repair it or exclude the pool as enge/dolder are excluded; there is no third
    outcome.
  - `declared_sources` selects 26, pinned offline against `data/catalog.json`.
  - enge and dolder are excluded, produce no `ScrapeFailure`, and stay `no_source`.
  - Heuried on 2026-10-01 resolves `ClosedDay(SEASONAL_BREAK)` from the built store.
  - `last_admission_before` is persisted for the pools whose page carries footnote ¹.
- **Depends on**: S2

### S4 — surface the conditional

- **Goal**: a user can tell a guaranteed session from a weather-dependent one.
- **Touches**: `apps/web/api/swim/model.py` + `service.py` (read
  `option.session.weather` — `SwimOption.session` already carries it, so **no new
  `query.py` field**), `apps/web/static/js/` (board/detail render), `locales/*.ts` (5).
- **Acceptance**:
  - `/swim` for heuried on a July afternoon returns both sessions with the 14:00–21:00 one
    marked fair-weather.
  - The board/detail render emits a fair-weather marker element for a `FAIR_ONLY` session
    and omits it for `ANY` — asserted in vitest over the render factory with `_fakedom`,
    the convention the repo already uses. ("Never presented as guaranteed" restates the
    goal and no gate can adjudicate it.)
  - Each of `en/de/fr/it/pl` carries the fair-weather key **by name** (`parity.test.ts` only
    cross-compares catalogues and is green with zero new keys).
  - Both QA chains green.
- **Depends on**: S3

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-06 | S1 | done | per-table attribution for format 1 pulled forward from S2 (the page-wide `_ROW_RE` widening exposed Leimbach's sauna table, which contributed a WomenOnly rule as POOL hours); attribution keys on the nearest heading ELEMENT, not `_table_priority`'s text window (the window is filled by the table's own `columns=` attribute); `_parse_time_range` strips tags (kaeferberg's Monday cell is `<p>11–15 Uhr</p>`); `_split_season` also accepts day numbers, giving `precision=DAY` a producer; `storage/codec.py` needed no change after all (it reuses `BasinDTO`) | `_row_groups` infers table boundaries from source adjacency — a heuristic over a flat regex, correct on all 13 fixtures but element-scoping is the real answer; 4 school fixtures are parsed by NO test, so a future `_ROW_RE` change could move them silently; `hallenbad-city` ships sauna hours as POOL hours (PRE-EXISTING, not this slice) because its sauna heading is emitted AFTER the table's rows attribute | yes |

## Decisions & divergences

- **2026-08-06, pre-approval** — `ClosureCode.SEASONAL_BREAK` reused rather than adding
  `OUT_OF_SEASON`: it exists, is translated in five locales, and the critic confirmed it has
  no producer today.
- **2026-08-06, pre-approval** — `Facility.operating_season` deferred. Verified by review
  that no in-scope pool has a season without hours, so shipping it here would persist a field
  no producer fills.
- **2026-08-06, pre-approval review** — footnote ¹ **is** last-admission. The plan had
  claimed it was only a daylight caveat; the full sentence continues *"Der letzte Einlass
  erfolgt bis 30 Minuten vor Badschluss"*, and `Facility.last_admission_before` already
  exists unfilled. Dropping it would contradict the Intent, so S2 extracts it.
- **2026-08-06, pre-approval review** — S2 split into parser (offline) and admission (live),
  and `pause_after` moved to S3. The combined slice carried a new parser family, a kind-gate
  widening, a `freshness_of` change, a roster repair and a live-build criterion.
- **2026-08-06, pre-approval review** — corrections to factual claims: the pinned Saturdays
  were a Wednesday and a Thursday; blaesi's grammar is **bare** (`Mai–September`) not
  parenthesised, so a `(…)`-anchored rule would have fixed kaeferberg and missed blaesi; the
  adjacency evidence is **46 rows, not 40**; the "attribute trap" does not exist in this repo
  (`_parse_stadtzurich` never scans attributes and recovers rows 16/16) and was replaced by
  the real `_ROW_RE` table-blindness and cell-shape defects; the widened kind gate admits
  **28**, not 26, before excluding enge/dolder.

- **2026-08-06, pre-approval review (round 2)** — the last-admission claim was three sets
  conflated. 13 pages carry the sentence, 12 the ¹ marker, only 11 both; `au-hoengg`'s ¹ is
  the daylight caveat alone and frauenbad/maennerbad carry the sentence with no marker at all,
  in differing wording. The criterion as written could not be satisfied by any anchoring.
- **2026-08-06, pre-approval review (round 2)** — S3's "25 pools and exit 0" fallback was
  unreachable: fail-fast aborts on the first declared-source fetch failure, so the
  `zwischen-hoelzern` URL repair is mandatory. `freshness_of`'s default is now stated
  (leave the predicate, fix the docstring) rather than left as an open either/or.
- **2026-08-06, pre-approval review (round 2)** — S1 was changing what
  `schedule_diff.golden.md` pins (blaesi 5 → 7 source rules) while the golden was assigned to
  S3; moved into S1. S4's "never presented as guaranteed" replaced with a mechanical check.

- **2026-08-06, S1** — critic **approved** with no blocking findings, having mutation-tested
  five assertions (season filter, `_empty_day`, `_ROW_RE`, the sauna guard, the serializer pops)
  and proved byte-invisibility by `cmp` against `HEAD` rather than by assertion.
- **2026-08-06, S1** — **`SEASONAL_BREAK`'s translations are wrong for this use, and must be
  fixed before S3 admits the lidos.** All five locales render it as *summer* break
  ("Summer break" / "Sommerpause" / "Pausa estiva" / "Przerwa letnia" / "Pause estivale"), but
  the resolver now emits it for an out-of-season day — which for an outdoor pool is
  October–April, the **winter**. The plan's stated justification for reuse was that the code was
  "already translated in five locales"; that justification is void. No defect ships in S1
  (blaesi and kaeferberg have mixed timetables, so `_empty_day`'s all-seasoned guard cannot
  fire). Decide in S3: reword the five strings to season-neutral, or mint the distinct code the
  plan declined. OWNER INPUT WANTED.
- **2026-08-06, S1** — `_nearest_heading`'s docstring overclaims ("the heading element says
  exactly what the city calls the table"). `hallenbad_city.html` emits its sauna heading AFTER
  the datatable's `rows=` attribute, so the heuristic returns `''` and admits the table. That
  is pre-existing and unchanged by S1, but it means **S2's criterion "no non-Zeitraum table
  contributes a rule" cannot be met by heading position alone** — S2 needs column-header
  awareness.

- **2026-08-06, owner decision** — mint `ClosureCode.OUT_OF_SEASON` rather than reword
  `SEASONAL_BREAK`. Closed-in-summer (an indoor Revision) and closed-outside-its-season (a
  lido in January) are different facts and the app can state each correctly; the plan's
  original reuse assumed one concept. Wording is season-NEUTRAL ("Closed for the season"),
  not "winter": the code derives from the pool's own window and does not know which season
  it is outside, so hardcoding winter would repeat the bug being fixed. Folded into S2 so it
  lands before S3 makes it visible.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/seasonal-hours.md` (what EXISTS now, not what was intended).
