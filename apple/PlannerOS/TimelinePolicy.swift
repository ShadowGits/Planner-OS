import Foundation

// The Timeline's layout rules: a vertical spine of capsules whose height
// follows duration, with free time shown between them.

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

/// Points per minute of a capsule; drags convert back with the same scale.
let timelinePointsPerMinute = 2.4

/// A 15-minute task is a circle; longer ones stretch, up to a limit.
func pillHeight(_ minutes: Int) -> Double { min(max(Double(minutes) * timelinePointsPerMinute, 52), 216) }

/// Free time takes less room than work does.
func gapHeight(_ minutes: Int) -> Double { min(max(Double(minutes) * 0.6, 34), 96) }

/// "15m", "1h", "1h 30m"
func durationText(_ minutes: Int) -> String {
    if minutes < 60 { return "\(minutes)m" }
    return minutes % 60 == 0 ? "\(minutes / 60)h" : "\(minutes / 60)h \(minutes % 60)m"
}

/// Words in a title that pick its icon, first match wins.
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

/// A colour slot that stays the same for a title across launches (Swift's own
/// string hash changes every launch, so this one is spelled out).
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
