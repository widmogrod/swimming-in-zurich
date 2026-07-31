---
type: plan
status: approved         # draft -> approved -> in-progress -> done
created: 2026-07-31
feature: provider-http-disk-cache
gates:
  qa: full               # ruff, mypy, pytest+coverage, crap.py
  review: adversarial    # critic must find no blocking issues per slice
pause_after: []          # no destructive step; nothing to gate mid-way
links: ["[[data-layer-architecture]]", "[[discovery-driven-providers]]", "[[gold-store]]"]
---

# Provider HTTP disk cache — inspectable, per-tier TTL, behind the `HttpClient` seam

## Context

The atomic `swimzh build` is network-bound: it serially refetches the WFS roster + pool pages +
Belegungsplan PDFs + the tariff page on every run (a cold build measured **>9 min**, killed before
completing). There is no on-disk cache, so local iteration is slow and there is no easy way to see
**what a provider's source actually returned**. This plan adds a **disk-cache abstraction for the
providers**: responses are cached to disk with a **per-tier TTL** (keyed off each provider's
volatility), so re-running the pipeline makes a network call **only when the cached entry is stale**;
a warm cache makes the build near-instant. The on-disk format is **one human-readable JSON file per
entry** (request + response headers + body), so a developer can `cat`/`jq` exactly what a site
returned. Owner decision (2026-07-31): a **thin custom transport we own**, not a library — the
maintained httpx cache lib (hishel 1.x) stores an opaque msgpack+gzip SQLite blob, defeating the
plain-file-inspectability goal; hishel 0.x had it but is EOL. A ~150-LOC transport also matches this
repo's own-the-seam ethos (the hand-rolled `HttpClient`, the hand-rolled i18n runtime).

## Design (signature altitude)

**One new seam: an `httpx` transport, so `HttpClient` and all five providers are UNCHANGED.**

- `core/httpcache.py`:
  - `CacheStore` — **pure, no httpx/network**: `fresh(request, now) -> httpx.Response | None`
    (returns a cached response iff an entry exists and `now < expires_at`), `put(request, response,
    *, tier, ttl_s, now)`. Owns key derivation (`sha256(method + url)[:16]`; query is in the url),
    the on-disk JSON (de)serialization, and the path scheme. **Body encoding is TEXT by default,
    base64 only for binary:** the store writes the body as inline UTF-8 **text** unless the response
    `Content-Type` is binary (`application/pdf`, `application/octet-stream`, `image/*`, and other
    non-text types) — then `body_base64`. A UTF-8-decode failure is a safety fallback to base64. So
    JSON/HTML/XML (WFS GeoJSON, stadt-zuerich pages, the tariff page, Baditicker XML) stay
    `cat`/`jq`-readable; only the Belegungsplan PDFs are base64. **Any `OSError`/corrupt-file is
    swallowed as a miss** — cache I/O never raises.
    Caches **all statuses** (2xx, 3xx redirect hops, 5xx) — see the redirect note below.
  - `DiskCacheTransport(inner, store, mode, *, now: Callable[[], datetime])` where
    `CacheMode = USE | REFRESH | OFF`. The **clock is injected** (`now`) so freshness is
    deterministic in tests. `handle_request` **fully buffers** the inner response body, then: on
    `USE`, a fresh hit returns a reconstructed `httpx.Response(status, headers, content=body)` (no
    network); else delegate to `inner` **once** and `put` the buffered result (write-through).
    `REFRESH` skips the read; `OFF` passes straight through. **Buffer-only — not compatible with
    `client.stream(...)`; the pipeline uses `.get()` only** (`max_bytes=10MB` bounds the PDFs).
- `core/cache_tiers.py` — the whole per-tier policy in one table, keyed off `HttpClient.source`:
  `geo_sport → 14d`, `page_provider → 7d`, `price_scraper → 7d`, `belegungsplan → 3d`,
  `schedule_scraper → 12h`, `baditicker → 2m` (mapping the static/snapshot/live volatility tiers).
  `HttpClient.get` stamps `request.extensions = {"cache_tier": t, "cache_ttl_s": ttl}` from
  `self._source` — providers untouched.
- **The tier seam requires per-source clients at the composition root (was the plan's original
  flaw).** Today `cli.py build` constructs ONE `HttpClient(source="geo_sport")` and threads it
  through every phase (`fetch_roster`/`scrape_prices`/`scrape_indoor_facilities`/`discover_pages`/
  `scrape_lane_plans`), so `self._source` is fixed and every request would collapse to the 14d tier.
  **Fix:** the composition root builds ONE `DiskCacheTransport` (one shared cache dir) and wraps it
  in **one `HttpClient` per source** — `geo_sport` (roster), `schedule_scraper`, `price_scraper`,
  `page_provider` (discovery), `belegungsplan` (lanes) — and threads the source-matched client into
  each **provider call**. NB a phase function is **not** source-atomic: `_compose_schedules` fans out
  to `scrape_prices` (`price_scraper`/7d) **and** `scrape_indoor_facilities` (`schedule_scraper`/12h);
  `_attach_lanes` fans out to `discover_pages` (`page_provider`/7d) **and** `scrape_lane_plans`
  (`belegungsplan`/3d). So `_compose_schedules` and `_attach_lanes` each take **two** clients, not
  one — the source granularity is the provider call, not the phase. Providers stay byte-unchanged
  (they still just receive an `HttpClient`); the change is in `cli.py`'s client construction +
  those two phase-function signatures. This is S4, not "one line".
- **Composition roots** (`cli.py`; `apps/web/main.py`): build the shared inner transport
  `DiskCacheTransport(httpx.HTTPTransport(), CacheStore(dir), mode, now=…)` once. Web runtime
  defaults `OFF` (baditicker already has its own in-process 2-min TTL).

**Errors-as-values preserved (the core invariant).** A hit returns a normal `httpx.Response` →
`HttpClient._classify` runs unchanged (a cached 500 still maps to `HttpStatus`). A miss delegates to
the real `HTTPTransport`, whose `TransportError`/`TimeoutException` propagate into `HttpClient`'s
existing `try/except` → `ConnectionFailed`/`Timeout`. No new exception type crosses the boundary; the
store's own disk faults degrade to a miss.

**On-disk layout** (`.cache/swimzh/<tier>/<host>/<key16>.json`, git-ignored). `body` holds readable
text for text content-types (`body_base64: null`); for a binary content-type, `body: null` and
`body_base64` holds the encoded bytes — exactly one of the two is set:
```json
{ "cache":   {"key":"9f3a1c…","tier":"static","fetched_at":"…","ttl_s":1209600,"expires_at":"…"},
  "request": {"method":"GET","url":"…","headers":{…}},
  "response":{"status":200,"content_type":"application/json","headers":{…},"body":"{…}","body_base64":null} }
```
Inspect: `cat`/`jq`/`find .cache/swimzh` (text bodies read directly). Clear: `rm -rf .cache/swimzh[/<tier>]`.

**Staleness & refresh.** TTL is **our** policy (origins send no useful `Cache-Control`). Stale/missing
→ exactly one refetch, write-through. `SWIMZH_CACHE=off|refresh` env + a `--refresh` flag drive
`CacheMode`; `OFF` == today's behavior (safety valve for CI/live-correctness runs).

**Redirects & statuses.** The live client sets `follow_redirects=True`, so httpx invokes the
transport **once per hop** and `HttpClient` never sees the 3xx. So the store must cache **every**
status keyed by the exact per-hop URL (301/302 included) — otherwise a redirecting page (e.g.
`bad-altstetten.ch`) still hits the network on a warm cache and breaks the zero-network guarantee. A
cached non-2xx replays exactly as the live one did (`_classify` still maps a cached 500 to
`HttpStatus`).

**Invariants.**
- `HttpClient` public API and every provider are byte-unchanged (a transport is the only seam).
- Cache I/O never raises across `HttpClient` — a corrupt/unwritable cache degrades to network.
- `OFF` mode is behaviourally identical to no cache (regression-guarded).
- The cache is a dev/build accelerator, **git-ignored**; it is NOT a runtime source of truth (the
  gold DB remains that) and NOT the test-fixture store (vcrpy cassettes stay the contract).

## Out of scope

- RFC 9111 / revalidation (`ETag`/`If-None-Match`) / `Vary` — GET-only, TTL-only. Non-goal.
- Unifying with the `vcrpy` cassettes — they stay the checked-in, `block_network` test contract; the
  cache is git-ignored and TTL-driven. (An optional one-way `cache promote` bridge is S5.)
- Fixing the ~57-page **lane-discovery scope** bug (discovery fetches every roster pool, not just the
  6 with a `lane_plan_source`) — a separate defect; a warm cache only *mitigates* the pain. Filed
  separately.
- Async — the pipeline client is sync (`httpx.Client`).

## Slices

### S1 — `CacheStore` (pure): keys, JSON±base64 (de)serialize, freshness, corrupt-as-miss

- **Goal**: A pure, network-free store that reads/writes one inspectable JSON file per entry and
  answers freshness — testable in complete isolation.
- **Touches**: `core/httpcache.py` (`CacheStore`), `tests/core/test_httpcache_store.py`.
- **Acceptance**: `put` then `fresh` round-trips a `Response` (status/headers/body) byte-exact; a
  **text** content-type (e.g. `application/json`) is stored as **inline readable text** (`body` is
  the JSON string, `body_base64` is null — asserted on the raw file); a **binary** content-type
  (`application/pdf`) is stored base64 (`body` null, `body_base64` set) and round-trips byte-exact; a
  non-UTF-8 body under a text-ish content-type falls back to base64 (safety); an entry past
  `expires_at` returns `None`; a hand-corrupted JSON file and an unreadable path both return `None`
  (miss) and never raise; the on-disk file is valid pretty JSON with the documented shape.
- **Depends on**: —

### S2 — `DiskCacheTransport` (USE/REFRESH/OFF)

- **Goal**: The transport that turns the store into httpx caching, driven by request extensions,
  with an **injected clock** so freshness is deterministic.
- **Touches**: `core/httpcache.py` (`DiskCacheTransport(inner, store, mode, *, now)`, `CacheMode`),
  `tests/core/test_httpcache_transport.py`.
- **Acceptance** (drive with `httpx.MockTransport` as `inner` + a controllable `now`): `USE` + fresh
  entry → **0** inner calls, cached body/status/headers returned; `USE` + stale (advance `now` past
  `expires_at`) or missing → **exactly 1** inner call, entry written; `REFRESH` → always 1 + overwrite;
  `OFF` → passthrough, store untouched; a redirect (302) and a 500 are both cached and replayed; an
  inner `TransportError` still propagates (not swallowed by the cache).
- **Depends on**: S1.

### S3 — Per-tier TTL table + `HttpClient.get` stamps extensions (mechanism)

- **Goal**: The mechanism — map each `source=` to its volatility TTL and stamp it per request. (This
  slice does NOT yet make production multi-tier — that needs the per-source clients in S4.)
- **Touches**: `core/cache_tiers.py` (the table), `core/http.py` (stamp `extensions` from
  `self._source` in `get`, without clobbering a caller-supplied `extensions`), `tests/core/test_cache_tiers.py`.
- **Acceptance**: `HttpClient(source="geo_sport").get(...)` stamps `cache_ttl_s == 14d` /
  `cache_tier == "static"`, `source="schedule_scraper"` → `12h`, etc. (per-source table asserted); an
  unknown `source` → documented default TTL; the stamp merges with (never overwrites) a caller's own
  `extensions`; a test asserts no provider module changed.
- **Depends on**: S2.

### S4 — Per-source clients at the composition root + `--refresh` / `SWIMZH_CACHE`

- **Goal**: Wire the cache into the build so **each phase actually gets its own tier** (the B1 fix),
  off for the web runtime, with the refresh escape hatch — and prove the warm-cache no-network win.
- **Touches**: `cli.py` — build ONE `DiskCacheTransport` and wrap it in **one `HttpClient` per
  source** (`geo_sport` roster, `schedule_scraper`, `price_scraper`, `page_provider` discovery,
  `belegungsplan` lanes), threading the source-matched client into each **provider call**;
  `_compose_schedules`/`_attach_lanes` signatures each take two clients; `--refresh` flag.
  `apps/web/main.py` (cache `OFF`), `config.py`/env (`SWIMZH_CACHE=off|refresh`), `.gitignore`,
  `tests/test_cli.py`.
- **Acceptance**: (1) **the B1 guard** — an end-to-end build against a spy store records the
  `(url, tier)` of each request and asserts the WFS roster is stamped `static`, the schedule pages
  `snapshot`/12h, the discovery pages `page_provider`/7d, the PDFs `belegungsplan`/3d, the price page
  7d — i.e. **all five tiers are exercised in a real build** (fails if a single shared client, or one
  client per phase, collapses price-vs-schedule or discovery-vs-lanes). (2) A warm-cache build makes
  **zero** inner (network) calls (pre-seeded store + call-recording `MockTransport`, second run = 0).
  (3) `--refresh`/`SWIMZH_CACHE=refresh` forces a refetch; `SWIMZH_CACHE=off` is byte-identical to
  no-cache; the web app builds its client cache-`OFF`; the cache dir is git-ignored.
- **Note (NB3, no action):** a stadt-zuerich pool `url` fetched by BOTH `schedule_scraper` (snapshot)
  and `page_provider` (discovery, 7d) is stored twice — once per tier (tier is in the path, not the
  key). Duplicate storage + a double cold-fetch, not incorrectness; warm-cache-zero-network still
  holds since each phase reads its own tier's copy.
- **Depends on**: S3.

### S5 (optional) — `swimzh cache` subcommand + fixture bridge

- **Goal**: Ergonomics — inspect/clear from the CLI and one-way seed a fixture from a live entry.
- **Touches**: `cli.py` (`cache show <url-substring>` / `cache clear [--tier]` / `cache promote
  <url>`), tests.
- **Acceptance**: `cache show` prints a matching entry's URL + status + decoded body; `cache clear
  --tier snapshot` removes only that tier's dir; `cache promote` writes a fixture file from a live
  entry (no live re-record needed). Purely additive.
- **Depends on**: S4.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

- 2026-07-31 (pre-approval): owner chose a **custom JSON transport** over hishel 1.x after the
  research showed hishel 1.x stores an opaque msgpack (headers) + gzipped-chunk (body) SQLite blob —
  queryable for age/TTL but readable only via a shipped decode helper, defeating the plain-`cat`/`jq`
  inspectability that was a first-class requirement. hishel 0.x had JSON `FileStorage` but is EOL.
- 2026-07-31 (pre-approval review, plan-critic): **BLOCKING B1 fixed** — the tier TTL keys off
  `HttpClient.source`, but the build threads ONE `source="geo_sport"` client through every phase
  (`cli.py:428`), so all requests would collapse to the 14d tier and the volatility table was inert.
  Fix: the composition root now builds **per-source clients** over a shared `DiskCacheTransport`
  (S4), and S4 acceptance adds a **B1 guard** asserting a real build exercises >1 tier. Providers
  remain byte-unchanged. **Non-blocking fixed**: N1 the `DiskCacheTransport` clock is injectable
  (`now=`); N2 the buffer-only/no-`stream()` constraint stated; N3 all statuses incl. redirect hops
  are cached (keyed per-hop URL) so warm-cache-zero-network holds for redirecting pages; N4 the S5
  `cache promote` bridge is acknowledged as a deliberate one-way exception to cache/cassette
  separation (optional slice).
- 2026-07-31 (owner): body encoding is **text-by-default, base64 only when the response
  `Content-Type` is binary** (PDF/octet-stream/image) — NOT base64 for JSON/HTML/XML. Inspectability
  is the point; only the Belegungsplan PDFs get base64. UTF-8-decode failure is a safety fallback.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/`.
