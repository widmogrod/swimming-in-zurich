// Store.swift — the read-only, bundle-safe SQLite reader.
//
// THE FINDING THIS FILE EXISTS TO HONOUR: a WAL-mode database cannot be read from an app
// bundle at all. `sqlite3_open_v2` returns SQLITE_OK and the FIRST PREPARE fails with
// SQLITE_CANTOPEN, because WAL needs its `-wal`/`-shm` sidecars and a writable directory,
// and an iOS bundle offers neither. The export guarantees the file is not WAL (asserted on
// header byte 18, because `PRAGMA journal_mode` can fail silently); this side opens it
// `READONLY | NOMUTEX | URI` with `immutable=1`, which tells SQLite the file cannot change
// underneath it and removes the last reason it would want to touch a sidecar or a lock.
//
// CONCURRENCY. Apple's SQLite is built `SQLITE_THREADSAFE=2` (multi-thread), NOT upstream's
// serialized default, so a connection is not internally mutex-protected; and
// `OpaquePointer`'s `Sendable` conformance is explicitly unavailable in the stdlib, so it
// cannot be papered over. Hence: the handle lives inside this actor — the actor IS the
// mutex, which is why the open flags say NOMUTEX — every method is a single non-suspending
// unit (actors are reentrant, so a suspension inside one would let another in), and no
// `sqlite3_stmt*` ever escapes: every method returns decoded value types.
//
// TWO FOOTGUNS, both pinned by tests in `StoreTests`:
//  1. `sqlite3_open_v2` returns a handle EVEN ON FAILURE. Not closing it on the error path
//     leaks the connection; `open` below closes before throwing.
//  2. `sqlite3_bind_text` with `SQLITE_STATIC` and a bridged Swift `String` is a
//     use-after-free: the C buffer Swift lends for the call is gone by the time
//     `sqlite3_step` reads it. Every bind here is `SQLITE_TRANSIENT`, and a source lint
//     asserts `SQLITE_STATIC` appears nowhere in `Sources/`.
//
// MEMORY. Apple's build sets `DEFAULT_CACHE_SIZE=2000` — a POSITIVE value, i.e. 2000 pages
// ≈ 8 MB, four times upstream's 2 MB — so the cache size is set explicitly rather than
// inherited. `mmap` is preferred because SQLite's heap page cache is DIRTY memory and counts
// fully against the app's footprint, while mmap'd read-only pages are CLEAN and are not.

import Foundation
import SQLite3

/// `sqlite3_bind_text`'s "copy this buffer" destructor. Never `SQLITE_STATIC` — see the
/// header. The stdlib exposes neither constant, so both are spelled out in C's terms and
/// only the safe one is defined here, so the wrong one cannot be reached by autocomplete.
private let sqliteTransient = unsafeBitCast(
  -1,
  to: (@convention(c) (UnsafeMutableRawPointer?) -> Void)?.self
)

/// 2 MiB of page cache (a NEGATIVE `cache_size` is KiB, not pages), plus 64 MiB of mmap
/// window. The whole store is ~2 MB today, so the mmap window covers it and the dirty page
/// cache stays a bounded fallback.
private let pageCacheKiB = 2_048
private let mmapWindowBytes = 64 * 1_024 * 1_024

public enum StoreError: Error, Equatable {
  case cannotOpen(path: String, code: Int32, message: String)
  case query(sql: String, code: Int32, message: String)
  case malformedRow(table: String, detail: String)
  case missingBundledStore
  /// The connection was closed before the swap and this reader outlived it. It is a state, not
  /// a defect: `StoreHost` closes the old connection so `replaceItemAt` cannot leave a reader
  /// holding an fd to the OLD INODE — which would go on serving last week's data with no error
  /// to reveal it. A query against a closed handle says so instead.
  case closed
}

/// The `meta` table — what this store is and how far it reaches.
public struct StoreMetadata: Equatable, Sendable {
  public let schemaVersion: Int
  public let builtAt: String
  public let horizonStart: String
  public let horizonEnd: String
  public let goldValidAsOf: String
  public let contentHash: String

  /// Whether a Zurich day key is inside the published horizon. A date beyond it is an
  /// explicit state in the UI — "beyond the published horizon" — and is deliberately
  /// distinct from "closed", which would be a claim the data does not make.
  public func covers(day: String) -> Bool {
    horizonStart <= day && day <= horizonEnd
  }
}

// The detail sheet's reads. Named constants rather than literals at the call site: the
// column ORDER is what `facilityRow` decodes by index, so the two must be read together.
private let poolDetailSQL = """
  SELECT name, kind, address, description, phone, url, freshness, admission_state,
         prices_doc, source, curated, valid_as_of, last_admission_before_s,
         operating_season, baditicker_poiid
  FROM pool WHERE pool_id = ?;
  """

private let basinSQL = """
  SELECT basin_id, name, kind, length_m, width_m, lanes, nominal_temp_c,
         measured_temp_c, diving_platforms_m, physical_source, lane_plan_url
  FROM pool_basin WHERE pool_id = ? ORDER BY basin_id;
  """

private let lockerSQL = """
  SELECT ord, doc FROM pool_locker WHERE pool_id = ? ORDER BY ord;
  """

private let rentalSQL = """
  SELECT ord, doc FROM pool_rental WHERE pool_id = ? ORDER BY ord;
  """

private let featureSQL = """
  SELECT feature_key, doc FROM pool_feature WHERE pool_id = ? ORDER BY feature_key;
  """

public actor Store {
  private let handle: OpaquePointer
  private var poolCache: [String: PoolRecord]?
  /// Whether `close()` has already run. The refresh path closes deliberately; the deinit is
  /// the fallback for a store nobody closed.
  private var isClosed = false

  /// Opens the pre-resolved export at `path`, read-only and immutable.
  public init(path: URL) throws {
    self.handle = try Store.open(path: path)
  }

  /// `isolated deinit` (Swift 6.2) is required, not stylistic: an `OpaquePointer` is not
  /// `Sendable`, so a nonisolated deinit cannot touch the handle at all — the compiler says
  /// so. Isolating it keeps the close on the actor that owns the connection.
  isolated deinit {
    if !isClosed { sqlite3_close_v2(handle) }
  }

  /// Close the connection NOW, rather than whenever the last reference happens to go.
  ///
  /// This exists for one reason and it is not tidiness. `FileManager.replaceItemAt` exchanges
  /// the FILE; an open connection keeps its fd on the old inode and keeps answering from it,
  /// silently, forever. So the refresh closes every connection before the swap and opens a new
  /// one after it. Idempotent: a second call is a no-op, never a double free.
  public func close() {
    guard !isClosed else { return }
    isClosed = true
    sqlite3_close_v2(handle)
  }

  /// The store bundled with `SwimZHKit`. This is the offline floor: it is present on first
  /// launch, before any network has been reached, which is the whole premise of the app.
  public static func bundled() throws -> Store {
    guard let url = Bundle.module.url(forResource: "ios", withExtension: "sqlite") else {
      throw StoreError.missingBundledStore
    }
    return try Store(path: url)
  }

  // MARK: - Opening

  private static func open(path: URL) throws -> OpaquePointer {
    var candidate: OpaquePointer?
    let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_NOMUTEX | SQLITE_OPEN_URI
    let code = sqlite3_open_v2(uri(for: path), &candidate, flags, nil)
    guard code == SQLITE_OK, let handle = candidate else {
      // `sqlite3_open_v2` hands back a handle even when it fails, and that handle owns
      // resources: closing it here is what stops a failed open from leaking a connection.
      let message = candidate.map { String(cString: sqlite3_errmsg($0)) } ?? "cannot open"
      sqlite3_close_v2(candidate)
      throw StoreError.cannotOpen(path: path.path, code: code, message: message)
    }
    configure(handle)
    return handle
  }

  /// `file:<percent-encoded path>?immutable=1`.
  ///
  /// The encoding is not optional: an iOS container path carries a UUID and can carry
  /// spaces, and `?` / `#` in a path would otherwise be read as URI syntax. `immutable=1`
  /// is what makes the file safe to read from a read-only directory with no sidecars.
  static func uri(for path: URL) -> String {
    var allowed = CharacterSet.alphanumerics
    allowed.insert(charactersIn: "-._~/")
    let encoded = path.path.addingPercentEncoding(withAllowedCharacters: allowed) ?? path.path
    return "file:\(encoded)?immutable=1"
  }

  /// Connection pragmas. Deliberately explicit: inheriting Apple's 8 MB dirty page cache is
  /// the difference between a 30 MB and a 100 MB footprint on a list of 57 pools.
  private static func configure(_ handle: OpaquePointer) {
    // Failures here are not fatal — a store that will not take an mmap window still answers
    // correctly, just with more dirty pages. Correctness never depends on a pragma.
    sqlite3_exec(handle, "PRAGMA cache_size = -\(pageCacheKiB);", nil, nil, nil)
    sqlite3_exec(handle, "PRAGMA mmap_size = \(mmapWindowBytes);", nil, nil, nil)
  }

  // MARK: - The answer

  /// One day's answer for one person — the `QueryResult` shape.
  ///
  /// `day` supplies the Zurich calendar day (which rows to read, all of them already
  /// resolved in Python); `at` supplies only the wall-clock time of day, which is the one
  /// clock input the client is allowed to reason about (invariant E1).
  public func answer(
    on day: Date,
    at instant: Date,
    for person: Person,
    near: GeoPoint? = nil,
    radiusKm: Double? = nil
  ) throws -> Answer {
    try answer(
      onDay: ZurichClock.day(of: day),
      at: ZurichClock.timeOfDay(of: instant),
      for: person,
      near: near,
      radiusKm: radiusKm
    )
  }

  /// The same answer, addressed by the store's own key. The `Date` overload above is the
  /// app's entry point; this one is what the golden fixture replays, because the fixture
  /// states a `yyyy-MM-dd` and an `HH:MM` and converting them through a `Date` would put a
  /// calendar between the test and the thing under test.
  public func answer(
    onDay day: String,
    at time: TimeOfDay,
    for person: Person,
    near: GeoPoint? = nil,
    radiusKm: Double? = nil
  ) throws -> Answer {
    let pools = try poolsByID()
    let reach = Reach(near: near, radiusKm: radiusKm)
    return Answer(
      day: day,
      options: try options(
        on: day, at: time, for: person, pools: pools, reach: reach,
        lanes: try laneDays(on: day)),
      statuses: try statuses(on: day, pools: pools, reach: reach),
      notices: try notices(on: day),
      warnings: try warnings(on: day)
    )
  }

  public func metadata() throws -> StoreMetadata {
    var values: [String: String] = [:]
    try each(sql: "SELECT key, value FROM meta;") { row in
      values[row.text(0)] = row.text(1)
    }
    return StoreMetadata(
      schemaVersion: Int(values["schema_version"] ?? "") ?? 0,
      builtAt: values["built_at"] ?? "",
      horizonStart: values["horizon_start"] ?? "",
      horizonEnd: values["horizon_end"] ?? "",
      goldValidAsOf: values["gold_valid_as_of"] ?? "",
      contentHash: values["content_hash"] ?? ""
    )
  }

  /// `PRAGMA integrity_check`'s first answer — `"ok"` for a sound file.
  ///
  /// Run against a store this app DOWNLOADED, never against the bundled one: the bundle is
  /// signed and the export already checked it. A downloaded file arrived over somebody's
  /// network from somebody's CDN, and a store that fails this check would fail at some
  /// arbitrary later read instead — after the previous one had been replaced.
  public func integrityCheck() throws -> String {
    var answer = "no answer"
    try each(sql: "PRAGMA integrity_check;") { row in answer = row.text(0) }
    return answer
  }

  /// How many ROWS `sqlite_stat1` carries.
  ///
  /// Rows, not existence: `ANALYZE` always CREATES the table, even on an empty database, so
  /// its presence proves nothing at all (measured in S1). A populated one is what gives the
  /// device's first query a real plan.
  public func statisticsRowCount() throws -> Int {
    var present = false
    try each(sql: "SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_stat1';") { row in
      present = (row.intOrNil(0) ?? 0) == 1
    }
    guard present else { return 0 }
    var rows = 0
    try each(sql: "SELECT count(*) FROM sqlite_stat1;") { row in rows = row.intOrNil(0) ?? 0 }
    return rows
  }

  /// Every pool in the store, for the browser screen and for search.
  public func pools() throws -> [PoolRecord] {
    try poolsByID().values.sorted { $0.name < $1.name }
  }

  // MARK: - Row readers

  private func poolsByID() throws -> [String: PoolRecord] {
    if let cached = poolCache { return cached }
    var pools: [String: PoolRecord] = [:]
    try each(
      sql: """
        SELECT pool_id, name, kind, address, lat, lon, url, freshness,
               admission_state, prices_doc
        FROM pool;
        """
    ) { row in
      let admission = try Store.admission(state: row.text(8), doc: row.textOrNil(9))
      pools[row.text(0)] = PoolRecord(
        id: row.text(0),
        name: row.text(1),
        kind: row.text(2),
        address: row.textOrNil(3),
        geo: row.geo(latColumn: 4, lonColumn: 5),
        url: row.textOrNil(6),
        freshness: row.text(7),
        admission: admission
      )
    }
    poolCache = pools
    return pools
  }

  private static func admission(state: String, doc: String?) throws -> Admission {
    switch state {
    case "free": return .free
    case "unknown": return .unknown
    case "tariff":
      guard let doc, let prices = PriceDoc.decode(json: doc) else {
        throw StoreError.malformedRow(table: "pool", detail: "unreadable prices_doc")
      }
      return .tariff(prices)
    default:
      throw StoreError.malformedRow(table: "pool", detail: "admission_state=\(state)")
    }
  }

  /// The `lane_day` rows for this day's WEEKDAY, keyed by basin.
  ///
  /// One read per answer rather than one per option: a Belegungsplan is a weekly plan, so the
  /// whole city's parsed lane data for a weekday is six rows. Mapping the date to a weekday is
  /// calendar ARITHMETIC, not a date rule (invariant E1) — it asks which key to read, never
  /// whether the day is a school holiday.
  private func laneDays(on day: String) throws -> [String: LaneDay] {
    guard let weekday = ZurichClock.weekday(of: day) else { return [:] }
    var days: [String: LaneDay] = [:]
    try each(
      sql: """
        SELECT basin_id, lane_count, strips, unresolved_lanes, confidence
        FROM lane_day WHERE weekday = ?;
        """,
      bind: [String(weekday)]
    ) { row in
      // A malformed plan is DROPPED, not defaulted: `LaneDay.decode` returns nil rather than
      // an empty plan, and an option with no lane data renders as "split not published" —
      // which is true — where an empty plan would render as "no lanes free", which is not.
      guard
        let decoded = LaneDay.decode(
          basinID: row.text(0),
          weekday: weekday,
          laneCount: row.intOrNil(1) ?? 0,
          strips: row.text(2),
          unresolvedLanes: row.text(3),
          confidence: row.text(4)
        )
      else { return }
      days[decoded.basinID] = decoded
    }
    return days
  }

  private func options(
    on day: String,
    at time: TimeOfDay,
    for person: Person,
    pools: [String: PoolRecord],
    reach: Reach,
    lanes: [String: LaneDay]
  ) throws -> [SwimOption] {
    var options: [SwimOption] = []
    try each(
      sql: """
        SELECT pool_id, basin_id, basin_name, length_m, lanes, start, end,
               access_kind, access_params, weather
        FROM session WHERE date = ?;
        """,
      bind: [day]
    ) { row in
      guard let pool = pools[row.text(0)] else {
        throw StoreError.malformedRow(table: "session", detail: "unknown pool \(row.text(0))")
      }
      guard let distance = reach.distance(to: pool.geo) else { return }
      guard let start = TimeOfDay(hhmm: row.text(5)), let end = TimeOfDay(hhmm: row.text(6)) else {
        throw StoreError.malformedRow(
          table: "session", detail: "time \(row.text(5))-\(row.text(6))")
      }
      let window = TimeWindow(start: start, end: end)
      let access = SessionAccess.decode(
        kind: row.text(7),
        params: AccessParams.decode(json: row.text(8))
      )
      let lane = lanes[row.text(1)]
      options.append(
        SwimOption(
          poolID: pool.id,
          poolName: pool.name,
          poolKind: pool.kind,
          basinID: row.text(1),
          basinName: row.text(2),
          lengthM: row.doubleOrNil(3),
          lanes: row.intOrNil(4),
          window: window,
          access: access,
          weather: row.text(9),
          eligibility: eligibility(person, access),
          openAtQueryTime: openAtQueryTime(window, at: time),
          price: priceFor(pool.admission, person),
          distanceKm: distance,
          // The lane quartet, derived here rather than baked: all four depend on the CLOCK
          // (`availability(at:)`) or on this session's own hours (the timeline and the
          // best-public window are both bounded by `window`), and E1 puts clock questions on
          // the client. `best_public` is bounded by the SESSION deliberately: "come at 09:00"
          // is not an answer for a row whose hours end at 08:00.
          laneAvailability: lane?.availability(at: time),
          laneTimeline: lane?.availabilityTimeline(within: window),
          laneDayView: lane,
          laneBestPublic: lane?.bestPublicTime(within: window)
        )
      )
    }
    return options.sorted(by: SwimOption.canonicalOrder)
  }

  private func statuses(
    on day: String,
    pools: [String: PoolRecord],
    reach: Reach
  ) throws -> [PoolDayStatus] {
    var statuses: [PoolDayStatus] = []
    try each(
      sql: """
        SELECT pool_id, status, detail_code, closure_code, detail_params
        FROM day WHERE date = ?;
        """,
      bind: [day]
    ) { row in
      guard let pool = pools[row.text(0)] else {
        throw StoreError.malformedRow(table: "day", detail: "unknown pool \(row.text(0))")
      }
      guard let distance = reach.distance(to: pool.geo) else { return }
      statuses.append(
        PoolDayStatus(
          poolID: pool.id,
          poolName: pool.name,
          poolKind: pool.kind,
          status: row.text(1),
          detailCode: row.text(2),
          closureCode: row.textOrNil(3),
          detailParams: Store.stringMap(json: row.text(4)),
          distanceKm: distance
        )
      )
    }
    return statuses.sorted { $0.poolID < $1.poolID }
  }

  private func notices(on day: String) throws -> [DayNotice] {
    var notices: [DayNotice] = []
    try each(sql: "SELECT pool_id, text FROM day_notice WHERE date = ?;", bind: [day]) { row in
      notices.append(DayNotice(poolID: row.text(0), text: row.text(1)))
    }
    return notices.sorted { ($0.poolID, $0.text) < ($1.poolID, $1.text) }
  }

  private func warnings(on day: String) throws -> [DayWarning] {
    var warnings: [DayWarning] = []
    try each(sql: "SELECT code, params FROM day_warning WHERE date = ?;", bind: [day]) { row in
      warnings.append(DayWarning(code: row.text(0), params: Store.stringMap(json: row.text(1))))
    }
    return warnings.sorted { $0.code < $1.code }
  }

  /// The export writes every `detail_params` / warning `params` value as a JSON string, so
  /// this decodes exactly that and nothing wider.
  private static func stringMap(json: String) -> [String: String] {
    guard let data = json.data(using: .utf8),
      let decoded = try? JSONDecoder().decode([String: String].self, from: data)
    else { return [:] }
    return decoded
  }

  // MARK: - The facility sheet

  /// Everything the detail sheet shows about one pool, on one date.
  ///
  /// SIX reads, one pool. That is deliberate at this size: the sheet is opened one pool at a
  /// time and off the scrolling path, so the cost is a keystroke's worth of work once, where
  /// caching it would mean holding a second copy of the store's largest documents beside the
  /// list model the memory budget is already half spent on.
  ///
  /// Returns nil for a pool the store does not have — a store the app did not write can be
  /// missing one (S5 downloads them), and an empty sheet is a better answer than a fabricated
  /// pool.
  public func facility(poolID: String, on day: String) throws -> FacilityDetail? {
    guard let row = try facilityRow(poolID: poolID) else { return nil }
    let basins = try basinRows(poolID: poolID)
    let lanes = try laneDays(on: day)
    return FacilityDetail(
      poolID: poolID,
      name: row.name,
      kind: row.kind,
      address: row.address,
      description: row.description,
      phone: row.phone,
      url: row.url,
      freshness: row.freshness,
      admission: row.admission,
      basins: basins,
      lockers: try documents(table: lockerSQL, bind: poolID).compactMap(LockerDetail.decode),
      rentals: try documents(table: rentalSQL, bind: poolID).compactMap(RentalDetail.decode),
      features: try featureRows(poolID: poolID),
      operatingSeason: row.operatingSeason,
      lastAdmissionBeforeSeconds: row.lastAdmissionBeforeSeconds,
      provenance: row.provenance,
      baditickerPOIID: row.baditickerPOIID,
      // Only the basins that actually carry a parsed Belegungsplan. A basin with no plan gets
      // no panel at all rather than an empty one: an empty panel reads as "no lane is
      // reserved", which is a claim, where absence is the honest state.
      lanePanels: basins.compactMap { basin in
        lanes[basin.basinID].map {
          LanePanel(basinID: basin.basinID, basinName: basin.name, day: $0)
        }
      }
    )
  }

  /// The `pool` row's own facts, including the four columns the list never reads.
  private func facilityRow(poolID: String) throws -> FacilityRow? {
    var found: FacilityRow?
    var failure: Error?
    try each(sql: poolDetailSQL, bind: [poolID]) { row in
      do {
        found = FacilityRow(
          name: row.text(0),
          kind: row.text(1),
          address: row.textOrNil(2),
          description: row.textOrNil(3),
          phone: row.textOrNil(4),
          url: row.textOrNil(5),
          freshness: row.text(6),
          admission: try Store.admission(state: row.text(7), doc: row.textOrNil(8)),
          provenance: Provenance(
            source: row.textOrNil(9),
            curated: (row.intOrNil(10) ?? 0) != 0,
            validAsOf: row.textOrNil(11)
          ),
          lastAdmissionBeforeSeconds: row.intOrNil(12),
          operatingSeason: row.textOrNil(13).flatMap(OperatingSeason.decode(json:)),
          baditickerPOIID: row.textOrNil(14)
        )
      } catch {
        failure = error
      }
    }
    if let failure { throw failure }
    return found
  }

  private func basinRows(poolID: String) throws -> [BasinDetail] {
    var basins: [BasinDetail] = []
    try each(sql: basinSQL, bind: [poolID]) { row in
      basins.append(
        BasinDetail(
          basinID: row.text(0),
          name: row.text(1),
          kind: row.text(2),
          lengthM: row.doubleOrNil(3),
          widthM: row.doubleOrNil(4),
          lanes: row.intOrNil(5),
          nominalTempC: row.doubleOrNil(6),
          measuredTempC: row.doubleOrNil(7),
          divingPlatformsM: decodeDoc(row.text(8)) ?? [],
          physicalSource: row.text(9),
          lanePlanURL: row.textOrNil(10)
        ))
    }
    return basins
  }

  private func featureRows(poolID: String) throws -> [FeatureDetail] {
    var features: [FeatureDetail] = []
    try each(sql: featureSQL, bind: [poolID]) { row in
      guard let feature = FeatureDetail.decode(key: row.text(0), json: row.text(1)) else { return }
      features.append(feature)
    }
    return features
  }

  /// The `(ordinal, doc)` pairs of a document table — the shape lockers and rentals share.
  private func documents(table sql: String, bind poolID: String) throws -> [(Int, String)] {
    var documents: [(Int, String)] = []
    try each(sql: sql, bind: [poolID]) { row in
      documents.append((row.intOrNil(0) ?? 0, row.text(1)))
    }
    return documents
  }

  // MARK: - The one place a statement exists

  /// Prepares `sql`, binds `bind` as TEXT, steps it, and hands each row to `body`.
  ///
  /// This is the only function in the package that touches a `sqlite3_stmt`, and the
  /// statement is finalized on every path including a thrown error. `body` is
  /// non-escaping, so the `SQLiteRow` it receives — and the pointer inside it — cannot
  /// outlive the step that produced it.
  private func each(
    sql: String,
    bind: [String] = [],
    body: (SQLiteRow) throws -> Void
  ) throws {
    guard !isClosed else { throw StoreError.closed }
    var statement: OpaquePointer?
    let prepared = sqlite3_prepare_v2(handle, sql, -1, &statement, nil)
    guard prepared == SQLITE_OK, let statement else {
      let message = String(cString: sqlite3_errmsg(handle))
      sqlite3_finalize(statement)
      throw StoreError.query(sql: sql, code: prepared, message: message)
    }
    defer { sqlite3_finalize(statement) }
    for (offset, value) in bind.enumerated() {
      // SQLITE_TRANSIENT, always: `value`'s C buffer is only valid for the duration of this
      // call, so SQLITE_STATIC would hand SQLite a pointer that is dangling by `step`.
      let bound = sqlite3_bind_text(statement, Int32(offset + 1), value, -1, sqliteTransient)
      guard bound == SQLITE_OK else {
        throw StoreError.query(sql: sql, code: bound, message: "bind \(offset + 1)")
      }
    }
    while true {
      let step = sqlite3_step(statement)
      if step == SQLITE_DONE { return }
      guard step == SQLITE_ROW else {
        throw StoreError.query(
          sql: sql, code: step, message: String(cString: sqlite3_errmsg(handle)))
      }
      try body(SQLiteRow(statement: statement))
    }
  }
}

/// The `pool` row behind the detail sheet, decoded once so `facility` reads as prose.
private struct FacilityRow {
  let name: String
  let kind: String
  let address: String?
  let description: String?
  let phone: String?
  let url: String?
  let freshness: String
  let admission: Admission
  let provenance: Provenance
  let lastAdmissionBeforeSeconds: Int?
  let operatingSeason: OperatingSeason?
  let baditickerPOIID: String?
}

extension LockerDetail {
  static func decode(_ pair: (ordinal: Int, doc: String)) -> LockerDetail? {
    decode(ordinal: pair.ordinal, json: pair.doc)
  }
}

extension RentalDetail {
  static func decode(_ pair: (ordinal: Int, doc: String)) -> RentalDetail? {
    decode(ordinal: pair.ordinal, json: pair.doc)
  }
}

/// A pool's date-independent facts. `prices_doc` is already parsed: the tariff is read once
/// per store, not once per session row.
public struct PoolRecord: Equatable, Sendable, Identifiable {
  public let id: String
  public let name: String
  public let kind: String
  public let address: String?
  public let geo: GeoPoint?
  public let url: String?
  public let freshness: String
  public let admission: Admission
}

extension SwimOption {
  /// A total, id-based order, so an answer is reproducible and the golden comparison is
  /// about content rather than about SQLite's row order. Display order is the view's job.
  static func canonicalOrder(_ lhs: SwimOption, _ rhs: SwimOption) -> Bool {
    let left = (
      lhs.poolID, lhs.basinID, lhs.window.start.hhmm, lhs.window.end.hhmm, lhs.access.kind
    )
    let right = (
      rhs.poolID, rhs.basinID, rhs.window.start.hhmm, rhs.window.end.hhmm, rhs.access.kind
    )
    return left < right
  }
}

/// The radius filter, as one value so the "no filter" case cannot be forgotten at a call
/// site: with no origin every pool is in reach and its distance is unknown (nil), which is
/// not the same as zero.
private struct Reach {
  let near: GeoPoint?
  let radiusKm: Double?

  /// `.some(distance)` when the pool is in reach (distance nil if there is no origin),
  /// `nil` when it is filtered out.
  func distance(to geo: GeoPoint?) -> Double?? {
    guard let near else { return .some(nil) }
    guard let geo else { return radiusKm == nil ? .some(nil) : nil }
    let km = haversineKm(near, geo)
    if let radiusKm, km > radiusKm { return nil }
    return .some(km)
  }
}

/// One stepped row. A struct over the borrowed statement — it never escapes `Store.each`.
private struct SQLiteRow {
  let statement: OpaquePointer

  func text(_ column: Int32) -> String {
    guard let bytes = sqlite3_column_text(statement, column) else { return "" }
    return String(cString: bytes)
  }

  func textOrNil(_ column: Int32) -> String? {
    sqlite3_column_type(statement, column) == SQLITE_NULL ? nil : text(column)
  }

  func doubleOrNil(_ column: Int32) -> Double? {
    sqlite3_column_type(statement, column) == SQLITE_NULL
      ? nil : sqlite3_column_double(statement, column)
  }

  func intOrNil(_ column: Int32) -> Int? {
    sqlite3_column_type(statement, column) == SQLITE_NULL
      ? nil : Int(sqlite3_column_int64(statement, column))
  }

  /// A pool has coordinates or it has none; a half-populated pair is treated as none rather
  /// than as a point on the equator.
  func geo(latColumn: Int32, lonColumn: Int32) -> GeoPoint? {
    guard let lat = doubleOrNil(latColumn), let lon = doubleOrNil(lonColumn) else { return nil }
    return GeoPoint(lat: lat, lon: lon)
  }
}
