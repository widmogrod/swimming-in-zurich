---
type: plan
status: draft
created: 2026-09-05
links: ["[[ios-design-system]]", "[[2026-08-23-native-ios-app-plan]]"]
---

# iOS 27 Liquid Glass review of the SwimZH app

A read of every view in `apps/ios/App/SwimZH/` against Apple's Liquid Glass guidance as it
stands after WWDC 2026 (iOS 27). The findings came first; the section "What was built" below
records what was then done about them on the same branch. Each finding says what it is, how
sure we are, and what it would cost.

## What iOS 27 changed (from public reporting; verify in the Xcode 27 SDK)

- **No opt-out.** `UIDesignRequiresCompatibility` is gone in Xcode 27. Recompiling applies glass.
  This app never set it, so nothing changes for us.
- **A user-facing glass slider.** Settings > Appearance > Liquid Glass runs from "clear" to
  "frosted". Glass surfaces follow it. `.regularMaterial` does NOT. The app must look right at
  both ends.
- **Toolbars regroup.** System apps moved back to grouped top/bottom bars instead of scattered
  floating buttons. New toolbar APIs reported: `.toolbarMinimizeBehavior(.onScrollDown, for:
  .navigationBar)`, `ToolbarOverflowMenu`, `.visibilityPriority(.high)`,
  `.topBarPinnedTrailing`.
- **Rendering.** Cheaper glass on low-power devices; nested `GlassEffectContainer` blends
  without seams. No new glass API surface.
- **Elsewhere in SwiftUI:** `.alert(item:)`, `.confirmationDialog(_:item:)`, `.swipeActions`
  outside `List`, `.reorderable()`.

Sources: dev.to WWDC26 SwiftUI breakdown, spaceport.build Liquid Glass guide, TWiT iOS 27
toolbar article, techtimes WWDC 2026 recap. None of these are Apple's own text; treat every
API name above as "check the SDK before writing it".

## What is already right (keep, and keep the lints)

| Area | Evidence | Verdict |
| --- | --- | --- |
| Glass only in system chrome | `UILintTests.nothingPaintsItsOwnGlass` bans `.glassEffect(` app-wide | Matches HIG "navigation layer, not content layer" |
| One grouped bottom bar | `TodayView` toolbar: `DefaultToolbarItem(kind: .search)` + `ToolbarSpacer` + picker + two buttons | Exactly the iOS 27 "grouped bars" direction |
| Hidden nav bar on the find screen | `.toolbarVisibility(.hidden, for: .navigationBar)` | Chrome that earned nothing is gone; correct |
| Scroll edge effect hidden on the day strip | `.scrollEdgeEffectHidden(for: .horizontal)` | Follows "edge effects are not decorative" |
| Bars attach to the scrolling view | lint `filterBarUsesSafeAreaBar` + no `VStack` wrapper | Edge effect and title collapse work |
| Haptics, numeric roll | `.sensoryFeedback`, `.numericText()` | Good iOS 26 delight, all declarative. The zoom push the pool route had was REMOVED on 2026-09-06: a zoom-pushed screen owns a drag-to-dismiss on every downward pan, which hijacked the drawer's drag and hid the bar (see "The pool screen is a map") |
| Deployment target | `IPHONEOS_DEPLOYMENT_TARGET = 27.0`, Swift 6 | iOS 27 only, by decision (2026-09-06): no `#available` and no older-OS branches |

## Findings, ranked by delight per hour

### 1. The app icon is a flat PNG (high impact, low effort)

`Assets.xcassets/AppIcon.appiconset/AppIcon.png` is one bitmap. iOS 26+ wraps a flat icon in a
glass slab with no depth, and the user-selectable Clear / Tinted / Dark icon modes look muddy
on it. Every system app and most updated third-party apps now ship an **Icon Composer
`.icon` file** with 2–4 layers.

- Do: build `SwimZH.icon` in Icon Composer (water layer, swimmer glyph, ring). Add it to the
  target and point `ASSETCATALOG_COMPILER_APPICON_NAME` at it.
- Check: Home Screen in Default, Dark, Clear, Tinted. Also App Store listing.
- Note: `docs/appstore/` screenshots will need a retake.

### 2. The map card should be glass, not material (medium impact, small effort)

`PoolMapView.PinCard` paints `.regularMaterial` and says glass would collide with the bottom
bar. Two facts against that today:

- The card sits inside the safe area, so it never overlaps the bar. The comment's premise is
  not what the layout does. Verify with one screenshot at the largest text size.
- `MapUserLocationButton` on the same screen IS glass. A material card beside a glass button
  is two surfaces that disagree, and on iOS 27 only one of them follows the user's slider.

The HIG lists "floating info card over a map" as the textbook case for glass.

- Do: `.glassEffect(.regular.interactive(), in: .rect(cornerRadius: Design.Radius.control))`
  on the card; drop the `.shadow`.
- Do: relax `nothingPaintsItsOwnGlass` from a flat ban to an allowlist of files. Keep the ban
  everywhere else.
- Check: card over dark water tiles, over the placeholder grid with no network, with Reduce
  Transparency on, and at both ends of the glass slider.

### 3. The day strip is the one piece of chrome without glass (high impact, medium effort)

`DayStrip` lives in a top `safeAreaBar`, so it is navigation-layer chrome: it changes the
question, not the answer. Yet its chips are flat tinted rectangles while the bar under the
thumb is glass. It is the most-touched control in the app and the one that looks a version old.

- Do: wrap the chips in a `GlassEffectContainer(spacing:)`; give each chip
  `.glassEffect(.regular.interactive(), in: .capsule)`; give the SELECTED chip a `.tint` and a
  `glassEffectID` in a `@Namespace`, so selection **morphs** from chip to chip when the day
  changes. That is the single most "iOS 27" moment the app can add.
- Keep: the today marker as a separate channel, the border for `differentiateWithoutColor`,
  the hysteresis hide/show rule (it is layout-correct and tested).
- Risk: glass chips over the scroll edge effect are fine (the effect is not glass). Glass chips
  over the LIST when the strip is showing at the top: the list scrolls under them, which is the
  intended look. Test at an accessibility size where the strip is three chips tall.
- Cost: the `UILintTests` allowlist above, plus `ScreenshotTests` retake.

### 4. Hero map as a background extension (medium impact, medium effort)

On the pool screen the map is a 150 pt rounded card inside the first list row, under an
inline nav bar with an empty title. iOS 26's `.backgroundExtensionEffect()` lets a hero image
run edge to edge and continue under the glass bar, so the back button floats over the water.
That is the look Apple's own detail screens have now, and it makes the zoom push land on a
picture instead of a card.

- Do: move the map out of the `Section` into a `safeAreaInset`/header above the `List`, full
  width, `.backgroundExtensionEffect()`, `.ignoresSafeArea(edges: .top)`.
- Cost: `FacilitySheet.nameBottom` is composed from `heroMapHeight`; the title-handover
  threshold must be re-derived and `poolTitleShows` re-tested. Medium risk, worth a spike.

### 5. Cheap symbol delight (low effort, do alongside anything above)

- Favourite heart: `.contentTransition(.symbolEffect(.replace))` on the row's
  `heart`/`heart.fill` swap, and `.symbolEffect(.bounce, value: isFavourite)`. The haptic
  already fires; the glyph should agree with it.
- Tier glyph in the section header: `.symbolEffect(.drawOn)` when the section first appears
  (SF Symbols 7). Only for `now`; every section animating is noise.
- Filter button: `.symbolEffect(.bounce, value: filters.isNarrowed)`.

### 6. Bottom bar minimize on scroll (low confidence, try in the SDK)

Reporting names `.toolbarMinimizeBehavior(.onScrollDown, for: .navigationBar)` as new in iOS
27. If the SDK also accepts `.bottomBar`, the four-item bar could shrink to the search glyph on
scroll down and give rows the height back, the same way the day strip yields. Check the SDK.
If it is nav-bar only, skip: the find screen has no nav bar.

### 7. Test the glass slider and the accessibility toggles (no code, one afternoon)

Nothing in `ScreenshotTests` or `BehaviourTests` runs under Reduce Transparency, Increase
Contrast, or the slider's two extremes. XCUITest cannot set them, so this is a manual pass on
one device: find screen, map with a card up, pool screen, filter sheet. Record what breaks in
this file before fixing anything.

## New capabilities worth a plan of their own (bigger, separate slices)

The store is pre-resolved for 400 days and needs no network. That makes these unusually cheap
for this app compared with most:

- **Home / Lock Screen widget:** "Open to you now" or "Nothing open, next at 06:00" from
  `ListModel.headline`. iOS 26 widgets render in glass with Clear/Tinted modes; needs
  `widgetAccentable` and a WidgetKit target reading the bundled SQLite.
- **App Shortcuts (App Intents):** "Where can I swim now?" in Siri and Spotlight, answering
  from the kit with no UI.
- **Control Center control:** one button that opens the nearest open pool's Directions.

Each needs a new target, its own localization pass across five languages, and a plan file.
Not part of this review's fixes.

## What was built (same day, this branch)

Every visual change was behind a **Lab switch** so the two looks could be compared on a phone
(`App/SwimZH/Lab.swift` + `App/SwimZH/Settings.bundle`, read through `@AppStorage`, defaulting
to the NEW look; tests passed `-lab.<key> value` launch arguments). **ALL DECIDED 2026-09-06
(evening): `Lab.swift`, the Settings bundle, `LabSwitchTests`, the "previous look" screenshot
set and every losing branch are deleted.** The table records what each switch compared and
which side won.

| Switch | Key | On | Off |
| --- | --- | --- | --- |
| Day strip | DECIDED 2026-09-06: `morph`, chips scale and fade in on scroll | chips in a `GlassEffectContainer`, the selected tint a separate glass view with one `glassEffectID` that morphs chip to chip; a `.scrollTransition` scales and fades each chip up as the scroll brings it in. Chosen over `flat`, `tint` (one interactive glass per chip, tint cross-fade) and `button` (`GlassButtonStyle`) after all four were felt, and — for the arrival — over the glass `.materialize` transition and plain pop-in. A tap no longer centres the tapped chip, and the strip's scroll clip is off so the press lens is not cut | — |
| Bottom bar | DECIDED 2026-09-06: a system tab bar — List, Map, Filters, Search | `TabView` whose selection is the bar's own draggable glass lens, `tabBarMinimizeBehavior(.onScrollDown)`, `Tab(role: .search)` with `tabViewSearchActivation(.searchTabSelection)`. Chosen over the bottom toolbar with a segmented list/map picker (a flat thumb inside the bar's glass, the one control with no lens) and a toolbar with a glyph-swapping toggle. The all-pools browser was REMOVED in the same decision: the list already holds every pool for the day. The search tab searches the PAGE the reader came from (list or map — `searchedContent`), with pool names as `searchSuggestions` through the kit's `browsePools` rule, so a search from the map stays on the map with autocomplete. The filters are a TAB (a page, not a sheet), chosen over a pill above the bar (`tabViewBottomAccessory`) after both were felt. A pushed pool screen hides the bar | — |
| Glass map card | DECIDED: glass (switch deleted) | `.glassEffect(.regular.interactive())`, `.materialize` transition, no shadow | `.regularMaterial` + shadow |
| Symbol motion | DECIDED: on (switch deleted) | heart draws on/off, filter glyph replace + bounce | plain swaps |
| Links open in | DECIDED: `sheet` — the in-app Safari pull-down sheet; `safari`, `web` (and its `WebBrowser`, icons and Done) and `external` deleted | `safari` (default): `SFSafariViewController` full screen, prewarmed; `sheet`: the same as a pull-down page sheet; `web`: SwiftUI `WebView` in the app's own glass bars | `external`: the Safari app |
| Favourite row | DECIDED: `hold` — the row stays put, the order settles at the top; `move`/`never` deleted | `hold` (default): the heart appears in place, nothing moves; the favourites-first order is applied when the reader scrolls back to the top, changes day/filter, or relaunches; `never`: favourites never lead | `move`: the row slides to the front of its tier at once (the old behaviour, now animated instead of cut) |
| Pool map arrives | DECIDED: `afterPush` (switch deleted) | `afterPush` (default): the screen pushes at once over a flat ground, the `Map` is built one beat later and fades in | `withPush`: the `Map` is in the pushed screen's first frame, so the tap waits for it |
| Preload keyboard | DECIDED: on (switch deleted) | a hidden field takes and resigns first responder once after the answer is on screen, so the first tap on search skips UIKit's first-keyboard bring-up | the first search tap pays it |

### The pool screen is a map (decided the same evening; two switches deleted)

The ask: make the pool screen's map "interactive and delightful — maybe pulling down expands
it, clicking makes the detail a panel that changes size". Three shapes were driven on a phone
in one evening, and the owner chose the last:

1. **Picture + list** (the `lab.heroExtends` variant above, then behind a switch): a 150 pt map
   over the facts, full-bleed under the bar.
2. **Picture that opens** (`lab.heroStage`): tap the picture or its glass button and it grew to
   fill the screen, the facts slid into a resizable panel, close brought the picture back.
3. **The map IS the screen** — what shipped. `PoolStage.swift`: a full-screen pannable map
   under the glass back button, the pool's pin, the reader's dot when permitted, transit stops
   and car parks (every other point-of-interest category is hidden as clutter), and one
   recentre button as a `topBarTrailing` toolbar item — the system's own glass, at the back
   button's height and size on the opposite side. It was a `.buttonStyle(.glass)` button
   floated over the map first, and sat visibly lower and larger than the back button beside
   it. `PoolStage.swift` paints no `.glassEffect` and is not in the glass allowlist.
   `PoolPanel.swift` is the facts card over it — a glass card that is PART OF THE VIEW, with
   three rests (`SwimZHKit.PanelDetent`: 0.32 / 0.55 / 0.9 of the screen), dragged between them
   with a soft quarter-rate overdrag at either end and velocity-projected landing
   (`panelVisibleHeight`, `panelDetent(from:)`, tested in `PanelLayoutTests`). It is laid out
   once at its tallest height and SLID by an offset, so a drag is a transform and nothing under
   the finger re-measures; the facts list scrolls only at the tallest rest. It holds
   `PoolHeader` (name, verdict, ribbon, actions) and the same `facts` `ForEach` a
   no-coordinates pool gets as a plain list. `detail` is optional: the map and the panel with
   the pool's name (from the roster) appear the moment the row is tapped, and the facts fill
   in when the store's six reads land — the screen no longer opens on a spinner.
   The bar carries NO title: the panel always shows the name, so `poolTitleShows` and its
   scroll handover are deleted along with both switches, their `Settings.bundle` rows and the
   old-look branches — a decided switch left behind is an unmeasured second code path.

   It was a system `.sheet` with detents first, and the phone said no three times: dismissed
   with the screen, the sheet lingered over the list for the length of its own animation after
   the pop; at `.large` it stopped being glass and went opaque (black, in dark mode); and it
   could not be presented until there was a detail to present. A view in the hierarchy pops
   with its screen, is glass at every height, and can stand on the map with only a name.
   `FacilitySheet.backSwipeEdge` keeps a 22 pt strip of the leading edge free of the map's own
   pan — and, topmost in the stack, of the drawer's — so the system's swipe-back works from
   either (`testSwipingFromTheLeadingEdgeGoesBack`, `…OverTheDrawerGoesBack`).

   **The drawer's gesture (2026-09-06, after a phone session).** The drawer has two slots: the
   header (name, verdict, ribbon, actions) is fixed under the handle and never scrolls; the
   facts list below scrolls only at the tallest rest. So a drag ANYWHERE on the drawer moves it
   at the two smaller rests, and on the header at every rest; at the tallest rest a deliberate
   pull past the list's top (`panelCollapses(listPull:)`, 60 pt) steps it down to half. Pulled
   down FROM its smallest size and let go past `panelDismissBeyond` (120 pt of finger), the
   screen goes back to the list (`panelRelease(from:)` → `.dismiss`); from any higher rest even
   a whole-screen flick only lands on the smallest size — two pulls to leave, never one, so a
   reader closing the facts cannot overshoot out of the screen (a driven test caught exactly
   that overshoot in the first version). The owner's ask:
   "pull drawer to minimal size, then go to main list when user pulls down further". A drag
   that starts sideways is not the drawer's, so the edge swipe keeps it.
   **The zoom push is gone** to make that possible: a zoom-pushed screen owns a drag-to-dismiss
   on every downward pan, and driven, every drag on the drawer's body shrank the whole screen
   toward the list and hid the bar while it did. The pool route is a plain push now; the row's
   `matchedTransitionSource` and the lint that demanded both halves are replaced by a lint
   that bans them. **MapKit is warmed at launch** (`MapWarmup`, one throwaway `MKMapView` 600 ms
   after the answer is on screen): the first pool tapped used to pay MapKit's first-map cost as
   a push that froze for a beat, which is what the owner saw first.

Two things the driven app found that reading the code did not:

- **Pull to open is impossible on this screen.** Version 2 also opened on a pull past the top
  (a stretch, a glass hint, a haptic at a tested threshold, `onScrollPhaseChange`). The test's
  own video attachment showed the whole screen shrinking back into the list row instead: the
  screen arrives by a ZOOM transition, and iOS gives a zoom-pushed screen drag-to-dismiss on
  overscroll, so the system consumed the pull before any scroll callback saw it. Not fought.
- **Never animate a `Map`'s frame.** Version 2's grow animation made MapKit rebuild its Metal
  drawable on every frame of the spring — "Failed to acquire drawable" per frame, a broken
  MapKit layout guide, and under Metal API validation (Xcode's debug default) an assertion in
  `MTLDebugDevice`. Version 3 has nothing to animate: the map is laid out once at the size of
  the screen.

Words: `action.backToPool` in all five catalogs (the open/close words came and went with
version 2). Glyph: `Icon.backToPool`. Driven by `testThePoolScreenOpensOnTheMapWithTheFactsInAPanel`
(map, panel taller than a fifth of the screen, directions reachable, recentre ≥ 44 pt and
harmless), `testThePoolScreenSaysItsNameOnceAtATime` (no bar title, back works with the panel
up) and `testThePanelCannotBeDraggedAway`. `ScreenshotTests`' `04-pool` is the map with the
panel.

Not behind a switch:
- **The app icon** is now `App/SwimZH/AppIcon.icon` (Icon Composer document: gradient fill,
  waves layer, swimmer layer, both front layers glass + specular). actool flattens it into three
  1024 px renders (default, dark, tintable) of about 3.2 MB together, which no build setting
  suppresses, and a device build carries the set twice (phone and pad idioms, even for an
  iPhone-only target: 9.3 MB measured) — so the `app_minus_sqlite` size ratchet moved from 4 MB
  to 12 MB, with the owner's say-so, in
  `apps/ios/budgets.json` and `tests/scripts/test_ios_budget.py`, with the reason recorded there.
  The old PNG set stays as the fallback.
- **The day strip opens on the selected day.** It began at the store's first day and only
  scrolled on a change of selection, so on a store more than a screen of days old the selected
  chip was off-screen. Found by the first glass screenshot; fixed in `DayStrip.init`.
- **`UILintTests.nothingPaintsItsOwnGlass`** is an allowlist of two files (`DayStrip.swift`,
  `PoolMapView.swift`) instead of a flat ban, and it fails if an allowlisted file stops
  painting glass.
- `ScreenshotTests` gained a `06-map-card` capture and a second test method,
  `testCaptureThePreviousLookSet`, which launches with every switch off and writes the same
  walk as `old-*.png`. A launch argument, deliberately: two attempts to pass the switch as an
  environment variable (`TEST_RUNNER_*`, then a scheme variable) produced "old look" sets
  that were pixel for pixel the new one, and a marker attachment proved the variable never
  reached the runner.

Both sets, plus the Home Screen icon in light and dark, are in
`docs/appstore/lab-2026-09-05/` (`01-…06` new look, `old-01-…old-06` previous look).

Two things the screenshots caught that reading the code did not:
- `.backgroundExtensionEffect()` inside a `List` row extended nothing; the hero reaches under
  the bar only when the list itself ignores the top safe area, and the map is then made taller
  by the measured bar height so its full 150 points stay visible.
- A glass surface composites over overlays applied AFTER it: the selected chip lost its border
  and the today chip its rule. Both are applied before the surface now, as content.

**Verification run on this branch:** `swift format lint --strict`, the 39 source lints, the
379-test package suite, the Swift CRAP gate, `tests/scripts` (pytest), the app-hosted suites,
and all 19 behaviour tests (after `make ios-sim-world`'s location grant), on Xcode 27.0 beta
with the iOS 27.0 simulator. The "iPhone 17 Pro" iOS 27 simulator crashed twice under load;
"iPhone 17" was stable.

Dropped from the list above: the bottom-bar minimize (finding 6). The reported
`toolbarMinimizeBehavior` API is not in the iOS 27.0 SDK; only `tabBarMinimizeBehavior`
exists, and this app has no tab bar.

### Links open inside the app (2026-09-06; a fourth picker)

The ask: "opening links in the app should happen by a built-in browser", with Apple's
practices and the iOS 27 look. Before: the website action and the facts' `Link` both went
through the environment's `openURL`, which handed the address to Safari and put the app in
the background. Coming back was the app switcher.

What was built, `App/SwimZH/LinkOpener.swift`:

- **One seam.** `linkOpening()` at the app root replaces `openURL` with an `OpenURLAction`
  that takes `http(s)` and returns `.systemAction` for everything else, so `tel:`, the Maps
  URL and `app-settings:` still leave the app. No call site changed; `Link` and `openURL(...)`
  both land here.
- **`lab.linkOpener`**, a picker in Settings > SwimZH with four values — DECIDED 2026-09-06:
  `sheet`; the other three are deleted:
  - `safari` (default) — `SFSafariViewController` in a full-screen cover. Safari's engine and
    the reader's own cookies, passwords, Reader and content blockers; on iOS 26+ its bars are
    the system's Liquid Glass. `entersReaderIfAvailable` off (Reader strips the timetable
    table), `barCollapsingEnabled` on, `preferredControlTintColor` the app accent, delegate
    finish clears the presentation state so the same link opens twice.
  - `sheet` — the same controller as a page sheet: the pool screen stays visible behind it and
    a pull down closes it. Lighter to glance at; the page is shorter.
  - `web` — SwiftUI's `WebView` (`WebPage`, iOS 26) in the app's own `NavigationStack`: Done
    and Share in the top bar, the page title inline, a bottom bar of back / forward / reload /
    open-in-Safari in the system's glass with `ToolbarSpacer`s, a linear progress line while
    loading, edge-swipe back and link previews on. Costs: no shared Safari state, no Reader,
    and every control is ours to keep right.
  - `external` — the Safari app, for comparison.
- **Prewarmed.** `prewarmingLink(url)` on the actions row calls
  `SFSafariViewController.prewarmConnections(to:)` while the panel is on screen and
  invalidates the token when it leaves, so the tap opens on a page rather than a spinner.
  Only for the two openers that use Safari's controller.
- **Driven.** `BehaviourTests.testTheWebsiteOpensInsideTheApp` relaunches with each in-app
  opener, taps the website action, and asserts a web view is on screen with the app still in
  the foreground; for `web` it presses the app's own Done and asserts the pool is back.
- Four catalog keys in five languages (`action.back`, `action.forward`, `action.reload`,
  `action.openInSafari`); four `Icon` entries (Safari's glyphs; open-in-Safari is the
  `arrow.up.right.square` leave-the-app arrow, not a second compass).

Recommendation: keep `safari`. It is the HIG's answer for a page that is a detour, it is the
least code, and it follows the reader's Safari settings and the iOS 27 glass slider for free.
`sheet` is worth a second look on a phone if the map behind it turns out to matter more than
the page height. `web` earns its keep only if the app ever needs to act on the page (inject a
timetable parser, keep the bar's own controls) — not today.

### Performance review (2026-09-06; three more switches)

The complaint, in the owner's words: a spinner and a search box at launch "when it loads
data"; tapping the search box "takes few seconds, it lags"; opening a pool's details lags
more; is there I/O blocking, or no lazy loading? And a favourite swiped mid-list is "pushed on
top of list and disappears from current view".

**What was measured, and how.**

1. *The rule layer, on the host* (a throwaway `swift test` probe against the bundled store,
   since deleted): open the store 2 ms; `metadata` + `pools` < 1 ms; one full day's `answer`
   2.6 ms cold, 1.0 ms warm; `listModel` 0.5 ms; `dayRibbon` for all 57 rows 0.5 ms;
   `a11yBlocks` for all rows 2 ms; the 400 day chips 3 ms; one pool's `facility` (six reads)
   0.2–0.5 ms and its `detailSections` under 0.15 ms; a thousand catalog renders 1–7 ms; a
   thousand formatted distances 1.7 ms. **There is no I/O on the scrolling path and nothing to
   lazy-load**: every store read runs inside the `Store` actor, off the main thread, and the
   whole answer costs less than one frame. The "no cache, re-query on every keystroke" choice
   in `TodayModel` is confirmed cheap.
2. *The app, driven in the simulator with Time Profiler attached* (`xctrace record --attach`
   on the simulator's process while `BehaviourTests`-style code drove it; Debug). Two lessons
   about the method before the numbers: XCUITest's own accessibility snapshots dominate the
   main thread in any window where the test polls (`.exists`, `waitForExistence`), so those
   stacks (`XCT*`, `_accessibilityUserTestingSnapshot*`) have to be excluded before the app's
   own cost is visible; and `pgrep -x SwimZH` finds the app on whichever booted simulator ran
   it last, so the attach must match the device's UDID in the process path. With the harness
   excluded, the app's own main-thread work per interaction: **opening search ~120 ms, all of
   it UIKit's first keyboard bring-up** (`_showKeyboardIgnoringPolicyDelegate`,
   `UIInputWindowController`), not one sample in this app's code; **opening a pool ~40 ms**
   (the navigation transition and the map's engine); **the favourite swipe and tap ~30 ms**
   (the swipe animation, one collection-view layout). Launch to the first row is 4.4 s under
   XCUITest, of which the store load and first list is ~0.2 s; the rest is process launch,
   dyld and the Swift runtime (a quarter of the app's own launch samples are
   `swift_conformsToProtocol*` scanning, the well-known debug-build cost).

So the seconds felt on a phone are not this app's CPU work, and not disk. What they most
plausibly are: **first-use system bills** (the keyboard's first show, MapKit's first live
`Map` frame — both paid on the main thread at the moment of the tap), **a Debug build on a
device** (`-Onone` SwiftUI and the conformance scan above are several times slower than
Release; the scheme's Run action is Debug), and **rendering** (Liquid Glass sampling a list of
57 canvases, a glass panel over a live map), which a simulator's Mac GPU does not reproduce.
The honest next measurement is on the phone: Instruments → Time Profiler + Hangs on a
**Release** build, or the Xcode Organizer's hang reports after a TestFlight build.

**What changed.**

- *Launch.* The `.loading` state is the launch colour and nothing else: no spinner (the store
  answers in milliseconds, and the HIG reserves progress indication for waits a reader can
  feel), and no search bar — `.searchable` moved from the stack onto the READY screen, so the
  bottom bar arrives with the rows it searches rather than a beat before them over nothing.
- *Search.* `KeyboardWarmup` (was behind `lab.keyboardWarmup`; decided on): after the answer is
  on screen, a zero-alpha `UITextField` takes and resigns first responder once, which loads
  the input system without showing it. The first tap on search then costs what the second
  always did. Same shape as `MapWarmup`.
- *Pool screen.* `lab.poolMapArrival` (decided `afterPush`, switch deleted): SwiftUI must render a pushed
  screen's first frame before the push can begin, and that frame held a live `Map`. Now the
  first frame is a flat ground in the launch colour with the panel and the pool's name already
  on it; the push starts at once; the `Map` is built 450 ms later and fades in. `withPush` is
  the previous behaviour, for comparison. The map is still never resized (`PoolStage`).
- *Favourites.* `lab.favouriteMove` (decided `hold`, switch deleted). The kit's `listModel` gained a
  `leading:` set — WHICH favourites lead their tier — separate from `favourites` — which rows
  wear the heart. `TodayModel` holds `leading` at the order on screen across a heart toggle,
  and catches it up on the next refresh the reader causes or when the list arrives back at its
  top (`listReachedTop` — an arrival, not a state, so a row is never moved from under a
  thumb). `move` keeps the old instant reorder but publishes it inside an animation so the
  row slides rather than cuts; `never` drops favourites-first ordering altogether.
  `BehaviourTests.testFavouritingARowKeepsItWhereItIs` drives the hold and the settle.

Recommendation: keep all three defaults. `hold` is the only one of the three favourite
behaviours in which a swipe changes exactly one row; `afterPush` makes the tap answer before
the map does, which is what Apple Maps and Photos do with their own heavy content; the
keyboard preload is invisible when it works and costs one hidden field once per launch.
Judge the "few seconds" again on a Release build before deciding anything else.

## Recommended order

1. Icon (finding 1). One day, mostly Icon Composer, no Swift.
2. Day strip glass + morphing selection (finding 3) and the map card (finding 2) in one
   slice, because both need the lint allowlist and one screenshot retake.
3. Symbol effects (finding 5) ride along with slice 2.
4. Manual glass-slider pass (finding 7) after slice 2, on device.
5. Hero background extension (finding 4) as its own spike.
6. Widgets and intents as a separate plan.

### The pool screen leads with its numbers (2026-09-06, evening; decided the same night)

"Temperature, number of lanes and lane length — at a glance; and a link to the lane plan when
the pool has one; the address, phone and website rows repeat the buttons, push them down."

- `SwimZHKit/Glance.swift` — `glanceFacts`: water (live reading > measured > the pool's
  stated number, each captioned honestly; a stale live reading muted), the LONGEST basin's
  length, its lane count (falling back to the day's Belegungsplan count). `lanePlanLinks`: one
  per basin with a published plan URL. Tested in `GlanceTests`.
- `PoolGlance.swift` — ONE line under the kind and verdict: "26 °C · 50 m · 6 lanes" with
  glyphs; the caption is the VoiceOver label. **Decided over three captioned tiles**
  (`lab.glance`, deleted): the line costs almost no height in the drawer's smallest rest.
- `PoolActions` gained **Lane plan** (a menu of basin names when a pool has two — Oerlikon).
- `detailSections` order: about (blurb + schedule state), admission, season, basins, features,
  lockers, rentals, lanes, **where (address/phone/website) second to last**, source.
- `PanelDetent.peek` 0.36 → 0.42, pinned by the driven test's geometry check that the action
  captions are not clipped at the smallest rest.

### Pull to check for newer data (2026-09-06, night)

"Pull to update: first fetch the latest manifest and show me whether the data is up to date and
when it was updated, any staleness; when the manifest does not match the app's state, download."

The S5 rule was **no `.refreshable`**: the store is republished weekly, so a pull would spin and,
six days in seven, change nothing — a gesture that usually does nothing teaches distrust. The
rule is kept in its real form: the pull exists only where it can **always answer**.

- `SwimZHKit/DataStatus.swift` — `dataCheck(after: RefreshOutcome)` folds every outcome into one
  of four sentences: **up to date** (`.notNewer`), **newer data installed** (`.installed`),
  **update the app for newer data** (`.schemaMismatch`), **could not check** (everything else —
  offline is the common case and is worded as a state, not an error). `SourceFreshness` decodes
  the store's own `meta.source_freshness` (the lake's silver headers); `staleSources` picks the
  ones the build could not refresh. `Format.instant/storeInstant/storeInstantDay` render the
  ISO stamps (Python's microseconds are dropped before parsing — Foundation takes 0 or 3 digits).
- `TodayModel.checkForUpdates` is the pull: **never throttled** (the reader asked), records
  `dataStatus = (check, checkedAt)`, reloads on install. The automatic launch/foreground
  `refreshStore` now runs through the same path, still throttled to once an hour, so the data
  rows are filled in quietly without a pull. `canCheckForUpdates` is "a manifest URL is
  configured"; the seam (`host`, `manifestURL`, `fetcher`) is injectable, the transport is still
  named only in the kit (`SourceLintTests.noNetworkOutsideTheSeam` holds).
- `TodayView` — `.refreshable` sits behind `PullToCheck(enabled:)`: **no manifest URL, no
  gesture** (the only pull that could exist would say "could not check" forever). The data
  section under the answer gains: **Updated** (`built_at`, date + time), the check row
  (sentence + time of the check, `dataCheck`), and one muted row per stale source
  ("Prices: not refreshed since 30 August 2026", `staleSource`). The footer says "pull down to
  check" only when the pull exists. `UILintTests.listAndNoFakeRefresh` now pins exactly one
  `.refreshable`, behind the gate, with its answer rendered.
- Catalog: ten keys in all five languages (`meta.builtAt`, `meta.check.*`, `meta.staleSource`,
  `meta.offlineNote.pull`, `sources.roster/schedules/lanePlans`); iOS catalog regenerated.
- Tests: `DataStatusTests` (kit), `TodayModelPullTests` (app-hosted, a real `StoreHost` in a
  scratch directory with a counting stub fetcher: install + sentence + time, up to date,
  offline, and the throttle that the pull bypasses).

**The URL is set** (same night): the base `Info.plist` names
`https://widmogrod.github.io/swimming-in-zurich/manifest.json`, which is what `publish-store.yml`
already publishes; `AppCorrectnessTests.theManifestIsConfigured` pins https + our host (it used
to pin the opposite). Note the committed fixture store is BUILT LATER than the published one, so
a pull on a dev build says "up to date" until the workflow publishes again — the `built_at >`
rule doing its job. `-swimzh.autoCheck NO` (launch argument) turns only the automatic check off,
so `BehaviourTests.testPullingTheListChecksForNewerDataAndSaysWhatItFound` can prove the row is
the PULL's.

Considered and not done: comparing `content_hash` instead of `built_at` (a same-facts republish
would then say "up to date" rather than download; it needs the manifest to carry the hash — an
additive field — and a rollback publish would then be followed, which `built_at >` refuses).
Worth doing the day the cadence is daily.

### The About screen (2026-09-06, night)

"An About screen: who built the app, what state the pool database is in, how to contribute —
a link to GitHub."

- `App/SwimZH/AboutView.swift`, pushed as `Route.about` from a new **About SwimZH** row at the
  end of the list's data section (beside the colour legend). Four sections:
  1. the app — display name and `Version {version} ({build})`, both read from the bundle;
  2. **Pool data** — `{count} pools in Zürich` (a plural, so fr/it needed `many`), data from /
     answers through / updated, one row **per source** (`sources.roster` … `lanePlans`) saying
     `fetched {date}` or, muted, `kept from {date} — the site could not be reached`, the same
     `dataCheck` row the pull fills, and a **Check for newer data** button (progress while it
     runs, `TodayModel.isChecking`) for the reader who never pulls;
  3. **Made by** — `NSHumanReadableCopyright` from the base `Info.plist` (`© 2026 Gabriel
     Habryn`): a name lives in data, never as a literal, which is also what keeps
     `UILintTests.noSentencesInTheApp` honest;
  4. **Contribute** — three `Link`s (repository, issues, the city's pool pages) that open in the
     in-app sheet through the root `openURL` seam, and a footer inviting fixes, missing pools and
     translations.
- Sixteen catalog keys (`nav.about`, `about.*`) in five languages; `AboutLinks` holds the URLs.
- `BehaviourTests.testTheAboutScreenSaysWhoWhatAndHow` drives it: reachable from the list, the
  count and provenance rows exist, the repository link is there, and tapping the button produces
  the check row (launched with the automatic check off, so the row is provably the button's).

### Ready for a wide window — the unfolded phone (2026-09-06, evening)

"Apple released in iOS 27 a way for responsive apps … this is for the foldable phone; adjust
this app to be ready for it, in the unfolded state."

**What the SDK actually offers.** Nothing fold-specific: the iOS 27 SwiftUI and UIKit
interfaces were grepped for hinge / fold / posture and name none. What an unfolded phone will
report is what every wide window reports today — a **regular horizontal size class** — so
readiness means keying the layout off the size class and nothing else (never the idiom, never a
screen size), and surviving a size-class flip mid-session. The same code is what an iPad, a
Split View window and a landscape Max get, which is also how it is tested: the app target now
runs natively on iPad (`TARGETED_DEVICE_FAMILY = "1,2"`, all four iPad orientations so the window
is resizable), the iPad mini simulator stands in for the unfolded phone, and a Max rotation
stands in for the fold.

**Built, behind a rebuilt Lab** (`App/SwimZH/Lab.swift` + `Settings.bundle`, `@AppStorage`, live
on return from Settings; tests pass `-lab.<key> value`):

| Switch | Key | Values |
| --- | --- | --- |
| Wide layout | `lab.wideLayout` | `stage` (default): the map is the screen and the list floats over its leading side in a glass card (`StageColumn`, width from the kit's `listColumnWidth`); a tapped row's facts take the card (`PoolPresentation.column` — `FacilitySheet` renders its list branch, no second map) while the SAME map flies to the pool with its neighbours' pins kept (`PoolMapView.focus`, the pin marked but not carded); the map's pin card opens the same facts in the same card (`PoolMapView.open` replaces the column's stack). No Map tab — the map is always there. `phone`: the phone layout stretched, the control. |
| Search and filters | `lab.wideChrome` | `column` (default): NO tab bar in a wide window — the regular-width `TabView` floats at the top centre, over the column's top, and cannot be moved ("list and filters are on center and take space for sidebar", owner) — so the column's own navigation bar carries the search field and a Filters button, and the filters open as a POPOVER sized as a form (`formPopoverHeight`). `tabs`: the system tab bar, the control; its filter page is held to `formMaximumWidth` and centred ("filter full screen looks bad on iPad"). |
| Opening a pool zooms to | `lab.wideFocus` | `neighbourhood` (default): the answer's 1.5 km minimum span, so the pools around it stay on the map; `pool`: the phone pool-screen's 700 m. |

- **`split` was built first and deleted the same evening** — a `NavigationSplitView` with the
  list in the sidebar and the map in the detail column, a tapped pool pushed over the map as the
  phone's pool screen. The owner's reaction on seeing it: the sidebar was not a floating glass
  surface while the pin card over the map was, and a tap opened a *second* map instead of
  moving the one already there; they asked for a tap to zoom the map to the pool with the other
  pins kept and for the facts to expand the list's card. That is the stage.
- **Two rounds of the owner's eye on the iPad.** (1) The card was an opaque white sheet with
  glass corners: a `NavigationStack` paints `systemBackground` under everything it hosts, so
  the glass never showed — `containerBackground(.clear, for: .navigation)` on the stack (and on
  the pushed facts) plus `scrollContentBackground(.hidden)` on the lists is what makes the card
  read as the phone's `PoolPanel` does. (2) A pin on the stage opens the pool in the card in
  ONE tap (`PoolMapView.open`, no floating `PinCard` on the stage); the phone keeps the card.
- **The card moves** ("the sidebar should allow reducing its height or moving to a different
  side of the screen just by flicking or dragging a finger"). A grab handle at the card's top is
  the one drag area (the list under it keeps scrolling). Dragged down it rests at one of three
  heights (`ColumnDetent`: whole, half, or just the search field + day strip — anchored to the
  bottom, content laid out once at full height, the card a window from the top, as `PoolPanel`);
  flicked across it goes to the other side (`ColumnSide`, decided by where the card's centre was
  HEADED against the window's middle) and the map's inset follows. Rules in the kit
  (`columnVisibleHeight`, `columnDetent`, `columnSide`), tested; driven by
  `testTheColumnShrinksByItsHandleAndFlicksToTheOtherSide`. Also: a pin REPLACING the open pool
  needed `.id(poolID)` on the pool screen — same depth, new value, and SwiftUI kept the old
  screen's loaded state ("clicking on pins does not work").
- **Pulled for, not resident** (third round): the search row is hidden until the list is
  pulled past its top (`columnControlsShouldShow`, kit-tested; pinned while the field has focus
  or a query), so the card opens on the grab bar and the day strip. The facts list lost its top
  margin under the back button.
- **The day strip folds instead of vanishing** ("the animation of days hiding is not smooth
  on iPhone or iPad"): the `if` that removed it snapped the bar's height — and the list's top
  inset — in one step while only the strip's fade animated. The strip now sits in a frame
  animated from its measured height to zero, so bar and list move on one curve; the strip still
  leaves the tree, so the yield tests and VoiceOver see it go.
- **One icon source.** `Assets.xcassets/AppIcon.appiconset` (the flat PNG the review's finding 1
  replaced) still sat beside `AppIcon.icon` under the same name; the two idioms resolved it
  differently ("why does the app icon look different on iPhone vs iPad?"). Deleted; the layered
  icon is the only `AppIcon`, and both simulators' home screens now show the same icon.
- **The fold keeps the open pool.** One `contentPath: [Route]` is bound to the compact list
  stack and to the stage column's stack, so a pool open in the card is, after folding, the
  phone's map-with-drawer screen for the same route, and is back in the card after unfolding.
  Going wide takes the Map tab away and carries a pool pushed from it over to the list's path.
- Driven: `BehaviourTests.testAWideWindowIsAMapWithTheListFloatingOverItAndAPoolOpensInTheCard`
  and `testThePhoneLayoutIsTheControlInAWideWindow` (skip in a compact window; run on the iPad
  mini), `testFoldingKeepsTheOpenPool` (a Max on its side, then upright, then on its side).
- Follow-up not done: under `tabs` the top tab bar still overlaps the column's top; only
  `column` solves that, which is why it is the default.

### The wide Lab decided; the find screen split in two shells (2026-09-06, night)

"current defaults look good, so everything else in lab can be removed."

- **Decided:** `stage`, `column`, `neighbourhood`. `Lab.swift`, `Settings.bundle`, the
  `phone` control layout, the `tabs` chrome (and `FilterPage`'s wide-width branch that served
  only it, plus `formMaximumWidth`) and the `pool` focus span are deleted, with the two driven
  tests that launched them. No Lab remains in the app.
- **`TodayView` split.** At 860 lines it held eight jobs and 37 size-class / Lab branch points.
  It is now the FORK only (size class → shell, the shared `contentPath`, the fold, launch
  work), plus what both shells share: `Route` and `RouteScreen`, `StoreStates` (the store's
  three states), a `routed` / `bare` pair and `FilterPage(model:)`. The shells:
  `CompactShell` (the tab bar and its three stacks, `.searchable` and the suggestions),
  `WideShell` (the stage: map + `StageColumn`, the column's side and width, `ColumnControls`
  with the popover), and `AnswerList` (the rows under the day strip, the strip's yield and the
  pulled-for controls — one list for both shells, so they cannot render the answer two ways).
  The tab and searched-content state now live in `CompactShell` and are simply rebuilt after a
  fold; `mapPath` stays on `TodayView` because the fold reads it after the shell is gone.
- **One `Detent`.** `ColumnDetent` was `PanelDetent` with three other numbers. The kit now has
  `Detent` (peek / half / tall) and a `DetentScale` (`.panel`, `.column`), with
  `detentVisibleHeight` / `detentLanding` shared by `PoolPanel` and `StageColumn`;
  `panelRelease` (the dismiss rule) stays panel-only.
