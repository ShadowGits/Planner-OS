import Foundation

var failures = 0
func check(_ value: Bool, _ label: String) {
    print("\(value ? "ok" : "FAIL") \(label)")
    if !value { failures += 1 }
}

@MainActor
func run() async {
    let base = URL(string: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "http://127.0.0.1:8880")!
    let connection = Connection(base: base, key: "app-secret")
    let api = PlannerAPI(connection: connection)
    let store = PlannerStore(connection: connection)
    let day = store.logicalToday
    do {
        struct Reads: Decodable { let counts: [String: Int] }
        func reads() async throws -> [String: Int] {
            let value: Reads = try await api.get("/v2/e2e/read-counts")
            return value.counts
        }
        let response = try await api.send("POST", "/v2/day/tasks", body: ["title": "Refresh fixture", "date": day, "start_time": "12:00"])
        let task = try JSONDecoder().decode(Envelope<MutationResult>.self, from: response).data.task!
        await store.start()
        check(store.days[day]?.items.contains { $0.id == task.id } == true, "initial day loaded")

        let path = "/v2/day?date=\(day)"
        let beforeCoalescing = try await reads()[path, default: 0]
        async let first: Void = store.loadDay(day)
        async let second: Void = store.loadDay(day)
        _ = await (first, second)
        check(try await reads()[path, default: 0] == beforeCoalescing + 1, "overlapping day reads share one request")
        let beforeBrowsing = try await reads()
        store.showDays([day])
        try await Task.sleep(nanoseconds: 500_000_000)
        await store.refreshIfStale()
        check(try await reads() == beforeBrowsing, "fresh scroll and early poll issue no requests")

        let beforeReminders = try await reads()
        let reminderDays = try await api.reminderDays(start: day)
        let afterReminders = try await reads()
        check(reminderDays.count == 7 && afterReminders["/v2/day/reminder-schedule?date=\(day)", default: 0] == beforeReminders["/v2/day/reminder-schedule?date=\(day)", default: 0] + 1,
              "reminders use one bounded week request")
        check(afterReminders[path] == beforeReminders[path], "reminders do not download full days")

        try await api.send("POST", "/v2/e2e/reminder-mode", body: ["mode": "404"])
        let fallbackBefore = try await reads()
        let fallback = try await api.reminderDays(start: day)
        let fallbackAfter = try await reads()
        let dayReads = (0..<7).map { "/v2/day?date=\(Civil.add(day, days: $0))" }
        check(fallback.count == 7 && dayReads.allSatisfy { fallbackAfter[$0, default: 0] == fallbackBefore[$0, default: 0] + 1 },
              "older-server 404 retains the complete seven-day fallback")
        for mode in ["500", "partial"] {
            try await api.send("POST", "/v2/e2e/reminder-mode", body: ["mode": mode])
            let failedBefore = try await reads()
            do {
                _ = try await api.reminderDays(start: day)
                check(false, "\(mode) reminder feed must fail")
            } catch {
                let failedAfter = try await reads()
                check(dayReads.allSatisfy { failedAfter[$0] == failedBefore[$0] },
                      "\(mode) reminder feed propagates failure without full-day downloads")
            }
        }
        try await api.send("POST", "/v2/e2e/reminder-mode", body: ["mode": "normal"])

        let distant = Civil.add(day, days: 3)
        await store.loadDay(distant)
        let beforeEdit = try await reads()["/v2/day?date=\(distant)", default: 0]
        if let loadedTask = store.days[day]?.items.first(where: { $0.id == task.id }) {
            await store.toggleStar(loadedTask)
        } else {
            check(false, "editable task is loaded")
        }
        check(try await reads()["/v2/day?date=\(distant)", default: 0] == beforeEdit,
              "ordinary edits do not refresh unrelated cached dates")

        try await api.send("PATCH", PlannerAPI.taskPath(task.id), body: ["title": "Changed on another device"])
        let remindersBefore = Reminders.syncCount
        await store.refreshInBackground()
        check(store.days[day]?.items.first { $0.id == task.id }?.title == "Changed on another device", "background refresh adopts remote changes")
        let cached: DayView? = api.cached("/v2/day?date=\(day)")
        check(cached?.items.first { $0.id == task.id }?.title == "Changed on another device", "background refresh updates the saved day")
        check(Reminders.syncCount > remindersBefore, "background refresh awaits reminder reconciliation")

        store.beginDrag(task.id)
        try await api.send("PATCH", PlannerAPI.taskPath(task.id), body: ["title": "Changed during drag"])
        await store.refreshInBackground()
        check(store.days[day]?.items.first { $0.id == task.id }?.title == "Changed on another device", "background refresh stays out of an active drag")
        store.endDrag()
        await store.refreshInBackground()
        check(store.days[day]?.items.first { $0.id == task.id }?.title == "Changed during drag", "refresh catches up after dragging ends")

        try await api.send("PATCH", PlannerAPI.taskPath(task.id), body: ["title": "Refreshed without a window"])
        // No RootView, activation, manual refresh or UI timer exists here.
        // The store's own timer must pick up this external change.
        for _ in 0..<160 {
            if store.days[day]?.items.first(where: { $0.id == task.id })?.title == "Refreshed without a window" { break }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        check(store.days[day]?.items.first { $0.id == task.id }?.title == "Refreshed without a window", "automatic refresh runs independently of a window")

        store.disconnect()
        let count = Reminders.syncCount
        await store.refreshInBackground()
        check(store.connection == nil && store.days.isEmpty && Reminders.syncCount == count, "disconnected planner does not refresh")

        let offline = PlannerStore(connection: Connection(base: URL(string: "http://127.0.0.1:1")!, key: "app-secret"))
        await offline.refreshAll(quiet: true)
        check(offline.toast == nil && !offline.loading, "a quiet offline refresh does not interrupt the user or leave loading stuck")
    } catch {
        failures += 1
        print("FAIL \(error)")
    }
    print(failures == 0 ? "All background refresh checks passed" : "\(failures) background refresh checks failed")
}

Task { @MainActor in
    await run()
    exit(failures == 0 ? 0 : 1)
}
dispatchMain()
