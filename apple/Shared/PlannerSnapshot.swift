import Foundation

/// What the home-screen widget shows.
///
/// A widget is a separate program with its own sandbox: it cannot read the
/// app's files, its settings or its keychain. The two share one folder, the
/// App Group, and nothing else. So the app writes the day here after every
/// sync and the widget only reads — no server address, no app key and no
/// network in the widget, which also means it draws instantly and still says
/// something sensible on a train with no signal.
///
/// Both targets compile this file. Changing it changes both.
struct PlannerSnapshot: Codable, Equatable {
    /// The day these tasks belong to, yyyy-MM-dd.
    var date: String
    /// When the app last wrote this, so the widget can admit to being stale.
    var updated: Date
    var tasks: [Item]
    /// Overdue and unscheduled work waiting in the Inbox.
    var waiting: Int

    struct Item: Codable, Equatable, Identifiable {
        var id: String
        var title: String
        /// Minutes after midnight; a task after midnight carries on past 1440.
        var start: Int
        var minutes: Int
        var done: Bool
        /// The task's colour slot, so the widget matches the timeline.
        var palette: Int

        var end: Int { start + max(minutes, 1) }
    }

    static let group = "group.dev.planneros.planner"
    private static let file = "today.json"

    /// The shared folder, or nil when the App Group is not signed into the
    /// build — the app still works, the widget simply has nothing to show.
    /// Only Apple's Foundation has App Groups; on Linux, where the planner's
    /// rules are tested, this stands in with a temporary folder so the logic
    /// below can still be exercised.
    static var folder: URL? {
        #if canImport(Darwin)
        return FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group)
        #else
        return FileManager.default.temporaryDirectory.appendingPathComponent(group, isDirectory: true)
        #endif
    }

    static func save(_ snapshot: PlannerSnapshot) {
        guard let folder else { return }
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        // The App Group's own folder is always there; its stand-in may not be.
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? data.write(to: folder.appendingPathComponent(file), options: .atomic)
    }

    static func load() -> PlannerSnapshot? {
        guard let folder,
              let data = try? Data(contentsOf: folder.appendingPathComponent(file)) else { return nil }
        return try? JSONDecoder().decode(PlannerSnapshot.self, from: data)
    }

    /// Tick a task off, or put it back, in the copy the widget is showing, so
    /// the widget redraws immediately instead of waiting for the server and
    /// then for the app's next sync. Returns false when the task has gone.
    @discardableResult
    static func mark(_ id: String, done: Bool) -> Bool {
        guard var snapshot = load(), let index = snapshot.tasks.firstIndex(where: { $0.id == id }) else { return false }
        snapshot.tasks[index].done = done
        save(snapshot)
        return true
    }

    /// The task under way at `minute`, if any.
    func current(at minute: Int) -> Item? {
        tasks.first { !$0.done && minute >= $0.start && minute < $0.end }
    }

    /// What is coming, soonest first, skipping anything finished or passed.
    func upcoming(after minute: Int) -> [Item] {
        tasks.filter { !$0.done && $0.start >= minute }.sorted { $0.start < $1.start }
    }

    /// Everything still to do today, for the "3 left" line.
    var remaining: Int { tasks.filter { !$0.done }.count }

    /// The moments the widget's wording changes: each start and each end. The
    /// widget asks to be redrawn at these rather than on a timer, so "now" is
    /// right without waking it every few minutes.
    func turningPoints(from minute: Int) -> [Int] {
        Set(tasks.flatMap { [$0.start, $0.end] })
            .filter { $0 > minute }
            .sorted()
    }
}
