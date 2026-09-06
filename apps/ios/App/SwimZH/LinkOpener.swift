// LinkOpener.swift — a web link opens INSIDE the app.
//
// The pool screen has one link that leaves it: the pool's own page, tapped from the actions
// row or from the facts. It used to hand the address to Safari. The app went to the
// background, and the way back was the app switcher — for a reader who wanted one look at
// the pool's notice and then the map they were already on. Apple's own apps keep such a
// detour in place (Mail, Messages, News, Maps), and the HIG's "Safari view controller" page
// says why: the page is a side trip, so the app stays where it was and one button returns.
//
// FOUR OPENERS, under `Lab.linkOpener`, because "in the app" still leaves a real choice to
// feel rather than argue: full screen, or a sheet the pool stays visible behind, or a browser
// of the app's own with the app's own glass bars. `Lab.LinkOpener` says what each costs.
//
// THE ONE SEAM. `linkOpening()` replaces the environment's `openURL` at the root, so every
// `Link` and every `openURL(...)` in the app reaches it — the facts' `Link`, the actions row,
// the filter sheet's Settings link — with no call site knowing. Only `http(s)` is taken:
// `tel:`, `maps:` and `app-settings:` are handed on to the system unchanged, because they were
// never web pages and the point was never to keep them.
//
// SAFARI, PREWARMED. `SFSafariViewController.prewarmConnections(to:)` opens the TLS
// connection to the pool's host while the reader is still reading the panel, so the tap
// shows a page rather than a spinner. The token is held for as long as the actions row is on
// screen and invalidated when it leaves, as the header of that API asks.

import SafariServices
import SwiftUI
import SwimZHKit
import WebKit

/// One address on its way to being shown. `Identifiable` by the address itself, so a
/// presentation binding can carry it and the same address tapped twice presents twice.
struct WebLink: Identifiable, Equatable {
  let url: URL
  var id: URL { url }

  /// Only a web page is ours to keep in the app; everything else the system already handles
  /// better than a browser would.
  static func isWeb(_ url: URL) -> Bool {
    let scheme = url.scheme?.lowercased()
    return scheme == "https" || scheme == "http"
  }
}

extension View {
  /// Route every web link on this view's tree through `Lab.linkOpener`. Once, at the root.
  func linkOpening() -> some View { modifier(LinkOpening()) }

  /// Open Safari's connection to `url` while this view is on screen, so a later tap on it
  /// lands on a page rather than a spinner. A no-op for the openers that never use Safari's
  /// controller, and for anything that is not a web address.
  func prewarmingLink(_ url: URL?) -> some View { modifier(LinkPrewarming(url: url)) }
}

struct LinkOpening: ViewModifier {
  @AppStorage(Lab.linkOpener) private var opener = Lab.LinkOpener.default
  @State private var link: WebLink?

  func body(content: Content) -> some View {
    content
      .environment(
        \.openURL,
        OpenURLAction { url in
          guard opener != .external, WebLink.isWeb(url) else { return .systemAction }
          link = WebLink(url: url)
          return .handled
        }
      )
      .fullScreenCover(item: covered) { link in
        switch opener {
        case .web:
          WebBrowser(link: link)
        case .safari, .sheet, .external:
          SafariBrowser(link: link, onFinish: { self.link = nil })
            .ignoresSafeArea()
        }
      }
      .sheet(item: sheeted) { link in
        SafariBrowser(link: link, onFinish: { self.link = nil })
          .ignoresSafeArea()
      }
  }

  // One piece of state, two presentations: the address goes to whichever the opener names,
  // and the other binding reads as nothing. Two `@State`s would be two chances to show both.
  private var covered: Binding<WebLink?> {
    Binding(get: { opener == .sheet ? nil : link }, set: { link = $0 })
  }
  private var sheeted: Binding<WebLink?> {
    Binding(get: { opener == .sheet ? link : nil }, set: { link = $0 })
  }
}

/// `SFSafariViewController`, as a SwiftUI view. Safari's engine and the reader's own Safari —
/// cookies, passwords, Reader, content blockers — and, on iOS 26 and later, the system's
/// Liquid Glass bars. Nothing here draws a control: the whole point of this opener is that
/// every control is Apple's.
struct SafariBrowser: UIViewControllerRepresentable {
  let link: WebLink
  /// The reader pressed Done or pulled the sheet down. The controller has dismissed itself by
  /// then; this lets the presentation state agree, so the same link can open again.
  let onFinish: () -> Void

  func makeUIViewController(context: Context) -> SFSafariViewController {
    let configuration = SFSafariViewController.Configuration()
    // The page as the pool published it. Reader would strip the timetable table the reader
    // came for.
    configuration.entersReaderIfAvailable = false
    // The bars shrink as the page scrolls, as Safari's do.
    configuration.barCollapsingEnabled = true
    let controller = SFSafariViewController(url: link.url, configuration: configuration)
    // The app's accent on Done and the toolbar, so the browser reads as part of the app.
    controller.preferredControlTintColor = UIColor(Color.accentColor)
    controller.dismissButtonStyle = .done
    controller.delegate = context.coordinator
    return controller
  }

  func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}

  func makeCoordinator() -> Coordinator { Coordinator(onFinish: onFinish) }

  final class Coordinator: NSObject, SFSafariViewControllerDelegate {
    let onFinish: () -> Void
    init(onFinish: @escaping () -> Void) { self.onFinish = onFinish }
    func safariViewControllerDidFinish(_ controller: SFSafariViewController) { onFinish() }
  }
}

/// The app's own browser: SwiftUI's `WebView` in the app's navigation stack, with the app's
/// bars. The system draws those bars in glass, the page's title sits in the top one, and the
/// bottom one carries what Safari's does — back, forward, reload, and the way out to Safari.
/// A progress line runs under the bar while the page loads, because a blank white page for
/// two seconds looks like a broken button.
struct WebBrowser: View {
  @Environment(\.localized) private var localized
  @Environment(\.dismiss) private var dismiss
  let link: WebLink
  @State private var page = WebPage()

  var body: some View {
    NavigationStack {
      WebView(page)
        // Safari's own gestures: swipe from the edge to go back, press a link for a preview.
        .webViewBackForwardNavigationGestures(.enabled)
        .webViewLinkPreviews(.enabled)
        .overlay(alignment: .top) { progress }
        .navigationTitle(page.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { bars }
    }
    .task { _ = page.load(link.url) }
  }

  @ViewBuilder
  private var progress: some View {
    if page.isLoading {
      ProgressView(value: page.estimatedProgress)
        .progressViewStyle(.linear)
        .transition(.opacity)
    }
  }

  /// Where the reader is now, or where they started if the page has not said yet.
  private var current: URL { page.url ?? link.url }

  @ToolbarContentBuilder
  private var bars: some ToolbarContent {
    ToolbarItem(placement: .topBarLeading) {
      Button {
        dismiss()
      } label: {
        Text(Message("action.done"), localized)
      }
      .accessibilityIdentifier("browserDone")
    }
    ToolbarItem(placement: .topBarTrailing) {
      ShareLink(item: current)
    }
    ToolbarItemGroup(placement: .bottomBar) {
      Button {
        if let item = page.backForwardList.backList.last { _ = page.load(item) }
      } label: {
        Image(systemName: Icon.back)
      }
      .disabled(page.backForwardList.backList.isEmpty)
      .accessibilityLabel(Text(Message("action.back"), localized))
      Button {
        if let item = page.backForwardList.forwardList.first { _ = page.load(item) }
      } label: {
        Image(systemName: Icon.forward)
      }
      .disabled(page.backForwardList.forwardList.isEmpty)
      .accessibilityLabel(Text(Message("action.forward"), localized))
    }
    ToolbarSpacer(.flexible, placement: .bottomBar)
    ToolbarItem(placement: .bottomBar) {
      Button {
        _ = page.reload()
      } label: {
        Image(systemName: Icon.reload)
      }
      .accessibilityLabel(Text(Message("action.reload"), localized))
    }
    ToolbarSpacer(.flexible, placement: .bottomBar)
    ToolbarItem(placement: .bottomBar) {
      Button {
        // Straight to the system, NOT through `openURL`: inside this browser that environment
        // is the app's own seam, and the reader asked to leave it.
        UIApplication.shared.open(current)
      } label: {
        Image(systemName: Icon.openInSafari)
      }
      .accessibilityLabel(Text(Message("action.openInSafari"), localized))
      .accessibilityIdentifier("browserOpenInSafari")
    }
  }
}

/// Holds Safari's prewarmed connection for as long as the view it decorates is on screen.
struct LinkPrewarming: ViewModifier {
  let url: URL?
  @AppStorage(Lab.linkOpener) private var opener = Lab.LinkOpener.default
  @State private var token: SFSafariViewController.PrewarmingToken?

  func body(content: Content) -> some View {
    content
      .onAppear {
        guard opener.usesSafariController, let url, WebLink.isWeb(url) else { return }
        token = SFSafariViewController.prewarmConnections(to: [url])
      }
      .onDisappear {
        token?.invalidate()
        token = nil
      }
  }
}
