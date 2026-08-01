---
type: summary
feature: roster-url-scheme-normalization
status: done
created: 2026-08-01
links: ["[[discovery-driven-providers]]", "[[data-layer-architecture]]", "[[source-links]]"]
---

# Roster URL scheme normalization — repairing a dead TLS listener at the WFS boundary

**What & why.** `www.sportamt.ch` (`194.56.34.210`) has **no TLS listener**: it accepts TCP on 443
and then sends nothing — ClientHello written, 0 bytes read, clean EOF at ~5.1s. Verified across TLS
1.0–1.3, ±SNI, ±ALPN, by-IP, apex host, `CERT_NONE`, `SECLEVEL=1`, under both LibreSSL-curl and
Python/OpenSSL; Qualys SSL Labs independently reports `protocols: []`, `certChains: []`. **No client
configuration can fix it.** Port 80 is healthy and 302s to the real page on `www.stadt-zuerich.ch`.

The city's own WFS roster publishes `url: https://www.sportamt.ch/<pool>` for 16 pools (17 carry a
sportamt URL; `seebad-katzensee` was already `http`) — all outdoor/lake/river. Page discovery failed
for all 16 at **~15.9s each** (5.1s EOF × 3 attempts, since `ConnectionFailed` is `retriable()` and
`RetryPolicy`'s default `sleep` is a no-op) ≈ **4 minutes of dead wait per build**. The
[[provider-http-disk-cache]] cannot amortize it: failed fetches are deliberately not cached.

## What exists now

- **`providers/geo_sport.py`** — `_normalize_roster_url(raw: str | None) -> str | None`, applied at
  the sole ingest point (`url=feature.properties.www` in `_to_geo_pool`). For a host **equal to**
  `sportamt.ch` or `www.sportamt.ch` (case-insensitive) with scheme `https`, it returns the URL on
  `http`; everything else is byte-identical. Parsed with `urlsplit`/`urlunsplit`.
- **`data/catalog.json`** — regenerated through that provider, so the committed snapshot is the
  **repaired** form. `data/sources.md` records the one plaintext hop and why it is accepted.
- **`cli.py`** — `live_timeout() -> httpx.Timeout` with `connect=5.0` and read/write/pool at 30.0.
- **The roster `url` is under test for the first time** — the golden roster test now compares it.

**Result: 15 of the 16 recover — verified by a live build**, not just by `curl`. `page discovery
failed` went **16 → 1**, and the survivor is exactly the predicted one:
`freibad-zwischen-den-hoelzern <- http://www.sportamt.ch/freibad-zwischen-hoelzern: HTTP 404`, a
stale WFS slug whose redirect target 404s — a fast, non-retried, non-fatal miss. Build exit 0, 57
facilities, 11.3s wall. The disk cache now holds **16 sportamt entries** where it previously held
none, since those pages had never once been fetched successfully. (The 11.3s was warm for the
stadt-zuerich pages; the clean attribution is the failure count and the ~4 minutes of TLS dead-wait
that no longer happens.) Fixing the slug means overriding a WFS-sourced value — a different decision,
deliberately not taken here.

## The four things worth remembering

1. **The field had zero test coverage.** The golden roster test explicitly projected `url` away and
   the API test asserted only non-nullness, so this repair — or any future corruption — would have
   shipped green through the whole QA chain. Both candidate fixes were audited *before* implementing,
   which is how that hole was found.
2. **The fixture asymmetry IS the pinning, and it looks like a bug.** The WFS fixtures and cassette
   keep the raw `https` form while `data/catalog.json` holds the repaired `http` form, so the golden
   test passes **only because the provider normalizes** (proven by mutation: neuter the normalizer and
   it fails with 16 differing entries). A contributor "fixing" the fixtures to match the snapshot
   would silently dissolve it — `wfs_snapshot.py`'s docstring now says so explicitly.
3. **Exact host match, never substring.** `sportamt.ch.example.com`, `notsportamt.ch`,
   `evil-sportamt.ch` and a trailing-dot host are all untouched; a userinfo form
   (`https://user@www.sportamt.ch/x`) matches on host only and cannot be spoofed by an `@`-prefixed
   authority. A substring match here would have been security-adjacent.
4. **Assert the seam, not the client.** `live_timeout()` exists as a factory because the live client
   is built under `# pragma: no cover - live` — the same trap that made a `--refresh` flag a silent
   production no-op in [[provider-http-disk-cache]].

## Why the scheme and not the host

Rewriting to `www.stadt-zuerich.ch/<slug>` would hardcode a copy of the city's slug mapping. The 302
**is** that mapping, served live, so following it survives a CMS move and survives the city fixing
TLS (the 302 would then point at the https form). A host rewrite would also put an invented URL behind
the user-visible "Official" link — and `freibad-zwischen-den-hoelzern` proves the slugs are not
reliably rewritable anyway. Corroborating evidence that the upstream scheme is noise: the city itself
already publishes `seebad-katzensee` on `http`.

The raw WFS value is **discarded**, deliberately — `GeoPool` gains no raw-vs-repaired provenance
field, since a tri-state would be gold-plating for a one-host repair. The consequence is that nothing
downstream can report what the city actually published; `data/sources.md` carries that note instead.

## Boundaries and carried debt

- No **cold** (`--refresh`) build has been measured against the repaired URLs, so the wall-clock
  saving is attributed from the failure count and the eliminated TLS dead-wait, not from a
  like-for-like cold comparison.
- The `Timeout(after_s=…)` label still reports 30.0s for a connect failure now bounded at 5.0s
  (`httpx.ConnectTimeout` is a `TimeoutException`). Accurate for reads, wide for connects.
- `apps/web/main.py` still builds its own live client on a flat timeout — the obvious `live_timeout()`
  reuse, listed as out of scope.
- `field_sourcing.py`'s `facility.website` row claims the WFS `www` as its source, but that field's
  only producer was the deleted curated tier (the `www` actually lands on `pool.url`). Pre-existing;
  resolve when `Facility.website` is retired.
- Not attempted: making the outdoor pools **scrapeable**. Their pages demonstrably carry
  *Öffnungszeiten* and *Preis*, so a follow-up plan is worth writing — the `INDOOR` guard in
  `scrape_indoor_facilities` is untouched here.

See [[2026-08-01-roster-url-scheme-normalization-plan]] for the ledger and full decision record.
