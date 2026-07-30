---
type: concept
created: 2026-07-21
updated: 2026-07-31
links: ["[[2026-07-21-lane-plan-reconciliation-plan]]", "[[lane-data-availability]]", "[[gold-store]]", "[[data-layer-architecture]]", "[[discovery-driven-providers]]"]
---

# Lane-plan source binding — a first-class domain attribute; extraction outcomes as persisted data

> **Reconciled to the as-built (2026-07-31) — see [[discovery-driven-providers]].** The three
> decisions once flagged "superseded" are now built and this doc describes them:
> - **The lane-plan URL is DISCOVERED, not a general curated input.** The page provider emits the
>   Belegungsplan links it finds; those become the lane provider's fetch-set. `lane_plan_source`
>   in `data/pools/*.yaml` survives only as the thin-crosswalk **binding** (url + optional
>   `section`) for the URL→basin join — a fact on no page. Every authored URL must appear among the
>   links its page advertises, else the build fails (`authored − discovered`, `UndiscoveredSource`).
> - **Fail-fast, not skip-and-continue-green.** A declared source whose fetch/parse fails now aborts
>   the atomic build non-zero (prior gold content-unchanged); there is **no longer a persisted
>   `LanePlanUnavailable` written for a failed source** — the DTO survives only for lossless
>   round-trip compatibility of an old blob.
> - **The binding is carried through compose.** When the scraped timetable wins (the post-strip
>   world), `build/compose.py` carries each curated basin's `lane_plan_source` onto the composed
>   facility so the crosswalk binding + physicals survive the schedule scrape.
>
> The URL-keyed deterministic join and the typed-error *values* below are unchanged.

A basin's lane document (its Belegungsplan) is a **first-class domain attribute**:
`Basin.lane_plan_source: LanePlanSource | None`, where `LanePlanSource(url, section=None)`. It is authored in
`data/pools/*.yaml` and rides the `facility_doc` blob (no gold DDL). Identity is thus known where the URL is
authored — on the basin that owns the plan — so a binding can never reference a basin that doesn't exist, and
there is no second identity store.

**Every declared source is a Belegungsplan PDF we parse — nothing else.** There is no `format` discriminator, no
view/download "fallback", and no fidelity ladder: a source either parses to a grid or fails the build. A
source with no PDF parser — an image/HTML grid such as Hallenbad Altstetten's PNG — is **out of scope on the
parser axis**. (Discovery removed the *rot* objection — a discovered link re-derives the rotating year-folder URL
each run rather than being hand-owned — but the missing PDF parser keeps Altstetten out; see
[[lane-data-availability]] and [[discovery-driven-providers]].)

**The fetch-set is DISCOVERED, and the binding is validated against it.** The lane provider fetches the links the
page provider discovered on each pool page — no hardcoded list, and no longer a projection of the authored
`lane_plan_source` URLs. The authored binding is now *checked* against discovery: every basin's declared
`lane_plan_source.url` must appear among the links its page advertises, or the build reports it as
`authored − discovered` (`UndiscoveredSource`) — so a stale hand-authored URL can never silently vanish. The
old `CITY_BELEGUNGSPLAN_URLS` / `PENDING_BELEGUNGSPLAENE` constants are gone.

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

**Extraction outcome state.** `Basin.lane_plan: LanePlan | LanePlanUnavailable | None`:
- `None` → nothing to extract (no source) **or** the scrape has not run yet.
- `LanePlan` → the parsed grid.
- `LanePlanUnavailable(source_url, section, cause: ProviderError, observed_at)` → a **legacy** typed
  extraction-failure value. **No longer produced by the current pipeline** — under the fail-fast atomic build a
  failed declared source aborts the whole build (non-zero, prior gold content-unchanged), it is not written as a
  per-basin hole. The variant + its DTO survive only so an older blob still round-trips.

The `cause` is the real closed-union `ProviderError` — `HttpStatus(status, body_snippet)`, `Timeout(after_s)`,
`ConnectionFailed(detail)`, `ParseError(detail, raw_snippet)`, … Lossless encodability was designed in (every
variant round-trips: `ProviderSpecific.detail` is narrowed `object → JsonValue`, no variant special-cased, no
`repr`), which is what would let a future selective-retry model store failures by error class — but the shipped
posture is fail-fast, so no such per-basin failure is persisted today.

**Failure aborts the build.** A fetch/parse failure of a declared lane source is fatal to the atomic build (the
fail-fast posture of [[discovery-driven-providers]]), not scoped to the basin — the older "the facility still
builds with a lane hole" behaviour is gone.

Do **not** conflate `lane_plan_source` (the thin-crosswalk **binding**) with `lane_plan` (the extraction
**outcome**). Accepted seams: stacked-sheet routing is a scoped text match. The old "rebuild before scrape"
operational invariant is **gone** — `swimzh build` runs discovery → scrape → lanes → compose in one atomic pass,
so the lane fetch-set is a projection of the *fresh* parent scrape within the same build, never a stale store.
See the plan [[2026-07-21-lane-plan-reconciliation-plan]] for the original slices.
