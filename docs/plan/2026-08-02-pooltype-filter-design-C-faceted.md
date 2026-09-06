# Pool-type filter — Design C: faceted browsing with live counts

Status: **design proposal, no code written.** Angle C of a set of competing proposals.
Date: 2026-08-02. Branch context: `feat/new-ui`.

---

## 0. The numbers this design is built on

Measured from the live `gold.sqlite` on this branch (57 pools):

| kind | count | `scraped` | `no_source` |
|---|---:|---:|---:|
| `school` (Schulschwimmanlage) | 18 | 0 | 18 |
| `paddling` (Planschbecken) | 13 | 0 | 13 |
| `outdoor` (Freibad) | 7 | 0 | 7 |
| `indoor` (Hallenbad) | 6 | 6 | 0 |
| `river` (Flussbad) | 6 | 0 | 6 |
| `lake` (Seebad) | 6 | 0 | 6 |
| `thermal` (Wärmebad, Käferberg) | 1 | 1 | 0 |
| **total** | **57** | **7** | **50** |

Three consequences that drive every decision below:

1. **31 of 57 pools (54%) are school + paddling** — the two kinds almost nobody
   searching "where can I swim tonight" wants. Today the UI shows all 57 undifferentiated.
   A type facet is not a nicety; it is the single highest-leverage filter in the product.
2. **Only 7 of 57 pools have a schedule at all.** `/swim` can never return an option for a
   Freibad, a Flussbad, a Seebad, a Schulbad or a Planschbecken today. A type filter wired
   naïvely to the board produces *seven ghost rows and zero ribbons* the moment a user picks
   "Freibad" — which reads as "the app is broken", or worse, as "they're all closed". This is
   the `no_source` trap and §4 is entirely about defusing it **before** the click.
3. **The facet is a property of the ROSTER, not of the day's answer.** Counts must be
   computed over `/pools`, which the app already fetches at boot (`app.ts` line ~679). That
   settles the client-vs-server question in §5 before we even argue it.

---

## 1. The facet model

### 1.1 Which facets

Four axes. Three are true facets (multi-select, counted); one is a cross-cutting refinement
that is deliberately **not** a facet.

| # | facet | key | values | source | default |
|---|---|---|---|---|---|
| F1 | **Type** | `poolKinds` | the 7 `PoolKind` values present in the roster | `PoolOut.kind` | `[]` = all |
| F2 | **Water** | `basinKinds` | `lap`, `non_swimmer`, `teaching`, `diving`, `children`, `vario` | `BasinKind` on the facility's basins | `[]` = all |
| F3 | **Comfort** | `features` | `sauna`, `steam_bath`, `wellness`, `slide`, `hot_tub`, `terrace`, `rest`, `gastronomy` | `FeatureKind` | `[]` = all |
| — | **Published hours** | `scheduledOnly` | boolean | derived `ScheduleFreshness == scraped` | `false` |

**F1 ships first and alone.** F2/F3 are designed here so the primitive is built once, but
they need a `/pools` payload widening (§5.2) and should land as a second slice. F1 needs no
server change whatsoever.

**Why `scheduledOnly` is not a facet.** Freshness is a property of *our data*, not of the
place. Rendering it as a counted facet alongside Type invites a user to click "no source, 50"
and conclude those pools don't exist. It is the same category error as rendering
`awaiting_scrape` as "closed" — which this codebase already forbids. It stays a single
labelled toggle, defaulting **off**, sitting outside the facet block, and its effect is
*predicted* by the chip underline (§2.2) rather than discovered by surprise.

**Why `lapOnly` is not folded into F2.** `appdata.ts`'s `LAP_FRIENDLY = {LaneSwim,
PublicSwim}` filters *sessions by access type*. F2 filters *pools by the physical basins they
own*. A pool with a 25 m Schwimmerbecken that runs no lane sessions today matches F2=`lap`
and fails `lapOnly`. Two different questions; keep two controls. (Rename the toggle's label
to "Lap sessions only" to make the distinction legible; the key stays `lapOnly`.)

### 1.2 Multi-select semantics

- **OR within a facet.** `type ∈ {outdoor, lake, river}` = "any open-air water".
- **AND across facets.** `type ∈ {outdoor} ∧ feature ∋ gastronomy`.
- **Empty set means ALL, not NONE.** `poolKinds: []` is the unfiltered default, and is what
  the URL omits. Selecting every chip individually collapses back to `[]` on normalise, so
  `?type=indoor,lake,outdoor,paddling,river,school,thermal` never appears in a shared link.
- A facet whose value set is a *superset* semantics question (a pool having two basin kinds)
  matches if **any** of its values is in the selection — standard multi-valued OR.

### 1.3 The count rule

The classic faceted-search rule, stated precisely because getting it wrong is the #1 facet
bug: **the count shown next to option `v` of facet `F` is computed over the universe filtered
by every constraint EXCEPT `F`'s own selection, then intersected with `v`.**

```
universe        = roster                                   (57 rows from /pools)
                ∩ withinRadius(place, radius_km)           non-facet geo constraint
                ∩ scheduledOnly ? {freshness == scraped} : ⊤

count(F, v)     = | universe ∩ ⋂_{G ≠ F} match(G, sel[G]) ∩ match(F, {v}) |
resultSet       = | universe ∩ ⋂_{G}     match(G, sel[G]) |
```

Concretely: with `type = {outdoor}` selected, the Type chips still read
`Hallenbad 6 / Freibad 7 / Flussbad 6 / …` (excluding Type's own selection), so clicking
"Flussbad" **adds** and the user can predict "13". Meanwhile the Comfort chips read counts
already narrowed to the 7 Freibäder. Without the exclusion rule every unselected Type chip
would read `0` and the facet would be a dead end after the first click.

`eligible_only` / gender / age are **not** part of the count universe: they annotate sessions
(`/swim` is called with `eligible_only=false` and eligibility is a per-row ✓/?/✕ badge), so
they cannot narrow a pool roster.

### 1.4 Two numbers per option, not one

Every chip carries a count **and** an honesty sub-signal:

- `n = count(F, v)` — the number, rendered as a digit.
- `h = |{p ∈ that set : freshness == scraped}|` — rendered as the **fill fraction of the
  chip's 2 px underline**, never as a second digit.

`Freibad 7` with an *empty* underline says, before you click: "seven of these exist; we have a
timetable for none of them." `Hallenbad 6` with a full underline says "six, all with hours."
This is not a new visual idea — it is exactly the board's ribbon-in-a-capacity-sheath
encoding (`--fam-sheath` under `--fam-public`), reused at 2 px. It is the single most
important element of this proposal.

### 1.5 Zero-count handling

| case | rendering |
|---|---|
| `n > 0` | normal chip, `aria-pressed` reflects selection |
| `n == 0` **and not selected** | shown, greyed, `aria-disabled="true"`, **`tabindex` retained** (never the HTML `disabled` attribute), click is a no-op that announces the reason |
| `n == 0` **and selected** | **stays fully enabled.** The escape hatch rule: a selection that has been starved to zero by another facet must remain clickable or the user is trapped |
| option absent from the roster entirely | not rendered (there is no `thermal` row if the roster has none) |

`disabled` on a `<button>` removes it from the tab order and from most screen-reader
virtual-cursor stops, so a blind user gets no explanation for why the option vanished.
`aria-disabled` keeps it announceable and lets `aria-describedby` carry
*"0 within 3 km — widen the area"*.

**Never silently drop a zero option.** A facet whose options appear and disappear as you
click is unlearnable; a stable list with greyed members teaches the shape of the data.

---

## 2. Mockups

### 2.1 Desktop — `blocks/toolbar.ts`

The strip gains a **second line**. Line 1 is unchanged (view / context / near / who / age).
Line 2 is the facet block plus the honesty toggle, laid out `grid-template-columns: 1fr auto`.

```
┌─ .toolbar ───────────────────────────────────────────────────────────────────────────────┐
│ View  [ Day ▮ Pool ]   ‹ Mon · 3 Aug ›   Near [ Wiedikon        ]                         │
│ Who   [ Any ▮ ♀ ▮ ♂ ▮ ⚧ ]   Age [ Any ▮ Child ▮ Teen ▮ Adult ▮ Senior ]   [ ] Lap sessions │
│                                                                                           │
│ Type  ┌───────────────────────────────────────────────────────────────────┐   Hours       │
│       │ ⌂≈ Hallenbad 6  ☀≈ Freibad 7  ⇉≈ Flussbad 6  ⊐≈ Seebad 6          │   [ ] only    │
│       │ ▭≈ Schulbad 18  ◡· Plansch 13  ≋ Wärmebad 1        · Clear ·       │   with        │
│       └───────────────────────────────────────────────────────────────────┘   published   │
│                                                                               hours       │
│       ▸ Water        ▸ Comfort                       (F2/F3, collapsed)                   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

Chip anatomy (the load-bearing detail):

```
   selected                unselected, all scheduled     unselected, none scheduled
  ┌──────────────────┐    ┌──────────────────┐          ┌──────────────────┐
  │ ⌂≈ Hallenbad  6  │    │ ≋  Wärmebad   1  │          │ ☀≈ Freibad    7  │
  │ ████████████████ │    │ ████████████████ │          │ ░░░░░░░░░░░░░░░░ │
  └──────────────────┘    └──────────────────┘          └──────────────────┘
    is-selected:            underline full  =             underline EMPTY =
    filled chip,            6 of 6 have a                 0 of 7 have a
    ink-on-accent           published timetable           published timetable

  zero-count, not selected            zero-count, SELECTED (escape hatch)
  ┌──────────────────┐                ┌──────────────────┐
  │ ⊐≈ Seebad     0  │  aria-disabled │ ⊐≈ Seebad     0  │  fully enabled,
  │ ░░░░░░░░░░░░░░░░ │  greyed        │ ████░░░░░░░░░░░░ │  is-selected + is-starved
  └──────────────────┘                └──────────────────┘  ("0 here — clear or widen")
```

`Clear` appears only when the facet has ≥1 selection. There is **no "All" chip** — an "All"
chip in a multi-select group is ambiguous (is it a value or a command?) and duplicates
`Clear`.

### 2.2 Mobile — `blocks/phonebar.ts`

Variant-E rules hold: **one** pinned element (the summary), no sheet, no nav stack. The
facets live in the existing `pbar__drawer`; the **summary tag row carries the active types as
bare glyphs** so the state is never lost when the drawer closes.

```
┌─ .pbar__days  (scrolls away) ────────────────────────────┐
│  Sun   Mon   Tue   Wed   Thu   Fri   Sat                 │
│   2   ▏3▕    4     5     6     7     8                   │
├─ .pbar__summary  (PINNED — is the disclosure trigger) ───┤
│  6 open to you now · ⌂≈☀≈+1 · 3 km · Any            ⌄   │
├─ .pbar__drawer  (open) ──────────────────────────────────┤
│                                                          │
│  Type  ◂ ⌂≈6  ☀≈7  ⇉≈6  ⊐≈6  ▭≈18  ◡·13  ≋1 ▸          │
│          ███   ░░░  ░░░  ░░░   ░░░   ░░░   ███           │
│                                                          │
│  Who   [ Any ▮ ♀ ▮ ♂ ▮ ⚧ ]                              │
│  Age   [ Any ▮ 8 ▮ 16 ▮ 34 ▮ 70 ]                       │
│                                                          │
│  [ ] Lap sessions only    [ ] Only with published hours  │
└──────────────────────────────────────────────────────────┘
```

The Type row is a **single horizontally-scrollable line** of glyph+count chips (label text
drops below 420 px; the glyph plus the count is the whole chip, and the accessible name still
carries the word). The scroll row is snapped (`scroll-snap-type: x mandatory`) and shows a
partial chip at the right edge so the overflow is discoverable without a chevron.

The summary's type tag is `⌂≈☀≈+1` — up to two glyphs then an overflow count. Zero selections
renders no tag at all (absence = all), keeping the pinned row short on a 390 px phone where
`phonebar.ts` already fights for width.

### 2.3 The icon set — one line per kind

New entries in `components/iconset.js`, same contract as today: 24-viewBox, `fill="none"`,
`stroke="currentColor"`, `stroke-width="1.6"`, `width/height: 1em`, `aria-hidden` by default.
**Shape only, no colour** (see §3.3). All seven are built from the existing `wave` path so
they read as a family; the *modifier above the wave* is what names the kind.

| kind | glyph | why it is legible at 16 px |
|---|---|---|
| `indoor` — Hallenbad | **`⌂≈`** a shallow gabled roof line arching over the wave | the whole distinction is "water with a roof over it"; the roof is the one universally-read shelter mark, and it needs only 3 strokes |
| `outdoor` — Freibad | **`☀≈`** the wave with a small sun (circle + 3 short rays) upper-left | the exact negation of the roof: water under sky. Sun-vs-roof is the strongest 16 px opposition available and survives at 12 px |
| `river` — Flussbad | **`⇉≈`** two parallel bank lines with the wave between them and a single chevron pointing downstream | a Flussbad is water that **moves**; direction is the semantic core. Banks alone would read as a lane; the chevron makes it a current |
| `lake` — Seebad | **`⊐≈`** a jetty — a horizontal deck line on two short piles entering the water from the left, wave to the right | every Zürich Seebad *is* its Steg. The pier reads immediately to a local and reads as "shore" to everyone else; without it, lake and outdoor collide |
| `school` — Schulschwimmanlage | **`▭≈`** the wave enclosed in a closed rounded rectangle | the roof motif *closed into a box* = "belongs to an institution, not to you". Deliberately **not** a mortarboard (US-specific) and not a book (reads as "info") |
| `paddling` — Planschbecken | **`◡·`** a shallow bowl arc with a **low-amplitude** wave and one small dot above it | encodes *small and shallow* by geometry: the wave's amplitude is visibly a third of every other glyph, and the dot is a child. Size-as-meaning survives downscaling because it is relative |
| `thermal` — Wärmebad | **`≋`** the wave with three short rising steam curls above | steam-over-water is the near-universal "hot" mark (onsen/spa signage worldwide); no text needed |
| *(generic)* | **`≈`** the existing `wave` | used for the legend header and the "any pool" affordance |

Design rules for the set:
- **The wave is the constant.** Every glyph shares the identical `wave` path at the identical
  baseline, so at a glance the row reads as "seven kinds of water" rather than seven unrelated
  pictograms.
- **The modifier lives above the wave**, in the top ~9 units of the 24-box, and is never more
  than 4 strokes. At 16 px that's ~6 device px of modifier — the practical floor.
- No glyph contains text, a letter, or a numeral (they'd need per-locale variants).
- All are `stroke`-only so they hint correctly against `--surface` and `--surface-2` in both
  themes and never need a dark-mode redraw (`currentColor` inverts for free — see §3.4).
- `ICON_NAMES` grows by 7; `badges.test.ts` already iterates `ICON_NAMES` and asserts each
  emits a `<svg>`, so the new glyphs are covered by the existing test the moment they land.
  Add one assertion: **every `PoolKind` value has a glyph** (a compile-adjacent completeness
  test, so a new kind in `models.py` cannot ship glyph-less).

---

## 3. How the filter renders on the ribbon, board, legend, and map

### 3.1 The board — preview by dimming, commit by collapsing

Two distinct moments, and conflating them is why most filters feel like ecommerce:

**Hover/focus a chip → PREVIEW.** Non-matching rows get `.is-offfacet`: `opacity: .28`, and
their ribbons repaint with the fill dropped so only the `--fam-sheath` capacity outline
remains. Nothing moves. The user sees *exactly* which rows the click will cost them, in
place, with the board's vertical rhythm intact. 120 ms ease; instant under
`prefers-reduced-motion`.

**Click → COMMIT.** The dimmed rows collapse into **one** summary bar in the board's row
stream, styled like a `stateblocks` row:

```
  ─────────────────────────────────────────────────────────────────
   Hallenbad Oerlikon   ▓▓▓▓▓▓▓▓▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
   Hallenbad City       ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒▒▒▒▒▒▒▒▒▒▒
  ─────────────────────────────────────────────────────────────────
   ▭≈ ◡·  31 pools hidden by type — school, paddling          Show
  ─────────────────────────────────────────────────────────────────
```

Why not simply remove them: the board is a **comparison** surface. Rows vanishing without
trace makes the result set feel arbitrary and makes "did I filter that away, or is it just
not there?" unanswerable — precisely the question the `no_source` states exist to answer
honestly. The collapse bar keeps the count, the kinds, and a one-click undo in the same
visual stream, and costs one row of height instead of thirty-one.

Why not keep them dimmed forever: at 31/57 the board would be 54% grey noise, and the ribbon
board's whole value is scanning density.

### 3.2 The phone list — remove, count in the group header

`poollist.ts` already groups by tier with a count (`plist__group`). Off-facet cards are
**removed** (a phone has no room for a preview state and no hover), and a final group header
reads `Hidden by type · 31` with the glyphs, tappable to clear. `is-muted` stays reserved for
its current meaning (open-but-not-to-you) — do not overload it.

### 3.3 The legend — the metro key becomes the control

`blocks/legend.ts` grows a **fourth group, "Pool type"**, above the existing three. Each row
is `glyph · label · count`, and — the move that makes this native rather than bolted on —
**each row is the facet control**: clicking a legend row toggles that kind. The legend is
already the board's key; making the key interactive is the metro-map idiom (tap a line on the
key, the line highlights).

The colour question, answered flatly: **kind is encoded by SHAPE, access family by COLOUR,
and the two never trade places.** All eight `--fam-*` hues are already spent on access
families, which is the board's primary semantic. Introducing seven kind hues would double-book
the colour channel, force the legend to explain two colour systems, and collide (a "lake"
blue next to a `--fam-public` aqua is unreadable). So:

- `legendModel()` gains `kinds: [{kind, glyph, label, count, scheduled}]`.
- The kind rows use the **glyph slot** where the family rows use the `legend__swatch` colour
  chip — structurally the same row, visually a different channel. No new `--fam-*` token, no
  new colour literal in `tokens.css` (which is the only file allowed hex, grep-asserted).
- The one tint kind ever gets: the `plist__dot` / board label-gutter glyph inherits
  `--ink-2`, and drops to `--muted` when off-facet. Value, not hue.

### 3.4 Dark / light

Zero new tokens. Every glyph is `stroke="currentColor"` and inherits the ink ramp, so it
inverts with the theme automatically — the same reason `iconset.js`'s comment rejects the 🌐
emoji for the language control. The chip underline uses the existing `--fam-sheath` (track)
and `--fam-public` (fill), both already aliased per theme in `tokens.css`. The greyed
zero-count chip uses `--faint` on `--chip`, which has ≥4.5:1 in both ramps.

One real hazard, already documented in `poollist.ts`: a canvas cannot be re-tinted by a CSS
variable after rasterisation. If the facet preview changes ribbon fills, the theme-flip
`repaint()` path must also be triggered on facet commit — otherwise a dimmed ribbon keeps its
old pixels. Reuse the existing `repaint()` (drop `pal`, redraw), don't invent a second path.

### 3.5 The map

**There is no map block today** (grepped: no leaflet/maplibre/mapbox anywhere in
`apps/web`). This is a forward contract for when one lands, not a change to be made now:

- Markers are the same 16 px glyph inside a pin. Same shape system, same file.
- Off-facet pins go to **30% opacity with their labels suppressed — never removed**. Removing
  map pins destroys the spatial context that is the entire reason for a map ("is there
  *anything* on this side of the lake?"). This is the one surface where dimming must be
  permanent, not a preview.
- Zoom-to-fit and clustering operate on the **matched set only**, so the viewport follows the
  filter even though the dimmed pins remain drawn.
- Selecting a kind from the legend highlights its pins with a 1 px `--accent` ring, not a
  fill — the fill channel stays free for the access-family / open-now state.

---

## 4. Empty and ghost states — and the `no_source` trap

Four distinct outcomes. They must **never** collapse into one "no results" message.

**(a) Facet matched nothing at all** (`resultSet == 0`, e.g. Freibad ∧ sauna ∧ 1 km).
New state block:

> **No pools match these filters**
> Nothing here combines *Freibad* and *sauna* within 1 km. Try widening the area or
> dropping a filter. *Not the same as closed.*
> `[ Clear Comfort ]  [ Widen to 5 km ]`

The two buttons are computed: offer to drop the facet whose removal yields the **largest**
non-zero result set, and to widen the radius. A dead end with no exit is the failure mode.

**(b) THE TRAP — facet matched pools, none of which has a schedule.** The common case: user
picks Freibad on a Tuesday in Day mode. Seven pools match; `/swim` returns seven `no_source`
statuses and zero options. Rendered naïvely this is seven grey ghost rows under an empty
board — indistinguishable from "everything is shut".

Required rendering — a **pinned explainer above the ghost rows**, and the ghost rows stay:

```
 ┌───────────────────────────────────────────────────────────────────────┐
 │ ☀≈  7 Freibäder here — we have no published timetable for any of them │
 │     yet. That is NOT the same as closed; most are open all summer.    │
 │     Each row links to the pool's official page.          [ Why? ]     │
 └───────────────────────────────────────────────────────────────────────┘
   Freibad Letzigraben        Hours not published yet →  official page ↗
   Freibad Heuried            Hours not published yet →  official page ↗
   …
```

Non-negotiables here, all of which follow from existing project invariants:

- The word "closed" must not appear. `rowStatusLine` already routes `no_source` /
  `awaiting_scrape` to their own labels; the explainer must not re-merge them.
- `awaiting_scrape` and `no_source` keep **separate** sentences in the explainer when the
  matched set mixes them ("hours not published yet" vs "no timetable source at all").
- The `PoolOut.url` official-page link is the fallback answer, and it is non-null on all 57
  pools. This is the only case in the product where we hand the user off — do it prominently,
  not as a footnote.
- **Do not auto-enable `scheduledOnly` to "fix" the empty board.** Silently discarding 50 of
  57 pools because we lack data about them is exactly the dishonesty the three-state
  freshness model exists to prevent.

**(c) Prediction, so (b) is rare.** The chip underline (§1.4) shows the empty sheath *before*
the click, and the chip's accessible name says "0 with published hours". When
`scheduledOnly` is ON, that empty sheath becomes a hard `n == 0` and the chip greys out under
the §1.5 rule — so the toggle converts a soft warning into a hard, explained block. That
coupling is the whole reason the underline and the toggle are designed together.

**(d) `/swim` failed.** Untouched: `api.ts`'s `EMPTY_ANSWER` fallback still applies, and the
facet UI must not reinterpret a fetch failure as "0 match". Guard: only render (a) when the
answer arrived (`warnings` present / a real response), otherwise render the existing failure
path.

---

## 5. Where the counts come from

### 5.1 Decision: **client-side, from the roster already in memory.** No new endpoint.

The argument, honestly costed:

**For the client roster.** `/pools` returns all 57 rows and `app.ts` already fetches it once
at boot to build the pool picker. Measured payload for the current `PoolOut` shape: ~11 KB
raw, ~3 KB gzipped — already paid for. Counting three facets over 57 rows is 57 × ~8
predicate evaluations ≈ 500 operations, sub-millisecond, which means counts can update on
**hover-preview** and on every keystroke of the radius slider with no debounce, no spinner,
and no loading state for a number. That responsiveness is not a nice-to-have: a facet count
that arrives 200 ms after the chip is the reason server-faceted UIs feel sluggish.

**Against a server facet endpoint.** A `GET /facets?…` would (i) add a round-trip on the
critical path of every filter interaction, (ii) create a *second* projection of the same gold
store that can disagree with `/pools` (two sources of truth for one number — the exact
failure mode `CLAUDE.md` spends a section forbidding), (iii) need its own router, service,
model, tests and CRAP budget, and (iv) buy nothing at n=57. The honest break-even for
server-side faceting is roughly n > 5 000 rows or facet cardinality the client cannot hold —
neither is remotely in view, and "possibly other cities in the future" multiplies 57 by a
small integer, not by a thousand.

**The cost I am accepting.** Facet correctness now lives in the browser, in TypeScript, under
the vitest/crap_ts gate rather than pytest. Mitigation: the counting logic goes in a new
**pure** module `static/js/facets.ts` (no DOM, no fetch), fully unit-tested — *not* in
`app.ts`, which is one of the four coverage-excluded entrypoints and would let an untested
branch hide. `crap_ts` will score it; keep `facetCounts` under cc 5 by table-driving the
predicates.

### 5.2 The one server change that F2/F3 need

`PoolOut` currently exposes `kind` and `freshness` — enough for **F1 and the underline, with
zero backend work**. F2/F3 need basin and feature kinds, which are already in the loaded
`facility_doc` blob. Widen the model rather than adding an endpoint:

```python
class PoolOut(BaseModel):
    ...
    basin_kinds: list[str] = []     # sorted, deduped BasinKind values
    feature_kinds: list[str] = []   # sorted, deduped FeatureKind values
```

Computed in `list_pools` from data already in hand. Cost: ~57 × 6 short tokens ≈ +2 KB raw,
+400 B gzipped. That is a payload change to an existing projection, not a second source of
truth — materially different from a facet endpoint.

### 5.3 The `/swim` side

`OptionOut` **already carries `kind`** (`service.py` line 65: `kind=option.facility_kind.value`),
so filtering the board's option rows by type needs no API change at all. `StatusOut` does not
— it carries only `facility` (a display name), so a ghost row can only be typed by joining on
name against the roster. Name joins are exactly the fragility `facility_id` exists to remove.

**Minimal, recommended server delta (2 lines + tests):**

```python
class StatusOut(BaseModel):
    facility: str
    facility_id: str   # NEW — join key, mirrors OptionOut
    kind: str          # NEW — so a ghost row can be typed without a name join
    ...
```

**Recommended against:** adding `kind=` to `GET /swim`. It would move filtering server-side
for a payload that is already small, and it would make the *board* the filter's home when the
filter is fundamentally about the roster. Client-side keeps preview-dimming (§3.1) possible —
you cannot preview a server-side filter without fetching it.

### 5.4 `FilterState` delta

`filterstate.js` / `.d.ts`:

```ts
export interface FilterState {
  place: FilterPlace;
  date: string | null;
  week: string | null;
  gender: "" | "female" | "male" | "diverse";
  age: number | null;
  mode: "day" | "pool";
  selectedPool: FilterPool | null;
  lapOnly: boolean;
  eligibleOnly: boolean;
  // --- NEW: the facet axes. `[]` means ALL, never NONE. ---
  poolKinds: PoolKindToken[];    // F1
  basinKinds: BasinKindToken[];  // F2 (slice 2)
  features: FeatureToken[];      // F3 (slice 2)
  scheduledOnly: boolean;        // the honesty toggle, default false
}
```

`merge()` rules — spell them out, because arrays are where immutable-merge helpers rot:

- Arrays are **overwritten wholesale**, like `selectedPool`; they are never concatenated and
  never shallow-merged (only `place` is shallow-merged, and that stays the sole exception).
- `createFilterState` **normalises**: dedupe, drop unknown tokens, sort ascending, and
  collapse a full set to `[]`. Normalising on construction is what makes URL round-tripping
  and `serialize()` equality stable, and it is one pure function that is trivially tested.
- `DEFAULT_FILTER` gains `poolKinds: Object.freeze([])` &c. — freeze the arrays, matching how
  `place` is already frozen, so the zero state cannot be mutated by a careless `.push()`.

### 5.5 URL encoding — `urlstate.ts`

Extend the fixed param order to:

```
view, date, who, age, type, water, feat, lap, hours, elig, pool
```

- **Comma-joined, sorted values**, one param per facet: `?type=lake,outdoor,river`.
  Comma over repeated params (`type=lake&type=outdoor`) because `urlstate.ts`'s contract is a
  *deterministic, stable string*, and `URLSearchParams` ordering with repeats is far easier to
  get subtly wrong. Comma is not percent-encoded by `URLSearchParams` in practice, so the link
  stays human-readable — which the module's own header calls out as a goal.
- **Omitted when empty**, and omitted when the selection covers every known value (that is
  the same state as empty after normalisation). A default view stays the bare `/`.
- `hours=1` for `scheduledOnly` (matching the existing `lap=1` / `elig=1` style).
- **Decoding is total and tolerant**, exactly like the existing params: split on comma, drop
  unknown/empty tokens, cap at 12 tokens, drop the param entirely if nothing survives. An
  attacker-supplied `?type=<script>` decodes to `[]`, not to a render.
- Round-trip examples:

```
  /?type=outdoor                         one kind
  /?type=lake,outdoor,river&hours=1      open-air water that actually has hours
  /?view=pool&pool=hallenbad-city        unchanged
  /                                      every default, including all facets cleared
```

- `isStructuralUrlChange` (`appdata.ts`) stays **unchanged**: a facet toggle is a filter
  change, so `replaceState`, not `pushState`. Adding facets to the structural test would make
  Back unusable after five chips — precisely the trade-off that function's docstring argues.

---

## 6. i18n

New keys in `locales/en.ts` (the source catalog); every other locale must supply all of them
or `tsc` fails, and `parity.test.ts` enforces it.

### 6.1 Kind labels — native words, not translations

```ts
"kind.indoor":   "Indoor pool",
"kind.outdoor":  "Outdoor pool",
"kind.river":    "River bath",
"kind.lake":     "Lake bath",
"kind.school":   "School pool",
"kind.paddling": "Paddling pool",
"kind.thermal":  "Thermal bath",
```

with `kind.<v>.long` tooltips carrying the German term for the en/pl/fr/it reader
(`"Indoor pool (Hallenbad)"`) — a visitor reads *Hallenbad* on the building, and hiding that
word helps nobody. The **de catalog uses the native words directly** (`Hallenbad`, `Freibad`,
`Flussbad`, `Seebad`, `Schulschwimmanlage`, `Planschbecken`, `Wärmebad`) with no gloss, and
the chip shows the short form (`Schulbad`) at ≤ 900 px.

### 6.2 Counted strings — CLDR plurals

```ts
"facet.count": { one: "{count} pool", other: "{count} pools" },
"facet.withHours": {
  one:   "{count} with published hours",
  other: "{count} with published hours",
},
"facet.hidden": {
  one:   "{count} pool hidden by type",
  other: "{count} pools hidden by type",
},
"state.facet.noHours.body": {
  one:   "{count} {kind} here — we have no published timetable for it yet. That is not the same as closed.",
  other: "{count} {kind} here — we have no published timetable for any of them yet. That is not the same as closed.",
},
"facet.results": { one: "{count} pool matches", other: "{count} pools match" },
```

Polish needs all four categories or it will not compile — the whole point of `Plural<'pl'>`:

```ts
// locales/pl.ts
"facet.count": {
  one:   "{count} basen",     // 1
  few:   "{count} baseny",    // 2–4, 22–24 …
  many:  "{count} basenów",   // 5–21, 25 …
  other: "{count} basenu",    // fractional
},
```

`fr` and `it` need `one | many | other` (they gained `many` in CLDR 42 — `plurals.test.ts`
already guards this against drift).

### 6.3 Chrome and a11y strings

```ts
"facet.type":            "Type",
"facet.water":           "Water",
"facet.comfort":         "Comfort",
"facet.clear":           "Clear",
"facet.clearAll":        "Clear filters",
"facet.showHidden":      "Show",
"facet.zeroReason":      "None within {radius}",
"facet.zeroReasonHours": "None with published hours",
"facet.starved":         "0 match with your other filters — clear it or widen the area",
"toolbar.scheduledOnly": "Only pools with published hours",
"toolbar.scheduledOnlyReason":
  "Hides the {count} pools we have no timetable for. They are not closed.",
"legend.group.poolType": "Pool type",
"state.facet.none.title": "No pools match these filters",
"state.facet.none.body":
  "Nothing here matches. Try widening the area or dropping a filter. Not the same as closed.",
"a11y.facetChip": "{kind}, {count} pools, {scheduled} with published hours",
```

Two localisation notes worth pinning in the catalog comments:

- **Never build a chip label by concatenation.** `"{count} {kind}"` must be one translatable
  unit (Polish and German both inflect the noun after a numeral); the facet chip therefore
  renders label and count as two *separate* DOM nodes with the number in `.tnum`, and the
  screen-reader name comes from the single `a11y.facetChip` message. This is the same rule
  `insight.*` already follows (a `·`-separated clause list, never an assembled sentence).
- **Counts go through `Intl.NumberFormat`**, not `String(n)` — trivially true at n<100, but
  the rule (`datefmt.ts` owns every number rendering) has no exceptions worth carving.

---

## 7. Interaction and accessibility

### 7.1 A new primitive: `components/facetgroup.js|ts`

**Do not extend `_selectgroup.js`.** It is a *single*-select roving group: it keeps one
`selected` value, sets `aria-pressed` on exactly one button, and moves the roving tabindex to
the selection. Multi-select is a genuinely different contract (n pressed buttons, tabindex
tied to *focus*, not to selection) and bending the shared file would put a branch through both
`SegmentedControl` and `ChipGroup` — a CRAP-gate regression on a file two components depend on.

`createFacetGroup(el, { props: { items, selected: string[], label }, onChange })` where each
item is `{ value, label, icon, count, scheduled, disabled }`.

### 7.2 Keyboard

| key | behaviour |
|---|---|
| `Tab` | enters the group once (roving tabindex), leaves it once |
| `←` `→` `↑` `↓` | move focus between chips, **without selecting** (multi-select must not select-on-focus, unlike the radio-style `SegmentedControl`) — reuse `keynav.rovingIndex` for wrap-around only |
| `Home` / `End` | first / last chip |
| `Space` / `Enter` | toggle the focused chip |
| `Escape` | clear this facet, focus stays put |
| `Backspace` / `Delete` | clear this facet (mirrors a token-input mental model) |

`Escape` clearing the facet must **not** also close the phone drawer — stop propagation, or a
Swiss-keyboard user clears their filters and loses the panel in one keystroke.

### 7.3 ARIA

- Group: `role="group"` + `aria-label` from `facet.type`. Not `listbox` — these are toggle
  buttons that filter a page, not options that select a value into a field.
- Chip: `<button type="button" aria-pressed="true|false">`, accessible name from
  `a11y.facetChip` (`"Freibad, 7 pools, 0 with published hours"`) so a screen-reader user
  gets both numbers **on focus**, where a sighted user gets them from the digit and the
  underline. Parity of information across channels is the point.
- Zero-count, unselected: `aria-disabled="true"` + `aria-describedby` → a visually-hidden span
  with `facet.zeroReason` / `facet.zeroReasonHours`. **Not** the `disabled` attribute (§1.5).
- Zero-count, selected: enabled, `aria-describedby` → `facet.starved`.
- The underline is decorative (`aria-hidden`) — its meaning is already in the name.
- **One `aria-live="polite"` region for the whole toolbar**, announcing only the *result*
  (`facet.results`), debounced ~350 ms. Announcing each chip's count on every change would
  produce a continuous stream of numbers and is the standard way faceted search becomes
  unusable with a screen reader.
- Focus is never moved by a filter change. The board re-renders under the user's focus.

### 7.4 Motion, touch, density

- Preview dimming: 120 ms opacity; **no transition** under `prefers-reduced-motion` (the
  state change still happens, instantly). The collapse bar does not animate height —
  `phonebar.ts` already documents a `grid-template-rows` transition wedging in a throttled
  frame and shutting a drawer permanently; do not repeat it.
- Touch targets ≥ 44 px tall on the phone chip row even though the chip *looks* 28 px
  (padding, not height).
- Chips never reflow between renders: the count is in a fixed-width `.tnum` slot so
  `6 → 13 → 7` does not jitter the row.

---

## 8. Open questions and risks

1. **A pool can be two kinds; `PoolKind` is single-valued.** Seebad Enge is a lake bath *with*
   an outdoor pool; the Letten complex is river *and* outdoor (the roster literally holds both
   "Flussbad Unterer Letten" and "Flussbad Unterer Letten (Flussteil)"). A single-valued facet
   will mislead someone. **Recommendation: do not model multi-kind now** — the gold store is
   single-valued and inventing a second kind in the UI would be a source of truth outside the
   store. Mitigate with F2 (Water), and revisit if the WFS ever exposes a secondary type.
2. **54% of the roster is school + paddling. Should they be excluded by default?** Strong
   recommendation: **no.** Silently hiding 31 pools is the same class of dishonesty as
   rendering `no_source` as "closed". Instead: order the chips by usefulness
   (Hallenbad, Freibad, Seebad, Flussbad, Wärmebad, Schulbad, Planschbecken), and offer **one
   visible, undoable preset** — a `Swimmable` chip that sets
   `type = {indoor, outdoor, lake, river, thermal}` and renders as selected so its effect is
   never invisible. Open question for the owner: does the preset earn its complexity, or is
   chip ordering enough?
3. **The `no_source` explainer could still read as "the app is broken."** We have no
   telemetry, so we cannot measure this. The mitigation is the official-page link being
   *prominent*, not a footnote — accept the residual risk and revisit if the outdoor scrape
   lands (which would move 7 Freibäder from `no_source` to `scraped` and largely dissolve the
   problem).
4. **Facet correctness moves to the TS chain.** Counting in `facets.ts` means the rule in §1.3
   is guarded by vitest, not pytest. Accepted (§5.1), with the mitigation that the module is
   pure and must not be added to `vitest.config.ts`'s exclusion list — "narrow that list,
   never widen it."
5. **`ScheduleFreshness` is derived at read.** If `freshness_of` ever becomes expensive or
   changes semantics, the underline silently changes meaning. Pin it: a test asserting the
   underline denominator equals `PoolsOut` rows with `freshness == "scraped"`.
6. **i18n parity is a hard gate.** ~30 new keys × 5 locales, with 4 Polish plural forms.
   `parity.test.ts` and `tsc` will both fail until every catalog is complete — this is a real
   slice cost, not a rounding error, and it should be sized as such.
7. **Chip row width at 900–1100 px.** Seven chips with glyph + word + count is ~640 px; the
   toolbar's second line will be tight against the Hours toggle. The label-drop breakpoint
   (§2.2) may need to fire on desktop too. Worth a quick bench before committing to two lines
   rather than a disclosure.
8. **Should the legend be interactive on mobile?** §3.3 makes legend rows the desktop
   control. On a phone the legend is a separate collapsed block; making it a *second* filter
   surface risks two controls disagreeing. Recommendation: legend is read-only on phone; the
   drawer is the only phone control.
