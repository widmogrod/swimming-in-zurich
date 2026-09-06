# Pool-type filter — Design A: taxonomy-first

Status: **design proposal, not implemented.** Angle: interrogate the taxonomy before
drawing the control. Sibling designs may argue other angles; this one argues that the
question "which chips?" is downstream of "which axis, and is `PoolKind` even it?".

---

## 0. The measurement that decides everything

Before proposing chips, count the roster. From `data/catalog.json` (57 entries) and the
built `gold.sqlite`:

| PoolKind   | pools | pools with ANY schedule rule | with a lane plan |
| ---------- | ----: | ---------------------------: | ---------------: |
| `school`   |    18 |                            0 |                0 |
| `paddling` |    13 |                            0 |                0 |
| `indoor`   |     6 |                        **6** |                6 |
| `outdoor`  |     7 |                            0 |                0 |
| `river`    |     6 |                            0 |                0 |
| `lake`     |     6 |                            0 |                0 |
| `thermal`  |     1 |                        **1** |                1 |
| **total**  |    57 |                        **7** |                7 |

Two facts fall out, and they drive the whole design:

1. **31 of 57 pools (54%) are `school` + `paddling`** — a Schulschwimmanlage (club/school
   reserved, no public timetable) and a Planschbecken (a 30 cm wading basin). Neither
   answers "where can I go swimming?". Giving them 2 of 7 chips spends 29% of the control
   on the majority of the roster that helps nobody.
2. **Only 7 pools have a schedule, and all 7 are `indoor`/`thermal`.** Every other kind is
   100% `no_source`/`awaiting_scrape` today. So a naive seven-chip row means *five of seven
   chips lead to an all-ghost result*. A type filter is therefore, right now, mostly a
   **ghost-state design problem wearing a filter costume** (§3).

Also measured, for the "should features be part of this?" question (§1.3): across all 57
pools gold holds **6 `Feature` rows total** (2 hot_tub, 2 slide, 2 rest, 1 sauna, 1
steam_bath, 1 gastronomy) and **15 basins with a kind, of which 13 are `other`, 1 `lap`,
1 `children`**.

---

## 1. The taxonomy argument

### 1.1 `PoolKind` is a registry taxonomy, not a user question

`PoolKind` is the WFS `Anlagetyp` — a municipal asset classification. It answers
"what kind of installation does the Sportamt own?". The user's questions are different,
and there are exactly three of them:

- **Q1 "Do I want to be outside?"** — a weather/season decision, essentially binary, with
  one meaningful refinement (a chlorinated open-air pool is a different product from the
  Limmat).
- **Q2 "What am I doing there — laps, or the kids?"** — that is `BasinKind`, *not*
  `PoolKind`. A Freibad contains both a 50 m lap basin and a children's pool.
- **Q3 "Is there a sauna after?"** — that is `FeatureKind`.

Q1 maps onto `PoolKind`. Q2 and Q3 do **not**, and folding them into one "type" chip row
would be the classic taxonomy error of unioning three orthogonal axes because they all
sound like nouns. **They are three axes. Only one of them ships.**

### 1.2 Axis A — WATER (ships now)

Four user-facing values, single-select, `All` is the default:

| UI value  | label (en)      | `PoolKind` members    | why grouped                                                                                                                       |
| --------- | --------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `""`      | **All**         | everything not hidden | default                                                                                                                            |
| `indoor`  | **Indoor**      | `indoor`, `thermal`   | Käferberg's `thermal` is already a *display override* on an indoor Hallenbad; it is roofed, ticketed and scheduled like the other 6 |
| `open`    | **Open-air**    | `outdoor`             | Freibad: chlorinated, fenced, seasonal, has a cash desk                                                                            |
| `natural` | **Lake & river**| `lake`, `river`       | Seebad + Flussbad: natural water, temperature-driven, share a mental model ("is it warm enough?") and share the Baditicker feed     |

**Why 4 and not 7:** `river` and `lake` split a group of 12 pools that a user never chooses
*between* at filter time — you decide "natural water" first and pick by location second.
Keeping them separate would cost a fifth chip to express a distinction the card badge (§2)
already carries for free.

**Why single-select, not multi-select.** The decision is genuinely one-of: "am I swimming
outside today". Multi-select buys ~one useful combination (`open` + `natural` = "anything
outdoors") at the cost of 16 states, a clear affordance, a plural URL token, and an
ambiguous empty state. `All` + the per-card type badge covers that combination. If usage
disproves this, the migration is **additive** — the URL token becomes a comma list and the
ChipGroup becomes multi-select, with no server change (§4).

### 1.3 Axis B — PURPOSE (does NOT ship: the data would make it lie)

`BasinKind` (lap! diving!) and `FeatureKind` (sauna!) are the same family as the *existing*
`lapOnly` toggle, and the honest name for that family is "what do you want to do", not
"type". But look at the counts: 1 basin in the whole gold store is typed `lap`; 1 pool has
a `sauna` row.

**Rule this design proposes as a hard invariant:** *a filter may only be offered on a field
whose absence is distinguishable from unknown.* Right now "no sauna row" and "we never
scraped the amenity list" are the same bytes. A "Sauna" chip would return 1 pool and imply
the other 56 have none — the schedule-honesty invariant (`no_source` ≠ closed) applied to
filters.

The project already has the correct pattern for this: the **disabled Busyness toggle** with
a `reason` (`toolbar.busynessReason`). So Axis B ships as exactly one more disabled toggle,
`toolbar.extras` ("Sauna & extras") with a reason string. It costs nothing, it is honest,
and it pre-announces the axis so the eventual real control has a reserved slot.

`lapOnly` stays exactly as it is. When `BasinKind` coverage is real, `lapOnly` is *promoted*
into a "Swim for: Laps / Family / Diving" select in the same slot — a replacement, not a
second chip row.

### 1.4 What gets collapsed, hidden, and defaulted

| treatment                             | members                                | rationale                                                             |
| ------------------------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| **Collapsed** into a broader chip     | `thermal`→Indoor, `river`+`lake`→Natural | distinction survives on the card badge, not in the control             |
| **Hidden from the default result set**| `school` (18), `paddling` (13)          | not places an adult goes swimming; 0 schedules; 54% of roster noise    |
| **Default state**                     | `water = ""` (All), `includeMinor = false` | one visible default, no pre-applied type filter                     |

**Hidden must not mean silent.** The hidden set is disclosed by a persistent, one-click
line in the toolbar — "31 school & paddling pools hidden · Show them" — which flips
`includeMinor`. That is the difference between an editorial default and a lie. This is the
single most contentious call in the proposal (§7 Q1).

Note the consequence: `includeMinor` is *not* a fifth chip. It is a different kind of
control (an inclusion escape hatch), and rendering it as a peer chip would suggest
"Paddling pools" is a thing people search for.

---

## 2. The control

Component pick: **`components/chipgroup.js`**, not `segmentedcontrol.js`. Both wrap
`_selectgroup.js` (same `role=group` / `aria-pressed` / arrow-key model), but `blocks.css`
already wraps `.toolbar__field .ui-chipgroup` at ≤560 px (lines ~770–774) while `.ui-seg`
does not. Four items with labels as long as "Lake & river" will clip in a segmented
control on a 390 px phone. Segments stay for View (2 items) and Gender (4 short items).

Placement in the strip: **after the context slot, before Near.** Water is a *context*
refinement (what/where), not a *person* refinement (who/how old). Current order
`[View][context][Near][Gender][Age][lap][busyness]` becomes
`[View][context][Water][Near][Gender][Age][lap][busyness][extras]`.

### Desktop toolbar

```
┌ Search filters ───────────────────────────────────────────────────────────────────────┐
│ View          Water                                    Near         Gender             │
│ ┌────┬────┐   ( All )(Indoor)(Open-air)(Lake & river)  ┌──────────┐ ┌───┬───┬───┬───┐  │
│ │Day │Pool│      ▲ pressed                             │Wiedikon ⌄│ │Any│ ♀ │ ♂ │ ⚧ │  │
│ └────┴────┘                                            └──────────┘ └───┴───┴───┴───┘  │
│                                                                                        │
│ ‹  Mon 3 Aug  [today]  ›        Age  ( Any )( Child )( Teen )( Adult )( Senior )       │
│                                                                                        │
│ [ ] Lap lanes only    [ ] Busyness — no data source yet    [ ] Sauna & extras — no     │
│                                                                data source yet         │
│ ────────────────────────────────────────────────────────────────────────────────────── │
│ 31 school & paddling pools hidden · [Show them]                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

With `water=open` selected, the strip gains an inline honesty note (data-driven, §3):

```
│ Water   ( All )(Indoor)(●Open-air)(Lake & river)                                       │
│         └─ No timetables published for open-air pools yet — locations only.            │
```

### Mobile phonebar (variant-E fusion: no sheet, no nav stack)

The drawer already mounts the *same* `#app-toolbar` node, so the control itself is free.
What is **not** free is the closed state: the water choice must be legible without opening
the drawer, so it joins the pinned summary tags right after the lead count.

Collapsed (the 95% state):

```
 ┌───────────────────────────────────────────────┐
 │  Sa    Su    Mo    Tu    We    Th    Fr       │  ← day strip, scrolls away
 │   1     2   [ 3]    4     5     6     7       │
 ├───────────────────────────────────────────────┤
 │ 4 open to you now · Open-air · Adult      ▾   │  ← pinned; tap = drawer
 └───────────────────────────────────────────────┘
   ▓▓▓ Seebad Enge          1.2 km              …
```

Tag order: lead count → **water** → gender → age → lap. Water outranks gender/age because
it changes *which pools exist*, not merely which sessions are yours; a user who forgot they
were filtered to Open-air must see that before they conclude the city has 7 pools.
`water = ""` (All) contributes **no** tag — defaults are never tagged (existing rule).

Drawer open (≤400 px, chips wrap 2×2):

```
 │ 4 open to you now · Open-air · Adult      ▴   │
 ├───────────────────────────────────────────────┤
 │ Water                                         │
 │ ( All        ) ( Indoor              )        │
 │ (●Open-air   ) ( Lake & river        )        │
 │ ⓘ No timetables for open-air pools yet.       │
 │                                               │
 │ Near   [ Where from?              ]           │
 │ Gender ( Any )( ♀ )( ♂ )( ⚧ )                 │
 │ Age    ( Any )( Child )( Teen )( Adult )…     │
 │ [ ] Lap lanes only                            │
 │ ─────────────────────────────────────────     │
 │ 31 school & paddling pools hidden [Show]      │
 └───────────────────────────────────────────────┘
```

The drawer keeps its existing dismiss-on-scroll behaviour; a water tap does **not**
auto-close it (users retry a filter that returned nothing, and a closing drawer would
force a re-open on every attempt).

### The card type badge

Because Axis A collapses 7 kinds into 4 and `All` is the default, the **card must carry the
real kind** — otherwise the collapse loses information. Add a small kind badge to
`plist__meta` (phone) and the board row (desktop), using the raw seven-value vocabulary:
`Hallenbad · Freibad · Flussbad · Seebad · Schulbad · Planschbecken · Wärmebad` (localised).
This is where `river` vs `lake` survives.

---

## 3. Empty / ghost-state behaviour

Three distinct outcomes. They must look different; a blank is never acceptable.

### 3.1 Filter yields pools, but **all** of them are `no_source` (the common case today)

`water=open` → 7 pools, 0 schedules. `water=natural` → 12 pools, 0 schedules.

Today each such pool would render its own `STATE_UNLISTED` ghost card and the screen would
be seven identical apologies. Proposal: a new **hoisted** state,
`STATE_UNLISTED_ALL`, selected when the filtered set is non-empty and *every* member is
unlisted:

```
 ┌ ⓘ ─────────────────────────────────────────────────────┐
 │  We have all 7 open-air pools — but no timetables.      │
 │  Zürich publishes opening hours for indoor pools only;   │
 │  open-air hours are not in any feed we can read yet.     │
 │  Not the same as closed.        [ Show indoor pools ]    │
 └─────────────────────────────────────────────────────────┘

   Freibad Letzigraben        2.1 km   Freibad · seasonal
   Freibad Allenmoos          3.4 km   Freibad · seasonal
   …ranked by DISTANCE, not by time
```

Rules:
- The banner replaces the per-card ghost text; the cards drop to **location mode** — name,
  distance, description, address, website link. That is real information, and it is the
  honest answer to "where can I go swimming outside".
- Ranking switches from `poolrank`'s time tiers to plain distance (the `unknown` tier
  already exists — `mobile.tier.unknown`; here it is the *only* tier, so the tier heading
  is suppressed and the banner carries the message once).
- The banner's action offers the nearest axis value that **does** have data
  (data-driven: whichever group has schedule coverage), never a hardcoded "Indoor".
- Never the word "closed", never a grey/disabled treatment. `stateblock--hours-not-listed`
  tint, not `--closed`.

### 3.2 Filter yields **zero** pools

Only reachable by combining water with place+radius (e.g. Open-air within 2 km of
Oerlikon). The message must **name the filter that emptied it** and offer to clear *only*
that one:

```
 ┌ ────────────────────────────────────────────────────── ┐
 │  No open-air pool within 2 km of Oerlikon.              │
 │  [ Show all water types ]   [ Widen to 5 km ]           │
 │  Nothing matched — this is not the same as closed.      │
 └─────────────────────────────────────────────────────────┘
```

This is a *variant* of `STATE_NONE`, not a new block: same card, parameterised copy
(`state.typeNone.*`) plus two action buttons. The existing `state.none.body` prose stays
for the un-parameterised case.

### 3.3 Filter yields a mix

Unchanged: plannable cards first in their time tiers, unlisted ones in the `unknown` tier
with their existing per-card ghost. No banner (the banner is only for the all-ghost case).

### 3.4 Seasonal honesty

An Open-air filter in January will be technically correct and practically useless. The
banner in 3.1 should carry the season when known (`Freibad · seasonal · May–Sep`). Where
gold has no season field, say nothing rather than guess — but see §7 Q6.

---

## 4. State, URL, API

### 4.1 `FilterState` delta (`filterstate.js` + `.d.ts`)

```ts
export interface FilterState {
  // …existing…
  /** The water axis. '' = all (default). NOT a PoolKind — see WATER_KINDS. */
  water: "" | "indoor" | "open" | "natural";
  /** Include school + paddling pools in the result set. Default false. */
  includeMinor: boolean;
}

export const DEFAULT_FILTER = { /* …, */ water: "", includeMinor: false };
```

**Naming, deliberately.** Not `kind` and not `type`:
- `kind` is the server's `PoolKind` vocabulary, and the mapping is **not** 1:1
  (`indoor` ⊃ `{indoor, thermal}`). Sharing the name invites an implicit-identity bug where
  someone passes `filter.kind` straight to `?kind=`.
- `type` is a noise word in JS.

**One mapping table, in one measured module.** A new `apps/web/static/js/pooltype.ts`:

```ts
export const WATER_KINDS: Record<Exclude<Water, "">, readonly PoolKind[]> = {
  indoor:  ["indoor", "thermal"],
  open:    ["outdoor"],
  natural: ["lake", "river"],
};
export const MINOR_KINDS = ["school", "paddling"] as const;
export function kindsFor(water: Water, includeMinor: boolean): PoolKind[];
```

It must **not** live in `toolbar.ts` (a browser-composition block); it is a rule, and rules
live in a measured module — the same argument `appdata.ts` exists for. Pin it with a test
asserting `WATER_KINDS ∪ MINOR_KINDS === PoolKind` exactly, so adding an eighth `PoolKind`
server-side fails a test instead of silently vanishing from the UI.

### 4.2 URL encoding (`urlstate.ts`)

Params `water` and `all`, inserted into the fixed order after `date` (context params before
person params):

```
view, date, water, all, who, age, lap, elig, pool
/?water=open&who=female&age=adult
```

- `toParams`: `if (state.water) p.set("water", state.water)` — `""` omitted, so the default
  view stays a bare `/`. `if (state.includeMinor) p.set("all", "1")`.
- `fromParams`: tolerant, matching the existing style —
  `if (w === "indoor" || w === "open" || w === "natural") patch.water = w;`
  unknown values are **dropped**, never thrown. `if (params.get("all") === "1")
  patch.includeMinor = true`.
- `UrlFilterState` / `FilterPatch` gain the two optional fields.
- `isStructuralUrlChange` (`appdata.ts`): **water is NOT structural.** It is a filter
  toggle, so it `replaceState`s like gender/age. Making it structural would put four
  history entries between a user and the page they arrived on.

### 4.3 API delta — server-side, in the domain vocabulary

Two changes, both small:

1. **`GET /swim` gains `kind: str | None = None`** — a comma-separated list of raw
   `PoolKind` values, validated against the enum (400 on an unknown member, matching the
   existing `gender` handling). Filtering happens in `build_answer` before eligibility, so
   both `options` and `statuses` are filtered coherently.
2. **`StatusOut` gains `kind: str`** (it already exists on `OptionOut`). Ghost cards need
   the type badge, and without it the client must name-join statuses against `/pools` —
   the join `classifyPools` already does, which is a known smell (facility *names* as keys).

Plus, for consistency: **`GET /pools?kind=` accepts a comma list** (currently single-valued,
`service.list_pools`).

**The layering decision that matters: the server never learns the word "open-air".** The
client expands `water` → `kindsFor()` → `?kind=outdoor`. Grouping is an editorial UI
argument and belongs where the argument lives; the API stays in domain vocabulary, so a
future re-grouping is a one-file client change with no API version bump.

**Why server-side rather than client-side (`applyLap` precedent).** `applyLap` filters
*sessions within a payload we already fetched*. A type filter removes *whole pools*, and
Pool mode fires **seven** `/swim` calls — client-side filtering would download 57 pools ×
7 days to display 7 of them. Do it once, at the source.

### 4.4 One interaction rule the wiring must respect

In **Pool mode** the water filter applies to the pool **picker**, not to the board. If the
user has Hallenbad Oerlikon selected and then picks Open-air, the board must keep rendering
Oerlikon (with its type badge) rather than going blank — the selected pool is an explicit
choice and outranks a category filter. The picker below it re-lists to Open-air only.
See §7 Q4.

---

## 5. i18n message keys

New keys for `locales/{en,de,fr,it,pl}.ts` (en is the source shape; every other locale must
supply all of them or `tsc` fails).

```ts
// --- Water axis -------------------------------------------------------------
"toolbar.water":            "Water",
"toolbar.water.any":        "All",
"toolbar.water.indoor":     "Indoor",
"toolbar.water.open":       "Open-air",
"toolbar.water.natural":    "Lake & river",

// --- The hidden minor set ---------------------------------------------------
"toolbar.includeMinor": {                     // plural: count = hidden pools
  one:   "{count} school & paddling pool hidden",
  other: "{count} school & paddling pools hidden",
},
"toolbar.includeMinor.show": "Show them",
"toolbar.includeMinor.hide": "Hide them again",

// --- Axis B placeholder (disabled toggle, Busyness pattern) -----------------
"toolbar.extras":           "Sauna & extras",
"toolbar.extrasReason":     "Sauna and amenity data has no source yet — not available.",

// --- Ghost states -----------------------------------------------------------
"state.typeUnlisted.title": {                 // param: count, water (localised label)
  one:   "We have the 1 {water} pool — but no timetable",
  other: "We have all {count} {water} pools — but no timetables",
},
"state.typeUnlisted.body":
  "Zürich publishes opening hours for indoor pools only; we can't read {water} hours from any feed yet. Not the same as closed.",
"state.typeUnlisted.action": "Show {water} pools",   // reuses a water label as the param

// --- Zero after a type filter ----------------------------------------------
"state.typeNone.title":     "No {water} pool within {km}",
"state.typeNone.clearType": "Show all water types",
"state.typeNone.widen":     "Widen to {km}",

// --- Card kind badge (the RAW 7-value vocabulary survives here) -------------
"pools.kind.indoor":   "Indoor pool",
"pools.kind.outdoor":  "Open-air pool",
"pools.kind.river":    "River bath",
"pools.kind.lake":     "Lake bath",
"pools.kind.school":   "School pool",
"pools.kind.paddling": "Paddling pool",
"pools.kind.thermal":  "Thermal bath",
"pools.kind.seasonal": "seasonal",
```

Notes for the translators:
- The phonebar summary tag **reuses `toolbar.water.*` verbatim** — no `mobile.tag.water`
  key. (Same trick `app.ts` already uses for the gender/age tags.)
- `de` must say **Hallenbad / Freibad / See & Fluss** and **Schwimmbad-typ** — the German
  nouns *are* the taxonomy, which is a strong signal the grouping is natural in the
  local mental model. Watch that the catalog is `de` while the *formatting* locale is
  `de-CH`; "Badi" is the Zürich colloquialism but the city's own signage says "Freibad", so
  use "Freibad".
- `pl` needs all four CLDR categories on the two plural entries (`toolbar.includeMinor`,
  `state.typeUnlisted.title`) or `plurals.ts` fails the build — this is exactly the case
  `Plural<L>` exists for.
- `state.typeUnlisted.body` interpolates a **localised noun into a sentence**; in `pl` this
  needs the locative/genitive, so translators must be free to restructure the sentence
  rather than receive a nominative label mid-clause. If that proves ugly, split into four
  per-water sentences (`state.typeUnlisted.body.open` &c.) — a 4× key cost for grammatical
  correctness, which this project has already paid elsewhere (the genitive-month rule in
  `datefmt.ts`).

---

## 6. Interaction, keyboard, a11y

- **Single-select.** Re-clicking the pressed chip is a **no-op**, not a toggle-off —
  `_selectgroup.js`'s `aria-pressed` model already behaves this way, and "All" *is* the
  clear affordance. No ✕ on the group.
- **Clear-all.** Not in the control. It lives in the empty state (§3.2), where it is
  needed and where it can name what it clears.
- **No count badges on the chips.** Two reasons. (a) A truthful "open now" count requires
  resolving the day for all 57 pools before the user has chosen — a fetch to render a
  filter. (b) With today's data three of four chips would read **0**, which looks like a
  broken app rather than a data gap. If counts are wanted later they must be *roster*
  counts ("7 pools"), which are always truthful, never *open* counts.
- **Keyboard.** Inherited free from `_selectgroup.js` + `keynav.js`: the group is one tab
  stop, ←/→ move between chips, Home/End jump, Space/Enter select. `role="group"` +
  `aria-label` from `toolbar.water`.
- **Live region.** The result count already announces via the phonebar lead tag
  (`aria-live` is on `.ui-datestepper__label` today, not the tag host) — the summary tag
  host should get `aria-live="polite"` so a water change is announced, not silently applied.
- **The honesty note is programmatic.** When a water group has zero scheduled pools, its
  chip gets `aria-describedby` → a visually-hidden "no timetables published yet" note. It
  is computed from the fetched data, **not** hardcoded, so it disappears by itself the day
  the outdoor scraper lands. A hardcoded note would become a lie on a green build.
- **`includeMinor` is a real `<button>`**, in the tab order after the chip group, with
  `aria-pressed` reflecting state so it reads as a toggle rather than navigation.
- **Focus survival.** Water changes re-render the list; focus must stay on the chip (the
  toolbar is rebuilt wholesale in `rebuildToolbar` today — a water change must *not* go
  through that path, or focus lands on `<body>` after every tap).

---

## 7. Open questions & risks

**Q1 (the big one). Is hiding 31 school + paddling pools by default owner-approved?**
It changes the current answer set for *every* query, not just filtered ones. This design
argues yes-with-disclosure: they carry no public schedule, no lanes, and no
adult-swimmable water, and the "31 hidden · Show them" line keeps it honest rather than
silent. But it is an editorial judgement about the product, not a UI detail, and it should
be decided explicitly. Fallback if rejected: keep them in `All`, add a fifth
`Other` chip, and accept the noisier default.

**Q2. `thermal` folded into Indoor.** Correct for Käferberg (already a display override on
a roofed pool). Breaks the day the city classifies an *outdoor* thermal bath. Mitigated by
the single mapping table + the exhaustiveness test, which turns that into a failing test
rather than a silently mis-grouped pool.

**Q3. Season-aware default?** Should `water` default to `indoor` in January and `open` in
July? **No.** A default that silently answers a question the user did not ask is the same
class of dishonesty as rendering `no_source` as closed. The *empty state* may mention the
season (§3.4); the default may not encode it.

**Q4. Pool mode + water filter.** §4.4 proposes the selected pool wins and the filter
applies only to the picker. The alternative — clearing the selection when it falls outside
the filter — is more "consistent" and much more annoying. Needs a decision; it is the only
place the two axes genuinely conflict.

**Q5. Is `no_source` for outdoor pools *permanent*?** If Zürich never publishes machine-
readable Freibad hours (they are seasonal prose on the page today), then §3.1's banner is
not a temporary apology but the permanent product for 25 of 57 pools. In that world the
right design is different: outdoor cards should stop pretending they are waiting for a
schedule and instead lead with season + water temperature (Baditicker **is** live for these
pools) + a link. Worth answering before building, because it changes what an outdoor card
*is*. This is arguably the highest-leverage finding in this document.

**Q6. Water temperature as the natural-water axis.** For `lake`/`river`, "is it warm
enough?" beats "is it open?" — and Baditicker already gives us that number. A future
refinement of the `natural` group might be a temperature threshold rather than any type
chip at all. Out of scope here, flagged so the four-value axis is not treated as final.

**Q7. Payload/perf.** Adding `kind` to `StatusOut` is trivial. Server-side `?kind=`
filtering *reduces* Pool-mode payload by up to 7×. No regression expected; the CRAP gate
sees one new branch in `build_answer` and one in `list_pools`.

**Q8. Test surface.** New/changed suites: `urlstate.test.ts` (two params, order,
tolerance), a new `pooltype.test.ts` (exhaustiveness + `kindsFor`), `toolbar.test.ts`
(chip group mounts, emits, default `""`), `stateblocks.test.ts` (the two new states),
`locales/parity.test.ts` (all five locales), plus Python tests for `?kind=` validation and
`StatusOut.kind`. Roughly 6 suites touched — sizeable but no architectural churn.
