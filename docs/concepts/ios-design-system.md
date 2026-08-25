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
