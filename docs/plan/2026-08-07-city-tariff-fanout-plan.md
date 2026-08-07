---
type: plan
status: in-progress
created: 2026-08-07
feature: city-tariff-fanout
branch: plan/city-tariff-fanout
worktree: .claude/worktrees/plan-city-tariff-fanout
base_branch: feat/new-ui
prerequisite: the price-age-bands work (S1 of [[2026-08-06-data-coverage-first-plan]]) must be COMMITTED — see S1 Depends on
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: ["S2"]
links: ["[[city-tariff]]", "[[2026-08-06-data-coverage-first-plan]]", "[[2026-08-02-gold-coverage-gaps]]", "[[discovery-driven-providers]]", "[[facility-field-sourcing]]"]
---

# City tariff fan-out — the pool page links to its own tariff, and the tariff has a school rate

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-06**

> for me feature is to collect as much accurate data and facts from websites; and then in ETL process clean and load them to SQL database that is golden set. Key is that we can model in simple way every type of pool or port swiming object; any sezonal opening hours; info about availability; lanes; depth; temputre; geneder restrictions etc. We shoudn't compress information; we should think about it as extract; load; transform pipeline

**2026-08-07**

> what is most tactical step to get missing data in?

## Context

`gold.sqlite` carries admission prices on **10 of 57** pools. Not because the tariff is narrow —
because `etl/scrape.py:213` gates the fan-out on `_CITY_HOST in url` where `_CITY_HOST` is the
literal `"stadt-zuerich.ch"` (`scrape.py:49`). **15 of the 26 declared sources publish their page
on `sportamt.ch`** (6 outdoor, 5 lake, 4 river) and are dropped by a substring test on a hostname.

The same tariff page carries a **separate school rate** in a row the parser already reads but
never selects, so all 4 school pools are served the Hallenbad rate:

```
Einzeleintritte                       Fr. 8.–   Fr. 6.–   Fr. 4.–     <- served to every pool
Eintritte Schulschwimmanlagen
  Einzeleintritt                      Fr. 5.–   Fr. 5.–   Fr. 2.50    <- never selected
```

Same defect class as [[2026-08-06-data-coverage-first-plan]]'s age bands: the page states it, the
code assumes it. Builds on [[city-tariff]], [[discovery-driven-providers]] and
[[facility-field-sourcing]].

## Design (signature altitude)

### The page publishes two tariffs; the provider returns both

```
CityTariffs:
    general: PriceTable    # "Einzeleintritte" — the unsectioned leading row
    school:  PriceTable    # the "Eintritte Schulschwimmanlagen" section

parse_prices(page_html, valid_as_of) -> Result[CityTariffs, ProviderError]
scrape_prices(client,   valid_as_of) -> Result[CityTariffs, ProviderError]
```

Both rows live in the **same `<stzh-datatable>` element** — the one carrying a
`Eintritte Schulschwimmanlagen` section — so they share its column headers and therefore the
same published bounds (`min_age` 20 / 16 / 6) that [[2026-08-06-data-coverage-first-plan]]
introduced. Nothing new is parsed for the bounds. `preise_abos.html` contains **two**
`<stzh-datatable>` elements and the second (winter) also opens with `Einzeleintritte 8/6/4` but
has **no** school section; taking one tariff from each would silently mix two header sets, so
both rows must come from the same element.

### Row selection is section-anchored

A grouping row is one whose price cells are all blank — there are **five**
(`Mehrfacheintritte`, `Saisonabo Bäder`, `Jahresabo Bäder`, `Eintritte Schulschwimmanlagen`,
`Eintritte Sauna City und Leimbach`).

```
general := the "Einzeleintritt*" row appearing under NO section (row 0, price cells filled)
school  := the "Einzeleintritt*" row under "Eintritte Schulschwimmanlagen"
```

**Three** rows in that element begin with `Einzeleintritt`; the third is the sauna's
(`Fr. 12.–`, and its own label says a Hallenbad ticket must be bought *in addition*). Today's
parser takes the first match and is correct only by row order.

### The fan-out follows a DISCOVERED LINK, not a host

The pool's own page states whether the city tariff applies by **linking to it**:

```
states_city_tariff(page_html) -> bool     # an href whose PATH ENDS
                                          # sport-und-badeanlagen/preise-abos.html

# S1 ships this form — host test retained, school-vs-general only:
tariff_for(source: DeclaredSource, tariffs) -> PriceTable | None

# S2 widens it to the end state and deletes the host test:
tariff_for(source: DeclaredSource, page_html, tariffs) -> PriceTable | None
    # no tariff link  -> None
    # kind is SCHOOL  -> tariffs.school
    # otherwise       -> tariffs.general
```

Match on the **path suffix**, never on equality with `price_scraper.PRICES_URL`: across the
fixtures the link appears 22× relative (`/web/de/stadtleben/…/preise-abos.html`) and once
absolute (`https://www.stadt-zuerich.ch/de/…`), and `web/de/` vs `de/` differ.

`_CITY_HOST` and the host test are **deleted**. This is [[discovery-driven-providers]] rule 2
applied to pricing: the binding is a link the upstream page emits, re-derived every run, not a
curated host list that rots when a WFS URL drifts.

It is also the only correct discriminator. Measured across all 26 declared sources against their
committed fixtures: **21 link to the tariff page, 5 do not** — and the 5 are exactly the pools a
city tariff must not be asserted for:

| pool | why no tariff |
|---|---|
| `hallenbad-altstetten` | private operator (`bad-altstetten.ch`); links to its own `/schwimmen-2#preise` |
| `flussbad-au-hoengg` | *"Der Eintritt ins Flussbad Au-Höngg ist gratis."* |
| `flussbad-oberer-letten` | *"Der Eintritt ins Flussbad Oberer Letten ist gratis."* |
| `seebad-katzensee` | *"Der Eintritt ins Seebad Katzensee ist gratis."* |
| `maennerbad-schanzengraben` | *"wird privat betrieben … ein Gratisbad"* |

A host-keyed fan-out would have charged Fr. 8.00 at four pools the city publishes as free. The
tariff page warns of exactly this: *"Es gibt Vergünstigungen aber auch Gratisbäder."*

### Invariants

- A pool whose page does not link the tariff receives **no** price. Free and private are never
  assigned a rate.
- Every served amount and every `min_age` is read from the page; none is a constant.
- Price coverage changes; **nothing else about a facility does**. No schedule, closure, basin,
  identity or resolver behaviour is touched.

## Out of scope

- **Storing free-ness.** Four pools are now *known* free, and `prices=None` still conflates
  *free* with *unknown* on all of them. Recording it needs `Admission = Free | Tariff | Unknown`,
  a blob-format change across all 57 pools. Deferred to its own plan — S2 emits an audit line
  naming the free pools so the fact is visible rather than lost.
- **The 31 pools that are not declared sources**: 13 Planschbecken sharing one URL, 14 school
  pools sharing `hallenbaeder.html`, `seebad-enge` + `freibad-dolder` (own pages, excluded by
  `_UNPARSEABLE_OPERATOR_PAGES`, `scrape.py:68-79`), and the two `flussbad-unterer-letten`
  entries sharing a URL.
- **Abonnemente** (Kombi6/12, Sportabo, Saisonabo) and the **sauna surcharge**. Real data on the
  page that we are not taking; none is single-admission pricing. `Feature.surcharge_chf` exists
  with no producer. Named so the residue is on record.
- **Resolver, `ClosureCode`, UI.**

## Slices

### S1 — the school pools stop paying the Hallenbad rate

- **Goal**: the 4 school pools serve the rate the city prints for Schulschwimmanlagen.
- **Touches**: `providers/price_scraper.py` (`CityTariffs`, section-anchored selection,
  `parse_prices`/`scrape_prices` return type), `etl/scrape.py` (`tariff_for`, the
  `scrape_declared_sources` parameter), `cli.py:290,292` (the two call sites),
  `etl/field_sourcing.py` (the `facility.prices` row), `tests/providers/test_price_scraper.py`,
  `tests/etl/test_scrape.py`.
- **Acceptance**:
  - Against the committed `preise_abos.html` fixture, as the projection actually asserted:
    - `[(e.min_age, e.amount_chf) for e in general.entries] == [(20, Decimal("8.00")), (16, Decimal("6.00")), (6, Decimal("4.00"))]`
    - `[(e.min_age, e.amount_chf) for e in school.entries]  == [(20, Decimal("5.00")), (16, Decimal("5.00")), (6, Decimal("2.50"))]`
  - A fixture copy whose `Eintritte Schulschwimmanlagen` section row is removed returns
    `Err(ParseError)` — a missing school tariff is never silently the general one. (This, not an
    amount assertion, is what proves the section anchoring: an amount check passes against
    today's parser unchanged.)
  - Both tariffs are read from the **same** `<stzh-datatable>`: a fixture copy with the FIRST
    element removed returns `Err(ParseError)` rather than falling through to the winter table.
  - `tariff_for(source, tariffs)` — the **2-arg S1 form**, host test still in place — over
    `data/catalog.json`'s declared sources: `tariffs.school` for the 4 `SCHOOL` entries,
    `tariffs.general` for 6, `None` for the other 16.
  - Priced-pool count after a rebuild is **still 10** — S1 corrects rates, it does not widen
    coverage. Gate it literally:
    `select count(*) from pool where json_extract(facility_doc,'$.prices') is not null` == 10.
  - `GET /swim?at=2026-08-13T17:30:00+02:00&eligible_only=false` for
    `schulschwimmanlage-aemtler` (2026-08-13 is a Thursday; the 17:15–19:00 rule is `GirlsOnly`,
    so **`eligible_only=false` is required** — the default `true` filters the option out before
    a price is rendered, and `_girls_only` denies every gender) returns an option whose `price`
    starts `"Erwachsene (ab 20 J.) Fr. 5.00"` for `age=30`, and `"Kinder (ab 6 J.) Fr. 2.50"`
    for `age=10`. Today those read `Fr. 8.00` and `Fr. 4.00`.
- **Depends on**: the price-age-bands slice of [[2026-08-06-data-coverage-first-plan]] being
  **committed**. `PriceEntry.min_age` and the three-member `PriceCategory` this design leans on
  exist only in the git index as of 2026-08-07; at `HEAD` of `feat/new-ui`,
  `domain/pricing.py` still has `PriceCategory.SENIOR` and no `min_age`, so a fresh worktree at
  `HEAD` cannot satisfy the acceptance criteria above. Verify with
  `git show HEAD:src/swimzh/domain/pricing.py | grep min_age` before starting.

### S2 — the tariff follows the link the page publishes

- **Goal**: every pool whose page links the tariff carries it; every pool that does not is
  reported, not silently unpriced.
- **Touches**: `providers/price_scraper.py` (`states_city_tariff`), `etl/scrape.py` (delete
  `_CITY_HOST` and the host test; `tariff_for` takes the `DeclaredSource` rather than a
  `(entry, url)` pair that can drift apart; the no-tariff note), `etl/scrape.ScrapeReport`
  (a third field for build notes — it carries only `extracts` and `failures` today,
  `scrape.py:117-119`), `cli.py` (surface the notes), `tests/etl/test_scrape.py`,
  `tests/test_cli.py`.
- **Acceptance**:
  - `states_city_tariff` over the 26 declared sources' committed fixtures: **True for 21**,
    **False for exactly** `hallenbad-altstetten`, `flussbad-au-hoengg`, `flussbad-oberer-letten`,
    `seebad-katzensee`, `maennerbad-schanzengraben`. Offline; no network in tests.
  - `hallenbad-altstetten` stays `False` although its page carries **9 `href`s containing
    `preise` across 3 distinct targets** (`/schwimmen-2#preise` ×5, `/schwimmen-2#schwimmpreise`
    ×2, `/sauna#saunapreise` ×2) — the match is on the tariff page's own path, not the substring.
  - `_CITY_HOST` no longer exists anywhere in `src/`.
  - **No regression**: all 10 pools priced before this plan are still priced after it.
  - After a rebuild the store has **21** pools with prices, up from 10: 6 city-host indoor-kind
    (5 `indoor` + Käferberg, `thermal` in gold by `data/registry.yaml` override), 4 `school`,
    and 11 on `sportamt.ch` (6 `outdoor`, 4 `lake`, 1 `river` — `frauenbad-stadthausquai`).
  - The build emits one note per no-tariff declared source, naming all five, and **exits 0** —
    a free or private pool is not a build failure. Gated by a `tests/test_cli.py` case over the
    committed fixtures, not by a manual build. The note exists because the live build reads
    `fetch_roster`, not the committed `catalog.json`, so the offline pin above cannot catch a
    WFS URL drift that silently deletes a price.
  - `GET /swim` for `freibad-heuried` at `2026-08-13T10:00:00+02:00` with `age=30` returns an
    option whose `price` starts `"Erwachsene (ab 20 J.) Fr. 8.00"`, where it has no price today.
  - `GET /swim` for `flussbad-oberer-letten` at the same instant returns an option with
    `price is None` — a free pool is never assigned a rate.
- **Depends on**: S1

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-07 | S1 | done | orchestrator finished the slice after the implementer subagent died twice on API errors; `apps/web/tests/fixtures/aemtler_girls_only.json` regenerated (outside Touches, forced by the slice); the SQL priced-count gate landed in `apps/web/tests/test_gold_store.py` (not named in Touches) | a failed `scrape_prices` still degrades silently to `tariffs=None` (`cli.py:290-292`), and the stricter parser widens that blast radius — one dropped heading now unprices all 10 pools with exit 0 | no |

## Decisions & divergences

**2026-08-07 — pre-approval review: the host-keyed fan-out was withdrawn.** The plan originally
widened `_CITY_HOSTS` to include `sportamt.ch` (evidence: `http://www.sportamt.ch/freibad-heuried`
302s to `https://www.stadt-zuerich.ch/freibad-heuried`) and claimed 25 priced pools. The critic
showed that **4 of those 15 sportamt pools publish "Der Eintritt … ist gratis"** and that
`maennerbad-schanzengraben` states *"wird privat betrieben"*, so the host rule would have invented
a Fr. 8.00 charge at four free pools — violating this plan's own "no tariff is invented"
invariant. Replaced with the discovered tariff link, which is page-stated, needs no host list,
and yields **21**. The 302 fact is kept in [[city-tariff]] as background, not as the rule.

**2026-08-07 — pre-approval review: three acceptance criteria were unrunnable.** A `PriceEntry`
(a 4-field frozen dataclass) was compared to 2-tuples; two `/swim` criteria named no `at`, which
for the seasonal `freibad-heuried` means the query yields no option at all outside its season,
and asserted `"Fr. 8.00"` where the rendered field is `option.price.display`
(`apps/web/api/swim/service.py:76`) — `"Erwachsene (ab 20 J.) Fr. 8.00"` since the age-bands
work. All three restated concretely.

**2026-08-07 — pre-approval review: S1 and S2 acceptance were mutually unsatisfiable.** S1
required `general` "for the remaining 21" while also requiring coverage to stay at 10, but
widening the host set is S2's change. S1's `tariff_for` criterion is now stated against the S1
host set (4 / 6 / 16).

**Suggestions taken without dispute**: the grouping-row enumeration was 4, is 5 (`Jahresabo Bäder`
was missing); the two-`<stzh-datatable>` hazard is now an explicit criterion; the tautological
"no 12.00/10.00 entry" criterion was dropped; the out-of-scope 31 accounted for only 27;
`tariff_for` takes the `DeclaredSource`; `ScrapeReport`'s new note field is named in Touches;
the "pin the 302 as a comment" criterion was dropped as uncheckable; `pause_after` moved from
S1 to S2, where the coverage change is inspectable.

**2026-08-07 — re-review round 2.** Three further blocking findings, all accepted: the aemtler
`/swim` criterion was unrunnable because that Thursday session is `GirlsOnly` and
`swim/router.py:31` defaults `eligible_only=True`, so the option is filtered out before a price
is rendered (`eligible_only=false` added, with the reason); the Design showed only the end-state
3-arg `tariff_for`, which S1 cannot satisfy and cannot evaluate from `data/catalog.json` (the
2-arg S1 form is now stated explicitly); and `hallenbad-altstetten` has 9 `preise` hrefs across
3 distinct targets, not "three hrefs" — a test written to the old wording would fail.
Also taken: the `scrape.py` citation (`:68-79`), both href forms named in the Design, the
no-tariff note gated by a `tests/test_cli.py` case rather than a manual build, an explicit
no-regression clause on S2, and the literal SQL for the "still 10" gate.

**Suggestion not taken**: replacing the substring host test with a `urlparse` netloc-suffix
comparison. The host test is **deleted** rather than hardened, so there is nothing to harden.

**2026-08-07 — S1: the implementer subagent died twice mid-slice on API errors.** Its partial
work landed correctly in the worktree (the absolute-path guard held; nothing leaked to the main
checkout) and was resumed once from transcript, then finished by the orchestrator: the
`tests/etl/test_scrape.py` cases and one leftover rename (`cli.py:320` still referenced the
removed `prices`, which `ruff` caught as F821). Both gates ran normally on the result.

**2026-08-07 — S1 review: the critic mutation-tested the section anchoring.** It reverted
`_single_entry_row` to first-match-wins and confirmed three tests fail, so the anchoring is
load-bearing rather than passing by row order. Its one blocking finding — the plan's literal
priced-count SQL gate existed in no test — was fixed by adding
`test_the_priced_pool_count_is_the_coverage_ratchet` and
`test_the_school_pools_are_served_the_school_tariff` to `apps/web/tests/test_gold_store.py`,
asserted on the fully-built `gold_db` so they cover scrape → compose → codec.

**2026-08-07 — the tautological sauna test was replaced.** The critic found
`test_the_sauna_row_is_never_mistaken_for_a_tariff` unfalsifiable (the sauna row sits under its
own section, so any anchoring break yields `Err`, caught elsewhere) — the same criterion this plan
had already dropped as tautological before approval, re-added as a test. Replaced with
`test_an_unreadable_school_amount_fails_rather_than_serving_the_general_rate`, which covers the
previously-unexecuted `school` error branch at `price_scraper.py:221`.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/city-tariff-fanout.md` (what EXISTS now, not what was intended).
