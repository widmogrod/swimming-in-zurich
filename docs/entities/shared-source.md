---
type: entity
name: shared-source
created: 2026-08-08
links: ["[[2026-08-08-sharedsource-fanout-plan]]", "[[annual-window]]", "[[admission]]", "[[discovery-driven-providers]]"]
---

# SharedSource

A page that describes a **set** of pools rather than one — the counterpart to a declared source.
`declared_sources` requires an unshared URL precisely because a shared one is an overview, not a
pool's page; a `SharedSource` is the case where that overview nevertheless states extractable
facts, **once, for all its members**: the Planschbecken page's *"je nach Wetter von Mai bis
September in Betrieb … kostenlos"* is a season, a weather condition, and free admission for
thirteen pools in one sentence.

The construct is `url + members + parser`: the member set is the roster entries sharing the URL,
and admission into the phase is **by parser registry, never by URL-sharing alone** —
`hallenbaeder.html` is shared by 14 school pools and names zero of them, so it has no parser and
its pools stay honestly `no_source`. Fail-fast fails **once** per shared page, not once per
member; that asymmetry is what made shared URLs dangerous to admit before this construct existed.

**Fan-out facts are page-level only.** The measured reason: a per-pool join against the page's
accordions fails on 2 of 13 names (roster *Josefswiese* vs page *Josefwiese* — the page is right;
*Föhrenwald* has no accordion at all), and what the join would buy is a one-line blurb for a
deleted field. Facts that are stated once apply to every member; facts stated per-member are out
of scope by construction.

Carries `OperatingSeason` (`window: AnnualWindow` + `weather: Weather`) onto the facility — the
seat for *a season with no timetable*, which `ScheduleRule` cannot hold (it requires a
`TimeRange`) — and `Admission.Free` from [[admission]]. The resolver's third day-state,
`OpenUnscheduledDay`, is what makes the season answerable: *open today, weather permitting, hours
not published* — a true sentence the model previously had no way to say.
