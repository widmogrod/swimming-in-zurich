// FilterBar.swift — the floating filter bar and the sheet behind it.
//
// The bar is attached with `safeAreaBar(edge:)`, NOT `safeAreaInset` and NOT `overlay`. That is
// the one modifier that extends the scroll edge effect under the bar, so the list visibly
// passes beneath it instead of being clipped by a rectangle floating over it. It is also the
// only place in the app that may apply `.glassEffect()` — a source lint enforces that, because
// the HIG says not to put Liquid Glass in the content layer and glass cannot sample glass, so
// a second glass surface renders inconsistently against this one.
//
// The bar itself is a summary plus a button; the controls live in a sheet. That mirrors the
// web, where the phone's sticky summary row IS the disclosure for the drawer — a filter bar
// that permanently occupied six controls' worth of a phone screen would cost more list than it
// is worth.

import SwiftUI
import SwimZHKit

struct FilterBar: View {
  @Environment(\.localized) private var localized
  @Binding var filters: Filters
  let kinds: [String]
  /// The model's OWN headline. Not a count the bar formats: the sentence changes tense with
  /// the day ("3 open to you" is a present-tense claim and may only be made about today) AND
  /// its plural form is the reader's language's business, which is precisely why it arrives as
  /// a `Message` carrying a count rather than as a finished string.
  let headline: Message
  @State private var showingFilters = false

  var body: some View {
    Button {
      showingFilters = true
    } label: {
      HStack(spacing: 8) {
        Image(systemName: "line.3.horizontal.decrease.circle")
        summary
        Spacer(minLength: 0)
        Image(systemName: "chevron.up").font(.footnote)
      }
      .padding(.horizontal, 16)
      .padding(.vertical, 10)
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    // The ONE glass surface in the app. See the header.
    .glassEffect(in: .capsule)
    .padding(.horizontal)
    .accessibilityLabel(Text(Message("mobile.filters"), localized))
    .accessibilityValue(Text(.joined(filters.summaryTags), localized))
    .sheet(isPresented: $showingFilters) {
      FilterSheet(filters: $filters, kinds: kinds)
    }
  }

  @ViewBuilder
  private var summary: some View {
    VStack(alignment: .leading, spacing: 1) {
      Text(headline, localized)
        .font(.subheadline.weight(.semibold))
      // Each tag is a whole unit and the middot is punctuation between them, so every tag is
      // localised BEFORE the join — a joined string handed to the catalog would be one opaque
      // sentence in English word order.
      summaryTags
        .font(.caption)
        .foregroundStyle(.secondary)
        .lineLimit(1)
    }
  }

  @ViewBuilder
  private var summaryTags: some View {
    if filters.summaryTags.isEmpty {
      Text(Message("filter.none"), localized)
    } else {
      Text(verbatim: filters.summaryTags.map { localized($0) }.joined(separator: " · "))
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
    .pickerStyle(.segmented)
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
      PlaceTypeahead(place: $filters.place)
    } label: {
      LabeledContent {
        Text(filters.place?.label ?? .key("place.anywhere"), localized)
      } label: {
        Text(Message("filter.measureFrom"), localized)
      }
    }
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
    @Binding var place: Place?
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
      List {
        Button {
          place = nil
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

    private func placeRow(_ candidate: Place) -> some View {
      Button {
        place = candidate
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
        Image(systemName: "checkmark")
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
