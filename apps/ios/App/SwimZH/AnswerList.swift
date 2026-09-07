// AnswerList.swift — the answer: the rows under the day strip, on every shell.
//
// ONE list for the phone and the wide column, so the two cannot rank, word or colour a pool
// two different ways. What differs between them is passed in: the wide column sits on glass
// (its grouped ground is hidden) and carries a row of controls above the strip that is PULLED
// FOR rather than resident (`ColumnControls`); the phone has neither.
//
// The day strip attaches to the SCROLLING view via `safeAreaBar(edge: .top)`, never to a
// wrapper around it: the system paints its scroll edge effect in response to the scroll view
// DIRECTLY under the bar, and a `VStack` whose first child is a static strip gives it nothing
// to answer. Reading DOWN the list takes the strip away and gives the rows its height; the
// smallest pull back up returns it, so changing day never costs a scroll to the top of fifty
// rows. Whether it shows is `SwimZHKit.stripShouldShow` — a rule, and a rule in a `body` is one
// nothing measures.
//
// `List`, not `LazyVStack`: not for speed (both are lazy, and 57 rows is noise either way) but
// for `.swipeActions` and system row and section styling.

import SwiftUI
import SwimZHKit

struct AnswerList: View {
  @Environment(\.localized) private var localized
  @Bindable var model: TodayModel
  let list: ListModel
  let metadata: StoreMetadata
  /// The wide column's controls, or nil on the phone. Their presence is what says the list is
  /// on glass, and they are shown only when pulled for.
  var column: ColumnControls? = nil

  /// Whether the day strip is on screen. View state rather than model state: nothing outside
  /// this screen has an opinion about it, and the DECISION it holds is the kit's.
  @State private var showsStrip = true
  /// Whether the list was at its top on the last scroll report — so the NEXT report can tell
  /// an arrival from a rest. See `listReachedTop`.
  @State private var listAtTop = true
  /// Whether the column's controls row is on screen — pulled for, never resident. The DECISION
  /// is the kit's (`columnControlsShouldShow`); this only records it, from the same scroll
  /// report the strip reads.
  @State private var showsControls = false

  /// The reader's text size, for one purpose only: how tall the strip is, which is what sets
  /// the gap between the two thresholds that hide and show it. Read the same way `DayStrip`
  /// reads it, through the same bridge.
  @Environment(\.dynamicTypeSize) private var dynamicTypeSize
  private var stripHeight: Double {
    stripLayout(for: TypeSize(dynamicTypeSize), width: 0).stripHeight
  }
  /// The strip's height as laid out — the kit's number until the first measurement, so the
  /// folding frame is right from the first frame and exact once the legend (which only the
  /// accessibility sizes add) has been measured.
  @State private var measuredStripHeight: Double =
    stripLayout(for: TypeSize(.large), width: 0).stripHeight

  var body: some View {
    listOrEmpty
      // Measured from the TOP OF THE CONTENT, not from the scroll view's own offset: hiding
      // the strip shrinks the top inset by its whole height and moves the raw offset by the
      // same amount, which is a jump in exactly the direction that would re-show it. See
      // `stripShouldShow`.
      .onScrollGeometryChange(for: Double.self) { geometry in
        geometry.contentOffset.y + geometry.contentInsets.top
      } action: { _, scrolled in
        report(scrolledTo: scrolled)
      }
      .safeAreaBar(edge: .top) {
        VStack(spacing: Design.Space.row) {
          // The column's controls, ONE row: the search field and the filters button, side by
          // side under the grab bar — and only when PULLED FOR. A navigation bar did this
          // first (a title row holding one button, the field in a drawer under it: a band of
          // empty glass), then a resident row; the owner wanted neither above the day strip.
          // Mail hides its search the same way.
          if let column, showsControls {
            column
              .transition(.move(edge: .top).combined(with: .opacity))
          }
          stripIfShown
            .animation(.snappy(duration: 0.22), value: showsStrip)
        }
      }
      .animation(.snappy(duration: 0.22), value: showsControls)
  }

  /// Read the scroll, ask the kit, record the answers.
  ///
  /// It does NOT call `withAnimation`. This runs on every frame of a scroll, and starting an
  /// animation from in here is how the app stopped ever reporting itself idle; the animation is
  /// declared on the bar instead, against these values.
  private func report(scrolledTo scrolled: Double) {
    // Arriving back at the top is when a held favourite may take its place at the front of
    // its tier — on screen, animated, and never out from under a thumb. Both halves of that
    // are the kit's (`listReachedTop`, `TodayModel.settleFavouriteOrder`); this only reports.
    if listReachedTop(scrolled: scrolled, wasAtTop: listAtTop) { model.settleFavouriteOrder() }
    listAtTop = listIsAtTop(scrolled: scrolled)
    if let column {
      let controls = columnControlsShouldShow(
        scrolled: scrolled, showing: showsControls, pinned: column.isPinned)
      if controls != showsControls { showsControls = controls }
    }
    let shows = stripShouldShow(
      scrolled: scrolled, stripHeight: stripHeight, showing: showsStrip)
    guard shows != showsStrip else { return }
    showsStrip = shows
  }

  /// The strip, in a frame that FOLDS when it yields. An `if` alone took the strip out of the
  /// bar in one step: the transition animated the strip's own fade, but the bar's height — and
  /// so the list's top inset — changed at once, and the rows jumped by a strip's height under
  /// the finger ("the animation of days hiding is not smooth"). The frame around it now animates
  /// from the strip's measured height to zero, so the bar and the list move together on one
  /// curve; the strip itself still leaves the tree, so a hidden strip is hidden to VoiceOver and
  /// to the driven tests alike.
  private var stripIfShown: some View {
    ZStack(alignment: .bottom) {
      if showsStrip {
        DayStrip(chips: model.chips, selection: $model.filters.day)
          .onGeometryChange(for: Double.self) { proxy in
            proxy.size.height
          } action: { height in
            if height > 0 { measuredStripHeight = height }
          }
          .transition(.opacity)
      }
    }
    .frame(height: showsStrip ? measuredStripHeight : 0, alignment: .bottom)
    .clipped()
  }

  @ViewBuilder
  private var listOrEmpty: some View {
    if list.beyondHorizon {
      beyondHorizon
    } else if list.isEmpty {
      // "Nothing matched" is NOT "everything is closed", and the wording says so: an empty
      // result is about the filters, and the remedy is in the user's hands.
      ContentUnavailableView {
        Label {
          Text(Message("combo.noPoolsMatch"), localized)
        } icon: {
          // The SAME glyph the browser's empty state uses. One sentence, one picture: the
          // two screens shipped `magnifyingglass` and the filter icon for the same words.
          Image(systemName: Icon.noMatch)
        }
      } description: {
        Text(Message("state.none.body.phone"), localized)
      }
    } else {
      rows
    }
  }

  /// The fifth day state, and it is the WHOLE SCREEN's state rather than any pool's: past the
  /// horizon there are no rows at all, so nothing here may read as a closure.
  private var beyondHorizon: some View {
    ContentUnavailableView {
      Label {
        Text(Message("state.beyondHorizon"), localized)
      } icon: {
        Image(systemName: Icon.beyondHorizon)
      }
    } description: {
      Text(
        Message(
          "state.beyondHorizon.body", ["date": localized.format.storeDate(metadata.horizonEnd)]),
        localized)
    }
  }

  private var rows: some View {
    // The list reserves a top margin for chrome that is no longer resident there — the search
    // field lives in the tab bar — which left a whole row of empty screen under the day
    // strip. Reclaimed deliberately, not by nudging paddings until it looked right.
    List {
      // The headline is a FACT, not a control, so it belongs in the content the eye reads
      // first — not riding in the chrome. It lived in the old filter bar, which is what made
      // that bar two lines tall and left it unable to share a row with anything.
      Text(list.headline, localized)
        .font(.screenHeadline)
        // The count ROLLS rather than cutting when the day changes. `.numericText()` is the one
        // content transition that understands digits, and this is the only line in the app
        // whose leading token is one. It costs nothing on the branches with no number in them.
        .contentTransition(.numericText())
        .animation(.snappy(duration: 0.3), value: list.day)
        .accessibilityIdentifier("headline")
        .listRowSeparator(.hidden)
        .listRowBackground(Color.clear)
        .listRowInsets(
          .init(
            top: 0, leading: Design.Space.gutter, bottom: 0, trailing: Design.Space.gutter)
        )
        .frame(maxWidth: .infinity, alignment: .leading)
      banners
      ForEach(list.sections) { section in
        Section {
          // ONE view per element, always. A `ForEach` element that resolves to a VARIABLE
          // number of views forces `List` to build every row's body just to learn the
          // identifiers (WWDC23 10160) — the laziness this screen must not lose as S3b adds
          // the expandable Gantt. `PoolRowView` is that one view; the lint keeps it that way.
          ForEach(section.rows) { row in
            PoolRowView(
              row: row,
              isFavourite: model.isFavourite(row.poolID),
              isToday: list.isToday,
              isExpanded: model.isExpanded(row.poolID),
              onToggleFavourite: { model.toggleFavourite(row.poolID) },
              onToggleExpanded: { model.toggleExpanded(row.poolID) }
            )
          }
        } header: {
          Label(section.title, systemImage: section.tier.symbol, localized)
        }
      }
      provenance
    }
    .modifier(PullToCheck(enabled: model.canCheckForUpdates) { await model.checkForUpdates() })
    .listStyle(.insetGrouped)
    // In the wide column the list is inside a glass card, and the card is the ground — see
    // `StageColumn`. On the phone the list keeps the system's grouped ground.
    .scrollContentBackground(column == nil ? .automatic : .hidden)
    // Inset-grouped sections default to about forty points of air between them. On a screen
    // whose whole job is a ranked list of six tiers, that is a row of pools spent on gaps.
    .listSectionSpacing(.compact)
    .contentMargins(.top, Design.Space.row, for: .scrollContent)
  }

  @ViewBuilder
  private var banners: some View {
    if !list.banners.isEmpty {
      Section {
        ForEach(list.banners) { banner in
          BannerView(banner: banner)
        }
      }
    }
  }

  private var provenance: some View {
    Section {
      // The VALUES are the store's own date KEYS (`2026-08-24`), so they go through
      // `Format.storeDate` before a reader sees them — the same fact the browser renders as
      // "24 August 2026". Shipping the key itself was a five-language regression hiding inside
      // a `Text(verbatim:)` that looked, correctly, like a value.
      // Each row is shown only when the store actually carries the stamp: the exporter writes
      // `gold_valid_as_of or ""`, and "Data from" followed by nothing is a blank where a fact
      // should be. An absent stamp means no row, not an empty one.
      stampRow(metadata.goldValidAsOf, label: "meta.dataFrom")
      stampRow(metadata.horizonEnd, label: "meta.answersThrough")
      // When the store in use was BUILT — the "when was it updated" a pull is asked for. An
      // instant, not a day key, so it goes through `storeInstant`; still shown as itself if
      // a store ever writes a stamp that is not one.
      if !metadata.builtAt.isEmpty {
        LabeledContent(
          content: { Text(verbatim: localized.format.storeInstant(metadata.builtAt)) },
          label: { Text(Message("meta.builtAt"), localized) })
      }
      // What the last check for a newer store found, and when. Nothing until one has run.
      if let check = model.dataStatus.check, let checkedAt = model.dataStatus.checkedAt {
        LabeledContent(
          content: { Text(verbatim: localized.format.dateTime(checkedAt)) },
          label: { Text(check.message, localized) }
        )
        .accessibilityIdentifier("dataCheck")
      }
      // Every source the build kept from an earlier run because it could not reach the site.
      // One row each, named: a reader told "prices: not refreshed since 30 August" can allow
      // for it; a reader told nothing cannot.
      ForEach(staleSources(metadata), id: \.source) { stale in
        Text(
          Message(
            "meta.staleSource",
            [
              "source": localized(stale.name),
              "date": localized.format.storeInstantDay(stale.fetchedAt),
            ]),
          localized
        )
        .foregroundStyle(.secondary)
        .accessibilityIdentifier("staleSource")
      }
      // The ribbon's colour key, at the end of the answer — where the colours are. It was two
      // taps deep inside an overflow menu — a legend nobody finds is a legend that is not
      // there, and without it the day tail's colours cannot be read at all.
      NavigationLink(value: Route.legend) {
        Label(Message("nav.accessTypes"), systemImage: Icon.legend, localized)
      }
      .accessibilityIdentifier("legendLink")
      // Who made this, what state the data is in, and how to help — one screen, at the end.
      NavigationLink(value: Route.about) {
        Label(Message("nav.about"), systemImage: Icon.about, localized)
      }
      .accessibilityIdentifier("aboutLink")
    } footer: {
      if model.canCheckForUpdates {
        Text(Message("meta.offlineNote.pull"), localized)
      } else {
        Text(Message("meta.offlineNote"), localized)
      }
    }
  }

  /// One dated row from `meta`, or nothing at all when the store carries no stamp.
  @ViewBuilder
  private func stampRow(_ key: String, label: String) -> some View {
    if !key.isEmpty {
      LabeledContent(
        content: { Text(verbatim: localized.format.storeDate(key)) },
        label: { Text(Message(label), localized) })
    }
  }
}

/// The pull, attached only when it can answer. SwiftUI has no "refreshable if", and a
/// `.refreshable` that runs a no-op is exactly the gesture the header refuses — so the
/// modifier is applied or not, and the DECISION (`canCheckForUpdates`) is the model's.
///
/// `.refreshable` ONLY when a manifest URL is configured, and it ALWAYS answers. The first S5
/// cut refused the gesture outright: the store changes weekly, so a pull would spin and, on six
/// days in seven, change nothing — and a gesture that usually does nothing teaches the reader
/// to distrust it. Decided 2026-09-06: the pull is worth having when it SAYS something every
/// time. It fetches the manifest and then the data section reports one of four sentences (up
/// to date / updated / could not check / update the app), the time of the check, when the
/// store was built, and any source the build could not refresh. An app with no manifest URL
/// gets no pull at all, because that pull could only ever say "could not check". The automatic
/// launch/foreground check fills the same rows, silently.
private struct PullToCheck: ViewModifier {
  let enabled: Bool
  let check: @Sendable () async -> Void

  func body(content: Content) -> some View {
    if enabled {
      content.refreshable { await check() }
    } else {
      content
    }
  }
}
