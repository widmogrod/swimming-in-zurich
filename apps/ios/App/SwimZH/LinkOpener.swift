// LinkOpener.swift — a web link opens INSIDE the app.
//
// The pool screen has one link that leaves it: the pool's own page, tapped from the actions
// row or from the facts. It used to hand the address to Safari. The app went to the
// background, and the way back was the app switcher — for a reader who wanted one look at
// the pool's notice and then the map they were already on. Apple's own apps keep such a
// detour in place (Mail, Messages, News, Maps), and the HIG's "Safari view controller" page
// says why: the page is a side trip, so the app stays where it was and one button returns.
//
// A SHEET, decided 2026-09-06 after four openers were felt side by side: `SFSafariViewController`
// as a page sheet, so the pool screen stays visible behind the page and a pull down closes it.
// Safari's engine, the reader's own cookies and passwords, Reader and content blockers, the
// system's Liquid Glass bars — and the least code. The full-screen cover of the same controller,
// a `WebView` browser of the app's own (own Done, back/forward/reload, share) and the Safari
// app itself were the other three, and are deleted rather than left as unmeasured paths.
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
  /// Route every web link on this view's tree into the in-app sheet. Once, at the root.
  func linkOpening() -> some View { modifier(LinkOpening()) }

  /// Open Safari's connection to `url` while this view is on screen, so a later tap on it
  /// lands on a page rather than a spinner. A no-op for anything that is not a web address.
  func prewarmingLink(_ url: URL?) -> some View { modifier(LinkPrewarming(url: url)) }
}

struct LinkOpening: ViewModifier {
  @State private var link: WebLink?

  func body(content: Content) -> some View {
    content
      .environment(
        \.openURL,
        OpenURLAction { url in
          guard WebLink.isWeb(url) else { return .systemAction }
          link = WebLink(url: url)
          return .handled
        }
      )
      .sheet(item: $link) { link in
        SafariBrowser(link: link, onFinish: { self.link = nil })
          .ignoresSafeArea()
      }
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

/// Holds Safari's prewarmed connection for as long as the view it decorates is on screen.
struct LinkPrewarming: ViewModifier {
  let url: URL?
  @State private var token: SFSafariViewController.PrewarmingToken?

  func body(content: Content) -> some View {
    content
      .onAppear {
        guard let url, WebLink.isWeb(url) else { return }
        token = SFSafariViewController.prewarmConnections(to: [url])
      }
      .onDisappear {
        token?.invalidate()
        token = nil
      }
  }
}
