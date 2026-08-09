---
type: plan
status: in-progress
created: 2026-08-09
feature: claim-audit-repairs
branch: plan/claim-audit-repairs
worktree: .claude/worktrees/plan-claim-audit-repairs
base_branch: feat/new-ui
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: ["S2"]
links: ["[[lane-plan-url-binding]]", "[[2026-07-21-lane-plan-reconciliation-plan]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# Claim-audit repairs — lane plans and the catalog stop serving claims their sources never made

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-09**

> irone out remining know issues before merging

## Context

Four defects with committed-fixture evidence, found by the claim-audit backtest
(agentic-engineering `evals/claim-audit/runs/2026-08-08-shipped.md`, auditors
blind, mechanisms execution-verified by two independent critics) and untouched
by the three plans that just landed. All four share one shape: **the code
serves a claim the source never made.** All four sites verified live at
`feat/new-ui` HEAD (18a6b88):

1. **Every Blaesi and Kaeferberg lane session is served 30 minutes early.**
   `belegungsplan.py:503` pairs time labels to cell rows BY RANK
   (`slots = labels[: len(rows)]`; `_nearest(w.top, rows)` at `:439`), never
   by y-geometry. A gutter label whose slot the source leaves blank produces
   no cell cluster, so every later row inherits the previous label. Measured:
   Blaesi's 07:30–08:00 label at y=130.9 has zero grid cells → rows 3–31
   shift (Sunday PublicSwim served 08:30–17:30; the PDF publishes
   09:00–18:00); Kaeferberg's 06:00–06:30 label at y=156.0 is empty and the
   first cells sit at y=180.3 under the 06:30 label at y=173.1 → the whole
   week shifts. The well-aligned sheets (City: offset −5.3 at pitch 12.60;
   corpus offsets span 0.411–0.434×pitch, critic-measured across all 7
   fixtures) are correct today and must stay byte-identical.
2. **Phantom reservations minted from a footer digit.** `_cell_words`
   (`:397–403`) admits any digit below `bahnen_top + bahnen_gap` with NO
   bottom boundary. The standalone digit in the footer sentence "Den
   Badegästen stehen … mindestens N Bahnen zur Verfügung." becomes a phantom
   bottom row and takes the next unused label: Leimbach's '2' (x=298,
   y=542.4) serves "lane 4 SchoolReserved Wednesday 22:00–22:30"
   (cells_total inflated to 1155 = 33×7×5); Oerlikon's '4' (x=563, y=780.3)
   serves "lane 8 reserved Thursday 23:00–23:30". The sentence those digits
   come from actually promises lanes stay PUBLIC.
3. **A swim club served as school-reserved.** `_code_to_access` (`:361`)
   classifies any legend name containing the SUBSTRING "schul" as
   SchoolReserved. Oerlikon's legend lists `2 Schulen` and the club
   `4 Schwimmschule Limmatsharks` as distinct owners; "schwimm**schul**e"
   hits the school branch first, so the club's sessions are served as school
   time. Same defect family as the fixed sauna-table and Gratisbad
   substring traps ("bare 'bad' is deliberately not a pool keyword").
4. **"NULL" served as a description for 50 of 57 pools.** The WFS source
   uses the literal token `NULL` as its null sentinel; `geo_sport.py`'s
   cleaning (`:79`, `:147`) passes it through as the STRING "NULL", and the
   committed `data/catalog.json` carries `"description": "NULL"` on 50
   entries — absence served as a definite (and absurd) value.

## Design (signature altitude)

### S1 — the grid ends where its labels end (MUST land before the pairing fix)

```
_cell_words(...)  gains a bottom boundary: last label y + pitch × tolerance
    # a digit below the label span is page prose (the footer promise), not a
    # cell; excluded, never an error — the footer is real content, not garble
```

Ordering is load-bearing, not belt-and-braces (critic-measured): the Leimbach
footer row sits 2.11×pitch and the Oerlikon footer row 3.65×pitch from any
label, so S2's strict pairing would return `SchemaMismatch` on both committed
sheets if the phantoms still existed. The boundary removes them first
(Leimbach 33→32 rows, cells_total 1155→1120; Oerlikon 35→34 rows — verified:
all remaining rows are rank==nearest aligned), and
`PlanCoverage.cells_total` returns to the sheet's true grid size.

### S2 — labels pair to rows by geometry, not rank

```
_pair_rows_to_labels(rows: Sequence[float], labels: Sequence[TimeLabel], spec)
    -> Result[tuple[TimeRange, ...], SchemaMismatch]
    # each cell-row cluster claims the label whose y is nearest within
    # spec-derived tolerance (corpus offsets measured 0.411–0.434×pitch —
    # the tolerance must admit ≥0.434; next label is ≥0.57×pitch away, so
    # nearest is unambiguous); a LABEL with no cells is legal (a blank
    # half-hour — the exact case rank pairing corrupts); a cell ROW with no
    # label within tolerance is SchemaMismatch (a row of reservations at a
    # time the sheet doesn't name is garble, not data — reachable only for
    # in-grid garble once S1's boundary excludes footer prose)
```

`_segment_grid` and `_parse_sectioned_basin` (the second rank-pairing site,
`:838` `used_slots = slots[: len(rows)]`) both route through it;
`_uniform_grid`/`_ragged_grid` index the aligned slots unchanged. Correct
sheets — where every row's nearest label is the rank-assigned one anyway —
parse to byte-identical plans; only sheets with blank slots move.

### S3 — the Schwimmschule is not a school: a targeted exclusion

```
_code_to_access:  a legend name whose "schul" hit comes ONLY from the word
    Schwimmschule is a CLUB and keeps its full name; every other "schul"
    carrier keeps today's SCHOOL routing — the committed legends are full of
    genuine compound-named schools (Kantonsschule, Tagesschule, Rafaelschule,
    Privatschule, Gesamtschule, Schulsportkurs) that a word-boundary rule
    would wrongly flip. The precedent is the targeted "bare 'bad' is not a
    pool keyword" negative, not a general re-classification.
```

### S4 — the WFS null sentinel parses to absence

```
geo_sport:  a property whose cleaned value is the literal token "NULL"
    (case-sensitive, the source's sentinel) -> None at the WFS boundary —
    one rule for description, address parts, and every other cleaned field;
    an all-None address renders as absent, not "".
GeoPool.description: str | None      # and the catalog snapshot re-taken:
                                     # 50 entries' description becomes absent
```

`data/catalog.json` is re-snapshotted through the recorded transport (the
roster-url-scheme S2 precedent: the golden provider-vs-committed test must
compare equal), and no serialized store value anywhere is the string "NULL".

### Invariants

- A fix may only DELETE wrong claims or RESTORE source-true ones — no fix
  invents data. The fidelity/golden diffs are exactly the named corrections.
- Sheets and pools not named in the evidence are byte-identical before/after
  each slice (the S2 well-aligned-sheets criterion, the S4 7-non-NULL pools).
- Fail-fast posture unchanged: garble aborts, absence is honest, prose is
  data.

## Out of scope

- **The scrape-gold curated-feedback suspicion** (`_merge_basins` fed
  composed output) — needs a targeted investigation first, and compose has
  been reworked by three plans since the observation; a plan of its own if
  it survives re-verification.
- **`SeniorsOnly`/`AdultsOnly.min_age` defaults** — repairing them needs a
  sourced fact (the city's actual thresholds), not a parser change.
- **Deposit semantics / the DTO contradiction validator** — recorded in the
  mietobjekt ledger for a future slice.
- **UI changes** — the corrected times/owners/descriptions flow through the
  existing surfaces.

## Slices

### S1 — the footer digit stops being a session

- **Goal**: no cell exists below the sheet's label span; the phantom
  reservations die and coverage counts return to the true grid.
- **Touches**: `providers/belegungsplan.py` (`_cell_words` bottom boundary),
  `tests/providers/test_belegungsplan.py` (incl. the two digest pins
  `_LEIMBACH_GOLDEN_DIGEST` at `:154` and `_OERLIKON_SCHWIMMER_DIGEST` at
  `:263-265`, which pin the phantoms today and MUST change).
- **Acceptance**:
  - Leimbach: no Wednesday 22:00–22:30 session; row count 32 (not 33);
    `cells_total == 32×7×5 == 1120`; no reservation's `TimeRange` lies
    beyond the last cell-backed label.
  - Oerlikon Schwimmerbecken: no Thursday 23:00–23:30 session on lane 8;
    row count 34 (not 35).
  - Both sheets' remaining reservations equal today's minus exactly the
    phantoms; every other committed fixture parses byte-identically.
  - The two golden digests are re-pinned with the phantom-free values and a
    comment naming what changed.
- **Depends on**: —

### S2 — lane sessions stop shifting: geometry pairing

- **Goal**: Blaesi and Kaeferberg lane sessions are served at the times
  their PDFs publish; every well-aligned sheet is untouched.
- **Touches**: `providers/belegungsplan.py` (`_pair_rows_to_labels`, both
  pairing sites `:503` and `:838`), `tests/providers/test_belegungsplan.py`.
  Resolved fact (critic): NO committed golden pins the shifted times — the
  Blaesi/Kaeferberg tests assert shape only (`:184-193`, `:217-226`), so the
  corrections land as new value pins, not golden diffs.
- **Acceptance**:
  - Blaesi: Sunday PublicSwim window parses 09:00–18:00 (was 08:30–17:30);
    the Monday school block 08:00–12:00 (was 07:30–11:30); the 07:30–08:00
    label yields NO sessions (the blank half-hour is honest).
  - Kaeferberg: the week's first sessions start 06:30 (was 06:00); no
    session earlier than the earliest cell-backed label.
  - Byte-identity: every other committed lane-plan fixture (City pinned
    explicitly, both sectioned Oerlikon basins at their 0.434×pitch offset)
    parses to a plan equal to its S1 state.
  - A synthetic sheet with an in-grid cell row nowhere near any label →
    `Err(SchemaMismatch)` naming the row.
- **Depends on**: S1 (without the boundary, strict pairing SchemaMismatches
  the two footer-carrying committed sheets — measured 2.11×/3.65×pitch).

### S3 — the Schwimmschule is a club; the real schools stay schools

- **Goal**: only the one wrong owner moves; every genuine compound-named
  school keeps its SCHOOL routing.
- **Touches**: `providers/belegungsplan.py` (`_code_to_access`),
  `tests/providers/test_belegungsplan.py`,
  `apps/web/tests/fixtures/pool_oerlikon.json` (the detail-preview fixture
  embeds the phantom AND the "Schools" owner for the affected codes — it is
  fixture-backed, so corrections do NOT flow automatically; regenerate or
  hand-correct it here together with the S1 phantom, one fixture touch).
- **Acceptance**:
  - Oerlikon: code-4 sessions serve `ClubReserved("Schwimmschule
    Limmatsharks")`; code-2 (`Schulen`) still `SchoolReserved`.
  - The genuine compound schools are pinned BY NAME as still
    SchoolReserved: Kantonsschule Zürich Nord, Tagesschule Blüemlisalp,
    Freie Oberstufenschule Zürich, Gesamtschule Unterstrass, Rafaelschule,
    Privatschule Toblerstrasse (schwimmerbecken), Privatschule firstclass,
    Schulsportkurs, Tagesschule Blüemlisalp Da Costa Beatrice
    (nichtschwimmer/sprungbecken) — a non-circular pin: named expected
    values, not the classifier's own regex.
  - No classification changes anywhere except the named Schwimmschule
    entry (corpus byte-identity minus exactly that owner).
- **Depends on**: S1 (same file + shared fixture touch; ordered to avoid
  churn).

### S4 — NULL is absence

- **Goal**: no store or wire value anywhere is the string "NULL"; absent
  descriptions and addresses are absent.
- **Touches**: `providers/geo_sport.py` (the sentinel rule; `description`
  is already `str | None` at every layer — no type change),
  `data/catalog.json` (re-snapshot via the committed WFS fixtures +
  MockTransport, the `test_roster.py:86` reproduction path — fully offline;
  the raw fixtures keep their literal `"NULL"` values so the golden pins
  the new rule, per the `wfs_snapshot.py` raw-asymmetry precedent),
  `tests/providers/test_geo_sport.py`, the golden roster test, storage/API
  tests that touch descriptions.
- **Acceptance**:
  - `parse`-level: a WFS property `"NULL"` → `None`; a real value passes; a
    value merely CONTAINING "NULL" as a substring passes untouched.
  - Catalog re-snapshot: EXACTLY 50 entries lose `description`; the other
    7 keep theirs verbatim; the provider-vs-committed golden compares
    equal. (`planschbecken-pfingstweid`'s empty `address` comes from real
    JSON nulls, not the sentinel — the sentinel rule must NOT produce a
    51st catalog diff; its absent-address rendering is a wire-layer
    concern, stated below.)
  - After a rebuild: no `facility_doc` and no `/pools/{id}` response
    contains the string `"NULL"` as a value (literal-scan assert).
  - The all-None/empty address renders absent at the API layer, not `""` —
    a wire-level pin on pfingstweid, no catalog change.
- **Depends on**: — (independent file; last because it re-snapshots a
  committed artifact the other slices don't touch).

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-09 | S1 | done | none of substance — `_first_data_top` refactored to reuse the new `_label_row_tops` (behavior-identical, verified by the byte-identity run). Process note: the implementer's connection dropped three times before it could deliver its report; the tree state was verified complete by the orchestrator and ALL claims were independently re-established by the critic (byte-identity executed against the HEAD parser across all 6 fixtures: exactly the two phantoms removed, nothing added, everything else field-identical). The 2.65-vs-3.65×pitch discrepancy adjudicated: both correct in different frames (last label ROW incl. the unconstructable 24:00 row vs last constructable TimeRange); a frame-naming clarification rides S2 | the sectioned-basin cell filter (`:839-843`) still has no bottom boundary — benign today (sectioned fixture parses identically), S2 touches that site and carries the boundary there; hypothetical door: a garbled final label row would silently shorten the grid by one row (no committed input takes it; a bottom-band cross-check noted for when convenient) | yes |
| 2026-08-09 | S2 | done | `_column_runs` gained a slot-contiguity break the Design didn't name — REQUIRED: Blaesi Thursday's Kantonspolizei block sits on both sides of the blank 07:30 label, and row-adjacency RLE would have bridged it, minting a claim over the blank half-hour (critic re-derived the necessity from raw pdfplumber geometry; verified a no-op on every well-aligned sheet by executed byte-identity). `_pair_rows_to_labels` also gained an injectivity arm (two rows claiming one label = SchemaMismatch) — same posture, unreachable on committed sheets. Tolerance set 0.5×pitch; the corpus window is (0.434, 0.514) with the sectioned Oerlikon basins binding at 0.514 — the comment's inherited "≥0.57" claim was corrected post-review (single-basin sheets ≥0.576; sectioned bind at 0.514, do-not-widen warning committed). Correct consequence: Blaesi Tue+Thu Kantonspolizei merge into one reservation (both source-true per raw geometry) | with <2 constructable labels the pairing degrades to length-checked rank pairing — unreachable on committed sheets (all ≥34 label rows), unit-covered both arms post-review; the S1 garbled-final-label hypothetical door remains open (cell_words excludes the orphan before pairing sees it) | yes |
| 2026-08-09 | S3 | done | the fix also lands on the Nichtschwimmer basin (the plan named only the schwimmerbecken generically — "Schwimmschule Limmatsharks" is code 4 in BOTH Oerlikon legends; 31 cells total flip, 10+21, critic re-derived); reservation-granularity divergence the plan didn't name — REQUIRED: distinct owners un-fuse Monday Teil 1's previously value-fused code-2/code-4 run into two reservations (raw codes verified: 15:30 row '2', 16:00 row '4'; cell-level identity holds; the mirror image of S2's merge); `pool_oerlikon.json` regenerated through the endpoint's own path (sprungbecken panel byte-identical — provenance proven; roster reorder is the deterministic sort key, no positional consumer) | `_legend_of` test helper re-implements the parser's word-extraction preamble — collapses onto a legend-extraction seam if one is ever exported (structural, declined this slice) | yes |

## Accepted drift

_(appended by hand from /dev:present findings the user has blessed; no command writes here)_

## Decisions & divergences

Substantive choices made during implementation, with the why. Each entry dated.

### 2026-08-09 — pre-approval review (plan-critic, 3 blocking, all accepted)

The critic parsed all seven committed PDFs and disproved three of the plan's
own design claims: (1) the original S1-then-S2 order was backwards — the
footer rows sit 2.11×/3.65×pitch from any label, so strict pairing would
SchemaMismatch both committed sheets before the boundary removed the
phantoms; reordered (boundary first), and the "belt-and-braces" framing
corrected to load-bearing. (2) The word-boundary school rule was over-broad:
the real legends carry nine genuine compound-named schools (Kantonsschule,
Tagesschule ×2, Freie Oberstufenschule, Gesamtschule, Rafaelschule,
Privatschule ×2, Schulsportkurs) that would have flipped to clubs — new
wrong claims from a repairs plan; replaced with a targeted Schwimmschule
exclusion and non-circular by-name pins. (3) The "footer text in no
reservation's provenance" criterion was unimplementable (no
reservation-level provenance field exists); replaced with the cells_total
and last-label-bound pins. Suggestions taken: golden conditional resolved
(no golden pins the shifted times; the two phantom digests do change and
belong to S1), City pitch corrected 12.95→12.60 (12.95 was Blaesi's),
tolerance widened to admit the sectioned basins' 0.434×pitch,
`pool_oerlikon.json` (fixture-backed preview surface embedding phantom +
wrong owner) added to S3's Touches, the S4 type hedge dropped
(`description` already optional everywhere), and the pfingstweid
address arm disambiguated to wire-level so the catalog diff stays exactly
50. `pause_after` moved S1→S2 with the reorder (the pairing slice remains
the riskiest).

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/claim-audit-repairs.md` (what EXISTS now, not what was intended).
