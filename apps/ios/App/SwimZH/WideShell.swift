// WideShell.swift — a wide window: the map is the screen, the list floats over it.
//
// An unfolded phone, an iPad, a landscape Max. The map is the whole window, edge to edge; the
// list rides over its leading side in a glass card (`StageColumn`, width from the kit's
// `listColumnWidth`). A tapped row's facts take the card (`PoolPresentation.column`:
// `FacilitySheet` renders its list branch, no second map) while the SAME map flies to the pool
// with its neighbours' pins kept (`PoolMapView.focus`, the pin marked but not carded). A pin
// on the map opens the same facts in the same card in ONE tap (`PoolMapView.open`) — it
// REPLACES the column's stack rather than pushing on it, so pin after pin never piles up
// screens behind the back button. Apple Maps on iPad. No Map tab: the map is always there.
//
// NO TAB BAR. The regular-width `TabView` floats at the top centre of the window, over the
// column's top, and there is no API to move it ("list and filters are in the centre and take
// the sidebar's space", owner). So the column carries its own controls: a search field and a
// Filters button, in ONE row under the grab bar — and only when PULLED FOR (`AnswerList`,
// `columnControlsShouldShow`): the card opens on the grab bar and the day strip. The filters
// open as a POPOVER from the button, sized as a form and not as a screen.
//
// The map is inset by the card's width so what it frames is framed in the part of it the
// reader can see; the inset follows the card when it is flicked to the other side.
//
// Built as one of three variants and chosen 2026-09-06: a `NavigationSplitView` (sidebar not
// glass, a tap opened a SECOND map) and the phone layout stretched (the control) are deleted.

import SwiftUI
import SwimZHKit

struct WideShell: View {
  @Bindable var model: TodayModel
  /// The column's stack — the owner's, so a fold keeps the open pool.
  @Binding var path: [Route]

  /// The window's width, for the column widths the kit derives from it.
  @State private var windowWidth: Double = 0
  /// Which edge the column sits against — flicked across by the reader. Held here because the
  /// MAP has to know it: the map is inset by the column's side.
  @State private var columnSide: ColumnSide = .leading
  /// Whether the filters popover is up.
  @State private var showsFilters = false
  /// Whether the column's field has the keyboard — one of the two things that pin the row.
  @State private var searchFocused = false

  var body: some View {
    ZStack(alignment: .topLeading) {
      StoreStates(model: model) { list, _ in
        PoolMapView(
          pins: poolPins(list.sections, geo: model.geoByPool),
          focus: focusedPool,
          open: { path = [.pool($0)] }
        )
        .safeAreaPadding(
          columnSide == .leading ? .leading : .trailing,
          listColumnWidth(in: windowWidth) + Design.Space.gutter)
      }
      StageColumn(windowWidth: windowWidth, side: $columnSide) {
        NavigationStack(path: $path) {
          StoreStates(model: model) { list, metadata in
            AnswerList(model: model, list: list, metadata: metadata, column: controls)
          }
          // No navigation bar in the column: its controls are in the bar above the strip.
          .bare()
          .routed(model)
          .containerBackground(.clear, for: .navigation)
        }
        .environment(\.poolPresentation, .column)
      }
    }
    .onGeometryChange(for: Double.self) { proxy in
      proxy.size.width
    } action: { width in
      windowWidth = width
    }
  }

  private var controls: ColumnControls {
    ColumnControls(model: model, hasFocus: $searchFocused, showsFilters: $showsFilters)
  }

  /// The pool the column is showing: the top of its stack, when that is a pool.
  private var focusedPool: String? {
    if case .pool(let poolID)? = path.last { return poolID }
    return nil
  }
}

/// The column's search field and filters button, in one row. The field is the app's own —
/// not `.searchable`, which needs a navigation bar to live in — bound to the same
/// `filters.search` the phone's field writes, so the list narrows as the reader types.
struct ColumnControls: View {
  @Environment(\.localized) private var localized
  @Bindable var model: TodayModel
  /// Reported up: the row must not vanish while the reader is typing in it.
  @Binding var hasFocus: Bool
  @Binding var showsFilters: Bool
  @FocusState private var focused: Bool

  /// Whether the row must stay whatever the list does: the field has focus, or holds a query.
  var isPinned: Bool { hasFocus || !model.filters.search.isEmpty }

  var body: some View {
    HStack(spacing: Design.Space.row) {
      field
      filtersButton
    }
    .padding(.horizontal, Design.Space.gutter)
    .onChange(of: focused) { _, focused in hasFocus = focused }
  }

  private var field: some View {
    HStack(spacing: Design.Space.row) {
      Image(systemName: Icon.noMatch)
        .foregroundStyle(.secondary)
      TextField(
        text: $model.filters.search, prompt: Text(Message("nav.findAPool"), localized)
      ) {
        Text(Message("nav.findAPool"), localized)
      }
      .textFieldStyle(.plain)
      .autocorrectionDisabled()
      .submitLabel(.search)
      .focused($focused)
      .accessibilityIdentifier("columnSearch")
      if !model.filters.search.isEmpty {
        Button {
          model.filters.search = ""
        } label: {
          Image(systemName: Icon.clearSearch)
            .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(Message("nav.findAPool"), localized))
      }
    }
    .padding(.horizontal, Design.Space.gutter)
    .frame(minHeight: Design.hitTarget)
    .background(.quaternary, in: Capsule())
  }

  /// The filters, behind one button, as a POPOVER: a form-sized surface anchored to the
  /// button, not a screen. The glyph fills when something is narrowed, as the phone tab's does.
  private var filtersButton: some View {
    Button {
      showsFilters.toggle()
    } label: {
      Image(systemName: model.filters.isNarrowed ? Icon.filterActive : Icon.filter)
        .font(.screenHeadline)
        .frame(width: Design.hitTarget, height: Design.hitTarget)
        .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityLabel(Text(Message("mobile.filters"), localized))
    .accessibilityIdentifier("filtersButton")
    .popover(isPresented: $showsFilters, arrowEdge: .top) {
      FilterPage(model: model)
        .frame(minWidth: listColumnMinimumWidth, minHeight: formPopoverHeight)
    }
  }
}
