---
type: plan
status: done
created: 2026-08-06
feature: price-age-bands
gates:
  qa: full
  review: adversarial
  max_rounds: 2
pause_after: []
links: ["[[2026-08-02-gold-coverage-gaps]]", "[[2026-08-06-seasonal-hours-plan]]"]
---

# Price age bands — stop inventing a tariff the city does not publish

## Intent (verbatim)

The user's own words, unedited. No agent may paraphrase, summarize, or
"clean up" this block. It is the anchor every later artifact is measured
against.

**2026-08-06**

> yes write plan it should focus first on getting data, fixing or improving providers; and also cleaning ambiguiity in data model; if we get right data, then querying should be easy

**2026-08-06** (on scope, after adversarial review)

> strip it down

## Context

This plan was drafted covering five gaps and reviewed adversarially five times. Every other
gap turned out to be blocked (see [Blocked](#blocked--needs-an-owner)); this one is not, and it
is serving wrong prices today.

`domain/pricing.py:28` bands ages at **≤5 / ≤15 / ≥65** and invents a `SENIOR` category. The
committed fixture `tests/providers/fixtures/preise_abos.html` carries the real bands in the
table's column headers:

```
"Erwachsene (ab 20 J.)"   "Jugendliche (ab 16 J.)"   "Kinder (ab 6 J.)"
```

and the string `Senior` appears **zero** times on that page. The scraper reads the row cells
positionally (`price_scraper.py:61`) and **discards the headers**, so the amounts are right and
every age mapping is wrong. Measured live against the store, on `hallenbad-blaesi`:

| age | served today | published truth |
|---|---|---|
| 10 | youth, CHF 6.00 | Kinder, CHF 4.00 — **overcharged** |
| 17 | adult, CHF 8.00 | Jugendliche, CHF 6.00 — **overcharged** |
| 70 | senior, CHF 6.00 | Erwachsene, CHF 8.00 — **undercharged, on a discount that does not exist** |

`query.py:386` calls `price_for` on every `/swim` option, so this is user-facing now on the 10
pools carrying prices.

The fix is **not** to re-hardcode better constants. The page states its own bounds; the parser
should read them. That is the same principle the seasonal plan and the school-access plan both
work from — the source is the fact, the classification is derived.

## Design (signature altitude)

### Bounds come from the page, not from the domain

```
PriceEntry:  + min_age: int | None      # from "(ab 20 J.)"; None = no stated bound

PriceTable.entry_for(age: int | None) -> PriceEntry | None
    # picks the entry with the greatest min_age <= age
    # age is None -> the entry with the greatest min_age (the unreduced/adult rate)
```

`category_for_age` and the module constants `_YOUTH_MAX_AGE` / `_SENIOR_MIN_AGE` are **deleted**.
Nothing in the domain decides what a Zürich youth is; the tariff does.

`PriceCategory.SENIOR` is **deleted** — 0 occurrences in the source page, and
`price_scraper.py:70` currently mints one from the `reduced` column, so the store publishes a
senior discount the tariff does not offer. Removing the member is compiler-enforced
(`mapping.py:147` is the only other site).

### The header is an attribute, not a row

`_ROW_RE` (`price_scraper.py:28`) matches `rows="[...]"` and is header-blind — the same defect
Gap 3 documents for the rentals tables. This slice adds a quote-aware `columns="[...]"` matcher
for **this one table**, which is what makes the bounds readable. Attribute order is not stable
across pages, so match by attribute name, never by position.

### The one thing the page does not state

`Kinder (ab 6 J.)` leaves **under-6 unpriced**. Today `price_for` falls back to the adult tariff
when a band is missing (`pricing.py:59-60`), which would charge a 3-year-old CHF 8.00.

**Decision taken: return `None`, and never fall back.** A missing band is unknown, not adult.
`OptionOut.price` is already `str | None` (`apps/web/api/swim/model.py:56`) and the UI already
renders a priceless option, so `None` costs nothing and asserts nothing. Inventing a price for a
toddler is exactly the class of fabrication `469a7b3` and `bad4020` removed elsewhere.

This also deletes the existing adult-fallback, which is the same fabrication in the same
function.

## Out of scope

- **Price discovery for the other 47 pools** (Gap 6's `+19 free` / `+29 total`). Blocked — see
  below. This slice changes **no** pool's price coverage; it corrects the mapping on the 10 that
  already have one.
- **Materialising free pools** (`is_free`). Needs discovery, which is blocked, and needs a
  render branch, which is UI.
- **The school tariff** (`Eintritte Schulschwimmanlagen`, 5.–/5.–/2.50). Only 4 of the 18 school
  pools are declared sources; the other 14 share `hallenbaeder.html` and are dropped by
  `declared_sources`' unshared-URL test. Blocked on the same mechanism as the Planschbecken.
- **All UI and presentation**, including the pool-type filter.
- **Deleting `Provenance.curated` / `measured_temp_c`.** `codec.py:74` is required under
  `extra="forbid"` and 57/57 blobs carry the key, so deletion invalidates every blob and forces a
  network-dependent rebuild. Re-propose separately.

## Slices

### S1 — read the published bands

- **Goal**: every age resolves to the entry the city publishes for it, or to nothing.
- **Touches**: `domain/pricing.py` (delete `category_for_age`, `_YOUTH_MAX_AGE`,
  `_SENIOR_MIN_AGE`, `PriceCategory.SENIOR`; add `PriceEntry.min_age`, `PriceTable.entry_for`,
  rewrite `price_for`), `providers/price_scraper.py` (quote-aware `columns` matcher, parse
  `ab N J.`, stop emitting `SENIOR`), `boundary/curated_dto.py` + `mapping.py:147`,
  `storage/codec.py` (`min_age` additive, popped when `None` per the `BasinDTO` precedent),
  `etl/field_sourcing.py` (the `facility.prices` row), `domain/query.py:386` (call-site type),
  `tests/providers/test_price_scraper.py`, `tests/domain/test_pricing.py`.
- **Acceptance**:
  - Against the committed `preise_abos.html` fixture, the parsed table is exactly
    `[(min_age=20, 8.00), (min_age=16, 6.00), (min_age=6, 4.00)]` — three entries, not four.
  - `PriceCategory.SENIOR` does not exist: `assert not hasattr(PriceCategory, "SENIOR")`.
    `assert set(PriceCategory) == {CHILD, YOUTH, ADULT}`.
  - Boundary tests, both sides of each published bound:
    `entry_for(5) is None`, `entry_for(6).amount_chf == 4`, `entry_for(15).amount_chf == 4`,
    `entry_for(16).amount_chf == 6`, `entry_for(19).amount_chf == 6`,
    `entry_for(20).amount_chf == 8`, `entry_for(70).amount_chf == 8`,
    `entry_for(None).amount_chf == 8`.
  - `assert not hasattr(pricing, "category_for_age")` and the two constants are gone — no
    hardcoded band survives anywhere in `src/`.
  - The adult fallback is gone: a table missing a band returns `None` for an age below every
    stated `min_age`, and a regression test names the toddler case.
  - Byte-stability: `'"min_age"' not in codec.dumps(f)` for a facility whose entries have no
    stated bound, mirroring `tests/storage/test_codec.py`'s existing absence assertions.
  - A rebuild is required (`min_age` enters the blob). `swimzh build` exits 0 and a `TestClient`
    boot serves `GET /pools` 200 against the rebuilt store.
- **Not in this slice**: any change to how many pools carry prices.

## Blocked — needs an owner

Filed here so they are not rediscovered. None is startable today.

- **Gap 6 discovery (+19 pools), Gap 3 rentals (15 pools / 101 rows), Gap 5 paddling (13),
  Gap 7 enge + dolder (2).** All four need pools that `declared_sources` currently excludes.
- **The blocker is not the kind gate.** All **13 Planschbecken share one URL**
  (`.../sommerbaeder/planschbecken.html`) and all **14 non-declared school pools share
  `hallenbaeder.html`**, so `declared_sources`' unshared-URL test (`etl/scrape.py:151`) drops
  them **regardless of kind**. Widening `_SCRAPEABLE_KINDS` does nothing for 27 of 57 pools.
  Reaching them needs a one-page-to-many-pools binding that no plan specifies; Gap 5 gestures at
  a `seed.py` xref join without designing it. **This is the single highest-value unowned piece of
  design in the backlog.**
- **The per-aspect fatal/non-fatal split** was proposed here and withdrawn. As specified it made
  a build exit 0 with a store claiming `ScheduleFreshness.NO_SOURCE` — *"no source exists"* — for
  pools whose page we fetched and failed to parse (`catalog.py:100`). The evidence doc rejects
  exactly that at `:388-390`. If it is revisited, the axis is **expected vs. not attempted**, not
  fatal vs. non-fatal, and the outcome is `_PhaseResult(code=1, fatal=False)` — the two-axis
  contract that already exists at `cli.py:249` — never exit 0.
- **`Facility.operating_season`** is out of scope in [[2026-08-06-seasonal-hours-plan]] and
  needed by Gap 5. Unowned.
- **Known roster defects** that will surface the moment the gate widens:
  `freibad-zwischen-den-hoelzern` carries a 404 URL in `data/catalog.json`
  (`.../freibad-zwischen-hoelzern`), and `flussbad-unterer-letten` shares its URL with
  `flussbad-unterer-letten-flussteil`.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|---|---|---|---|---|---|
| 2026-08-06 | S1 | done | `min_age` also surfaced on `/pools` (`PriceEntryOut`); an unbounded column is now a fail-fast `ParseError` | the school tariff (5.–/5.–/2.50) sits unread in the same table | no |

## Decisions & divergences

**2026-08-06 — the bound reaches the reader, not just the resolver.** `display` is now built from
the page's own header (`"Erwachsene (ab 20 J.) Fr. 8.00"`), and `PriceEntryOut.min_age` is
additive on `/pools`. The plan listed no `apps/web` file, but withholding a published bound from
the surface that shows the price is compression — the thing the intent forbids. No render logic
changed.

**2026-08-06 — an unbounded price column is fatal, not defaulted.** If a header stops printing
`ab N J.`, `parse_prices` returns `ParseError` rather than storing the amount under a guessed
band. Consistent with fail-fast scraping: a price we cannot attach to an age is not a price.

**2026-08-06 — `entry_for` ignores entries with `min_age=None`.** An unbounded entry is not
treated as universal; a table with no bounds resolves to `None` for every age. The only producer
(the scraper) now always sets the bound, so this affects hand-authored tables only.

**2026-08-06 — the three illustrative fixtures were rewritten**, not just stripped of `senior`:
they now carry the real 20/16/6 bounds, so the demo data teaches the published model.

## Summary

`domain/pricing.py` no longer decides what a Zürich youth is. The tariff prints its bounds in the
table headers the scraper used to discard; `PriceEntry.min_age` carries them, `PriceTable.entry_for`
picks the greatest bound an age clears, and nothing falls back. Verified against the rebuilt store
(`hallenbad-blaesi`): 15 -> 4.00 (was 6.00), 17 -> 6.00 (was 8.00), 70 -> 8.00 (was a 6.00 senior
rate the city does not offer), 3 -> no price (was 8.00). `PriceCategory.SENIOR`, `category_for_age`,
`_YOUTH_MAX_AGE` and `_SENIOR_MIN_AGE` are deleted; a test asserts none can return.

Price COVERAGE is unchanged at 10 pools — reaching the other 47 needs the one-page-to-many-pools
binding recorded under [Blocked](#blocked--needs-an-owner).
