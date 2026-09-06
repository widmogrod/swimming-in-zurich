// AboutView.swift — who made this, what state the pool data is in, and how to help.
//
// Three questions a curious reader asks at the bottom of the list, answered on one pushed
// screen. Everything here is either a catalog `Message`, a value the store or the bundle
// wrote (formatted), or a URL — the same rule as every other screen. The two facts that name
// a PERSON come out of `Info.plist` (`NSHumanReadableCopyright`, Apple's own key), so a name
// lives in data and never as a literal in a Swift file.
//
// The DATA section is the reader-facing "state of the database": how many pools, when the
// facts were collected, how far the answers reach, when the store was built, what the last
// check for a newer store found, and — per source — when the build last reached the city's
// pages and whether it had to keep an older copy. It is the same `dataStatus` the list's pull
// fills, with a BUTTON for the reader who never pulls.

import SwiftUI
import SwimZHKit

/// The addresses the About screen offers. Configuration, in one place; the app's `openURL` is
/// replaced at the root (`LinkOpener.swift`) so each opens inside the app.
enum AboutLinks {
  static let repository = URL(string: "https://github.com/widmogrod/swimming-in-zurich")!
  static let issues = URL(string: "https://github.com/widmogrod/swimming-in-zurich/issues")!
  static let city = URL(
    string:
      "https://www.stadt-zuerich.ch/de/sport-und-erholung/sport-und-badeanlagen/hallenbaeder.html"
  )!
}

struct AboutView: View {
  @Environment(\.localized) private var localized

  let poolCount: Int
  let metadata: StoreMetadata?
  let status: DataStatus
  let canCheck: Bool
  let isChecking: Bool
  let check: @Sendable () async -> Void

  var body: some View {
    List {
      identity
      data
      madeBy
      contribute
    }
    .listStyle(.insetGrouped)
    .navigationTitle(Text(Message("about.title"), localized))
    .navigationBarTitleDisplayMode(.inline)
  }

  // MARK: - The app

  private var identity: some View {
    Section {
      HStack(spacing: Design.Space.gutter) {
        Image(systemName: Icon.about)
          .font(.heroTitle)
          .foregroundStyle(.tint)
          .accessibilityHidden(true)
        VStack(alignment: .leading, spacing: Design.Space.hair) {
          Text(verbatim: appName).font(.rowTitle)
          Text(
            Message("about.version", ["version": marketingVersion, "build": buildNumber]),
            localized
          )
          .font(.rowFact)
          .foregroundStyle(.secondary)
        }
      }
      .padding(.vertical, Design.Space.tight)
      .accessibilityElement(children: .combine)
    }
  }

  /// The bundle's display name — a proper noun the plist carries, never a catalog entry.
  private var appName: String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String
      ?? Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String ?? ""
  }

  private var marketingVersion: String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
  }

  private var buildNumber: String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""
  }

  // MARK: - The data

  private var data: some View {
    Section {
      Text(Message("about.poolCount", count: poolCount), localized)
        .accessibilityIdentifier("aboutPoolCount")
      if let metadata {
        stampRow(metadata.goldValidAsOf, label: "meta.dataFrom")
        stampRow(metadata.horizonEnd, label: "meta.answersThrough")
        if !metadata.builtAt.isEmpty {
          LabeledContent(
            content: { Text(verbatim: localized.format.storeInstant(metadata.builtAt)) },
            label: { Text(Message("meta.builtAt"), localized) })
        }
        ForEach(metadata.sourceFreshness, id: \.source) { source in
          sourceRow(source)
        }
      }
      if let check = status.check, let checkedAt = status.checkedAt {
        LabeledContent(
          content: { Text(verbatim: localized.format.dateTime(checkedAt)) },
          label: { Text(check.message, localized) }
        )
        .accessibilityIdentifier("dataCheck")
      }
      if canCheck {
        checkButton
      }
    } header: {
      Text(Message("about.data"), localized)
    } footer: {
      Text(Message("about.dataNote"), localized)
    }
  }

  /// One source's provenance: its name, and either when the build fetched it or — muted, as
  /// a caveat — the older copy it had to keep.
  private func sourceRow(_ source: SourceFreshness) -> some View {
    let date = localized.format.storeInstantDay(source.fetchedAt)
    return VStack(alignment: .leading, spacing: Design.Space.hair) {
      Text(source.name, localized).font(.noticeTitle)
      switch source.status {
      case .fresh:
        Text(Message("about.source.fresh", ["date": date]), localized)
          .font(.noticeBody)
          .foregroundStyle(.secondary)
      case .stale:
        Text(Message("about.source.stale", ["date": date]), localized)
          .font(.noticeBody)
          .foregroundStyle(.secondary)
      }
    }
    .accessibilityElement(children: .combine)
    .accessibilityIdentifier(source.status == .stale ? "staleSource" : "freshSource")
  }

  private var checkButton: some View {
    Button {
      Task { await check() }
    } label: {
      HStack {
        if isChecking {
          Label(Message("about.checking"), systemImage: Icon.checkNow, localized)
        } else {
          Label(Message("about.checkNow"), systemImage: Icon.checkNow, localized)
        }
        if isChecking {
          Spacer()
          ProgressView()
        }
      }
    }
    .disabled(isChecking)
    .accessibilityIdentifier("checkNow")
  }

  @ViewBuilder
  private func stampRow(_ key: String, label: String) -> some View {
    if !key.isEmpty {
      LabeledContent(
        content: { Text(verbatim: localized.format.storeDate(key)) },
        label: { Text(Message(label), localized) })
    }
  }

  // MARK: - The people

  private var madeBy: some View {
    Section {
      LabeledContent(
        content: { Text(verbatim: copyright) },
        label: { Label(Message("about.madeBy"), systemImage: Icon.author, localized) })
    }
  }

  /// Apple's `NSHumanReadableCopyright`, set in the base `Info.plist`.
  private var copyright: String {
    Bundle.main.object(forInfoDictionaryKey: "NSHumanReadableCopyright") as? String ?? ""
  }

  // MARK: - Contributing

  private var contribute: some View {
    Section {
      Link(destination: AboutLinks.repository) {
        Label(Message("about.repository"), systemImage: Icon.repository, localized)
      }
      .accessibilityIdentifier("aboutRepository")
      Link(destination: AboutLinks.issues) {
        Label(Message("about.issues"), systemImage: Icon.issue, localized)
      }
      Link(destination: AboutLinks.city) {
        Label(Message("about.dataSource"), systemImage: Icon.city, localized)
      }
    } header: {
      Text(Message("about.contribute"), localized)
    } footer: {
      Text(Message("about.contributeNote"), localized)
    }
  }
}
