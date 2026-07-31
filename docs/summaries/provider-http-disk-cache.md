---
type: summary
feature: provider-http-disk-cache
status: done
created: 2026-08-01
links: ["[[data-layer-architecture]]", "[[discovery-driven-providers]]", "[[gold-store]]"]
---

# Provider HTTP disk cache — inspectable JSON entries, per-tier TTL, behind a transport

**What & why.** `swimzh build` is network-bound — it serially refetched the WFS roster, ~57 pool
pages, the Belegungsplan PDFs and the tariff page on every run (a cold build measured **>9 min**,
killed before completing). There was no on-disk cache, and no easy way to see *what a provider's
source actually returned*. Now every provider response caches to disk with a per-tier TTL, so a
re-run hits the network only when an entry is stale, and a warm build is near-instant.

## What exists now

- **`core/httpcache.py`** — `CacheStore` (pure, no httpx transport, no network): key derivation
  `sha256(method + url)[:16]`, the path scheme, the JSON (de)serialization, TTL freshness. Plus
  `DiskCacheTransport(inner, store, mode, *, now)` with `CacheMode = USE | REFRESH | OFF` — the clock
  is **injected**, so freshness is deterministic in tests.
- **`core/cache_tiers.py`** — the whole volatility policy in one table, keyed off `HttpClient.source`:
  `geo_sport` 14d, `page_provider` 7d, `price_scraper` 7d, `belegungsplan` 3d, `schedule_scraper` 12h,
  `baditicker` 2m. The tier is a closed `Literal`, not a `str`.
- **`HttpClient.get`** stamps `cache_tier` + `cache_ttl_s` onto `request.extensions` from its
  `source=`, merging into (never overwriting) a caller's own extensions.
- **`cli.py`** builds ONE `DiskCacheTransport` and wraps it in **one `HttpClient` per source**;
  `--refresh` / `SWIMZH_CACHE=off|refresh` drive the mode. **`apps/web/main.py`** wires the cache
  `OFF` (Baditicker has its own in-process 2-min TTL) and reads no env of its own.
- On disk: `.cache/swimzh/<tier>/<host>/<key16>.json`, git-ignored. Body is **inline readable text**
  for text content-types (`cat`/`jq` the WFS GeoJSON, the pool pages, the tariff page); base64 only
  for a binary content-type (the Belegungsplan PDFs) or as a UTF-8-decode safety fallback.

## The four things worth remembering

1. **A transport is the only seam that keeps providers honest.** `HttpClient`'s public API and all
   five providers are byte-unchanged; a test greps `src/swimzh/providers/*.py` for any mention of the
   cache and fails if one appears.
2. **httpx decodes response bodies ABOVE the transport.** Storing `response.content` under verbatim
   headers writes decoded bytes under `content-encoding: gzip`; rebuilding then runs the header-driven
   decoder and raises `DecodingError`. Since httpx sends `Accept-Encoding: gzip, deflate` by default,
   this would have turned essentially **every** warm hit into an `Err(DecodeError)`. The store strips
   `content-encoding`/`content-length`/`transfer-encoding` on **both** write and read.
3. **The tier granularity is the provider call, not the phase.** TTL keys off `HttpClient.source`, and
   the build used to thread ONE `source="geo_sport"` client everywhere — which would have collapsed
   every request to the 14d tier and made the volatility table inert (the pre-approval B1 finding).
   `_compose_schedules` fans out to price *and* schedule, `_attach_lanes` to discovery *and* lanes, so
   each takes **two** clients. The build-level guard asserts all five `(source, tier, ttl)` triples
   plus the URL set behind each stamp — and classifies each request by **URL shape alone**, never by
   the stamp it is checking, or it would prove nothing.
4. **A composition root that cannot be constructed in a test is not wired, it is asserted.** The
   `--refresh`/`SWIMZH_CACHE` → `CacheMode` → transport join sat behind `if clients is None` (every
   test injects clients) *and* a `# pragma: no cover - live`, so hardcoding `CacheMode.USE` left the
   whole suite green while `--refresh` became a silent production no-op. It is now the testable
   factory `live_transport(...)`, with the pragma scoped to the `httpx.Client` block alone.

## Boundaries and carried debt

The cache is a **dev/build accelerator**: git-ignored, TTL-driven, and neither a runtime source of
truth (the gold DB remains that) nor the test-fixture store (the `vcrpy` cassettes stay the
checked-in, `block_network` contract). RFC 9111 revalidation, `Vary`, and async are all non-goals.

- Buffer-only: `client.stream(...)` is **defeated, not broken** — it still yields the full body in the
  requested chunk sizes, but every byte is buffered first. Nothing in this repo streams.
- `SWIMZH_CACHE=off` is identical to no-cache at the level of **response bytes**, not client
  construction: passing an explicit `transport=` disables httpx's env proxy mounts, so
  `HTTP(S)_PROXY` is no longer honoured. Recorded, not fixed — nothing here uses a proxy.
- An oversized response (over `HttpClient(max_bytes=…)`) is written to disk *before* `_classify`
  rejects it, so it replays as `TooLarge` for its whole TTL. Accepted; `--refresh` clears it.
- The guard cannot separate `price_scraper` from `page_provider` while they share `static`/7d — split
  the assertion if those TTLs ever diverge.
- A stadt-zuerich pool page fetched by both `schedule_scraper` (snapshot) and `page_provider` (static)
  is stored **twice**, once per tier. Duplicate storage, not incorrectness.
- The ~57-page **lane-discovery scope bug** (discovery fetches every roster pool, not just the 6 with
  a `lane_plan_source`) is only *mitigated* by a warm cache. Still open, filed separately.

`swimzh cache show/clear/promote` (S5) was **not built** — inspection is `cat`/`jq`/`find
.cache/swimzh` and clearing is `rm -rf`. See [[2026-07-31-provider-http-disk-cache-plan]] for the
ledger and the full decision record.
