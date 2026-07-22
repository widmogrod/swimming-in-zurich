---
type: concept
created: 2026-07-21
links: ["[[2026-07-21-lane-plan-reconciliation-plan]]", "[[lane-plan-url-binding]]", "[[richer-data-fidelity]]"]
---

# Lane-data availability — the complete published universe for Zürich pools

Researched 2026-07-21 (3-agent web sweep, verified by fetching). This bounds ALL lane-reservation
("Belegungsplan") data obtainable for the 57 catalog pools — use it to avoid chasing sources that don't exist.

## The published universe is 8 PDFs across 6 indoor pools — and we already have all 8

`scrape-lanes` fetches exactly the complete set. Fetching the raw HTML of every stadt-zuerich indoor-pool
page and grepping `belegungsplaene/*.pdf` returns **only** these 8 slugs (all HTTP 200), which are already
wired in `etl/lane_plans.py`:

| Pool | Basin(s) with a Belegungsplan | Slug |
|---|---|---|
| Hallenbad City | Schwimmerbecken (50m) · Variobecken (Hubboden) | `city-schwimmerbecken`, `city-variobecken` |
| Hallenbad Oerlikon | Schwimmerbecken (50m) · Nichtschwimmer+Sprungbecken (one **combined** sheet, 2 sections) | `oerlikon-schwimmerbecken`, `oerlikon-nichtschwimmer-sprungbecken` |
| Hallenbad Bungertwies | 25m (single basin) | `bungertwies` |
| Hallenbad Bläsi | 25m (single basin) | `blaesi` |
| Hallenbad Leimbach | 25m (single basin) | `leimbach` |
| Wärmebad Käferberg | Mehrzweckbecken (Hubboden) | `kaeferberg` |

Not every basin has a plan: City has 4 physical basins but only 2 lane sheets (Nichtschwimmbecken/Fussbad
have none); Käferberg's 32°C thermal pool has none. So a curated basin legitimately carries **no**
`lane_plan_source` — expected, not a gap.

## What does NOT exist (so don't build discovery for it)

- **Outdoor Freibäder / lake Strandbäder / river Flussbäder publish NO Belegungsplan.** Every plausible slug
  (letzigraben, max-frisch-bad, allenmoos, auhof, zuerichhorn, mythenquai, heuried, seebach, oberer-letten,
  unterer-letten, maennerbad, frauenbad) returns 404 against the same DAM base that serves the indoor 8 as
  200. Their pool pages carry **opening hours only** (Oberer Letten even says "keine Reservation möglich").
  Belegungspläne are an **indoor-Hallenbad-only** artifact. Outdoor lane use is governed physically on-site.
- **The DAM `belegungsplaene/` directory is not browsable** (404, no index). Discovery is pool-page →
  linked-PDF only — and that discovery is now **exhausted**.

## The one off-city source: Hallenbad Altstetten (external operator, different medium)

Altstetten (`bad-altstetten.ch`, a Genossenschaft — not the city) DOES publish a weekly 5-lane grid, but as a
**PNG image** (`.../wp-content/uploads/2026/03/belegung-schwimmerbecken-...-scaled.png`), not a PDF and not in
the city format. It has no text legend (colour→club is visual only), lanes are unlabelled, and the URL sits in
a year-folder that rotates. Ingesting it needs **OCR/vision parsing + a hand-maintained legend** — a separate
pipeline from the stadt-zuerich PDF parser. Discover the image from the `/schwimmen-2/` page, never pin the URL.

Club / ASVZ / Schwimmverein sources (Limmat Sharks, ZüriLeu, Limmat-Nixen, ASVZ) are **not** a viable
supplementary feed: each publishes in a different shape or not at all (ASVZ hides times in a booking portal;
clubs list pools without times). At best cross-validation, never a primary source.

## Consequences for the roadmap

- **Discovery is done.** The [[2026-07-21-lane-plan-reconciliation-plan]] needs no discovery slice; its derived
  fetch-set + `PENDING_BELEGUNGSPLAENE` list is provably complete and stable for stadt-zuerich.
- The lane-data ceiling via the PDF pipeline is these 8 sheets. Reconciliation unlocks the 2 currently-blocked
  curated basins (bungertwies-25m, oerlikon-sprungbecken → 4 attach); curating leimbach/blaesi/käferberg (their
  sheets already parse) raises it to ~7; City-Variobecken needs a curated Vario basin.
- **Altstetten is a distinct future feature** (vision-parse a PNG), not part of the PDF reconciliation plan.
- Caveat: stadt-zuerich pool pages are **JS-rendered** — WebFetch/rendered-DOM sees no PDF links; raw HTML
  (`curl`) + grep is the reliable method (relevant if `schedule_scraper.py` ever depends on the rendered DOM).
