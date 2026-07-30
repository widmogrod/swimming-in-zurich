---
type: concept
name: discovery-driven-providers
status: implemented   # direction set 2026-07-28; shipped via website-sourced-providers S1–S5 + delete-curated-schedule-tier S1–S4.
created: 2026-07-28
updated: 2026-07-31
links: ["[[lane-plan-url-binding]]", "[[data-layer-architecture]]", "[[source-links]]", "[[lane-data-availability]]", "[[gold-store]]", "[[2026-07-28-website-sourced-providers-plan]]"]
---

# Discovery-driven providers — every fact from a source, links discovered not curated, fail-fast

> **Status: implemented.** This recorded an owner decision (2026-07-28) about how the ETL sources
> data; it is now the as-built design. The `website-sourced-providers` run (S1–S5) built the
> roster/geo/`geo_sport_id`/schedule/price/notice/lane providers and the fail-fast posture, and
> `delete-curated-schedule-tier` (S1–S4) reduced curated YAML to the thin crosswalk and folded the
> whole chain into one atomic `swimzh build`. The "anti-patterns to fix" below are kept as a record
> of what was resolved (each is annotated). See [[website-sourced-providers]] for the end-state.

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

## Anti-patterns / tensions that were fixed under this rule (RESOLVED — kept for the record)

- **RESOLVED — links are now discovered.** The page provider emits the Belegungsplan links it
  finds and they become the lane provider's fetch-set (the discovery hop, `website-sourced-providers`
  S1). `lane_plan_source` in `data/pools/*.yaml` survives only as the thin-crosswalk URL→basin
  *binding* (where a link is not discoverable on the page), no longer a general curated input.
- **A punt this rule *reframes* (does not automatically dissolve).** [[lane-plan-url-binding]]
  declines Altstetten because a *curated* link rots: *"a standing maintenance liability
  (Altstetten's URL sits in a rotating year-folder and would rot); we decline to own one… not
  surfaced as a raw link."* That is an argument against **hand-owned** links, not **discovered**
  ones — a discovery provider re-derives the rotating-year-folder URL each run, removing the *rot*
  objection. But two conditions remain: the link must actually be **discoverable on the page**,
  and Altstetten's plan is a **PNG grid with no PDF parser** ([[lane-plan-url-binding]]) — so it
  stays out of scope on the *parser* axis even once discovery removes the rot. Discovery makes the
  punt worth **revisiting**, not automatically reversed. (See also [[lane-data-availability]].)
- **RESOLVED — the stale-fetch-set bug is gone.** `swimzh build` now runs the chain in one atomic
  pass, so the lane fetch-set is a projection of the *fresh* parent scrape within the same build,
  not the previously-built store. The "edit YAML without rebuilding" staleness window no longer
  exists.
- **RESOLVED — fail-fast, not skip-and-continue-green.** The atomic build aborts non-zero on any
  fatal provider failure and leaves the prior gold content-unchanged (temp-DB + swap). The
  typed-error *values* stayed; the green-exit posture went. (One deliberate exception: the price
  scrape is best-effort — the single non-fatal chain link — recorded in the plan ledger.)

## Resolved decision — fail semantics

When a single provider hard-fails, the build **aborts as a whole** (non-zero, loud) and leaves the
prior gold untouched — chosen over "fail only its own slice red while others complete." Rationale:
all-or-nothing fresh gold, never a partial/stale-but-green dataset; the cost accepted is that one
flaky source blocks the whole build. Resolved 2026-07-28 by the owner; implemented via
[[2026-07-28-website-sourced-providers-plan]] S4 (temp-DB build + atomic swap).
