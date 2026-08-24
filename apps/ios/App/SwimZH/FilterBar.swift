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
  @Binding var filters: Filters
  let kinds: [String]
  /// The model's OWN headline. Not a count the bar formats: the sentence changes tense with
  /// the day ("3 open to you" is a present-tense claim and may only be made about today), and
  /// that decision belongs where a test can drive it.
  let headline: String
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
    .accessibilityLabel("Filters")
    .accessibilityValue(filters.summaryTags.joined(separator: ", "))
    .sheet(isPresented: $showingFilters) {
      FilterSheet(filters: $filters, kinds: kinds)
    }
  }

  @ViewBuilder
  private var summary: some View {
    VStack(alignment: .leading, spacing: 1) {
      Text(headline)
        .font(.subheadline.weight(.semibold))
      Text(
        filters.summaryTags.isEmpty ? "No filters" : filters.summaryTags.joined(separator: " · ")
      )
      .font(.caption)
      .foregroundStyle(.secondary)
      .lineLimit(1)
    }
  }
}

/// The controls. A plain `Form`, deliberately: every one of these is a standard system control,
/// and the system already knows how to lay them out at every text size, in both appearances and
/// under VoiceOver.
struct FilterSheet: View {
  @Binding var filters: Filters
  let kinds: [String]
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationStack {
      Form {
        Section("Who") {
          genderPicker
          agePicker
        }
        Section("Where") {
          placePicker
          radiusPicker
        }
        Section("What") {
          Toggle("Only sessions open to me", isOn: $filters.eligibleOnly)
          Toggle("Only my favourites", isOn: $filters.favouritesOnly)
          kindPicker
        }
      }
      .navigationTitle("Filters")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .confirmationAction) {
          Button("Done") { dismiss() }
        }
      }
    }
    .presentationDetents([.medium, .large])
  }

  private var genderPicker: some View {
    Picker("Gender", selection: $filters.gender) {
      // "Any" is the ABSENCE of a gender, not a fourth value: an unstated gender makes a
      // women-only session answer "check with the pool", which is the honest verdict.
      Text("Any").tag(Gender?.none)
      ForEach(Gender.allCases, id: \.self) { gender in
        Text(gender.rawValue.capitalized).tag(Gender?.some(gender))
      }
    }
    .pickerStyle(.segmented)
  }

  private var agePicker: some View {
    Picker("Age", selection: $filters.age) {
      ForEach(AgeBand.all) { band in
        Text(band.label).tag(band.age)
      }
    }
  }

  private var placePicker: some View {
    NavigationLink {
      PlaceTypeahead(place: $filters.place)
    } label: {
      LabeledContent("Measure from", value: filters.place?.label ?? "Anywhere")
    }
  }

  private var radiusPicker: some View {
    Picker("Within", selection: $filters.radiusKm) {
      // nil is NO limit, which is not the same as a very large one: with no radius a pool
      // that publishes no coordinates is still listed, and with one it cannot be.
      Text("Any distance").tag(Double?.none)
      // The value domain comes from the kit, beside `AgeBand.all` and `Places.presets`, so it
      // is pinned by a test rather than by a literal in a `ForEach`.
      ForEach(RadiusOption.all, id: \.self) { km in
        Text(
          Measurement(value: km, unit: UnitLength.kilometers),
          format: .measurement(width: .abbreviated)
        )
        .tag(Double?.some(km))
      }
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
    @Binding var place: Place?
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
      List {
        Button("Anywhere") {
          place = nil
          dismiss()
        }
        ForEach(Places.matching(query)) { candidate in
          placeRow(candidate)
        }
      }
      .searchable(text: $query, prompt: "Search places")
      .navigationTitle("Measure from")
      .navigationBarTitleDisplayMode(.inline)
    }

    private func placeRow(_ candidate: Place) -> some View {
      Button {
        place = candidate
        dismiss()
      } label: {
        LabeledContent(candidate.label) {
          checkmark(candidate)
        }
      }
    }

    @ViewBuilder
    private func checkmark(_ candidate: Place) -> some View {
      if candidate == place {
        Image(systemName: "checkmark").accessibilityLabel("Selected")
      }
    }
  }

  private var kindPicker: some View {
    // An empty selection means ALL kinds — so a kind added to the roster upstream appears
    // without a code change here.
    NavigationLink {
      List(kinds, id: \.self, selection: $filters.kinds) { kind in
        Text(kind.capitalized)
      }
      .environment(\.editMode, .constant(.active))
      .navigationTitle("Pool kinds")
    } label: {
      LabeledContent(
        "Pool kinds",
        value: filters.kinds.isEmpty ? "All" : filters.kinds.sorted().joined(separator: ", ")
      )
    }
  }
}
