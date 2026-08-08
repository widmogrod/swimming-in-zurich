---
type: plan
status: in-progress
created: 2026-08-08
feature: admission-union
branch: plan/admission-union
worktree: .claude/worktrees/plan-admission-union
base_branch: feat/new-ui
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: []
links: ["[[admission]]", "[[city-tariff]]", "[[2026-08-07-city-tariff-fanout-plan]]", "[[facility-field-sourcing]]"]
---

# Admission union — free is a fact the city publishes, not a missing price

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-06**

> for me feature is to collect as much accurate data and facts from websites; and then in ETL process clean and load them to SQL database that is golden set. Key is that we can model in simple way every type of pool or port swiming object; any sezonal opening hours; info about availability; lanes; depth; temputre; geneder restrictions etc. We shoudn't compress information; we should think about it as extract; load; transform pipeline

**2026-08-08**

> 1 ok; 2 - rerun and re-discover; if they're stale we should not allow stale data in, or serve old data to users; 3 = go with sharedsources as suggested;

## Context

Four pools publish *"Der Eintritt … ist gratis"* on their own pages (`flussbad-au-hoengg`,
`flussbad-oberer-letten`, `seebad-katzensee`) or *"wird privat betrieben … ein Gratisbad"*
(`maennerbad-schanzengraben`), and the store records all four as `prices=None` — the **same value
carried by the 32 pools nobody has priced**. Free and unknown are different facts compressed into
one null; the only place the free fact survives today is a build stderr note. That is exactly the
compression the intent forbids, and it is a prerequisite for the SharedSource plan: the
Planschbecken page's headline fact is *"Die Nutzung der Planschbecken ist kostenlos"*, and without
the union that fact would be discarded again, 13 more times.

The same missing distinction hides a failure: a failed `scrape_prices` degrades silently to
`tariffs=None` (`cli.py:294-295`), unpricing all 21 tariffed pools while the build exits 0 — the
skip-and-continue-green pattern the project bans. Builds on [[city-tariff]] (the link
discriminator) and [[2026-08-07-city-tariff-fanout-plan]] (whose S2 ledger recorded both debts).

## Design (signature altitude)

### The domain union

```
Admission = Free | Tariff(table: PriceTable) | Unknown          # closed, matched exhaustively

Facility.admission: Admission = Unknown()                        # REPLACES prices: PriceTable | None
```

`Facility.prices` is deleted. Consumers `match` the union and end with `assert_never`:
`query.py:386` resolves a price only in the `Tariff` arm; `apps/web/api/pools` projects both the
table (Tariff) and the kind.

### The page states free-ness; a provider reads it

```
states_free_admission(page_html) -> bool
    # the TIGHT sentence only: r"Der Eintritt[^.<]{0,80}ist\s+gratis" or "Gratisbad"
    # NOT bare "gratis": the Ausstattung/locker rows print it on 21 of the 26 declared pages
    # ("Garderobenkasten ... gratis", "gratis, plus Depot Fr. 5.-")

admission_for(source: DeclaredSource, page_html, tariffs: CityTariffs) -> Admission
    # states_city_tariff  -> Tariff(school | general by kind)     [precedence: checked first]
    # states_free_admission -> Free
    # neither             -> Unknown  (+ the existing build note)
```

Measured against all 26 declared sources' committed fixtures: the tight pattern matches **exactly
the 4 free pools** and none of the other 22 (`hallenbad-altstetten` matches neither arm →
`Unknown`, correct for a private operator whose tariff we do not know). If a page ever matched
both, the tariff link wins and a note names the contradiction — a stated tariff with a stray
gratis sentence is a page bug to surface, not a build failure.

### Serialization — additive and invisible, old blobs stay loadable

Every blob today carries a `prices` key (`null` or a table; **not** popped — `codec.py:98` states
this). The union rides the existing key plus one new optional discriminant:

```
Tariff(t)  ->  prices: <table>                      (byte-identical to today)
Unknown    ->  prices: null                         (byte-identical to today)
Free       ->  prices: null, admission_state: "free"   (the only new bytes)
```

Decoding: a table → `Tariff`; `admission_state == "free"` → `Free`; else `Unknown`. A pre-union
blob therefore loads as `Unknown` for unpriced pools — the honest reading of a blob that predates
the distinction — which is what keeps the re-layer commands (`scrape-gold`/`scrape-lanes`, which
load existing blobs) working across the change. `admission_state` is popped when absent, per the
`min_age` precedent.

### A failed tariff scrape becomes fatal

```
_compose_schedules: scrape_prices -> Err  =>  abort the phase (fatal), naming the typed cause
```

**S1 interim bridge**: S1 keeps `scrape_declared_sources(..., tariffs: CityTariffs | None = None)`
— `None` maps every declared source to `Unknown` with no note — so the cli degradation path stays
type-valid until S2 deletes it. Only `admission_for` itself takes `CityTariffs` non-optional from
the start. An implementer who tightens the outer signature in S1 pre-satisfies S2's criterion and
breaks ten S1-era test call sites; do not.

Losing the whole tariff page is not "26 pools are Unknown" — it is a provider failure, and under
fail-fast a declared-source failure aborts the build. The per-pool `Unknown` remains the honest
value for a pool whose *page* states nothing; only the *scrape* failing wholesale is fatal.

### Invariants

- `Free` is asserted only from the pool's own page sentence — never inferred from a missing
  tariff link, a hostname, or a kind.
- A `Tariff` pool's blob bytes are unchanged by this plan; an `Unknown` pool's too. Only the 4
  `Free` pools' blobs gain a key.
- `/swim` behaviour for `Tariff` and `Unknown` pools is byte-identical to today. A `Free` pool's
  option still carries `price: null` (rendering free-ness is UI, deferred); the *data* is no
  longer lost.

## Out of scope

- **UI rendering of free admission.** Data first, per the standing decision; `/pools` exposes the
  kind, the web UI is untouched.
- **The Planschbecken / SharedSource fan-out** — its own plan; this one lays the `Free` type it
  needs.
- **The "total link outage builds green" alarm.** With the union, that state becomes 26 `Unknown`
  notes; making note-volume fatal is a policy knob deferred with it.
- **`Provenance.curated`** and the rest of the vestigial-field debt.
- **`flussbad-unterer-letten`'s free fact.** Its page states *"Es ist ein Gratisbad"*, but two
  roster entries share its URL so it is not a declared source — its free-ness stays compressed
  into the 32 Unknown. A known coverage gap owned by the SharedSource plan, not a miss here.

## Slices

### S1 — the four free pools stop reading as unknown

- **Goal**: `Free`, `Tariff`, `Unknown` are distinct in the domain, the store, and `/pools`.
- **Touches**: `domain/models.py` (delete `prices`, add `admission`), new `domain/admission.py`
  (the union), `domain/query.py:386` (match), `providers/price_scraper.py`
  (`states_free_admission`), `etl/scrape.py` (`tariff_for` → `admission_for`, note text),
  `build/compose.py:147`, `providers/curated.py:102`, `boundary/curated_dto.py` +
  `storage/codec.py` (the `admission_state` discriminant, popped when absent),
  `etl/field_sourcing.py` + `etl/fidelity_report.py:390` (the audit rows),
  `apps/web/api/pools` (model/service/router: `admission: "free" | "tariff" | "unknown"`),
  mirrored tests.
- **Acceptance**:
  - `states_free_admission` over the 26 declared fixtures: True for exactly
    `flussbad-au-hoengg`, `flussbad-oberer-letten`, `seebad-katzensee`,
    `maennerbad-schanzengraben`; False for the other 22 — pinned offline, and a test names the
    locker-row `gratis` trap: `hallenbad_city.html` carries bare `gratis` in its Ausstattung
    rows ("Garderobenkasten … gratis") and must stay False.
  - After a rebuild: **21 Tariff / 4 Free / 32 Unknown**, by literal SQL over `facility_doc`
    (`admission_state` present on exactly 4 rows; `prices` non-null on exactly 21).
  - Byte-stability: a `Tariff` facility and an `Unknown` facility serialize to the same bytes as
    before the union (`'"admission_state"' not in codec.dumps(f)`); a pre-union blob with
    `prices: null` loads as `Unknown`.
  - `GET /pools/{id}` shows `admission: "free"` for `seebad-katzensee`, `"tariff"` for
    `hallenbad-city`, `"unknown"` for `hallenbad-altstetten`.
  - `GET /swim` responses for a `Tariff` and an `Unknown` pool are unchanged from before the
    slice (regression-pinned on the committed fixtures).
  - `"prices" not in {f.name for f in dataclasses.fields(Facility)}` — the compressed field
    cannot return. (Not `hasattr`: a re-added field without a default creates no class
    attribute, so `hasattr` would pass while the field returned.)
- **Depends on**: —

### S2 — a lost tariff page fails the build instead of unpricing it

- **Goal**: `scrape_prices -> Err` aborts the build with the typed cause; no run exits 0 with the
  tariff silently missing.
- **Touches**: `cli.py:294-295` (`_compose_schedules`), `etl/scrape.py:222-228` (the
  `tariffs: CityTariffs | None = None` parameter becomes `CityTariffs`), `tests/etl/test_scrape.py`
  (10 call sites: 9 omit `tariffs`, one passes `tariffs=None` — and the None-branch
  note-suppression test's subject ceases to exist and is deleted with the branch),
  `tests/test_cli.py`.
- **Acceptance**:
  - A build whose price client returns HTTP 500 exits non-zero and names the `ProviderError`;
    the prior gold store is content-unchanged (the atomic-swap guarantee, asserted).
  - A build whose price client succeeds but where one pool states neither tariff nor gratis
    still exits 0 with that pool `Unknown` and noted — per-pool unknowns are not failures.
  - `scrape_declared_sources` no longer accepts `tariffs: CityTariffs | None` — the parameter is
    `CityTariffs`, so the "scrape failed but we continued" state is unrepresentable at the call
    site.
- **Depends on**: S1

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-08 | S1 | done | none — implementation notes: the Tariff-arm price match lives in module-level `_price_of` (match + `assert_never` preserved) because inlining pushed `find_swim_options` to CRAP 30.1 > 30; the `Gratisbad` regex arm was anchored to a predication (`ist\s+(?:es\s+)?ein\s+Gratisbad`) after a critic claim-audit finding — the bare token would have asserted Free from a page merely mentioning another facility's Gratisbad; Männerbad's fixture bytes match the anchored form exactly | none — the `tariffs: CityTariffs \| None = None` bridge and its None-branch test are plan-mandated S1 state that S2 deletes | yes |
| 2026-08-08 | S2 | done | plan's affected-call-site count was stale (said 10 in tests/etl/test_scrape.py; actual 14 sites, 9 affected — 8 omit + 1 `tariffs=None`, 5 already passed `_TARIFFS`); CLI-test doubles beyond the enumerated changes (in-Touches file) had to serve the committed price fixture at the tariff URL — they served pool HTML everywhere, which S1 silently degraded and S2 correctly makes fatal; consolidated into `_with_price_fixture` per critic round 2, which also dropped the now-invariant " (with tariffs)" stdout suffix | none | yes |

## Accepted drift

_(appended by hand from /dev:present findings the user has blessed; no command writes here)_

## Decisions & divergences

**2026-08-08 — pre-approval review (2 blocking, both accepted).** The claimed bare-`gratis` trap
was wrong: `Kombi6 (1 x gratis)` appears on **0** of the 26 declared fixtures (it lives on the
tariff page, which `states_free_admission` never sees); the real exposure is the Ausstattung/locker
rows (`"Garderobenkasten … gratis"`) on **21** of 26 — the criterion now pins `hallenbad_city.html`
False. And S2's signature-tightening touched a file and ten test call sites its Touches omitted;
both are named now, plus the S1 interim bridge that keeps the outer signature optional until S2.
Suggestions taken: `cli.py` line refs corrected post-merge (294-295), the `hasattr` guard replaced
with `dataclasses.fields` (a defaultless re-add would slip past `hasattr`), unterer-letten's
compressed free fact recorded as a known gap. `pause_after: []` is deliberate: the plan is two
small slices, review runs at `max_rounds: 2`, and completion always pauses before merge-back.

### 2026-08-08 — S1 (critic: approve, round 1; claim-audit step live)

First slice reviewed under the critic's new claim-audit step. The step
self-gated correctly (diff transforms scraped-page facts), verified the
slice as a REPAIR of the free/unknown absence-as-claim (every absence door
traced to `Unknown`), and produced one true shape-1 finding at the correct
minor severity: the unanchored `Gratisbad` token (fixed pre-commit, see
ledger). Declined suggestion: deduplicating the `states_free_admission`
re-scan on Tariff pages — conformant to the plan's note-with-caller design
and S2 reworks that loop anyway. Discoveries: the build's "states no city
tariff" stderr note count drops 5 → 1 (the 4 free pools no longer emit it —
an implied consequence no criterion named); the /swim Unknown pin uses a
September instant because altstetten's operator Revision closure (Jul 30 –
Aug 16) covers the suite's AUGUST_MORNING constant. Starting state: the
worktree carried uncommitted partial S1 edits from a prior interrupted
session; the implementer verified each against the plan, finished the two
files broken mid-edit, and wrote the (absent) test mirror from scratch.

### 2026-08-08 — S2 (critic: approve, round 1; two mechanical suggestions taken)

The critic's claim-audit step self-gated again and returned an EMPTY findings
list, explicitly invoking the empty-list-is-valid outcome — it verified the
slice as the shape-1 repair it is (the failed-scrape absence door now refuses
loudly at the boundary; per-pool Unknown keeps its explicit seat + note).
Suggestions taken: the " (with tariffs)" stdout suffix dropped (its
discriminator died with the degrade branch — an invariant claim implying a
counterfactual mode) and the duplicated price-fixture routing consolidated
into `_with_price_fixture`. Discovery worth keeping: the fatality also binds
`scrape-gold` (same `_compose_schedules`), so the re-layer can no longer exit
0 unpriced — intended in spirit, unnamed by any criterion.

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/admission-union.md` (what EXISTS now, not what was intended).
