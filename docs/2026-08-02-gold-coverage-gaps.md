# Gold-store coverage gaps — what is extractable but unextracted (2026-08-02)

Measured against the committed `gold.sqlite` (57 pools) and against **live** fetches of every
pool's WFS `url`, run through the production parsers. Not a plan — an evidence catalogue.

**Revision 2 (2026-08-02, post-investigation).** Eleven parallel investigations re-derived every
claim in revision 1 against live pages. Several of revision 1's claims were **wrong**; they are
corrected in place and listed in [Corrections](#corrections-to-revision-1). One finding is not a
gap at all but a **live wrong answer being served today** — see Gap 7.

---

## 0. URGENT — a false answer in the store right now

`hallenbad-altstetten` has `closures: []` and a rule `sat/sun 08:00–18:00`. Its operator page says:

> *"Am Donnerstag, 30. Juli – Sonntag, 16. August 2026 findet die jährliche Betriebsrevision
> statt. Während dieser Zeit ist der gesamte Betrieb geschlossen."*

Today is 2 August. **We tell users a closed building is open**, on 1 of the only 7 pools carrying
any schedule — a wrong answer on ~14% of our entire schedule surface, for 18 days. `ClosureRange`
and `Notice` already exist and are already composed end-to-end; this needs a date-range regex over
one page and **no Gap-2 domain work**. Fix first, independent of everything else.

A second, structural falsehood ships on **all 57 pools**: `public_holiday_policy` is the literal
`HolidayPolicy.NORMAL`, hardcoded at `build/compose.py:143`, supplied by no provider and no
crosswalk. `resolver.py:88-105` branches on it and falls straight through to ordinary weekday
rules — so **on Christmas Day and Good Friday we tell every user every pool runs normal hours**.
For Bungertwies that contradicts its own page (`Karfreitag geschlossen`, footnote 3). Empty fields
are honest; this one is manufactured. See Gap 8.

---

## 1. Baseline: what the gold store holds

| fact | pools with it | of 57 |
|---|---|---|
| geo, geo_sport_id, address, name, kind, url | 57 | 100% |
| `basins` (any) | 8 | 14% |
| schedule rules | 7 (6 indoor + käferberg) | 12% |
| prices | 6 | 11% |
| closures / notices | 6 | 11% |
| basin dimensions | 2 | 4% |
| features | 4 | 7% |
| **lockers / amenities / accessibility / website / last_admission_before / measured_temp_c** | **0** | **0%** |
| `public_holiday_policy` | 57 — **fabricated**, see §0 | — |

By kind: `indoor` 6/6 scraped, `thermal` 1/1, and **0/50** of `school` (18), `paddling` (13),
`outdoor` (7), `lake` (6), `river` (6).

**The structural cause** is `etl/scrape.py:106` — `if entry.kind is not PoolKind.INDOOR or not
entry.url: continue`. Note the precedence: this `continue` fires **before** the `_CITY_HOST` price
test at `:120`, so for all 51 non-indoor pools **the host test is dead code**.

---

## Gap 1 — school timetables: 4 pools, and a safety bug in the obvious fix

The city overview page states the split definitively: exactly **5 of 18** Schulschwimmanlagen have
public swimming; the rest sit under *"Schulschwimmanlagen ohne öffentliches Schwimmen"*. But only
**4 carry a per-pool URL** in the roster (aemtler, altweg, riedtli, tannenrauch); **borrweg has the
generic overview URL** and needs discovery. The other 13 correctly 404 on a slug.

**`parse_schedule` silently drops 45% of school rows** (20 source rows → 11 rules). School pages
encode multi-session days as continuation rows with a `\xa0` day cell; the Hallenbäder pack slots
into one cell with `<br>`. `_parse_days('\xa0')` → empty → the row is skipped. The dropped rows are
disproportionately the *differentiated* ones.

**Shipping the kind-gate flip alone creates a correctness regression.** Aemtler's Thursday
17:15–19:00 is `für Mädchen` (girls only); `_parse_category` matches on `"frau"`, so it classifies
as `PublicSwim` — the app would tell an adult man he may attend a girls-only session. Altweg has a
trans/non-binary session for which `SessionAccess` has **no member at all**, and 8 `für Erwachsene`
rows fold to `PublicSwim` though `AdultsOnly` exists.

**Gain:** 7→12 pools scheduled, 42→62 rules, `WomenOnly` **2→7** citywide. *"Women-only swim on
Monday evening"* currently returns a **false empty**; after the fix it returns Aemtler 18:45–19:30.
Plus 5 basin lengths and nominal temps from page prose.

**Design.** Replace the kind gate with a **URL-shape predicate derived from the roster**: a pool is
a declared schedule source iff it owns a URL no other roster entry shares. Zero network, zero
hardcoded slugs, and it generalises to Gaps 5 and 6 (13 paddling pools share one page). Do **not**
relax the gate to `kind in {INDOOR, SCHOOL}` — all 14 generic-URL pools would fetch
`hallenbaeder.html`, `parse_schedule` returns `Err` on it, and **every build would abort forever**.
Borrweg's URL comes from `page_provider` index discovery, emitted as `(Name, url)` and resolved
through the existing `pool_alias` lookup; discovery failure must be **non-fatal**, page-parse
failure stays fatal.

`CLAUDE.md` cites `aemtler` as the canonical `no_source` example in two places (plus
`ScheduleFreshness` docstrings and `test_schedule_freshness.py`). That is now false —
`schulschwimmanlage-hardau` is the clean replacement.

## Gap 2 — seasonal outdoor hours: 19 pools, the one real domain decision

All 19 sportamt.ch URLs 302 to `stadt-zuerich.ch/<slug>` and carry an `stzh-datatable` in the
**same row encoding `_ROW_RE` already matches** — but keyed by date range, not weekday:

```
columns = ['Zeitraum','Öffnungszeiten bei jedem Wetter','Öffnungszeiten nur bei schönem Wetter']
rows    = [["9.–29. Mai","9–14 Uhr","14–20 Uhr"],
           ["30. Mai–16. August","9–14 Uhr","14–21 Uhr¹"], …]
```

### Ground truth (all 18 pages, exhaustive)

- **Four header shapes, not one.** All-weather + fair-weather (12 pools); all-weather only (3);
  **fair-weather only** (1 — maennerbad); and `Badbereich|Zeit|""` (mythenquai, a *second* table
  with no heading and no stated relation to its first).
- **Fair-weather is provably additive**: all-weather `end` == fair-weather `start` in **100% of 40
  rows**, corroborated by frauenbad prose. But the page never states the rule.
- **Zero gaps, zero overlaps** between consecutive Zeitraum rows in every pool — an observed
  regularity of one snapshot, *not* a stated invariant.
- **The year exists.** `Öffnungszeiten 2026`, once per page, in a heading whose DOM position varies
  (slotted *inside* the datatable on 9 pages, a sibling heading on 7, both on 1). A cell-only
  parser loses it.
- **Footnote ¹ is a daylight caveat**, byte-identical on 13 pages: *"Schwimmbetrieb ab August nur
  solange die Aufsicht aufgrund der Lichtverhältnisse gewährleistet werden kann."* It makes every
  August-onward closing time an **upper bound with an unknown real end**. Footnote ² means two
  different things on two pools (an event-scoped early close; a basin restriction).
- Season extents vary 11 Apr–25 Oct down to 17 May–11 Sep; rows vary 2–7. Minute separator is a
  **dot** (`14–19.30 Uhr`). maennerbad puts weekdays *inside* the value with a `\xa0` continuation
  row. mythenquai has **open-ended** times (`Täglich ab 7 Uhr geöffnet`) and two rules joined by a
  bare `<br>`.

### The modelling decision

`ClosureCode.SEASONAL_BREAK` **already exists** and is translated in all five locales — but has
**no live producer** (`_CLOSURE_WORDS` lacks `sommerpause`). And `_scope_applies`
(`resolver.py:40-48`) **never receives the date**, so a season is currently *undecidable* from the
arguments it gets. `NO_SESSIONS` is a lie-in-waiting: an out-of-season day renders "No sessions
scheduled".

| option | shape | cost | verdict |
|---|---|---|---|
| **A — bolt-on** | `season: AnnualWindow \| None` + weather field on `ScheduleRule` | ~4 resolver lines, 1 DTO pair, **0 existing test edits** | recommended, with the caveat below |
| **B — `Applicability` union** | replaces `DayScope` with `Always \| DuringSchoolTerm \| … \| AnnualWindow \| AllOf` | ~18 mechanical test edits | more honest; **`AllOf` is unjustified** — see grep |
| **C — layered `OperatingPeriod`** | one period per Zeitraum row, each with its own timetable | + `BasinDTO` shape change | defer behind a gate |

**The deciding experiment.** Both designs named the same falsifier: does any pool combine a season
with a school-calendar qualifier? Grep for `Ferien|Schul|Feiertag` inside every seasonal table
across all 18 pages: **zero hits** (one incidental page-level hit on auhof). The composition
argument for a union collapses; a nullable field composes them for free.

**Rejected by both designers, and by this doc: a day-level `ConditionalDay`/`MaybeOpenDay`.** On
heuried, 9–14 is *certainly* open and only 14–21 is weather-dependent. A day-level "maybe" launders
a known fact into an unknown — strictly less honest — and forces a fourth UI terminal state plus an
edit to `test_honesty.py`, a guard test that exists to prevent exactly that. Weather belongs on
`ResolvedSession`, mirroring how `Basin.lane_plan` carries its three states on the thing the
uncertainty is about.

**Open caveat (raised by Gap 5, unresolved).** Option A puts the season on `ScheduleRule`, which
requires a `TimeRange`. The 13 paddling pools have a season and **no hours at all**, and
seebad-enge has a whole-schedule weather disclaimer. So either season needs a **facility-level**
home for the hours-less case, or `catalog.freshness_of` ("has rules → scraped") and `query.py:392`
("no rules → skip") must both change from *has rules* to *has resolvable hours* — otherwise those
pools flip to `scraped` and `/swim` emits an option with no real hours. **Decide this before
writing code.** Related: the paddling season is month-granular ("Mai bis September") while the
tables are day-precise, so the type must distinguish imprecise from precise bounds rather than
inventing 1 May / 30 September.

**Serialization trap.** `RuleDTO` has no pop-when-default serializer (unlike `BasinDTO`), so a new
field changes bytes on every rule in every blob and trips the byte-stability guards in
`tests/storage/test_codec.py`. Cheap precedented fix; a landmine if unnoticed.

**Year-free vs year-bound:** recommend year-free windows for resolution *plus* the scraped year
stored as provenance — staleness becomes knowable without minting dates the city never published.

## Gap 3 — locker/rental tables: 15 pools, 101 rows, and a taxonomy that fits 27 of them

**Owner decision (2026-08-02): collect the data now; UI comes later.** So the absence of a lockers
panel is *not* a blocker for this gap and no UI slice is in scope. The acceptance criterion is the
data landing correctly in the gold store and on the API, not anything rendering.

`domain/lockers.py` fully models `LockerCategory`/`LockerMechanism`/fee/deposit/period/`raw`, and
the whole domain→DTO→API path **already exists and is dark** — `FacilityDetailOut.lockers` is
populated by `pools/service.py:175`, and `apps/web/tests/api/test_pools.py:166` *asserts it is
empty* (that assertion flips). No lockers panel exists in the UI at all.

**The real blocker is not the UI — it is the fatal-abort gate.** All 15 pools are
outdoor/lake/river, so `etl/scrape.py:106` never fetches their pages; and if the gate is simply
widened, `parse_schedule` returns `Err` on the `Zeitraum` shape and `ScrapeReport.failures` aborts
the whole build. Rentals therefore need **either** Gap 2 landing first, **or** a per-aspect split so
a pool can contribute rentals + notices while its schedule is honestly absent. Recommended step 0:
widen the gate to "has a url" and make the per-pool result per-aspect.

Corpus is **15 pools / 101 rows** (not 10/~60): +seebach 11, zwischen-den-hoelzern 10, wollishofen
8, auhof 8, unterer-letten 1. Today's 3-member enum expresses **27 of 101 rows**:

| bucket | rows | covered? |
|---|---|---|
| storage (Garderobenkasten, Wertsachenfach, Wäschefach, Saisonkasten, Liegestuhlfach) | 44 | 27 of them |
| cabin (Tages-/Saisonkabine) | 19 | no |
| equipment (deck chair, parasol, towel, swimwear, padlock, bike lock, play kit) | 32 | no |
| venue hire (Mehrzweckraum, Lounge, Pavillon, Mööslihalle) | 6 | no |

**Design: a `Rental` concept alongside `LockerOption`, with `LockerOption` as a pure projection** —
not an extended enum. `LockerCategory.SUNSHADE` would render deck chairs under a heading that says
Lockers. 29 distinct item names; match **longest-first** (`Liegestuhlsaisonfach` contains
`Liegestuhl`; `Saisonkasten` and `Garderobenkasten` both contain `kasten` — wrong order misfiles 14
rows), and unrecognised items become `OTHER` carrying the exact label, never dropped.

`deposit_chf: Decimal | None` **cannot express `Ausweis als Depot`** (2 rows) — `None` means "no
deposit", so it would tell a swimmer to bring nothing when the truth is "leave your ID". Replace
with a closed union `NoDeposit | CashDeposit | IdDeposit | UnknownDeposit`, and likewise
`Free | Amount | OnRequest | Unknown` for fees (8 rows are `auf Anfrage` / `via Kiosk`).
Add `LockerMechanism.OWN_PADLOCK` — 20 rows say *eigenes Vorhängeschloss mitbringen*, and "do I
need coins?" is the actual user question.

**Parsing:** the header is an **attribute, not a row** — `_ROW_RE` is header-blind and flattens
every table on the page into one list, and attribute order is not stable (`baederinfos` emits
`rows` before `columns`). Use a quote-aware attribute matcher. The extractor is a **parser, not a
fetching provider** (`parse_rentals(html)` called on bytes `etl/scrape.py` already fetched, exactly
like `parse_notices`) — so it needs **no new cache tier**, and adding one would be actively wrong.

**Counterexample that kills every hardcode:** frauenbad's Garderobenkasten is `Fr. 1.–, plus Depot
Fr. 20.–`, unlike the other 11 pools' `gratis`.

## Gap 4 — live temperature: the inline block *is* Baditicker, and gains 0 pools

**Revision 1 was wrong about this gap.** Same-instant comparison of all 57 roster URLs against the
feed: **16/16 temperatures agree exactly**, and where the page exposes an `aktualisiert` row it is
byte-identical to the feed's `dateModified`. The inline `baederinfos` block is the Baditicker
record rendered server-side by AEM — not an independent source.

- **Temperature: +0 pools.** The 18 facilities with an inline reading are precisely the 18 the feed
  already covers. The feed carries 6 *more* rows (5 Hallenbäder + Käferberg), all with empty
  `<temperatureWater>`.
- **School and paddling gain nothing** — `hallenbaeder/*.html` and `planschbecken.html` have **no
  `baederinfos` element at all**. That was the entire stated reason to prefer url-keying.
- **"url-keyed vs poiid-keyed" is a false dichotomy** — the *feed* carries `<urlPage>`.
- **Occupancy: +0.** `Auslastung`/`Anzahl Gäste` are the literal string `"-"` server-side on all 22
  pages; they fill client-side from the CrowdMonitor websocket, which `data/sources.md:18` defers
  pending vendor terms.
- Cost of the page route: **18 fetches ≈ 900 KB to reconstruct one 15.6 KB feed request** — ~58×
  the bytes for a strict subset.

**Answer to "should this enter the gold store": no — (a), runtime-only.** `Basin.measured_temp_c`
is a bare `Decimal | None` with **no timestamp companion**, so option (b) "build-time with explicit
staleness" is not even available without a domain change bought to make a worse copy of a runtime
path that already works. `core/cache_tiers.py` already *has* the third tier (`LIVE`/2 min).

**What is genuinely new and page-only: `Hinweise`** — operator-authored, same-day, on 7 of 18:
*"Letzter Einlass 20:30 Uhr"*, *"Grillstellen gesperrt - Feuerverbot"*, *"5m Sprungbrett ist
gesperrt"*. That deserves its own narrow live port (`LiveNotice`, mirroring `LiveTemp`), read on
`/pools/{id}` **only**, with its own in-process TTL (the web runtime wires the disk cache OFF
precisely so `age` cannot lie).

**Status vs the resolver — the resolver wins, and one pool settles it.** Käferberg right now:
inline says `Status: offen`; the feed says `offen` with `dateModified` **six months stale**; *the
same page's own prose* says *"bis und mit Sonntag, 2. August, Bad geschlossen (Revisionsarbeiten)"*;
**our gold store already has that closure and is correct**. Promoting the live flag to authority
would take a right answer and break it. Rule: the resolved schedule always wins; live `is_open` may
**narrow**, never widen; suppress it where `freshness == scraped`.

**Two live bugs found in passing.** `providers/baditicker.py:119` maps an *empty*
`openClosedTextPlain` to `is_open = False` — **absent rendered as closed** for 5 Hallenbäder with
1–2-year-old timestamps. And `data/registry.yaml`'s `crowdmonitor_keys` hold *display names*
(`['Bungertwies', …]`) where the protocol uses uids (`SSD-3`, `LETZI-1`) — every hand-authored key
misses. The pages and the websocket both carry the correct uid; derive it, per CLAUDE.md's
everything-sourced rule. The websocket also resolves the S4 ledger's open question:
`flb8803` = "Flussbad Unterer Letten (Flussteil)".

## Gap 5 — 13 paddling pools: a deterministic join, and one pool that must stay empty

**The binding is not ambiguous.** The page is an accordion, and each item's Stadtplan link carries
`selectedObject=pb3965` — **that is the WFS `poi_id`, already stored as `geo_sport_id`**. So it is
the same external-key join `build/reconcile.Xref` already implements. **12 of 13 bind exactly,
zero mismatches.**

Both fallbacks are provably wrong on live data: **ordinal binding misbinds 7 of 13** (the page has
12 items, the roster 13, and the missing one sits 7th alphabetically, cascading every later row);
**name binding fails 2 of 12** ("Josef**s**wiese" vs "Josefwiese", "Pfingstweid**park**" vs
"Pfingstweid").

**Prerequisite:** `build/seed.py:151-160` emits the `geo_sport` xref *only* for pools with a
`data/registry.yaml` entry. None of the 13 has one, so `pool_xref` holds **zero `pb####` rows** and
the join cannot resolve today. ~3 lines, and it enables any future poi_id-keyed provider.

**Gain:** 12 pools × free price + 29 feature instances (store-wide features **4→16 pools**, 9→38
instances) + 11 rule-less `CHILDREN` basins + `heated` for Fritschiwiese. No hours ever — the page
contains **zero occurrences of "Uhr"**.

**Föhrenwald is in the roster and absent from the operator's page.** The tempting move is to apply
the page-level *"Die Nutzung der Planschbecken ist kostenlos"* to all 13. Do not: that publishes
"free, open May–September" for a pool the city no longer lists, to a parent who then drives there
with a toddler. Model it as an audited, non-fatal **`UnlistedPool`** receiving *no* page facts.

Paddling pools are **not** excluded from `/swim` by kind — `find_swim_options` is kind-blind and a
3-year-old passes eligibility. They are excluded purely by having zero basins (`query.py:392`).
Josefwiese's descriptor says *"Wasserspiel"*, not Planschbecken; record the discrepancy for owner
review rather than letting a scraper flip a `PoolKind` from prose.

**New domain needs:** `FeatureKind` gains `PLAYGROUND`, `SPORT_COURT`, `BBQ`, `ANIMALS` (each ×5
locales); `Basin.heated: bool | None` (**tri-state** — `False` would assert the other 11 are
unheated, which the page never says); `pricing.free_admission()` + `PriceTable.is_free`.

## Gap 6 — prices: the "one-line host fix" would attach a tariff to free pools

**Revision 1 was wrong about this gap too.** Two reasons the host predicate cannot be repaired:

1. **It is dead code.** The `INDOOR` gate at `scrape.py:106` `continue`s before `:120` is reached,
   so for all 51 non-indoor pools the host test never runs. Flipping it changes nothing.
2. **Making it pass would publish a CHF 8.– tariff for pools the city says are free.** Verified
   live: 6 pools state *"Der Eintritt … ist gratis"* / *"Gratisbad"* with **no** tariff link — the
   three Flussbäder, au-hoengg, katzensee, maennerbad. Plus 13 Planschbecken (*"kostenlos"*). The
   honest split is **10 paid / 19 free**; a hostname test gets 6 of 17 backwards.

**The school pools have a different tariff.** All 18 link the same `preise-abos.html`, but it
carries a separate `Eintritte Schulschwimmanlagen` block: **5.– / 5.– / 2.50** vs Bäder 8/6/4.
Link-presence alone overstates by 60% on 18 pools.

**Design: discovery, which the codebase already planned.** `page_provider.py:14-16` names *"a price
page"* as the next link class; `fidelity_report.py:404-406` says a discovered price page *"is the
intended route"*. It costs **zero new HTTP requests** — `_attach_lanes` already fetches all 57 pool
pages. The applicability signal and the price fact then come from the same document: a page linking
the tariff *is* the city asserting it applies; a page saying *gratis* is it asserting the opposite.
Default-deny: no positive per-page signal → `None`.

**Free must be materialised**, not left as `PriceTable(entries=())` — that renders identically to
"we don't know". Zero-amount entries plus an `is_free` render branch (else `priceLabel()` prints
`CHF 0.00`).

**A pre-existing bug this scales 6→16 pools.** Live tariff columns are `Erwachsene (ab 20 J.)` /
`Jugendliche (ab 16 J.)` / `Kinder (ab 6 J.)`; `pricing.category_for_age` uses ≤5 / ≤15 / ≥65. All
four bands are wrong today: a 10-year-old is charged 6.– (truth 4.–), a 17-year-old 8.– (truth
6.–), and **a 70-year-old 6.– when the truth is 8.–** — there is no senior discount on this tariff
at all. `/swim` shows the age-matched entry, so this is user-facing now.

**Trap:** heuried's page contains *"Pickleball-Schläger können gratis gemietet werden"* — a naive
`'gratis' in text` free-detector produces a false positive on a **paid** pool.

**Payoff lands on `/pools` detail, not `/swim`** — no free pool can appear in `/swim` results until
Gap 2 ships, since `/swim` only emits options for basins carrying rules.

## Gap 7 — three private operators: one urgent fix, two defensible skips

### altstetten — values right, method untrustworthy, completeness poor

The 3 stored rules *are* the real hours, but `_parse_html_table` takes the **first schedule-like
table**, and the page has two structurally identical footer tables: `Öffnungszeiten Hallenbad` and
`Öffnungszeiten Sauna`. We read **position, not the label** — a coin flip we happen to be winning,
which would flip **silently**, with no `ParseError`. Fix `_parse_html_table` to be **label-anchored**
regardless of anything else in this gap.

The canonical `/oeffnungszeiten/` page carries everything the footer drops: the **Revision closure**
(§0), ~11 holiday exceptions, prices, sauna/wellness/slide hours, 4 basin temps, rentals. Care:
the under-16 window is scoped to *Wellnessbad* and Damentag/Herrentag to *Sauna* — a whole-page grab
would invent an age restriction on the pool that does not exist.

The city's own altstetten page defers to the operator **and its closure disturber is a year stale**
(`active_to = 2025-08-17`). The operator is authoritative.

### dolder — not `no_source`; the site moved

`doldersports.com` now 302s to **`doldereisundbad.ch/wellenbad/`** — a rebuild with **zero
`<table>` elements**, which is why every table parser failed. Stripped, the body is 5.6 KB of dense
facts: season `19. Juni bis 13. September 2026`, hours, a **hard closure on Sa 5 Sep**, prices,
rentals, basins, live 23 °C (matching the city page exactly).

**The trap:** the page ships schema.org JSON-LD with `"openingHours": ["Monday,…,Sunday
09:00-17:00"]` — a **Yoast default on the `Organization` node** (the whole site, including the
winter ice rink) that **contradicts the page's own visible hours**. Structurally clean, factually
wrong. This is the strongest evidence that Gap 7's problem is judgment, not parsing.

### enge — revision 1 quoted the wrong hours

`tonttu.ch` is a 993-byte latin-1 meta-refresh stub (encoding is a non-issue: `scrape_schedule`
decodes `utf-8, "replace"`, and there is nothing to decode). The strings revision 1 cited
(`täglich von 8-24 Uhr`) come from the header's **Gastro** status popup — **extracting it as pool
hours would tell users they can swim in the lake until midnight.**

The real schedule is in the body: season `9. Mai – 20. September`, **three** stacked windows
(`9.–31. Mai: 9–19`, `1. Juni–30. Aug: 8–20`, `31. Aug–20. Sept: 8–19`), a `WomenOnly` Frauenseite,
and — verbatim Gap 2 in prose — *"Bei schlechtem Wetter reduzierte Öffnungszeiten. **Bei jeder
Witterung von 9 bis 11 Uhr geöffnet.**"* That is a **guaranteed core window nested inside a wider
conditional one**, which a boolean `weather_dependent` cannot express. Advisory *"für Kinder nicht
geeignet"* must **not** become an eligibility rule.

### Design and posture

**Dispatch on `pool_id`, not URL host** — the host is not stable (dolder changed domain *during
this investigation*; a host-keyed table would have silently fallen through to a confusing
`ParseError`). Do **not** extend `_PARSERS`: it is pool-blind and first-`Ok`-wins, and this gap
produced **three independent ways it returns a confident wrong answer** (sauna table, Gastro
widget, JSON-LD). One new cache source `operator_pages` at `SNAPSHOT`/12h, not one per operator.

**Keep failure fatal.** The atomic build already means a fatal operator failure = *build aborts,
prior gold unchanged, app serves yesterday's correct data, a human gets paged*. The alternative
writes `no_source` — a **false claim that no schedule source exists** — published green and
indistinguishable from a school pool that genuinely has none. robots.txt permits everything needed
on all three (`bad-altstetten.ch` sets `crawl-delay: 10`; `seebadenge.ch` disallows `/plan`).

**Owner decision (2026-08-02): skip nothing — extract as much as each operator publishes.** The
maintenance-ratio argument for dropping enge and dolder is overridden; all three operators get a
module, and the goal is maximum extraction, not minimum surface. UI is explicitly out of scope.

Full-extraction targets per pool: **altstetten** — Revision closure, ~11 dated holiday exceptions,
prices, sauna/wellness/slide feature hours, 4 basin nominal temps, rentals. **dolder** — season
window, daily hours, the 5 Sep closure, three dated hour overrides, prices, rentals (Sonnenschirm
CHF 5, Liegestuhl CHF 7), basins, features. **enge** — three stacked seasonal windows, the
`WomenOnly` Frauenseite, the guaranteed-core weather rule, prices incl. Abendeintritt, 44 m lane
dimensions, Sunday-evening sauna hours, rentals.

**Two consequences of going full-extraction**, both feeding back into Gap 2:

1. **Enge's weather rule must not degrade to a boolean.** *"Bei schlechtem Wetter reduzierte
   Öffnungszeiten. Bei jeder Witterung von 9 bis 11 Uhr geöffnet."* is a **guaranteed core window
   inside a wider conditional one**. Gap 2's recommended bolt-on *can* express it — 09:00–11:00 as
   unconditional plus the remainder as fair-weather — but only because weather sits on the rule, not
   on the day. This is a second, independent argument against the day-level `MaybeOpenDay` that both
   designers already rejected.
2. **Dolder needs a date-RANGE exception**, which does not exist. `31.07–16.08 → 10.00–19.30` is one
   override across 17 days; `ScheduleException` is single-date, so today it would mean 17 synthesised
   rows. Either add a range-scoped override, or reuse whatever primitive Gap 2 lands for season
   windows — they are plausibly the same shape. **Decide this alongside Gap 2, not after.**

Still true and unaffected: the altstetten Revision closure (§0) and the Tarifverbund price predicate
have **no** Gap-2 dependency and should ship first.

## Gap 8 — fields written by nothing: three deletions beat three fills

`etl/field_sourcing.py` classifies these as `DROP_CANDIDATE` ("no website producer today"). Re-derived
against live pages, the table is wrong in **both** directions:

| field | verdict | evidence |
|---|---|---|
| `last_admission_before` | **SOURCE FOUND** | *"Der letzte Einlass erfolgt bis 30 Minuten vor Badschluss"* — **32/32 pages, value 30, zero variance** |
| `lockers` | **SOURCE FOUND** | 25 pages (Gap 3) |
| `measured_temp_c` | **SOURCE FOUND** | but see Gap 4 — runtime, not gold |
| `public_holiday_policy` | **SOURCE FOUND, 4 pools** + must become nullable | `(und Feiertage)` on the Sunday row of blaesi/kaeferberg/leimbach/bungertwies → `SUNDAY_SCHEDULE` |
| `website` | **DELETE** | audit claims `SOURCED 7/7`; store says **0/57** — `_aspects()` never constructs it. Duplicate of `pool.url`, which the UI actually uses |
| `amenities` | **DELETE** | source exists but every item maps onto `features`/`Basin` physicals; `fidelity_report._derivable_amenities` already defines it as a projection of other fields |
| `accessibility` | **DELETE** | the city's `handicapInformation` `<ul>` is **empty on 26/26 pages** — it delegates to `ginto.guide`. Replace with a typed `accessibility_url` (~20 pools) |

**Revision 1's footnote hypothesis was wrong** — `¹` is the daylight/supervision caveat (Gap 2),
not last-admission. The real source is a sibling `<p>` one paragraph below.

**Nothing here renders today.** Grepping all of `apps/web/static/js/**` for
`lockers|amenities|accessibility|last_admission|website` returns **zero non-test hits** — a strong
independent argument for the three deletions, and a warning that any fill work must include a UI
change or it delivers nothing.

**`last_admission_before` is the one that prevents a wasted trip**: a pool closing at 20:00 stops
admitting at 19:30, and today the UI says "open until 20:00".

**Why the audit went stale, structurally:** `ProducerKind` has **no member for "a source exists, no
provider built yet"**, so everything in that position is mislabelled `DROP_CANDIDATE`. And
`test_every_entry_is_internally_consistent` checks a row is *well-formed*, never that it is *true* —
which is how the `website` row claimed `SOURCED 7/7` against an empty column indefinitely. Add
`SOURCEABLE_UNBUILT`, and a test that cross-checks each `SOURCED` row against real coverage in a
built store. Every `coverage` string is also still `"x/7"` — a 7-pool-era denominator against 57.

---

## Ranked plan

| # | work | pools | domain change? | blocked by |
|---|---|---|---|---|
| **0** | **altstetten Revision closure** (§0) | fixes 1 wrong answer | none | — |
| **0** | **`public_holiday_policy` → nullable** (§0) | removes a lie on 57 | small, compiler-enforced | — |
| 1 | label-anchor `_parse_html_table` | trust on 1 | none | — |
| 2 | Gap 8 deletions + `SOURCEABLE_UNBUILT` | −3 dead fields | deletions | — |
| 3 | Gap 4 honesty fixes (`is_open: bool \| None`, derive uids) | 5 pools stop reading "closed" | none | — |
| 4 | Gap 1 school pools (URL predicate + continuation rows + access vocab) | +5 | `SessionAccess` member | — |
| 5 | Gap 6 price discovery + age bands | +29 priced/free | none | — |
| 6 | Gap 3 rentals (data only, no UI) | +15 | `Rental`, `Deposit`/`Fee` unions | per-aspect gate, or Gap 2 |
| 7 | Gap 5 paddling | +12 | `FeatureKind` ×4, `Basin.heated` | seed.py xref; season from Gap 2 |
| 8 | **Gap 2 seasonal hours** | **+19** | **yes — the real decision** | — |
| 9 | Gap 7 enge + dolder, full extraction | +2 rich | range-scoped exception (see Gap 7) | Gap 2 |

Items 0–5 need **no** seasonal domain model and together move schedule/price coverage from ~12% to
roughly half the roster, while removing two active falsehoods. Gap 2 is the only genuine modelling
decision and it gates the summer half of the city.

**Owner decisions (2026-08-02).** UI work is out of scope everywhere in this plan — the acceptance
criterion for every gap is data landing correctly in the gold store and on the API. Gap 3 proceeds
data-only. Gap 7 skips nothing: all three operators get full extraction. Consequently the
**per-aspect fatal/non-fatal split** (Gap 3) and a **range-scoped exception primitive** (Gap 7,
dolder) are promoted from optional to required, and both should be settled while Gap 2's season
model is being decided rather than bolted on afterwards.

---

## Corrections to revision 1

1. **Gap 1 is 4 pools with URLs, not 5** (borrweg needs discovery), and `parse_schedule` **drops 45%
   of school rows**. The naive gate flip also **mislabels a girls-only session as public**.
2. **Gap 4 gains 0 pools of temperature.** The inline block *is* Baditicker rendered server-side
   (16/16 identical); school and paddling pages have no such block. Only `Hinweise` is new.
3. **Gap 6's host predicate is dead code** (the kind gate fires first), and "fixing" it would price
   6 free pools. School pools have a separate 5/5/2.50 tariff.
4. **The `¹` footnote is a daylight/supervision caveat**, not last-admission. `last_admission_before`
   is sourced from a different paragraph — 32/32 pages.
5. **Gap 7's encoding claim was a red herring** (the stub has no data), revision 1 **quoted enge's
   Gastro-popup hours as pool hours**, and dolder is extractable — its site moved to
   `doldereisundbad.ch`.
6. **Gap 3 is 15 pools / 101 rows**, and today's `LockerCategory` covers 27 of them.
7. `etl/fidelity_report.py:398-401`'s claim that the timetable "carries no term-vs-holiday variant"
   was derived from indoor pages only; the outdoor `Zeitraum` format falsifies it.

## Operational bugs found in passing

- **`freibad-zwischen-hoelzern` 404s** — the live slug is `freibad-zwischen-**den**-hoelzern`.
- **A `[^>]*` attribute regex silently drops `rows` on ~2/3 of these tables** (`<sup>` inside the
  attribute encodes as `&lt;sup>`, leaving the `>` unescaped). Use a quote-aware matcher.
- **`planschbecken.html` lists 12 entries, not 13** — Föhrenwald is absent.
- **`registry.yaml` `crowdmonitor_keys` are display names, not protocol uids** — all currently miss.
- **`baditicker.py:119` renders an empty open/closed field as `False`** — absent as closed.
