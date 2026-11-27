import CryptoKit
import EventKit
import Foundation

/// Mirrors only URL-tagged ASAP reminders; unrelated list entries are untouched.
@MainActor
final class AppleASAPReminders {
    static let shared = AppleASAPReminders()
    static let listName = "TODOs One time"
    private let events = EKEventStore()
    private let enabledKey = "apple_asap_connected"
    var authorized: Bool { EKEventStore.authorizationStatus(for: .reminder) == .fullAccess }

    func connect() async throws {
        guard try await events.requestFullAccessToReminders() else {
            throw PlannerError(message: "Allow Reminders access to connect the ASAP list.")
        }
        _ = try list()
        UserDefaults.standard.set(true, forKey: enabledKey)
    }

    private func list() throws -> EKCalendar {
        let matches = events.calendars(for: .reminder).filter { $0.title == Self.listName }
        guard matches.count <= 1 else { throw PlannerError(message: "More than one Reminders list has this name. Rename one before connecting.") }
        if let found = matches.first {
            guard found.allowsContentModifications else { throw PlannerError(message: "The Reminders list is read-only.") }
            return found
        }
        throw PlannerError(message: "The TODOs One time list is not available. Make it visible in Apple Reminders, then connect it here.")
    }

    /// Returns Planner task IDs completed in Reminders. Completion wins when
    /// both apps changed before synchronization; titles are owned by Planner.
    func reconcile(_ open: [PlannerTask], connection: Connection) async throws -> [String] {
        guard UserDefaults.standard.bool(forKey: enabledKey), authorized else { return [] }
        let calendar = try list()
        let predicate = events.predicateForReminders(in: [calendar])
        let rows: [EKReminder] = try await withCheckedThrowingContinuation { continuation in
            events.fetchReminders(matching: predicate) { reminders in
                guard let reminders else {
                    continuation.resume(throwing: PlannerError(message: "Could not read the Reminders list. Existing entries were kept.")); return
                }
                continuation.resume(returning: reminders)
            }
        }
        let scope = SHA256.hash(data: Data((connection.base.absoluteString + "|" + connection.key).utf8)).map { String(format: "%02x", $0) }.joined()
        let prefix = "planneros://asap/" + scope + "/"
        let stateKey = "apple_asap_seen_" + scope
        let previousOpen = Set(UserDefaults.standard.stringArray(forKey: stateKey) ?? [])
        let byID = Dictionary(grouping: rows.filter { $0.url?.absoluteString.hasPrefix(prefix) == true }) {
            String($0.url!.absoluteString.dropFirst(prefix.count))
        }
        let openIDs = Set(open.map(\.id))
        let changes = asapCompletionChanges(open: openIDs, reminders: byID.mapValues { $0.contains(where: { $0.isCompleted }) }, previouslyOpen: previousOpen)
        var closed: [String] = []
        for task in open {
            if let existing = byID[task.id]?.first {
                if changes.planner.contains(task.id) { closed.append(task.id); continue }
                if existing.title != task.title { existing.title = task.title; try events.save(existing, commit: true) }
            } else {
                let reminder = EKReminder(eventStore: events)
                reminder.calendar = calendar; reminder.title = task.title; reminder.priority = 1
                reminder.url = URL(string: prefix + task.id)
                try events.save(reminder, commit: true)
            }
        }
        for (id, reminders) in byID where changes.apple.contains(id) {
            for reminder in reminders where !reminder.isCompleted {
                reminder.isCompleted = true
                try events.save(reminder, commit: true)
            }
        }
        UserDefaults.standard.set(Array(openIDs), forKey: stateKey)
        return closed
    }
}
