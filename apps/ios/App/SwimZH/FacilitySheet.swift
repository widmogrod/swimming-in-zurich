// FacilitySheet.swift — the facility detail screen.
//
// It renders `[DetailSection]` and decides NOTHING. Every sentence, every caveat and every
// omission was decided in `SwimZHKit.detailSections`, where a test drives it — which is what
// makes S3b acceptance 4's "these fields are rendered" a checkable claim rather than a
// declaration. `FieldCoverageTests.renderedRowsExistForEveryClaimedField` walks the whole
// roster out of the committed store and demands a row for every field named as rendered.
//
// The one thing this file decides is which rows are ACTIONABLE: a phone number dials, a website
// opens. Both are `Link`/`Button` rather than plain text because a tappable number beside an
// address is what a swimmer standing outside a locked door actually needs.
//
// THE NAME IS SAID ONCE. The screen opened with it in the navigation bar AND at `heroTitle`
// underneath, six points apart — the same word twice, which is the plainest kind of careless.
// Deleting either copy would have been wrong: the hero is what makes the push continuous with
// the row you tapped, and a bar with no title on a pushed screen leaves a bare chevron with
// nothing to say what you are looking at once the hero has scrolled away.
//
// So the bar waits. It is empty while the hero's name is on screen and takes the name over the
// moment it is not — which is exactly what a `.large` navigation title does for free, and what
// a hand-built hero has to be told to do. The decision is `SwimZHKit.poolTitleShows`; the
// height it needs is measured here, because it depends on the reader's text size.

import SwiftUI
import SwimZHKit

struct FacilitySheet: View {
  @Environment(\.localized) private var localized
  let detail: FacilityDetail
  let day: String
  let person: Person
  /// The live water temperature, when it has been asked for. Nil means "not asked yet", not
  /// "unavailable" — the unavailable states are values of `LiveTemp` and each says its own
  /// reason. See `SwimZHKit.liveWaterRow`.
  let live: LiveTemp?
  /// The instant the live reading's age is stated as of. Threaded in rather than read here, so
  /// the sheet and its loader cannot disagree about what "now" is — and so a test can state it.
  let asOf: Date
  /// The answer's row for this pool, or nil when the screen was reached from the all-pools
  /// browser. See `PoolHeader`.
  let row: PoolRow?
  /// Where the pool is, from the roster. The detail payload carries an address but no
  /// coordinates, so this is threaded in rather than looked up here.
  let point: GeoPoint?
  let isToday: Bool

  /// Whether the bar is stating the name yet. See the header.
  @State private var showsTitle = false

  /// `Lab.heroExtends`: the hero map runs edge to edge and under the navigation bar, rather
  /// than sitting as a rounded picture inside the first row's gutters. The row's insets and
  /// the title handover both depend on it, which is why the sheet reads the flag and not only
  /// `PoolHeader`.
  @AppStorage(Lab.heroExtends) private var heroExtends = true

  /// How tall the hero's name is at the reader's text size. `@ScaledMetric` rather than a
  /// constant for the same reason the day strip's height is one: at an accessibility size this
  /// line is more than twice as tall, and a fixed threshold would hand the name to the bar
  /// while it was still plainly on screen.
  @ScaledMetric(relativeTo: .title) private var nameHeight = 41

  /// How far down the content the hero's name ends: the map, the gap under it, the name itself,
  /// and the section's own top inset. Composed from the parts rather than written as one number
  /// so that changing the map's height cannot silently desynchronise the handover.
  ///
  /// The top inset is the row's, so it is composed from the SAME value `heroInsets` uses:
  /// when the hero extends, the row has no top inset and the name ends that much sooner.
  ///
  /// EXTENDED, the list starts under the bar rather than below it, so the name is hidden not
  /// when it leaves the screen but when it passes under the bar's bottom edge — `barBottom`
  /// points earlier. Measured, not assumed: the bar's height is the system's, and it differs
  /// between a phone with a Dynamic Island and one without.
  private var nameBottom: Double {
    let underTheBar = heroExtends ? barBottom : 0
    // The map is taller by the part of it under the bar, and the bar hides that much of the
    // content: the two cancel, and writing both keeps the handover honest if either moves.
    return heroInsets.top + heroMapHeight + underTheBar + Design.Space.gutter + nameHeight
      - underTheBar
  }

  /// The top safe area — status bar plus navigation bar — as measured OUTSIDE the list, which
  /// is the only place it can be read once the list itself ignores it.
  @State private var barBottom: Double = 0

  /// The hero row's insets. With the hero extended the map reaches all three top edges of the
  /// row — the gutters move INTO `PoolHeader`, under the map, so the name and the actions keep
  /// their margin while the picture does not.
  private var heroInsets: EdgeInsets {
    heroExtends
      ? EdgeInsets(top: 0, leading: 0, bottom: Design.Space.row, trailing: 0)
      : EdgeInsets(
        top: Design.Space.row, leading: Design.Space.gutter,
        bottom: Design.Space.row, trailing: Design.Space.gutter)
  }

  var body: some View {
    List {
      // THE SCREEN NO LONGER OPENS ON A TABLE. See `PoolHeader` for what replaced it and why
      // every row below it survived the change.
      Section {
        PoolHeader(
          detail: detail, row: row, point: point, isToday: isToday,
          heroTopInset: heroExtends ? barBottom : 0
        )
        .listRowInsets(heroInsets)
        .listRowBackground(Color.clear)
        .listRowSeparator(.hidden)
      }
      // The section's own side margins would keep an edge-to-edge map twenty points short
      // of each edge; they go to zero for the hero section alone. `nil` is the default.
      .listSectionMargins(.horizontal, heroExtends ? 0 : nil)
      ForEach(sections) { section in
        Section {
          ForEach(section.rows) { row in
            DetailRowView(row: row)
          }
        } header: {
          // iOS 26 renders a section header exactly as written; it no longer upper-cases it.
          // The catalog entries are therefore sentence case in all five languages.
          Text(section.title, localized)
        }
      }
    }
    .listStyle(.insetGrouped)
    .listSectionSpacing(.compact)
    // THE HERO REACHES UNDER THE BAR, and `.backgroundExtensionEffect()` alone did not do it —
    // driven and photographed: inside a `List` row the effect had nothing to extend into, and
    // the screen opened on a band of empty background between the back button and the map.
    // What reaches is the list itself starting at the top of the screen: the map is then the
    // thing under the status bar and the glass back button, and the bar's own scroll edge
    // effect does the softening. Off the switch, nothing here changes.
    .contentMargins(.top, heroExtends ? 0 : nil, for: .scrollContent)
    .ignoresSafeArea(edges: heroExtends ? .top : [])
    // Read on the view that still HAS a top safe area — the one outside `ignoresSafeArea` —
    // because inside it the inset is, by construction, zero.
    .onGeometryChange(for: Double.self) { proxy in
      proxy.safeAreaInsets.top
    } action: { inset in
      barBottom = inset
    }
    // The sheet's rendered identity is the pool's NAME, never its id — which is why
    // `FacilityDetailOut.facility_id` stays deliberately omitted from `renderedFields`. It is
    // rendered twice over: at `heroTitle` in `PoolHeader`, and here once that has scrolled off.
    .navigationTitle(showsTitle ? Text(verbatim: detail.name) : Text(verbatim: ""))
    .navigationBarTitleDisplayMode(.inline)
    // Measured from the top of the CONTENT, the same quantity the find screen's day strip
    // watches — and unlike that one this needs no correction for a moving inset, because
    // filling in a title changes no layout.
    .onScrollGeometryChange(for: Double.self) { geometry in
      geometry.contentOffset.y + geometry.contentInsets.top
    } action: { _, scrolled in
      title(scrolledTo: scrolled)
    }
    .animation(.easeInOut(duration: 0.2), value: showsTitle)
  }

  /// Read the scroll, ask the kit, record the answer. It does NOT call `withAnimation`: this
  /// runs on every frame of a drag, and the animation is declared against the value instead —
  /// the lesson the day strip's first version cost.
  private func title(scrolledTo scrolled: Double) {
    let shows = poolTitleShows(scrolled: scrolled, nameBottom: nameBottom, showing: showsTitle)
    guard shows != showsTitle else { return }
    showsTitle = shows
  }

  private var sections: [DetailSection] {
    detailSections(detail, on: day, for: person, in: localized, live: live, at: asOf)
  }
}

/// One line of the sheet. ONE view per `ForEach` element (the laziness rule), so everything a
/// row can grow into — its caveat, its link — lives inside a single `VStack`.
struct DetailRowView: View {
  @Environment(\.localized) private var localized
  let row: DetailRow

  var body: some View {
    VStack(alignment: .leading, spacing: Design.Space.hair) {
      value
      caveat
    }
    .accessibilityElement(children: .combine)
  }

  /// The row's value, rendered ONCE and reused: a URL test and a `tel:` build both need the
  /// characters, and rendering it twice would be two chances to disagree.
  private var rendered: String { localized(row.value) }

  @ViewBuilder
  private var value: some View {
    if let url = URL(string: rendered), rendered.hasPrefix("http") {
      Link(destination: url) {
        LabeledContent {
          Text(verbatim: rendered).lineLimit(1).truncationMode(.middle)
        } label: {
          Text(row.label, localized)
        }
      }
    } else if row.id == "phone",
      let url = URL(string: "tel:\(rendered.filter { !$0.isWhitespace })")
    {
      // `tel:` is the one URL an offline app can still act on usefully.
      //
      // `if let`, not `!`, and the same shape `PoolHeader.call` already uses for the same
      // field. This is STORE data — a scraped phone string — so any character the scrape
      // carries through that `URL` will not accept (a parenthesised area code, a stray
      // non-ASCII digit) crashed the whole sheet rather than losing one row of it. A pool whose
      // number cannot be dialled falls through to the plain text row below, where the number is
      // still readable and copyable.
      Link(destination: url) {
        LabeledContent {
          Text(verbatim: rendered)
        } label: {
          Text(row.label, localized)
        }
      }
    } else if row.isProse {
      // A PARAGRAPH, so the label goes ABOVE it and the text runs left-to-right across the
      // whole row. In a `LabeledContent` it would sit in the trailing slot and wrap against
      // the right margin, giving a ragged left edge — which is exactly how the pool blurb
      // shipped, and what the first App Store screenshot caught. `isProse` is the kit's
      // rule, not a length guess here: a short blurb is still prose, and a long address is
      // still a fact.
      VStack(alignment: .leading, spacing: Design.Space.hair) {
        Text(row.label, localized)
        Text(verbatim: rendered)
          .foregroundStyle(.secondary)
          // Without this a wrapped `Text` inside a row can still be given one line's height
          // and truncate, which loses the end of the very paragraph this branch exists for.
          .fixedSize(horizontal: false, vertical: true)
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    } else {
      LabeledContent {
        Text(verbatim: rendered)
          .multilineTextAlignment(.trailing)
          // A weaker fact, shown as one. `row.muted` is set by ONE rule in the kit — a live
          // water reading that is hours old, or that the sensor has not taken — so a
          // nine-hour-old temperature does not read with the weight of a nine-minute-old one.
          // The words are unchanged either way; only the emphasis moves.
          .foregroundStyle(row.muted ? AnyShapeStyle(.secondary) : AnyShapeStyle(.primary))
      } label: {
        Text(row.label, localized)
      }
    }
  }

  /// The honesty line: why this fact is weaker than it looks. Never truncated — a caveat that
  /// runs off the edge of the row is a caveat nobody reads.
  @ViewBuilder
  private var caveat: some View {
    if let caveat = row.caveat {
      Text(caveat, localized)
        .font(.rowNote)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }
  }
}
