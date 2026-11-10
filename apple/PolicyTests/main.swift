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

// Tasks at the same time sit side by side, as the old timeline had them.
let clash = timelineItems([task("Standup", time: "11:00", minutes: 30),
                           task("Deep work", time: "11:00", minutes: 120),
                           task("Lunch", time: "13:30", minutes: 45)])
check(clash.map(\.id), ["overlap-660-2", "gap-780", "Lunch"], "two at once become one group")
guard case .overlap(let clashGroup) = clash[0] else { fatalError("expected a group") }
check(clashGroup.columns, 2, "two at once means two columns")
check(clashGroup.start, 11 * 60, "it starts when the first does")
check(clashGroup.end, 13 * 60, "and ends when the last does")
check(Set(clashGroup.placed.map(\.column)), [0, 1], "each keeps its own column")
check(Set(clashGroup.placed.map(\.top)), [0], "both start together, so both sit at the top")
check(clashGroup.placed.first { $0.task.title == "Standup" }?.height, pillHeight(30),
      "a short task is still drawn at least a circle tall")

let reused = timelineItems([task("Standup", time: "11:00", minutes: 30),
                            task("Deep work", time: "11:00", minutes: 120),
                            task("Call", time: "11:45", minutes: 30)])
guard case .overlap(let reusedGroup) = reused[0] else { fatalError("expected a group") }
check(reusedGroup.columns, 2, "the column the short task freed is reused, not a third opened")
check(reusedGroup.placed.first { $0.task.title == "Call" }?.column,
      reusedGroup.placed.first { $0.task.title == "Standup" }?.column, "the call takes the free column")
check(reusedGroup.placed.first { $0.task.title == "Call" }?.top, 45 * 1.6,
      "and sits where its own clock puts it")

let queue = timelineItems([task("A", time: "09:00", minutes: 30), task("B", time: "09:30", minutes: 30)])
check(queue.allSatisfy { if case .task = $0 { return true } else { return false } }, true,
      "back to back is not an overlap: that stays an ordinary row")

// And the clock still reads true across a group, so a drag lands where it looks.
for minute in stride(from: 11 * 60, through: 14 * 60 + 15, by: 5) {
    check(minuteAt(offsetFor(minute, in: clash), in: clash), minute, "round trip at \(columnClock(minute, twentyFour: true))")
}
let clashHeight = itemHeight(clash[0])
check(minuteAt(0, in: clash), 11 * 60, "the group starts where it starts")
check(minuteAt(clashHeight / 2, in: clash), 12 * 60, "and halfway down it is halfway through")
check(timelineAnchor(clash, now: 11 * 60 + 10)?.isEmpty, false, "a task inside a group can still be scrolled to")

// The six the widget shows: what is on now and what follows, ticked or not.
check(widgetDay.window(at: 11 * 60 + 20, count: 6).map(\.title), ["Shortlist", "Dinner", "Night owl"],
      "it starts at the task under way and carries on from there")
check(widgetDay.window(at: 10 * 60, count: 6).map(\.title), ["Shortlist", "Dinner", "Night owl"],
      "in a gap it starts at the next one")
check(widgetDay.window(at: 7 * 60 + 10, count: 2).map(\.title), ["Gym", "Shortlist"],
      "a ticked task still holds its place, so the list does not jump as you tick")
check(widgetDay.window(at: 30 * 60, count: 2).map(\.title), ["Dinner", "Night owl"],
      "once the day has gone it shows the end of it rather than nothing")
check(widgetDay.window(at: 11 * 60, count: 2).map(\.title), ["Shortlist", "Dinner"], "and never more than asked")
check(PlannerSnapshot(date: "2026-05-13", updated: Date(), tasks: [], waiting: 0).window(at: 600, count: 6), [],
      "an empty day has nothing to show")

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


// What Siri is allowed to do, and what it says back. The intents themselves
// are thin wrappers Apple's framework reads; all of this is the part that
// decides, so all of it is checked here.
func spoken(_ id: String, _ start: Int, _ minutes: Int, done: Bool = false) -> PlannerSnapshot.Item {
    PlannerSnapshot.Item(id: id, title: id, start: start, minutes: minutes, done: done, palette: 0)
}
let voiceDay = PlannerSnapshot(date: "2026-11-05", updated: Date(), tasks: [
    spoken("Gym", 7 * 60, 60, done: true),
    spoken("Deep work", 9 * 60, 60),
    spoken("Standup", 11 * 60, 15),
    spoken("Gym kit wash", 19 * 60, 30),
], waiting: 2)

check(PlannerVoice.spokenClock(570), "9:30 am", "says half nine")
check(PlannerVoice.spokenClock(1145), "7:05 pm", "says five past seven")
check(PlannerVoice.spokenClock(720), "12:00 pm", "says noon")
check(PlannerVoice.spokenClock(0), "12:00 am", "says midnight")
check(PlannerVoice.spokenClock(1530), "1:30 am", "a small-hours slot reads as the morning")
check(PlannerVoice.durationSpoken(45), "45 minutes", "minutes only")
check(PlannerVoice.durationSpoken(60), "1 hour", "one hour")
check(PlannerVoice.durationSpoken(150), "2 hours 30 minutes", "hours and minutes")
check(PlannerVoice.clockText(570), "09:30", "writes a time the server takes")
check(PlannerVoice.clockText(1530), "25:30", "and writes a small-hours slot the way the day view does")

// "What am I doing?"
check(PlannerVoice.nowSentence(voiceDay, at: 9 * 60 + 31), "Deep work, 29 minutes left.", "what is under way")
check(PlannerVoice.nowSentence(voiceDay, at: 10 * 60 + 30), "Next is Standup at 11:00 am.", "nothing on, so what is next")
check(PlannerVoice.nowSentence(voiceDay, at: 22 * 60), "Nothing more is scheduled today. 2 tasks are waiting in your inbox.", "past the last task, and owns up to the inbox")
check(PlannerVoice.nowSentence(nil, at: 600), "Nothing on today.", "no snapshot at all")
check(PlannerVoice.nowSentence(PlannerSnapshot(date: "2026-11-05", updated: Date(), tasks: [], waiting: 0), at: 600),
      "Nothing on today.", "an empty day")

// "What's next?" skips whatever is already running.
check(PlannerVoice.nextSentence(voiceDay, at: 9 * 60 + 31), "Next is Standup at 11:00 am.", "next, not now")
check(PlannerVoice.nextSentence(voiceDay, at: 20 * 60), "Nothing more is scheduled today. 2 tasks are waiting in your inbox.", "nothing left to come")

// "How much is left?"
check(PlannerVoice.remainingSentence(voiceDay, at: 600), "3 left, 1 hour 45 minutes of it.", "what is still open")
let allDone = PlannerSnapshot(date: "2026-11-05", updated: Date(), tasks: [spoken("Gym", 420, 60, done: true)], waiting: 0)
check(PlannerVoice.remainingSentence(allDone, at: 600), "Everything is ticked off.", "a finished day")

// Finding the task someone named out loud.
check(PlannerVoice.onlyMatch(voiceDay, matching: "deep work", at: 600)?.id, "Deep work", "a plain name")
check(PlannerVoice.onlyMatch(voiceDay, matching: "DEEP", at: 600)?.id, "Deep work", "case does not matter")
check(PlannerVoice.onlyMatch(voiceDay, matching: "gy", at: 600) == nil, true, "half a word fits two tasks: ask which")
check(PlannerVoice.onlyMatch(voiceDay, matching: "gym", at: 600)?.id, "Gym",
      "but the whole name wins outright, even though it is inside the other one")
check(PlannerVoice.onlyMatch(voiceDay, matching: "yoga", at: 600) == nil, true, "nothing matches")
check(PlannerVoice.candidates(voiceDay, matching: "gym", at: 600).map { $0.id },
      ["Gym kit wash", "Gym"], "open before finished when asked which")
check(PlannerVoice.candidates(voiceDay, matching: "", at: 600).count, 4, "no name offers the whole day")

// A time handed over by Siri, turned into the planner's counting.
var voiceCal = Calendar(identifier: .gregorian)
voiceCal.timeZone = TimeZone(identifier: "UTC")!
func moment(_ text: String) -> Date {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm"; f.timeZone = TimeZone(identifier: "UTC")!
    return f.date(from: text)!
}
check(PlannerVoice.minutes(from: moment("2026-11-05 19:00"), on: "2026-11-05", calendar: voiceCal), 1140, "seven in the evening")
check(PlannerVoice.minutes(from: moment("2026-11-06 01:30"), on: "2026-11-05", calendar: voiceCal), 1530,
      "half one tomorrow is still tonight at 25:30")
check(PlannerVoice.minutes(from: moment("2026-11-06 09:00"), on: "2026-11-05", calendar: voiceCal), 540,
      "but nine tomorrow is just nine")
check(PlannerVoice.dayStamp(moment("2026-11-05 19:00"), calendar: voiceCal), "2026-11-05", "the day it falls on")


// The day's loose ends: the same rule the server uses, so the Fit button only
// shows when it would do something and the count matches what comes back.
let looseDay = [
    task("untimed"),
    task("missed", time: "09:00", minutes: 30),
    task("underway", time: "12:00", minutes: 120),
    task("later", time: "19:00"),
    task("ticked", time: "08:00", done: true),
    task("habit", habit: true),
]
check(looseEnds(looseDay, now: 13 * 60).map { $0.id }, ["untimed", "missed"], "untimed and slipped, nothing else")
check(looseEnds(looseDay, now: nil).map { $0.id }, ["untimed"], "another day has no clock, so only the untimed")
check(looseEnds(looseDay, now: 9 * 60 + 15).map { $0.id }, ["untimed"], "a slot still running has not slipped")
check(looseEnds([], now: 600).isEmpty, true, "an empty day has no loose ends")
check(looseEnds([task("ticked", done: true)], now: 600).isEmpty, true, "a finished task is not a loose end")


// Talking about a set of tasks: "move all the transcript ones to today".
check(PlannerVoice.dayLabel("2026-11-06", today: "2026-11-06"), "today", "today")
check(PlannerVoice.dayLabel("2026-11-07", today: "2026-11-06"), "tomorrow", "tomorrow")
check(PlannerVoice.dayLabel("2026-11-05", today: "2026-11-06"), "yesterday", "yesterday")
check(PlannerVoice.dayLabel("2026-11-30", today: "2026-11-06"), "30 November", "a day further off")
check(PlannerVoice.dayLabel("2027-01-01", today: "2026-12-31"), "tomorrow", "tomorrow over new year")
check(PlannerVoice.dayLabel("nonsense", today: "2026-11-06"), "nonsense", "nothing to read")
check(PlannerVoice.shift("2026-02-28", by: 1), "2026-03-01", "no leap day in 2026")
check(PlannerVoice.shift("2028-02-28", by: 1), "2028-02-29", "but there is in 2028")

// Siri always asks before moving a pile: a misheard word must not move forty.
check(PlannerVoice.moveQuestion(count: 6, to: "today"), "That is 6 tasks. Move them all to today?", "asks first")
check(PlannerVoice.moveQuestion(count: 1, to: "tomorrow"), "Move 1 task to tomorrow?", "asks about one")
check(PlannerVoice.movedSentence(count: 6, to: "today"), "Moved 6 tasks to today.", "says what it did")
check(PlannerVoice.movedSentence(count: 1, to: "today"), "Moved 1 task to today.", "and for one")
check(PlannerVoice.foundSentence(count: 6, total: 6, query: "transcripts"), "6 tasks match transcripts.", "what was found")
check(PlannerVoice.foundSentence(count: 1, total: 1, query: "APS"), "1 task matches APS.", "just the one")
check(PlannerVoice.foundSentence(count: 0, total: 0, query: "yoga"), "Nothing matches yoga.", "nothing found")
check(PlannerVoice.foundSentence(count: 50, total: 588, query: "study"), "50 tasks match study, out of 588.",
      "owns up to showing only some")

// How each task reads in a list Siri puts on screen.
check(PlannerVoice.describe(VoiceTask(id: "a", title: "A", date: "2026-11-06", time: "09:30"), today: "2026-11-06"),
      "today, 9:30 am", "today at a time")
check(PlannerVoice.describe(VoiceTask(id: "b", title: "B", date: "2026-11-30"), today: "2026-11-06"),
      "30 November", "a day with no time")
check(PlannerVoice.describe(VoiceTask(id: "c", title: "C"), today: "2026-11-06"), "No date yet", "nothing set")
check(PlannerVoice.describe(VoiceTask(id: "d", title: "D", date: "2026-11-06", done: true), today: "2026-11-06"),
      "Done", "already finished")

// Reading the server's own task shape, the one search returns.
let searchRow: [String: Any] = ["id": "t1", "title": "Order transcripts", "scheduled_date": "2026-11-30",
                                "start_time": "09:30:00", "estimated_minutes": 45, "status": "todo"]
let fromRow = VoiceTask(row: searchRow)
check(fromRow?.id, "t1", "the id")
check(fromRow?.title, "Order transcripts", "the name")
check(fromRow?.date, "2026-11-30", "the planned day")
check(fromRow?.minutes, 45, "how long")
check(fromRow?.done, false, "still open")
check(VoiceTask(row: ["id": "t2", "title": "Sorted", "status": "done"])?.done, true, "a finished one")
check(VoiceTask(row: ["id": "t3", "title": "Skipped", "status": "skipped"])?.done, true, "a dropped one counts as closed")
check(VoiceTask(row: ["id": "t4", "title": "Bare"])?.minutes, 30, "no duration given")
check(VoiceTask(row: ["id": "t5", "title": "Due only", "due_date": "2026-12-15"])?.date, "2026-12-15",
      "a deadline stands in for a planned day")
check(VoiceTask(row: ["title": "No id"]) == nil, true, "a row with no id is refused")
check(VoiceTask(row: ["id": "t6"]) == nil, true, "and so is one with no name")
check(PlannerVoice.parseClock("09:30:00"), 570, "reads the server's clock")
check(PlannerVoice.parseClock("25:30"), 1530, "and a small-hours one")
check(PlannerVoice.parseClock(nil) == nil, true, "no time at all")

// 6 November: nothing scheduled, twenty overdue. "Nothing on today" alone
// was true and still the wrong answer.
let emptyButBehind = PlannerSnapshot(date: "2026-11-06", updated: Date(), tasks: [], waiting: 20)
check(PlannerVoice.nowSentence(emptyButBehind, at: 600), "Nothing on today. 20 tasks are waiting in your inbox.", "an empty day with a backlog")
check(PlannerVoice.remainingSentence(emptyButBehind, at: 600), "Nothing on today. 20 tasks are waiting in your inbox.", "and when asked what is left")
check(PlannerVoice.nextSentence(emptyButBehind, at: 600), "Nothing more is scheduled today. 20 tasks are waiting in your inbox.", "and when asked what is next")
let oneBehind = PlannerSnapshot(date: "2026-11-06", updated: Date(), tasks: [], waiting: 1)
check(PlannerVoice.nowSentence(oneBehind, at: 600), "Nothing on today. 1 task is waiting in your inbox.", "just the one waiting")
check(PlannerVoice.nowSentence(PlannerSnapshot(date: "2026-11-06", updated: Date(), tasks: [], waiting: 0), at: 600),
      "Nothing on today.", "a genuinely clear slate says only that")
check(PlannerVoice.remainingSentence(allDone, at: 600), "Everything is ticked off.", "a finished day with an empty inbox")

// Today as a list — the shape of 6 November: seven habits, twenty waiting.
let friday = PlannerSnapshot(date: "2026-11-06", updated: Date(), tasks: [
    spoken("Gym", 17 * 60 + 30, 90),
    spoken("Skin care and health", 3 * 60, 30, done: true),
    spoken("Shower and skin care", 11 * 60, 30),
    spoken("IELTS prep", 12 * 60, 60),
    spoken("Reading", 16 * 60, 60),
    spoken("Talk to mom", 22 * 60 + 30, 30),
    spoken("Research internship search", 23 * 60, 60),
], waiting: 20)
let at1230 = PlannerVoice.todayRows(friday, at: 12 * 60 + 30)
check(at1230.count, 7, "every habit is on the list, not only the current one")
check(at1230.map { $0.title }, ["Skin care and health", "Shower and skin care", "IELTS prep", "Reading", "Gym",
                                "Talk to mom", "Research internship search"], "in time order")
check(at1230.map { $0.state }, [.done, .missed, .now, .next, .later, .later, .later], "each marked")
check(at1230[0].time, "3:00 am", "times read like a clock")
check(at1230[4].time, "5:30 pm", "an evening time")
check(PlannerVoice.todaySummary(friday, at: 12 * 60 + 30),
      "7 on today, 1 done. Now: IELTS prep. 20 tasks are waiting in your inbox.", "the line said above the list")
check(PlannerVoice.todaySummary(friday, at: 14 * 60),
      "7 on today, 1 done. Next: Reading at 4:00 pm. 20 tasks are waiting in your inbox.", "nothing under way, so what is next")
check(PlannerVoice.todayRows(nil, at: 600).isEmpty, true, "no copy, no rows")
check(PlannerVoice.todaySummary(emptyButBehind, at: 600), "Nothing on today. 20 tasks are waiting in your inbox.",
      "an empty day still owns up to the inbox")

// The copy the app left must be today's, or it is not believed.
check(PlannerVoice.isFresh(friday, today: "2026-11-06"), true, "today's copy is believed")
check(PlannerVoice.isFresh(friday, today: "2026-11-07"), false, "yesterday's copy is not")
check(PlannerVoice.isFresh(nil, today: "2026-11-06"), false, "nor is no copy at all")
check(PlannerVoice.logicalDay(moment("2026-11-07 01:30"), calendar: voiceCal), "2026-11-06",
      "half past one at night is still the evening before")
check(PlannerVoice.logicalDay(moment("2026-11-07 04:00"), calendar: voiceCal), "2026-11-07", "four is the new day")
check(PlannerVoice.logicalMinute(moment("2026-11-07 01:30"), calendar: voiceCal), 25 * 60 + 30,
      "and counts as 25:30, after the evening's tasks")
check(PlannerVoice.logicalMinute(moment("2026-11-06 17:30"), calendar: voiceCal), 17 * 60 + 30, "a daytime minute")

// The server's day, read into the same shape.
let serverDay: [String: Any] = ["date": "2026-11-06", "items": [
    ["id": "habit:gym:2026-11-06", "title": "Gym", "start_time": "17:30:00", "estimated_minutes": 90, "done": false],
    ["id": "t1", "title": "Untimed", "start_time": NSNull(), "done": false],
    ["id": "t2", "title": "Late", "start_time": "25:30:00", "done": true],
    ["title": "No id", "start_time": "09:00:00"],
]]
let fromServer = PlannerVoice.snapshot(fromDay: serverDay, waiting: 20)
check(fromServer?.date, "2026-11-06", "the day the server answered for")
check(fromServer?.tasks.map { $0.id }, ["habit:gym:2026-11-06", "t2"], "timed items only, habits included")
check(fromServer?.tasks.first?.start, 17 * 60 + 30, "the habit's time")
check(fromServer?.tasks.last?.start, 25 * 60 + 30, "a small-hours slot kept as tonight")
check(fromServer?.tasks.last?.done, true, "ticked state")
check(fromServer?.waiting, 20, "the inbox count carried over")
check(fromServer?.tasks.first?.palette, PlannerVoice.paletteSlot("Gym"), "the timeline's colour")
check(PlannerVoice.paletteSlot("Yoga"), paletteIndex(task("Yoga"), count: 8), "the same colour rule as the app")
check(PlannerVoice.snapshot(fromDay: ["items": []], waiting: 0) == nil, true, "no date, no day")

// Adding a task said out loud: "add call Shashank sir tomorrow at 2pm".
for (said, minutes) in [("14:00", 840), ("2 pm", 840), ("2pm", 840), ("2:30pm", 870), ("2:30 p.m.", 870),
                        ("12 pm", 720), ("12am", 0), ("noon", 720), ("midnight", 0), ("09:05", 545), ("9", 540)] {
    check(PlannerVoice.parseSpokenTime(said), minutes, "reads \(said)")
}
for bad in ["", "13pm", "0am", "25:00", "9:75", "later", "2:3:4", nil] as [String?] {
    check(PlannerVoice.parseSpokenTime(bad) == nil, true, "refuses \(bad ?? "nothing")")
}
// Both halves optional, as asked: a day only fills the date and leaves the time empty.
let slotToday = "2026-11-10"
check(PlannerVoice.taskSlot(day: "2026-11-11", time: 840, today: slotToday, nowMinute: 600).date, "2026-11-11", "day and time: the day")
check(PlannerVoice.taskSlot(day: "2026-11-11", time: 840, today: slotToday, nowMinute: 600).time, "14:00", "day and time: the time")
check(PlannerVoice.taskSlot(day: "2026-11-11", time: nil, today: slotToday, nowMinute: 600).date, "2026-11-11", "a day alone: that day")
check(PlannerVoice.taskSlot(day: "2026-11-11", time: nil, today: slotToday, nowMinute: 600).time == nil, true, "a day alone: no time")
check(PlannerVoice.taskSlot(day: nil, time: nil, today: slotToday, nowMinute: 600).date, slotToday, "neither: today")
check(PlannerVoice.taskSlot(day: nil, time: nil, today: slotToday, nowMinute: 600).time == nil, true, "neither: no time")
check(PlannerVoice.taskSlot(day: nil, time: 840, today: slotToday, nowMinute: 600).date, slotToday, "a time alone: today")
check(PlannerVoice.taskSlot(day: nil, time: 60, today: slotToday, nowMinute: 21 * 60).date, "2026-11-11",
      "1 am said in the evening means tonight, on tomorrow's date")
check(PlannerVoice.taskSlot(day: nil, time: 60, today: slotToday, nowMinute: 24 * 60 + 30).date, "2026-11-11",
      "and said after midnight, still the coming small hours")
check(PlannerVoice.addedSentence("Call Shashank sir", date: "2026-11-11", time: "14:00", today: slotToday),
      "Added Call Shashank sir tomorrow at 2:00 pm.", "says what it added and when")
check(PlannerVoice.addedSentence("Transcripts", date: "2026-11-11", time: nil, today: slotToday),
      "Added Transcripts tomorrow, with no set time.", "and says when there is no time")
check(PlannerVoice.addedSentence("APS", date: "2026-11-30", time: nil, today: slotToday),
      "Added APS on 30 November, with no set time.", "a day further off")

print(failures == 0 ? "All policy checks passed" : "\(failures) checks failed")
exit(failures == 0 ? 0 : 1)
