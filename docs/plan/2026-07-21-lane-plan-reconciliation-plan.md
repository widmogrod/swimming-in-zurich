---
type: plan
status: done              # draft -> approved -> in-progress -> done
created: 2026-07-21
updated: 2026-07-22
feature: lane-plan-reconciliation
branch: plan/lane-plan-reconciliation
worktree: "relocated into the main checkout (see Decisions 2026-07-22 — worktree relocation)"
base_branch: main
gates:
  qa: full               # ruff, format, mypy strict, pytest+coverage floor (95), CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: [S1]        # S1 validates the whole design (URL-keyed join + errors-as-persisted-state); human-review before S2 builds stacked-sheet routing on top
links: ["[[lane-plan-url-binding]]", "[[lane-data-availability]]", "[[richer-data-fidelity]]", "[[gold-store]]", "[[data-layer-architecture]]"]
---

# Plan — Reconcile lane plans by URL-origin identity, not fuzzy PDF-title text

## Context

The Belegungsplan parser now reads 8/8 published sheets (see [[richer-data-fidelity]]), but only
**2 of 8 reach a swimmer**: `attach_lane_plans` (`etl/silver.py`) reconciles a parsed plan to a basin by
**fuzzy-matching the PDF's internal title** (`ParsedPlan.basin_hint`) against a `normalise("<facility> <basin
name-or-kind-word>")` key index (`_basin_hint_index`). That fails for real curated basins whose header omits
the facility (E3 stacked-sheet titles "Nichtschwimmer"/"Sprungbecken") or omits the basin (single-basin sheets
like "Hallenbad Bungertwies"). Two curated basins (**bungertwies-25m**, **oerlikon-sprungbecken**) parse
correctly and still never attach — a genuine reconciliation defect, not curation debt.

The fix (agreed via a 3-design / 9-critic panel, then elevated with the owner): make the lane document a
**first-class domain attribute on the basin** — `Basin.lane_plan_source` (url + optional section) authored in
`data/pools/*.yaml`. Because identity is known at the point the URL is listed, the ETL is **driven by the
domain** (the hardcoded URL list dies) and reconciles by a **deterministic URL-keyed join**, deleting the fuzzy
matcher. And because a Belegungsplan is a curated PDF we parse, the **extraction outcome is itself first-class
persisted state**: a basin's `lane_plan` is either a parsed `LanePlan`, or a `LanePlanUnavailable` carrying the
real typed `ProviderError` cause — errors are stored data, not exceptions, so partial extraction loses nothing
and recovery can select failed rows *by error class*. Builds on the identity spine + gold-store single-source
discipline ([[gold-store]], [[data-layer-architecture]]) and the [[lane-plan-url-binding]] concept; scoped by
the availability catalog [[lane-data-availability]].

## Design (signature altitude)

**`lane_plan_source` is a FIRST-CLASS domain attribute on the basin** — where the basin's lane document lives,
authored in `data/pools/*.yaml`, riding the existing `facility_doc` blob (no gold DDL / no migration). Every
declared source is a Belegungsplan PDF; there is **no `format`, no `label`, no view/download fallback**:
```
# domain/models.py
LanePlanSource(url: str, section: str | None = None)
    # section = bare basin token for a STACKED multi-basin sheet (None => whole sheet)
Basin.lane_plan_source: LanePlanSource | None = None       # additive, first-class — NOT an ETL side-list
```
Mirror through `boundary/curated_dto.py` + `boundary/mapping.py` (pop-when-default, Slice-D style), round-trip
guarded. Strongest SSOT posture: the binding lives *with* the basin, so it can never reference a basin that
doesn't exist, and there is no second identity store.

**The ETL is DRIVEN BY the domain — the hardcoded URL list dies.** `CITY_BELEGUNGSPLAN_URLS` and
`PENDING_BELEGUNGSPLAENE` are **deleted**; what to extract is a projection of the model, so a source exists to
be extracted *iff a basin declares it* (no drift, no second home; adding a source is one YAML edit):
```
sources = [(f.identity.facility_id, b.basin_id, b.lane_plan_source)
           for f in facilities for b in f.basins if b.lane_plan_source is not None]
```

**Extraction outcome is FIRST-CLASS PERSISTED STATE — errors are data, not exceptions:**
```
# domain/models.py
@dataclass(frozen=True, slots=True)
class LanePlanUnavailable:
    source_url: str
    section: str | None
    cause: ProviderError          # the REAL closed-union cause — HttpStatus(status, body_snippet),
    observed_at: datetime         # Timeout(after_s), ConnectionFailed, ParseError(detail, raw_snippet), …
Basin.lane_plan: LanePlan | LanePlanUnavailable | None
    #  None                -> nothing to extract (no source) OR scrape not yet run
    #  LanePlan            -> parsed grid
    #  LanePlanUnavailable -> source declared, extraction attempted and FAILED (cause persisted losslessly)
```

| basin state | ETL action | stored `lane_plan` |
|---|---|---|
| no `lane_plan_source` | nothing | `None` |
| source declared, not yet scraped | (build only) | `None` |
| source declared, parse succeeds | fetch + parse (deterministic, URL-keyed) | `LanePlan` (parsed grid) |
| source declared, fetch/parse fails | fetch attempted → typed miss recorded | `LanePlanUnavailable(cause=<ProviderError>)` |

Because the failure is a stored value keyed by its typed cause, **partial extraction loses nothing** and
recovery can partition rows by error class (`retriable()` network causes → retry; `ParseError` → parser fix, not
a re-run). The selective-retry command is **deferred** (see Out of scope); the data model enables it.

**Lossless persistence needs every `ProviderError` variant encodable.** `ProviderSpecific.detail` is narrowed
`object → JsonValue` in `core/errors.py` (`type JsonValue = None | bool | int | float | str | list[JsonValue] |
dict[str, JsonValue]`) — its only real payloads are `str`/`dict`/`None`, so the whole closed union round-trips
through the boundary DTO with no variant special-cased and no lossy `repr`.

**Granular tier — deterministic, URL-keyed join (no fuzzy matching).** Parse fetch-set = `{src.url for every
declared source}`; the fetch loop stamps `ParsedPlan.source_url`; `attach_lane_plans` becomes a pure inner join
matching the parsed result back to the basin whose URL it came from. `_basin_hint_index`/the normalise-the-title
lookup is **deleted**; `build/reconcile.py`'s `BasinHint` arm retires; `basin_hint` demotes to a stacked-sheet
discriminator + `UnboundPlan` audit string, never an identity key, never persisted.
```
build_url_bindings(facilities) -> Result[dict[str, tuple[_Binding, ...]], ProviderError]   # dup (url,section) => fatal Err, named
bind_plans(parsed, bindings) -> tuple[tuple[BoundPlan, ...], tuple[UnboundPlan, ...]]        # keyed on source_url
    #   single-basin (section None) -> bind directly, hint IGNORED
    #   stacked (N bindings)        -> route each parsed section to the binding whose token appears in normalize(hint)
    #   parser-split M != claimed   -> extras -> UnboundPlan (structural guard; never a silent positional misbind)
BoundPlan(pool_id, basin_id, plan)   UnboundPlan(source_url, basin_hint, reason)
# attach = inner join over BoundPlan by (pool_id, basin_id); two BoundPlans on one basin => fatal Err.
# a declared source that FAILED to fetch/parse -> its basin gets LanePlanUnavailable(cause), never silent None.
# PoolId/BasinId READ off loaded facilities (reconstruct_pool_id) — NO new minting seam.
```

## Invariants to preserve

One gold DB is the only runtime source (no `apps/web/**` reads `data/`); `PoolId` minted only in
`build/reconcile` + `build/seed` (`reconstruct_pool_id` the single re-wrap door — the join re-wraps, never
mints); errors are typed values (`Result[..., ProviderError]`, `match` + `assert_never`); the `ProviderError`
union stays **closed** — variants unchanged, only `ProviderSpecific.detail` narrows `object → JsonValue` to make
the union losslessly persistable (`retriable`/`describe` unaffected); a lane-plan extraction failure fails
**only** that basin's `lane_plan`, never the facility/pool (asserted); `swimzh build` stays offline;
`scrape-lanes` layers onto an already-built store; additive gold round-trip stays byte-exact for pre-existing
blobs; domain pure; all datetimes tz-aware.

## Honest compromises (accepted, from the critic panel)

- **Stacked sheets are not a *pure* id join** — the `section` token is a text compare against the parsed header
  (scoped to one known sheet). It is misbind-safe only for **non-overlapping** tokens (containment can misroute
  if one is a substring of another section's header); the structural count-guard backstops the common cases.
  Pure id-join holds only for single-basin sheets, and the match depends on the parser's header extraction
  (`_basin_title`, owned by [[richer-data-fidelity]], out of scope here).
- **"Rebuild before scrape" is a real, un-type-enforced operational invariant** — the parse fetch-set derives
  from the built store, so a store built before a basin gained its `lane_plan_source` silently parses fewer
  sources. The closed source universe ([[lane-data-availability]]) does **not** bound this: closure rules out an
  *unknown* source appearing, but not a *known* source dropped by a stale store. Guarded by a derivation test +
  documented; not type-enforced.
- **`lane_plan_source` (curated input) vs `lane_plan` (extraction outcome)** are two adjacent `Basin` fields that
  invite conflation — mitigated by the `docs/concepts/` note (S3), not by the type system.
- **`LanePlanUnavailable` widens `Basin.lane_plan`'s read surface** — every reader of `lane_plan` now handles a
  third case (`match` over `LanePlan | LanePlanUnavailable | None`). Deliberate: it is what makes a failed
  extraction inspectable rather than an indistinguishable `None`.

## Out of scope

- **FULL curation** of leimbach / blaesi / kaeferberg (schedules, eligibility, geo) — S1 gives them only a
  minimal schedule-less basin carrying `lane_plan_source` (so their already-parsing sheets attach and their URL
  becomes first-class), NOT a full timetable. They stay out of `/swim` (Decision #5 rule: no rules → no option).
  city-vario needs a curated Variobecken basin, so its sheet is **not** authored/fetched (deferred);
  oerlikon-nichtschwimmer stays an honest `UnboundPlan`.
- **A selective-retry command** (`scrape-lanes --retry-failed` / re-extract only `LanePlanUnavailable` rows of a
  given error class). The persisted `LanePlanUnavailable(cause)` state **enables** it; the command itself is a
  deferred follow-up, not this plan.
- **A raw view/download "fallback" link** for any source (rejected: a curated external link is a maintenance
  liability). No `format`/`label` field, no fidelity ladder.
- **Hallenbad Altstetten** (a PNG lane grid on a rotating URL) — surfacing OR parsing it. It has no PDF parser
  and its URL rotates ([[lane-data-availability]]); a distinct future feature (vision/OCR + discovery), fully out.
- **A discovery slice.** The 2026-07-21 stress test ([[lane-data-availability]]) proved the published
  stadt-zuerich Belegungsplan universe is EXACTLY the 8 sheets already wired — no missing basin, no browsable
  index, outdoor/river/lake pools publish none. The domain-derived source set is therefore complete and closed;
  no crawler/enumeration is needed.
- Any gold **schema/DDL** change or SQLite migration (the field rides `facility_doc`).
- A separate `data/belegungsplan.yaml` crosswalk table (the rejected spine-native variant — reintroduces
  cross-file `basin_id` coupling).
- Changing the parser's geometry/section-splitting (owned by [[richer-data-fidelity]] E1–E3).
- Re-reading `data/` at request time.

## Slices

### S1 — First-class `lane_plan_source` + domain-driven deterministic extraction (single-basin PDFs); extraction outcomes as persisted state; hardcoded URL list deleted; lands Bungertwies

- **Goal**: make `lane_plan_source` a first-class domain field that DRIVES extraction (no hardcoded URL list),
  replace the fuzzy matcher with a deterministic URL-keyed inner join for single-basin PDFs, record every
  extraction outcome as first-class persisted state (`LanePlan | LanePlanUnavailable | None`), and prove it
  end-to-end with no regression to the basins that already attach.
- **Touches**: `core/errors.py` (`JsonValue`; narrow `ProviderSpecific.detail: object → JsonValue`);
  `domain/models.py` (`LanePlanSource(url, section=None)`, `Basin.lane_plan_source`; `LanePlanUnavailable`,
  widen `Basin.lane_plan` to `LanePlan | LanePlanUnavailable | None`); `boundary/curated_dto.py` +
  `boundary/mapping.py` (round-trip `lane_plan_source` AND `LanePlanUnavailable` — full `ProviderError` codec,
  pop-when-default); `providers/belegungsplan.py` (`ParsedPlan.source_url`, parser stays URL-agnostic);
  `etl/lane_plans.py` (**delete `CITY_BELEGUNGSPLAN_URLS` and `PENDING_BELEGUNGSPLAENE`**; parse fetch-set
  derived from the domain — `{src.url for basin sources}`; fetch loop stamps `source_url`; a failed fetch/parse
  is mapped back to its basin(s) as a typed miss); `etl/silver.py` (`build_url_bindings`, `bind_plans`
  single-basin, rewrite `attach_lane_plans` as inner join over `BoundPlan`; stamp `LanePlanUnavailable(cause)`
  onto a declared basin whose source failed; delete `_basin_hint_index`/`_BasinRef`; add `UnboundPlan`);
  `build/reconcile.py` (retire `BasinHint` arm) + `build/seed.py` ripple; `data/pools/*.yaml` — author
  `lane_plan_source` onto **city-schwimmer**, **oerlikon-schwimmer**, **bungertwies**, and give
  **leimbach/blaesi/kaeferberg** a minimal schedule-less basin carrying their `lane_plan_source` (so deleting
  the hardcoded list drops nothing and their parsing sheets attach).
- **Acceptance**: `scrape-lanes` attaches **Bungertwies** by URL — a **deliberately garbled `basin_hint` still
  binds** (header-independence test); **City-50m + Oerlikon-50m still attach**, **leimbach/blaesi/kaeferberg now
  attach** to their minimal basins (were `unmatched`); a **failed-fetch source records `LanePlanUnavailable` with
  the exact `ProviderError` cause AND the facility still builds** (scoped-failure test); the full `ProviderError`
  union (incl. `ProviderSpecific`) **round-trips losslessly** through the boundary DTO (codec test); a
  **grep-guard proves `CITY_BELEGUNGSPLAN_URLS` / `PENDING` / `_basin_hint_index` are gone**; a **derivation
  test** asserts the parse fetch-set == the domain's declared source urls (nothing hardcoded); a **golden-set
  test** pins the exact bound set; a **duplicate `(url, section)` → fatal `Err(SchemaMismatch)`** named; existing
  gold round-trip byte-unchanged; QA green.
- **Depends on**: — **[PAUSE — this slice validates the whole design; human-review before S2.]**

### S2 — Stacked-sheet `section` routing (lands Oerlikon Sprungbecken)

- **Goal**: bind a basin *within* a multi-basin/Teil sheet via the declared `section` token, with the structural
  count-guard, so the second real reconciliation bug is fixed.
- **Touches**: `etl/silver.py` (`bind_plans` stacked branch: route each parsed section to the binding whose
  `section` token appears in `normalize(basin_hint)`; parser-split count ≠ claimed bindings → `UnboundPlan`, never
  a silent positional misbind); `data/pools/oerlikon.yaml` (add `lane_plan_source` with
  `section: sprungbecken` to `oerlikon-sprungbecken`, pointing at the combined nichtschwimmer-sprungbecken
  sheet); extend the golden-set fixture.
- **Acceptance**: `scrape-lanes` attaches **Oerlikon Sprungbecken**; the still-uncurated **Nichtschwimmer**
  section surfaces as exactly one honest `UnboundPlan`; a **wrong/typo `section` token binds nothing** (fails
  safe, asserted); parser-split-count ≠ claimed → typed miss (asserted); the golden-set now includes
  `(hallenbad-oerlikon, oerlikon-sprungbecken)` → **4/… attached**; City/Bungertwies unchanged; QA green.
- **Depends on**: S1.

### S3 — Honest `unbound` + `unavailable` report + doc reversal

- **Goal**: surface unbound URLs and unavailable extractions as an auditable operational report, and correct the
  docs that this design makes false.
- **Touches**: `cli.py` (`scrape-lanes` prints the `UnboundPlan` audit AND a per-basin `LanePlanUnavailable`
  summary — url + `describe(cause)` — to stderr; `match` the fatal `Err` with `assert_never`); reverse
  "decision #8" docstring in `etl/lane_plans.py` (the "URL→basin binding is intentionally NOT made here" comment
  is now false); `silver.py` module docstring; the CLAUDE.md lane-plan paragraph; confirm
  `docs/concepts/lane-plan-url-binding.md` is the final first-class / errors-as-persisted-state shape (already
  rewritten), distinguishing `lane_plan_source` (curated input) vs `lane_plan` (extraction outcome).
- **Acceptance**: `scrape-lanes` prints the per-URL `unbound` reasons and the per-basin `unavailable` causes
  (not a bare `unmatched` list); a grep confirms the stale "basin_hint drives reconciliation" / decision-#8
  claims are gone; the concepts note exists and is linked; QA green.
- **Depends on**: S1.

## Ledger

Appended by /dev:implement after each slice — never rewritten. Newest row last.

| date | slice | status | divergence from plan | tech debt created | human review? |
|------|-------|--------|----------------------|-------------------|---------------|
| 2026-07-22 | S1 | done | worktree relocated into main checkout (subagent cwd targeted the main repo, not the worktree); `index_bound_plans` two-plans→one-basin guard tested directly (structurally unreachable via the single-basin join until S2) | none (2 non-blocking critic notes deferred to S2) | yes |
| 2026-07-22 | S2 | done | ambiguous section token (header matching >1 declared token) fails safe to `UnboundPlan` — STRICTER than the plan's "can misroute" compromise; concept-note wording to be reversed in S3 | none | yes |
| 2026-07-22 | S3 | done | source docstrings were already accurate (S1/S2 removed the stale claims) — edited anyway for the grep-guard + stacked-routing description; CLI audit extracted to `_report_lane_audit` (CC); added typed `UnmatchedSection` audit (folds S2 critic suggestion a) | none | no |

## Decisions & divergences

- **2026-07-21 — design source.** Synthesized from a 3-design / 9-critic panel (provenance-first base, grafting
  minimal's structural count-guard + spine-native's loud-failure discipline; rejected spine-native's separate
  `data/belegungsplan.yaml` table for reintroducing cross-file `basin_id` coupling). Scoreboard: provenance-first
  12/15, spine-native 12/15, minimal 11/15; provenance-first won on SSOT (binding on the owning basin ⇒ no
  dangling-basin class).
- **2026-07-21 — design elevated to first-class domain (owner directive).** Supersedes the panel's
  "`lane_plan_source` as ETL-only input" framing: `lane_plan_source` is a first-class `Basin` attribute, so the
  ETL is DRIVEN BY the domain — `CITY_BELEGUNGSPLAN_URLS` **and** `PENDING_BELEGUNGSPLAENE` are DELETED and the
  parse fetch-set is a projection of the declared sources (kills the hardcoding + the PENDING wart the critics
  docked).
- **2026-07-22 — fallback/fidelity-ladder REMOVED; extraction outcomes become first-class persisted data
  (owner directive).** Reverses the 2026-07-21 "fidelity ladder" elevation. (1) A curated view/download link is
  a maintenance liability (Altstetten's URL rotates → born-stale), so there is **no fallback tier, no `format`,
  no `label`**; a source is a PDF we parse or nothing. Altstetten is fully out of scope (was S3 fallback —
  **that slice is deleted**, plan back to 3 slices). (2) Instead, a failed extraction is recorded as
  first-class state: `Basin.lane_plan` widens to `LanePlan | LanePlanUnavailable | None`, and
  `LanePlanUnavailable` carries the **real `ProviderError` cause persisted losslessly** — errors are stored data,
  enabling recovery-by-error-class and lossless partial extraction. (3) Lossless persistence forced narrowing
  `ProviderSpecific.detail: object → JsonValue` (the only un-encodable field in the closed union; real payloads
  are str/dict/None, so it is a safe narrowing — one production site + two tests). (4) A **selective-retry
  command** is deferred (the model enables it; the CLI is a follow-up). (5) The closed-universe/rebuild framing
  is corrected: closure bounds "no unknown source", not "no known source dropped by a stale store".
- **2026-07-21 — stress test validated the plan (3-agent web sweep → [[lane-data-availability]]).** Findings:
  (1) the 8 wired PDFs ARE the complete published stadt-zuerich Belegungsplan set — no missing basin/sheet, DAM
  dir not browsable, all 8 resolve 200; (2) NO outdoor/lake/river pool publishes a Belegungsplan (exhaustive
  404s vs. indoor 200s; pages carry hours only); (3) Altstetten publishes a PNG lane grid on a rotating URL
  (vision + discovery path, out of scope). Consequences folded in: no discovery slice; the derived fetch-set is
  provably complete/stable, which bounds only the "unknown source appears" risk (NOT the stale-store risk). S1/S2
  target the two blocked-but-real curated basins; the design is confirmed as the correct lever (the gap is 100%
  reconciliation, 0% discovery).

- **2026-07-22 — worktree relocation (execution divergence, not design).** `/dev:implement` created an isolated
  worktree, but the spawned `slice-implementer` resolved files via the session's primary-working-directory
  absolute path and wrote S1 into the **main checkout**, not the worktree (the critic, running `git` from its
  cwd, correctly found the worktree empty — a false "unimplemented" verdict). Recovered non-destructively:
  captured S1 as a patch, removed the now-empty worktree (branch preserved), and `git switch`ed the main
  checkout onto `plan/lane-plan-reconciliation`, carrying the staged S1 changes across. Net effect: the plan
  branch now lives in the main working tree rather than a separate worktree; base `main` is still written only by
  the approve commit + the eventual ff-merge. Re-ran the critic against the real code (verdict **approve**) and
  the full QA chain (399 passed, 95.59%, crap OK) before committing.
- **2026-07-22 — S1 landed.** `lane_plan_source` + `LanePlanUnavailable` + widened `Basin.lane_plan` are
  first-class; the `ProviderError` codec round-trips losslessly via an explicit pydantic `Field(discriminator=
  "type")` tag (not shape inference — the implementer's "smart union on shape" note was imprecise; the `lane_plan`
  slot uses shape-disjoint discrimination, but the `ProviderError` union is tag-discriminated). The fuzzy matcher
  (`_basin_hint_index`, `BASIN_KIND_WORDS`), the hardcoded URL lists (`CITY_BELEGUNGSPLAN_URLS`,
  `PENDING_BELEGUNGSPLAENE`), and the `BasinHint` `SourceRef` arm (+ `build_basin_hint_index`, `Crosswalk.
  basin_hint`/`ambiguous_hints`) are deleted. Discovery for S2/S3: leimbach/blaesi/kaeferberg are a new
  **curated-but-schedule-less** class (physical_source CURATED, no rules) distinct from Slice-F PARSED_PROSE prose
  pools — several spine/build test guards were widened to recognise it; keep the `prose` vs `lane_only`
  distinction when touching those. Non-blocking (deferred): (1) `attach_lane_plans`' two-plans→one-basin `Err`
  arm is covered only via `index_bound_plans` directly — add an `attach`-level test once S2 makes it reachable;
  (2) `resolve_all`'s `Err` arm is structurally unreachable after `_Ambiguous` retired — revisit when a new fatal
  `SourceRef` cause appears.

- **2026-07-22 — S2 landed (stacked-sheet `section` routing).** `bind_plans` now routes each parsed section of a
  multi-basin sheet to the binding whose declared `section` token is contained in `normalize(basin_hint)`, with
  the count-guard (extra parsed sections → `UnboundPlan`). Oerlikon Sprungbecken attaches via the combined
  nichtschwimmer-sprungbecken sheet; Nichtschwimmer surfaces as exactly one honest `UnboundPlan`. **Divergence
  (accepted, stronger than plan):** an *ambiguous* section — a parsed header containing >1 declared token —
  fails safe to `UnboundPlan` rather than the "can misroute" hazard the Honest-compromises section documented;
  the critic empirically confirmed (overlapping `becken`/`sprungbecken`, `schwimmer`/`nichtschwimmer`) that **no
  input binds the wrong basin**. Consequence: the concept note's "containment can misroute" wording is now false
  and must be **reversed in S3** (doc-reversal is already S3 scope). Also closed S1 deferred note (1): the
  two-plans→one-basin fatal `Err` is now reachable and tested through `attach_lane_plans`. Two critic suggestions
  folded into S3's audit scope: (a) an audit line for a declared section token that matched **no** parsed header
  (a curated basin silently left `None` by a parser header regression); (b) optionally use realistic headers in
  the golden-set routing assertion so it is not self-fulfilling.

- **2026-07-22 — S3 landed (honest audit + doc reversal).** `scrape-lanes` now prints a typed stderr audit:
  per-basin `LanePlanUnavailable` cause (`describe(cause)`), per-URL `UnboundPlan` (url + hint + reason), and a
  new `UnmatchedSection` line (a curated `section` token that matched **no** parsed header — a likely parser
  regression, no longer a silent `None`). `find_unmatched_sections` is scoped to sheets that actually parsed, so
  a whole-sheet fetch failure stays a single `LanePlanUnavailable` (no double-report) and an ambiguous token
  stays a single `UnboundPlan`. The concept note's false "can misroute" line is reversed to the shipped
  fail-safe behaviour; `etl/lane_plans.py`/`etl/silver.py` docstrings and the `CLAUDE.md` lane-plan paragraph now
  describe the URL-keyed join + persisted outcomes. Divergence: the docstrings were already free of the stale
  decision-#8 claims (S1/S2 had removed them), so S3 added the positive description + grep-guard rather than a
  literal reversal; the CLI audit was extracted to `_report_lane_audit` (CC gate). Behaviour is reporting-only —
  scrape/build/attachment unchanged (critic-confirmed). Concept-note count-guard wording tightened post-review
  (the stacked path's guard is emergent via the zero-match arm, not an explicit count compare).

## Summary

The lane-plan reconciliation defect (only 2 of 8 parsed Belegungspläne reached a swimmer, because attachment
fuzzy-matched the PDF's internal title) is fixed by making the lane document a **first-class domain attribute**
— `Basin.lane_plan_source(url, section=None)` authored in `data/pools/*.yaml`, riding `facility_doc` (no gold
DDL). The ETL is now **driven by the domain**: the parse fetch-set is a projection of the declared sources
(`declared_source_urls`), the hardcoded `CITY_BELEGUNGSPLAN_URLS`/`PENDING_BELEGUNGSPLAENE` lists and the fuzzy
`_basin_hint_index` (+ the `BasinHint` `SourceRef` arm) are deleted, and reconciliation is a **deterministic
URL-keyed inner join** — pure for single-basin sheets, plus a fail-safe `section`-token text match for stacked
multi-basin sheets (ambiguous/overlapping token → `UnboundPlan`, never a misbind; critic-verified against real
headers). Extraction outcomes are **first-class persisted state**: `Basin.lane_plan: LanePlan |
LanePlanUnavailable | None`, where `LanePlanUnavailable` carries the real closed-union `ProviderError` cause
persisted **losslessly** (enabled by narrowing `ProviderSpecific.detail: object → JsonValue`) — so a failed
extraction fails only that basin's `lane_plan`, never the pool build, partial extraction loses nothing, and
recovery can partition failures by error class (a deferred selective-retry command). `scrape-lanes` emits a
typed stderr audit (`unavailable` causes, `unbound` URLs, `unmatched section`). Result: City-50m, Oerlikon-50m,
**Oerlikon-Sprungbecken**, **Bungertwies**, **leimbach/blaesi/kaeferberg** attach (was 2/8 → now the full curated
set); Nichtschwimmer is an honest `UnboundPlan`. Out of scope and untouched: fallback/view-download links,
Altstetten's rotating-URL PNG, a discovery crawler, and gold DDL. Delivered in 3 gated slices (S1 first-class
field + join + errors-as-data; S2 stacked routing; S3 audit + doc reversal); QA green throughout (410 passed,
95.79%, CRAP clean). One execution divergence: the worktree was relocated into the main checkout because the
implementer subagent wrote to the main repo path (recovered non-destructively; base `main` untouched until
merge). Then distilled into `docs/summaries/lane-plan-reconciliation.md`.
