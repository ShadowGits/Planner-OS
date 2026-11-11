import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Ticks made on the widget that the server has not heard about yet.
///
/// A widget only redraws once its button's action has finished. When that
/// action waited for the server, the circle sat empty for as long as the
/// request took — seconds, on a server that had gone to sleep. So the action
/// no longer waits: it changes the widget's own copy, writes the tick down
/// here, and finishes at once. The tick is then sent from wherever gets the
/// chance first — the widget straight afterwards, its next redraw, or the app
/// the next time it reads the server — and is crossed off this list only when
/// the server has taken it.
///
/// If the server refuses a tick outright (the task was deleted elsewhere) it
/// is taken back on the widget. If the server simply cannot be reached, the
/// tick stays here and is tried again; the widget keeps showing it.
enum PendingTicks {
    struct Tick: Codable, Equatable {
        var id: String
        var done: Bool
        var at: Date
    }

    private static let file = "pending-ticks.json"
    /// A tick nobody managed to deliver in a day is not going to be.
    private static let lifetime: TimeInterval = 24 * 3600

    private static var location: URL? { PlannerSnapshot.folder?.appendingPathComponent(file) }

    static func all(now: Date = Date()) -> [Tick] {
        guard let location, let data = try? Data(contentsOf: location),
              let ticks = try? JSONDecoder().decode([Tick].self, from: data) else { return [] }
        return ticks.filter { now.timeIntervalSince($0.at) < lifetime }
    }

    private static func write(_ ticks: [Tick]) {
        guard let location, let folder = PlannerSnapshot.folder else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        guard let data = try? JSONEncoder().encode(ticks) else { return }
        try? data.write(to: location, options: .atomic)
    }

    /// Note a tick to be sent. The latest tap on a task replaces any earlier
    /// one, so ticking and unticking quickly sends only where it ended up.
    static func add(_ id: String, done: Bool, now: Date = Date()) {
        write(all(now: now).filter { $0.id != id } + [Tick(id: id, done: done, at: now)])
    }

    /// Cross a tick off, but only if it is still the one that was sent: a
    /// newer tap made while the request was out must not be lost.
    static func remove(_ tick: Tick) {
        write(all().filter { !($0.id == tick.id && $0.done == tick.done) })
    }

    static func clear() { write([]) }

    /// What a task's tick should read as, given taps not yet delivered. The
    /// app uses this when it rewrites the widget's copy, so a fresh read from
    /// the server cannot undo a tick the server has not been told about.
    static func overlay(_ id: String, done: Bool, pending: [Tick]) -> Bool {
        pending.last { $0.id == id }?.done ?? done
    }

    /// Send every waiting tick. Returns true when one was refused and taken
    /// back, so the caller knows the widget needs drawing again.
    @discardableResult
    static func flush() async -> Bool {
        var takenBack = false
        for tick in all() {
            do {
                try await PlannerWidgetAPI.setDone(tick.id, tick.done)
                remove(tick)
            } catch is PlannerWidgetAPI.Failure {
                // The server answered and said no. Waiting will not change it.
                remove(tick)
                PlannerSnapshot.mark(tick.id, done: !tick.done)
                takenBack = true
            } catch {
                // No answer at all: keep it, and try again next time.
            }
        }
        return takenBack
    }
}
