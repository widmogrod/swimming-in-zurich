# App Review Information — Notes (SwimZH 0.1.3)

Paste the block below into App Store Connect →
App Review Information → Notes. Then reply to the Apple message
and attach the screen recording.

---

3. PURPOSE AND TARGET AUDIENCE

SwimZH answers one question: "Where can I go swimming in Zurich,
Switzerland, right now or on a chosen day?"

Residents and visitors of Zurich have to check ~57 separate public
swimming pool web pages to learn opening hours, prices, lane
closures, and who is allowed in (women-only slots, school-only
slots, age limits). SwimZH puts all of it in one offline list:
pick a day and a time, optionally set your age, gender and a
distance radius, and the app shows which pools are open and which
ones you are actually eligible to enter.

Audience: general public. No age-restricted content. Free.
No account, no advertising, no analytics, no tracking, no
in-app purchases, no user-generated content.

4. SETTING UP AND ACCESSING THE MAIN FEATURES

No login is required. There is no account system, so no demo
credentials and no sample files are needed. Everything works on
first launch, and works fully offline (airplane mode).

Main flows:
- Launch the app. The list opens on today, at the current time.
- Tap a day chip in the top strip to move to another date
  (up to ~400 days ahead).
- Drag the time axis to change the time of day.
- Tap "Filters" to set age, gender, pool type, and a distance
  radius. Eligibility labels on each pool update immediately.
- Tap any pool to open its detail sheet: opening hours, prices,
  per-lane occupancy plan, facilities, phone number, website,
  and directions.
- Switch to the map tab to see the same results as pins.
- Location is optional. If you deny or skip the location prompt,
  the app works exactly the same, minus distance sorting and
  the "you are here" dot.

5. EXTERNAL SERVICES AND DATA SOURCES

The app has NO backend of our own, no authentication service, no
payment processor, no AI service, and no third-party SDKs.

- Pool data (identity, address, coordinates, opening hours,
  prices, lane plans) is PRE-BAKED into a SQLite file embedded in
  the app bundle. It is derived from the City of Zurich's open
  government data (WFS geodata service) and the city's own public
  pool pages on stadt-zuerich.ch. This requires no network at
  runtime.
- The ONLY network request the shipped build makes is an optional
  live water-temperature reading from the City of Zurich's public
  open-data "Baditicker" feed:
  https://www.stadt-zuerich.ch/stzh/bathdatadownload
  It is anonymous, unauthenticated, and sends no user data. If it
  fails, the app states that the temperature is unavailable and
  everything else keeps working.
- Apple MapKit / Core Location are used for the map and for
  distance. Location is "when in use" only, optional, and never
  leaves the device.

6. REGIONAL DIFFERENCES

There are none. The app behaves identically in every region and
on every App Store storefront. The content is always the same:
public swimming pools in the city of Zurich, Switzerland.

The interface is localized into 5 languages — English, German,
French, Italian and Polish — and follows the device language.
That is a translation of the same content, not a feature or
content difference. Dates, distances and prices are formatted per
locale. No feature is gated by region, and no content is hidden
in any region.

7. REGULATED INDUSTRY / THIRD-PARTY MATERIAL

The app is not in a regulated industry. It offers no health,
medical, financial, gambling or other regulated service. It sells
nothing and books nothing — it does not reserve pool entry and
does not process payments.

All underlying data is public open government data published by
the City of Zurich under an open licence permitting use and
redistribution with attribution, plus publicly published pool
opening hours and tariffs from the city's own pages. The app is
independent and is not affiliated with, endorsed by, or presented
as an official app of the City of Zurich.

2. TESTED DEVICES AND OPERATING SYSTEMS

The submitted build (0.1.3, build 8) was installed from TestFlight
and tested on a physical device:

- iPhone 13 — iOS 27 (public beta)

The app is iPhone only (no iPad) and requires iOS 26.0 or later.
It uses no beta-only APIs; the submitted binary was built with the
public Xcode 26 SDK on a clean CI machine.

1. SCREEN RECORDING

A screen recording made on the physical iPhone 13 above, running
the TestFlight build of 0.1.3 (8), is attached to this reply. It
starts at app launch and walks through the core flow: the day
strip, the time axis, the filters (age, gender, pool type,
distance), a pool detail sheet, the map, and the "when in use"
location permission prompt.

There is nothing else to record: the app has no account
registration, no login, no account deletion, no paid content, no
purchases or subscriptions, no user-generated content, and no App
Tracking Transparency prompt. Location is the only permission the
app ever requests, and it is optional.
