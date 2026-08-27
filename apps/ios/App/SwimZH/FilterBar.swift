// FilterBar.swift — the floating filter bar and the sheet behind it.
//
// NOBODY HERE PAINTS GLASS, and the comment that used to say this file was the one place
// allowed to describes an app that no longer exists. The filter control is a toolbar item, so
// the SYSTEM draws its bar, its Liquid Glass and its scroll edge effect. That is the whole
// lesson of the iOS 26 guidance: you do not apply the material, you use the chrome that already
// has it. The lint is now a flat ban — a `.glassEffect(` anywhere in the app target means
// something is being hand-built again.
//
// The bar itself is a summary plus a button; the controls live in a sheet. That mirrors the
// web, where the phone's sticky summary row IS the disclosure for the drawer — a filter bar
// that permanently occupied six controls' worth of a phone screen would cost more list than it
// is worth.

import SwiftUI
import SwimZHKit

/// The filter control, as ONE toolbar item.
///
/// It used to be a full-width capsule in a `safeAreaBar` of its own, carrying the headline
/// sentence on a second line. That made it two rows tall and unable to share a bar with
/// anything — so when iOS 26 drew its search field at the bottom (which is where iPhone
/// search now lives), the two stacked, and the rows underneath were hidden behind both.
///
/// As a toolbar item it shares the system's bar, and its glass, with the search field. The
/// headline moved into the list, where a fact belongs.
struct FilterButton: View {
  @Binding var filters: Filters
  let kinds: [String]
  /// The phone's own position. Threaded down rather than reached for, so this file has no
  /// opinion about Core Location and the sheet can be previewed without one.
  let location: any LocationFixing
  /// Measure from the phone. `async` because it is a device that takes a moment to answer, and
  /// the row has to be able to say so while it does.
  let onUseMyLocation: () async -> Void
  /// Measure from a named place, or from nowhere. Separate from a plain binding because
  /// choosing a preset must ALSO stop the device preference — see `TodayModel.useNamedPlace`.
  let onUseNamedPlace: (Place?) -> Void

  @Environment(\.localized) private var localized
  @State private var showingFilters = false

  var body: some View {
    Button {
      showingFilters = true
    } label: {
      Label {
        Text(Message("mobile.filters"), localized)
      } icon: {
        Image(systemName: filters.isNarrowed ? Icon.filterActive : Icon.filter)
      }
    }
    // The value, not the label, is what changes — so a reader who has narrowed the list hears
    // WHAT it is narrowed to, rather than the word "Filters" twice.
    .accessibilityValue(Text(.joined(filters.summaryTags), localized))
    .accessibilityIdentifier("filterButton")
    .sheet(isPresented: $showingFilters) {
      FilterSheet(
        filters: $filters, kinds: kinds, location: location,
        onUseMyLocation: onUseMyLocation, onUseNamedPlace: onUseNamedPlace)
    }
  }
}

/// The controls. A plain `Form`, deliberately: every one of these is a standard system control,
/// and the system already knows how to lay them out at every text size, in both appearances and
/// under VoiceOver.
struct FilterSheet: View {
  @Environment(\.localized) private var localized
  @Binding var filters: Filters
  let kinds: [String]
  let location: any LocationFixing
  let onUseMyLocation: () async -> Void
  let onUseNamedPlace: (Place?) -> Void
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationStack {
      Form {
        // iOS 26 renders a section header EXACTLY as it is written — it no longer
        // upper-cases them — so these read as sentence-case headings in every language, and
        // the catalogs were audited for entries that had relied on the system shouting.
        Section {
          genderPicker
          agePicker
        } header: {
          Text(Message("filter.section.who"), localized)
        }
        Section {
          placePicker
          radiusPicker
        } header: {
          Text(Message("filter.section.where"), localized)
        }
        Section {
          Toggle(isOn: $filters.eligibleOnly) {
            Text(Message("filter.eligibleOnly.toggle"), localized)
          }
          Toggle(isOn: $filters.favouritesOnly) {
            Text(Message("filter.favouritesOnly.toggle"), localized)
          }
          kindPicker
        } header: {
          Text(Message("filter.section.what"), localized)
        }
      }
      .navigationTitle(Text(Message("mobile.filters"), localized))
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .confirmationAction) {
          Button {
            dismiss()
          } label: {
            Text(Message("action.done"), localized)
          }
        }
      }
    }
    .presentationDetents([.medium, .large])
  }

  private var genderPicker: some View {
    Picker(selection: $filters.gender) {
      // "Any" is the ABSENCE of a gender, not a fourth value: an unstated gender makes a
      // women-only session answer "check with the pool", which is the honest verdict.
      Text(Message("toolbar.gender.any"), localized).tag(Gender?.none)
      ForEach(Gender.allCases, id: \.self) { gender in
        // The raw value is the EXPORT's token; `.capitalized` on it was an English word with a
        // Swiss accent. The catalog has these three under the same keys the web toolbar uses.
        Text(Message("toolbar.gender.\(gender.rawValue)"), localized).tag(Gender?.some(gender))
      }
    } label: {
      Text(Message("toolbar.gender"), localized)
    }
    // The Form's DEFAULT style, like the two pickers under it. Segmented put four labels in a
    // fixed width in five languages: German and French truncated at ordinary text sizes and
    // were unreadable at accessibility ones, and it was the only control in the sheet that did
    // not look like the rest.
  }

  private var agePicker: some View {
    Picker(selection: $filters.age) {
      ForEach(AgeBand.all) { band in
        Text(band.label, localized).tag(band.age)
      }
    } label: {
      Text(Message("toolbar.age"), localized)
    }
  }

  private var placePicker: some View {
    NavigationLink {
      PlaceTypeahead(
        place: filters.place, location: location, onUseMyLocation: onUseMyLocation,
        onUseNamedPlace: onUseNamedPlace)
    } label: {
      LabeledContent {
        Text(filters.place?.label ?? .key("place.anywhere"), localized)
      } label: {
        Text(Message("filter.measureFrom"), localized)
      }
    }
    .accessibilityIdentifier("measureFrom")
  }

  private var radiusPicker: some View {
    Picker(selection: $filters.radiusKm) {
      // nil is NO limit, which is not the same as a very large one: with no radius a pool
      // that publishes no coordinates is still listed, and with one it cannot be.
      Text(Message("filter.anyDistance"), localized).tag(Double?.none)
      // The value domain comes from the kit, beside `AgeBand.all` and `Places.presets`, so it
      // is pinned by a test rather than by a literal in a `ForEach`.
      ForEach(RadiusOption.all, id: \.self) { km in
        Text(verbatim: localized.format.distance(kilometres: km))
          .tag(Double?.some(km))
      }
    } label: {
      Text(Message("filter.within"), localized)
    }
    .disabled(filters.place == nil)
  }

  /// The place typeahead — a searchable list over `Places.matching(_:)`.
  ///
  /// A search field rather than a `Picker`, because `Places.matching` is the kit's diacritic-
  /// and case-folding rule and a picker would leave it unreachable: tested code nothing calls is
  /// worse than either alone. "Anywhere" is a row of its own, so clearing the origin is one tap
  /// and can never be confused with a very large radius.
  struct PlaceTypeahead: View {
    @Environment(\.localized) private var localized
    /// The chosen place, READ ONLY. It used to be a `Binding` written straight from this view,
    /// which is exactly the shape that cannot express "the reader asked for their position and
    /// we have not got one yet": a binding must be assigned something, and the only honest
    /// something at that moment is nothing at all. Both ways of choosing are closures now, and
    /// the device one installs a place only if `devicePlace` yields one.
    let place: Place?
    let location: any LocationFixing
    let onUseMyLocation: () async -> Void
    let onUseNamedPlace: (Place?) -> Void
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
      List {
        Section {
          myLocationRow
        } footer: {
          locationFooter
        }
        Button {
          onUseNamedPlace(nil)
          dismiss()
        } label: {
          Text(Message("place.anywhere"), localized)
        }
        // The match runs against the RENDERED label, so a French reader searching "gare"
        // finds the station — which is why `Places.matching` needs the renderer at all.
        ForEach(Places.matching(query, in: localized)) { candidate in
          placeRow(candidate)
        }
      }
      .searchable(text: $query, prompt: Text(Message("place.searchPrompt"), localized))
      .navigationTitle(Text(Message("filter.measureFrom"), localized))
      .navigationBarTitleDisplayMode(.inline)
    }

    /// Measure from the phone.
    ///
    /// It does NOT dismiss on tap, and that is the difference between this row and every other
    /// one here. A preset answers instantly, so leaving is the right next thing; a fix takes a
    /// moment and can fail, and a sheet that closed on the tap would leave the reader looking at
    /// a list still measured from the station with nothing anywhere to say why.
    private var myLocationRow: some View {
      Button {
        Task { await onUseMyLocation() }
      } label: {
        // An `HStack`, not the `LabeledContent` every other row here uses, and that was
        // measured. `LabeledContent` is built for a Form ROW; inside a `Button`'s label it
        // reshapes the element enough that an `.accessibilityIdentifier` on the button never
        // reaches the accessibility tree — `BehaviourTests` could not find this row at all
        // while a `strings` check proved the identifier was in the shipped binary.
        HStack {
          Text(Message("place.useMyLocation"), localized)
          Spacer(minLength: Design.Space.tight)
          locationTrailing
        }
        .contentShape(Rectangle())
      }
      .accessibilityIdentifier("useMyLocation")
      .disabled(location.state == .locating)
    }

    @ViewBuilder
    private var locationTrailing: some View {
      if location.state == .locating {
        ProgressView()
      } else if place?.source == .device {
        // HOW OLD THE FIX IS, next to the tick that says it is the one in use. The row could
        // say "Use my location ✓" over a coordinate taken before a tram ride — a foreground
        // refresh that is refused leaves the earlier fix installed, which is right, but until
        // now nothing on any screen said it was old. `Date()` is read as the row is drawn:
        // this is a pushed screen the reader has just opened, so the age is current when it
        // is read, and a ticking caption in a picker would be movement for its own sake.
        // No identifier of its own: a `Button` combines its label's children into ONE
        // accessibility element (the reason `myLocationRow` is an `HStack` at all), so this
        // reaches VoiceOver as part of the row's own announcement rather than beside it.
        if let stale = stalePositionNote(fixedAt: location.fixedAt, at: Date(), in: localized) {
          Text(stale, localized)
            .font(.rowFact)
            .foregroundStyle(.secondary)
        }
        Image(systemName: Icon.selected)
          .accessibilityLabel(Text(Message("a11y.selected"), localized))
      }
    }

    /// Why it did not work, and — only where Settings can actually fix it — a way there.
    ///
    /// The three refusals are three sentences and three remedies (`LocationRefusal`), so an
    /// "Open Settings" button under `restricted` would send someone to a switch they are not
    /// allowed to move, and under `unavailable` to a page showing nothing wrong.
    @ViewBuilder
    private var locationFooter: some View {
      if let note = locationNote(location.state) {
        VStack(alignment: .leading, spacing: Design.Space.snug) {
          Text(note, localized)
          settingsButton
        }
        .accessibilityIdentifier("locationNote")
      }
    }

    @ViewBuilder
    private var settingsButton: some View {
      if settingsCanFix(location.state), let url = URL(string: UIApplication.openSettingsURLString)
      {
        Link(destination: url) {
          Text(Message("action.openSettings"), localized)
        }
        .accessibilityIdentifier("openSettings")
      }
    }

    private func placeRow(_ candidate: Place) -> some View {
      Button {
        onUseNamedPlace(candidate)
        dismiss()
      } label: {
        LabeledContent {
          checkmark(candidate)
        } label: {
          Text(candidate.label, localized)
        }
      }
    }

    @ViewBuilder
    private func checkmark(_ candidate: Place) -> some View {
      if candidate == place {
        Image(systemName: Icon.selected)
          .accessibilityLabel(Text(Message("a11y.selected"), localized))
      }
    }
  }

  private var kindPicker: some View {
    // An empty selection means ALL kinds — so a kind added to the roster upstream appears
    // without a code change here.
    NavigationLink {
      List(kinds, id: \.self, selection: $filters.kinds) { kind in
        // Through `poolKindLabel`, not `.capitalized`: the raw token is the WFS roster's own
        // word ("school", "paddling") and capitalising it put a domain token on screen.
        Text(poolKindLabel(kind), localized)
      }
      .environment(\.editMode, .constant(.active))
      .navigationTitle(Text(Message("filter.poolKinds"), localized))
      // Inline, like every other title in the app. This one screen was still opening with a
      // large one, which is a different header height on the third push of the same flow.
      .navigationBarTitleDisplayMode(.inline)
    } label: {
      LabeledContent {
        selectedKinds
      } label: {
        Text(Message("filter.poolKinds"), localized)
      }
    }
  }

  @ViewBuilder
  private var selectedKinds: some View {
    if filters.kinds.isEmpty {
      Text(Message("filter.allKinds"), localized)
    } else {
      Text(.joined(filters.kinds.sorted().map { .message(poolKindLabel($0)) }), localized)
    }
  }
}
