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

print(failures == 0 ? "All policy checks passed" : "\(failures) checks failed")
exit(failures == 0 ? 0 : 1)
