---
type: concept
created: 2026-07-24
links: ["[[basin]]", "[[lane-plan-url-binding]]", "[[2026-07-24-source-links-plan]]"]
---

# Outbound source links ("verify at the source")

The UI surfaces the **official sources** behind every answer so a swimmer can verify it, and so
pools where our own data runs out (uncurated / closed) still offer a one-tap path to the truth.
Three URLs, all already in the store: the pool's official page (the catalog **`url`**, on all 57
pools → `PoolOut.url` on the `/pools` listing — **not** `FacilityDetailOut.website`, which only 2
pools declare), the original Belegungsplan PDF per basin (`Basin.lane_plan_source.url` — see
[[basin]] and [[lane-plan-url-binding]]), and the tariff page (`PriceTable.source_url`). Because
`/pools/{id}` 404s for uncurated pools, the official-page URL is threaded into the DetailPanel
from the listing (frontend-side), which is the only source that reaches every pool.

Conventions for any outbound source link:

- **New tab, safely**: `<a target="_blank" rel="noopener noreferrer">` — never navigate away
  from the swimmer's session.
- **Name the destination**: a trailing `↗` glyph and an `aria-label` that states the label and
  "opens in a new tab"; PDF sources carry a visible "PDF" marker so a tap is never a surprise
  download.
- **Honest omission**: a source with no URL renders **no** chip (never a dead link); when a pool
  has no sources at all, the strip renders nothing rather than an empty container.
- **Provenance is actionable**: the ProvenanceStamp's "read from the pool's website" is the same
  promise this affordance keeps.

Deliberately excluded (see the plan): board-row / card shortcuts, the schedule `source_url`
(redundant with the official page), and per-section PDF deep-linking (`section` is a sheet token,
not a URL fragment).
