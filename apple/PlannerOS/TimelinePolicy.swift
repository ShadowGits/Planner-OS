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
/// The planner's day runs to 04:00: the next date's tasks before then belong to
/// the evening, and the server lists them on its day as 24:00 and later (25:30).
let logicalDayCutoff = 4 * 60

/// The latest start a drag can reach: 27:55, as on the old timeline, which let a
/// task go that far without leaving the day.
let timelineLastStart = 27 * 60 + 55

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

private func snapToFive(_ minute: Double) -> Int { min(max(Int((minute / 5).rounded()) * 5, 0), timelineLastStart) }

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

/// Where a dropped task starts: at the time shown, from midnight to 27:55.
func dropStart(_ minute: Int) -> Int { min(max(minute, 0), timelineLastStart) }

/// The date and "HH:mm" a drop saves: past 24:00 is the next date.
func dropTarget(_ date: String, _ start: Int) -> (date: String, time: String) {
    let start = dropStart(start)
    return (start >= 24 * 60 ? Civil.add(date, days: 1) : date, Civil.clock(start % (24 * 60)))
}

/// Where the day's tasks finish, for the room below them.
func timelineLastEnd(_ items: [TimelineItem]) -> Int? {
    items.compactMap { item -> Int? in
        if case .task(let task, _) = item { return task.clockMinutes + task.minutes }
        return nil
    }.max()
}

/// While a task is held the timeline carries on below the last task at scale to
/// the end of the day at 04:00, with room for the held capsule, so it can land there.
func nightRoom(_ items: [TimelineItem], heldMinutes: Int) -> Double {
    guard let end = timelineLastEnd(items) else { return 0 }
    return Double(max(timelineLastStart - end, 0)) * timelinePointsPerMinute + pillHeight(heldMinutes)
}

/// The whole hours shown in that room, after the last task up to 04:00, where the day ends.
func nightHours(_ items: [TimelineItem]) -> [Int] {
    guard let end = timelineLastEnd(items) else { return [] }
    let first = (end + 59) / 60 * 60, last = 24 * 60 + logicalDayCutoff
    guard first <= last else { return [] }
    return stride(from: first, through: last, by: 60).filter { $0 - end >= 15 }
}

/// A task as a day's view shows it, as the server lists it: on its own date at
/// its time, or, before 04:00 on the next date, on this day at 24:00 and later
/// ("01:30" becomes "25:30"). Nil when it is on neither.
func shown(_ task: PlannerTask, on day: String) -> PlannerTask? {
    guard let date = task.date else { return nil }
    guard task.time != nil else { return date == day ? task : nil }
    let clock = task.clockMinutes % (24 * 60)
    var copy = task
    if date == day {
        copy.time = Civil.clock(clock)
        return copy
    }
    if date == Civil.add(day, days: 1), clock < logicalDayCutoff {
        copy.time = String(format: "%02d:%02d", (clock + 24 * 60) / 60, clock % 60)
        return copy
    }
    return nil
}

/// Minutes into the planner's day, which runs to 04:00: 01:30 is 25:30.
func logicalMinutes(_ moment: Moment) -> Int { moment.minutes < 4 * 60 ? moment.minutes + 24 * 60 : moment.minutes }

/// "Part 2/3" for a piece of a split task.
func partText(_ task: PlannerTask) -> String? {
    guard task.parent != nil else { return nil }
    return "Part \(task.partIndex.map(String.init) ?? "?")/\(task.partCount.map(String.init) ?? "?")"
}

/// "1h 5m", "25m", "30s", as Android writes time worked.
func workDuration(_ seconds: Int) -> String {
    let n = max(seconds, 0)
    var parts: [String] = []
    if n / 3600 > 0 { parts.append("\(n / 3600)h") }
    if n / 60 % 60 > 0 { parts.append("\(n / 60 % 60)m") }
    if n % 60 > 0 { parts.append("\(n % 60)s") }
    return parts.isEmpty ? "0m" : parts.joined(separator: " ")
}

/// "25m worked · 35m left", or just "1h worked" once it is done.
func workedText(_ task: PlannerTask) -> String {
    "\(workDuration(task.workedSeconds)) worked" + (task.done ? "" : " · \(workDuration(task.remainingSeconds)) left")
}

/// "Top Wins · 1 of 3", or "Day won" once every starred task is done.
func winsTitle(_ wins: [PlannerTask]) -> String {
    !wins.isEmpty && wins.allSatisfy(\.done) ? "Day won" : "Top Wins · \(wins.filter(\.done).count) of \(wins.count)"
}

/// The now bar's height in the list: at the current time's place in the layout, and when now
/// is before the first task or after the last, just above or below them. Nil on other days.
func nowBarOffset(_ now: Int, in items: [TimelineItem]) -> Double? {
    guard !items.isEmpty, now >= 0, now <= 24 * 60 + 240 else { return nil }
    let bottom = items.reduce(0) { $0 + itemHeight($1) }
    return min(max(offsetFor(now, in: items), -12), bottom + 20)
}

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

// MARK: Editing

/// What the task editor's fields hold, as plain values.
struct EditorFields: Equatable {
    var title: String
    /// yyyy-MM-dd, nil when "On a day" is off.
    var date: String?
    /// "HH:mm", nil when "At a time" is off.
    var time: String?
    var minutes: Int
    var notes: String
    var starred: Bool
}

/// The task as the editor saves it. Only fields the person changed in the
/// editor move away from the task; anything left alone keeps the task's own
/// value, so a rename saves the name and nothing else, whatever the date and
/// time pickers did with the time zone or a 25:30 slot.
func editedTask(_ task: PlannerTask, from start: EditorFields, to end: EditorFields) -> PlannerTask {
    var edited = task
    let title = end.title.trimmingCharacters(in: .whitespacesAndNewlines)
    if end.title != start.title, !title.isEmpty { edited.title = title }
    if end.date != start.date || end.time != start.time {
        edited.date = end.date
        edited.time = end.date == nil ? nil : end.time
    }
    if end.minutes != start.minutes { edited.minutes = end.minutes }
    if end.notes != start.notes {
        let notes = end.notes.trimmingCharacters(in: .whitespacesAndNewlines)
        edited.notes = notes.isEmpty ? nil : notes
    }
    if end.starred != start.starred { edited.starred = end.starred }
    return edited
}
