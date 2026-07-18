---
type: entity
created: 2026-07-19
links: ["[[2026-07-19-rich-pool-domain]]", "[[basin]]"]
---

# Feature

A non-swim amenity on a `Facility` — sauna, steam bath, wellness, slide, hot
tub. Deliberately NOT a `BasinKind`: features can't host swim sessions, and
folding them into basins would leak non-swim rows into `find_swim_options`.

`hours` reuses `ScheduleRule`, so "is the sauna open now?" resolves through
the existing resolver. May carry a surcharge (`Eintritt Fr. 10.-`) and a
temperature.
