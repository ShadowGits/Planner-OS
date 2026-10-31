// The Focus rules, checked against the same cases as Android's FocusPolicyTest.
// Run on any machine with Swift: see apple/README.md.
import Foundation

var failures = 0
func check<T: Equatable>(_ actual: T, _ expected: T, _ label: String, line: Int = #line) {
    if actual != expected { failures += 1; print("FAIL line \(line) \(label): got \(actual), expected \(expected)") }
}

// Saturday 31 October 2026, 13:00 in the workspace zone.
let now = Moment(today: "2026-10-31", minutes: 13 * 60)
func task(_ id: String, date: String? = nil, time: String? = nil, due: String? = nil, starred: Bool = false,
          priority: String? = "medium", milestone: String? = nil, done: Bool = false, habit: Bool = false, minutes: Int = 30) -> PlannerTask {
    PlannerTask(id: id, title: id, time: time, minutes: minutes, done: done, starred: starred, habit: habit,
                date: date, dueDate: due, milestoneId: milestone, priority: priority)
}
let milestones = [
    "shortlist": FocusMilestone(id: "shortlist", name: "Shortlist finalized", targetDate: "2026-11-02"),
    "calculus": FocusMilestone(id: "calculus", name: "Calculus refresh", targetDate: "2027-02-28"),
]

// Reasons match the server Inbox.
check(focusReason(task("a", date: "2026-11-01", due: "2026-09-30"), now), .deadline, "deadline")
check(focusReason(task("b", date: "2026-10-30", time: "21:30"), now), .missedSlot, "missed yesterday")
check(focusReason(task("c", date: "2026-10-31", time: "09:00"), now), .missedSlot, "missed today")
check(focusReason(task("d"), now), .neverScheduled, "never scheduled")
check(focusReason(task("e", date: "2026-10-31", time: "23:00"), now), nil, "later today")
check(focusReason(task("f", date: "2026-10-31"), now), nil, "untimed today")
check(focusReason(task("g", date: "2026-09-30", done: true), now), nil, "done")
check(focusReason(task("h", date: "2026-10-30", time: "07:00", habit: true), now), nil, "habit")

// Ranking: pins, then deadlines, then near milestones, then age.
check(rankOverdue([
    task("old-calculus", due: "2026-09-14", milestone: "calculus"),
    task("cut-list", date: "2026-11-02", due: "2026-10-30", milestone: "shortlist"),
    task("missed", date: "2026-10-03", time: "18:30"),
    task("aps", date: "2026-09-30", due: "2026-09-20", priority: "high"),
    task("idea"),
    task("workout", date: "2026-10-03", time: "18:30", starred: true),
], milestones: milestones, now: now).map { $0.task.id }, ["aps", "workout", "cut-list", "old-calculus", "missed", "idea"], "rank")

// Lateness reads like the web cards.
check(lateness(task("a", due: "2026-09-20"), .deadline, now), "41d late", "days late")
check(lateness(task("b", date: "2026-10-30", time: "21:30"), .missedSlot, now), "Missed Fri 30 Oct 21:30", "missed")
check(lateness(task("c"), .neverScheduled, now), "Never scheduled", "never")
check(milestoneSoon(task("d", milestone: "shortlist"), milestones, now), "milestone in 2d", "soon")
check(milestoneSoon(task("e", milestone: "calculus"), milestones, now), nil, "not soon")

// Today is what is left and not already overdue.
let view = DayView(date: "2026-10-31", items: [
    task("cv", date: "2026-10-31", time: "23:00"),
    task("missed", date: "2026-10-31", time: "09:00"),
    task("finished", date: "2026-10-31", time: "20:00", done: true),
    task("gym", date: "2026-10-31", time: "18:00", habit: true),
    task("anytime", date: "2026-10-31"),
])
let backlog = [task("due-today", due: "2026-10-31"), task("anytime", date: "2026-10-31"), task("late", due: "2026-10-01")]
check(focusToday(view, backlog: backlog, now: now).map(\.id), ["cv", "anytime", "due-today"], "today")

// Moving carries only a broken deadline.
let broken = movedForFocus(task("a", date: "2026-10-03", time: "18:30", due: "2026-09-20"), to: "2026-11-09", today: "2026-10-31")
check(broken.date, "2026-11-09", "moved date"); check(broken.time, nil, "untimed"); check(broken.dueDate, "2026-11-09", "deadline moved")
check(movedForFocus(task("b", date: "2026-10-30", due: "2026-11-30"), to: "2026-11-09", today: "2026-10-31").dueDate, "2026-11-30", "future deadline stays")
check(focusReason(broken, now), nil, "no longer overdue")

// Quick dates collapse on a Saturday.
check(quickMoveDates("2026-10-31").map(\.date), ["2026-10-31", "2026-11-01", "2026-11-02"], "saturday")
check(quickMoveDates("2026-10-28").map(\.date), ["2026-10-28", "2026-10-29", "2026-10-31", "2026-11-02"], "wednesday")

// Week rows follow milestone targets.
let rows = focusWeekRows([
    task("a", date: "2026-10-26", milestone: "calculus"),
    task("b", date: "2026-11-01", milestone: "shortlist"),
    task("c", date: "2026-10-28"),
    task("d", date: "2026-11-05", milestone: "shortlist"),
    task("e", date: "2026-10-29", habit: true),
], weekStart: "2026-10-26", milestones: milestones, projectNames: [:])
check(rows.map(\.label), ["Shortlist finalized", "Calculus refresh", "Other"], "row order")
check(rows[0].cells[6].map(\.id), ["b"], "sunday cell")
check(rows[0].cells.map(\.count).reduce(0, +), 1, "outside the week is left out")
check(Civil.weekStart("2026-11-01"), "2026-10-26", "week start")

// Timeline lanes and drag snapping.
let lanes = timelineLanes([task("x", time: "09:00", minutes: 60), task("y", time: "09:30"), task("z", time: "11:00")])
check(lanes["x"]!.count, 2, "overlap lanes"); check(lanes["y"]!.index, 1, "second lane"); check(lanes["z"]!.count, 1, "own cluster")
check(snappedStart(540, minutes: 30, dragMinutes: 13), 555, "snap to five")
check(snappedStart(1410, minutes: 60, dragMinutes: 100), 1380, "kept in the day")

// Reminders: ten minutes before, future only, soonest first.
let kolkata = TimeZone(identifier: "Asia/Kolkata")!
let noon = Civil.instant("2026-10-31", "13:00", in: kolkata)!
let plan = planReminders([view, DayView(date: "2026-11-01", items: [task("early", date: "2026-11-01", time: "08:00")])], now: noon, timeZone: kolkata)
check(plan.map(\.title), ["gym", "cv", "early"], "reminder order")
check(plan.first?.fire, Civil.instant("2026-10-31", "17:50", in: kolkata), "ten minutes before")

// Decoding the API's shapes.
let json = #"{"success":true,"data":{"date":"2026-10-31","timezone":"Asia/Kolkata","items":[{"id":"t1","title":"CV","start_time":"18:30:00","estimated_minutes":null,"done":false,"is_habit":false,"scheduled_date":"2026-10-31","due_date":null,"notes":""}]}}"#
let decoded = try! JSONDecoder().decode(Envelope<DayView>.self, from: Data(json.utf8)).data
check(decoded.items[0].time, "18:30", "seconds dropped"); check(decoded.items[0].minutes, 30, "null minutes"); check(decoded.items[0].notes, nil, "blank notes")
let triage = #"{"success":true,"data":{"moved":2,"milestones_extended":[{"id":"m","name":"Shortlist","from":"2026-11-02","to":"2026-11-09"}]}}"#
check(milestoneNotes(Data(triage.utf8)), ["\"Shortlist\" now due 9 Nov (was 2 Nov)"], "milestone notes")
check((try? Connection.origin("https://planner.example.com/"))?.absoluteString, "https://planner.example.com", "origin")
check((try? Connection.origin("http://planner.example.com"))?.absoluteString, nil, "https only")
check((try? Connection.origin("https://planner.example.com/app"))?.absoluteString, nil, "no path")

// Timeline layout: gaps, shared edges, heights, icons, colours.
let day = timelineItems([
    task("wake", time: "07:00", minutes: 15), task("yoga", time: "07:15"),
    task("coffee", time: "08:45", minutes: 15), task("anytime"),
])
check(day.map(\.id), ["wake", "yoga", "gap-465", "coffee"], "timeline items")
if case .task(_, let shows) = day[1] { check(shows, false, "shared edge hides the start") }
if case .task(_, let shows) = day[3] { check(shows, true, "after a gap the start shows") }
if case .gap(_, let minutes, let next) = day[2] { check(minutes, 60, "gap length"); check(next, "coffee", "gap leads to") }
check(pillHeight(15), 52, "short task is a circle"); check(pillHeight(30), 72, "30m"); check(pillHeight(600), 216, "capped")
check(durationText(15), "15m", "minutes"); check(durationText(60), "1h", "hour"); check(durationText(90), "1h 30m", "mixed")
check(taskSymbol(task("Wake Up")), "alarm", "wake icon"); check(taskSymbol(task("Bike to Office")), "bicycle", "bike icon")
check(taskSymbol(task("Coffee")), "cup.and.saucer", "coffee icon"); check(taskSymbol(task("Something else")), "checklist", "default icon")
check(paletteIndex(task("Yoga"), count: 8), paletteIndex(task("Yoga"), count: 8), "stable colour")
check(timelineAnchor(day, now: 8 * 60), "coffee", "anchor is next up"); check(timelineAnchor(day, now: nil), "wake", "anchor is first")
check(Civil.clockText(7 * 60, twentyFour: false), "07:00 AM", "12h"); check(Civil.clockText(13 * 60 + 5, twentyFour: false), "01:05 PM", "pm")
check(Civil.clockText(1440, twentyFour: true), "00:00", "midnight"); check(Civil.monthName("2026-05-13"), "May", "month")
check(Civil.weekdayShort("2026-05-13"), "Wed", "weekday")

// Drop maths: a point in the list to a time and back.
let dropDay = timelineItems([task("wake", time: "07:00", minutes: 15), task("yoga", time: "07:15"), task("coffee", time: "08:45", minutes: 15)])
// Rows: wake 0-62, yoga 62-144 (pill 72), gap 144-180 (60m at 0.6 = 36), coffee 180-242.
check(minuteAt(0, in: dropDay), 420, "top of the list is the first start")
check(minuteAt(62 + 5 + 36, in: dropDay), 450, "halfway down a 30-minute capsule is 15 minutes in")
check(minuteAt(144 + 18, in: dropDay), 495, "halfway through an hour of free time")
check(minuteAt(242 + 24, in: dropDay), 550, "below the last task at 2.4 points a minute")
check(minuteAt(-50, in: dropDay), 420, "above the top is the first start")
for minute in stride(from: 420, through: 600, by: 5) {
    check(minuteAt(offsetFor(minute, in: dropDay), in: dropDay), minute, "round trip \(Civil.clock(minute))")
}
check(minuteAt(30, in: []), 555, "an empty day starts from 09:00")
check(dropStart(1430, duration: 60), 1380, "a drop keeps the task inside the day")

print(failures == 0 ? "All policy checks passed" : "\(failures) checks failed")
exit(failures == 0 ? 0 : 1)
