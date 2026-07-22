---
type: summary
created: 2026-07-19
links: ["[[2026-07-19-ux-usability-pass]]", "[[ux-presentation]]", "[[2026-07-19-ux-ascii-design]]"]
---

# UX usability pass — what exists now

Implemented 2026-07-19 via /dev:implement (6 slices, all gates green: 205 tests,
coverage 94.86% ≥ 91 floor, mypy strict clean, CRAP clean). Origin: after the first UI shipped,
the owner found it unfriendly; a 5-lens UX critic panel produced a prioritized backlog, executed
here. Presentation-only — everything is in the single-file `apps/web/api/ui/router.py`; no
domain/API/endpoint change.

## Core diagnosis (fixed)

**The pool was not a first-class, actionable object** — facility names were inert text with no
link/detail, though the masthead promised "the official link" and `/pools`/catalog already carried
`url`/`phone`/`address`/`lat`/`lon`. Everything else (one-pool tourist, glossary wall, glyph-decoder
tax, wrong hierarchy) were symptoms of building around sessions/glyph-axes instead of actionable pools.

## What shipped, per owner complaint

- **(a) tourist "one pool"** → S1 dedupes starter pools to distinct facilities (first-wins loop →
  each pool's earliest/next session).
- **(b) primer too big** → S1 collapses the ~19-row primer to one line + default-closed `<details>`;
  starters above the fold.
- **(c) no detail / website link** → S3 memoizes `/pools` into a `name→{url,phone,address,lat,lon}`
  join map (`loadPoolsData()`/`poolInfo()`); facility names are links with a one-line detail
  (address · `tel:` · `official ↗` · `🗺 directions ↗`), incl. on closed/uncurated status lines.
  S5 makes "All pools" a hub: a "schedule ✓ / location only" column (catalog ∩ `/swim` facilities,
  uncurated excluded per invariant #1), a `Plan ›` jump (`jumpToPlan`/`planPreselect`), and a
  case-insensitive name filter; `/pools` now fetched once total.
- **(d) jargon** → S2 renders access as English words, moves the glyph legend into a closed
  `<details>`, kills dev vocabulary (`valid_as_of`→"Schedule last checked", `UNCURATED`→"Hours not
  listed yet…", `curated/scraped`→plain words), and drops the `[fc]` column for one plain busyness
  line. S4 reorders the card (name→status pill + eligibility *word*→distance/price; length demoted to
  a tag; open-vs-later a colored pill not opacity) and makes the week grid scroll on mobile with
  visible times. S6 lifts place/gender/age/radius into one shared context bar (tabs continue the
  session; active tab re-runs on change) and demotes the amber coverage banner to a neutral line.

## Invariants kept

Three terminal states stay distinct (wording only changed); busyness never faked; length-badge kept
(demoted, not deleted); inline decode-at-point-of-need retained; zero-dependency single-file UI.

## IA decision (#15)

"First time here?" was KEPT as a tab (not demoted to a Find panel) — it carries onboarding Find
lacks (primer, deduped starters, inline decode, kept-visible closed pools, `eligible_only=false`
mode). Nav spine: Now · Week · Visit · All-pools.

## Open backlog / tech debt

- **Registry not wired at runtime** (from [[ux-presentation]]) — UNCURATED / "location only" depend
  on it; highest-leverage cross-cutting fix.
- Find is now **location-scoped** (radius-filters; clear-radius = distance without filter); single
  shared radius default 10 km (was Plan 10 / Tourist 5) — confirm intent.
- Inactive tabs show results from the previous context until re-run; shared-context re-run fires on
  `change` not `input` (a debounce would be nicer).
- `esc()` doesn't neutralise `javascript:`/`data:` href schemes (non-exploitable today — trusted
  committed catalog). UI tests assert served-HTML source strings, not runtime DOM (a jsdom/Playwright
  harness would strengthen them).

## Process note

A concurrent `/dev:implement` session (the `lane-reservations` plan) ran on the same repo and its
`git reset` wiped uncommitted S5 once; S5/S6 were committed immediately after passing to protect
them. Lesson: use **worktree isolation** for concurrent implement loops.
