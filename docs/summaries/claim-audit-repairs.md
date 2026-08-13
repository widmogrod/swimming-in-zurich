---
type: summary
created: 2026-08-09
links: ["[[2026-08-09-claim-audit-repairs-plan]]", "[[lane-plan-url-binding]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# Claim-audit repairs

Four defects that served claims their sources never made — found by a blind
claim-audit backtest, repaired with executed byte-identity proofs that
nothing else moved.

## What exists

- **The grid bottom** — `_grid_bottom` bounds lane-plan cells at the last
  gutter label row + one pitch (`GridSpec.label_overhang_ratio`); footer
  digits (2.11×/2.65×pitch below) can never mint phantom sessions. Leimbach
  and Oerlikon lost exactly their two fabricated sessions; `cells_total` is
  the true grid again. Applied at both the flat and sectioned sites.
- **Geometry pairing** — `_pair_rows_to_labels` replaces both rank slices:
  a cell row claims its nearest label within 0.5×pitch (measured corpus
  window (0.434, 0.514); the sectioned Oerlikon basins bind — do-not-widen
  warning committed). A label with no cells is an honest blank half-hour;
  an unpairable in-grid row or a double claim is `SchemaMismatch`. RLE runs
  break at slot gaps so no reservation bridges a blank. Blaesi serves
  Sunday public swim 09:00–18:00 and Kaeferberg starts 06:30 — as their
  PDFs publish; correct consequences: Blaesi Tue+Thu Kantonspolizei merge,
  Oerlikon Monday Schulen/Schwimmschule un-fuse (both raw-geometry-true).
- **The owner exclusion** — `_code_to_access` routes SCHOOL only when a
  "schul" hit survives removing the word "schwimmschule": 31 cells across
  both Oerlikon basins serve `ClubReserved("Schwimmschule Limmatsharks")`;
  the nine genuine compound-named schools (Kantonsschule … Schulsportkurs)
  are pinned by name as untouched. `pool_oerlikon.json` regenerated through
  the endpoint's own path (sprungbecken byte-identical proved the method).
- **The NULL sentinel** — the WFS literal token `NULL` parses to `None` at
  the boundary (description, address parts, every cleaned field; `name`
  deliberately exempt — identity-bearing, corpus-pinned). `catalog.json`
  re-snapshotted offline byte-equal: exactly 50 descriptions became
  absent, 7 kept verbatim. The wire serves absence as null-never-`""`, and
  a whole-surface scan (57 rows, every blob, every `/pools/{id}`) pins
  that no served value is the string "NULL".

## Verification discipline worth reusing

Every slice compared the whole fixture corpus against the prior-commit
parser (`git show <sha>:…` loaded side by side) — implementer and critic
independently — so each diff is provably exactly the named correction.
The plan itself went through two pre-approval critic rounds that reversed
its slice order and rescued nine schools from its own over-broad rule.

## Known limits

A garbled final label row would silently shorten a grid by one row (no
committed input does; bottom-band cross-check recorded). Uncleaned fields
match the sentinel only as the exact token. The `_legend_of` test helper
duplicates the parser's word-extraction preamble until a seam is exported.
