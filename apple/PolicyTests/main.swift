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
let rich = #"{"id":"t2","title":"Essay","start_time":"10:00","estimated_minutes":60,"recurrence_key":"weekly-essay","parent_task_id":"whole","parent_title":"Essay","part_index":2,"part_total":3,"worked_seconds":1500,"planned_seconds":3000}"#
let richTask = try! JSONDecoder().decode(PlannerTask.self, from: Data(rich.utf8))
check(richTask.recurrenceKey, "weekly-essay", "repeat key decoded")
check(partText(richTask), "Part 2/3", "parts decoded")
check(richTask.workedSeconds, 1500, "time worked decoded"); check(richTask.remainingSeconds, 1500, "left of the planned time")
check(decoded.items[0].recurrenceKey, nil, "no repeat key"); check(decoded.items[0].workedSeconds, 0, "nothing worked")
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
check(dropStart(1430), 1430, "a drop near midnight stays where it is shown")
check(dropStart(5000), 27 * 60 + 55, "27:55 is the latest start, as on the old timeline")
check(dropStart(-30), 0, "nothing before midnight")
check(dropTarget("2026-05-13", 25 * 60 + 30).date, "2026-05-14", "a drop at 25:30 is on the next date")
check(dropTarget("2026-05-13", 25 * 60 + 30).time, "01:30", "at 01:30")
check(dropTarget("2026-05-13", 22 * 60).date, "2026-05-13", "before midnight it stays on the day")
check(dropTarget("2026-05-13", 22 * 60).time, "22:00", "at the time shown")

// The now bar shows wherever now falls.
let barDay = timelineItems([task("Coffee", time: "15:45", minutes: 15), task("Emails", time: "16:00"), task("Home", time: "17:00")])
check(nowBarOffset(16 * 60 + 10, in: barDay), offsetFor(16 * 60 + 10, in: barDay), "now bar inside a task")
check(nowBarOffset(16 * 60 + 40, in: barDay), offsetFor(16 * 60 + 40, in: barDay), "now bar in free time")
check(nowBarOffset(6 * 60, in: barDay), -12, "now bar before the first task, just above it")
check(nowBarOffset(23 * 60, in: barDay), barDay.reduce(0) { $0 + itemHeight($1) } + 20, "now bar after the last task, just below it")
check(nowBarOffset(-1, in: barDay), nil, "no now bar on a later day")
check(nowBarOffset(Int.max, in: barDay), nil, "no now bar on an earlier day")

// A held task can go until 04:00 the next morning, in the same day.
let night = timelineItems([task("Dinner", time: "20:00", minutes: 60), task("Read", time: "21:30", minutes: 45)])
let nightBottom: Double = night.reduce(0) { $0 + itemHeight($1) }
check(timelineLastEnd(night), 22 * 60 + 15, "the end of the day's tasks")
let nightExpected: Double = Double(timelineLastStart - (22 * 60 + 15)) * 1.6 + pillHeight(60)
check(nightRoom(night, heldMinutes: 60), nightExpected, "room to the latest start at scale, plus the held capsule")
check(nightHours(night), [23 * 60, 24 * 60, 25 * 60, 26 * 60, 27 * 60, 28 * 60], "faint hours from the next whole hour to 04:00")
let halfPastOne: Int = 25 * 60 + 30
let pastEnd: Double = Double(halfPastOne - (22 * 60 + 15)) * 1.6
check(minuteAt(nightBottom + pastEnd, in: night), halfPastOne, "01:30 the next morning is reachable")
check(minuteAt(nightBottom + 5000, in: night), 27 * 60 + 55, "27:55 is the latest start")
check(nightHours(timelineItems([task("Late", time: "22:50", minutes: 15)])), [24 * 60, 25 * 60, 26 * 60, 27 * 60, 28 * 60], "an hour too close to the last task is left out")
check(nightRoom([], heldMinutes: 30), 0, "no room on an empty day")
check(logicalMinutes(Moment(today: "2026-05-14", minutes: 90)), 25 * 60 + 30, "01:30 is 25:30 of the evening's day")
let owl = PlannerTask(id: "owl", title: "Night owl", time: "01:30", minutes: 30, date: "2026-05-14")
check(shown(owl, on: "2026-05-13")?.time, "25:30", "after midnight it stays at the end of the evening's day")
check(shown(owl, on: "2026-05-14")?.time, "01:30", "and is at 01:30 on its own date")
check(shown(owl, on: "2026-05-15") == nil, true, "and on no other day")
var owlListed = owl; owlListed.time = "25:30"
check(shown(owlListed, on: "2026-05-14")?.time, "01:30", "the evening's 25:30 copy is 01:30 on its date")
check(shown(owlListed, on: "2026-05-13")?.time, "25:30", "and stays 25:30 on the evening")
let breakfast = PlannerTask(id: "b", title: "Breakfast", time: "08:00", minutes: 30, date: "2026-05-14")
check(shown(breakfast, on: "2026-05-13") == nil, true, "a morning task is not the evening's")
let listed = DayView(date: "2026-05-13", items: [owlListed]), own = DayView(date: "2026-05-14", items: [owl])
let owlReminders = planReminders([listed, own], now: Civil.instant("2026-05-13", "12:00", in: kolkata)!, timeZone: kolkata)
check(owlReminders.count, 1, "one reminder for a task after midnight, though both days list it")
check(owlReminders.first?.fire, Civil.instant("2026-05-14", "01:20", in: kolkata), "ten minutes before 01:30 on its date")
check(logicalMinutes(Moment(today: "2026-05-14", minutes: 9 * 60)), 9 * 60, "09:00 is 09:00")

// What the old timeline showed on each task, kept.
let piece = PlannerTask(id: "p", title: "Essay", time: "10:00", minutes: 60, parent: "whole", parentTitle: "Essay", partIndex: 2, partCount: 3)
check(partText(piece), "Part 2/3", "a piece of a split task")
check(partText(task("Solo", time: "10:00")), nil, "a whole task has no part")
let studied = PlannerTask(id: "w", title: "Study", time: "10:00", minutes: 60, workedSeconds: 25 * 60)
check(workedText(studied), "25m worked · 35m left", "time worked and left")
var finished = studied; finished.done = true
check(workedText(finished), "25m worked", "just time worked once done")
check(workDuration(3900), "1h 5m", "as Android writes it"); check(workDuration(0), "0m", "nothing yet")
let winA = task("a", time: "09:00", starred: true), winB = task("b", time: "10:00", starred: true, done: true)
check(winsTitle([winA, winB]), "Top Wins · 1 of 2", "Top Wins count")
var wonA = winA; wonA.done = true
check(winsTitle([wonA, winB]), "Day won", "every win done")

// The editor saves only what was changed.
let sop = PlannerTask(id: "sop", title: "Draft SOP", time: "25:30", minutes: 45, date: "2026-05-14", notes: " old ")
let openedFields = EditorFields(title: "Draft SOP", date: "2026-05-14", time: "01:30", minutes: 45, notes: " old ", starred: false)
var renamedFields = openedFields; renamedFields.title = "  Draft SOP for TUM "
let renamedTask = editedTask(sop, from: openedFields, to: renamedFields)
check(renamedTask.title, "Draft SOP for TUM", "a rename saves the trimmed name")
check(renamedTask.time, "25:30", "and leaves the time as the task had it")
check(renamedTask.date, "2026-05-14", "and the date")
check(renamedTask.notes, " old ", "and the notes")
check(renamedTask.minutes, 45, "and the length")
var blankFields = openedFields; blankFields.title = "   "
check(editedTask(sop, from: openedFields, to: blankFields).title, "Draft SOP", "a blank name keeps the old one")
var movedFields = openedFields; movedFields.time = "02:00"
let movedTask = editedTask(sop, from: openedFields, to: movedFields)
check(movedTask.time, "02:00", "a new time is saved"); check(movedTask.date, "2026-05-14", "with the day shown")
var untimedFields = openedFields; untimedFields.date = nil
check(editedTask(sop, from: openedFields, to: untimedFields).time, nil, "no day means no time")
var notedFields = openedFields; notedFields.notes = "  bring CV  "; notedFields.minutes = 60; notedFields.starred = true
let notedTask = editedTask(sop, from: openedFields, to: notedFields)
check(notedTask.notes, "bring CV", "notes trimmed"); check(notedTask.minutes, 60, "length"); check(notedTask.starred, true, "star")
check(notedTask.time, "25:30", "time untouched when only other fields change")

// What the widget is handed, and what it makes of it.
let widgetDay = PlannerSnapshot(
    date: "2026-05-13", updated: Date(),
    tasks: [
        .init(id: "a", title: "Gym", start: 7 * 60, minutes: 60, done: true, palette: 3),
        .init(id: "b", title: "Shortlist", start: 11 * 60, minutes: 90, done: false, palette: 4),
        .init(id: "c", title: "Dinner", start: 20 * 60, minutes: 45, done: false, palette: 0),
        .init(id: "d", title: "Night owl", start: 25 * 60 + 30, minutes: 30, done: false, palette: 6),
    ],
    waiting: 2)
check(widgetDay.current(at: 11 * 60 + 20)?.title, "Shortlist", "the task under way")
check(widgetDay.current(at: 10 * 60) == nil, true, "nothing is under way in a gap")
check(widgetDay.current(at: 7 * 60 + 10) == nil, true, "a finished task is not under way")
check(widgetDay.upcoming(after: 11 * 60 + 20).map(\.title), ["Dinner", "Night owl"], "what is still coming")
check(widgetDay.upcoming(after: 26 * 60), [], "nothing after the last one")
check(widgetDay.remaining, 3, "how many are left")
check(widgetDay.turningPoints(from: 11 * 60 + 20), [12 * 60 + 30, 20 * 60, 20 * 60 + 45, 25 * 60 + 30, 26 * 60],
      "it redraws when something starts or ends, never in between")
check(widgetDay.turningPoints(from: 26 * 60), [], "and not again once the day is done")
let widgetRoundTrip = try! JSONDecoder().decode(
    PlannerSnapshot.self, from: try! JSONEncoder().encode(widgetDay))
check(widgetRoundTrip, widgetDay, "the snapshot survives being written and read")

// Ticking from the widget: its own copy first, so the circle fills at once.
PlannerSnapshot.save(widgetDay)
check(PlannerSnapshot.mark("b", done: true), true, "a task on the widget can be ticked")
check(PlannerSnapshot.load()?.tasks.first { $0.id == "b" }?.done, true, "and it stays ticked")
check(PlannerSnapshot.load()?.remaining, 2, "with one fewer left")
check(PlannerSnapshot.mark("b", done: false), true, "and it can be put back")
check(PlannerSnapshot.load()?.tasks.first { $0.id == "b" }?.done, false, "back to not done")
check(PlannerSnapshot.mark("gone", done: true), false, "a task that is no longer there cannot be ticked")

// What the widget needs to reach the server, and that disconnecting takes it.
WidgetConnection.save(server: "https://planner.example.com", key: "app-secret")
check(WidgetConnection.load()?.server, "https://planner.example.com", "the widget gets the server")
check(WidgetConnection.load()?.key, "app-secret", "and the key")
WidgetConnection.clear()
check(WidgetConnection.load() == nil, true, "disconnecting takes it away")

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
