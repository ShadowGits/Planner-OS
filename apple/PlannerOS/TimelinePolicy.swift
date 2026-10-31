import Foundation

// The day laid out as Structured lays it out (docs/structured-ux.md): time runs
// down the page at 1.6 pt a minute, each task a capsule on a spine, free time
// between them. Android follows the same rules in StructuredTimeline.kt.

enum TimelineItem: Identifiable, Equatable {
    case task(PlannerTask, showsStart: Bool)
    /// Free time between tasks, and the task that follows it.
    case gap(start: Int, minutes: Int, next: String)

    var id: String {
        switch self {
        case .task(let task, _): return task.id
        case .gap(let start, _, _): return "gap-\(start)"
        }
    }
}

/// Timed tasks in order, with free time of five minutes or more between them.
/// A start time is shown only where it is not the previous task's end.
func timelineItems(_ tasks: [PlannerTask]) -> [TimelineItem] {
    let timed = tasks.filter { $0.time != nil }
        .sorted { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) }
    var items: [TimelineItem] = []
    var lastEnd: Int?
    for task in timed {
        let start = task.clockMinutes
        if let end = lastEnd, start - end >= 5 {
            items.append(.gap(start: end, minutes: start - end, next: task.title))
        }
        items.append(.task(task, showsStart: lastEnd != start))
        lastEnd = max(lastEnd ?? 0, start + task.minutes)
    }
    return items
}

/// Structured's scale: two hours is about 190 pt.
let timelinePointsPerMinute = 1.6
/// Capsule width, and the height of the shortest task (a circle).
let timelinePillWidth = 48.0
/// Space above and below each capsule inside its row.
let timelineRowPadding = 4.0
private let lastStart = 24 * 60 - 5

func pillHeight(_ minutes: Int) -> Double { min(max(Double(minutes) * timelinePointsPerMinute, timelinePillWidth), 640) }

/// A few minutes is a short piece of spine; free time keeps the scale; a long window is capped.
func gapHeight(_ minutes: Int) -> Double {
    if minutes < 30 { return 16 }
    if minutes < 180 { return max(Double(minutes) * timelinePointsPerMinute, 64) }
    return 104
}

func itemHeight(_ item: TimelineItem) -> Double {
    switch item {
    case .task(let task, _): return pillHeight(task.minutes) + 2 * timelineRowPadding
    case .gap(_, let minutes, _): return gapHeight(minutes)
    }
}

/// How far down the list an item starts.
func itemOffset(_ id: String, in items: [TimelineItem]) -> Double? {
    var top = 0.0
    for item in items {
        if item.id == id { return top }
        top += itemHeight(item)
    }
    return nil
}

private func snapToFive(_ minute: Double) -> Int { min(max(Int((minute / 5).rounded()) * 5, 0), lastStart) }

private func firstStart(_ items: [TimelineItem]) -> Int? {
    for item in items { if case .task(let task, _) = item { return task.clockMinutes } }
    return nil
}

/// The time a point of the list stands for, y in points from its top, snapped to
/// five minutes. Inside a capsule time runs over its duration, inside free time
/// over the gap, beyond the ends at scale.
func minuteAt(_ y: Double, in items: [TimelineItem]) -> Int {
    if y < 0 { return snapToFive(Double(firstStart(items) ?? 9 * 60) + y / timelinePointsPerMinute) }
    var top = 0.0
    var end: Int?
    for item in items {
        let height = itemHeight(item)
        switch item {
        case .task(let task, _):
            if y < top + height {
                let inside = min(max((y - top - timelineRowPadding) / pillHeight(task.minutes), 0), 1)
                return snapToFive(Double(task.clockMinutes) + inside * Double(task.minutes))
            }
            end = max(end ?? 0, task.clockMinutes + task.minutes)
        case .gap(let start, let minutes, _):
            if y < top + height { return snapToFive(Double(start) + (y - top) / height * Double(minutes)) }
            end = start + minutes
        }
        top += height
    }
    return snapToFive(Double(end ?? 9 * 60) + (y - top) / timelinePointsPerMinute)
}

/// Where a time sits in the list: the inverse of minuteAt.
func offsetFor(_ minute: Int, in items: [TimelineItem]) -> Double {
    if let first = firstStart(items), minute < first { return Double(minute - first) * timelinePointsPerMinute }
    var top = 0.0
    var end: Int?
    for item in items {
        let height = itemHeight(item)
        switch item {
        case .task(let task, _):
            if minute < task.clockMinutes { return top }
            if minute < task.clockMinutes + task.minutes {
                return top + timelineRowPadding
                    + Double(minute - task.clockMinutes) / Double(max(task.minutes, 1)) * pillHeight(task.minutes)
            }
            end = max(end ?? 0, task.clockMinutes + task.minutes)
        case .gap(let start, let minutes, _):
            if minute < start + minutes { return top + Double(minute - start) / Double(max(minutes, 1)) * height }
            end = start + minutes
        }
        top += height
    }
    return top + Double(minute - (end ?? 9 * 60)) * timelinePointsPerMinute
}

/// Where a dropped task starts: at the time shown, kept inside the day.
func dropStart(_ minute: Int, duration: Int) -> Int { min(max(minute, 0), 24 * 60 - min(max(duration, 5), 24 * 60)) }

/// Where a task stands against the clock, which decides how its capsule is filled.
enum TaskPhase { case upcoming, underway, past, done }

/// `now` is minutes into the day shown: Int.max on an earlier day, -1 on a later one.
func taskPhase(_ task: PlannerTask, now: Int) -> TaskPhase {
    if task.done { return .done }
    if now >= task.clockMinutes + task.minutes { return .past }
    if now >= task.clockMinutes { return .underway }
    return .upcoming
}

func taskProgress(_ task: PlannerTask, now: Int) -> Double {
    min(max(Double(now - task.clockMinutes) / Double(max(task.minutes, 1)), 0), 1)
}

func nowOnDay(_ day: String, today: String, minutes: Int) -> Int {
    if day < today { return Int.max }
    if day > today { return -1 }
    return minutes
}

/// "15m", "1h", "1h 30m"
func durationText(_ minutes: Int) -> String {
    if minutes < 60 { return "\(minutes)m" }
    return minutes % 60 == 0 ? "\(minutes / 60)h" : "\(minutes / 60)h \(minutes % 60)m"
}

/// "15 min", "1 hr", "1 hr, 30 min", as in the subtitle.
func durationWords(_ minutes: Int) -> String {
    if minutes < 60 { return "\(minutes) min" }
    return minutes % 60 == 0 ? "\(minutes / 60) hr" : "\(minutes / 60) hr, \(minutes % 60) min"
}

func remainingText(_ task: PlannerTask, now: Int) -> String {
    "\(durationText(max(task.clockMinutes + task.minutes - now, 1))) remaining"
}

/// "7:00" on a 12-hour device, "07:00" on a 24-hour one, as in the left column.
func columnClock(_ minute: Int, twentyFour: Bool) -> String {
    let m = ((minute % 1440) + 1440) % 1440, hour = m / 60
    if twentyFour { return String(format: "%02d:%02d", hour, m % 60) }
    return "\(hour % 12 == 0 ? 12 : hour % 12):" + String(format: "%02d", m % 60)
}

private func half(_ minute: Int) -> String { ((minute % 1440) + 1440) % 1440 < 720 ? "AM" : "PM" }

/// "4:15 PM", used while dragging.
func fullClock(_ minute: Int, twentyFour: Bool) -> String {
    twentyFour ? columnClock(minute, twentyFour: true) : "\(columnClock(minute, twentyFour: false)) \(half(minute))"
}

/// "7:00–7:15 AM", or "11:30 AM–12:15 PM" across noon, or "07:00–07:15".
func rangeText(_ start: Int, _ end: Int, twentyFour: Bool) -> String {
    if twentyFour { return "\(columnClock(start, twentyFour: true))–\(columnClock(end, twentyFour: true))" }
    if half(start) == half(end) { return "\(columnClock(start, twentyFour: false))–\(columnClock(end, twentyFour: false)) \(half(end))" }
    return "\(fullClock(start, twentyFour: false))–\(fullClock(end, twentyFour: false))"
}

/// Whole hours inside a long task, for the left column.
func hourMarks(_ task: PlannerTask) -> [Int] {
    let start = task.clockMinutes, end = task.clockMinutes + task.minutes
    let first = start / 60 + 1, last = (end - 1) / 60
    guard first <= last else { return [] }
    return (first...last).map { $0 * 60 }.filter { $0 - start >= 25 && end - $0 >= 25 }
}

/// Words in a title that pick its icon, first match wins; Android uses the same list.
private let symbolRules: [([String], String)] = [
    (["wake", "alarm"], "alarm"),
    (["sleep", "bed", "nap"], "bed.double"),
    (["yoga", "meditat", "stretch", "breath"], "figure.mind.and.body"),
    (["gym", "workout", "lift", "strength"], "dumbbell"),
    (["run", "jog"], "figure.run"),
    (["walk"], "figure.walk"),
    (["bike", "cycl"], "bicycle"),
    (["shower", "get ready", "bath"], "shower"),
    (["coffee", "tea"], "cup.and.saucer"),
    (["breakfast", "lunch", "dinner", "meal", "eat", "cook"], "fork.knife"),
    (["water", "hydrat"], "drop"),
    (["german", "language", "duolingo", "vocab"], "character.bubble"),
    (["study", "learn", "course", "lecture", "class", "calculus", "math", "revise", "exam"], "book"),
    (["read", "book"], "book.closed"),
    (["apply", "application", "university", "uni ", "admission", "aps"], "graduationcap"),
    (["cv", "resume", "write", "essay", "sop", "letter", "draft"], "pencil"),
    (["call", "phone"], "phone"),
    (["meet", "interview", "sync", "standup"], "person.2"),
    (["mail", "email", "inbox"], "envelope"),
    (["code", "dev", "build", "deploy", "bug", "app", "planner"], "laptopcomputer"),
    (["pay", "bank", "budget", "tax", "finance", "money", "rent", "invoice"], "creditcard"),
    (["shop", "grocer", "buy"], "cart"),
    (["clean", "laundry", "tidy"], "sparkles"),
    (["flight", "travel", "visa", "trip", "airport"], "airplane"),
    (["drive", "car "], "car"),
    (["doctor", "health", "medic", "dentist"], "cross.case"),
    (["birthday", "anniversary", "gift"], "gift"),
    (["music", "guitar", "piano"], "music.note"),
    (["plan", "review", "journal"], "list.bullet.clipboard"),
    (["work", "office", "job", "intern"], "briefcase"),
]

/// The SF Symbol a task shows in its capsule.
func taskSymbol(_ task: PlannerTask) -> String {
    let title = " " + task.title.lowercased() + " "
    for (words, symbol) in symbolRules where words.contains(where: { title.contains($0) }) { return symbol }
    return task.habit ? "repeat" : "checklist"
}

/// A colour slot that stays the same for a title across launches and devices
/// (Swift's own string hash changes every launch, so this one is spelled out).
func paletteIndex(_ task: PlannerTask, count: Int) -> Int {
    var hash: UInt64 = 5381
    for scalar in task.title.unicodeScalars { hash = (hash &* 33) &+ UInt64(scalar.value) }
    return Int(hash % UInt64(max(count, 1)))
}

/// The task to scroll to: the one under way or next up today, else the first.
func timelineAnchor(_ items: [TimelineItem], now: Int?) -> String? {
    let tasks = items.compactMap { item -> PlannerTask? in
        if case .task(let task, _) = item { return task }
        return nil
    }
    if let now, let current = tasks.first(where: { $0.clockMinutes + $0.minutes > now }) { return current.id }
    return tasks.first?.id
}
