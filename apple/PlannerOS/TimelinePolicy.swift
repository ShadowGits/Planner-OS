import Foundation
#if canImport(CoreGraphics)
import CoreGraphics
#endif

/// A chosen timeline gap. Its bounds stay in logical-day minutes; only the
/// write converts an overnight slot to the next calendar date.
struct PendingSlot: Equatable {
    let day: String
    let start: Int
    let end: Int

    init(day: String, start: Int, end: Int) {
        self.day = day
        self.start = ((start + 4) / 5) * 5
        self.end = end
    }

    var target: (date: String, time: String) { dropTarget(day, start) }
    var minutes: Int { max(0, end - start) }

    func accepts(_ task: PlannerTask) -> Bool {
        guard !task.done, !task.habit, !task.fromCalendar, !task.id.hasPrefix("pending:") else { return false }
        guard let date = task.date ?? task.dueDate else { return true }
        if date != target.date { return date < target.date }
        guard task.time != nil else { return true }
        return task.clockMinutes + task.minutes <= start % 1440
    }

    /// Keep the full scheduled duration: fitting is a move, never a silent
    /// shortening or split, even when some actual work has already been logged.
    func fits(_ task: PlannerTask) -> Bool { task.minutes <= minutes }

    func candidates(_ tasks: [PlannerTask]) -> [PlannerTask] {
        var seen = Set<String>()
        return tasks.filter { accepts($0) && seen.insert($0.id).inserted }.sorted {
            if fits($0) != fits($1) { return fits($0) }
            if $0.starred != $1.starred { return $0.starred }
            return ($0.date ?? $0.dueDate ?? "9999", $0.title, $0.id) < ($1.date ?? $1.dueDate ?? "9999", $1.title, $1.id)
        }
    }

    func isFree(for task: PlannerTask, among tasks: [PlannerTask]) -> Bool {
        guard fits(task) else { return false }
        return !tasks.contains { other in
            var dated = other
            dated.date = other.date ?? other.dueDate
            guard other.id != task.id, let displayed = shown(dated, on: day), displayed.time != nil else { return false }
            return displayed.clockMinutes < start + task.minutes && displayed.clockMinutes + displayed.minutes > start
        }
    }
}

/// Free stretches on the calendar day, merging overlaps before offering a gap.
func pendingSlots(day: String, tasks: [PlannerTask]) -> [PendingSlot] {
    let timed = calendarDay(tasks).filter { $0.time != nil }.sorted { $0.clockMinutes < $1.clockMinutes }
    var end = 0
    var slots: [PendingSlot] = []
    for task in timed {
        let slot = PendingSlot(day: day, start: end, end: min(task.clockMinutes, 1440))
        if slot.minutes >= 30 { slots.append(slot) }
        end = max(end, task.clockMinutes + task.minutes)
    }
    let last = PendingSlot(day: day, start: end, end: 1440)
    if last.minutes >= 30 { slots.append(last) }
    return slots
}


// The timeline: one scroll across days. A day runs midnight to midnight, every
// hour is the same height, and a thick header marks where each one starts.
// Everything here is plain arithmetic, so the screen that draws it and the
// gestures that hit-test it cannot disagree, and it is checked without Xcode.

let timelineHourHeight = 50.0
let timelineDayHeight = 24 * timelineHourHeight
let timelineHeaderHeight = 64.0
/// The Top Wins bar pinned above the scroll. Always there: were it to come and go
/// with the day in view, the scroll would resize and the day in view flip back.
let timelineWinsHeight = 44.0
let timelineUntimedHeight = 44.0
/// Room above 00:00 and below 24:00, so the first hour label is not on the header's line.
let timelineGridPadding = 10.0
/// The least a block is drawn: just under half an hour, so half-hour tasks back
/// to back never collide. Shorter ones that would collide go side by side.
let timelineMinBlock = 24.0
let timelineLabelWidth = 56.0
let timelineTrailing = 8.0
let timelineDaysBack = 14
let timelineDaysAhead = 60

/// How far down its day's 24 hours a minute sits.
func minuteOffset(_ minute: Int) -> Double { Double(minute) * timelineHourHeight / 60 }

/// The day as the timeline shows it, midnight to midnight: the next morning's
/// tasks the server also lists on this day, at 24:00 and later, are left to their own date.
func calendarDay(_ items: [PlannerTask]) -> [PlannerTask] {
    items.filter { $0.time == nil || $0.clockMinutes < 24 * 60 }
}

/// A timed task's place in its day: which column of how many, and where.
struct TimelineBlock: Equatable, Identifiable {
    var task: PlannerTask
    var column: Int
    var columns: Int
    /// Points below 00:00.
    var top: Double
    var height: Double
    var id: String { task.id }

    /// In the day's 24-hour grid, as wide as `width`.
    func frame(width: Double) -> CGRect {
        let each = width / Double(max(columns, 1))
        let gap = columns > 1 ? 3.0 : 0
        return CGRect(x: each * Double(column), y: top, width: max(each - gap, 1), height: height)
    }
}

/// Blocks that would touch on screen share the width, each in the first column
/// free at its start, as a calendar does. Nothing is moved and nothing is hidden.
func timelineBlocks(_ tasks: [PlannerTask]) -> [TimelineBlock] {
    let sized = tasks.filter { $0.time != nil }
        .map { task -> TimelineBlock in
            let top = min(minuteOffset(task.clockMinutes), timelineDayHeight - timelineMinBlock)
            // A task that runs past midnight is cut at the line; it is not repeated below it.
            let height = min(max(minuteOffset(task.minutes), timelineMinBlock), timelineDayHeight - top)
            return TimelineBlock(task: task, column: 0, columns: 1, top: top, height: height)
        }
        .sorted { ($0.top, $0.task.title, $0.id) < ($1.top, $1.task.title, $1.id) }

    var out: [TimelineBlock] = []
    var group: [TimelineBlock] = []
    var ends: [Double] = []
    let touch = 0.01
    func close() {
        out += group.map { var block = $0; block.columns = ends.count; return block }
        group = []
        ends = []
    }
    for var block in sized {
        if let last = ends.max(), block.top >= last - touch { close() }
        if let free = ends.firstIndex(where: { block.top >= $0 - touch }) {
            block.column = free
            ends[free] = block.top + block.height
        } else {
            block.column = ends.count
            ends.append(block.top + block.height)
        }
        group.append(block)
    }
    close()
    return out
}

/// Free time between two timed tasks, which a tap fills with a new one.
struct TimelineGap: Equatable, Identifiable {
    var start: Int
    var minutes: Int
    /// Points below 00:00, clear of a short task drawn taller than it is.
    var top: Double
    var height: Double

    var id: Int { start }
    /// A new task's start: the gap's, rounded up to five minutes.
    var addAt: Int { min((start + 4) / 5 * 5, 24 * 60 - 5) }
}

/// Five minutes or more free between one timed task and the next. The time
/// before the first and after the last is not a gap.
func timelineGaps(_ blocks: [TimelineBlock]) -> [TimelineGap] {
    var gaps: [TimelineGap] = []
    var previous: (end: Int, bottom: Double)?
    for block in blocks.sorted(by: { $0.task.clockMinutes < $1.task.clockMinutes }) {
        let start = block.task.clockMinutes
        if let previous, start - previous.end >= 5 {
            let top = max(minuteOffset(previous.end), previous.bottom)
            if block.top > top {
                gaps.append(TimelineGap(start: previous.end, minutes: start - previous.end, top: top, height: block.top - top))
            }
        }
        previous = (max(previous?.end ?? 0, start + max(block.task.minutes, 1)),
                    max(previous?.bottom ?? 0, block.top + block.height))
    }
    return gaps
}

/// Where Now goes: the task under way or next. Nil once the day's are over.
func timelineAnchor(_ tasks: [PlannerTask], now: Int) -> PlannerTask? {
    tasks.filter { $0.time != nil }
        .sorted { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) }
        .first { $0.clockMinutes + $0.minutes > now }
}

/// The buttons that sit on a block, in its own coordinates. Neither ever
/// reaches outside its block, where a tap would belong to the task next to it.
struct BlockParts: Equatable {
    var tick: CGRect
    var star: CGRect?

    init(width: Double, height: Double) {
        let tickWidth = min(44, width / 2), side = min(44, height)
        tick = CGRect(x: width - tickWidth, y: height - side, width: tickWidth, height: side)
        star = width >= 150 ? CGRect(x: width - tickWidth - 40, y: height - side, width: 40, height: side) : nil
    }
}

/// One day's part of the scroll.
struct TimelineDay: Equatable, Identifiable {
    var date: String
    var top: Double
    var untimed: [PlannerTask]
    var blocks: [TimelineBlock]
    var gaps: [TimelineGap]

    var id: String { date }
    var untimedTop: Double { top + timelineHeaderHeight }
    /// 00:00 of this day.
    var gridTop: Double { untimedTop + Double(untimed.count) * timelineUntimedHeight + timelineGridPadding }
    /// 24:00 of this day.
    var gridBottom: Double { gridTop + timelineDayHeight }
    var bottom: Double { gridBottom + timelineGridPadding }
}

/// A point of the scroll by what it shows, which holds when heights above it change.
enum TimelineSpot: Equatable {
    case clock(date: String, minute: Double)
    case head(date: String, offset: Double)
}

/// A task under a point of the scroll.
struct TimelineHit: Equatable {
    var task: PlannerTask
    var date: String
    /// In the scroll's coordinates.
    var frame: CGRect
}

struct TimelineLayout: Equatable {
    private(set) var days: [TimelineDay] = []

    init(dates: [String] = [], tasks: (String) -> [PlannerTask] = { _ in [] }) {
        var top = 0.0
        for date in dates {
            let items = calendarDay(tasks(date))
            let byName = items.sorted { ($0.clockMinutes, $0.title, $0.id) < ($1.clockMinutes, $1.title, $1.id) }
            let blocks = timelineBlocks(items)
            let day = TimelineDay(date: date, top: top, untimed: byName.filter { $0.time == nil },
                                  blocks: blocks, gaps: timelineGaps(blocks))
            days.append(day)
            top = day.bottom
        }
    }

    var height: Double { days.last?.bottom ?? 0 }

    func day(_ date: String) -> TimelineDay? { days.first { $0.date == date } }

    /// The day at a height, the nearest one past either end.
    func index(at y: Double) -> Int? {
        guard !days.isEmpty else { return nil }
        var low = 0, high = days.count - 1
        while low < high {
            let middle = (low + high) / 2
            if days[middle].bottom <= y { low = middle + 1 } else { high = middle }
        }
        return low
    }

    func spot(at y: Double) -> TimelineSpot? {
        guard let index = index(at: y) else { return nil }
        let day = days[index]
        // From the room above 00:00 down is the clock's: a hair short of midnight is still midnight.
        if y < day.gridTop - timelineGridPadding { return .head(date: day.date, offset: y - day.top) }
        return .clock(date: day.date, minute: (y - day.gridTop) / timelineHourHeight * 60)
    }

    func y(of spot: TimelineSpot) -> Double? {
        switch spot {
        case .head(let date, let offset):
            return day(date).map { min($0.top + offset, $0.gridTop) }
        case .clock(let date, let minute):
            return day(date).map { $0.gridTop + minute / 60 * timelineHourHeight }
        }
    }

    /// The date and time a block whose top is at `y` lands on, to five minutes.
    /// Crossing a day's header is crossing midnight.
    func landing(at y: Double) -> (date: String, start: Int)? {
        guard let index = index(at: y) else { return nil }
        let day = days[index]
        if y < day.gridTop { return (day.date, 0) }
        let minute = Int(((y - day.gridTop) / timelineHourHeight * 12).rounded()) * 5
        return (day.date, min(minute, 24 * 60 - 5))
    }

    /// The task under a point of a scroll `width` wide: by its body, which is
    /// what a tap or a hold takes, or `anywhere` on it, which is enough to swipe it.
    func hit(_ point: CGPoint, width: Double, anywhere: Bool = false) -> TimelineHit? {
        let x = Double(point.x), y = Double(point.y)
        guard y >= 0, y < height, let index = index(at: y) else { return nil }
        let day = days[index]
        let right = width - timelineTrailing
        if y >= day.untimedTop, y < day.gridTop - timelineGridPadding {
            let row = Int((y - day.untimedTop) / timelineUntimedHeight)
            let button = anywhere ? 0 : timelineUntimedHeight
            guard day.untimed.indices.contains(row), x >= timelineTrailing + button, x < right - button else { return nil }
            let frame = CGRect(x: timelineTrailing, y: day.untimedTop + Double(row) * timelineUntimedHeight,
                               width: right - timelineTrailing, height: timelineUntimedHeight)
            return TimelineHit(task: day.untimed[row], date: day.date, frame: frame)
        }
        for block in day.blocks {
            let frame = block.frame(width: right - timelineLabelWidth).offsetBy(dx: timelineLabelWidth, dy: day.gridTop)
            guard frame.contains(point) else { continue }
            let parts = BlockParts(width: Double(frame.width), height: Double(frame.height))
            let inside = CGPoint(x: point.x - frame.minX, y: point.y - frame.minY)
            if !anywhere, parts.tick.contains(inside) || parts.star?.contains(inside) == true { return nil }
            return TimelineHit(task: block.task, date: day.date, frame: frame)
        }
        return nil
    }
}

/// The dates the timeline scrolls over: two weeks back to sixty days ahead,
/// stretched to reach a day picked outside them.
func timelineDates(today: String, reaching picked: String? = nil) -> [String] {
    let usual = (Civil.add(today, days: -timelineDaysBack), Civil.add(today, days: timelineDaysAhead))
    let first = min(usual.0, picked ?? usual.0), last = max(usual.1, picked ?? usual.1)
    return (0...max(Civil.between(first, last), 0)).map { Civil.add(first, days: $0) }
}

/// "7 AM", or "07:00" on a 24-hour device: twelve o'clock comes twice in a day, so it says which.
func hourLabel(_ hour: Int, twentyFour: Bool) -> String {
    if twentyFour { return String(format: "%02d:00", hour % 24) }
    let clock = hour % 24
    return "\(clock % 12 == 0 ? 12 : clock % 12) \(clock < 12 ? "AM" : "PM")"
}

/// The next morning before this still shows on the widget's evening (the store keeps 25:30 for it).
let logicalDayCutoff = 4 * 60

/// The latest start the store takes for a day: 27:55, which saves on the next date.
let timelineLastStart = 27 * 60 + 55

/// Where a dropped task starts: at the time shown, from midnight to 27:55.
func dropStart(_ minute: Int) -> Int { min(max(minute, 0), timelineLastStart) }

/// The date and "HH:mm" a drop saves: past 24:00 is the next date.
func dropTarget(_ date: String, _ start: Int) -> (date: String, time: String) {
    let start = dropStart(start)
    return (start >= 24 * 60 ? Civil.add(date, days: 1) : date, Civil.clock(start % (24 * 60)))
}

/// A task as a day's view shows it, as the server lists it: on its own date at
/// its time, or, before 04:00 on the next date, on this day at 24:00 and later
/// ("01:30" becomes "25:30"). Nil when it is on neither.
func shown(_ task: PlannerTask, on day: String) -> PlannerTask? {
    // With no date it is listed on the day it is due, as the server lists it.
    guard let date = task.date else { return task.dueDate == day ? task : nil }
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

// MARK: The floating clock

/// What the Mac's floating clock counts: the task under way, or the vacant time
/// until the next, and what is next either way.
struct ClockFocus: Equatable {
    /// The one under way; in vacant time, the one that ends it.
    var task: PlannerTask
    var running: Bool
    /// Seconds to its end while it runs, to its start before that.
    var remaining: Int
    /// How far round the ring is: through the task, or through the last hour before it.
    var progress: Double
    /// Others under way at the same time, or starting at the same moment.
    var others: Int
    /// The next to start, whether or not something is under way.
    var next: PlannerTask?
    var nextIsTomorrow = false
}

/// The latest to start of those under way, else the next to start, today or
/// tomorrow. Yesterday counts, for a task that runs on past midnight.
func clockFocus(today: String, seconds: Int, tasks: (String) -> [PlannerTask]) -> ClockFocus? {
    var timed: [(task: PlannerTask, start: Int, end: Int)] = []
    for offset in -1...1 {
        for task in calendarDay(tasks(Civil.add(today, days: offset))) where task.time != nil && !task.done {
            let start = offset * 86_400 + task.clockMinutes * 60
            timed.append((task, start, start + task.minutes * 60))
        }
    }
    timed.sort { ($0.start, $0.task.title) < ($1.start, $1.task.title) }
    let running = timed.filter { $0.start <= seconds && seconds < $0.end }
    let upcoming = timed.first { $0.start > seconds }
    let tomorrow = (upcoming?.start ?? 0) >= 86_400
    if let current = running.last {
        return ClockFocus(task: current.task, running: true, remaining: current.end - seconds,
                          progress: Double(seconds - current.start) / Double(max(current.end - current.start, 1)),
                          others: running.count - 1, next: upcoming?.task, nextIsTomorrow: tomorrow)
    }
    guard let next = upcoming else { return nil }
    let wait = next.start - seconds
    return ClockFocus(task: next.task, running: false, remaining: wait, progress: max(1 - Double(wait) / 3600, 0),
                      others: timed.filter { $0.start == next.start }.count - 1, next: next.task, nextIsTomorrow: tomorrow)
}

/// "4:05", or "1:04:05" from an hour up.
func countdownText(_ seconds: Int) -> String {
    let left = max(seconds, 0)
    if left >= 3600 { return String(format: "%d:%02d:%02d", left / 3600, left / 60 % 60, left % 60) }
    return String(format: "%d:%02d", left / 60, left % 60)
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

/// The day's loose ends: what "Fit my day" would find a time for.
///
/// Deliberately the same rule the server applies, so the button only appears
/// when it would actually do something, and so the count on screen matches
/// what comes back. A habit is a standing commitment and a calendar event is
/// an appointment, so neither is a loose end; a task under way right now is
/// happening, so it is left alone; a task whose slot finished without it being
/// ticked off has slipped and wants a new time.
func looseEnds(_ tasks: [PlannerTask], now: Int?) -> [PlannerTask] {
    tasks.filter { task in
        guard !task.done, !task.habit, !task.fromCalendar else { return false }
        guard task.time != nil else { return true }
        guard let now else { return false }
        return task.clockMinutes + max(task.minutes, 1) <= now
    }
}

/// The day as a plain list, the way Android's list view has it: what is still
/// to do in time order with untimed work last, then what is done.
func dayList(_ tasks: [PlannerTask]) -> (open: [PlannerTask], done: [PlannerTask]) {
    let ordered = tasks.sorted { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) }
    return (ordered.filter { !$0.done }, ordered.filter { $0.done })
}
