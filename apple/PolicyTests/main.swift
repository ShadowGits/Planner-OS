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
check(pillHeight(15), 48, "a 15-minute task is a circle"); check(pillHeight(120), 192, "two hours is about 190 pt"); check(pillHeight(900), 640, "capped")
check(gapHeight(15), 16, "a few minutes is a short piece of spine"); check(gapHeight(60), 96, "free time keeps the scale"); check(gapHeight(600), 104, "a long window is capped")
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
// Rows: wake 0-56, yoga 56-112, an hour of free time 112-208, coffee 208-264.
check(minuteAt(0, in: dropDay), 420, "top of the list is the first start")
check(minuteAt(56 + 4 + 24, in: dropDay), 450, "halfway down a 30-minute capsule is 15 minutes in")
check(minuteAt(112 + 48, in: dropDay), 495, "halfway through an hour of free time")
check(minuteAt(264 + 16, in: dropDay), 550, "below the last task at 1.6 points a minute")
check(minuteAt(-50, in: dropDay), 390, "above the top is earlier, at scale")
for minute in stride(from: 420, through: 600, by: 5) {
    check(minuteAt(offsetFor(minute, in: dropDay), in: dropDay), minute, "round trip \(Civil.clock(minute))")
}
check(minuteAt(30, in: []), 560, "an empty day starts from 09:00")
check(dropStart(1430, duration: 60), 1380, "a drop keeps the task inside the day")

// Capsules fill by time; words match Structured.
let emails = task("Emails", time: "16:00", minutes: 30)
check(taskPhase(emails, now: 15 * 60), .upcoming, "ahead of now")
check(taskPhase(emails, now: 16 * 60 + 1), .underway, "under way")
check(taskProgress(emails, now: 16 * 60 + 15), 0.5, "half done")
check(taskPhase(emails, now: 17 * 60), .past, "passed")
var ticked = emails; ticked.done = true
check(taskPhase(ticked, now: 15 * 60), .done, "done")
check(remainingText(emails, now: 16 * 60 + 1), "29m remaining", "remaining")
check(taskPhase(emails, now: nowOnDay("2026-05-12", today: "2026-05-13", minutes: 600)), .past, "an earlier day has all passed")
check(taskPhase(emails, now: nowOnDay("2026-05-14", today: "2026-05-13", minutes: 600)), .upcoming, "a later day is all ahead")
check(rangeText(420, 435, twentyFour: false), "7:00–7:15 AM", "range"); check(rangeText(690, 735, twentyFour: false), "11:30 AM–12:15 PM", "across noon")
check(rangeText(420, 435, twentyFour: true), "07:00–07:15", "24-hour range")
check(durationWords(15), "15 min", "words"); check(durationWords(60), "1 hr", "hour words"); check(durationWords(90), "1 hr, 30 min", "mixed words")
check(fullClock(16 * 60 + 15, twentyFour: false), "4:15 PM", "drag label")
check(hourMarks(task("Blog", time: "13:30", minutes: 120)), [14 * 60, 15 * 60], "whole hours inside a long task")
var colourHash: UInt64 = 5381
for scalar in "Yoga".unicodeScalars { colourHash = (colourHash &* 33) &+ UInt64(scalar.value) }
check(paletteIndex(task("Yoga"), count: 8), Int(colourHash % 8), "same colour hash as Android")

print(failures == 0 ? "All policy checks passed" : "\(failures) checks failed")
exit(failures == 0 ? 0 : 1)
