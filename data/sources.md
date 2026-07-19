# Data sources — legal register

> **These `data/` files are ETL inputs, not runtime reads.** The curated YAML (`pools/*.yaml`,
> `registry.yaml`, `calendar/*.yaml`) and `catalog.json` are the human/curated **source of
> truth**, committed to git. `swimzh build` assembles them (offline) into the single SQLite
> gold DB that the app actually reads at runtime; the app never opens these files directly.

One row per source we use or intend to use. Track license, terms, and refresh cadence so a
stale-but-typed wrong answer is a tracked risk, not a surprise. **Owner action noted below:
email Open Data Zürich to ask whether machine-readable schedules exist — that could remove
the need to scrape entirely.**

| Source | What we take | License / terms | Machine-readable? | Refresh cadence | Status |
|--------|--------------|-----------------|-------------------|-----------------|--------|
| `geo_sport` (data.stadt-zuerich.ch, CKAN) | Pool locations, facility metadata, geo | **CC0** (open) | ✅ JSON/GeoJSON | Rare (yearly-ish) | Planned (milestone 3) |
| stadt-zuerich.ch Hallenbäder pages | Opening hours + public-swim/women-only/senior slots | ⚠️ Not open data; copyright-in-compilation unclear under Swiss law | ⚠️ Timetable embedded as entity-encoded JSON in the HTML | Per season / term | **Scraped** by `providers/schedule_scraper.py` (`scrape-gold`); read-only of public pages, best-effort, 6/7 indoor pools parse. Prefer asking OGD for a feed (below). |
| CrowdMonitor (occupancy) — vendor = countee.ch | Live occupancy (indoor+outdoor) | ❌ Commercial; ToS unclear; surfaced via city "Badi aktuell" pages | ~JSON (semi-open) | 1–5 min | **Deferred** until vendor terms verified (milestone 5, behind a flag) |
| Baditicker API (stadt-zuerich.ch OGD) | Outdoor water temp + open/closed | Open (OGD) | ✅ JSON | Seasonal (off in winter) | Out of scope (outdoor only) |
| Zürich school-holiday / public-holiday dates | Calendar overlays | Public info (zh.ch, stadt-zuerich.ch) | Partially | ~Yearly | Curated into `data/calendar/zurich.yaml` (verify dates) |

## Open actions
- [ ] Email Open Data Zürich / OGD team: are indoor-pool **opening hours & public-swim
      schedules** available in any machine-readable form? (Could eliminate scraping.)
- [ ] Identify the exact CrowdMonitor vendor endpoint + terms before consuming occupancy.
- [ ] Verify the 2026 school-holiday and public-holiday dates in `data/calendar/zurich.yaml`.
- [ ] Verify each curated pool's hours/prices against its official page; update `valid_as_of`.
