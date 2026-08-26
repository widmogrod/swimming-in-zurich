---
type: concept
created: 2026-08-24
links: ["[[day-tail-time-axis]]", "[[ios-resolved-export]]", "[[card-button-content-model]]"]
---

# The iOS design system — one decision, one place, and a lint per decision

A HIG review of the app target (2026-08-24) found no crash, no wrong answer and no failing gate.
What it found was the app saying one thing several ways, and two controls a reader with VoiceOver
or an ordinary thumb could not use. Both classes have the same shape: a decision taken at the call
site, repeatedly, by whoever was editing that file. So each decision now has one home in
`App/SwimZH/Theme.swift`, and `UILintTests` bans the raw form everywhere else.

## What moved into `Theme.swift`

It was the colour file. Colours were centralised because a `Color(red:)` cannot carry a dark
appearance — but that was never the real reason: a colour is a mapping from a STATE to a value,
and so are the other four.

| Token | Was | Why it is one place |
| --- | --- | --- |
| `Design.Space` | `2, 4, 6, 8, 10, 16` inline | Five files, no rule between them |
| `Design.Radius` | `12`, `3`, `2`, `half` | Three sizes of thing, three numbers, no correspondence |
| `Design.hitTarget` | nothing | The HIG's 44 pt, stated once and asserted by a lint |
| `Font.<role>` | `.caption` / `.caption2` / `.footnote` | A price and a distance are one RANK and shipped as two sizes |
| `Icon.<name>` | SF Symbol literals | `questionmark.circle` stood for three unrelated ideas |
| `ChipColor` | `TierPast` at 12% | A day chip was painted in the word that means "already finished" |

The type ramp is by ROLE, never by size: `rowTitle`, `rowVerdict`, `rowFact`, `rowNote`,
`noticeTitle`, `noticeBody`, `panelTitle`, `screenHeadline`, and the three the day strip uses. A
view asks for the rank of the thing it is showing; the ramp answers which system font that is.

## The two accessibility defects, and why they were invisible

**The pool row was one accessibility element.** `.accessibilityElement(children: .combine)` merged
the row's whole subtree into a single label — swallowing the navigation link, the favourite, the
lane disclosure, and every one of the ribbon's hand-built `a11yBlocks`. The app pays for canvas
accessibility explicitly (a `Canvas` offers none, and a lint has demanded `accessibilityChildren`
since S3b) and then hid all of it behind one sentence. It is `.contain` now; the summary sentence
moved onto the link, so one swipe still reads name, verdict and mark.

**Two controls were too small to hit.** The lane disclosure was a `.caption` chevron — about 11
points. It is a labelled row now, using the two catalog sentences that already existed for it.

Neither is visible to any runtime test, and both were shipped by careful people: `.combine` is the
right modifier for a row that is only text, and a chevron is the right glyph. The lints therefore
police the COMBINATION (a view that combines its children may not also build a `NavigationLink` or
an `accessibilityChildren`) rather than either half.

## One screen, one idiom

The find screen and the all-pools browser are two lists of pools that push the same destination.
They were doing four things differently — search placement (one pinned its field with
`displayMode: .always`, the form a lint already banned on the other screen), title display mode,
the filter control (a top-bar menu against a bottom-bar button and a sheet, wearing the same
glyph), and the push itself (a destination VIEW against a VALUE with a zoom transition). They now
share all four, and `theTwoListsShareOneIdiom` says so in the suite.

## The dead gesture

`RibbonCanvas`'s spatial tap resolved a block through `TimeAxis` and stored its ID in a `@State`
nothing rendered. The binding carries the whole `A11yBlock` now and the row shows the block's own
`Message` — the same sentence VoiceOver reads for it, so the tap and the screen reader cannot give
two answers.

## Source lints cannot see behaviour — `SwimZHUITests` exists because of that

Every guard listed above reads the SOURCE, and a screenshot only proves what one idle frame looks
like. Neither can answer "what happens when you press it", and that gap shipped a defect the very
first reader found: `.searchToolbarBehavior(.minimize)` was present, asserted by a lint, and
commented in two files as putting the search field in the bottom bar — while the field actually
collapsed into the NAVIGATION bar, so opening search took that bar over and the browse menu with
it. Every gate was green.

`App/SwimZHUITests/BehaviourTests.swift` drives the app instead. It runs in the same
`xcodebuild … test` the QA chain already ends with, and it queries by accessibility IDENTIFIER,
never by label — a test looking for "Browse" would pass in one of five languages and fail in four.

It found two real defects on its first run, and neither was visible in source:

1. **Tapping a pool in the all-pools browser landed you back on the browser.** The rows pushed a
   `String` into the stack's `navigationDestination` while the browse menu pushed destination
   VIEWS; mixing the two forms in one stack re-activated the menu's link on top of the sheet you
   had just opened. The fix is the `Route` enum — every push in this stack is now a value of one
   type. (The browser's rows also claimed `matchedTransitionSource` ids the find screen's rows
   already held; both lists are in the stack at once, so the same id was claimed twice.)
2. **Search looked like a one-way door.** iOS hides BOTH bars for the duration of a search, and
   four gestures — tapping the day strip, scrolling, clearing the field, scrolling again — all
   left the bar count at zero. The browse menu was nearly moved into the bottom bar to escape
   that, on the false premise that the bottom bar survives. A SCREENSHOT taken while search was
   active is what settled it: the system draws its own `close` button beside the field, and that
   is the way out. The lasting change is only WHERE the field opens — bottom bar, under the
   thumb, via `DefaultToolbarItem(kind: .search, placement: .bottomBar)` — and the test now pins
   both halves: it opens below the midline, and closing it gives the chrome back.

The method is worth keeping: assert the behaviour, and when the assertion fails, get EVIDENCE (a
hierarchy dump, a screenshot) before changing the code. Two of the three fixes attempted here
were guesses, and the tests rejected both.

## The day is said once, and the strip yields

The navigation bar spelled the date out while the strip underneath drew the same fact — one thing
said twice, costing a row of a phone screen for the copy you cannot tap. The title is gone; the
strip stays, because it is the one you can act on. `chromeYieldsToContent` now asserts the find
screen carries no `navigationTitle` at all, and `testTheDayIsSaidOnceOnly` checks the bar holds no
text.

The strip also yields to the list: read down and it gives the rows its height, come back up and it
returns. Whether it shows is `SwimZHKit.stripShouldShow`, and its shape is the interesting part.

**The first version was a DIRECTION rule** — hide going down, show going up — and it was wrong in a
way no reading of the code would show. Hiding the strip shrinks the scroll view's top inset by the
strip's own height, which moves the scroll position by that much; the rule then read that jump as
a scroll and undid itself, forever. From outside it looked like swipes that took eighty seconds
and an app that never reported itself idle, which is how `BehaviourTests` found it.

The rule is now **two thresholds with a gap wider than the strip is tall** — show within 40 points
of the top, hide beyond `40 + stripHeight + 60` — so the jump hiding it causes can never cross
back. `theBandClearsTheInset` runs that over all twelve text sizes, and it rejected the first fix
too: a FIXED band cleared the strip at the default size and not at an accessibility size, where
the strip is three times as tall. Two further rules fell out of the same episode: the offset is
measured from the top of the CONTENT (`contentOffset.y + contentInsets.top`, the one number an
inset change does not move), and the animation is declared on the bar rather than started inside
the scroll callback, which runs on every frame of a drag.

## Chrome that earned nothing

Removing the title left a full navigation bar holding one overflow button — which is worse than
the title was: it costs the same ~50 points and says nothing at all. Both are gone now.

- The overflow menu held two items, and neither was a rarely-wanted variant of anything, which
  is the only thing an overflow menu is for. **All pools** is a one-tap control in the bottom
  bar; the **colour legend** is a labelled row at the end of the list, where a reader looking at
  the colours already is. Nothing on this screen is behind an ellipsis.
- With nothing left in it, the navigation bar is hidden (`.toolbarVisibility(.hidden, for:
  .navigationBar)`). The day strip now starts at the top of the screen.
- `.listSectionSpacing(.compact)`: inset-grouped sections default to about forty points of air
  between them, and this screen has six tiers. That was a row of pools spent on gaps.

`testTheFindScreenSpendsNoRowOnChrome` pins all of it — no navigation bar, the all-pools control
present, the strip present — and a lint bans `Icon.browse` from coming back.

**A build-hygiene note that cost an hour.** The first attempt at this looked like it changed
nothing: the screenshot was identical, twice, after a rebuild and a reinstall. The code was
right; the incremental build had not picked it up. `strings SwimZH.app/SwimZH.debug.dylib | grep
<an accessibility identifier>` is the two-second check for "is what I am looking at what I
wrote", and `xcodebuild clean build` is the fix. The app's own code is in the **debug dylib**,
not in the 40 KB stub executable beside it.

## What was deliberately NOT done

A "reset filters" control. It is the obvious next thing and it needs a new catalog key, which
means five web locale files, `make ios-locales`, and the plural gate — a translation change, not a
consistency fix. It belongs in its own slice with the wording decided rather than invented.

## The pool screen stopped being a table

> "When I click on a pool I'm shown a table."

Literally true. The screen opened on a `List` of label/value pairs whose first row was the
address. Nothing on it connected to the row that had just been tapped, nothing on it could be
acted on, and the pool's own answer — the sentence the list had spent a row saying — was not on
it at all. The zoom transition was animating towards a spreadsheet.

`PoolHeader.swift` is what it opens on now, in the order a swimmer wants:

1. **Where it is, as a picture.** A small `Map`, non-interactive, at `poolMapSpanMetres`. The
   address is still a string in the facts below, where a string belongs.
2. **What it is called**, at the size a screen about one thing can afford, with the SAME
   `Verdict` the list row drew underneath. That is the continuity the push never had.
3. **When**, as the SAME `dayRibbon` the row drew — the one part of the answer a table cannot
   say.
4. **What to do about it.** Directions (`maps.apple.com/?daddr=`), Call (`tel:`), Website. Round,
   labelled, `Design.hitTarget` on both axes, and each one present only when the pool published
   the thing it acts on — a greyed-out "Call" for a pool with no number is a promise the data
   cannot keep.

Nothing below was removed to make room: every `detailSections` row survives, `FieldCoverageTests`
is untouched, and the header deliberately repeats none of them — which is why the address is a
map here and a string there.

The header takes the row and the point from `TodayModel` (`row(_:)` → `SwimZHKit.findRow`,
`geoByPool`). Both are **optional**, because the all-pools browser pushes the same screen from
the roster, where no answer and therefore no verdict exists. The verdict and the ribbon are then
omitted rather than invented.

## List and map are one answer, drawn twice

> "I can't switch views nicely ie app list, map (apple map)."

The word that mattered was *same*. `PoolMapView` is handed the very `[ListSection]` the list is
drawing, through `SwimZHKit.poolPins`, so the day, the radius, the kind filter and the search
that shaped the list have already shaped the map. Switching is a **mode**, not a destination: no
push, no reset, and the day strip stays up because the day is still the question.

Coordinates come from the ROSTER (`PoolRecord.geo`) — the answer carries no geometry — and a pool
the roster cannot place is dropped **and counted** (`PinSet.missing`), never dropped silently.

**Why MapKit is acceptable in an offline app.** The promise is that the app *answers* with no
network, and that is untouched: the map reads no store and the pins are already in memory. Tiles
are a picture of the city, not an answer about it; with no network MapKit draws its placeholder
grid and every pin stays where it is, still tappable, still labelled. Degraded, never wrong —
which is also why the map is a mode rather than the default.

**Three things this cost, all found by driving the app:**

* **A `Map` swallows its siblings' accessibility.** The card above the map was *drawn* — a
  host-side screenshot showed it — and absent from the accessibility tree entirely, so VoiceOver
  could not reach it and `BehaviourTests` reported it missing on a screen that was plainly
  showing it. Four framings were tried (`safeAreaInset`, `overlay` on the map, `overlay` on the
  stack, a plain `Text` probe) and all four were invisible. `.accessibilityElement(children:
  .contain)` on the `ZStack` is the fix, and it is load-bearing rather than tidy.
* **A pin does not push, it raises a card.** An annotation that navigated would make the map a
  menu: you would leave it to learn anything about one pool and come back for the next. The card
  carries the pin's own `Verdict`, in the same words the row uses, and the whole card is the link.
* **The frame needs two spans, not one.** `MapFrame` carries `tallMetres` and `wideMetres`
  separately. A single span is square, a phone is not, and MapKit fits the square into the taller
  axis: the first build opened on Bülach, the airport and Thalwil. Padding is `1.18` with a
  `1_500 m` floor so three pools on one corner still frame a neighbourhood rather than a car park.

The bottom bar is now three verbs — **find** (search), **see** (list/map), **narrow** (filter).
"All pools" moved out of it into the end of the list beside the colour legend: this screen
answers "where can I swim on this day", the map answers it spatially, and the roster is the
reference behind both — the same kind of thing the legend is. That also cost `BehaviourTests` its
landmark for a third time, because a lazy `List` does not build an off-screen row: the mode picker
is the landmark now, and it lives in the toolbar, which is always resident.

## A session line is two ranks, not five things

The widest row on a real iPhone read:

```
06:00–  Schwimmer…  5 of 6 lanes…  Erwachsene (ab
22:00                              20 J.) Fr. 8.00
```

A time broken across two lines, a basin truncated, a lane summary truncated and a price wrapped
mid-parenthesis — four facts the row spent space on and then did not say. The answer was not
smaller type (the ramp was already at its smallest) and not `minimumScaleFactor` (which makes a
row of five sizes). It was to stop asking one line to hold two ranks: **when and where** on the
first, **what it costs and what is left** on the second, and no second line at all when the
source published none of it.

## The headline never leads with a zero

The largest sentence on the screen read **"0 open to you now"** — true, grammatically headless,
and the least useful true thing it could have said, printed above a list whose very first row
read "Opens 06:00".

Two defects, one line:

* **No noun.** All five catalogs said `{count} open to you now`. Open *what*? Fixed with the
  plural entries the runtime already supports (`1 pool` / `2 pools`, `1 Bad` / `2 Bäder`, and
  Polish's four forms), which is what `plurals.ts` exists for.
* **The zero.** A count of none is not a quantity worth stating. `ListModel.headline` now
  branches: a count when there is one, **"Nothing open to you now — next at 06:00"** when there
  is not, and **"Nothing more open to you today"** when the day is done.

`nextOpenToYou` is carried on the **row**, not derived once for the screen, and that is not
tidiness: the favourites-only filter narrows the rows after the clock has been put away, and a
headline pointing at a pool the reader has just asked not to see would be worse than the zero it
replaced. It is also `mark == .attend`, not merely "the next session" — the sentence says *to
you*, so the eligibility has to agree with the words. Nil off today, like every other
present-tense claim in the model (E1).

## The lane stack was an unreadable brick

Six lanes across a 46-point band is six 6.1-point rows. The first version drew each as a
square-cornered rectangle one point shorter than its slot, and painted reserved at 0.75 against
public at 0.9. On a real iPhone that composited into a solid teal block: the gaps were a
hairline, the corners were square so nothing separated one bar from the next, and the two states
were a few per cent of opacity apart. The busiest pool in the city — the one row most worth
glancing at — was the one row that said nothing.

The web's `drawDayTail` has the same encoding, so this is a rendering choice rather than a port
bug, and the golden fixture constrains the model and not the paint. Four changes:

* `laneGap` takes a **third** of each slot rather than a point, so the stack reads as bars.
* Every bar is **rounded to half its own height**, so it is a capsule at any lane count.
* **Reserved is much fainter** (0.3 against 0.95), because the question the row answers is "can I
  swim" — reserved is the answer's background, not half of a two-tone chart.
* A faint **track** runs the session's whole width under the lanes. Without it, a stack with
  holes in it and a stack that stops early are the same picture.

## Delight, where it is a fact about the act

`.sensoryFeedback` on the four controls that change what you are looking at without going
anywhere: the day chip (since S3b), the favourite heart (`.impact(weight: .light)` — nothing
succeeded, a switch moved), the list/map picker and a map pin (both `.selection`, because they
are the same kind of act). Declarative, no UIKit import, and it obeys the reader's own haptics
setting without any of these files having to ask.

`.contentTransition(.numericText())` on the headline, so the count rolls rather than cuts when
the day changes. It is the only line in the app whose leading token is a digit, and it costs
nothing on the branches that have no number in them.

## Fifty-seven pins were one brown mass

The map's first version drew every answered pool as its own annotation. Framed on Zürich that
put roughly forty of them inside the middle third of the screen, overlapping into something you
could neither read nor reliably tap.

`MKMapView` has `clusteringIdentifier` for exactly this and SwiftUI's `Map` does not expose it —
which turned out better, because grouping is a **rule**: it lives in `SwimZHKit.clusterPins`
where a test drives it, and doing it ourselves is what lets a group be anchored and coloured by
the most interesting pool in it rather than by an arbitrary member.

* **Greedy, not a grid.** A grid snaps each pin to a cell, which is O(n) and has the one bad
  property that matters here: two pools ten metres apart either side of a boundary stay drawn on
  top of each other — the exact case the function exists for. Greedy has no boundary, and at 57
  pools the O(n²) is ~3,000 distance checks run once per gesture.
* **Best pin first, and it leads.** The first pin to claim a patch of screen is the most
  interesting one there, so the badge sits at *its* coordinates and wears *its* tier colour. A
  centroid would have been the obvious anchor and is wrong: expanding then makes every member
  jump somewhere new, where anchoring on the lead means the badge simply becomes the pin that
  was already under it.
* **The camera is an input.** What overlaps depends entirely on zoom, so `onMapCameraChange`
  feeds `metresPerPoint` back in. `.onEnd`, not `.continuous` — one recompute per gesture, and a
  badge whose count flickered mid-pinch would be worse than the wait.
* **Spacing is 44 points, not 34.** A group badge is 34 across, so 34 put two badges exactly rim
  to rim — visible in a screenshot as pairs of touching circles down the west of the city.
* **Tapping a group zooms into it**, via `clusterFrame`, whose floor is a city block rather than
  the whole-answer 1.5 km. Reusing `pinFrame` would have thrown a reader who tapped to get
  closer *out* to a 1.5 km view.

`pinProminence` fades the three tiers you cannot swim in today (`past`, `closed`, `unknown`).
Muting `unknown` beside `closed` is safe because prominence is not the channel that distinction
travels on — the two keep different glyphs, colours and words — and `scheduled` is deliberately
never muted, or every future date would render as a grey map.

## Two tests measured a navigation mistake

"All pools" moved into the end of the list in the map commit, to free bottom-bar room for the
list/map picker. It read as tidy — the roster is reference, like the colour legend beside it —
and it was wrong for a reason no screenshot shows: the list is 57 pools long, so *one tap* had
become *twenty-five swipes and a tap*.

What measured it was `BehaviourTests`. Two tests that merely needed to **reach** the control
spent ~55 s each scrolling, and both became load-dependent — passing alone, failing inside a
full suite run, because a row still decelerating is a row a tap misses. Chasing that with a
settle-and-tap helper fixed one test and moved the flake to the other, which was the signal: a
test working that hard to reach a control is describing the reader's problem.

The bar had room all along — search at the leading edge, picker in the middle — so the button
rejoined the filter in the trailing group. The two tests dropped to ~12 s each and the suite from
288 s to 223 s. The colour legend stayed in the list, because a note about what the colours mean
genuinely belongs where the colours are.

**And it shipped one glyph twice.** Back in the bar, `Icon.allPools` and the picker's
`Icon.list` were both `list.bullet`, four inches apart — the founding defect of the `Icon` list,
recurring in the file built to prevent it. Keeping the names in one place makes a collision
visible to a reader of that file, and it still took a screenshot to notice. `glyphsAreDistinct`
now fails the build on it (verified by reintroducing the collision), allowing only the
state-pair suffixes like `filter`/`filterActive`.

## The name is said once at a time

The pool screen opened with the name in the navigation bar **and** at `heroTitle` six points
under it — the same word twice, which is the plainest kind of careless.

Neither copy could simply be deleted. The hero is what makes the push continuous with the row
you tapped; a bar with no title on a pushed screen leaves a bare chevron with nothing to say
what you are looking at once the hero has scrolled away.

So the bar waits. `SwimZHKit.poolTitleShows` hands the name over the moment the hero's copy
leaves the screen — which is exactly what a `.large` navigation title does for free and what a
hand-built hero has to be told to do.

* **`nameBottom` is measured, not assumed.** It is composed from the map's height, the gap under
  it, a `@ScaledMetric` name line and the section inset, so changing the map cannot silently
  desynchronise the handover — and at an accessibility size, where the name is more than twice
  as tall, a fixed threshold would put it in the bar while it was still plainly on screen.
* **The band is 24 points, much narrower than the day strip's.** Worth writing down because the
  reason is structural: the strip's band must exceed the strip's own height, since hiding it
  shrinks the scroll inset and moves the offset in the direction that would re-show it — a
  feedback loop. Revealing a title changes no layout, so this band only has to survive a finger
  resting on the boundary.

`UILintTests.detailSheetRendersTheName` used to pin an unconditional
`.navigationTitle(Text(verbatim: detail.name))` — which would now be demanding the duplication
back. It checks both halves instead: the hero renders the name, and the bar's copy is
conditional. Either alone leaves a screen that can be looking at a pool without ever naming it.
`BehaviourTests.testThePoolScreenSaysItsNameOnceAtATime` proves it by driving the app, and was
verified to fail when the unconditional title is restored.

## The phone knows where it is, and now the app asks

> "it does not use gps from the phone on map or as a way to sort closest"

Every distance was measured from **Zürich Hauptbahnhof**, because `Places.default` is the station
and there was no other origin. "Nearest first" meant nearest to the station, on a device that
knows exactly where it is. `Filters.swift` carried the reason:

> Core Location would be the slice's only new framework dependency and the plan rules out MapKit
> precisely to keep the offline property.

**That premise is gone.** The map mode links MapKit, so Core Location is no longer the only new
framework — and the offline property was never actually at stake: GNSS is a *receiver*, and a fix
needs no network at all. What remained was a stale comment and a phone app measuring from a
railway station.

### The invariant, which is the app's oldest one in new clothes

A pool whose schedule we do not have must never render as "closed". A **position** we do not have
must never render as a **distance**. Quietly measuring from the station while the reader believes
they are being measured from their phone is the same class of lie — an unknown presented as a
fact — and the more dangerous one, because a wrong distance still looks like a distance.

So `SwimZHKit.devicePlace` returns nil for **every** state but `.fixed`. `.locating` is the
tempting exception (the reader has just asked, and a spinner wants somewhere to live) and is
exactly the one that would install a position the app has not got. Leaving the previous place is
not a compromise: it is still correctly *labelled*, so nothing on screen is false while the fix
is on its way.

### Ported from the web, with one deliberate divergence

`components/placetypeahead.ts` solved this first, emitting `source: 'geolocation' | 'preset' |
'fallback'` with a `reason`, commented "so the UI never implies a precision it does not have".
`PlaceSource` is that shape. The divergence: the web responds to a refusal by moving the reader
to a preset; this does not. On the web there may be no place selected at all, so a fallback is
the difference between an answer and a dead end — this app always has one, so silently swapping
the reader's chosen place would be a surprise where "that did not work, and here is why" is an
explanation.

`LocationRefusal` has **three** cases because the remedy differs and a reader told the wrong one
is sent somewhere that cannot help: `denied` is fixed in Settings by this reader, `restricted`
cannot be fixed by them at all, and `unavailable` is not about permission — this app's Settings
page would show nothing wrong. Only `denied` gets an "Open Settings" button.

### What is persisted, and what is never

The **preference** (one Bool) is persisted, because a choice remade on every launch is a choice
most people make once and stop using. The **position** is never written anywhere — not to the
store, not to defaults, not to a log. `shouldLocateOnLaunch` requires both `preferred` *and*
already-authorised, so a launch can restore the choice and can never raise a permission dialog
in front of someone who has not asked for one.

### Five languages, including the system's own dialog

iOS renders a purpose string in the **system's** language, so `INFOPLIST_KEY_NSLocation…` alone
would ask a German reader in English. `locales_to_xcstrings.mjs` now emits a third output —
`App/SwimZH/InfoPlist.xcstrings` — from the same web catalogs as every other sentence. Both
halves are needed and they are written in different places: the xcstrings **overrides** a value
per language, it does not **declare** one, so without the build setting iOS treats the permission
as undeclared and the prompt never appears. `test_the_base_infoplist_key_matches_the_english_
catalog` is what stops the two drifting.

### Three things the driven app taught

* **`LabeledContent` inside a `Button` label eats the identifier.** `BehaviourTests` could not
  find the "Use my location" row while a `strings` check proved the identifier was in the shipped
  binary. A plain `HStack` fixed it. Every other row here keeps `LabeledContent` — they are Form
  rows, which is what it is for.
* **A persisted preference leaks between tests.** Once the location test had opted in, every
  later launch located itself and re-sorted the list — which broke the lane-plan test (a
  different pool sorted first, and it publishes no lane plan) and then the location test itself,
  whose "before" was already measured from the phone. Fixed with `UserDefaults`' argument domain,
  which wins on read and is not written back: a clean start with no test hook in production code.
* **An XCUITest cannot shell out** (`Process` is macOS-only), and the permission alert belongs to
  SpringBoard. So the world is set from outside by `make ios-sim-world`. The coordinates are
  load-bearing: Wollishofen is ~4 km south of the station, so the two orderings genuinely differ
  and a run that changed nothing would prove nothing. The **refusal** path is not driven — its
  invariant is `devicePlace`, and `LocatedTests` walks every state including all three refusals.
