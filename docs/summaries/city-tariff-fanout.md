---
type: summary
created: 2026-08-08
feature: city-tariff-fanout
links: ["[[2026-08-07-city-tariff-fanout-plan]]", "[[city-tariff]]", "[[discovery-driven-providers]]", "[[price-age-bands]]"]
---

# City tariff fan-out — what exists now

Admission prices reach **21 of 57** pools (was 10), and a Schulschwimmanlage charges the rate the
city actually prints for it.

## The two things that changed

**`parse_prices` returns `CityTariffs`, not one table.** The page publishes a general
`Einzeleintritte` row (8.–/6.–/4.–) *and* a separate one under `Eintritte Schulschwimmanlagen`
(5.–/5.–/2.50). Only the general one was read, so every school-pool visitor was overcharged by
Fr. 3.00 (a child by Fr. 1.50). Selection is **section-anchored** inside the single
`<stzh-datatable>` carrying that heading — three rows in it begin with `Einzeleintritt`, and the
third is the sauna's Fr. 12.– surcharge whose own label says a Hallenbad ticket must be bought in
addition.

**The fan-out follows a discovered link.** `_CITY_HOST` is gone. `states_city_tariff(page_html)`
is true when the page carries an href whose path ends `/sport-und-badeanlagen/preise-abos.html`;
`tariff_for(source, page_html, tariffs)` then picks the school rate for a `SCHOOL` pool and the
general rate otherwise. This is [[discovery-driven-providers]] rule 2 applied to pricing.

## Why not the hostname — the mistake worth remembering

`sportamt.ch` really is the city's sports office, and
`http://www.sportamt.ch/freibad-heuried` → **302** → `https://www.stadt-zuerich.ch/freibad-heuried`.
"City host ⇒ city tariff" looked airtight and was wrong: **four of those pools publish
*"Der Eintritt … ist gratis"*** and `maennerbad-schanzengraben` states *"wird privat betrieben"*.
The rule would have invented a Fr. 8.00 charge at four free pools. The tariff page warns of exactly
this — *"Es gibt Vergünstigungen aber auch Gratisbäder."*

**Municipal operation and paid admission are different facts, and only one of them is a hostname.**
Caught by the plan critic before any code existed; see [[city-tariff]] for the discriminator.

## What the numbers are, and where they are pinned

| set | count | pinned by |
|---|---|---|
| declared sources | 26 | `tests/etl/test_scrape.py` |
| link the tariff page | 21 | `test_states_city_tariff_over_every_declared_sources_committed_page` |
| state no tariff | 5 | same — altstetten (private) + 4 free |
| priced pools in a built store | 21 | `apps/web/tests/test_gold_store.py` (literal SQL over `facility_doc`) |

A declared source with no tariff produces a **build note**, not a failure: the build prints it and
exits 0. The note exists because the live build reads `fetch_roster`, not the committed
`catalog.json`, so the offline ratchet cannot see a WFS URL drift that deletes a price.

## Reviewed by mutation, not by reading

Both slices' reviews broke the mechanism and watched tests fail, which is the only way to tell a
real gate from a tautology:

- reverting the section anchoring to first-match-wins → **3** tests fail
- forcing `states_city_tariff` to `True` → **8** fail; to `False` → **12** fail

One test in S1 *was* found tautological — a "no Fr. 12.– entry" assertion that no mutation could
break, the same criterion the plan had already dropped before approval and which crept back in as
a test. Replaced with one covering a genuinely unexecuted error branch.

## Left standing

- **Free ≠ unknown, and the store cannot tell.** The four free pools carry `prices=None`, the same
  value as the 31 pools nobody has scraped. Only the build note holds the fact. Needs
  `Admission = Free | Tariff | Unknown`, a blob-format change across all 57 pools.
- **A total link outage builds green.** If every page dropped the link: 26 notes, 0 priced, exit 0.
  CI's ratchet catches it; a live build would not.
- **A failed `scrape_prices` degrades silently** to `tariffs=None` (`cli.py:290-292`) — pre-existing,
  but it now unprices 21 pools rather than 10.
- **Still unpriced: 36 pools.** 31 are not declared sources at all (13 Planschbecken sharing one
  URL, 14 school pools sharing `hallenbaeder.html`, enge + dolder, the unterer-letten pair) and
  need the one-page-to-many-pools binding; 5 are the free/private ones, correctly unpriced.
