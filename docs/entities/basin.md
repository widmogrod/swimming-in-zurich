---
type: entity
created: 2026-07-19
links: ["[[2026-07-19-rich-pool-domain]]"]
---

# Basin

Swimmable water within a facility — the unit that hosts `ResolvedSession`s and
carries schedule rules. Basins are NOT features (sauna/steam have no lanes or
swimmable water and live on `Facility.features` instead).

Physical attributes (kind, `Dimensions` in `Decimal`, lanes, nominal water
temperature) are partial by nature: most come from parsing free-text WFS
`infrastruktur` prose. `physical_source: BasinSource(CURATED | PARSED_PROSE)`
is the per-basin honesty signal — hand-verified vs auto-extracted. Missing
facts stay `None`; never assert completeness.

Invariants:
- `nominal_temp_c` is a design target, not a live measurement.
- Live occupancy never attaches to `Basin` (query-time only, never in gold).
