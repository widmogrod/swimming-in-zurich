---
type: concept
name: discovery-driven-providers
status: proposed   # direction set 2026-07-28; not yet built. Supersedes parts of the sourcing stance.
created: 2026-07-28
updated: 2026-07-28
links: ["[[lane-plan-url-binding]]", "[[data-layer-architecture]]", "[[source-links]]", "[[lane-data-availability]]", "[[gold-store]]", "[[2026-07-28-website-sourced-providers-plan]]"]
---

# Discovery-driven providers — every fact from a source, links discovered not curated, fail-fast

> **Status: proposed.** This records an owner decision (2026-07-28) about how the ETL should
> source data. It is *not yet built*, and it deliberately overrides parts of the as-built
> design below (`lane_plan_source` as curated YAML input; the Altstetten "out of scope" punt;
> the best-effort skip-and-continue posture). Where prose here and elsewhere conflict, this is
> the intended direction and the older text is the current implementation.

## The rules

1. **Every fact originates from a source website via a provider — even low-volatility facts.**
   Basin `kind`, eligibility rules, the pool roster/identity: if it is in gold, a provider
   extracted it from a source. Hand-authored YAML is **not** a source of truth — it goes stale
   and its origin is unknowable. (ToS is not a constraint on what may be sourced.)

2. **Providers are chained by discovery.** A provider extracts not only *facts* but *links to
   sub-resources* — a Belegungsplan, an availability grid, a reservation endpoint. Those
   discovered links become the **fetch-set (inputs) of the next provider**. No stage hardcodes
   URLs; each stage's inputs are a *projection of the previous stage's output*, recursively.
   Because links are re-derived every run, they cannot rot or have "unknown origin" — the
   origin *is* the upstream extraction.

3. **Providers are independent and per-cadence.** A slow-changing "structure" provider may run
   on a monthly schedule while a schedule/availability/occupancy provider runs hourly. Design
   for independent scheduling now; build later.

4. **Fail-fast; silent crash is not allowed.** A provider that cannot produce a *declared* or
   *discovered* fact makes its run go **red / non-zero**. Errors-as-values is fine *iff* the
   error is surfaced to a non-zero exit — what is banned is **skip-and-continue-green**, a run
   that exits 0 with a hole.

## How discovery chaining works

```
pool page provider ──► facts + discovered links {availability@X, belegungsplan@Y, reservation@Z}
        │                         │
        │ (fetch-set of stage 2 = projection of stage 1's discovered links)
        ▼                         ▼
   availability provider     lane-plan provider     reservation provider   … per-cadence, independent
        │                         │                         │
        └──────────── each stamps parent identity, joins deterministically ──────────┘
                                  ▼
                              gold.sqlite  ──►  services (/swim, /pools)
```

Stage 1 fetches the pool page and emits the sub-resource links it finds; stage 2+ consume those
links. The coupling between stages is the **freshly discovered link**, not a snapshot in the
store — which is what removes the stale-fetch-set bug (see anti-patterns).

## Patterns already in the codebase that MATCH this (reuse, don't reinvent)

- **Fetch-set as a projection, no hardcoded list.** [[lane-plan-url-binding]]: *what to extract
  is a projection of the model — `{(basin, source.url) for every basin that declares one}`; the
  `CITY_BELEGUNGSPLAN_URLS` / `PENDING_BELEGUNGSPLAENE` constants are deleted.* The shape is
  already right; only the *source of the projection* must change (YAML → upstream discovery).
- **Provenance-stamped deterministic join** (`etl/silver.py`). The fetch loop stamps
  `ParsedPlan.source_url` (the URL it already knows) and joins by URL back to the owning basin;
  the fuzzy `_basin_hint_index` was **deleted** and `basin_hint` is explicitly *not an identity
  key*. This is how identity crosses a discovery hop: provider N stamps the **parent's stable
  id** onto each discovered link so provider N+1's result joins back deterministically — never a
  fuzzy content match.
- **Independent layered stages onto one store** — `build → scrape-gold → scrape-lanes` each
  layer onto the already-built gold DB. The "independent providers" skeleton exists.
- **Extraction outcome as first-class typed state** — `Basin.lane_plan: LanePlan |
  LanePlanUnavailable | None`, with `LanePlanUnavailable(cause: ProviderError, observed_at)`
  persisted *losslessly* and keyed by error class (retry `retriable()` network causes,
  quarantine `ParseError`). The right substrate for fail-fast that stays granular.

## Anti-patterns / tensions to fix under this rule

- **Links are hand-authored, not discovered — the discovery hop doesn't exist yet.**
  `lane_plan_source` is *"authored in `data/pools/*.yaml`"* and called a *"curated input"*
  ([[lane-plan-url-binding]]); the page scraper (`providers/schedule_scraper.py`) extracts **no
  links** — it only parses the embedded timetable JSON. Today the "previous provider" that
  discovers the Belegungsplan link is a **human**. Rule 2 says the page provider must *emit*
  those links and feed the next provider.
- **A punt this rule *reframes* (does not automatically dissolve).** [[lane-plan-url-binding]]
  declines Altstetten because a *curated* link rots: *"a standing maintenance liability
  (Altstetten's URL sits in a rotating year-folder and would rot); we decline to own one… not
  surfaced as a raw link."* That is an argument against **hand-owned** links, not **discovered**
  ones — a discovery provider re-derives the rotating-year-folder URL each run, removing the *rot*
  objection. But two conditions remain: the link must actually be **discoverable on the page**,
  and Altstetten's plan is a **PNG grid with no PDF parser** ([[lane-plan-url-binding]]) — so it
  stays out of scope on the *parser* axis even once discovery removes the rot. Discovery makes the
  punt worth **revisiting**, not automatically reversed. (See also [[lane-data-availability]].)
- **A silent-staleness invariant that violates rule 4.** [[lane-plan-url-binding]] admits an
  un-type-enforced invariant: *"editing a basin's source in YAML without rebuilding leaves
  `scrape-lanes` fetching the old, smaller set."* That stale-store projection is exactly the
  "silent" failure banned here. A discovery-driven fetch-set (from a *fresh* parent scrape, not
  the built store) removes this class of bug.
- **Best-effort skip-and-report.** `scrape-gold` is documented "best-effort — unparseable pages
  skipped and reported" (build stays green), and `LanePlanUnavailable` is scoped so "the
  facility still builds." Both let a run exit 0 with missing data → become hard, non-zero
  failures under rule 4. The typed-error *values* stay; the green-exit posture goes.

## Resolved decision — fail semantics

When a single provider hard-fails, the build **aborts as a whole** (non-zero, loud) and leaves the
prior gold untouched — chosen over "fail only its own slice red while others complete." Rationale:
all-or-nothing fresh gold, never a partial/stale-but-green dataset; the cost accepted is that one
flaky source blocks the whole build. Resolved 2026-07-28 by the owner; implemented via
[[2026-07-28-website-sourced-providers-plan]] S4 (temp-DB build + atomic swap).
