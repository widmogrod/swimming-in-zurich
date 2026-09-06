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
| Deployment target | `IPHONEOS_DEPLOYMENT_TARGET = 26.0`, Swift 6 | Nothing blocks iOS 27 APIs behind `#available` |

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

Every visual change is behind a **Lab switch** so the two looks can be compared on a phone:
`App/SwimZH/Lab.swift` names five `UserDefaults` keys, read through `@AppStorage`, defaulting
to the NEW look; `App/SwimZH/Settings.bundle` puts the four toggles in the system Settings app
under SwimZH (English only, deliberately: they exist until a variant is chosen, then the key,
the toggle and the losing branch are deleted). Tests pass `-lab.<key> NO` as launch arguments;
`Lab.typeLaunchArguments()` rewrites those string values as real booleans in the volatile
argument domain, because `@AppStorage<Bool>` reads a string as absent — the first "old look"
screenshot set was pixel-identical to the new one for exactly that reason.

| Switch | Key | On | Off |
| --- | --- | --- | --- |
| Day strip | `lab.stripStyle` (picker) | `morph`: chips in a `GlassEffectContainer`, the selected tint a separate glass view with one `glassEffectID` that morphs chip to chip — but each tap also swaps the tapped chip's own glass off, three glass transitions at once, and the press lens never shows on the selected chip; `tint` (default): one interactive glass per chip always, selection is a tint cross-fade, the lens works; `button`: the system `GlassButtonStyle`, same tint rule | `flat`: tinted chips |
| Bottom bar | `lab.bottomBar` (picker) | `toggle`: the same toolbar with list/map as ONE glyph-swapping glass button, so every control presses alike; `tabs`: a system `TabView` — Find, Map, All pools, `Tab(role: .search)` — whose selection is the tab bar's own draggable glass lens, the filter as `tabViewBottomAccessory`, `tabBarMinimizeBehavior(.onScrollDown)` | `toolbar`: bottom toolbar with a segmented list/map picker (a flat thumb inside the bar's glass — the one control with no lens) |
| Glass map card | `lab.glassCard` | `.glassEffect(.regular.interactive())`, `.materialize` transition, no shadow | `.regularMaterial` + shadow |
| Symbol motion | `lab.symbolMotion` | heart draws on/off, filter glyph replace + bounce | plain swaps |
| Links open in | `lab.linkOpener` (picker) | `safari` (default): `SFSafariViewController` full screen, prewarmed; `sheet`: the same as a pull-down page sheet; `web`: SwiftUI `WebView` in the app's own glass bars | `external`: the Safari app |

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
- **`lab.linkOpener`**, a picker in Settings > SwimZH with four values:
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

## Recommended order

1. Icon (finding 1). One day, mostly Icon Composer, no Swift.
2. Day strip glass + morphing selection (finding 3) and the map card (finding 2) in one
   slice, because both need the lint allowlist and one screenshot retake.
3. Symbol effects (finding 5) ride along with slice 2.
4. Manual glass-slider pass (finding 7) after slice 2, on device.
5. Hero background extension (finding 4) as its own spike.
6. Widgets and intents as a separate plan.
