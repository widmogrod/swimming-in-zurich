---
type: plan
status: done
created: 2026-08-08
feature: mietobjekt-extraction
branch: plan/mietobjekt-extraction
worktree: .claude/worktrees/plan-mietobjekt-extraction
base_branch: feat/new-ui
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: ["S1"]
prerequisite: "scheduled after [[2026-08-08-admission-union-plan]] and [[2026-08-08-sharedsource-fanout-plan]] reach `status: done` — all three move `domain/models.py`, `build/compose.py`, `storage/codec.py`, `boundary/curated_dto.py`, `etl/scrape.py`; this plan rebases onto their landed state"
links: ["[[locker-option]]", "[[facility-field-sourcing]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# Mietobjekt extraction — the lockers machinery gets its producer, and the rentals get a seat

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-06**

> for me feature is to collect as much accurate data and facts from websites; and then in ETL process clean and load them to SQL database that is golden set. Key is that we can model in simple way every type of pool or port swiming object; any sezonal opening hours; info about availability; lanes; depth; temputre; geneder restrictions etc. We shoudn't compress information; we should think about it as extract; load; transform pipeline

**2026-08-08** (the standing instruction this plan executes: gap 3 was greenlit earlier as
"we just need collect data; UI can come later")

> write other plans

## Context

`LockerOption` is fully built surface with **zero producers**: a domain type whose docstring
already describes the real page rows ("gratis, plus Depot Fr. 5.–"), a DTO, a codec arm, a
compose slot, and a `/pools` projection — and 0/57 pools carry a row. The data sits in the same
pool pages the schedule scraper already fetches: a `Mietobjekt | Preis` table on **20** of the 26
declared sources' committed fixtures (6 have none: altstetten, maennerbad, and the 4
Schulschwimmanlagen), e.g. Hallenbad City's:

```
Garderobenkasten        gratis, plus Depot Fr. 5.–
Wertsachenfach          gratis, plus Depot Fr. 5.–
Badetuch                Fr. 3.–, plus Depot Fr. 20.–
Badebekleidung          Fr. 3.–, plus Depot Fr. 20.–
Schwimmbrille           Fr. 3.–, plus Depot Fr. 20.–
Wäschefach (1/2 Jahr)   Fr. 240.–
Wäschefach (1 Jahr)     Fr. 400.–
```

Half that table is not lockers. `LockerCategory` covers `WARDROBE | VALUABLES | LAUNDRY`; the
rest is **rentals** with no seat — and the corpus is far wider than City's three rows: across the
20 tables sit Saisonkabine (×10), Tageskabine (×9), Liegestuhl (×9), Sonnenschirm (×8), towels /
swimwear / goggles (×11), plus one-offs (Mööslihalle, Lounge, Pavillon) — roughly 70 non-locker
rows in all. Dropping any of them would be gap 3's compression all over again. Two facts, two
types, one shared parser. Zero new HTTP requests: the pages are already fetched by
`scrape_declared_sources`.

## Design (signature altitude)

### One table, two typed outputs

```
RentalKind = TOWEL | SWIMWEAR | GOGGLES | CABIN | SUNLOUNGER | PARASOL | OTHER
             # kinds earn membership by corpus frequency (Kabine x19, Liegestuhl x9,
             # Sonnenschirm x8); OTHER keeps raw — the UNMAPPED idiom

RentalItem:  kind: RentalKind, fee_chf: Decimal | None,
             deposit_chf: Decimal | None, period: str | None, raw: str
Facility.rentals: tuple[RentalItem, ...] = ()

parse_mietobjekte(page_html) -> Result[MietobjektTable, ProviderError]
MietobjektTable:  lockers: tuple[LockerOption, ...], rentals: tuple[RentalItem, ...]
```

Both types (`RentalItem`/`RentalKind` included) are defined in **S1** so the parser's return shape
never changes; S2 only wires rentals onward. The table is anchored by its own `Mietobjekt` column
header inside a `<stzh-datatable>` element, decoded with the machinery `price_scraper` already
owns (`_cells`/`_text`/`_money` — which handle the escaped-JSON attributes, endash cents, nbsp,
and the `<p>`-wrapped values Leimbach/Oerlikon carry). Row labels route by German noun:

- **`LockerOption`**: any `…kasten` label → `WARDROBE` (`Monatskasten`/`Saisonkasten` carry their
  prefix as `period` — a Kasten is a locker whatever its rental term); `Wertsachenfach` →
  `VALUABLES`; `Wäschefach` → `LAUNDRY`, `(1/2 Jahr)`-style suffixes as `period` verbatim,
  deliberately unparsed (the docstring's standing decision).
- **`RentalItem`**: `Badetuch` → TOWEL; `Badebekleidung`/`Badehosen` → SWIMWEAR; `Schwimmbrille` →
  GOGGLES; `…kabine` → CABIN (prefix as `period`); `Liegestuhl` → SUNLOUNGER; `Sonnenschirm` →
  PARASOL; anything else → `OTHER` with the label in `raw` — nothing is dropped.

**The cost grammar, specified against the real corpus, not three examples.** The 20 tables carry
prose cells a naive parser would crash on: `"gratis, eigenes Vorhängeschloss mitbringen"` (the
Garderobenkasten row at 13 outdoor pools), `"auf Anfrage"` (×6), `"Vermietung via
Restaurant/Kiosk"`, `"Fr. 2.–, plus Ausweis als Depot"` (a non-monetary deposit), and
triple-clause rows. The rule:

- a cell with **no `Fr.` token** → `fee=None, deposit=None`, the prose preserved in `raw` —
  absence of a stated price is data, not an error;
- a cell **with `Fr.` tokens** → first amount is `fee` (`"gratis, …"` prefix ⇒ `fee=None`), a
  `Depot Fr. N` clause is `deposit`; extra clauses ride in `raw`; `"Ausweis als Depot"` ⇒
  `deposit=None` (non-monetary, kept in `raw`);
- a `Fr.` token that yields **no parseable amount** → `Err(ParseError)`, fatal — that is garble,
  not prose.

### Wiring and failure

- `ScrapedAspects.lockers` **already exists** with a default (`build/compose.py:63`), compose
  already folds it (`compose.py:150`) — the missing link is that `etl/scrape._aspects`
  (`scrape.py:141-165`) never fills it. S1 fills it; only `rentals` is a genuinely new aspect
  field. **A page without the table is not a failure** — absence yields empty tuples (6 of 26
  declared fixtures have none). A cell that trips the grammar's `Err` arm aborts the build:
  fail-fast on garble, tolerant of absence and of prose.
- Blob: `lockers` already serializes; `rentals` is additive, popped when empty, so every current
  blob is byte-identical.
- `/pools/{id}`: the existing lockers projection starts carrying rows; `rentals` is an additive
  list on the detail.

### Invariants

- Every row of every parsed table lands somewhere — `OTHER` + `raw` is the no-drop guarantee.
- No new network: the parser runs on bytes `scrape_declared_sources` already fetched.
- Pools whose pages carry no table are untouched, byte-for-byte.

## Out of scope

- **UI rendering** of lockers or rentals — data first.
- **The Sauna surcharge / Abonnemente** rows on the tariff page — different page, different plan.
- **`mechanism`** (`LockerMechanism`) — the pages do not state it; stays `None`.
- **The 31 non-declared pools** — no page fetch to piggyback on until SharedSource-style coverage
  reaches them.

## Slices

### S1 — the lockers machinery produces rows end-to-end

- **Goal**: `Garderobenkasten`/`Wertsachenfach`/`Wäschefach` rows reach the store and `/pools`
  through the machinery that has waited for them.
- **Touches**: new `providers/mietobjekt.py` (`parse_mietobjekte`, full `MietobjektTable`
  including `RentalItem`), new `domain/rentals.py` (`RentalItem`, `RentalKind` — defined in S1,
  wired in S2), `etl/scrape.py:141-165` (`_aspects` fills the EXISTING `lockers` aspect field —
  `build/compose.py` needs no S1 edit), `etl/field_sourcing.py` (the `facility.lockers` row
  leaves `SOURCEABLE_UNBUILT`), `tests/providers/test_mietobjekt.py`, `tests/etl/test_scrape.py`,
  `apps/web/tests/test_gold_store.py`, `apps/web/tests/api/test_pools.py:172-174` (its
  `lockers == []` pin for hallenbad-city flips to the four real rows).
- **Acceptance**:
  - Against `hallenbad_city.html`: exactly 4 `LockerOption`s — wardrobe (fee `None`, deposit 5),
    valuables (fee `None`, deposit 5), laundry ×2 (fees 240 and 400, periods `"1/2 Jahr"` and
    `"1 Jahr"`).
  - A fixture with no `Mietobjekt` table yields `()` and no error; a copy of the city fixture
    with a price cell garbled to `"Fr. ab"` yields `Err(ParseError)`; the prose cells parse per
    the grammar — `"gratis, eigenes Vorhängeschloss mitbringen"` → fee/deposit `None` + raw
    (pinned on a real outdoor fixture), `"auf Anfrage"` likewise, `"Fr. 2.–, plus Ausweis als
    Depot"` → fee 2, deposit `None`.
  - After a rebuild: pools with non-empty `lockers` == **20** — the expected id set derived by a
    plain noun scan (`…kasten`/`Wertsachenfach`/`Wäschefach`) over the DECLARED fixtures only,
    independent of the parser, so the criterion cannot collapse into comparing the parser with
    itself. (Includes `strandbad_mythenquai`, whose table opens with `Wertsachenfach` and has no
    Garderobenkasten row — the case a `Garderobenkasten`-only grep misses.)
  - Blob byte-stability for a pool without the table.
- **Depends on**: — within this plan. Cross-plan: see the frontmatter `prerequisite` — three
  plans move the same five files, and this one runs last and rebases onto their landed state.

### S2 — the rentals stop being dropped

- **Goal**: towel/swimwear/goggles rows land as `RentalItem`s; unknown labels land as `OTHER`.
- **Touches**: `domain/models.py` (`Facility.rentals`), new `domain/rentals.py` (`RentalItem`,
  `RentalKind`), `providers/mietobjekt.py` (rentals side), `boundary/curated_dto.py` +
  `storage/codec.py` (additive `rentals`, popped when empty), `build/compose.py`,
  `apps/web/api/pools` (additive detail list), `etl/field_sourcing.py` (a new `facility.rentals`
  row), mirrored tests.
- **Acceptance**:
  - Against `hallenbad_city.html`: 3 `RentalItem`s, each fee 3 / deposit 20, kinds
    TOWEL / SWIMWEAR / GOGGLES.
  - A synthetic row `"Luftmatratze | Fr. 5.–"` parses to `RentalItem(OTHER, fee=5, raw=…)` —
    the no-drop guarantee, pinned.
  - `'"rentals"' not in codec.dumps(f)` for a facility with none — a recorded deviation from the
    facility-level emit-unconditionally comment (`codec.py:96-100`), taken because emitting
    `"rentals": []` would rewrite all 57 blobs for a field most never carry; the `min_age`
    field-serializer precedent applies and the codec comment gets updated. Round-trip losslessly
    for a facility with rows.
  - After a rebuild: pools with non-empty `rentals` == **20** — every declared table has at least
    one non-locker row once OTHER routing is honest (the "10" of the draft counted only the
    towel noun). Kind-level pins: TOWEL/SWIMWEAR/GOGGLES on the **11** fixtures carrying those
    nouns; CABIN on ≥10; the expected sets derived by the same parser-independent noun scan.
  - `GET /pools/{id}` for `hallenbad-city` lists all 7 Mietobjekt rows across the two fields.
- **Depends on**: S1.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-09 | S1 | done | `tests/etl/test_field_sourcing.py` edited outside Touches (its SOURCEABLE_UNBUILT pin broke by the required row flip — updated to guard SOURCED); the "auf Anfrage"/"Ausweis als Depot" grammar pins land on RentalItems not LockerOptions (the corpus puts those cells on rental-labeled rows); post-approve critic fixes: a Mietobjekt-anchored table whose `columns=`/`rows=` attribute fails JSON decode is now `Err(ParseError)` not silent absence (the plan's own fatal-on-malformed posture applied to the decode door); the noun-scan regex and pool-id→fixture mapping hoisted to shared `tests/declared_fixtures.py` (kills the cross-test-module imports) | `providers/mietobjekt.py` imports `price_scraper`'s private table helpers (recorded reuse decision; promote to a shared module when a third consumer appears); `fee_chf=None` carries two meanings (stated-gratis vs unstated) — S2 MUST resolve per the Decisions directive before rentals hit the wire | yes |
| 2026-08-09 | S2 | done | `RentalItem.fee` is a closed union `Priced \| Gratis \| Unstated` instead of the Design's `fee_chf: Decimal \| None` — the Decisions directive's resolution (bool flag rejected: invalid states representable; gratis→0 rejected: fabricates an amount); serialized as `fee_chf` + popped `fee_state`. Out-of-Touches edits, all disclosed: `domain/query.py` (no other path to the detail), `boundary/mapping.py`, `etl/scrape.py`, `tests/declared_fixtures.py`. Kind-level acceptance pins live at parser level, not post-rebuild as phrased (equivalent modulo wiring other tests cover). Critic round 1 blocked on the UNPINNED Unstated wire arm (mutation to "gratis" stayed green — the directive's conflation at the served surface); fixed with the paired wire assertion, mutation now fails, round 2 approve. Incident: a mutation-revert via git checkout clobbered uncommitted service.py edits; re-applied and verified byte-exact against the pre-incident reviewed blob (hash 5fc34ff) | LockerOption keeps two-state `fee_chf` (corpus-honest; guarded by a loud test if an auf-Anfrage locker ever appears — unify onto the fee union then); `deposit_chf` still compresses Ausweis-deposit vs no-deposit into one None (raw carries it); declined-by-direction: a RentalItemDTO validator making a corrupt fee_chf+fee_state pair loud (peer-conformant with `_admission_from_stored`'s prices-first precedent; cross-cutting — would touch admission too) | yes |

## Accepted drift

_(appended by hand from /dev:present findings the user has blessed; no command writes here)_

## Decisions & divergences

**2026-08-08 — pre-approval review (5 blocking, all accepted).** (1) Every count was wrong — the
draft grepped ALL fixtures instead of the 26 declared ones and by single nouns instead of row
sets: 21→**20** tables (unterer-letten is not declared), 19→**20** locker-carrying (mythenquai's
table opens with `Wertsachenfach`, no Garderobenkasten), 10→11 rental-noun fixtures (seebach
lists `Badebekleidung` without `Badetuch`); the acceptance sets are now derived
parser-independently over declared sources only. (2) The rentals-count criterion contradicted the
plan's own no-drop routing — with OTHER rows honest, **20** pools carry rentals, not 10. (3) The
three-example cost grammar would have aborted the build on ~25 real prose cells
(`"gratis, eigenes Vorhängeschloss mitbringen"` ×13, `"auf Anfrage"` ×6, non-monetary deposits);
the grammar is now specified against the enumerated corpus with a prose-vs-garble boundary.
(4) `ScrapedAspects.lockers` already exists and compose already folds it — the Touches now point
at the real gap (`etl/scrape._aspects`) and include the `test_pools.py` pin the slice flips.
(5) `pause_after` was empty with no rationale; S1 now pauses (owner-visible routing + grammar
decisions for 20 pools). Suggestions taken: reuse of `price_scraper`'s table machinery named;
`RentalKind` widened to the corpus's frequent kinds (CABIN/SUNLOUNGER/PARASOL) with
`Monatskasten`/`Saisonkasten` routed to lockers and `Badehosen` to swimwear; the codec
pop-vs-emit deviation recorded; the cross-plan file-collision ordering moved into checkable
frontmatter; the S1/S2 type split stated (types in S1, wiring in S2).

### 2026-08-09 — S1 review directive for S2: the two meanings of `fee_chf=None`

The S1 critic surfaced a semantics collision S2 MUST resolve before putting
rentals on the wire: `domain/lockers.py` reads `fee_chf=None` as "free to
use" while `domain/rentals.py:39` reads it as "the page states no fee", and
the parser maps BOTH stated-gratis cells (Liegestuhl ×8, Sonnenschirm ×4,
Spielmaterial) and genuinely-unstated cells (`auf Anfrage`) to the same
`None`. Serving `fee_chf: null` with two meanings is the admission-union
compression all over again at rental scale. S2 resolves it — either a
distinct stated-free representation on `RentalItem` or reconciled docstring
semantics with the distinction carried another way — and pins the
Liegestuhl (stated gratis) vs Mehrzweckraum (`auf Anfrage`) pair as the
proof. Also for S2's awareness: periods ride as verbatim label prefixes
("Monats"/"Saison"/"Tages", Fugen-s included).

## Summary

Done 2026-08-09, two slices, critic approve r1 (S1) and revise→approve
(S2 — the unpinned Unstated wire arm, proven by mutation).

What exists now: `parse_mietobjekte` reads the Mietobjekt-anchored
`stzh-datatable` on the 20 declared pages that carry one, routing by
German noun — Garderobenkasten/Wertsachenfach/Wäschefach →
`LockerOption` (periods verbatim-unparsed), everything else →
`RentalItem`, unknown labels → `OTHER` with `raw` (the no-drop
guarantee). Cost cells decompose on the fee/deposit axes over the
critic-verified 48-cell corpus grammar; absence of the table is
Ok-empty, a malformed cell or undecodable anchored table is a fatal
`ParseError`. `RentalItem.fee` is the closed union
`Priced | Gratis | Unstated` — a stated gratis and an unstated fee are
different facts, pinned at parser, codec, and wire; `LockerOption`
keeps its corpus-honest two-state `fee_chf` behind a loud guard test.
After rebuild both carrying sets equal the fixture-derived 20
(parser-independent noun scans, one shared owner
`tests/declared_fixtures.py`); `/pools/hallenbad-city` serves all 7
rows across the two fields; blobs pop `rentals` when empty and pre-S2
blobs load `()`.

Final: make qa green — 883 passed, coverage 96.06% ≥ 95, mypy strict,
CRAP clean. Open debt: the locker fee two-state (guarded),
deposit-semantics compression (raw carries it), the private
price_scraper helper imports, and the declined DTO contradiction
validator — all in the ledger.
