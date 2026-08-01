---
type: plan
status: in-progress      # draft -> approved -> in-progress -> done
created: 2026-08-01
feature: roster-url-scheme-normalization
branch: plan/roster-url-scheme-normalization
worktree: .claude/worktrees/plan-roster-url-scheme-normalization
base_branch: feat/new-ui
gates:
  qa: full               # ruff, ruff format, mypy strict, pytest+coverage, crap.py
  review: adversarial    # critic must find no blocking issues per slice
  max_rounds: 2          # revise/retry rounds per gate before a slice is blocked
pause_after: ["S2"]      # S2 needs live network and rewrites a committed data file
links: ["[[discovery-driven-providers]]", "[[data-layer-architecture]]", "[[source-links]]"]
---

# Roster URL scheme normalization — recover 15 outdoor pools from a dead TLS listener

## Context

The city's WFS roster publishes `url: https://www.sportamt.ch/<pool>` for **17 of 57** pools — 17 of
the 19 outdoor/lake/river ones (the other two, `freibad-dolder` and `seebad-enge`, are third-party
hosts). That host **has no TLS listener**: it accepts TCP on 443 and then sends nothing (ClientHello
written, 0 bytes read, clean EOF at ~5.1s). Verified 2026-08-01 across TLS 1.0–1.3, ±SNI, ±ALPN,
by-IP, apex hostname, `CERT_NONE`, `SECLEVEL=1`, under both LibreSSL-curl and Python/OpenSSL; Qualys
SSL Labs from an independent vantage reports `protocols: []`, `certChains: []`, "Unable to connect".
**No client configuration can fix it** — there is nothing to negotiate with.

Port 80 is healthy: `http://www.sportamt.ch/<pool>` → one `302` → `https://www.stadt-zuerich.ch/<pool>`
→ 200 in <1s with the real page (verified to contain *Öffnungszeiten* and *Preis*). So page discovery
fails for the 16 `https` pools today — a non-fatal `PageMiss` each, costing **~15.9s** (5.1s EOF × 3
attempts, since `ConnectionFailed` is `retriable()` and `RetryPolicy`'s default `sleep` is a no-op) ≈
**4 minutes of dead wait per build**. The [[provider-http-disk-cache]] cannot amortize it: failed
fetches are deliberately not cached. This plan normalizes the **scheme** so the existing
`follow_redirects=True` reaches the real pages. Outdoor pools are in scope for this project, so this
is a coverage gap, not merely a slow build.

**15, not 16.** `freibad-zwischen-den-hoelzern` carries a stale WFS slug: its url redirects to
`…/freibad-zwischen-hoelzern`, which **404s** (the live page is `…/freibad-zwischen-den-hoelzern`).
That pool keeps failing after this plan — but as a *fast* `HttpStatus(404)`, which `retriable()`
rejects, so one attempt instead of three. Fixing the slug means overriding a WFS-sourced value, which
is a different decision; out of scope here.

## Design (signature altitude)

**One seam: the WFS boundary mapping. Nothing downstream changes shape.**

- `providers/geo_sport.py` — the sole ingest point for this field is `url=feature.properties.www`
  (`_to_geo_pool`, :99). Introduce a private normalizer applied there:

  ```
  _normalize_roster_url(raw: str | None) -> str | None
  ```

  For a host **equal to** `sportamt.ch` or `www.sportamt.ch` (case-insensitive) with scheme `https`,
  return the same URL with scheme `http`. Every other URL is returned **byte-identical** — a targeted
  repair of one known-broken host, not a general scheme policy. Parse with `urllib.parse`
  (`urlsplit`/`urlunsplit`), never string surgery, so path/query/fragment survive and a host that
  merely *contains* the string (`sportamt.ch.example.com`) is not matched.

- **Layer choice: the provider, by preference not by force.** Both live paths funnel through
  `etl/catalog.build_catalog` (`etl/roster.py:41`, `cli.py:505`), so normalizing there would cover
  `build` and `build-catalog` equally — there is **no correctness discriminator**. The provider is
  chosen because that is where an external source is turned into typed domain data, and this is a
  defect in the external source. Trade-off accepted: the raw WFS value is **discarded**, not retained
  alongside the repaired one (see Decisions).

- **Why the scheme and not the host.** Rewriting to `www.stadt-zuerich.ch/<slug>` hardcodes a copy of
  the city's slug mapping; the 302 *is* that mapping, served live, so following it survives a CMS move
  and survives the city fixing TLS (the 302 would then point at the https form, which
  `follow_redirects` traverses). A host rewrite also puts an invented URL behind the user-visible
  "Official" link. Corroborating evidence that the upstream scheme is noise: **`seebad-katzensee` is
  already emitted as `http://`** while the other 16 are `https://`. And `freibad-zwischen-den-hoelzern`
  proves the slugs are not reliably rewritable anyway.

- `cli.py` — replace the flat `timeout=_LIVE_TIMEOUT_S` on the live client with an explicit
  `httpx.Timeout`, exposed through a **named, testable seam** (`live_timeout() -> httpx.Timeout`),
  since the client itself is built inline under `# pragma: no cover - live`. `HttpClient` never
  forwards `timeout_s` to `client.get` — it only labels `Timeout(after_s=…)` — so a client-level
  connect budget governs without touching that bookkeeping.

**Invariants.**
- Only `sportamt.ch` https URLs change; every other roster URL is byte-identical (asserted).
- The roster `url` is **not** an identity key and must not become one — two roster entries already
  share `https://www.sportamt.ch/flussbad-unterer-letten`.
- `ScheduleFreshness` is unaffected: `storage/codec.py:199-206` reads blob rules + `kind` only, and
  **never the URL**, despite docstrings describing the scrapeable set as "indoor *stadt-zuerich*".
- The one genuine host test on this field — `_CITY_HOST in entry.url` gating price attachment
  (`etl/scrape.py:120`) — is unreachable for all 17 (the loop `continue`s on `kind is not INDOOR` at
  `:106`; all 17 are outdoor/river/lake). A scheme change cannot flip it.
- **No new fatal path.** A `PageMiss` is a stderr audit line (`cli.py:395-400`) while a *discovered*
  lane source that fails is `fatal=True` (`cli.py:417-423`). Verified 2026-08-01: fetching **all 16**
  pages over the 302 and grepping a superset of `_BELEGUNGSPLAN_HREF` (`page_provider.py:40-43`, both
  quote styles, any `belegungsplaene` href) yields **0 matches on all 16** — outdoor pools have no
  lane plans, so no newly-reachable page can enter the fatal fetch-set.

## Out of scope

- Fixing the stale `freibad-zwischen-den-hoelzern` slug — that means overriding a WFS-sourced value,
  a different decision from repairing a scheme.
- Reporting the broken TLS to the city (worth doing; not code).
- Making the outdoor pools **scrapeable** (parsing their Öffnungszeiten/Preis into schedules). This
  plan restores reachability only; the pages demonstrably carry hours and prices, which makes a
  follow-up plan worth writing, but `scrape_indoor_facilities`' `INDOOR` guard is untouched here.
- The ~57-page **lane-discovery scope bug**. Fixing the URLs makes it cheaper, not correct.
- A general URL-normalization policy for all providers. Targeted repair only.
- Retiring `Facility.website` — dead plumbing with no producer since the curated tier was deleted.
- Reusing `live_timeout()` in `apps/web/main.py:68`, which builds its own live client with the same
  flat `timeout=_HTTP_TIMEOUT_S`. Seen and deliberately left alone — the obvious follow-up once the
  seam exists.

## Slices

### S1 — Normalize the scheme at the WFS boundary, offline, with the field finally under test

- **Goal**: `parse_pools` emits a reachable URL for the sportamt pools and a byte-identical URL for
  everyone else — proven by tests, since **no test asserts this field today**.
- **Touches**: `src/swimzh/providers/geo_sport.py` (`_normalize_roster_url` + its use in
  `_to_geo_pool`); a provider-level test over `tests/providers/fixtures/wfs/*.json`;
  `src/swimzh/etl/field_sourcing.py:211-215` (its `facility.website` note describes the WFS `www` as
  the "official pool page URL" — correct the wording now that it is repaired on the way in).
- **Acceptance** (all offline, driven through `parse_pools` with crafted FeatureCollections rather
  than by calling the private helper, to stay clear of the tracked `reportPrivateUsage` debt): every
  `sportamt.ch` entry is emitted with scheme `http` and an otherwise unchanged URL (path/query/
  fragment preserved); every non-sportamt entry is byte-identical to today's value, asserted over the
  **full** fixture set, not a sample; an already-`http://` sportamt URL is unchanged; a `None` url
  stays `None`; `WWW.SportAmt.CH` normalizes; `sportamt.ch.example.com` is **not** rewritten.
  **Does NOT touch `tests/providers/test_roster.py`** — that test compares the cassette against
  `data/catalog.json`, which still holds the old values until S2 (see Decisions, B1).
- **Depends on**: —

### S2 — Re-snapshot `data/catalog.json` and put the golden roster test on `url`

- **Goal**: make the committed WFS snapshot agree with the normalizer, and close the hole that let
  this field change unnoticed.
- **Touches**: `data/catalog.json` (regenerated via `swimzh build-catalog`),
  `tests/providers/test_roster.py` (add `url` to the golden comparison, which currently projects it
  away at :44-59), `data/sources.md`, and the "`data/catalog.json` IS a WFS snapshot" docstrings in
  `storage/catalog_json.py:5-7` + `tests/providers/test_roster.py:1-4` (it is now a *repaired*
  snapshot — say so).
- **Acceptance**: the regenerated snapshot has all 17 sportamt entries on `http://`; the diff carries
  **no** non-url change beyond the regeneration timestamp, gated mechanically —
  `git diff -U0 data/catalog.json | grep '^[+-]' | grep -Ev '^(\+\+\+|---)' | grep -v '"generated_at"'
  | grep -v '"url"'` must be **empty** — if the live WFS has
  drifted (a renamed pool, moved coordinates), **STOP and report** rather than absorbing it silently,
  since the golden test compares the old cassette against the new snapshot and would need the cassette
  re-recorded as a separate decision; the golden roster test now includes `url` and passes;
  `data/sources.md` records that these fetches traverse one plaintext hop before the 302 to https, and
  why that is accepted for public pool pages carrying no credentials.
- **Requires live network.** If the WFS is unreachable, report — never hand-edit the snapshot.
- **Depends on**: S1.

### S3 — Granular connect timeout

- **Goal**: bound what any silently-blackholing host can cost a build, independent of this fix.
- **Touches**: `src/swimzh/cli.py` (a new `live_timeout() -> httpx.Timeout` seam + its use at the
  live-client construction, `:652-653`), `tests/test_cli.py`.
- **Acceptance** (**fully offline** — this slice runs unattended after the `pause_after: ["S2"]` gate,
  so it must need no network): `live_timeout()` returns an `httpx.Timeout` with `connect=5.0` and
  read/write/pool at the existing `_LIVE_TIMEOUT_S` (30.0), asserted directly on the factory's return
  value — the client itself is built under `# pragma: no cover - live`, so assert the seam, not the
  client (the same lesson as [[provider-http-disk-cache]]'s S4); existing timeout classification
  (`Timeout`/`ConnectionFailed` → `ProviderError`, both retriable) is unchanged. The headroom
  measurements are already taken (see Decisions) — do **not** re-measure.
- **Depends on**: — (independent; ordered last as the least risky)

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-08-01 | S1 | done | `_normalize_roster_url` also returns `raw` unchanged when `urlsplit`/`.hostname` raises `ValueError` (malformed URL) — unnamed in the plan, but `www` is untrusted upstream text and `parse_pools` maps only `JSONDecodeError`/`ValidationError`, so a raw `ValueError` would escape the provider boundary and break errors-as-values | none | yes |

## Decisions & divergences

- 2026-08-01 (investigation): **no client configuration can make HTTPS work** — every TLS variant
  reads 0 bytes and EOFs at ~5.1s under both LibreSSL and OpenSSL; SSL Labs independently reports no
  protocols and no cert chain. Rewriting the URL is the only lever. **Could not determine** from two
  vantage points whether the silence is universal or scoped to certain source networks.
- 2026-08-01 (investigation): chose **scheme normalization over host rewriting** — the 302 is the
  city's live slug mapping, so following it survives CMS moves and a future TLS fix, while a host
  rewrite hardcodes a copy that fails silently behind a user-visible "Official" link.
- 2026-08-01 (audit): the roster `url` is **user-visible** (`/pools` → `PoolOut.url` → the "Official"
  chip, whose aria-label speaks the host), is **persisted** as the `pool.url` column (not in
  `facility_doc`), and is **protected by no test at all** — the golden roster test projects it away
  and the API test asserts only non-nullness (`apps/web/tests/api/test_pools.py:55`). Either candidate
  rewrite would have shipped green through the entire QA chain.
- 2026-08-01 (pre-approval review, plan-critic): **B1 fixed** — S1 originally added `url` to the
  golden roster test while the snapshot regeneration sat in a later slice. That test compares the
  cassette (17 sportamt urls) against `data/catalog.json` (16 on `https`), so S1 would have failed its
  own pytest gate on 16 pools. The golden-test change and the snapshot regeneration are now the **same
  slice** (S2); S1 pins the field offline over the WFS fixtures instead.
- 2026-08-01 (pre-approval review, plan-critic): **B2 fixed** — S3 named a `live_clients` seam that
  does not exist (only `live_transport`, `cli.py:153`; the client is built inline under a live
  pragma), making its criterion unassertable. S3 now introduces `live_timeout()` explicitly.
- 2026-08-01 (pre-approval review, plan-critic): **B3 fixed** — the plan claimed all 16 pools recover.
  Verified live: `freibad-zwischen-den-hoelzern`'s WFS slug is stale and its redirect target **404s**.
  Title, Context and scope now say **15**, and the residual is recorded as a fast non-retriable
  `HttpStatus(404)` miss that stays non-fatal.
- 2026-08-01 (pre-approval review, plan-critic): **B4 fixed** — the snapshot slice was justified by
  "`build` and `scrape-gold` would fetch different URLs", which is **false**: `scrape-gold` reaches
  these pools only through `scrape_indoor_facilities`, which skips every non-INDOOR entry
  (`etl/scrape.py:106`), and all 17 are outdoor/river/lake. S2's real justification is the golden test
  plus snapshot honesty. The "why the provider and not the ETL layer" argument was likewise a
  non-discriminator (both paths funnel through `build_catalog`) and is now stated as a **preference
  with its trade-off named**, not a correctness claim.
- 2026-08-01 (pre-approval review, plan-critic): the old S2 ("prove discovery recovers") is **folded
  into S1's invariant**. The critic fetched **all 16** pages and found **0** Belegungsplan hrefs on
  every one, closing the original 6-of-16 sample gap; a slice whose deliverable was "possibly" a
  change to audit output was not vertical.
- 2026-08-01 (pre-approval review, measurements taken so S3 needs no network): TCP-connect / TLS
  times for every real host are ~125× inside the 5.0s budget — `www.ogd.stadt-zuerich.ch`
  0.019s/0.038s, `www.stadt-zuerich.ch` 0.013s/0.032s, `www.bad-altstetten.ch` 0.020s (http, 301).
  Those are **three** hosts, not four: the Belegungsplan PDFs live on `www.stadt-zuerich.ch/content/dam/…`,
  the same host as the pool pages. **5.0s was chosen over 3.0s** because a schedule-page connect
  failure is *fatal* (`cli.py:268-276`), so the budget must not be the thing that breaks a build.
- 2026-08-01 (scope boundary, pre-existing): the "no new fatal path" invariant is verified as of this
  date and holds because a discovered link that *fetches and parses* merely lands in the audited
  `UnboundPlan` stream — only a fetch/parse **failure** is fatal (`cli.py:417-423`). That exposure
  already exists for all 37 stadt-zuerich pages and belongs to the lane-discovery scope bug, not here.
- 2026-08-01 (S1): the host match is **exact, against a frozenset of `urlsplit(...).hostname.lower()`**,
  never a substring — verified that `sportamt.ch.example.com`, `notsportamt.ch`, `evil-sportamt.ch`,
  a trailing-dot host and a schemeless URL are all left unchanged, while the apex and
  `HTTPS://WWW.SportAmt.CH` are repaired. A userinfo form (`https://user@www.sportamt.ch/x`) matches
  on host only and cannot be spoofed by an `@`-prefixed authority. A substring match here would have
  been a security-adjacent defect.
- 2026-08-01 (S1, obligation carried into S2): the committed WFS fixtures hold **16** `https` sportamt
  entries + 1 already-`http` (`seebad-katzensee`) = 17, and the snapshot test pins that `16` as a
  literal. S2's regeneration must keep the count consistent or update the assertion. The test's oracle
  also branches on the `https://www.sportamt.ch/` prefix, so an apex or case-variant entry appearing
  after regeneration fails **loudly**, not silently.
- 2026-08-01 (S1, noted — pre-existing, not introduced): `field_sourcing.py`'s `facility.website` row
  claims the WFS `www` as its source, but that field's only producer was the deleted curated tier;
  the WFS `www` actually lands on `GeoPool.url` → the `pool.url` column. The row was already
  inaccurate before this slice. Resolve when `Facility.website` is retired (out of scope here).
- 2026-08-01: **the raw WFS value is discarded, deliberately.** `GeoPool` gains no
  raw-vs-repaired provenance field — a tri-state would be gold-plating in a plan that otherwise
  repairs one host. The consequence is that nothing downstream can report what the city actually
  published; `data/sources.md` carries that note instead (S2).

## Summary

Written when the plan reaches `done`; then distilled into
`docs/summaries/roster-url-scheme-normalization.md` (what EXISTS now, not what was intended).
