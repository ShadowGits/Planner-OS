import Foundation

// What Focus shows and in which order: the same rules as the web dashboard
// (Deutschland-Dash src/lib/focus.ts) and the Android app (FocusPolicy.kt), so
// every screen agrees on what is most pressing.

enum FocusReason: Int, CaseIterable {
    case deadline, missedSlot, neverScheduled

    var heading: String {
        switch self {
        case .deadline: return "Past deadline"
        case .missedSlot: return "Missed slot"
        case .neverScheduled: return "Never scheduled"
        }
    }
}

/// A milestone as far as Focus needs it: a name to show and a date to rank by.
struct FocusMilestone: Hashable {
    var id: String
    var name: String
    var targetDate: String?
}

/// "Now" in the workspace timezone: the calendar date and minutes after midnight.
struct Moment {
    var today: String
    var minutes: Int

    init(today: String, minutes: Int) { self.today = today; self.minutes = minutes }

    init(now: Date, timeZone: TimeZone) {
        today = Civil.today(in: timeZone, now: now)
        minutes = Civil.minutesOfDay(now, in: timeZone)
    }
}

typealias RankedTask = (task: PlannerTask, reason: FocusReason)

func isOverdue(_ task: PlannerTask, _ now: Moment) -> Bool {
    if task.done { return false }
    if let due = task.dueDate, due < now.today { return true }
    guard let date = task.date else { return false } // An undated idea has no missed deadline.
    if date < now.today { return true }
    if date == now.today, task.time != nil { return task.clockMinutes + task.minutes <= now.minutes }
    return false
}

/// The Inbox holds overdue work and untimed work for today or no day at all.
func belongsInInbox(_ task: PlannerTask, _ now: Moment) -> Bool {
    !task.done && (isOverdue(task, now) || (task.time == nil && (task.date == nil || task.date! <= now.today)))
}

/// Why a task is overdue, or nil when it is not. Unlike isOverdue, an idea with
/// no date at all counts here: Focus is where it gets one.
func focusReason(_ task: PlannerTask, _ now: Moment) -> FocusReason? {
    if task.done || task.habit { return nil }
    if let due = task.dueDate, due < now.today { return .deadline }
    if isOverdue(task, now) { return .missedSlot }
    if task.date == nil && task.dueDate == nil { return .neverScheduled }
    return nil
}

func isPinned(_ task: PlannerTask) -> Bool { task.starred || task.priority == "high" }

/// Work feeding a milestone this close outranks work that is merely older.
let milestoneSoonDays = 14

/// The day a task went wrong on: its deadline if that passed, else its slot.
func overdueSince(_ task: PlannerTask, _ reason: FocusReason) -> String? {
    reason == .deadline ? task.dueDate : (task.date ?? task.dueDate)
}

/// Overdue tasks, most pressing first. Priority alone cannot order them, since
/// nearly everything is "medium", so dates do the work: starred and
/// high-priority first, then broken deadlines before missed slots before
/// never-scheduled, then work for a milestone due within two weeks, then oldest.
func rankOverdue(_ tasks: [PlannerTask], milestones: [String: FocusMilestone], now: Moment) -> [RankedTask] {
    func soon(_ task: PlannerTask) -> Int {
        guard let target = task.milestoneId.flatMap({ milestones[$0]?.targetDate }) else { return Int.max }
        let days = Civil.between(now.today, target)
        return (0...milestoneSoonDays).contains(days) ? days : Int.max
    }
    func key(_ item: RankedTask) -> (Int, Int, Int, String, String) {
        (isPinned(item.task) ? 0 : 1, item.reason.rawValue, soon(item.task),
         overdueSince(item.task, item.reason) ?? "9999-12-31", item.task.title)
    }
    return tasks.compactMap { task in focusReason(task, now).map { (task: task, reason: $0) } }
        .sorted { key($0) < key($1) }
}

/// How late a task is, in words that fit on a card.
func lateness(_ task: PlannerTask, _ reason: FocusReason, _ now: Moment) -> String {
    if reason == .neverScheduled { return "Never scheduled" }
    guard let since = overdueSince(task, reason) else { return "Overdue" }
    let days = Civil.between(since, now.today)
    if reason == .deadline { return days <= 0 ? "Due today" : "\(days)d late" }
    let time = task.time.map { " " + $0 } ?? ""
    return days <= 0 ? "Missed today\(time)" : "Missed \(Civil.short(since))\(time)"
}

/// "milestone in 3d" when the task's milestone is close, else nil.
func milestoneSoon(_ task: PlannerTask, _ milestones: [String: FocusMilestone], _ now: Moment) -> String? {
    guard let target = task.milestoneId.flatMap({ milestones[$0]?.targetDate }) else { return nil }
    let days = Civil.between(now.today, target)
    if days < 0 || days > milestoneSoonDays { return nil }
    return days == 0 ? "milestone due today" : "milestone in \(days)d"
}

/// What is still to do today: today's planned tasks plus untimed work the
/// Inbox holds for today, minus anything already counted as overdue. Habits
/// stay on the timeline, where they are ticked.
func focusToday(_ todayView: DayView?, backlog: [PlannerTask], now: Moment) -> [PlannerTask] {
    // The view is the logical today, which runs to 04:00, so its tasks are taken
    // as they are rather than re-filtered by calendar date.
    var seen = Set<String>()
    return ((todayView?.items ?? []) + backlog)
        .filter { !$0.done && !$0.habit && focusReason($0, now) == nil && seen.insert($0.id).inserted }
        .sorted { a, b in
            (a.time == nil ? 1 : 0, a.clockMinutes, isPinned(a) ? 0 : 1, a.title)
                < (b.time == nil ? 1 : 0, b.clockMinutes, isPinned(b) ? 0 : 1, b.title)
        }
}

struct MoveOption: Identifiable, Hashable {
    var date: String
    var label: String
    var id: String { date }
}

/// One-tap move targets: today, tomorrow, the coming Saturday, next Monday.
func quickMoveDates(_ today: String) -> [MoveOption] {
    let weekday = Civil.weekday(today)
    let saturday = Civil.add(today, days: ((6 - weekday) + 7) % 7)
    let toMonday = (8 - weekday) % 7
    let monday = Civil.add(today, days: toMonday == 0 ? 7 : toMonday)
    var seen = Set<String>()
    return [(today, "Today"), (Civil.add(today, days: 1), "Tomorrow"),
            (saturday, Civil.short(saturday)), (monday, Civil.short(monday))]
        .filter { seen.insert($0.0).inserted }
        .map { MoveOption(date: $0.0, label: $0.1) }
}

struct FocusWeekRow: Identifiable {
    var id: String
    var label: String
    var sublabel: String?
    var milestone: FocusMilestone?
    /// Seven cells, Monday first.
    var cells: [[PlannerTask]]
}

/// The week as rows of seven: one row per milestone, or per project for tasks
/// with none, soonest milestone target first.
func focusWeekRows(_ items: [PlannerTask], weekStart: String, milestones: [String: FocusMilestone],
                   projectNames: [String: String]) -> [FocusWeekRow] {
    var rows: [String: FocusWeekRow] = [:]
    for task in items where !task.habit {
        guard let day = task.date ?? task.dueDate else { continue }
        let column = Civil.between(weekStart, day)
        guard (0...6).contains(column) else { continue }
        let milestone = task.milestoneId.flatMap { milestones[$0] }
        let key: String, label: String, sublabel: String?
        if let id = task.milestoneId {
            key = "m:\(id)"; label = milestone?.name ?? "Milestone"; sublabel = task.projectId.flatMap { projectNames[$0] }
        } else if let project = task.projectId {
            key = "p:\(project)"; label = projectNames[project] ?? "Project"; sublabel = "No milestone"
        } else {
            key = "none"; label = "Other"; sublabel = "No project"
        }
        var row = rows[key] ?? FocusWeekRow(id: key, label: label, sublabel: sublabel, milestone: milestone,
                                            cells: Array(repeating: [], count: 7))
        row.cells[column].append(task)
        rows[key] = row
    }
    func rank(_ key: String) -> Int { key.hasPrefix("m:") ? 0 : key.hasPrefix("p:") ? 1 : 2 }
    return rows.values
        .sorted { (rank($0.id), $0.milestone?.targetDate ?? "9999-12-31", $0.label) < (rank($1.id), $1.milestone?.targetDate ?? "9999-12-31", $1.label) }
        .map { row in
            var sorted = row
            sorted.cells = row.cells.map { $0.sorted { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) } }
            return sorted
        }
}

/// The same task after a Focus move: planned for the day with no time, so it
/// lands in that day's unscheduled list. A deadline already broken moves with
/// it, as the server does; one still ahead stays.
func movedForFocus(_ task: PlannerTask, to: String, today: String) -> PlannerTask {
    var moved = task
    moved.date = to
    moved.time = nil
    if let due = task.dueDate, due < today { moved.dueDate = to }
    return moved
}

/// "Shortlist finalized" now due 9 Nov (was 2 Nov), for each milestone a write pushed out.
func milestoneNotes(_ response: Data) -> [String] {
    guard let result = try? JSONDecoder().decode(Envelope<MutationResult>.self, from: response) else { return [] }
    return (result.data.milestonesExtended ?? []).map {
        "\"\($0.name)\" now due \(Civil.dayMonth($0.to)) (was \(Civil.dayMonth($0.from)))"
    }
}

/// Side-by-side lanes for overlapping timeline blocks: each task's lane and how
/// many lanes its cluster of overlaps needs.
func timelineLanes(_ tasks: [PlannerTask], minimumMinutes: Int = 25) -> [String: (index: Int, count: Int)] {
    var result: [String: (index: Int, count: Int)] = [:]
    var cluster: [(id: String, lane: Int)] = []
    var laneEnds: [Int] = []
    var clusterEnd = Int.min
    func flush() {
        for member in cluster { result[member.id] = (index: member.lane, count: laneEnds.count) }
        cluster = []
        laneEnds = []
    }
    for task in tasks.filter({ $0.time != nil }).sorted(by: { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) }) {
        let start = task.clockMinutes, end = start + max(task.minutes, minimumMinutes)
        if !cluster.isEmpty && start >= clusterEnd { flush(); clusterEnd = Int.min }
        if let lane = laneEnds.firstIndex(where: { $0 <= start }) {
            laneEnds[lane] = end
            cluster.append((id: task.id, lane: lane))
        } else {
            laneEnds.append(end)
            cluster.append((id: task.id, lane: laneEnds.count - 1))
        }
        clusterEnd = max(clusterEnd, end)
    }
    flush()
    return result
}

/// A dragged block's new start: snapped to five minutes and kept inside the day.
func snappedStart(_ start: Int, minutes: Int, dragMinutes: Double) -> Int {
    let snapped = Int(((Double(start) + dragMinutes) / 5).rounded()) * 5
    return min(max(snapped, 0), 24 * 60 - min(max(minutes, 5), 24 * 60))
}

struct Reminder: Hashable {
    var id: String
    var title: String
    var body: String
    var fire: Date
}

/// Reminder lead time, as on Android: ten minutes before each timed task.
let reminderLeadMinutes = 10

/// iOS keeps at most 64 pending notifications; leave room for the test one.
let reminderLimit = 60

/// The reminders the coming days need, soonest first.
func planReminders(_ days: [DayView], now: Date, timeZone: TimeZone) -> [Reminder] {
    var seen = Set<String>()
    var reminders: [Reminder] = []
    for view in days {
        for task in view.items where !task.done {
            guard let time = task.time, let start = Civil.instant(task.date ?? view.date, time, in: timeZone) else { continue }
            let fire = start.addingTimeInterval(TimeInterval(-reminderLeadMinutes * 60))
            let id = "task-\(task.id)-\(task.date ?? view.date)-\(time)"
            guard fire > now, seen.insert(id).inserted else { continue }
            reminders.append(Reminder(id: id, title: task.title,
                                      body: "Starts at \(time) · \(task.minutes) min", fire: fire))
        }
    }
    return Array(reminders.sorted { ($0.fire, $0.id) < ($1.fire, $1.id) }.prefix(reminderLimit))
}
