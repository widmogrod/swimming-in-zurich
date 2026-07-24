---
type: plan
status: approved         # draft -> approved -> in-progress -> done
created: 2026-07-24
feature: source-links
gates:
  qa: full               # ruff, mypy, pytest+coverage, CRAP (run in that order)
  review: adversarial    # dev:critic-reviewer must find no blocking issues
pause_after: [S1]        # verify the API contract before the UI is built on it
links: ["[[source-links]]", "[[basin]]", "[[lane-plan-url-binding]]"]
---

# Outbound source links — "Verify at the source"

## Context

The UI answers "where can I swim now?" but never lets a swimmer reach the **official
source**: the pool's stadt-zuerich.ch page, the original Belegungsplan (lane-plan) PDF, or
the tariff page. Every one of these URLs already exists in the data — the catalog **`url`**
(present on **all 57** pools, reaching the frontend as `PoolOut.url` on the `/pools` listing
the app already fetches), `Basin.lane_plan_source.url` (the authored PDF source, present after
an offline `swimzh build`), and `PriceTable.source_url` (on the `/pools/{id}` detail). The
official-page URL already reaches the browser and is dropped; the lane-plan URL is in the
domain but not projected. This plan surfaces all three as an on-brand **"verify at the source"**
affordance in the DetailPanel.

**Correction (pre-approval review):** the official-page URL is the catalog `url` on the
listing, **not** `FacilityDetailOut.website`. `website` is populated on only **2** of 57 pools
(`data/pools/aemtler.yaml`, `city.yaml`) and is `null` for the rest (oerlikon included), and
`/pools/{id}` **404s for uncurated pools**, so a detail-response projection would never reach
them. Sourcing the official page from the listing `PoolOut.url` (threaded into the panel
frontend-side) is the only approach that covers all pools — see Decisions.

This builds on [[basin]] (the `lane_plan_source` attribute) and the URL-binding work in
[[lane-plan-url-binding]], and introduces the [[source-links]] concept (outbound-link
conventions: new-tab semantics, PDF labelling, honest omission). It reinforces the app's
existing honesty story — the ProvenanceStamp already *says* "read from the pool's website";
this makes that phrase actionable and gives uncurated / closed pools (where our own data runs
out) a one-tap path to the truth.

## Design (signature altitude)

**Backend — project the lane-plan URL (`apps/web/api/pools/`):**

- `BasinOut` gains one field: `lane_plan_url: str | None` (the basin's declared
  `lane_plan_source.url`; `None` when the basin declares none). The `section` token stays in
  the domain — it is a sheet sub-section, not a URL fragment, so it has no UI use here.
- `_basin_out(basin)` reads `basin.lane_plan_source.url if basin.lane_plan_source else None`.
- `PriceTableOut.source_url` is **already present** — no change. `FacilityDetailOut.website`
  is **not used** (see Correction). S1 only adds the lane-plan URL.

**Frontend — the official-page URL comes from the listing, not the detail:**

- `app.js` already fetches `/pools` into `poolsMeta` (line ~464) and builds `poolIdByName`. Add
  a `poolUrlByName: Map<name, url>` (or `-ById`) from the same `poolsMeta`; `PoolOut.url` is
  non-null on all 57 pools. Thread the resolved URL into `openPanel(...)` at **both** call
  sites (the curated-row branch and the closed/uncurated-row branch) as `officialUrl`, and pass
  it through to `createDetailPanel`. This reaches **uncurated** pools too, whose `/pools/{id}`
  detail 404s (`detail = null`).

**Frontend — a SourceStrip component wired into the DetailPanel:**

- `createSourceStrip(el, { props }) → { el }` — a new **component** (peer of
  `provenancestamp.js`), matching the existing component signature. `props`:
  `{ officialUrl, lanePlanUrls: string[], pricesUrl }` (any subset may be null/empty).
- It renders one chip per **present** URL. Each chip is
  `<a target="_blank" rel="noopener noreferrer">` with an icon, a label, a trailing `↗`, and
  `aria-label="<label> — opens <host> in a new tab"`. A source whose URL is null renders **no
  chip**; when no source is present the strip renders **nothing** (no empty container).
- Chip set + order: **Official page** (`officialUrl`), **Lane plan PDF** (one chip per distinct
  `lanePlanUrls` entry), **Prices** (`pricesUrl`). PDF chips carry a small "PDF" tag so a tap is
  never a surprise download. **Chips dedup by URL across kinds** (plain exact-string equality —
  no trailing-slash/case normalization), keeping the first in that priority order — for most
  city pools `prices.source_url` equals the pool page, so Prices collapses into Official rather
  than duplicating it.
- `detailpanel.js` builds `props` from `opts.officialUrl`, the basins' `lane_plan_url` (the
  selected basin's URL when a basin is selected, else **all** basins' URLs — so a curated panel
  opened on one basin shows that basin's PDF, while a basin-less mount shows every basin's), and
  `detail.prices.source_url`, then
  mounts the strip near the ProvenanceStamp. The strip is built in **every** panel state
  (`lanes` / `lanes-unknown` / `closed` / `uncurated`) — an uncurated pool still shows its
  Official-page chip.

**Icons:** add `external-link` (and a `document`/PDF glyph) to `components/iconset.js`
(`iconSvg`), reusing the existing inline-SVG mechanism; no new icon system.

## Out of scope

- **Board-row and all-pools-card `↗` shortcuts.** A nice follow-up, but the DetailPanel opens
  for every pool, so it fully satisfies "open the official page + availability pages." Deferred
  to avoid gold-plating.
- **The schedule `source_url`** (authored on some timetables, e.g. `city.yaml`) — not projected
  today and redundant with the Official-page link. Excluded.
- **`FacilityDetailOut.website`.** Populated on only 2 of 57 pools and redundant with the catalog
  `url` for those; the official-page chip uses the listing `PoolOut.url` uniformly. Not touched.
- **Per-section PDF deep-linking.** `lane_plan_source.section` is a sheet token, not a URL
  fragment; no per-basin deep link is possible, so `section` is not surfaced.
- **Any domain / gold-store / builder change.** All URLs already exist in the store; this is a
  projection (lane-plan URL) + presentation change only.

## Slices

### S1 — Project the lane-plan source URL onto `/pools/{id}`

- **Goal**: `GET /pools/{id}` returns each basin's declared Belegungsplan PDF URL alongside the
  already-present `prices.source_url`.
- **Touches**:
  - `apps/web/api/pools/model.py` — `BasinOut.lane_plan_url: str | None`.
  - `apps/web/api/pools/service.py` — `_basin_out` maps `basin.lane_plan_source`.
  - `apps/web/tests/fixtures/pool_oerlikon.json` — regenerate so basins carry `lane_plan_url`
    (the frontend fixture the JS tests load).
  - `apps/web/tests/api/test_pools.py` (or `test_detail_preview.py`) — new assertions.
- **Acceptance**:
  - For a curated pool with declared lane sources (oerlikon: 2 basins, each a **distinct** PDF —
    `oerlikon-schwimmerbecken.pdf` and `oerlikon-nichtschwimmer-sprungbecken.pdf`), the detail
    response’s basins carry the exact `lane_plan_url` from the YAML; a basin with no
    `lane_plan_source` returns `lane_plan_url == null`.
  - The same response’s `prices.source_url` is non-null (regression guard that the price source
    still reaches the boundary). The official-page URL is a listing concern (`PoolOut.url`) and
    is asserted in S2, not here — S1 makes no `website` claim.
  - Test runs against the **real offline-built gold store** (the `gold_db` conftest fixture,
    `build_store(DATA_DIR, db)`), proving the URL is present after `swimzh build` alone — no
    `scrape-lanes` needed.
  - Full QA chain green (ruff, mypy, pytest+coverage, CRAP).
- **Depends on**: —

### S2 — SourceStrip component, wired into the DetailPanel

- **Goal**: the DetailPanel shows a "Sources" strip of new-tab links (Official page · Lane plan
  PDF · Prices) for every pool, in every state.
- **Touches**:
  - `apps/web/static/js/components/sourcestrip.js` (new) + `sourcestrip.test.js` (new).
  - `apps/web/static/js/components/iconset.js` — add `external-link` + document glyph.
  - `apps/web/static/js/app.js` — `poolUrlByName` from `poolsMeta`; thread `officialUrl` through
    both `openPanel` call sites into `createDetailPanel`.
  - `apps/web/static/js/blocks/detailpanel.js` — build props (incl. `opts.officialUrl`), mount
    the strip near the ProvenanceStamp; `detailpanel.test.js` — integration assertions.
  - `apps/web/static/components.css` — `.ui-sourcestrip` styles (tokens only, no raw hex),
    matching `.ui-provstamp` / `.ui-chip`.
- **Acceptance** (checkable via `node --test`, run through `apps/web/tests/test_static_js.py`):
  - Given three distinct URLs, the strip renders 3 chips, each an `<a>` with
    `target="_blank"`, `rel` containing `noopener` and `noreferrer`, an `href` equal to the
    input URL, and an `aria-label` naming the destination and "new tab".
  - A null `officialUrl` / null `pricesUrl` / empty `lanePlanUrls` each drops **only** its own
    chip; all-empty props render an element with **no** chips (no dead links).
  - Two `lanePlanUrls` entries with the same URL produce **one** Lane-plan chip; a `pricesUrl`
    equal to `officialUrl` collapses into the Official chip (dedup by resolved URL across kinds).
  - PDF chips (lane plan) carry a "PDF" marker in their text/label.
  - Panel integration: mounting `createDetailPanel` with the oerlikon fixture, `officialUrl`
    set, and **no selected basin** yields a strip with the Official-page link and both Lane-plan
    links (oerlikon’s two PDFs are distinct → two chips, the "all basins'" branch); mounting the
    same fixture **with** a selected basin yields exactly that basin's one Lane-plan chip;
    mounting an **uncurated**-state panel with `detail = {}` and `officialUrl` set yields exactly
    the Official-page chip.
  - Full QA chain green.
- **Depends on**: S1 (for the lane-plan URL; Official-page and Prices chips need no backend).

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|

## Decisions & divergences

Substantive choices made during implementation, with the why. Each entry dated.

- **2026-07-24 — pre-approval review (plan-critic).** The original draft claimed the
  official-page URL was `Facility.website` "stamped from the WFS catalog onto all ~57 pools."
  False: `data/catalog.json` entries carry `url` (0 carry `website`); `Facility.website` is
  composed only from the curated YAML `website:` aspect and is declared by just 2 pools
  (`aemtler`, `city`) — `null` for oerlikon and 53 others. It reaches the frontend as
  `FacilityDetailOut.website` (`null` in the real `pool_oerlikon.json` capture), whereas the
  catalog `url` reaches `PoolOut.url` on the `/pools` listing (non-null on all 57).
  Additionally, `/pools/{id}` **404s for uncurated pools** (`router.py`), so `app.js` opens
  their panel with `detail = null` — a `FacilityDetailOut` projection could never give them an
  official-page chip. **Change:** source the official-page chip from the listing `PoolOut.url`,
  threaded into the panel by `app.js` (frontend-only, covers all pools incl. uncurated); drop
  `FacilityDetailOut.website` from scope; remove the unsatisfiable "non-null website"
  acceptance criterion; add cross-kind URL dedup (city pools' `prices.source_url` equals the
  pool page). All other critic-verified facts held.

## Summary

Written when the plan reaches `done`; then distilled into `docs/summaries/source-links.md`
(what EXISTS now, not what was intended).
