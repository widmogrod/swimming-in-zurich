---
type: plan
status: in-progress
created: 2026-08-08
feature: sharedsource-fanout
branch: plan/sharedsource-fanout
worktree: .claude/worktrees/plan-sharedsource-fanout
base_branch: feat/new-ui
prerequisite: "[[2026-08-08-admission-union-plan]] frontmatter must read `status: done` — this plan writes `Admission.Free` onto 13 pools and needs the `Admission` union and `Facility.admission` that plan delivers. (That plan does NOT promise an aspect-level field; renaming `ScrapedAspects.prices` to `admission` is verified at S3 start and belongs to whichever plan runs first.)"
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: ["S1"]
links: ["[[shared-source]]", "[[admission]]", "[[annual-window]]", "[[discovery-driven-providers]]", "[[2026-08-08-admission-union-plan]]"]
---

# SharedSource fan-out — one page states three facts about thirteen pools

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-06**

> for me feature is to collect as much accurate data and facts from websites; and then in ETL process clean and load them to SQL database that is golden set. Key is that we can model in simple way every type of pool or port swiming object; any sezonal opening hours; info about availability; lanes; depth; temputre; geneder restrictions etc. We shoudn't compress information; we should think about it as extract; load; transform pipeline

**2026-08-08**

> 1 ok; 2 - rerun and re-discover; if they're stale we should not allow stale data in, or serve old data to users; 3 = go with sharedsources as suggested;

## Context

The 13 Planschbecken are invisible to every scraper: they all share one URL
(`…/sommerbaeder/planschbecken.html`), and `declared_sources`' unshared-URL test drops them —
correctly, since under fail-fast one unparseable overview page must not abort the build 13 times.
But the page itself states real facts, **once, for all thirteen**: *"Diese sind je nach Wetter von
Mai bis September in Betrieb. Die Nutzung der Planschbecken ist kostenlos."* — a season, a weather
condition, and free admission. There are **no per-pool hours on that page at all**, and the
per-pool accordion adds only a blurb; a per-pool join was measured and rejected (2 of 13 names
mismatch: roster *Josefswiese* vs page *Josefwiese*; *Föhrenwald* has 12-of-13 accordions).

So this is not "split a page into 13 records" — it is "one page's facts fan out to a member set",
and the model has nowhere to put any of the three: a season with no timetable does not fit
`ScheduleRule` (which requires a `TimeRange`), and `DaySchedule = OpenDay | ClosedDay` has no
variant for *open, hours unpublished*. Builds on [[annual-window]] and `Weather` (both shipped by
seasonal-hours), [[admission]]'s `Free`, and [[discovery-driven-providers]] (fail-fast, page-stated
facts only).

## Design (signature altitude)

### Two domain seats the facts have lacked

```
OperatingSeason:  window: AnnualWindow,  weather: Weather        # facility-level, timetable-free
Facility.operating_season: OperatingSeason | None = None

DaySchedule = OpenDay | OpenUnscheduledDay | ClosedDay           # third variant, closed set
OpenUnscheduledDay:  weather: Weather = Weather.ANY              # open per season; hours unpublished
```

`Weather` rides `OperatingSeason` (not a session) because *"je nach Wetter"* qualifies the whole
season and there are no sessions to hang it from. The resolver gains a season gate:

```
resolve_hours:  closures → exceptions → SEASON GATE → holiday policy → rules
    outside the facility window                    -> ClosedDay(OUT_OF_SEASON)
    inside it, and the basin has NO rules          -> OpenUnscheduledDay(weather)
    inside it, rules exist                         -> unchanged path
```

**The consumers do NOT match exhaustively today** — the only `assert_never` sites in `query.py`
(`:232`, `:342`) guard `Result` unions, not `DaySchedule`. The three real match sites would let a
new variant fall through silently: `query.py:403-407` (statement-level match in the basin loop),
`query.py:547-551` (`_feature_status`), `apps/web/api/pools/service.py:155-162` (an unmatched day
renders as hours=[] with no reason). S1 therefore ADDS `case _ as unreachable:
assert_never(unreachable)` at those three named sites as its first change, which is what makes the
variant a compile error everywhere else. A zero-basin facility with an `operating_season` resolves at facility level and yields a `/swim`
status (a fourth honest state that REPLACES the `no_source` ghost for that facility — a facility
carrying an `operating_season` is excluded from `_schedule_less_statuses` (`query.py:588-612`), so
it appears exactly once per query, never as both). Status wire values, named exactly:
in-season → `status: "open_unscheduled"` (a NEW status value on `apps/web/api/swim/model.py`,
carrying the season + weather); out-of-season → `status: "closed"` + `closure_code:
"out_of_season"` — the same pair a seasonal scraped pool (Heuried in January) already serves, so
no new closed shape. This does not breach the "a schedule-less pool is never rendered closed"
invariant (`model.py:79`, CLAUDE.md): that invariant protects pools whose schedule is UNKNOWN,
and a pool whose own page states its season is out of it is knowably shut. One sentence lands in
both pinning docs to say so. The web UI is untouched: `ribbonmodel.ts:150` degrades an unknown
status to the dotted ghost, and a test pins that `"open_unscheduled"` degrades cleanly with no
raw i18n key leaking.

### The shared-source phase — a sibling of `declared_sources`

```
SharedSource:      url: str,  members: tuple[PoolCatalogEntry, ...],  parse: SharedPageParser
SharedPageParser = Callable[[str], Result[SharedFacts, ProviderError]]
SharedFacts:       operating_season: OperatingSeason | None,  admission: Admission

shared_sources(catalog) -> tuple[SharedSource, ...]
    # entries sharing a URL, ADMITTED ONLY when that URL is in the parser registry —
    # hallenbaeder.html (14 school pools) has NO registered parser: it names zero of them
    # (verified 2026-08-07), so it stays out and those pools stay no_source.

scrape_shared_sources(client, catalog, fetched_at) -> ScrapeReport
    # ONE fetch per shared page; on Ok, ONE extract per MEMBER (Name ref, same aspects);
    # on Err, ONE failure for the whole set — fail-fast fails once, not thirteen times.
```

The Planschbecken parser reads the page's own sentence — the month range via the existing
month-name machinery (`MONTH` precision; never day-precise, per [[annual-window]]'s rendering
rule), *"je nach Wetter"* → `Weather.FAIR_ONLY`, *"kostenlos"* → `Free()`. A page missing the
sentence is `Err(ParseError)` and aborts the build.

### Invariants

- Fan-out facts are **page-level only**. No per-pool accordion join, no name matching, no blurbs.
- Existing pools' resolution is unchanged: a facility without `operating_season` never produces
  `OpenUnscheduledDay`, and a rule-carrying basin inside its window resolves exactly as today.
- `ScheduleFreshness` is untouched: it describes the **timetable**, and a Planschbecken has no
  timetable — the page publishes none — so `no_source` remains the true answer for the schedule
  while the season and admission ride as separate facts.
- Blob encoding is additive-and-invisible: `operating_season` is popped when `None`, so the 44
  pools without one serialize byte-identically.

## Out of scope

- **UI.** Data first; `/pools` and `/swim` expose the facts, the web UI renders nothing new.
- **The per-pool accordion blurbs** ("mit Spielplatz") — a deleted-field's worth of data behind a
  fuzzy join; rejected with measurements.
- **`hallenbaeder.html`.** It names none of the 14 school pools; no parser, no members, no change.
- **The `flussbad-unterer-letten` pair.** Two roster entries share one real pool page — a
  *different* problem (identity aliasing, not fact fan-out); registering it here would fan one
  pool's timetable onto two entries without deciding whether they are one pool.
- **`Facility.operating_season` for scraped pools** whose seasonal rules already carry
  `ScheduleRule.season` — no duplication; the facility field is only written where no rules exist.

## Slices

### S1 — the resolver learns "open, hours unpublished"

- **Goal**: `OpenUnscheduledDay` and the season gate exist; every consumer handles them; no
  existing pool's resolution changes.
- **Touches**: `domain/schedule.py` (`OpenUnscheduledDay`, the `DaySchedule` union),
  `domain/models.py` (`OperatingSeason`, `Facility.operating_season`), `domain/resolver.py` (the
  gate), `domain/query.py` (`assert_never` at `:403-407` and `:547-551`; the zero-basin seasonal
  path → the `"open_unscheduled"` status; the `_schedule_less_statuses` exclusion),
  `apps/web/api/pools/service.py:155-162` (`assert_never` + the new arm),
  `apps/web/api/swim/model.py` (the status value + the invariant-wording sentence, mirrored in
  CLAUDE.md), `boundary/curated_dto.py` + `storage/codec.py` (`operating_season`, popped when
  `None` per the `min_age` field-serializer precedent — a recorded deviation from the
  facility-level emit-unconditionally comment at `codec.py:96-100`, which gets updated),
  `etl/field_sourcing.py`, mirrored tests. NOTE: `query.py:400`'s rule-less-basin skip is
  UNCHANGED — the `OpenUnscheduledDay` branch is reachable only through the new facility-level
  `resolve_hours(facility, (), (), …)` call, never by un-skipping a `PARSED_PROSE` basin.
- **Acceptance**:
  - A zero-rule facility with `operating_season(Mai–Sep, FAIR_ONLY)` resolves 2026-07-15 →
    `OpenUnscheduledDay(weather=FAIR_ONLY)` and 2026-01-15 → `ClosedDay(OUT_OF_SEASON)`.
  - A facility with **no** `operating_season` and no rules resolves exactly as today
    (regression-pinned on the illustrative fixtures).
  - Blob byte-stability: `'"operating_season"' not in codec.dumps(f)` for a facility without one;
    a facility with one round-trips losslessly.
  - `/swim` on the committed-fixture store is byte-identical to before the slice (no pool has an
    `operating_season` yet — the gate is inert until S3 writes one).
  - The three named match sites end in `assert_never`, and a meta-test greps that every
    `DaySchedule` match in `src/` + `apps/` does — THAT is what makes the next variant a compile
    error; mypy alone is green today with all three sites unhandled and proves nothing.
  - A facility with an `operating_season` appears exactly once in `/swim` `statuses` — never also
    as a `no_source` ghost.
- **Depends on**: [[2026-08-08-admission-union-plan]] merged (the `Admission` import surface).

### S2 — the Planschbecken page parses, offline

- **Goal**: one committed fixture yields the three facts; a page without them is a typed failure.
- **Touches**: new `providers/planschbecken.py` (`parse_planschbecken(page_html) ->
  Result[SharedFacts, ProviderError]`), the `SharedFacts` type (in `etl/scrape.py` or the
  provider), a new committed fixture `tests/providers/fixtures/planschbecken.html` (fetched once
  from the live page), `tests/providers/test_planschbecken.py`.
- **Acceptance**:
  - Against the committed fixture: `operating_season.window` is the month-granular Mai–September
    window (`precision == MONTH`), `weather is FAIR_ONLY`, `admission == Free()`.
  - A copy with the season sentence removed → `Err(ParseError)`; with *"je nach Wetter"* removed →
    `weather is ANY` (stated weather only, never assumed); with *"kostenlos"* removed →
    `admission == Unknown()` (free-ness is stated, never inferred).
  - No accordion content is read: a copy with every `<stzh-accordion-item>` stripped parses to
    the identical `SharedFacts`. CAVEAT, checked at fixture-commit time: this criterion assumes
    the season/kostenlos sentence sits OUTSIDE the accordion markup (the 2026-08-07 inspection
    says it does — page-level prose above the accordion). If the live page has moved it inside,
    the criterion is replaced by "only the sentence's own element is read" and the divergence is
    recorded.
- **Depends on**: S1 (the `OperatingSeason` type).

### S3 — thirteen pools stop being invisible

- **Goal**: the fan-out runs in the atomic build; the store carries the facts; `/swim` and
  `/pools` serve them.
- **Touches**: `etl/scrape.py` (`SharedSource`, `shared_sources`, `scrape_shared_sources`, the
  parser registry), `build/compose.py` (`ScrapedAspects.operating_season` — the dataclass lives
  at `build/compose.py:42`), `apps/web/tests/api/test_swim.py` (the S1 inertness pin's
  `seasoned == 0` premise dies at this slice's rebuild — rewrite it into the "exactly 13"
  assertion below; planned here so it is not a surprise),
  `build/compose.py:42` (`ScrapedAspects.operating_season` — the dataclass lives HERE, not in
  `etl/scrape.py`, which only imports it; and if the admission plan has not renamed the `prices`
  aspect field to `admission`, that rename lands here too),
  `cli.py` (`_compose_schedules` runs the shared phase in the same temp-DB swap),
  `tests/etl/test_scrape.py`, `tests/test_cli.py`, `apps/web/tests/test_gold_store.py`.
- **Acceptance**:
  - `shared_sources` over `data/catalog.json`: exactly **one** shared source
    (`planschbecken.html`, 13 members); `hallenbaeder.html` and the unterer-letten pair yield
    none — pinned offline with the reason asserted in the test name.
  - After a rebuild: exactly **13** blobs carry `operating_season` (literal SQL), all 13 with
    `admission_state: "free"` — free-pool count citywide becomes **17** (4 + 13).
  - `GET /swim?at=2026-07-15T14:00:00+02:00` includes a Planschbecken with
    `status == "open_unscheduled"` (season + weather surfaced), and it appears exactly once in
    `statuses`; the same query at `2026-01-15` shows `status == "closed"` with
    `closure_code == "out_of_season"`. `GET /pools/{id}` for one Planschbecken shows `admission: "free"` and the
    season.
  - A fetch failure of the shared page aborts the build **once** (one `ScrapeFailure`, non-zero
    exit, prior gold content-unchanged).
  - Every pool priced/scheduled before the slice is byte-identical in the store after it
    (fan-out enriches the 13 existing schedule-less docs; it may not alter any pool that was
    priced or scheduled before the slice).
- **Depends on**: S1, S2.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-08 | S1 | done | CRAP-gate refactor inside the slice (`find_swim_options` hit CC=32 with the new arm — extracted `_session_option`/`_seasonal_status_for`, pure code motion, /swim byte-identity re-verified by cmp after); plan line numbers had drifted (written pre-admission-union merge) — match sites identified by content, all 4 guarded (3 named + the new `_seasonal_status`); the Design's UI degrade pin was in no slice's Touches — landed here (2 vitest tests) since S1 mints the wire value; `OpenUnscheduledDay.weather` REQUIRED (recorded unfolded suggestion taken) | `_seasonal_status`'s mypy-required unreachable `OpenDay` arm raises AssertionError — one permanently-uncovered line in query.py | yes |
| 2026-08-08 | S2 | done | the plan's "Josefswiese absent" measurement was uncheckable page-wide — the page's own image alt-text inside the Josefwiese accordion spells it "Josefswiese"; pinned at the accordion-HEADING level (the measured fact the join rejection rests on). `SharedFacts` pinned to `providers/planschbecken.py` (the plan's "or" resolved). Critic round 1 blocked on a FALSE provenance claim: the fixture had been LF-normalized by a text-mode write (26 CRLF lost) while its docstring claimed byte-identity to cache entry 107cac543a59f52e — re-materialized binary-exact (39,714 bytes, verified), claim now true as written; tag-strip reordered before html.unescape as review hardening | fourth module-private German month-name table (`_MONTHS` peers in belegungsplan/schedule_scraper/operator_pages) — consolidation touches three out-of-slice modules | yes |

## Accepted drift

_(appended by hand from /dev:present findings the user has blessed; no command writes here)_

## Decisions & divergences

**2026-08-08 — pre-approval review (4 blocking, all accepted).** (1) The plan claimed the
`DaySchedule` consumers already match exhaustively — false: the only `assert_never`s in `query.py`
guard `Result` unions, and the three real match sites would swallow a new variant silently; S1 now
adds the guards at the three named sites and the mypy criterion (vacuously green) was replaced
with a grep meta-test. (2) The new seasonal status would have COEXISTED with the `no_source` ghost
(`_schedule_less_statuses` keys on basin rules), double-reporting every Planschbecken; exclusivity
is now designed and pinned. (3) "shows it `out_of_season`" named no wire field — the exact values
are now stated (`"open_unscheduled"`; `"closed"` + `closure_code "out_of_season"`), with the
"never closed" invariant reconciled in prose where it is pinned. (4) The prerequisite over-claimed
(`ScrapedAspects.admission` is not promised by the admission plan) and mis-located
`ScrapedAspects` in `etl/scrape.py`; both corrected (`build/compose.py:42`). Suggestions taken:
machine-checkable prerequisite (`status: done`), the codec emit-unconditionally comment update,
the Decision-#5 skip-boundary sentence, the accordion-placement caveat, and the UI degrade pin
(no raw i18n key).

**2026-08-08 — second pre-approval review (independent critic, 1 blocking, accepted).** S3's
acceptance gloss "(fan-out adds pools; it may not touch existing ones)" was false against the
repo: the 13 Planschbecken already exist as location-only facility docs (`seed.py:122-124`
writes one per catalog pool), so fan-out MODIFIES 13 existing blobs and adds no rows — the gloss
as written would fail a correct implementation and could steer an implementer toward minting new
ids (forbidden at `etl/scrape.py:96`). Rescoped to "enriches the 13 existing schedule-less docs;
may not alter any pool that was priced or scheduled before the slice" (owner-supplied wording).
Suggestions from the same review, not yet folded: pin the three page measurements (Josefwiese
heading, Föhrenwald absent, 12 accordion items) into S2's committed-fixture criterion; make
`OpenUnscheduledDay.weather` required rather than defaulted; pin `SharedFacts` to one owner
(drop "etl/scrape.py or the provider"); delete S3 Touches' stale `etl/scrape.ScrapedAspects`
entry; soften the "silently" over-claim for the `query.py` open_now site (NameError, loud).

### 2026-08-08 — S1 (critic: approve, round 1) + the pinned wire shape for S3

The `_seasonal_status` params wire shape was unpinned by the plan; S1 chose
and shipped: `{"weather", "season_start_month", "season_end_month",
"season_precision"}`, plus `"season_start_day"`/`"season_end_day"` ONLY at
`DAY` precision (honoring the annual-window month-rendering rule). **S3's
acceptance must assert these exact keys.** S1 also landed the Design's UI
degrade pin (2 vitest tests — no slice owned it; S1 mints the wire value)
and took the recorded unfolded suggestion: `OpenUnscheduledDay.weather` is
REQUIRED, no default — the season gate passing `operating_season.weather`
is the only producer. Critic verification of note: `/swim` byte-identity
independently reproduced (3 instants, cmp clean); the no-ghost exclusivity
guard mutation-tested (removing it fails 3 pins). The critic's claim-audit
step correctly SKIPPED this slice (no externally-sourced data transformed —
the season fact enters only at S3). Tech debt: `_seasonal_status`'s
mypy-required unreachable `OpenDay` arm is one permanently-uncovered line.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/sharedsource-fanout.md` (what EXISTS now, not what was intended).
