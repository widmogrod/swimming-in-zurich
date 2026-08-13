---
type: summary
created: 2026-08-09
links: ["[[2026-08-08-mietobjekt-extraction-plan]]", "[[locker-option]]", "[[rental-item]]", "[[facility-field-sourcing]]"]
---

# Mietobjekt extraction

The lockers machinery got its producer, and the rentals got a seat — one
table, two typed outputs, nothing dropped. See [[rental-item]].

## What exists

- **The parser** — `providers/mietobjekt.py::parse_mietobjekte`, anchored
  by the `Mietobjekt` column header inside a `<stzh-datatable>` on the raw
  page (reuses `price_scraper`'s escaped-JSON machinery — private imports,
  recorded debt). On the 20 declared pages that carry the table. Absence
  → `Ok` empty; a malformed price cell or an undecodable anchored table
  → fatal `ParseError`.
- **Routing** — `…kasten`/`Wertsachenfach`/`Wäschefach` → `LockerOption`
  (period suffixes verbatim-unparsed: "1/2 Jahr", "Monats", "Saison",
  "Tages"); towel/swimwear/goggles/cabin/sunlounger/parasol nouns →
  `RentalItem` with a closed `RentalKind`; anything else →
  `RentalItem(OTHER)` carrying the label in `raw` — no row lands on the
  floor, pinned synthetically.
- **The fee union** — `RentalFee = Priced(amount) | Gratis | Unstated`:
  a page-stated "gratis" (13 cells in the corpus) and a fee the page
  doesn't state (8 cells, e.g. "auf Anfrage") are different facts and
  cannot compress. Pinned at parser, codec, and wire (the wire pin exists
  because a critic mutation proved the arm was unenforced). Serialized as
  `fee_chf` + `fee_state: "gratis"` popped when absent. `LockerOption`
  keeps two-state `fee_chf` — corpus-honest, behind a loud guard test.
- **The sets** — locker-carrying and rentals-carrying pools both equal
  the fixture-derived 20, established by parser-independent noun scans
  owned once in `tests/declared_fixtures.py` (also the shared pool-id →
  fixture mapping). Kind-level pins: wear 11, cabin 11, sunlounger 9,
  parasol 8.
- **The wire** — `/pools/{id}` lists lockers and rentals; hallenbad-city
  serves all 7 Mietobjekt rows across the two fields;
  `fee: "priced" | "gratis" | "unstated"` with `fee_chf` non-null exactly
  when priced. Blobs pop `rentals` when empty; pre-S2 blobs load `()`.

## Known limits

Deposits still compress "Ausweis als Depot" and "no deposit stated" into
one `None` (`raw` carries the distinction; nothing reads deposits
semantically). `mechanism` stays `None` — pages don't state it. The 31
non-declared pools have no page fetch to piggyback on. UI renders nothing
new — data first, per the standing decision.
