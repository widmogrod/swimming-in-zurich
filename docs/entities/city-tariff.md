---
type: entity
name: city-tariff
created: 2026-08-07
links: ["[[2026-08-07-city-tariff-fanout-plan]]", "[[2026-08-06-data-coverage-first-plan]]", "[[discovery-driven-providers]]", "[[facility-field-sourcing]]"]
---

# City tariff

Zürich publishes admission prices **once, city-wide**, on `preise-abos.html` — not per pool. One
`<stzh-datatable>` carries several tariffs grouped by rows whose price cells are blank
(`Mehrfacheintritte`, `Saisonabo Bäder`, `Jahresabo Bäder`, `Eintritte Schulschwimmanlagen`,
`Eintritte Sauna City und Leimbach`). That grouping is the page's own structure and is what row
selection anchors on: **three rows in that element begin with `Einzeleintritt`**, and one is the
sauna's — a surcharge whose own label says a Hallenbad ticket must be bought *in addition*, so
serving it as pool admission would be wrong twice over. The file holds **two** such elements; the
second (winter) repeats `Einzeleintritte 8/6/4` but has no school section, so a tariff pair taken
one row from each would silently mix two header sets.

Schulschwimmanlagen are priced separately — 5.– / 5.– / 2.50 against the general 8.– / 6.– / 4.–.
Both rows share the element's column headers, so the school rate inherits `min_age` 20 / 16 / 6
without a second parse; see [[2026-08-06-data-coverage-first-plan]] for why bounds are read and
never assumed.

## Which pools it covers — the page says, by linking

The tariff applies to a pool exactly when **that pool's own page links to it** (an `href` whose
path ends `sport-und-badeanlagen/preise-abos.html`). Measured across all 26 declared sources
against their committed fixtures: **21 link, 5 do not**, and the 5 are precisely the pools a city
rate must never be asserted for — `hallenbad-altstetten` (private operator, links to its own
`/schwimmen-2#preise`), `maennerbad-schanzengraben` (*"wird privat betrieben … ein Gratisbad"*),
and `flussbad-au-hoengg` / `flussbad-oberer-letten` / `seebad-katzensee`, each of which publishes
*"Der Eintritt … ist gratis."*

This is [[discovery-driven-providers]] rule 2 applied to pricing: a link the upstream page emits,
re-derived every run, rather than a curated list that rots.

**A host-keyed rule looks right and is not.** `sportamt.ch` really is the city's sports office —
`http://www.sportamt.ch/freibad-heuried` returns 302 → `https://www.stadt-zuerich.ch/freibad-heuried`
(verified 2026-08-07) — so "city host ⇒ city tariff" is tempting. It would have charged Fr. 8.00
at four pools the city publishes as free. The tariff page warns of exactly this case:
*"Es gibt Vergünstigungen aber auch Gratisbäder."* Municipal operation and paid admission are
different facts, and only one of them is a hostname.

**Free is not the same as unknown**, and the store cannot yet tell them apart: those four pools
land as `prices=None`, the same value carried by the 31 pools nobody has scraped. Separating them
needs `Admission = Free | Tariff | Unknown`.
