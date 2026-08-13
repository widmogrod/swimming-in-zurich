---
type: summary
created: 2026-08-06
feature: price-age-bands
links: ["[[2026-08-06-data-coverage-first-plan]]", "[[2026-08-02-gold-coverage-gaps]]"]
---

# Price age bands — the tariff states its own bounds

## What was wrong

`domain/pricing.py` banded ages at `≤5 / ≤15 / ≥65` and carried a `PriceCategory.SENIOR`. The
central price page prints its bands in the table's **column headers** —
`Erwachsene (ab 20 J.)`, `Jugendliche (ab 16 J.)`, `Kinder (ab 6 J.)` — and the string `Senior`
appears **zero** times on it. The scraper read the row cells positionally and discarded the
headers, so every amount was right and every age mapping was wrong. `query.py` calls `price_for`
on every `/swim` option, so this was live on the 10 pools carrying prices.

| age | served | published |
|---|---|---|
| 15 | 6.00 | 4.00 — overcharged |
| 17 | 8.00 | 6.00 — overcharged |
| 70 | 6.00 | 8.00 — a discount that does not exist |
| 3 | 8.00 | unpriced — the page prints no under-6 rate |

## The shape of the fix

`PriceEntry.min_age: int | None` carries the bound **the page printed**.
`PriceTable.entry_for(age)` returns the entry with the greatest `min_age` the age clears; an
unknown age takes the greatest bound (the unreduced rate — the one answer that can never
undercharge). Below every published bound the answer is `None`.

`category_for_age`, `_YOUTH_MAX_AGE`, `_SENIOR_MIN_AGE`, `PriceCategory.SENIOR` and
`PriceTable.by_category` are **deleted**, and a test asserts they cannot return.

## Three things worth remembering

- **`min_age=None` is not "covers everyone".** It means the source stated no bound, so the entry
  is not age-resolvable at all. Treating it as universal would reinstate the fallback by the back
  door.
- **No fallback, ever.** The old code fell back to the adult tariff when a band was missing, which
  charged a 3-year-old CHF 8.00. Unknown is `None`; `OptionOut.price` is already `str | None` and
  the UI already renders a priceless option, so honesty costs nothing here.
- **The `columns="…"` payload must be read off the RAW page.** It is an HTML-escaped attribute:
  unescaping the document first puts bare `"` inside it and destroys the attribute boundaries the
  regex matches on. Same trap `schedule_scraper` documents; the parse is `<stzh-datatable>`-scoped
  because the page carries several tables and a row means nothing without the headers above it.

## Left standing

- **Coverage is unchanged at 10 pools.** The other 47 need a one-page-to-many-pools binding that
  no plan specifies: 13 Planschbecken share one URL and 14 school pools share `hallenbaeder.html`,
  so `declared_sources`' unshared-URL test drops them regardless of kind.
- **The school tariff** (`Eintritte Schulschwimmanlagen`, 5.–/5.–/2.50) sits in the same
  `<stzh-datatable>` we already parse, unread — its columns carry the same three bounds. Cheap to
  pick up once a pool can be bound to it.
