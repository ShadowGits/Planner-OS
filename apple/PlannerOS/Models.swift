import Foundation

/// A task as the planner API sends it (`/v2/day`, `/v2/day/inbox`, `/v2/week`).
struct PlannerTask: Identifiable, Hashable, Decodable {
    var id: String
    var title: String
    /// "HH:mm" in the workspace timezone; the API's seconds are dropped.
    var time: String?
    var minutes: Int
    var done: Bool
    var starred: Bool
    var habit: Bool
    var parent: String?
    /// The day it is planned for, yyyy-MM-dd.
    var date: String?
    var notes: String?
    var projectId: String?
    var dueDate: String?
    var milestoneId: String?
    var priority: String?

    init(id: String, title: String, time: String? = nil, minutes: Int = 30, done: Bool = false, starred: Bool = false,
         habit: Bool = false, parent: String? = nil, date: String? = nil, notes: String? = nil, projectId: String? = nil,
         dueDate: String? = nil, milestoneId: String? = nil, priority: String? = "medium") {
        self.id = id; self.title = title; self.time = time.map { String($0.prefix(5)) }; self.minutes = max(1, minutes)
        self.done = done; self.starred = starred; self.habit = habit; self.parent = parent; self.date = date
        self.notes = notes; self.projectId = projectId; self.dueDate = dueDate; self.milestoneId = milestoneId
        self.priority = priority
    }

    enum CodingKeys: String, CodingKey {
        case id, title, done, starred, notes, priority, status
        case time = "start_time", minutes = "estimated_minutes", habit = "is_habit", parent = "parent_task_id"
        case date = "scheduled_date", projectId = "project_id", dueDate = "due_date", milestoneId = "milestone_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let status = c.text(.status)
        self.init(
            id: try c.decode(String.self, forKey: .id),
            title: c.text(.title) ?? "",
            time: c.text(.time),
            minutes: (try? c.decodeIfPresent(Int.self, forKey: .minutes)) ?? 30,
            done: (try? c.decodeIfPresent(Bool.self, forKey: .done)) ?? ["done", "completed", "skipped"].contains(status ?? ""),
            starred: (try? c.decodeIfPresent(Bool.self, forKey: .starred)) ?? false,
            habit: (try? c.decodeIfPresent(Bool.self, forKey: .habit)) ?? false,
            parent: c.text(.parent),
            date: c.text(.date),
            notes: c.text(.notes),
            projectId: c.text(.projectId),
            dueDate: c.text(.dueDate),
            milestoneId: c.text(.milestoneId),
            priority: c.text(.priority)
        )
    }

    /// Minutes after midnight, or Int.max for untimed work so it sorts last.
    var clockMinutes: Int {
        guard let time else { return Int.max }
        let parts = time.split(separator: ":").compactMap { Int($0) }
        guard let hour = parts.first else { return Int.max }
        return hour * 60 + (parts.count > 1 ? parts[1] : 0)
    }
}

extension KeyedDecodingContainer {
    /// A string field, with null, missing and blank all read as nil.
    func text(_ key: Key) -> String? {
        guard let value = try? decodeIfPresent(String.self, forKey: key), !value.isEmpty else { return nil }
        return value
    }
}

/// One logical day (`/v2/day`) or the Inbox (`/v2/day/inbox`).
struct DayView: Decodable {
    var date: String
    var timezone: String
    var items: [PlannerTask]
    var starredLimit: Int

    enum CodingKeys: String, CodingKey { case date, timezone, items, starredLimit = "starred_limit" }

    init(date: String, timezone: String = "Asia/Kolkata", items: [PlannerTask], starredLimit: Int = 5) {
        self.date = date; self.timezone = timezone; self.items = items; self.starredLimit = starredLimit
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        timezone = c.text(.timezone) ?? "Asia/Kolkata"
        items = try c.decode([PlannerTask].self, forKey: .items)
        starredLimit = (try? c.decodeIfPresent(Int.self, forKey: .starredLimit)) ?? 5
    }
}

/// Monday to Sunday of tasks, as `/v2/week` sends it.
struct WeekView: Decodable {
    var weekStart: String
    var items: [PlannerTask]

    enum CodingKeys: String, CodingKey { case weekStart = "week_start", items }
}

struct MilestoneRow: Decodable, Identifiable, Hashable {
    var id: String
    var name: String
    var targetDate: String?
    var status: String?

    enum CodingKeys: String, CodingKey { case id, name, targetDate = "target_date", status }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = c.text(.name) ?? "Milestone"
        targetDate = c.text(.targetDate)
        status = c.text(.status)
    }
}

struct ProjectRow: Decodable {
    var id: String
    var name: String
}

struct PlanningContext: Decodable {
    var projects: [ProjectRow]
}

/// A page of `/v2/native/dashboard` rows.
struct DashboardPage<Row: Decodable>: Decodable {
    var rows: [Row]
    var nextOffset: Int?

    enum CodingKeys: String, CodingKey { case rows, nextOffset = "next_offset" }
}

/// A milestone a move pushed out, as triage and task updates report it.
struct MilestoneExtension: Decodable {
    var name: String
    var from: String
    var to: String
}

struct MutationResult: Decodable {
    var milestonesExtended: [MilestoneExtension]?
    var task: CreatedTask?

    enum CodingKeys: String, CodingKey { case milestonesExtended = "milestones_extended", task }
}

struct CreatedTask: Decodable { var id: String }

struct Envelope<T: Decodable>: Decodable { var data: T }

/// Calendar dates as yyyy-MM-dd strings, which also sort correctly as text.
enum Civil {
    private static let utc: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }()

    private static func formatter(_ pattern: String, _ zone: TimeZone) -> DateFormatter {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = zone
        f.dateFormat = pattern
        return f
    }

    private static let isoUTC = formatter("yyyy-MM-dd", TimeZone(identifier: "UTC")!)
    private static let shortUTC = formatter("EEE d MMM", TimeZone(identifier: "UTC")!)
    private static let dayMonthUTC = formatter("d MMM", TimeZone(identifier: "UTC")!)

    static func parse(_ iso: String) -> Date? { isoUTC.date(from: String(iso.prefix(10))) }

    static func add(_ iso: String, days: Int) -> String {
        guard let date = parse(iso), let moved = utc.date(byAdding: .day, value: days, to: date) else { return iso }
        return isoUTC.string(from: moved)
    }

    /// Whole days from `a` to `b`.
    static func between(_ a: String, _ b: String) -> Int {
        guard let from = parse(a), let to = parse(b) else { return 0 }
        return utc.dateComponents([.day], from: from, to: to).day ?? 0
    }

    /// 1 for Monday through 7 for Sunday.
    static func weekday(_ iso: String) -> Int {
        guard let date = parse(iso) else { return 1 }
        return (utc.component(.weekday, from: date) + 5) % 7 + 1
    }

    static func weekStart(_ iso: String) -> String { add(iso, days: 1 - weekday(iso)) }

    static func today(in zone: TimeZone, now: Date = Date()) -> String { formatter("yyyy-MM-dd", zone).string(from: now) }

    /// The planner's day runs to 04:00, so a late evening still counts as that day.
    static func logicalToday(in zone: TimeZone, now: Date = Date()) -> String {
        today(in: zone, now: now.addingTimeInterval(-4 * 3600))
    }

    static func minutesOfDay(_ now: Date, in zone: TimeZone) -> Int {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let parts = calendar.dateComponents([.hour, .minute], from: now)
        return (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
    }

    /// The instant a date and "HH:mm" name in the workspace timezone.
    static func instant(_ iso: String, _ time: String, in zone: TimeZone) -> Date? {
        let day = iso.split(separator: "-").compactMap { Int($0) }
        let clock = time.split(separator: ":").compactMap { Int($0) }
        guard day.count == 3, clock.count >= 2 else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        return calendar.date(from: DateComponents(year: day[0], month: day[1], day: day[2], hour: clock[0], minute: clock[1]))
    }

    /// Midnight of a date in the workspace timezone, for date pickers.
    static func pickerDate(_ iso: String, in zone: TimeZone) -> Date { instant(iso, "00:00", in: zone) ?? Date() }

    static func iso(_ date: Date, in zone: TimeZone) -> String { formatter("yyyy-MM-dd", zone).string(from: date) }

    /// "Fri 30 Oct"
    static func short(_ iso: String) -> String { parse(iso).map(shortUTC.string(from:)) ?? iso }

    /// "30 Oct"
    static func dayMonth(_ iso: String) -> String { parse(iso).map(dayMonthUTC.string(from:)) ?? iso }

    private static let monthUTC = formatter("MMMM", TimeZone(identifier: "UTC")!)
    private static let weekdayUTC = formatter("EEE", TimeZone(identifier: "UTC")!)

    /// "May"
    static func monthName(_ iso: String) -> String { parse(iso).map(monthUTC.string(from:)) ?? "" }

    /// "2026"
    static func year(_ iso: String) -> String { String(iso.prefix(4)) }

    /// "Mon"
    static func weekdayShort(_ iso: String) -> String { parse(iso).map(weekdayUTC.string(from:)) ?? "" }

    /// Whether the device shows a 24-hour clock.
    static var prefers24Hour: Bool {
        !(DateFormatter.dateFormat(fromTemplate: "j", options: 0, locale: .current) ?? "").contains("a")
    }

    /// "07:00 AM", or "07:00" on a 24-hour device.
    static func clockText(_ minutes: Int, twentyFour: Bool) -> String {
        let m = ((minutes % 1440) + 1440) % 1440
        let hour = m / 60
        if twentyFour { return String(format: "%02d:%02d", hour, m % 60) }
        return String(format: "%02d:%02d", hour % 12 == 0 ? 12 : hour % 12, m % 60) + (hour < 12 ? " AM" : " PM")
    }

    /// "07:05" from minutes after midnight.
    static func clock(_ minutes: Int) -> String {
        let m = max(0, minutes) % (24 * 60)
        return String(format: "%02d:%02d", m / 60, m % 60)
    }
}
