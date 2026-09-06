# Pool-type filter — Design B: **intent-first**

*Design proposal, 2026-08-02. No code changed. Branch `feat/new-ui`.*

Companion to the literal-taxonomy design. This one argues that the `PoolKind` enum is a
*storage* fact, not an *interface* fact, and that the primary filter surface should ask
**"what do you want to do?"**, resolving that internally to a predicate over
`PoolKind` × `BasinKind` × `FeatureKind`. The literal taxonomy stays reachable, one click
away, for the person who came for the Flussbad specifically.

---

## 0. The measurement that shapes everything below

Before designing anything I counted what is actually in the gold store
(`gold.sqlite`, built 2026-08-01, 57 pools):

| axis | reality |
|---|---|
| `PoolKind` | **100 % populated** — school 18, paddling 13, outdoor 7, indoor 6, river 6, lake 6, thermal 1 |
| `ScheduleFreshness` | `scraped` **7** (6 indoor + Käferberg). Every outdoor / river / lake / paddling / school pool is schedule-less |
| `BasinKind` | 14 basin rows in total. **`lap` appears once.** 11 are `other` (the synthetic `Hauptbecken` the flat scraper emits), 1 `children`, 2 `other` |
| `FeatureKind` | **9 instances across all 57 pools** — 1 sauna, 1 steam_bath, 2 hot_tub, 2 slide, 2 rest, 1 gastronomy |
| `amenities`, `description` | empty / `NULL` on every row I sampled |

Three consequences I will not design around:

1. **`PoolKind` is the only dense axis.** Any intent whose predicate *requires*
   `BasinKind` or `FeatureKind` returns near-nothing today. So each intent needs a
   **dense arm** (PoolKind, always evaluable) and a **sharp arm** (Basin/Feature,
   evaluated when present). The intent is the union of its arms — never the intersection.
2. **31 of 57 pools are `school` + `paddling`.** No swimmer types "Schulschwimmanlage"
   into a filter. A literal 7-way type control spends over half its option set on
   categories that answer nobody's question, and puts the two useful ones (indoor,
   outdoor) alphabetically adjacent to five that are not. This is the single strongest
   argument for intent-first here.
3. **Filtering by anything outdoors selects a set that is 100 % schedule-less.** The
   `no_source` trap is not an edge case in this design — it is the *modal* outcome of the
   most obvious intent. §4 treats it as a first-class result, not an empty state.

---

## 1. The intent vocabulary

Five intents. Each is a named predicate `Intent = (pool, basins, features, session) → bool`,
evaluated **per option row** and **per ghost row**. Within an intent the arms are `OR`.

### `laps` — "Swim laps"

```
pool.kind ∈ {INDOOR, OUTDOOR}                                  # dense arm
  OR  basin.kind == LAP                                        # sharp arm
  OR  basin.lanes != null && basin.lanes >= 1                  # sharp arm
  OR  basin.dimensions.length_m >= 25                          # sharp arm
AND session.access ∈ {LaneSwim, PublicSwim}                    # session arm — see §3
```

Earns its slot because it is the highest-frequency habitual query (a lap swimmer swims
weekly; a Freibad visitor goes when the weather says so) and because it is the one intent
where the *session* matters as much as the pool — a 50 m pool during a club block is not
lap swimming. Note the session arm is **AND**, not OR: it is a constraint on the row, not
an alternative way of matching the pool.

Rejects: river (no measurable lanes, current-dependent), lake (no defined course),
paddling, school (public lap access is not published), thermal (Käferberg is 4 × 8 m).

### `kids` — "With kids"

```
pool.kind == PADDLING                                          # dense arm — 13 pools
  OR  basin.kind ∈ {CHILDREN, NON_SWIMMER, TEACHING}           # sharp arm
  OR  feature.kind == SLIDE                                    # sharp arm
```

Earns its slot on the strength of the dense arm alone: 13 Planschbecken are *only* ever
wanted for this reason, and today they are unreachable except by scrolling a 57-row list.
This intent turns the largest dead category in the catalog into the answer to a real
question. `NON_SWIMMER` is included deliberately — Nichtschwimmerbecken is where a
6-year-old actually swims, and excluding it would make the intent under-answer once
basin data densifies.

### `outdoors` — "Outdoors"

```
pool.kind ∈ {OUTDOOR, RIVER, LAKE, PADDLING}                   # dense arm — 32 pools
  OR  basin.kind == OUTDOOR                                    # sharp arm (Aussenbecken
                                                               #  at an INDOOR pool)
```

Earns its slot because it is the only weather-driven intent and because its sharp arm
does something no literal type filter can: an indoor Hallenbad with an Aussenbecken
**satisfies "outdoors"** while being `PoolKind.INDOOR`. That single case is the whole
thesis of this design in miniature — the type enum gets the answer wrong, the intent gets
it right.

### `warm` — "Warm water"

```
pool.kind == THERMAL                                           # dense arm — 1 pool
  OR  basin.nominal_temp_c >= 30                               # sharp arm
  OR  basin.measured_temp_c >= 30                              # sharp arm
  OR  feature.kind == HOT_TUB                                  # sharp arm
```

Earns its slot on need, not volume. "Warm water for my knee" is a specific, poorly-served,
high-stakes query (rehab, older swimmers, small children), and it is the one intent a user
cannot approximate by any other control in the UI. Today it resolves to Käferberg plus two
hot-tub pools — a small honest answer beats no answer. `measured_temp_c` is preferred over
`nominal_temp_c` when both are present; both are checked so the intent survives either
being null. **30 °C is the threshold**, not 28: 28 is a normal Hallenbad temperature and
would make the intent select everything.

### `spa` — "Sauna & spa"

```
feature.kind ∈ {SAUNA, STEAM_BATH, WELLNESS, HOT_TUB}          # sharp arm only
```

The only intent with **no dense arm** — deliberately. There is no `PoolKind` that implies
a sauna, and inventing one ("indoor pools probably have a sauna") would be a lie of
exactly the kind `ScheduleFreshness` exists to prevent. So this chip is honest-by-
construction: it answers with exactly the pools we have recorded a feature for, and its
count badge (§4) says so. It earns its slot because "a sauna afterwards" is a real,
common Zürich winter outing and because the data, though thin, is *correct* where present.

### Rejected candidates, with reasons

- **"Sunbathe / make a day of it"** (`REST`, `TERRACE`, `GASTRONOMY`) — 3 feature
  instances in the whole store, and almost entirely coextensive with `outdoors`. Revisit
  when the feature extractor densifies; a chip that duplicates its neighbour is worse than
  no chip.
- **"Free entry"** — the right question for the 13 paddling pools and the Flussbäder, but
  price is a `PriceTable` on the facility and "free" is currently the *absence* of an
  entry, not an assertion of one. Cannot be evaluated honestly today.
- **"Quiet / not busy"** — busyness has no data source; the toolbar already carries a
  disabled Busyness toggle with a stated reason. Do not launder an unavailable fact into
  an intent chip.
- **"Accessible"** — `accessibility` is free text on the facility detail, unparsed. A
  chip that silently misses a wheelchair-accessible pool is worse than the current absence.

### Combination semantics — **AND across intents, OR within an intent**

`{laps, outdoors}` means *"outdoor lap swimming"*, not *"laps or outdoors"*. Opinionated
choice; the alternative (OR) was considered and rejected because a chip row that *widens*
as you press more chips inverts every filter convention the user has, and because the
lead-tag count would then go up as you narrow, which reads as a bug.

The cost is real: AND on sparse data produces empty sets fast. It is paid for by the
count badges (§4), which let the user see the collision *before* the click, and by the
relax affordance in the empty state.

---

## 2. Where intent beats taxonomy, and where it fails

**Wins.**

- It reaches the 31 school/paddling pools that a type filter surfaces as noise. `kids`
  makes 13 Planschbecken findable; nothing else in the UI does.
- It crosses the enum where the enum is wrong: an Aussenbecken at a Hallenbad satisfies
  `outdoors`; a `thermal` display-override pool satisfies `warm` *and* has a schedule.
- Five options fit one toolbar row. Seven types plus an "any" do not, and would push the
  existing gender/age controls to a third row on a 1280 px viewport.
- It is translatable as *copy*, not as *vocabulary*. "Freibad" has no English word;
  "Outdoors" does. The literal filter forces every locale to either transliterate Swiss
  German or invent a term that no local uses.
- It degrades honestly: an intent can say "3 pools, 19 more with no published hours",
  which is a sentence. A type filter says "22 outdoor pools" and then shows 22 ghosts.

**Failures — stated plainly.**

1. **The user who wants the Flussbad.** "Outdoors" gives them 32 pools including 13
   paddling pools and the Zürichsee. There is no intent that means "river". This is a
   genuine loss and the escape hatch in §3 exists solely because of it.
2. **Intent chips are editorial claims.** `laps` asserting that every `OUTDOOR` pool is
   lap-swimmable is a *guess* dressed as a filter. Mitigation: the dense arm is
   documented in the chip's hover/`aria-describedby` hint ("indoor and outdoor pools;
   lane data where we have it"), and once `BasinKind` densifies the dense arm should be
   narrowed, not widened.
3. **Sparse data makes AND-combination look broken.** `laps + spa` = 1 pool today.
   Mitigated, not solved.
4. **Vocabulary drift.** Every new intent is a new editorial decision with five
   translations and a predicate to defend. The literal enum is free — it is generated
   from the domain. Intents are a maintained artefact; budget for it.
5. **A locale may not carve the world this way.** "Wellness" and "Spa" are not
   coextensive across de-CH / it-CH. The chips are copy, so this is a translation problem
   rather than a data problem, but it is not nothing.

---

## 3. The escape hatch, and what happens to `lapOnly`

### `[ Exact types ▾ ]` — a popover, not a row

A `Select`-adjacent disclosure at the end of the intent row opens a small popover holding
the **literal 7-way `PoolKind` multi-select**, with live counts, plus a `Clear` link:

```
┌ Exact types ─────────────────────┐
│ ☐ Indoor pool          6         │
│ ☐ Outdoor pool         7         │
│ ☑ River bath           6         │
│ ☐ Lake bath            6         │
│ ☐ Paddling pool       13  ⌀      │
│ ☐ School pool         18  ⌀      │
│ ☐ Thermal bath         1         │
│                        Clear all │
└──────────────────────────────────┘
   ⌀ = no published timetable
```

Rules:

- `kinds` is an **independent axis**, `AND`ed with `intents`. Picking `river` while `laps`
  is pressed means "river baths, and I want to swim laps" — which is empty, and the empty
  state says which of the two to drop.
- A non-empty `kinds` set surfaces back on the primary row as a compact summary chip
  (`Types: River +1 ✕`), so an exact selection is never invisible under a collapsed
  popover. Filter state you cannot see is the bug the phone summary tags already exist to
  prevent; the same rule applies here.
- The popover **never** disables an option with count 0 — a 0 with its reason is
  information; a greyed row is a dead end.
- Labels are locale copy (`kind.river` = "River bath" / "Flussbad" / "Bain en rivière"),
  and de-CH keeps the local term because there it *is* the word people use.

### `lapOnly` → **absorbed into the `laps` intent, field removed**

`lapOnly` today does something its label does not say. In `appdata.applyLap` it filters
option rows to `access ∈ {LaneSwim, PublicSwim}` — i.e. "sessions I am allowed into", not
"lane basins". A user reading *"Lap lanes only"* and getting a Planschbecken public swim
is being misled by the control.

Proposal:

- Delete `lapOnly` from `FilterState`, the toolbar, and the phone summary tags.
- Its behaviour becomes the **session arm** of the `laps` intent (§1), where the label
  finally matches the predicate — because the pool arm and the basin arm are now applied
  alongside it.
- `appdata.applyLap` / `applyLapWeek` are replaced by `applyIntents(answer, intents)` /
  `applyIntentsWeek`, same shape, same purity, same test location. `LAP_FRIENDLY` moves
  into the `laps` predicate.
- **URL back-compat:** `?lap=1` keeps decoding, as a legacy alias producing
  `intents: ['laps']`. `toParams` never writes it again. The existing `urlstate` test that
  asserts `lap=1 → lapOnly` is rewritten to assert `lap=1 → intents:['laps']`; the
  tolerant-decode test (`lap=true` is dropped) is kept verbatim.

This is a net **removal** of one control while gaining five.

---

## 4. Mockups

### Desktop — the toolbar grows a first row

Intent precedes refinement, so it goes **above** the existing strip, not into it. The
existing `.toolbar` becomes a two-row grid; every current field keeps its position on
row 2, so no muscle memory breaks.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ I want to…                                                                             │
│  ╭───────────────╮ ╭────────────────╮ ╭───────────────╮ ╭──────────────╮ ╭───────────╮ │
│  │〰 Swim laps  6│ │👥 With kids 0·13│ │☀ Outdoors 0·32│ │♨ Warm water 1│ │◈ Sauna  2│ │
│  ╰───────────────╯ ╰────────────────╯ ╰───────────────╯ ╰──────────────╯ ╰───────────╯ │
│                                                             [ Exact types ▾ ]  ✕ Clear │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ View          Near              Gender                     Age                         │
│ ┌Day│Pool┐ ‹ Fri 2 Aug ›  ┌───────────┐ ┌Any│F│M│D┐ (Any)(Child)(Teen)(Adult)(Senior)  │
│ └────────┘                └───────────┘ └─────────┘                       ◯ Busyness   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Selected state, `laps` + `outdoors` pressed, with the exact-types summary present:

```
│  ╭═══════════════╮ ╭────────────────╮ ╭═══════════════╮ ╭──────────────╮ ╭───────────╮ │
│  ║〰 Swim laps  6║ │👥 With kids 0·13│ ║☀ Outdoors  0·7║ │♨ Warm water 0│ │◈ Sauna  0│ │
│  ╰═══════════════╯ ╰────────────────╯ ╰═══════════════╯ ╰──────────────╯ ╰───────────╯ │
│  ⟨ Types: River +1  ✕ ⟩                                     [ Exact types ▾ ]  ✕ Clear │
```

**The count badge is the load-bearing detail.** It reads `plannable · unlisted`:

- `6` — six pools match and have a readable timetable.
- `0·32` — thirty-two pools match, **none** publishes hours we can read.
- Counts are computed against the *other* active filters (place, date, gender, age, the
  other pressed intents), so they are true previews of the click, not global constants.
  A chip whose count would drop to `0·0` is still rendered, at 0 — never hidden, never
  disabled. Hiding a chip asserts the world does not contain that thing.

The glyphs are `iconset` line SVGs in `currentColor`, not emoji (the header's globe
comment already establishes this rule): `wave` for laps, `family` for kids, a new
`sun` for outdoors, `water-drop`/a new `thermometer` for warm, a new `steam` for spa.
Three new `PATHS` entries.

### Mobile — drawer row + a rewritten lead tag

The variant-E fusion forbids a bottom sheet and a nav stack, and `phonebar.ts` documents
that **only one thing may be pinned**. So the intent chips go into the existing
`.pbar__drawer` (which already reparents the whole desktop toolbar) as its first row —
and the *pinned* representation is the summary line, which the intents rewrite rather
than lengthen.

Collapsed (the normal state):

```
 ┌──────────────────────────────────────────────┐
 │  Thu   Fri   Sat   Sun   Mon   Tue   Wed     │  ← day strip (scrolls away)
 │   31    1     2     3     4     5     6      │
 │        ▔▔▔▔▔                                 │
 ├──────────────────────────────────────────────┤ ← pinned from here
 │ 3 for laps open to you now · Adult · +2 ▾    │
 └──────────────────────────────────────────────┘
```

The lead tag becomes **intent-aware**: `mobile.openToYou.laps` = "{count} for laps open to
you now". With ≥ 2 intents it falls back to a neutral count plus the intent names as
tags. This buys discoverability with zero new pinned pixels — which is the whole
constraint.

Expanded (tap the summary):

```
 ├──────────────────────────────────────────────┤
 │ 3 for laps open to you now · Adult · +2 ▴    │
 ├──────────────────────────────────────────────┤
 │ I want to…                                   │
 │ ╭═════════════╮ ╭──────────────╮ ╭─────────╮ │
 │ ║〰 Laps    6 ║ │👥 Kids   0·13│ │☀ Out 0·32│→│  ← horizontal scroll, snap
 │ ╰═════════════╯ ╰──────────────╯ ╰─────────╯ │
 │ [ Exact types ▾ ]                    ✕ Clear │
 ├──────────────────────────────────────────────┤
 │ Near   [ Where from?              ]          │
 │ Gender ┌Any│F│M│D┐                           │
 │ Age    (Any)(Child)(Teen)(Adult)(Senior)     │
 └──────────────────────────────────────────────┘
```

The drawer already hides `--view` and `--context` on phone (the day strip *is* the date
control); the intent row is `--intent` and stays visible. `Exact types` on phone opens
**inline inside the drawer** (an expanding block), not as a floating popover — a popover
over a drawer over a pinned bar is the stacking bug `phonebar.ts` was written to avoid.

**Considered and rejected:** an always-visible intent rail replacing the day strip on
scroll. Two horizontally-scrolling rails competing for the same gesture, and it re-opens
the two-sticky-bars problem the phone bar solved once already.

---

## 5. Empty and ghost states — the `no_source` trap

This is where an intent filter can do real damage, because the most attractive chip
(`Outdoors`) selects 32 pools of which **zero** have a schedule.

### The rule

> Filtering by intent filters **options and ghost rows alike, by the same predicate**.
> A ghost row that matches the intent stays on the board. Removing it would erase the
> pool from the answer, and a pool erased by a filter is indistinguishable from a pool
> that does not exist.

So `Outdoors` produces a board with **0 ribbons and 32 ghost rows**. That is the correct,
honest answer, and it must not be rendered by `STATE_NONE` ("Nothing matched here"),
because something did match — we just cannot say when it is open.

### A fourth state block: `STATE_ALL_UNLISTED`

`stateblocks.ts` has three states. Add a fourth, selected when
`options.length === 0 && statuses.length > 0 && every(status) is unlisted`:

```
┌────────────────────────────────────────────────────────────────┐
│ 32 outdoor pools — none publishes hours we can read            │
│                                                                │
│ Zürich's Freibäder, Flussbäder, Seebäder and Planschbecken     │
│ are seasonal and post their hours on their own pages, which    │
│ we don't yet read. They are almost certainly open right now —  │
│ this is not the same as closed.                                │
│                                                                │
│ [ See all 32 on the pool list ]   [ Drop "Outdoors" ]          │
└────────────────────────────────────────────────────────────────┘
```

Distinct tint from `--closed`, sharing the `--hours-not-listed` family. It **reuses**
`unlistedSummaryCard`'s "collapse N identical ghosts into one count" rule rather than
printing 32 paragraphs.

### The relax affordance

When `options.length === 0` and **more than one** filter axis is active, the empty/ghost
block ends with per-axis relax buttons carrying the count each drop would restore:

```
  Nothing open matched all of: Laps · Outdoors · River bath
     [ Drop "Outdoors" → 6 ]   [ Drop "River bath" → 6 ]   [ Clear all → 7 ]
```

This is what pays for the AND semantics of §1. Without it, AND is a trap; with it, AND is
a conversation.

### Chip-level pre-emption

The `0·32` badge means the user *sees the trap before stepping in it*. Pressing a chip
whose plannable count is 0 is then a deliberate act ("show me the outdoor pools anyway"),
and the resulting ghost board is what they asked for.

### What must never happen

- A `no_source` / `awaiting_scrape` pool rendered as **closed** because a filter emptied
  its option list. The existing `isUnlisted` / `stateForStatus` split already prevents
  this; the intent filter must not route around it by dropping the status row.
- `STATE_NONE` shown when statuses exist. Already guarded by `emptyState`; the new
  fourth state slots in *above* it in `update()`'s branch order.

---

## 6. `FilterState` delta, URL encoding, API params

### `FilterState`

```diff
  export interface FilterState {
    place: FilterPlace;
    date: string | null;
    week: string | null;
    gender: "" | "female" | "male" | "diverse";
    age: number | null;
    mode: "day" | "pool";
    selectedPool: FilterPool | null;
-   lapOnly: boolean;
+   /** Active intents, in a CANONICAL order (INTENT_ORDER), deduped. [] = unconstrained. */
+   intents: IntentKey[];
+   /** Exact PoolKind escape hatch, canonical order, deduped. [] = all kinds. */
+   kinds: PoolKindValue[];
    eligibleOnly: boolean;
  }
+
+ export type IntentKey = "laps" | "kids" | "outdoors" | "warm" | "spa";
+ export type PoolKindValue =
+   | "indoor" | "outdoor" | "river" | "lake" | "school" | "paddling" | "thermal";
```

`DEFAULT_FILTER` gains `intents: Object.freeze([])`, `kinds: Object.freeze([])`.

**`merge` needs one change.** It shallow-merges `place` and overwrites everything else —
correct for arrays (a patch supplying `intents` replaces it wholesale, which is what a
chip toggle wants), but the *frozen empty arrays* in `DEFAULT_FILTER` would then be shared
across states. Copy them in `createFilterState`, and normalise (sort into canonical order,
dedupe, drop unknown members) in one exported `normalizeIntents` / `normalizeKinds` so the
URL round-trip is stable and `isStructuralUrlChange` can compare by `join(",")`.

**New pure module `intents.ts`** — the predicate table, the count computation, and
`applyIntents(answer, intents, kinds)`. It is the natural home for exactly the kind of
rule the CRAP gate wants measured, alongside `appdata.ts`. Not in `toolbar.ts`: the
toolbar is layout.

### URL (`urlstate.ts`)

Fixed param order becomes: `view, date, who, age, want, kind, elig, pool`.

```
/?view=day&want=laps,outdoors&kind=river
/?want=kids
/?lap=1                     ← legacy, decodes to want=laps, never written back
```

- `want` — comma-joined `IntentKey`s in canonical order. Decode is **tolerant** like every
  other param: unknown tokens dropped, empty result → key absent from the patch. Never
  throws.
- `kind` — comma-joined `PoolKind` values, same rules, validated against the seven.
- Both omitted when empty, so the default view stays a bare `/`.
- `toParams` writes canonical order so a shared link is byte-stable regardless of click
  order — the existing determinism property.
- Cap the decoded list length (≤ 8) so a hostile URL cannot balloon the predicate set.

**History:** intent and kind changes are *filter* changes, not structural — they should
`replaceState`, matching the existing rule in `isStructuralUrlChange` (view and pool are
structural, everything else replaces). No change to that function.

### API — what the server must add

Evaluate the predicates **client-side**, in `intents.ts`. Do **not** add an `intent=`
param to `/swim`. The intent vocabulary is editorial UI copy with five translations; baking
it into the wire duplicates it, versions it, and makes every future intent a backend
release. With 57 pools and one `/swim` call per day, client-side is free.

But client-side evaluation is **impossible today** — three fields are missing at the
boundary. These are the exact, minimal server changes:

| # | change | why | blocks which intent |
|---|---|---|---|
| 1 | `StatusOut` gains `kind: str` | ghost rows carry only a facility *name*. Without `kind` no intent can filter the 50 schedule-less pools — i.e. the entire `outdoors` / `kids` result set | all |
| 2 | `OptionOut` gains `basin_kind: str` | `SwimOption.basin_kind` **already exists in the domain** (`query.py:242`) and is dropped at the DTO. Pure projection, one line in `_option_out` | `laps`, `kids` |
| 3 | `OptionOut` gains `features: list[str]` and `basin_nominal_temp_c` / `basin_measured_temp_c` | facility features live only on `/pools/{id}` detail (one request per pool). `SwimOption.water_temp_c` already exists in the domain and is likewise dropped | `spa`, `warm` |

Item 1 is non-negotiable and is the one with real consequence — without it, an intent
filter silently deletes 50 of 57 pools from the answer, which is precisely the honesty
failure `ScheduleFreshness` was introduced to prevent. Items 2 and 3 are pure DTO
projections of fields the domain already computes.

Two further notes:

- `/pools` needs **no** change. It already accepts `?kind=`, which the all-pools browser
  tab can keep using directly for the exact-type axis.
- If item 3 is judged too heavy for one slice, ship `laps` / `kids` / `outdoors` first
  (items 1 + 2 only) and gate `warm` / `spa` behind the feature projection. The chips are
  data-driven; a missing predicate input means the chip is not registered, not that it
  renders a lie.

---

## 7. i18n keys

New keys in `locales/en.ts` (the source catalog — every other locale then fails `tsc`
until translated, which is the point):

```ts
// --- Intent filter ---------------------------------------------------------------
"intent.legend":          "I want to…",
"intent.laps.label":      "Swim laps",
"intent.laps.hint":       "Indoor and outdoor pools, and lane data where we have it.",
"intent.kids.label":      "With kids",
"intent.kids.hint":       "Paddling pools, children's and teaching basins, slides.",
"intent.outdoors.label":  "Outdoors",
"intent.outdoors.hint":   "Lidos, river and lake baths — and outdoor basins at indoor pools.",
"intent.warm.label":      "Warm water",
"intent.warm.hint":       "Thermal baths, hot tubs, and basins at 30 °C or more.",
"intent.spa.label":       "Sauna & spa",
"intent.spa.hint":        "Only pools where we have recorded a sauna, steam bath or hot tub.",
"intent.clear":           "Clear filters",

// Chip count badge. Two numbers, never concatenated by the caller.
"intent.count":           "{plannable} with hours, {unlisted} unlisted",
"intent.countShort":      "{plannable}·{unlisted}",   // the visible badge

// --- Exact types (the escape hatch) ----------------------------------------------
"kind.legend":            "Exact types",
"kind.indoor":            "Indoor pool",
"kind.outdoor":           "Outdoor pool",
"kind.river":             "River bath",
"kind.lake":              "Lake bath",
"kind.school":            "School pool",
"kind.paddling":          "Paddling pool",
"kind.thermal":           "Thermal bath",
"kind.noTimetable":       "no published timetable",
"kind.summary": {         // the summary chip back on the primary row
  one:   "Types: {first}",
  other: "Types: {first} +{rest}",
},

// --- The fourth state block ------------------------------------------------------
"state.allUnlisted.title": {
  one:   "{count} pool matched — it publishes no hours we can read",
  other: "{count} pools matched — none publishes hours we can read",
},
"state.allUnlisted.body":  "These are seasonal pools that post their hours on their own pages, which we don’t read yet. They may well be open — this is not the same as closed.",
"state.allUnlisted.seeAll":"See them all on the pool list",
"state.relax.lead":        "Nothing open matched all of:",
"state.relax.drop":        "Drop “{filter}” → {count}",
"state.relax.clear":       "Clear all → {count}",

// --- Phone -----------------------------------------------------------------------
"mobile.openToYouFor": {   // single-intent lead tag
  one:   "{count} for {intent} open to you now",
  other: "{count} for {intent} open to you now",
},
```

Translation notes worth writing into the catalog comments:

- `intent.*.label` are **verb phrases in English, noun phrases in German** ("Bahnen
  ziehen" / "Mit Kindern"). Translators must not be forced into English syntax; each label
  is a whole unit.
- `state.allUnlisted.title` is a plural entry, so `pl` must supply `few`/`many` — 22 is
  `many`, 32 is `many`, 2 is `few`. The compiler will insist.
- `kind.*` keep the **local Swiss-German term in de** (Freibad, Flussbad, Seebad,
  Planschbecken) — that is the word on the sign.
- `intent.countShort`'s `·` separator is punctuation, not grammar (same reasoning as
  `insight.*`'s middot lists), so it stays outside the message.
- No message concatenates a filter name into a sentence except `state.relax.drop`, where
  `{filter}` is a whole quoted label — acceptable because it is quoted, i.e. a citation,
  not a grammatical constituent.

---

## 8. Interaction and a11y

**The multi-select gap.** `chipgroup.js` and `segmentedcontrol.js` are both thin skins
over `_selectgroup.js`, which is **single-select** (one `selected` string, `aria-pressed`
exclusive, roving tabindex). The intent row needs multi-select. Do **not** fork
`buildSelectGroup`; extend it with `props.multiple` so it holds a `Set` instead of a
scalar, and add `createChipGroupMulti` as a third skin. `aria-pressed` per button already
carries multi-select semantics correctly — it is a toggle-button group, not a radio group,
and that is exactly what `aria-pressed` means. `role="group"` stays. This is a ~20-line
change to a file that both existing skins already share.

**Keyboard.** Arrow keys keep roving (`rovingIndex`, unchanged). In multi mode, arrows
**move focus only**; `Space`/`Enter` toggles. This is the WAI-ARIA toolbar pattern and it
differs from the current single-select behaviour where arrow = select — so the two modes
must not share the `choose(next, true)` path. Home/End jump to first/last.

**Focus is never stolen.** Toggling a chip re-renders the board; focus stays on the chip.
The board's `destroy()`/rebuild in `render()` must not run through a `.focus()`.

**Live region.** The result count must be announced. The phone summary's lead tag is
already `aria-live` adjacent; on desktop, add `aria-live="polite"` to the insight bar's
count clause (it already exists as `insight.day.pools`) rather than adding a second live
region — two live regions double-announce.

**Chip hint.** Each chip gets `aria-describedby` → a visually-hidden `intent.*.hint`
span, so a screen-reader user learns the predicate a sighted user gets from the tooltip.
The count badge is inside the button and part of its accessible name via
`intent.count` (the long form, "6 with hours, 0 unlisted") — the visible `6·0` badge is
`aria-hidden`, because "six dot zero" is noise.

**Touch targets.** Chips at 44 px minimum height on phone; the drawer row scrolls
horizontally with `scroll-snap-type: x proximity` and `scrollbar-width: none`, matching
`.pbar__days`.

**Reduced motion.** The popover/inline-expand uses no height transition — the
`grid-template-rows` wedge documented in `phonebar.ts` applies here verbatim. Show/hide.

**Theme.** Chips introduce no colour: selected state reuses `.ui-chip.is-selected`; the
count badge is `var(--muted)`, and the `0·n` "unlisted" half takes the same tint token as
`.stateblock--hours-not-listed`. No hex in any block.

---

## 9. Open questions and risks

1. **Is `laps` ⊇ every `OUTDOOR` pool defensible?** I think yes today (all 7 Zürich
   Freibäder have a Schwimmerbecken) but it is an unverified editorial claim baked into a
   filter. **Ask the owner.** If not, `laps` loses its dense arm and becomes as thin as
   `spa`.
2. **AND vs OR across intents.** I have committed to AND. If usage shows people pressing
   two chips and bouncing off an empty board despite the relax affordance, the fallback is
   *not* to switch to OR but to make the second chip press auto-preview the collision.
3. **Do intents belong in the URL as `want=`, or should the URL carry the resolved
   `kind=` set?** `want=` is more legible and survives a predicate change; a resolved
   `kind=` is stable against vocabulary churn but leaks the mapping into every shared
   link. I chose `want=`; a shared link therefore means "what I wanted", not "what I saw",
   and will re-resolve as the data densifies. That is a feature for a planning tool and a
   bug for a bookmark. Flag it.
4. **The `kids` intent's honesty ceiling.** 13 paddling pools, all `no_source`, all
   seasonal, several closed by October. Pressing `With kids` in November yields 13 ghosts
   for pools that are physically drained. We have no closure data for them. The state
   block copy must not say "may well be open" for a Planschbecken in winter. This may need
   a seasonal caveat keyed off `PoolKind.PADDLING` + month — which is a *guess*, and
   guesses are what this codebase refuses. **Genuinely unresolved.**
5. **Feature data density is the gate on two of five intents.** `spa` and `warm` are
   defensible at 9 recorded feature instances only because they are *correct where
   present*. If the owner reads a 2-pool sauna answer as broken rather than honest, cut
   both chips to three intents and revisit after the feature extractor lands.
6. **New CRAP surface.** `intents.ts` is a predicate table with branching — exactly the
   shape that trips the gate. It must ship with its own vitest suite (one test per
   intent's arms, plus the AND/OR combination), not as an afterthought.
7. **`school` pools are reachable by no intent at all.** 18 of 57 pools are then only
   findable via `Exact types` or the all-pools browser. I think that is right — a
   Schulschwimmanlage is not a place a stranger goes swimming — but it is a deliberate
   demotion of a third of the catalog and should be an explicit owner decision, not a
   side-effect of a chip row.
