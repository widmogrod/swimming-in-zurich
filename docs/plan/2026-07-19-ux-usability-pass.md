---
type: plan
status: in-progress      # owner approved full backlog in-chat 2026-07-19 ("Everything: full backlog")
created: 2026-07-19
feature: ux-usability-pass
gates:
  qa: full               # make qa — ruff, format, mypy strict, pytest+coverage floor, CRAP
  review: adversarial    # critic subagent must find no blocking issues
pause_after: []          # run S1..S6 back-to-back (owner chose the full backlog)
scope: presentation only # single-file web UI (apps/web/api/ui/router.py); reuses existing endpoints
links: ["[[2026-07-19-ux-ascii-design]]", "[[ux-presentation]]", "[[fastapi-service-integration]]"]
---

# Plan — UX usability pass (fix the shipped web UI)

Origin: after shipping [[2026-07-19-ux-ascii-design]] the owner found the UI unfriendly
(tourist shows ~one pool, primer too big, no pool-detail/website link, too much unexplained
jargon). A 5-lens UX critic panel (IA · disclosure · actionability · plain-language · hierarchy)
+ a lead synthesis produced a prioritized backlog. This plan executes it.

## The core problem (all 5 critics agreed)

**The pool is not a first-class, actionable object where the swimmer stands.** On Find / Plan /
First-time the facility is inert text (`<span class="name">`) — no link, no detail, no phone, no
route to a schedule — though the masthead promises "verify on-site via the official link" and
`/pools`/`catalog.json` already carry `url`, `phone`, `address`, `lat/lon` per pool, joinable by
the name the card shows. The other complaints (one pool, glossary wall, glyph-decoder tax, wrong
visual hierarchy) are symptoms of building around sessions/axes instead of actionable pools.

## Constraints & what to KEEP (do not regress)

- **Honesty invariant #1** — never merge open / closed-with-reason / uncurated. Fixes change
  *wording and staging* only ("Hours not listed yet" instead of `UNCURATED`), never the distinction.
- **Honesty invariant #2** — busyness is never faked; keep "not available yet" (just not a whole
  column + 3 captions).
- **Length-badge concept** — a real lap-swimmer filter; demote its *size/priority*, keep it.
- **Inline decode-at-point-of-need** (the tourist card's "This slot is …" line) — the good model.
- **Zero-dependency single-file architecture** — plain HTML/CSS/JS + `tel:`/maps links + one
  memoized `/pools` fetch. No new endpoint, framework, or external asset.

## Endpoints/data available (fixes must use only these)

`/swim` options carry `{facility, basin, start, end, access, eligible, reason, price, distance_km,
open_now, valid_as_of, kind, length_m, lanes, source, curated}` — **name only, no url/phone**.
`/pools` → `{count, kinds, pools[{name, kind, address, url, phone?, lat, lon, …}]}` (**url/phone/geo
here**). `/access-types` → label+description per access key. Join key: facility **name**.

## Slices

Each slice is one vertical increment to `apps/web/api/ui/router.py` + its UI tests, taken fully
through QA + adversarial-review gates before the next. Presentation-only; no domain/API change.

- **S1 — Tourist tab: distinct starters + collapsed primer.** *(P0)*
  #1 dedupe starter pools to distinct facilities (`[...new Map(a.options.map(o=>[o.facility,o]))
  .values()].slice(0,3)` at line 416 — options are distance-then-time ordered, so this keeps the
  best session per pool). #3 collapse the ~19-row primer to one always-on line ("Just walk in and
  pay in CHF — no booking") + a default-closed `<details>` for POOL TYPES / THE SLOTS, keyed to the
  `kind`s actually present in `a.options`; move starter pools above the fold. Tests: starters are
  distinct facilities; primer is in a closed `<details>`.

- **S2 — Plain-language pass (words, not glyphs; kill dev vocabulary).** *(P1)*
  #4 render the English access word on cards (`accessLabel()` already computes it) and move the
  4-line glyph legend below results into a closed `<details>` on Find/Plan. #5 replace developer
  strings: `valid_as_of`→"Schedule last checked {date}", `(curated)/(scraped)/(mixed)`→"official
  schedule / read from the pool's website / mixed sources", `UNCURATED — schedule unknown`→"Hours
  not listed yet — may well be open, we just don't have its timetable". #8 drop the `[fc]` busyness
  column + its two captions → one line "Busyness: not available yet". Tests: no raw `valid_as_of`/
  `UNCURATED`/`[fc]` token rendered; access words present; legend inside `<details>`.

- **S3 — Pool as a first-class object (the spine).** *(P0)*
  Memoize `/pools` once into a `name → {url, phone, address, lat, lon}` map (the fetch already
  happens at lines 350/474; stop discarding it). #2 make every facility name a link + a one-line
  detail (address, `tel:` phone, `official ↗`) on Find/Plan/Tourist; cards with no catalog match
  degrade to today's plain text (never a broken link). #6 add `official ↗` to closed/uncurated
  status lines (join `s.facility`). #14 add `🗺 directions ↗` from `lat/lon`
  (`google.com/maps/dir/?api=1&destination=…`). Tests: facility name is an `<a href>` when a
  catalog url exists; closed status line carries an official link; a directions link is emitted.

- **S4 — Card & grid visual hierarchy.** *(P1)*
  #7 reorder the card: name (big, linked) → status pill + eligibility **word** (from `o.reason`) →
  distance/price → length demoted to a small tag; make open-vs-later a bold pill not opacity; drop
  the redundant `indoor` kind from the Find badge. #9 wrap the week grid in `overflow-x:auto` +
  `min-width` and render session time ranges as visible cell text (not `title=`-only) so they show
  on touch. Tests: grid has a scroll container and visible times; card renders an eligibility word.

- **S5 — "All pools" becomes a hub + name search.** *(P2)*
  #11 add a "schedule ✓/—" column (intersect the table names with `/swim` facilities) and a
  "Plan ›"/"Find ›" button on rows that have a schedule (switch tab + preselect); rows without one
  are greyed "location only — no timetable yet". #13 add a client-side name filter box over
  `/pools` (`includes` on `p.name`), reused as the jump-to-schedule entry. Tests: schedule column
  present; filter narrows the rendered rows; jump button wired.

- **S6 — Shared context bar + IA cleanup.** *(P2, larger — validate the risky bet in-slice)*
  #12 lift the shared inputs (place/gender/age/radius) into one persistent header bar above the
  tabs; each tab consumes it and adds only its own control (Find: "When"). #10 consolidate the
  trailing meta-stack into one provenance footer per tab and demote the amber "7 of 57" `.warn`
  banner to a neutral data-coverage line (reuse `catalogCount`). #15 **(validate first, do last —
  reversible)** consider demoting "First time here?" from a tab to a collapsible "New here? ▸" panel
  on Find, leaving a Now · Week · All-pools spine; if it risks regressing tourist onboarding, keep
  the tab and record the decision instead. Tests: one shared context bar drives all tabs; footer
  consolidated; whatever IA decision is made is asserted.

## Ledger

| date | slice | status | divergence | tech debt | human review? |
|------|-------|--------|------------|-----------|---------------|
| 2026-07-19 | S1 | done | TO ENTER/TO BRING rows folded into the single always-on line (plan directed collapsing ~19 rows); critic caught that JS `Map`-from-entries keeps LAST not first — dedupe changed to an explicit `.has`-guarded first-wins loop so each starter shows the pool's earliest/next session | none | no |
| 2026-07-19 | S2 | done | `o.valid_as_of` remains as an API-property READ in the script (JSON contract field), so tests assert the display phrase "valid as of" is gone + "Schedule last checked" present, not the raw token's absence | grid day-notes still say terse "NOT closed" (honest, not a dev token) — could align to the new voice in S4; `accessLabel()` returns upper-case (LANE/PUBLIC) — S4 hierarchy pass can sentence-case | no |
| 2026-07-19 | S3 | done | none — All-pools `loadPools` kept its own `/pools` fetch (needs the full array+kinds); the memoized join map is fetched once and shared by Find/Plan/Tourist | All-pools tab still double-fetches `/pools` (fold into `loadPoolsData()` in S5); `esc()` doesn't neutralize `javascript:`/`data:` href schemes — non-exploitable today (url is trusted committed WFS catalog), an http(s)-only allowlist would harden if the source changes | no |
| 2026-07-19 | S4 | done | length badge kept its `lenbadge` class name (restyled small) rather than being renamed — preserves KEEP-invariant intent, avoids churning S1/S2 badge tests; `.celltime` is always visible (stronger than "wider viewports only") | none — but note: a stale `.mypy_cache` produces phantom errors in `catalog_store.py`; `rm -rf .mypy_cache` before mypy clears them (recurring env quirk, not a code defect) | yes |
| 2026-07-19 | S5 | done | scheduled set = catalog names ∩ (`/swim` options ∪ **closed** statuses); `uncurated` statuses EXCLUDED so no-timetable pools honestly read "location only — no timetable yet", never "closed" (invariant #1). Single `Plan ›` jump only (Find form has no pool selector to preselect). **Uncommitted S5 was wiped once by a concurrent `/dev:implement` session's `git reset` (see "Decisions & divergences") and re-applied.** | `jumpToPlan` preselects only if the pool is within the Plan tab's current place/radius (HB 10 km covers all 4 central scheduled pools today); out-of-radius pool lands on nearest instead | yes |
