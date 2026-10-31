import Foundation
import Observation

/// Everything the screens show, and every change they make. Changes apply on
/// screen at once and roll back if the server refuses them, like Android.
@MainActor
@Observable
final class PlannerStore {
    private(set) var connection: Connection?
    private var api: PlannerAPI?
    private(set) var timeZone: TimeZone
    /// Ticks every minute so overdue and the now line stay current.
    var now = Date()
    var selectedDate: String
    private(set) var days: [String: DayView] = [:]
    private(set) var inbox: DayView?
    private(set) var week: WeekView?
    private(set) var milestoneRows: [MilestoneRow] = []
    private(set) var projects: [String: String] = [:]
    private(set) var busy: Set<String> = []
    private(set) var loading = false
    /// A short message for the bottom of the screen.
    var toast: String?

    /// Bumped by every write, so a refresh that started before it is not applied.
    private var revision = 0
    private var reminderSync: Task<Void, Never>?
    private var toastClear: Task<Void, Never>?

    /// Writes still saving, counting the refresh after each; tests wait for 0.
    private(set) var writesInFlight = 0
    /// Writes the server has not answered yet. Reads are not applied while any
    /// are out, so a read that crossed a change on its way cannot undo it on screen.
    private var unconfirmed = 0

    /// `connection` is the saved one in the app; the end-to-end tests pass a local server.
    init(connection saved: Connection? = ConnectionStore.load()) {
        let zone = TimeZone(identifier: UserDefaults.standard.string(forKey: "timezone") ?? "Asia/Kolkata") ?? .current
        timeZone = zone
        selectedDate = Civil.logicalToday(in: zone)
        connection = saved
        api = connection.map { PlannerAPI(connection: $0) }
        paintCached()
    }

    var moment: Moment { Moment(now: now, timeZone: timeZone) }
    var calendarToday: String { Civil.today(in: timeZone, now: now) }
    var logicalToday: String { Civil.logicalToday(in: timeZone, now: now) }

    var milestones: [String: FocusMilestone] {
        Dictionary(milestoneRows.map { ($0.id, FocusMilestone(id: $0.id, name: $0.name, targetDate: $0.targetDate)) },
                   uniquingKeysWith: { first, _ in first })
    }

    var focusOverdue: [RankedTask] { rankOverdue(inbox?.items ?? [], milestones: milestones, now: moment) }
    var focusTodayTasks: [PlannerTask] { focusToday(days[logicalToday], backlog: inbox?.items ?? [], now: moment) }
    var weekRows: [FocusWeekRow] {
        guard let week else { return [] }
        return focusWeekRows(week.items, weekStart: week.weekStart, milestones: milestones, projectNames: projects)
    }

    /// The milestone or project a task belongs to, for its card.
    func context(_ task: PlannerTask) -> String? {
        task.milestoneId.flatMap { milestones[$0]?.name } ?? task.projectId.flatMap { projects[$0] }
    }

    // MARK: Reading

    private func paintCached() {
        guard let api else { return }
        if let day: DayView = api.cached("/v2/day?date=\(selectedDate)") { days[selectedDate] = day }
        inbox = api.cached("/v2/day/inbox")
        week = api.cached("week")
        milestoneRows = api.cached("milestones").map { (page: DashboardPage<MilestoneRow>) in page.rows } ?? []
        if let planning: PlanningContext = api.cached("/v2/day/planning-context") {
            projects = Dictionary(planning.projects.map { ($0.id, $0.name) }, uniquingKeysWith: { first, _ in first })
        }
    }

    func start() async {
        guard api != nil else { return }
        await refreshAll()
        if await Reminders.status() == .notDetermined, await Reminders.requestPermission() { syncReminders() }
    }

    func refreshAll() async {
        guard api != nil else { return }
        loading = true
        async let selected: Void = loadDay(selectedDate)
        async let today: Void = loadTodayIfAway()
        async let backlog: Void = refreshInbox()
        async let thisWeek: Void = refreshWeek()
        async let targets: Void = refreshMilestones()
        async let names: Void = refreshProjects()
        _ = await (selected, today, backlog, thisWeek, targets, names)
        loading = false
        syncReminders()
    }

    /// Focus needs today's view even while Today shows another day.
    private func loadTodayIfAway() async {
        if selectedDate != logicalToday { await loadDay(logicalToday, quiet: true) }
    }

    func loadDay(_ date: String, quiet: Bool = false) async {
        guard let api else { return }
        let started = revision
        do {
            let view: DayView = try await api.get("/v2/day?date=\(date)")
            guard started == revision, unconfirmed == 0 else { return }
            days[date] = view
            adopt(view.timezone)
        } catch { if !quiet { report(error) } }
    }

    func refreshInbox(quiet: Bool = false) async {
        guard let api else { return }
        let started = revision
        do {
            let view: DayView = try await api.get("/v2/day/inbox")
            if started == revision, unconfirmed == 0 { inbox = view }
        } catch { if !quiet { report(error) } }
    }

    func refreshWeek(anchor: String? = nil, quiet: Bool = false) async {
        guard let api else { return }
        let started = revision
        do {
            let view: WeekView = try await api.get("/v2/week?date=\(anchor ?? week?.weekStart ?? calendarToday)", cacheAs: "week")
            if started == revision, unconfirmed == 0 { week = view }
        } catch { if !quiet { report(error) } }
    }

    func refreshMilestones() async {
        guard let api else { return }
        var rows: [MilestoneRow] = []
        var offset: Int? = 0
        do {
            while let next = offset, rows.count < 2000 {
                let page: DashboardPage<MilestoneRow> = try await api.get("/v2/native/dashboard?section=milestones&offset=\(next)")
                rows += page.rows
                offset = page.nextOffset
            }
            milestoneRows = rows
            cacheMilestones(rows)
        } catch { /* The saved list stays; Focus still works without it. */ }
    }

    private func cacheMilestones(_ rows: [MilestoneRow]) {
        let encoded = rows.map { row -> [String: Any] in
            ["id": row.id, "name": row.name, "target_date": row.targetDate ?? NSNull(), "status": row.status ?? NSNull()]
        }
        if let data = try? JSONSerialization.data(withJSONObject: ["data": ["rows": encoded, "next_offset": NSNull()]]) {
            ResponseCache.save(data, key: "milestones")
        }
    }

    func refreshProjects() async {
        guard let api else { return }
        if let planning: PlanningContext = try? await api.get("/v2/day/planning-context") {
            projects = Dictionary(planning.projects.map { ($0.id, $0.name) }, uniquingKeysWith: { first, _ in first })
        }
    }

    private func adopt(_ identifier: String) {
        guard let zone = TimeZone(identifier: identifier), zone != timeZone else { return }
        timeZone = zone
        UserDefaults.standard.set(identifier, forKey: "timezone")
    }

    // MARK: Writing

    /// Applies `change` on screen (nil removes the task), sends `remote`, and
    /// puts everything back if it fails. Returns the response, or nil on failure.
    /// Shows a change on screen at once and saves it in the background. If the
    /// server refuses, only these tasks are put back as they were, and a message
    /// says what could not be saved and why. `what` reads like "move “Yoga”".
    @discardableResult
    private func perform(_ tasks: [PlannerTask], _ what: String, local change: (PlannerTask) -> PlannerTask?,
                         remote: (PlannerAPI) async throws -> Data) async -> Data? {
        if let adding = tasks.first(where: { $0.id.hasPrefix("pending:") }) {
            show("Still adding “\(adding.title)”. Try again in a moment.")
            return nil
        }
        guard let api, !tasks.isEmpty else { return nil }
        let ids = Set(tasks.map(\.id))
        writesInFlight += 1
        defer { writesInFlight -= 1 }
        unconfirmed += 1
        revision += 1
        busy.formUnion(ids)
        applyLocal(tasks, change)
        do {
            let data = try await remote(api)
            unconfirmed -= 1
            busy.subtract(ids)
            revision += 1
            await afterWrite()
            return data
        } catch {
            unconfirmed -= 1
            busy.subtract(ids)
            revision += 1
            // The tasks as they were passed in are the copies from before this change.
            applyLocal(tasks) { $0 }
            failed(what, error)
            // Then read the server again: the failure may mean the task changed
            // or went away elsewhere. Offline, the restored copy stays.
            await afterWrite()
            return nil
        }
    }

    /// Projects a change into every copy on screen: each day, the Inbox and the week.
    private func applyLocal(_ tasks: [PlannerTask], _ change: (PlannerTask) -> PlannerTask?) {
        let ids = Set(tasks.map(\.id))
        var updated: [String: PlannerTask] = [:]
        for task in tasks { if let next = change(task) { updated[task.id] = next } }
        let now = moment
        for (date, view) in days {
            var items = view.items.filter { !ids.contains($0.id) }
            items += updated.values.filter { ($0.date ?? "") == date }
            days[date]?.items = items
        }
        if var box = inbox {
            box.items = box.items.filter { !ids.contains($0.id) } + updated.values.filter { belongsInInbox($0, now) }
            inbox = box
        }
        if var current = week {
            let end = Civil.add(current.weekStart, days: 6)
            current.items = current.items.filter { !ids.contains($0.id) } + updated.values.filter { task in
                guard let day = task.date ?? task.dueDate else { return false }
                return day >= current.weekStart && day <= end
            }
            week = current
        }
    }

    private func afterWrite() async {
        await loadDay(selectedDate, quiet: true)
        await loadTodayIfAway()
        await refreshInbox(quiet: true)
        await refreshWeek(quiet: true)
        syncReminders()
    }

    func setDone(_ task: PlannerTask, _ done: Bool = true) async {
        await perform([task], "\(done ? "tick off" : "reopen") “\(task.title)”", local: { var next = $0; next.done = done; return next }) {
            try await $0.send("PATCH", PlannerAPI.taskPath(task.id), body: ["done": done])
        }
    }

    func toggleStar(_ task: PlannerTask) async {
        await perform([task], "\(task.starred ? "unstar" : "star") “\(task.title)”", local: { var next = $0; next.starred.toggle(); return next }) {
            try await $0.send("PATCH", PlannerAPI.taskPath(task.id), body: ["starred": !task.starred])
        }
    }

    /// A timeline drop: moves the task on screen in this same frame, inside the
    /// caller's animation, then saves it. Waiting for a Task to start would let
    /// the block flash back to its old slot first.
    func rescheduleNow(_ task: PlannerTask, date: String, start: Int) {
        guard api != nil, !task.id.hasPrefix("pending:") else { return }
        let time = Civil.clock(start)
        var moved = task
        moved.date = date
        moved.time = time
        applyLocal([task]) { _ in moved }
        Task {
            await perform([task], "move “\(task.title)” to \(Civil.clockText(start, twentyFour: Civil.prefers24Hour))", local: { _ in moved }) {
                try await $0.send("PATCH", PlannerAPI.taskPath(task.id), body: ["scheduled_date": date, "start_time": time])
            }
        }
    }

    /// Moves tasks to a day, untimed, in one request. A broken deadline moves
    /// with them; a milestone the move overruns is pushed out by the server.
    func move(_ tasks: [PlannerTask], to date: String) async {
        let today = calendarToday
        let response = await perform(tasks, "move \(plural(tasks.count, "task")) to \(Civil.short(date))", local: { movedForFocus($0, to: date, today: today) }) {
            try await $0.send("POST", "/v2/day/tasks/triage", body: ["task_ids": tasks.map(\.id), "action": "move", "to_date": date])
        }
        guard let response else { return }
        let notes = milestoneNotes(response)
        show((["Moved \(plural(tasks.count, "task")) to \(Civil.short(date))"] + notes).joined(separator: "\n"))
        if !notes.isEmpty { await refreshMilestones() }
    }

    /// Closes tasks as skipped. Nothing is deleted.
    func drop(_ tasks: [PlannerTask]) async {
        let response = await perform(tasks, "drop \(plural(tasks.count, "task"))", local: { var next = $0; next.done = true; return next }) {
            try await $0.send("POST", "/v2/day/tasks/triage", body: ["task_ids": tasks.map(\.id), "action": "drop", "to_date": NSNull()])
        }
        if response != nil { show("Dropped \(plural(tasks.count, "task")) — kept as skipped, not deleted") }
    }

    /// Saves an edited task, sending only the fields that changed.
    @discardableResult
    func update(_ task: PlannerTask, to edited: PlannerTask) async -> Bool {
        var body: [String: Any] = [:]
        if edited.title != task.title { body["title"] = edited.title }
        if edited.minutes != task.minutes { body["estimated_minutes"] = edited.minutes }
        if edited.date != task.date { body["scheduled_date"] = edited.date.map { $0 as Any } ?? NSNull() }
        if edited.time != task.time { body["start_time"] = edited.time.map { $0 as Any } ?? NSNull() }
        if edited.notes != task.notes { body["notes"] = edited.notes ?? "" }
        if edited.starred != task.starred { body["starred"] = edited.starred }
        if edited.done != task.done { body["done"] = edited.done }
        if body.isEmpty { return true }
        let response = await perform([task], "save “\(task.title)”", local: { _ in edited }) {
            try await $0.send("PATCH", PlannerAPI.taskPath(task.id), body: body)
        }
        guard let response else { return false }
        let notes = milestoneNotes(response)
        if !notes.isEmpty { show(notes.joined(separator: "\n")); await refreshMilestones() }
        return true
    }

    /// Adds a task. It shows at once under a temporary id, which the server's
    /// id replaces when it answers; if the server refuses, it is taken off again.
    @discardableResult
    func create(title: String, date: String?, time: String?, minutes: Int, notes: String?, starred: Bool) async -> Bool {
        guard let api else { return false }
        var body: [String: Any] = ["title": title, "estimated_minutes": minutes]
        if let date { body["date"] = date }
        if let time { body["start_time"] = time }
        if let notes, !notes.isEmpty { body["notes"] = notes }
        let pending = PlannerTask(id: "pending:\(UUID().uuidString)", title: title, time: time, minutes: minutes,
                                  starred: starred, date: date, notes: notes?.isEmpty == false ? notes : nil)
        writesInFlight += 1
        defer { writesInFlight -= 1 }
        unconfirmed += 1
        revision += 1
        applyLocal([pending]) { $0 }
        do {
            let data = try await api.send("POST", "/v2/day/tasks", body: body)
            let id = (try? JSONDecoder().decode(Envelope<MutationResult>.self, from: data))?.data.task?.id
            if starred, let id {
                _ = try? await api.send("PATCH", PlannerAPI.taskPath(id), body: ["starred": true])
            }
            unconfirmed -= 1
            revision += 1
            if let id { applyLocal([pending]) { var saved = $0; saved.id = id; return saved } }
            await afterWrite()
            return true
        } catch {
            unconfirmed -= 1
            revision += 1
            applyLocal([pending]) { _ in nil }
            failed("add “\(title)”", error)
            return false
        }
    }

    @discardableResult
    func delete(_ task: PlannerTask) async -> Bool {
        await perform([task], "delete “\(task.title)”", local: { _ in nil }) {
            do { try await $0.send("DELETE", PlannerAPI.taskPath(task.id)) }
            catch let error as PlannerError where error.status == 404 { return Data() } // Already gone.
            return Data()
        } != nil
    }

    // MARK: Connection

    func connect(server: String, key: String) async throws {
        let candidate = Connection(base: try Connection.origin(server), key: key.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !candidate.key.isEmpty else { throw PlannerError(message: "An app access key is required.") }
        let probe = PlannerAPI(connection: candidate)
        // Checked before anything saved is replaced, so a typo keeps the old connection.
        let _: DayView = try await probe.get("/v2/day?date=\(logicalToday)")
        try ConnectionStore.save(candidate)
        ResponseCache.clear()
        days = [:]; inbox = nil; week = nil; milestoneRows = []; projects = [:]
        connection = candidate
        api = probe
        selectedDate = logicalToday
        await start()
    }

    func disconnect() {
        ConnectionStore.clear()
        ResponseCache.clear()
        Reminders.clear()
        connection = nil; api = nil
        days = [:]; inbox = nil; week = nil; milestoneRows = []; projects = [:]
    }

    /// Re-queues the coming week's reminders, once things settle.
    func syncReminders() {
        guard let api else { return }
        let zone = timeZone
        reminderSync?.cancel()
        reminderSync = Task {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            guard !Task.isCancelled else { return }
            await Reminders.sync(api: api, timeZone: zone)
        }
    }

    // MARK: Messages

    func show(_ message: String, seconds: Double = 4) {
        toast = message
        toastClear?.cancel()
        toastClear = Task {
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            guard !Task.isCancelled else { return }
            toast = nil
        }
    }

    /// "Couldn't move “Yoga” to 10:00: the server's reason. Your change was undone."
    private func failed(_ what: String, _ error: Error) {
        if error is CancellationError || (error as? URLError)?.code == .cancelled { return }
        var reason = error.localizedDescription
        while reason.hasSuffix(".") { reason.removeLast() }
        show("Couldn't \(what): \(reason). Your change was undone.", seconds: 7)
    }

    private func report(_ error: Error) {
        if error is CancellationError || (error as? URLError)?.code == .cancelled { return }
        show(error.localizedDescription)
    }
}

func plural(_ count: Int, _ word: String) -> String { "\(count) \(word)\(count == 1 ? "" : "s")" }
