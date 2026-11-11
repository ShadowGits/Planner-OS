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

    print("Drag past midnight, in the same day")
    check(await store.create(title: "Night owl", date: today, time: "22:00", minutes: 30, notes: nil, starred: false), true, "add a late task")
    await store.loadDay(today)
    store.rescheduleNow(onScreen("Night owl")!, date: today, start: 25 * 60 + 30)
    check(onScreen("Night owl")?.time, "25:30", "stays in the evening's list at once, after midnight")
    await settle()
    check(onScreen("Night owl")?.time, "25:30", "and after saving and refreshing")
    check(await onServer("Night owl", tomorrow)?.time, "01:30", "saved at 01:30")
    check(await onServer("Night owl", tomorrow)?.date, tomorrow, "on the next date")
    check(await onServer("Night owl")?.time, "25:30", "which the server lists on the evening as 25:30")
    await store.toggleStar(onScreen("Night owl")!)
    check(onScreen("Night owl")?.time, "25:30", "starring it keeps it on the evening")

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

    print("Rename from the editor")
    check(await store.create(title: "Draft SOP", date: today, time: "11:00", minutes: 45, notes: nil, starred: false), true, "add a task to rename")
    await store.loadDay(today)
    let sopTask = onScreen("Draft SOP")!
    let sopOpened = EditorFields(title: "Draft SOP", date: today, time: "11:00", minutes: 45, notes: "", starred: false)
    var sopRenamed = sopOpened; sopRenamed.title = "Draft SOP for TUM"
    check(await store.update(sopTask, to: editedTask(sopTask, from: sopOpened, to: sopRenamed)), true, "save the new name")
    check(onScreen("Draft SOP for TUM")?.time, "11:00", "renamed on screen, same time")
    await settle()
    check(onScreen("Draft SOP for TUM") != nil, true, "still renamed after saving and refreshing")
    check(await onServer("Draft SOP for TUM")?.time, "11:00", "server has the new name at the same time")
    check(await onServer("Draft SOP") == nil, true, "and not the old one")

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

    print("What the widget is left")
    store.publishWidget()
    let onWidget = PlannerSnapshot.load()
    check(onWidget?.date, today, "the widget gets today, by the planner's day")
    check(onWidget?.tasks.contains { $0.title == "Quick" }, true, "with today's timed tasks on it")
    check(onWidget?.tasks.allSatisfy { $0.palette >= 0 && $0.palette < 8 }, true, "each in a real colour slot")
    check(onWidget?.tasks.contains { $0.title == "Read" }, false, "and nothing moved to another day")

    print("Ticking a task off from the widget")
    store.publishWidget()
    let widgetTask = PlannerSnapshot.load()?.tasks.first { $0.title == "Quick" }
    check(widgetTask != nil, true, "the task is on the widget")
    if let widgetTask {
        check(PlannerSnapshot.mark(widgetTask.id, done: true), true, "the widget ticks it at once")
        check(PlannerSnapshot.load()?.tasks.first { $0.id == widgetTask.id }?.done, true, "and shows it ticked")
        do {
            try await PlannerWidgetAPI.setDone(widgetTask.id, true)
            check(await onServer("Quick")?.done, true, "and the server has it too")
        } catch {
            failures += 1
            print("  FAIL the widget could not tell the server: \(error)")
        }
        // Putting it back has to work the same way, or an accidental tap sticks.
        try? await PlannerWidgetAPI.setDone(widgetTask.id, false)
        check(await onServer("Quick")?.done, false, "and it can be put back")

        // A task that has gone: the widget takes its own tick back rather than
        // sitting there showing something that never happened.
        WidgetConnection.save(server: base.absoluteString, key: "wrong-key")
        PlannerSnapshot.mark(widgetTask.id, done: true)
        do {
            try await PlannerWidgetAPI.setDone(widgetTask.id, true)
            failures += 1; print("  FAIL a refused tick looked like it worked")
        } catch {
            PlannerSnapshot.mark(widgetTask.id, done: false)
            check(PlannerSnapshot.load()?.tasks.first { $0.id == widgetTask.id }?.done, false,
                  "a refused tick is taken back")
        }
        WidgetConnection.save(server: base.absoluteString, key: connection.key)
    }

    print("A tick on the widget does not wait for the server")
    if let quick = await serverDay(today).first(where: { !$0.done && $0.time != nil }) {
        PendingTicks.clear()
        // What the widget's button does: its own copy, a note, and done.
        PlannerSnapshot.mark(quick.id, done: true)
        PendingTicks.add(quick.id, done: true)
        check(PlannerSnapshot.load()?.tasks.first { $0.id == quick.id }?.done, true, "the widget shows it ticked before anything is sent")
        check(await serverDay(today).first { $0.id == quick.id }?.done, false, "and the server has not heard yet")
        check(await PendingTicks.flush(), false, "sending it takes nothing back")
        check(await serverDay(today).first { $0.id == quick.id }?.done, true, "then the server has it")
        check(PendingTicks.all().isEmpty, true, "and it is crossed off the waiting list")

        // No answer from the server: the tick is kept and still shown.
        PlannerSnapshot.mark(quick.id, done: false)
        PendingTicks.add(quick.id, done: false)
        WidgetConnection.save(server: "http://127.0.0.1:9", key: connection.key)
        _ = await PendingTicks.flush()
        check(PendingTicks.all().map(\.id), [quick.id], "with no answer the tick waits instead of being lost")
        check(PlannerSnapshot.load()?.tasks.first { $0.id == quick.id }?.done, false, "and the widget keeps showing it")
        // The app reading the server meanwhile must not undo it on the widget.
        WidgetConnection.save(server: base.absoluteString, key: connection.key)
        await store.refreshAll(quiet: true)
        check(await serverDay(today).first { $0.id == quick.id }?.done, false, "the app sends it the next time it reads")
        check(PendingTicks.all().isEmpty, true, "and the list is empty again")

        // The server says no: taken back, not retried for ever.
        PlannerSnapshot.mark(quick.id, done: true)
        PendingTicks.add(quick.id, done: true)
        WidgetConnection.save(server: base.absoluteString, key: "wrong-key")
        check(await PendingTicks.flush(), true, "a refused tick reports that it was taken back")
        check(PlannerSnapshot.load()?.tasks.first { $0.id == quick.id }?.done, false, "the widget shows it unticked again")
        check(PendingTicks.all().isEmpty, true, "and it is not tried again")
        WidgetConnection.save(server: base.absoluteString, key: connection.key)
    } else { failures += 1; print("  FAIL no open timed task to tick") }

    print("A change made elsewhere reaches a window left open")
    check(await store.create(title: "From the phone", date: today, time: "14:00", minutes: 30, notes: nil, starred: false), true, "add a task")
    await settle()
    let elsewhere = await onServer("From the phone")!
    // As the phone would: straight to the server, with this store none the wiser.
    _ = try? await server.send("PATCH", PlannerAPI.taskPath(elsewhere.id), body: ["title": "Renamed on the phone"])
    check(onScreen("From the phone") != nil, true, "the open window still shows the old name")

    // Not yet: a window that has just read is not re-read every minute.
    await store.refreshIfStale(after: 600)
    check(onScreen("From the phone") != nil, true, "a fresh window is left alone")

    // Once it is stale, it catches up without being touched.
    await store.refreshIfStale(after: 0)
    check(onScreen("Renamed on the phone") != nil, true, "a stale window re-reads and catches up")
    check(onScreen("From the phone"), nil, "and drops what it was showing")

    print("Reminders")
    check(await store.create(title: "Call", date: tomorrow, time: "09:00", minutes: 15, notes: nil, starred: false), true, "add tomorrow's call")
    let zone = TimeZone(identifier: "Asia/Kolkata")!
    let plan = planReminders([DayView(date: tomorrow, items: await serverDay(tomorrow))], now: Date(), timeZone: zone)
    check(plan.first { $0.title == "Call" }?.fire, Civil.instant(tomorrow, "08:50", in: zone), "reminder 10 minutes before, from server data")
    // From noon of the evening's day, so the check does not depend on when it runs.
    let both = planReminders([DayView(date: today, items: await serverDay(today)), DayView(date: tomorrow, items: await serverDay(tomorrow))],
                             now: Civil.instant(today, "12:00", in: zone)!, timeZone: zone)
    check(both.filter { $0.title == "Night owl" }.map(\.fire), [Civil.instant(tomorrow, "01:20", in: zone)!], "one reminder after midnight, at its real time")

    // A day well ahead, so the clock has no say and nothing above is on it.
    let fitDay = Civil.add(today, days: 5)
    let moveDay = Civil.add(today, days: 6)

    print("Fit the day, from the app")
    check(await store.create(title: "Appointment", date: fitDay, time: "07:00", minutes: 60, notes: nil, starred: false), true, "add something fixed")
    check(await store.create(title: "Loose end", date: fitDay, time: nil, minutes: 30, notes: nil, starred: false), true, "add a task with no time")
    await settle()
    store.selectedDate = fitDay
    await store.loadDay(fitDay)
    check(looseEnds(store.days[fitDay]?.items ?? [], now: nil).map(\.title), ["Loose end"], "the button would say one")
    store.toast = nil
    await store.fitDay()
    await settle()
    check(await onServer("Loose end", fitDay)?.time, "08:00", "the server gave it the first time that does not clash")
    check(onScreen("Loose end", fitDay)?.time, "08:00", "and the screen shows it without being asked")
    check(await onServer("Appointment", fitDay)?.time, "07:00", "what was already there did not move")
    check(store.toast, "Moved Loose end to 8:00 am.", "and it says what it did, in the server's words")
    check(looseEnds(store.days[fitDay]?.items ?? [], now: nil).isEmpty, true, "nothing is left to fit")
    store.selectedDate = today

    print("What Siri does, against the server")
    WidgetConnection.save(server: base.absoluteString, key: connection.key)
    do {
        let timed = try await PlannerVoiceAPI.create(title: "Call Shashank sir", on: moveDay, at: 14 * 60, lasting: 45)
        check(timed.title, "Call Shashank sir", "a task said with a day and a time is added")
        check(await onServer("Call Shashank sir", moveDay)?.time, "14:00", "at that time")
        check(await onServer("Call Shashank sir", moveDay)?.minutes, 45, "for that long")

        let untimed = try await PlannerVoiceAPI.create(title: "Sort the transcripts", on: moveDay, at: nil, lasting: nil)
        let saved = await onServer("Sort the transcripts", moveDay)
        check(saved != nil, true, "a task said with only a day lands on that day")
        check(saved?.time, nil, "with no time filled in")

        let found = try await PlannerVoiceAPI.search("TRANSCRIPT")
        check(found.tasks.map(\.title), ["Sort the transcripts"], "search finds a task by part of its name, whatever the case")
        check(found.tasks.first?.date, moveDay, "and knows its day, though it is not today")
        check(found.total, 1, "and how many there are in all")
        check((try await PlannerVoiceAPI.search("no such thing")).tasks.isEmpty, true, "nothing matching finds nothing")

        let open = try await PlannerVoiceAPI.openTasks()
        check(open.contains { $0.id == untimed.id } && open.contains { $0.id == timed.id }, true,
              "the list Siri chooses from has tasks from other days")
        check(open.contains { $0.done }, false, "and nothing already finished")

        let landing = Civil.add(today, days: 7)
        check(try await PlannerVoiceAPI.move(found.tasks.map(\.id), to: landing), 1, "what was found can be moved in one go")
        check(await onServer("Sort the transcripts", landing) != nil, true, "it is on the new day")
        check(await onServer("Sort the transcripts", moveDay), nil, "and gone from the old one")

        let fitted = try await PlannerVoiceAPI.fit(on: landing, after: nil)
        check(fitted.placed, 1, "fit my day places it")
        check(fitted.spoken, "Moved Sort the transcripts to 7:00 am.", "and says so in one sentence")
        check(await onServer("Sort the transcripts", landing)?.time, "07:00", "the server has the time")

        let read = try await PlannerVoiceAPI.today(moveDay, waiting: 4)
        check(read.date, moveDay, "a day read straight from the server is the day asked for")
        check(read.tasks.map(\.title), ["Call Shashank sir"], "with its timed tasks")
        check(read.waiting, 4, "and the inbox count carried over")
        check(PlannerSnapshot.load()?.date, moveDay, "and it is saved, so the widget catches up")
        check(PlannerVoice.todaySummary(read, at: 9 * 60), "1 on today, 0 done. Next: Call Shashank sir at 2:00 pm. 4 tasks are waiting in your inbox.",
              "which is what Siri says above the list")
    } catch {
        failures += 1; print("  FAIL a voice call threw: \(error)")
    }
    do {
        let moving = try await PlannerVoiceAPI.search("Shashank").tasks.first!
        let saturday = Civil.add(today, days: 8)
        try await PlannerVoiceAPI.reschedule(moving.id, day: saturday, time: 18 * 60)
        check(await onServer("Call Shashank sir", saturday)?.time, "18:00", "one task moved to a new day and time")
        try await PlannerVoiceAPI.reschedule(moving.id, day: nil, time: 9 * 60 + 30)
        check(await onServer("Call Shashank sir", saturday)?.time, "09:30", "a time alone keeps its day")
        let sunday = Civil.add(today, days: 9)
        try await PlannerVoiceAPI.reschedule(moving.id, day: sunday, time: nil)
        check(await onServer("Call Shashank sir", sunday)?.time, "09:30", "a day alone keeps its time")

        try await PlannerVoiceAPI.delete(moving.id)
        check(await onServer("Call Shashank sir", sunday), nil, "a deleted task is gone from the server")
        check((try await PlannerVoiceAPI.search("Shashank")).tasks.isEmpty, true, "and cannot be found any more")

        let before = await serverDay(today).map { "\($0.title) \($0.time ?? "-")" }
        let trial = try await PlannerVoiceAPI.spread(dryRun: true)
        check(await serverDay(today).map { "\($0.title) \($0.time ?? "-")" }, before, "a trial run of planning the overdue pile changes nothing")
        let real = try await PlannerVoiceAPI.spread(dryRun: false)
        check(real.placed, trial.placed, "the real run does what the trial said it would")
        check(real.spoken.isEmpty, false, "and says so in a sentence")
        check((try await PlannerVoiceAPI.spread(dryRun: true)).placed <= real.left, true, "afterwards only what would not fit is still overdue")
    } catch {
        failures += 1; print("  FAIL a voice change threw: \(error)")
    }

    print("Plan the overdue pile, from the app")
    store.toast = nil
    await store.spreadOverdue()
    await settle()
    check(store.toast?.isEmpty, false, "it answers in the server's words")

    // Leave the widget's copy as the app would have it.
    await store.refreshAll(quiet: true)

    do {
        WidgetConnection.save(server: base.absoluteString, key: "wrong-key")
        _ = try await PlannerVoiceAPI.create(title: "Should not exist", on: moveDay, at: nil, lasting: nil)
        failures += 1; print("  FAIL a refused add looked like it worked")
    } catch let refused as PlannerVoiceAPI.Failure {
        check(refused.message.isEmpty, false, "a refused add says why instead of claiming it worked")
    } catch {
        failures += 1; print("  FAIL a refused add threw something unreadable: \(error)")
    }
    WidgetConnection.save(server: base.absoluteString, key: connection.key)

    print(failures == 0 ? "iPhone app store: all end-to-end checks passed" : "iPhone app store: \(failures) checks failed")
}

await run()
exit(failures == 0 ? 0 : 1)
