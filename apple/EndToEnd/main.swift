// The iPhone/iPad/Mac app's store against a running Planner OS API: every
// action the screens offer, checked on screen (the store) and on the server.
// Start the API first (python3 e2e/server.py 8765), then see e2e/run.sh.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

var failures = 0
func check<T: Equatable>(_ actual: T, _ expected: T, _ label: String, line: Int = #line) {
    if actual == expected { print("  ok   \(label)") } else { failures += 1; print("  FAIL \(label): got \(actual), expected \(expected) (line \(line))") }
}

@MainActor
func run() async {
    let base = URL(string: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "http://127.0.0.1:8765")!
    let connection = Connection(base: base, key: "app-secret")
    let server = PlannerAPI(connection: connection)
    let store = PlannerStore(connection: connection)
    let today = store.logicalToday
    let tomorrow = Civil.add(today, days: 1)

    func settle() async {
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if store.writesInFlight == 0 && store.busy.isEmpty { return }
        }
        failures += 1; print("  FAIL writes never finished")
    }
    func serverDay(_ date: String) async -> [PlannerTask] {
        ((try? await server.get("/v2/day?date=\(date)") as DayView)?.items) ?? []
    }
    func onScreen(_ title: String, _ date: String = today) -> PlannerTask? { store.days[date]?.items.first { $0.title == title } }
    func onServer(_ title: String, _ date: String = today) async -> PlannerTask? { await serverDay(date).first { $0.title == title } }

    print("Add")
    check(await store.create(title: "Yoga", date: today, time: "07:15", minutes: 30, notes: nil, starred: false), true, "add a timed task")
    check(await store.create(title: "Coffee", date: today, time: "08:45", minutes: 15, notes: "oat milk", starred: true), true, "add a starred task with notes")
    check(await store.create(title: "Read", date: today, time: nil, minutes: 20, notes: nil, starred: false), true, "add an untimed task")
    check(await store.create(title: "Someday idea", date: nil, time: nil, minutes: 30, notes: nil, starred: false), true, "add an undated task")
    await store.loadDay(today)
    check(onScreen("Yoga")?.time, "07:15", "new task is on screen")
    check(await onServer("Coffee")?.starred, true, "star saved on create")
    check(await onServer("Coffee")?.notes, "oat milk", "notes saved on create")

    print("Drag on the timeline")
    let yoga = onScreen("Yoga")!
    store.rescheduleNow(yoga, date: today, start: 10 * 60)
    check(onScreen("Yoga")?.time, "10:00", "moves at once, in the same frame as the drop")
    await settle()
    check(onScreen("Yoga")?.time, "10:00", "stays at the new time after saving and refreshing")
    check(await onServer("Yoga")?.time, "10:00", "server has the new time")
    check(timelineItems(store.days[today]?.items ?? []).map(\.id).last, yoga.id, "timeline order follows the new time")

    print("Tick, untick, star")
    let coffee = onScreen("Coffee")!
    await store.setDone(coffee)
    check(onScreen("Coffee")?.done, true, "ticked on screen")
    check(await onServer("Coffee")?.done, true, "ticked on server")
    await store.setDone(onScreen("Coffee")!, false)
    check(await onServer("Coffee")?.done, false, "unticked on server")
    await store.toggleStar(onScreen("Coffee")!)
    check(await onServer("Coffee")?.starred, false, "unstarred on server")

    print("Edit")
    var edited = onScreen("Yoga")!
    edited.title = "Yoga flow"; edited.minutes = 45; edited.notes = "mat"
    check(await store.update(onScreen("Yoga")!, to: edited), true, "save an edit")
    let flow = await onServer("Yoga flow")
    check(flow?.minutes, 45, "duration saved"); check(flow?.notes, "mat", "notes saved"); check(flow?.time, "10:00", "time kept")
    var unscheduled = onScreen("Yoga flow")!
    unscheduled.time = nil
    check(await store.update(onScreen("Yoga flow")!, to: unscheduled), true, "clear the time")
    check(await onServer("Yoga flow")?.time, nil, "time cleared on server")

    print("Focus: move and drop")
    await store.move([onScreen("Read")!], to: tomorrow)
    check(onScreen("Read"), nil, "moved task leaves today")
    check(await onServer("Read", tomorrow)?.date, tomorrow, "server has it tomorrow")
    await store.refreshInbox()
    let idea = store.inbox?.items.first { $0.title == "Someday idea" }
    check(idea != nil, true, "undated task is in the inbox")
    if let idea {
        check(store.focusOverdue.contains { $0.task.id == idea.id }, true, "and on Focus as never scheduled")
        await store.drop([idea])
        await store.refreshInbox()
        check(store.inbox?.items.contains { $0.id == idea.id }, false, "dropped task leaves the inbox")
    }

    print("A failed save puts the task back")
    let gone = onScreen("Coffee")!
    _ = try? await server.send("DELETE", PlannerAPI.taskPath(gone.id))
    store.rescheduleNow(gone, date: today, start: 12 * 60)
    await settle()
    check(onScreen("Coffee")?.time ?? "gone", "gone", "a task deleted elsewhere is gone after the failed move")

    // The test server delays every write by 0.4s, like a phone network.
    func letItStart() async { for _ in 0..<5 { await Task.yield() } }

    print("Instant on screen, saved in the background")
    let adding = Task { await store.create(title: "Quick", date: today, time: "16:00", minutes: 15, notes: nil, starred: false) }
    await letItStart()
    check(onScreen("Quick") != nil, true, "a new task shows before the server answers")
    check(onScreen("Quick")?.id.hasPrefix("pending:"), true, "under a temporary id")
    check(await onServer("Quick") == nil, true, "while the server has not saved it yet")
    _ = await adding.value
    check(onScreen("Quick")?.id.hasPrefix("pending:"), false, "then it takes the server's id")
    check(await onServer("Quick") != nil, true, "and the server has it")
    let ticking = Task { await store.setDone(onScreen("Quick")!) }
    await letItStart()
    check(onScreen("Quick")?.done, true, "a tick shows before the server answers")
    check(await onServer("Quick")?.done, false, "while the server is still saving it")
    await ticking.value
    check(await onServer("Quick")?.done, true, "then the server has it")

    print("A refused change is undone, with a message")
    store.toast = nil
    var tooLong = onScreen("Quick")!
    tooLong.minutes = 5000
    let refusing = Task { await store.update(onScreen("Quick")!, to: tooLong) }
    await letItStart()
    check(onScreen("Quick")?.minutes, 5000, "shows at once")
    _ = await refusing.value
    check(onScreen("Quick")?.minutes, 15, "undone when the server refuses it")
    check(store.toast?.hasPrefix("Couldn't save “Quick”") ?? false, true, "with a message saying what could not be saved")
    print("    message: \(store.toast ?? "none")")

    print("Delete")
    check(await store.delete(onScreen("Yoga flow")!), true, "delete")
    check(await onServer("Yoga flow"), nil, "deleted on server")

    print("Reminders")
    check(await store.create(title: "Call", date: tomorrow, time: "09:00", minutes: 15, notes: nil, starred: false), true, "add tomorrow's call")
    let zone = TimeZone(identifier: "Asia/Kolkata")!
    let plan = planReminders([DayView(date: tomorrow, items: await serverDay(tomorrow))], now: Date(), timeZone: zone)
    check(plan.first?.fire, Civil.instant(tomorrow, "08:50", in: zone), "reminder 10 minutes before, from server data")

    print(failures == 0 ? "iPhone app store: all end-to-end checks passed" : "iPhone app store: \(failures) checks failed")
}

await run()
exit(failures == 0 ? 0 : 1)
