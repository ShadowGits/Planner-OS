import Foundation
#if canImport(UserNotifications)
import UserNotifications
#endif

/// What Planner OS says when it reminds you, and when it keeps on reminding.
///
/// Blunt on purpose: asked for. Ten minutes before a task, then — until it is
/// ticked — at its start, fifteen minutes in, and when it should have ended.
/// Each morning, how much is overdue and the worst of it; each evening, what
/// was planned against what was ticked. The same words on the iPhone, Android
/// and the server (planner_core/services.py, ReminderPolicy.kt); change one,
/// change all three.
///
/// Calendar events get the ten-minute warning only: an appointment happens at
/// its time whether or not anyone ticks it, so nagging about it is noise.
enum HarshReminders {
    static let leadMinutes = 10
    static let lateMinutes = 15
    /// A task this short has ended before "fifteen minutes in" would land.
    static let lateNeedsMinutes = 20
    /// The morning callout, as the first thing after waking.
    static let morningMinute = 11 * 60
    /// The evening report, once the noon-to-nine working stretch is over.
    static let eveningMinute = 21 * 60 + 30

    /// "09:30" for any minute of the planner's day, 25:30 included.
    static func clock(_ minutes: Int) -> String {
        let wrapped = ((minutes % 1440) + 1440) % 1440
        return String(format: "%02d:%02d", wrapped / 60, wrapped % 60)
    }

    static func leadBody(start: Int, minutes: Int) -> String {
        "In \(leadMinutes) min · \(clock(start)) · \(minutes) min. Wrap up what you're doing."
    }

    enum Nag: String, CaseIterable { case start, late, end }

    /// The follow-ups a task gets until it is ticked, as minutes after its
    /// start. A short task skips "late", which would land after it ended.
    static func nags(minutes: Int) -> [(Nag, Int)] {
        var list: [(Nag, Int)] = [(.start, 0)]
        if minutes > lateNeedsMinutes { list.append((.late, lateMinutes)) }
        list.append((.end, max(minutes, 1)))
        return list
    }

    static func nagText(_ nag: Nag, title: String, start: Int, minutes: Int) -> (title: String, body: String) {
        switch nag {
        case .start:
            return ("Now: \(title)", "It's \(clock(start)). You planned this. Start it.")
        case .late:
            return ("\(lateMinutes) min late: \(title)", "Still not ticked. Start it now or move it. Don't let it slide.")
        case .end:
            return ("Not done: \(title)",
                    "This should have been finished by \(clock(start + max(minutes, 1))). Tick it, or admit you skipped it.")
        }
    }

    /// "3 days", "1 week", "3 weeks".
    static func lateWords(days: Int) -> String {
        if days >= 14 { return "\(days / 7) weeks" }
        if days >= 7 { return "1 week" }
        return days == 1 ? "1 day" : "\(days) days"
    }

    /// The morning callout: what is overdue and the worst of it, then today.
    static func morning(overdue: Int, worst: (title: String, daysLate: Int)?, planned: Int,
                        first: (title: String, start: Int)?) -> (title: String, body: String)? {
        guard overdue > 0 || planned > 0 else { return nil }
        var lines: [String] = []
        if overdue > 0 {
            var line = "\(overdue) overdue."
            if let worst, worst.daysLate > 0 { line += " Worst: \(worst.title), \(lateWords(days: worst.daysLate)) late." }
            lines.append(line)
        } else {
            lines.append("Nothing overdue.")
        }
        if planned > 0 {
            var line = "Today: \(planned) planned."
            if let first { line += " First up: \(first.title) at \(clock(first.start))." }
            lines.append(line)
        } else {
            lines.append("Nothing planned today. Plan it, or it will not happen.")
        }
        return (overdue > 0 ? "Overdue check" : "Today", lines.joined(separator: " "))
    }

    /// One thing on the day, as the evening report reads it.
    struct ReportItem: Codable, Equatable {
        var id: String
        var title: String
        /// Minutes after midnight, past 1440 after midnight; nil when untimed.
        var start: Int?
        var done: Bool
    }

    /// The evening report: what was planned up to now against what was
    /// ticked, naming what was skipped. Anything still to come tonight is
    /// counted apart rather than called skipped.
    static func evening(_ items: [ReportItem], at minute: Int) -> (title: String, body: String)? {
        let due = items.filter { ($0.start ?? -1) < minute }
        let later = items.filter { !$0.done && ($0.start ?? -1) >= minute }
        guard !due.isEmpty else { return nil }
        let done = due.filter(\.done).count
        var body: String
        if done == due.count {
            body = "All \(due.count) done today. That is how it's done."
        } else {
            let skipped = due.filter { !$0.done }.sorted { ($0.start ?? 99_999, $0.title) < ($1.start ?? 99_999, $1.title) }
            var names = skipped.prefix(4).map(\.title).joined(separator: ", ")
            if skipped.count > 4 { names += ", +\(skipped.count - 4) more" }
            body = "You did \(done) of \(due.count) today. Skipped: \(names)."
        }
        if !later.isEmpty { body += " Still to come tonight: \(later.count)." }
        return ("Today's report", body)
    }

    /// A wall-clock minute on a day, as a moment — here rather than borrowed
    /// from the app, because the widget compiles this file too.
    static func moment(_ day: String, _ minute: Int, in zone: TimeZone) -> Date? {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        guard let midnight = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])) else { return nil }
        return calendar.date(byAdding: .minute, value: minute, to: midnight)
    }

    // MARK: - The day's list, kept for the evening report

    private static let reportFile = "report.json"

    struct Report: Codable, Equatable {
        var date: String
        var items: [ReportItem]
    }

    /// The app writes the whole day here — untimed tasks too, which the
    /// widget's copy leaves out — so a tick on the widget or through Siri can
    /// redo tonight's report without waiting for the app.
    static func saveReport(_ report: Report) {
        guard let folder = PlannerSnapshot.folder, let data = try? JSONEncoder().encode(report) else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? data.write(to: folder.appendingPathComponent(reportFile), options: .atomic)
    }

    static func loadReport() -> Report? {
        guard let folder = PlannerSnapshot.folder,
              let data = try? Data(contentsOf: folder.appendingPathComponent(reportFile)) else { return nil }
        return try? JSONDecoder().decode(Report.self, from: data)
    }

    @discardableResult
    static func markReport(_ id: String, done: Bool) -> Report? {
        guard var report = loadReport(), let index = report.items.firstIndex(where: { $0.id == id }) else { return nil }
        report.items[index].done = done
        saveReport(report)
        return report
    }

    // MARK: - Delivery

    /// Pending-notification ids. Everything for one task shares a prefix, so
    /// ticking it can take back every nag still to come in one go.
    static func taskPrefix(_ taskId: String) -> String { "task-\(taskId)-" }
    static let eveningId = "daily-evening"
    static let morningId = "daily-morning"

    #if canImport(UserNotifications)
    /// A tick, wherever it was made: no more nags about that task, and
    /// tonight's report no longer calls it skipped.
    static func ticked(_ taskId: String, done: Bool, timeZone: TimeZone = .current) async {
        let center = UNUserNotificationCenter.current()
        if done {
            let prefix = taskPrefix(taskId)
            let ids = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(prefix) }
            center.removePendingNotificationRequests(withIdentifiers: ids)
        }
        if let report = markReport(taskId, done: done) {
            await scheduleEvening(report, timeZone: timeZone)
        }
    }

    /// Tonight's report, or none once tonight's has gone.
    static func scheduleEvening(_ report: Report, timeZone: TimeZone, now: Date = Date()) async {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [eveningId])
        guard let text = evening(report.items, at: eveningMinute),
              let fire = moment(report.date, eveningMinute, in: timeZone), fire > now else { return }
        try? await center.add(request(eveningId, text, at: fire, timeZone: timeZone))
    }

    static func request(_ id: String, _ text: (title: String, body: String), at fire: Date,
                        timeZone: TimeZone) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = text.title
        content.body = text.body
        content.sound = Bundle.main.url(forResource: "task_reminder", withExtension: "wav") == nil
            ? .default : UNNotificationSound(named: UNNotificationSoundName("task_reminder.wav"))
        content.threadIdentifier = "planner-tasks"
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        var when = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: fire)
        when.timeZone = timeZone
        return UNNotificationRequest(identifier: id, content: content,
                                     trigger: UNCalendarNotificationTrigger(dateMatching: when, repeats: false))
    }
    #endif
}
