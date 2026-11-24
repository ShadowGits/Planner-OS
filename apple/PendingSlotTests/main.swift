import Foundation

var failures = 0
func check(_ result: Bool, _ label: String) {
    if !result { failures += 1; print("FAIL: \(label)") }
}
let day = "2026-11-24"
let gap = PendingSlot(day: day, start: 571, end: 630)
check(gap.start == 575 && gap.minutes == 55, "round up inside the gap, preserving its end")
let old = PlannerTask(id: "old", title: "Finish proposal", time: "11:00", minutes: 45, date: "2026-11-23", notes: "Keep this")
let long = PlannerTask(id: "long", title: "Long task", minutes: 60, starred: true, date: "2026-11-22")
let undated = PlannerTask(id: "undated", title: "Unscheduled", minutes: 20)
let finished = PlannerTask(id: "done", title: "Done", done: true, date: "2026-11-23")
let habit = PlannerTask(id: "habit:x:2026-11-23", title: "Habit", habit: true, date: "2026-11-23")
let calendar = PlannerTask(id: "calendar", title: "Appointment", date: "2026-11-23", source: "apple_calendar")
let future = PlannerTask(id: "future", title: "Later", time: "15:00", date: day)
let tomorrow = PlannerTask(id: "tomorrow", title: "Tomorrow", date: "2026-11-25")
check(gap.candidates([long, old, old, undated, finished, habit, calendar, future, tomorrow]).map(\.id) == ["old", "undated", "long"], "deduplicate, exclude closed/fixed/future tasks, put fits before starred oversize tasks")
check(gap.accepts(PlannerTask(id: "earlier", title: "Earlier", time: "08:00", date: day)), "a missed same-day slot can be fitted")
check(!gap.accepts(PlannerTask(id: "active", title: "Active", time: "09:00", minutes: 90, date: day)), "an active slot is not previous work")
check(!gap.accepts(PlannerTask(id: "pending:new", title: "Still adding")), "exclude unsaved tasks")
check(gap.fits(old) && !gap.fits(long), "long tasks are not silently shortened")
var worked = long
worked.workedSeconds = 50 * 60
check(!gap.fits(worked), "logged work does not silently resize the planned slot")
let before = PlannerTask(id: "before", title: "Before", time: "09:00", minutes: 35, date: day)
let after = PlannerTask(id: "after", title: "After", time: "10:20", date: day)
check(gap.isFree(for: old, among: [before, after]), "touching edges are allowed")
let blocked = PlannerTask(id: "block", title: "New booking", time: "10:00", done: true, date: day)
check(!gap.isFree(for: old, among: [blocked]), "even a completed booking occupies the gap")
let dueOnly = PlannerTask(id: "due", title: "Due-date booking", time: "10:00", dueDate: day)
check(!gap.isFree(for: old, among: [dueOnly]), "a timed task shown by its due date still occupies the gap")
let overnight = PendingSlot(day: day, start: 1501, end: 1560)
check(overnight.target.date == "2026-11-25" && overnight.target.time == "01:05", "after midnight uses the next calendar date")
let nightBlock = PlannerTask(id: "night", title: "Night booking", time: "01:30", date: "2026-11-25")
check(!overnight.isFree(for: old, among: [nightBlock]), "overnight collision is checked in logical-day coordinates")
check(PendingSlot(day: day, start: 599, end: 600).minutes == 0, "rounding cannot invent room")
print(failures == 0 ? "All pending-slot checks passed" : "\(failures) pending-slot checks failed")
exit(failures == 0 ? 0 : 1)
