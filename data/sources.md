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
| WFS `infrastruktur` prose (via `catalog.json` `description`) | Per-pool basin physicals (kind, size, lanes, nominal temp, diving-platform heights) + non-basin amenities (sauna/steam/terrace/restaurant/…) | Same terms as `geo_sport` (WFS metadata) | ⚠️ Free-text prose, not structured | With the WFS metadata (yearly-ish) | **Parsed offline** by `providers/infrastruktur.py`, wired into `swimzh build` for location-only pools → schedule-less `PARSED_PROSE` basins (shown in `/pools/{id}` with a caveat, never a `/swim` option). Best-effort, partial. |
| stadt-zuerich.ch Hallenbäder pages | Opening hours + public-swim/women-only/senior slots | ⚠️ Not open data; copyright-in-compilation unclear under Swiss law | ⚠️ Timetable embedded as entity-encoded JSON in the HTML | Per season / term | **Scraped** by `providers/schedule_scraper.py` (`scrape-gold`); read-only of public pages, best-effort, 6/7 indoor pools parse. Prefer asking OGD for a feed (below). |
| CrowdMonitor (occupancy) — vendor = countee.ch | Live occupancy (indoor+outdoor) | ❌ Commercial; ToS unclear; surfaced via city "Badi aktuell" pages | ~JSON (semi-open) | 1–5 min | **Deferred** until vendor terms verified (milestone 5, behind a flag) |
| Baditicker API (stadt-zuerich.ch OGD, `stzh/bathdatadownload`) | Current water temp + open/closed. **Covers indoor Hallenbäder too** (City, Oerlikon, Bläsi, Bungertwies, Leimbach, Käferberg) — not outdoor-only. Keyed by `poiid` (e.g. Freibad Heuried = `fb012`). | Open (OGD, no usage restrictions) | ✅ JSON/XML | Hand-measured by lifeguards during operation (~May–Sept); stale/absent off-season. Per-reading `dateModified`. | **Implemented** — `providers/baditicker.py` (`fetch`+`parse`+`BaditickerProvider` TTL cache) reads it as a freshness-bearing live reading (facility-level `live_water_temp` on `/pools/{id}`), keyed by `registry.yaml baditicker_poiid`; never a static gold column (time-varying — carries its own `dateModified`). Wired behind `SWIMZH_BADITICKER_URL` (fail-open when unset). See the temp-provider design note. |
| Zürich school-holiday / public-holiday dates | Calendar overlays | Public info (zh.ch, stadt-zuerich.ch) | Partially | ~Yearly | Curated into `data/calendar/zurich.yaml` (verify dates) |

## `www.sportamt.ch` — one plaintext hop, accepted

The WFS roster points **17 of 57** pools at `www.sportamt.ch` (17 of the 19 outdoor/lake/river
ones) — **16** of them as `https://www.sportamt.ch/<pool>`; the 17th, `seebad-katzensee`, is
already published as `http` and the repair leaves it alone. That host **has no TLS listener**: it accepts TCP on 443 and then sends
nothing — ClientHello written, 0 bytes read, clean EOF at ~5.1s. Verified 2026-08-01 across TLS
1.0–1.3, ±SNI, ±ALPN, by-IP, apex host, `CERT_NONE` and `SECLEVEL=1`, under both LibreSSL-curl and
Python/OpenSSL; Qualys SSL Labs from an independent vantage reports no protocols and no cert chain.
No client configuration can fix it. Port 80 is healthy and answers with a single `302` to
`https://www.stadt-zuerich.ch/<pool>`, the real page.

`providers/geo_sport.py::_normalize_roster_url` therefore rewrites **only** that exact host (apex or
`www`, case-insensitive) from `https` to `http`; every other roster URL is byte-identical. The
repair happens at the WFS boundary, so `data/catalog.json` is a snapshot of what the **provider**
emits, not of the raw feed — and the raw `https` value is **discarded**, deliberately: nothing
downstream can report what the city actually published. This note is that record.

**Why the plaintext hop is accepted.** Each fetch traverses exactly one unencrypted request to
`www.sportamt.ch` before the 302 lands it on `https://www.stadt-zuerich.ch`, where the rest of the
exchange is encrypted. What crosses in the clear is a GET for a **public pool page** — no
credentials, no cookies, no user data, nothing per-visitor. The exposure is that an on-path attacker
could see which pool page is being fetched or tamper with the redirect; the alternative is a URL
that cannot be fetched at all (16 pools unreachable) or hardcoding a private copy of the city's slug
mapping behind a user-visible "Official" link. The 302 **is** that mapping, served live. Revisit if
the city ever brings up a TLS listener — the repair then becomes unnecessary, and a 302 from port 80
to the https form would be followed transparently anyway.

## Open actions
- [ ] Email Open Data Zürich / OGD team: are indoor-pool **opening hours & public-swim
      schedules** available in any machine-readable form? (Could eliminate scraping.)
- [ ] Identify the exact CrowdMonitor vendor endpoint + terms before consuming occupancy.
- [ ] Verify the 2026 school-holiday and public-holiday dates in `data/calendar/zurich.yaml`.
- [ ] Verify each curated pool's hours/prices against its official page; update `valid_as_of`.
- [ ] Report the dead `www.sportamt.ch` TLS listener to the city (see the note above); drop the
      scheme repair once port 443 answers.
