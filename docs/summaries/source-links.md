---
type: summary
created: 2026-07-25
links: ["[[source-links]]", "[[2026-07-24-source-links-plan]]", "[[basin]]", "[[lane-plan-url-binding]]"]
---

# Source links — what exists now

The DetailPanel surfaces the **official sources** behind every pool as new-tab links, so a
swimmer can verify the answer (and pools where our data runs out still offer a one-tap path to
the truth). See the [[source-links]] concept for the conventions.

## API

- `GET /pools/{id}` → each `BasinOut` carries `lane_plan_url: str | None` — the basin's declared
  Belegungsplan PDF (`Basin.lane_plan_source.url`), `null` when none is declared. Mapped in
  `apps/web/api/pools/service.py::_basin_out`. Present after an offline `swimzh build` (it is
  curated input, not `scrape-lanes` output). `PriceTableOut.source_url` was already present.
- The official-page URL is **not** on the detail response. It is the catalog `url` →
  `PoolOut.url` on the `/pools` listing (non-null on all 57 pools). `FacilityDetailOut.website`
  is populated on only 2 pools and is unused here. `/pools/{id}` 404s for uncurated pools, so the
  listing URL is the only source that reaches every pool.

## UI

- `apps/web/static/js/components/sourcestrip.js` — `createSourceStrip(el, { props })`, props
  `{ officialUrl, lanePlanUrls: string[], pricesUrl }`. One `<a target="_blank"
  rel="noopener noreferrer">` chip per present URL, in order Official → Lane plan (PDF-tagged,
  one per distinct URL) → Prices. Deduped by exact-string URL across kinds (first wins), so a
  city pool whose prices page is its pool page shows one chip, not two. Absent URLs render no
  chip; an all-empty strip is a bare element with no group role (no empty screen-reader
  announcement). Icons via `iconset.js` (`external-link`, `doc`).
- `apps/web/static/js/blocks/detailpanel.js` mounts the strip near the ProvenanceStamp in every
  panel state (`lanes` / `lanes-unknown` / `closed` / `uncurated`). Lane-plan URLs = the selected
  basin's when a basin is open, else all basins'.
- `apps/web/static/js/app.js` builds `poolUrlByName` from the `/pools` listing and threads
  `officialUrl` through both `openPanel` call sites into `createDetailPanel`.
- `.ui-sourcestrip*` styles in `apps/web/static/components.css` (tokens only), with the chip
  anchor in the shared focus-visible ring.

## Not built (deliberate)

Board-row / all-pools-card `↗` shortcuts; the schedule `source_url`; per-section PDF
deep-linking (`section` stays domain-only). See the plan's Out of scope.
