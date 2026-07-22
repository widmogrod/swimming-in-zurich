---
type: concept
created: 2026-07-21
updated: 2026-07-22
links: ["[[2026-07-21-lane-plan-reconciliation-plan]]", "[[lane-data-availability]]", "[[gold-store]]", "[[data-layer-architecture]]"]
---

# Lane-plan source binding — a first-class domain attribute; extraction outcomes as persisted data

A basin's lane document (its Belegungsplan) is a **first-class domain attribute**:
`Basin.lane_plan_source: LanePlanSource | None`, where `LanePlanSource(url, section=None)`. It is authored in
`data/pools/*.yaml` and rides the `facility_doc` blob (no gold DDL). Identity is thus known where the URL is
authored — on the basin that owns the plan — so a binding can never reference a basin that doesn't exist, and
there is no second identity store.

**Every declared source is a Belegungsplan PDF we parse — nothing else.** There is no `format` discriminator, no
view/download "fallback", and no fidelity ladder: a source either parses to a grid or records why it didn't. A
source with no PDF parser — an image/HTML grid such as Hallenbad Altstetten's PNG — is **out of scope**, not
surfaced as a raw link. A curated external link is a standing maintenance liability (Altstetten's URL sits in a
rotating year-folder and would rot; see [[lane-data-availability]]), and we decline to own one.

**The ETL is driven by the domain, not a hardcoded list.** What to extract is a projection of the model —
`{(basin, source.url) for every basin that declares one}`; the old `CITY_BELEGUNGSPLAN_URLS` /
`PENDING_BELEGUNGSPLAENE` constants are deleted. A source exists to be extracted *iff a basin declares it*, and
adding one is a single YAML edit on the owning basin.

**Granular join — URL-keyed for single-basin sheets, URL+section-text for stacked ones.** The fetch loop stamps
`ParsedPlan.source_url` (the URL it already knows); for a **single-basin** sheet `attach_lane_plans` is a pure
inner join matching the parsed result back to the basin whose URL it came from — the fuzzy `_basin_hint_index`
(normalise the PDF title against a facility×basin-word key) is deleted. A **stacked** multi-basin sheet shares
one URL across all its sections, so the URL alone cannot discriminate: each section is routed by the declared
`section` token against the parsed header — a **scoped text match, not a pure id join**. The routing **fails
safe, never misbinds**: a parsed header matching **more than one** declared token (an ambiguous/overlapping
token — one is a substring of another section's header) is surfaced as `UnboundPlan` rather than positionally
guessed, and a header matching **zero** tokens is likewise `UnboundPlan` — so any extra parsed section beyond
the declared bindings falls into this zero-match arm rather than being positionally guessed (in the single-basin
path an explicit `len(plans)` count-guard does the same). The dual case — a declared token
that matched **no** parsed header — is surfaced as an audited `unmatched section` (a likely parser-header
regression), never a silent `None`. This residual soft match depends on the parser's header extraction
(`_basin_title`, owned by [[richer-data-fidelity]], out of scope here). Failures are typed values: a URL no
basin claims → non-fatal `UnboundPlan` (audited to stderr); a duplicate or double binding → fatal
`Err(SchemaMismatch)`. `PoolId`/`BasinId` are read off loaded facilities (`reconstruct_pool_id`), never minted.

**Extraction outcome is first-class persisted state — errors are data, not exceptions.**
`Basin.lane_plan: LanePlan | LanePlanUnavailable | None`:
- `None` → nothing to extract (no source) **or** the scrape has not run yet.
- `LanePlan` → the parsed grid.
- `LanePlanUnavailable(source_url, section, cause: ProviderError, observed_at)` → a declared source whose
  extraction was attempted and **failed**.

The `cause` is the real closed-union `ProviderError` — `HttpStatus(status, body_snippet)`, `Timeout(after_s)`,
`ConnectionFailed(detail)`, `ParseError(detail, raw_snippet)`, … — persisted **losslessly**, not reduced to a
status code or a `describe()` string. Because the failure is a stored value keyed by its typed cause, **partial
extraction loses nothing**: a run that parses 5/8 sheets writes 5 `LanePlan` + 3 `LanePlanUnavailable`, and
recovery selects the failed rows *by error class* — retry the `retriable()` network causes (`Timeout`,
`ConnectionFailed`), quarantine the `ParseError` sheets that need a parser fix, not a re-run. The selective-retry
command is deferred; the data model is what enables it.

Lossless persistence requires that **every** `ProviderError` variant be encodable, so `ProviderSpecific.detail`
is narrowed `object → JsonValue` (its only real payloads are `str`/`dict`/`None`) — the union then round-trips
through the boundary DTO with no variant special-cased and no `repr`.

**Failure is scoped to the field.** A fetch/parse failure fails **only** that basin's `lane_plan` (→
`LanePlanUnavailable`); the facility, its schedule, geo, and eligibility build and serve normally. This is
asserted, not assumed.

Do **not** conflate `lane_plan_source` (curated **input**) with `lane_plan` (the extraction **outcome**).
Accepted seams: stacked-sheet routing is a scoped text match; the parse fetch-set derives from the built store,
so **"rebuild before scrape" is a real, un-type-enforced operational invariant** — editing a basin's source in
YAML without rebuilding leaves `scrape-lanes` fetching the *old, smaller* set. The closed source universe
([[lane-data-availability]]) does **not** bound this: closure rules out an *unknown* source appearing, but not a
*known* source silently dropped by a stale store; that risk is caught only by a fetch-set derivation test. See
the plan [[2026-07-21-lane-plan-reconciliation-plan]] for the slices.
