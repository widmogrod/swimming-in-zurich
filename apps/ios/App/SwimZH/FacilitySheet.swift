// FacilitySheet.swift — the facility detail screen: a map, with the facts in a panel over it.
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
// THE SHAPE. The screen is `PoolStage` — the map, full screen — and the facts are `PoolPanel`
// over it, a card with three heights that is part of this view (not a presented sheet; the
// panel's header says why). The map stays live under the panel at every height. The way out of
// the screen is the back button or a swipe from the leading edge — `backSwipeEdge` keeps that
// edge free of the map's own pan. "When I click on a pool I'm shown a table" was the first
// version; a picture over a list was the second; the owner chose this third after seeing both.
//
// THE NAME IS SAID ONCE, in the panel at `heroTitle`. The bar over the map carries no title:
// with the panel always present there is never a moment the name has scrolled away, so a bar
// title would be the same word twice, six points apart — the duplication the second version
// spent a scroll rule (`poolTitleShows`, now deleted) avoiding.
//
// THE MAP DOES NOT WAIT FOR THE FACTS. `detail` is optional: the pool's place and name come
// from the roster and are known the moment the row is tapped, so the map and the panel with
// the name appear at once and the facts fill the panel when their six reads land. A spinner
// where the screen should be was the first thing the owner saw of the map screen, and this is
// the fix.
//
// A pool with no coordinates — none in the roster today, but the type allows it — gets the
// facts as a plain list, because a map with nothing to point at is worse than no map.

import SwiftUI
import SwimZHKit

struct FacilitySheet: View {
  @Environment(\.localized) private var localized
  /// The facts, once loaded. Nil while the store is still being read — see the header.
  let detail: FacilityDetail?
  /// The pool's name, from the roster, so the panel can say it before the facts arrive.
  let name: String
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

  /// Which of the panel's three heights it rests at. It starts at the smallest: the reader
  /// opened a pool, and the panel exists to say what it is while getting out of the map's way.
  @State private var detent: Detent = .peek
  /// How many times the reader has asked for the pool back under the pin. A count rather than a
  /// flag because the same request twice is two requests, and a flag cannot say the second.
  @State private var homeRequests = 0
  /// How far the facts list is pulled past its top, at the tallest rest. Read on every frame
  /// of a drag; letting go with it past `panelCollapsePull` steps the drawer down instead.
  @State private var listPull: Double = 0
  /// The drawer pulled past its smallest size is the way out — see `PoolPanel`.
  @Environment(\.dismiss) private var dismiss
  /// Whether the map has been asked for yet. False until the push has landed — see `stage`.
  @State private var mapArrived = false
  /// Stage or column — see `PoolPresentation`. In a column the screen is already inside a card
  /// over a live map (`StageColumn`), so a second map with a drawer would be a map over a map;
  /// the facts are a plain list there, under the same header, and the map behind flies to the
  /// pool (`PoolMapView.focus`).
  @Environment(\.poolPresentation) private var presentation

  var body: some View {
    if let point, presentation == .stage {
      ZStack(alignment: .bottom) {
        stage(point)
        PoolPanel(detent: $detent, onDismiss: { dismiss() }) {
          panelHeader
        } facts: {
          panelFacts
        }
        // ABOVE the drawer too: an edge swipe that began on the drawer went nowhere, because the
        // drawer's drag took it. The strip costs the drawer its outermost 22 points.
        backSwipeEdge
      }
      .navigationBarTitleDisplayMode(.inline)
      // The one map control, in the BAR: the system's own glass, at the back button's height
      // and size, on the opposite side. Floated over the map it sat lower and larger than the
      // back button beside it — two controls disagreeing about where the bar was.
      .toolbar {
        ToolbarItem(placement: .topBarTrailing) {
          Button {
            homeRequests += 1
          } label: {
            Image(systemName: Icon.backToPool)
          }
          .accessibilityLabel(Text(Message("action.backToPool"), localized))
          .accessibilityIdentifier("poolStageRecentre")
        }
      }
    } else {
      // The column, and the no-coordinates fallback: the same list. The header says the name
      // at once and the facts fill in under it — the column never opens on a bare spinner,
      // for the reason the panel never does.
      List {
        Section {
          panelHeader
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(.init(top: 0, leading: 0, bottom: 0, trailing: 0))
        }
        if let detail {
          facts(detail)
        }
      }
      .listStyle(.insetGrouped)
      .listSectionSpacing(.compact)
      // In the column the card is the surface, as it is for the panel: the list's grouped
      // ground and the pushed host's own ground would both paint over the glass.
      .scrollContentBackground(presentation == .column ? .hidden : .automatic)
      .containerBackground(.clear, for: .navigation)
      // Straight under the back button: the list's default top margin plus the header's own
      // air was a band of empty glass between the bar and the name.
      .contentMargins(.top, 0, for: .scrollContent)
      .navigationBarTitleDisplayMode(.inline)
      .accessibilityIdentifier("poolFacts")
    }
  }

  /// The map — or, until the push has landed, the ground it will fade in over.
  ///
  /// THE TAP USED TO WAIT FOR THE MAP. SwiftUI renders a pushed screen's first frame before
  /// the push animation can begin, and this screen's first frame held a live `Map`: MapKit's
  /// renderer, its tiles, the location dot. So the reader's tap on a row was followed by a
  /// pause, then a push — the "opening a pool lags" complaint. So the first frame is a flat
  /// ground in the launch colour (the panel with the pool's name is there at once), the push
  /// starts immediately, and the map is built one beat later and fades in. Decided
  /// 2026-09-06 over the map-in-the-first-frame variant, which is deleted.
  /// `MapWarmup` already paid the framework's cost; this moves the map's own first frame off
  /// the tap. The map view is never resized either way — see `PoolStage`.
  @ViewBuilder
  private func stage(_ point: GeoPoint) -> some View {
    if mapArrived {
      PoolStage(name: name, point: point, homeRequests: homeRequests)
        .transition(.opacity)
    } else {
      Color("LaunchBackground")
        .ignoresSafeArea()
        .task {
          // One push's worth of time, then the map. A fixed beat rather than a transition
          // callback: SwiftUI's navigation push exposes no completion, and the push itself
          // takes about this long.
          try? await Task.sleep(for: .milliseconds(450))
          withAnimation(.easeIn(duration: 0.25)) { mapArrived = true }
        }
    }
  }

  /// A strip along the leading edge that neither the map nor the drawer gets to take, so the
  /// system's swipe-back gesture can. Driven twice: with the map edge to edge, the map's own
  /// pan won every edge swipe; with the drawer up, the drawer's drag won the ones that began
  /// on it. Topmost in the stack, so it wins both.
  private var backSwipeEdge: some View {
    HStack(spacing: 0) {
      Color.clear
        .frame(width: Design.hitTarget / 2)
        .contentShape(Rectangle())
      Spacer(minLength: 0)
    }
    .frame(maxHeight: .infinity)
    .accessibilityHidden(true)
  }

  /// The drawer's fixed top: the pool's name, its answer and its actions once the facts are
  /// here, and the name over a spinner until then — so the drawer is never an empty card and
  /// the name is never absent. It never scrolls, so a drag on it always moves the drawer.
  @ViewBuilder
  private var panelHeader: some View {
    if let detail {
      PoolHeader(
        detail: detail, row: row, point: point, isToday: isToday, live: live, asOf: asOf
      )
      .padding(.horizontal, Design.Space.gutter)
    } else {
      VStack(alignment: .leading, spacing: Design.Space.gutter) {
        // A pool's name is a proper noun, never translated and never truncated.
        Text(verbatim: name)
          .font(.heroTitle)
          .fixedSize(horizontal: false, vertical: true)
        ProgressView()
      }
      .padding(.horizontal, Design.Space.gutter)
      .padding(.vertical, Design.Space.row)
      .frame(maxWidth: .infinity, alignment: .leading)
    }
  }

  /// The drawer's scrolling part: every published fact. It scrolls only at the tallest rest —
  /// lower, a drag on it moves the drawer — and a deliberate pull past its top at that rest
  /// steps the drawer down a size, the gesture a reader makes to get the map back.
  @ViewBuilder
  private var panelFacts: some View {
    if let detail {
      List {
        facts(detail)
      }
      .listStyle(.insetGrouped)
      .listSectionSpacing(.compact)
      // The card is the surface; the list's own grouped background would paint over it.
      .scrollContentBackground(.hidden)
      .contentMargins(.top, 0, for: .scrollContent)
      .scrollDisabled(detent != .tall)
      .onScrollGeometryChange(for: Double.self) { geometry in
        geometry.contentOffset.y + geometry.contentInsets.top
      } action: { _, scrolled in
        listPull = max(0, -scrolled)
      }
      .onScrollPhaseChange { old, _ in
        guard old == .interacting, panelCollapses(listPull: listPull) else { return }
        withAnimation(panelSpring) { detent = .half }
      }
    }
  }

  private func sections(_ detail: FacilityDetail) -> [DetailSection] {
    detailSections(detail, on: day, for: person, in: localized, live: live, at: asOf)
  }

  /// Every published fact, every caveat — the rows the screen was once only made of. ONE view,
  /// used by the panel and by the no-coordinates list, so the two cannot render a pool's facts
  /// two different ways.
  private func facts(_ detail: FacilityDetail) -> some View {
    ForEach(sections(detail)) { section in
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
