# App Store listing — SwimZH

The copy and the answers the App Store Connect forms ask for, kept here so a re-submission or a
new locale starts from what was actually filed rather than from memory. **Every claim below is
one the app can back**; if a feature changes, this file changes with it.

Bundle ID `ch.swimzh.SwimZH` · Team `A5A644VYCS` · submitted automatically by
`.github/workflows/release.yml` on a published GitHub Release.

## App Information

| Field | Value |
| --- | --- |
| Name (≤30) | `SwimZH: Zürich Pools` |
| Subtitle (≤30) | `Every pool, when it is open` |
| Primary category | Sports |
| Secondary category | Health & Fitness |
| Content rights | Does not contain third-party content |
| Age rating | 4+ (no objectionable content of any kind) |
| Privacy policy URL | `https://widmogrod.github.io/swimming-in-zurich/privacy.html` |
| Support URL | `https://github.com/widmogrod/swimming-in-zurich` |
| Marketing URL | *(leave empty)* |
| Copyright | `2026 Gabriel Habryn` |

## Keywords (≤100 characters, comma-separated, no spaces)

```
schwimmen,hallenbad,freibad,badi,seebad,baden,bahnen,schwimmbad,lane,swim,badeanzeiger
```

86 characters. The name and subtitle are indexed too, which is why "zürich", "pool" and "open"
are deliberately NOT repeated here — that budget buys the German words a local actually types.

## Promotional text (≤170, editable without a new build)

```
Indoor and outdoor, all of Zürich. Opening hours, lane plans and prices — offline, on the day you actually want to swim.
```

## Description

```
SwimZH answers one question: where can I go swimming in Zürich — right now, or on a day you pick?

Every public pool in the city in one list, sorted by how far away it is: the indoor Hallenbäder, the outdoor Freibäder, and the lake Seebäder.

WORKS WITH NO SIGNAL
The whole timetable ships inside the app. Opening hours, prices, lane plans and pool sizes are answered instantly and offline — in a changing room, in a tram tunnel, on a plan-the-week evening. The app refreshes its data quietly in the background when it can.

ANY DAY, NOT JUST TODAY
Swipe the day strip forward. School terms and public holidays are already built in, so a Wednesday in the autumn break shows the hours that genuinely apply that day, not the usual ones.

FILTERS THAT MATCH REAL SESSIONS
Women-only hours, men-only hours and age limits are part of a pool's schedule, not a footnote under it. Say who is swimming and the list narrows to sessions you can actually attend.

LANES, NOT GUESSES
Where the city publishes a Belegungsplan, you can see which lanes a club has reserved and which are left for the public.

HONEST ABOUT WHAT IT DOESN'T KNOW
A pool with no published timetable is shown as "schedule unknown" — never as "closed". A water temperature that could not be read says so, rather than showing you this morning's number from three weeks ago.

LIVE WATER TEMPERATURE
Open a pool and, where the city publishes one, you get the current reading together with the time it was taken.

FIVE LANGUAGES
English, German, French, Italian and Polish — with Swiss date and number formats, not approximations of them.

PRIVATE BY DESIGN
No account. No analytics. No advertising. No tracking. Your location is used to measure distance and to place you on the map, and it never leaves your phone.

Pool data comes from the City of Zürich's published pool pages and its open geodata. SwimZH is an independent app and is not affiliated with or endorsed by the City of Zürich.
```

## What's New (first release)

```
First release. Every public pool in Zürich — indoor, outdoor and lake — with opening hours, prices, lane plans and live water temperatures, working offline.
```

## App Privacy questionnaire

Answer **"No, we do not collect data from this app."** That is literally true and each part of it
is provable:

- No account, no analytics SDK, no advertising SDK, no crash reporter.
- The privacy manifest declares `NSPrivacyTracking = false`, an empty
  `NSPrivacyTrackingDomains`, and an empty `NSPrivacyCollectedDataTypes` — asserted by
  `AppCorrectnessTests`.
- The only declared required-reason API is `UserDefaults` (`CA92.1` — the app's own defaults in
  its own container).
- Location is read on device and never transmitted (`LocationSource.swift`).
- The two network calls the app makes — a water temperature, and the store refresh — carry no
  identifier and nothing about the reader (`Live.swift`, `Refresh.swift`, the only two files
  permitted to touch the network).

## Export compliance

**No** — the app uses no encryption beyond standard HTTPS, which is exempt. The release lane
answers this automatically (`export_compliance_uses_encryption: false` in `fastlane/Fastfile`),
so it does not stall in "Waiting for Export Compliance".

## Screenshots

Required: **at least one 6.9" iPhone screenshot, 1320 × 2868**. Apple scales that set down to the
other sizes, so one device family is enough.
