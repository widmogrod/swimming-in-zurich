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
| Zoom push, haptics, numeric roll | `matchedTransitionSource`, `.sensoryFeedback`, `.numericText()` | Good iOS 26 delight, all declarative |
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
`App/SwimZH/Lab.swift` names four `UserDefaults` keys, read through `@AppStorage`, defaulting
to the NEW look; `App/SwimZH/Settings.bundle` puts the four toggles in the system Settings app
under SwimZH (English only, deliberately: they exist until a variant is chosen, then the key,
the toggle and the losing branch are deleted). Tests pass `-lab.<key> NO` as launch arguments;
`Lab.typeLaunchArguments()` rewrites those string values as real booleans in the volatile
argument domain, because `@AppStorage<Bool>` reads a string as absent — the first "old look"
screenshot set was pixel-identical to the new one for exactly that reason.

| Switch | Key | On | Off |
| --- | --- | --- | --- |
| Glass day strip | `lab.glassStrip` | chips in a `GlassEffectContainer`; the selected tint is a separate glass view with one `glassEffectID`, so it morphs chip to chip | flat tinted chips |
| Glass map card | `lab.glassCard` | `.glassEffect(.regular.interactive())`, `.materialize` transition, no shadow | `.regularMaterial` + shadow |
| Hero map under the bar | `lab.heroExtends` | full-bleed map; the list ignores the top safe area so the map sits under the status bar and the glass back button; title handover threshold subtracts the measured bar height | 150 pt rounded map inside the row |
| Symbol motion | `lab.symbolMotion` | heart draws on/off, filter glyph replace + bounce | plain swaps |

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

## Recommended order

1. Icon (finding 1). One day, mostly Icon Composer, no Swift.
2. Day strip glass + morphing selection (finding 3) and the map card (finding 2) in one
   slice, because both need the lint allowlist and one screenshot retake.
3. Symbol effects (finding 5) ride along with slice 2.
4. Manual glass-slider pass (finding 7) after slice 2, on device.
5. Hero background extension (finding 4) as its own spike.
6. Widgets and intents as a separate plan.
