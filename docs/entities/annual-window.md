---
type: entity
name: annual-window
created: 2026-08-06
links: ["[[2026-08-06-seasonal-hours-plan]]", "[[basin]]"]
---

# AnnualWindow

A yearly-recurring date window — *"30. Mai–16. August"*, *"Mai bis September"* — carried on a
`ScheduleRule` as its `season`. `contains(d)` ignores the year, so a window whose `start` is
after its `end` wraps New Year (`Oktober–April`).

**Year-free by construction.** Zürich publishes the year exactly once per page, in a heading
(`Öffnungszeiten 2026`) whose position in the DOM varies, and never inside a `Zeitraum` cell.
A year-bound range would go quietly wrong the moment the season rolled over; a year-free one
resolves correctly next year, and the scraped year is kept as provenance rather than as a
bound. The cost is that a genuinely changed window looks current until the next build — which
is why `Provenance.fetched_at` matters more once seasons exist.

**`precision` is not decoration.** `"30. Mai–16. August"` is day-precise; *"von Mai bis
September"* is month-granular. The window records which kind it is.

The prohibition is on **rendering**, not on resolving: `contains` treats a `MONTH` window as
whole months inclusive (1 May through 30 September), because a date either falls inside those
months or it does not and that judgement needs no invented precision. What callers may not do
is *display* a `MONTH` window as "1 May – 30 September", which states two days the city never
published. Show the months.

A rule with no season is in force all year — the default, and what every indoor rule stays.
When *every* rule on a basin carries a season and none contains the queried date, the day
resolves to `ClosureCode.SEASONAL_BREAK`, not `NO_SESSIONS`: "shut for the winter" and
"nothing scheduled this weekday" are different sentences, and only one of them is true of a
lido in October.

Sits alongside `Weather` (`ANY | FAIR_ONLY`), which answers a different question — *under
what condition* rather than *when* — and rides on the resolved session rather than the day,
because the all-weather and fair-weather windows are adjacent and additive: part of the day
is certain even when the rest is not.
