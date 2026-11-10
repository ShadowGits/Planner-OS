import Foundation
#if canImport(AppIntents)
import AppIntents
#if canImport(WidgetKit)
import WidgetKit
#endif

/// What Siri can do in Planner OS.
///
/// Siri cannot look at a screen and press things. It can only use the actions
/// an app writes down here, and since the 27.3 Siri AI preview it uses them in
/// two ways:
///
/// - Siri AI understands what was said in any words and picks the actions that
///   fit. It only considers actions marked `@AppIntent(.tool)`, and it tells
///   them apart — and fills in their parameters — from the title and
///   description on each action and on every parameter. Those descriptions are
///   written for a model that has never seen Planner OS, because that is what
///   reads them. Without the marker, Siri AI cannot see an action at all: it
///   answers "Planner OS can't be used for this".
/// - Plain Siri, the Shortcuts app, Spotlight and the Action button use the
///   fixed phrases in `PlannerShortcuts` at the bottom.
///
/// Every action is a thin wrapper. What to do and what to say back lives in
/// PlannerVoice, which is plain Foundation and is tested on every run.
/// `e2e/swift_intents.py` refuses an action without the marker, or a parameter
/// or property without a description, so neither can go missing again.
///
/// Apple's rules: developer.apple.com/documentation/appintents/
/// bringing-custom-actions-and-content-to-siri

// MARK: - The task Siri is talking about

/// A task as Siri sees it, so "mark the gym done" can be narrowed to one
/// thing, and so Siri can ask which when a phrase fits more than one.
struct PlannerTaskEntity: AppEntity, Identifiable {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Task"
    static let defaultQuery = PlannerTaskQuery()

    var id: String

    @Property(title: "Name", description: "The task's name as it appears on the person's plan.")
    var title: String

    @Property(title: "Day", description: "The day the task is planned for, as yyyy-MM-dd. Empty when it has no day yet.")
    var day: String

    @Property(title: "Start time", description: "When the task starts, as 24-hour HH:mm. Empty when it has no set time.")
    var time: String

    @Property(title: "Done", description: "Whether the task has been ticked off.")
    var done: Bool

    /// What a list of tasks shows under each name: "tomorrow, 2:00 pm".
    var subtitle: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(title)", subtitle: "\(subtitle)")
    }

    init(_ task: VoiceTask, today: String) {
        id = task.id
        subtitle = PlannerVoice.describe(task, today: today)
        title = task.title
        day = task.date ?? ""
        time = PlannerVoice.parseClock(task.time).map(PlannerVoice.clockText) ?? ""
        done = task.done
    }

    init(_ item: PlannerSnapshot.Item, today: String) {
        self.init(
            VoiceTask(id: item.id, title: item.title, date: today,
                      time: PlannerVoice.clockText(item.start), minutes: item.minutes, done: item.done),
            today: today
        )
    }
}

/// How Siri finds the task someone named.
///
/// Apple's rule is that Siri finds an app's entities through Spotlight or an
/// `EnumerableEntityQuery`; this is the second. It lists every open task from
/// the server — not the widget's copy, which holds today alone, so a task
/// dated September could never be found from it — and searches by name when
/// there is a word to go on. With no signal it falls back to today.
struct PlannerTaskQuery: EnumerableEntityQuery, EntityStringQuery {
    private var today: String { PlannerVoice.logicalDay(Date()) }
    private var nowMinutes: Int { PlannerVoice.logicalMinute(Date()) }

    func allEntities() async throws -> [PlannerTaskEntity] {
        let stamp = today
        if let open = try? await PlannerVoiceAPI.openTasks() {
            return open.map { PlannerTaskEntity($0, today: stamp) }
        }
        return (PlannerSnapshot.load()?.tasks ?? []).map { PlannerTaskEntity($0, today: stamp) }
    }

    func entities(for identifiers: [String]) async throws -> [PlannerTaskEntity] {
        let stamp = today
        let known = (PlannerSnapshot.load()?.tasks ?? [])
            .filter { identifiers.contains($0.id) }
            .map { PlannerTaskEntity($0, today: stamp) }
        if known.count == identifiers.count { return known }
        // Something is not on today: look the rest up among the open tasks.
        let wanted = Set(identifiers).subtracting(known.map(\.id))
        let rest = ((try? await PlannerVoiceAPI.openTasks()) ?? [])
            .filter { wanted.contains($0.id) }
            .map { PlannerTaskEntity($0, today: stamp) }
        return known + rest
    }

    /// What Siri offers when it has to ask "which one?".
    func entities(matching string: String) async throws -> [PlannerTaskEntity] {
        let stamp = today
        if let found = try? await PlannerVoiceAPI.search(string, limit: 25) {
            return found.tasks.map { PlannerTaskEntity($0, today: stamp) }
        }
        return PlannerVoice.candidates(PlannerSnapshot.load(), matching: string, at: nowMinutes)
            .map { PlannerTaskEntity($0, today: stamp) }
    }

    func suggestedEntities() async throws -> [PlannerTaskEntity] {
        let stamp = today
        return PlannerVoice.candidates(PlannerSnapshot.load(), matching: "", at: nowMinutes)
            .prefix(8)
            .map { PlannerTaskEntity($0, today: stamp) }
    }
}

/// Minutes into the planner's day, which runs to four in the morning.
private func minutesNow() -> Int { PlannerVoice.logicalMinute(Date()) }

/// Today, and never another day passed off as today.
///
/// The app leaves a copy for the widget, but only writes it while it runs, so
/// the copy is often from yesterday. When it is not today's, ask the server;
/// when the server cannot be reached either, say so rather than guess.
private func currentDay() async -> PlannerSnapshot? {
    let today = PlannerVoice.logicalDay(Date())
    let saved = PlannerSnapshot.load()
    if PlannerVoice.isFresh(saved, today: today) { return saved }
    return try? await PlannerVoiceAPI.today(today, waiting: saved?.waiting ?? 0)
}

private let unreachable: IntentDialog =
    "I can't reach Planner OS right now, and the copy on this phone isn't from today. Open the app once."

// MARK: - Asking

/// "What's on today?" — the whole day, shown as a list.
///
/// The list is the answer, so Siri shows it rather than reading it out; the
/// line it says is only what the list adds up to.
@AppIntent(.tool)
struct ShowTodayIntent: AppIntent {
    static let title: LocalizedStringResource = "Show today's plan"
    static let description = IntentDescription(
        "Shows everything on the person's Planner OS plan for today as a list: tasks and habits, done and still to do, in time order, marking what is under way, what is next and what was missed, and how many tasks are waiting in the inbox. Use this for any question about what is on today, what the day looks like, or what is planned."
    )
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog & ShowsSnippetView {
        guard let day = await currentDay() else {
            return .result(dialog: unreachable, view: TodaySnippet(rows: [], more: 0, waiting: 0))
        }
        let minute = minutesNow()
        let rows = PlannerVoice.todayRows(day, at: minute)
        let shown = Array(rows.prefix(TodaySnippet.limit))
        return .result(
            dialog: IntentDialog(stringLiteral: PlannerVoice.todaySummary(day, at: minute)),
            view: TodaySnippet(rows: shown, more: rows.count - shown.count, waiting: day.waiting)
        )
    }
}

/// "What am I doing right now?" — only the one thing under way, or next.
@AppIntent(.tool)
struct CurrentTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "What am I doing now"
    static let description = IntentDescription(
        "Says only the single Planner OS task under way at this moment, with how long is left, or the next one if nothing is under way. For the whole day, use Show today's plan instead."
    )
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let day = await currentDay() else { return .result(dialog: unreachable) }
        return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.nowSentence(day, at: minutesNow())))
    }
}

/// "What's next?" — skips whatever is already running.
@AppIntent(.tool)
struct NextTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "What's next"
    static let description = IntentDescription(
        "Says the next Planner OS task or habit due to start today, and when, skipping whatever is already under way."
    )
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let day = await currentDay() else { return .result(dialog: unreachable) }
        return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.nextSentence(day, at: minutesNow())))
    }
}

/// "How much is left today?"
@AppIntent(.tool)
struct RemainingTodayIntent: AppIntent {
    static let title: LocalizedStringResource = "How much is left today"
    static let description = IntentDescription(
        "Says how many of today's Planner OS tasks and habits are still not done and how long they add up to, and how many tasks are waiting in the inbox."
    )
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let day = await currentDay() else { return .result(dialog: unreachable) }
        return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.remainingSentence(day, at: minutesNow())))
    }
}

// MARK: - Changing

/// "Add call Shashank sir tomorrow at 2pm."
///
/// The day and the time are separate and both optional, so "tomorrow" alone
/// puts the task on tomorrow with no set time, rather than at midnight.
@AppIntent(.tool)
struct AddTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Add a task"
    static let description = IntentDescription(
        "Adds one task to the person's Planner OS plan. Use it for any request to add, plan, schedule, note or remember something to do. The day and the start time are both optional: with a day only, the task goes on that day with no set time; with neither, it goes on today with no set time. For several separate things to do, add each as its own task."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Task",
        description: "A short name for the task in the person's own words, as they would write it on a to-do list — for example \"Call Shashank sir about the transcripts\". Leave out the day, the time and the duration; those have their own parameters.",
        requestValueDialog: "What should the task be called?"
    )
    var name: String

    @Parameter(
        title: "Day",
        description: "The day the task is for, such as today, tomorrow or a date. Only the date is used. Leave empty when no day was said; the task then goes on today."
    )
    var day: Date?

    @Parameter(
        title: "Start time",
        description: "When the task starts, only if a time was said, written as 24-hour HH:mm — for example 14:00 for 2 pm. Leave empty when no time was said; the task then has no set time."
    )
    var time: String?

    @Parameter(
        title: "Minutes",
        description: "How long the task takes, in whole minutes, for example 30. Leave empty when no duration was said."
    )
    var minutes: Int?

    static var parameterSummary: some ParameterSummary {
        Summary("Add \(\.$name) on \(\.$day) at \(\.$time)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let taskName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !taskName.isEmpty else { return .result(dialog: "A task needs a name.") }
        var clock: Int?
        if let time, !time.trimmingCharacters(in: .whitespaces).isEmpty {
            guard let read = PlannerVoice.parseSpokenTime(time) else {
                return .result(dialog: IntentDialog(stringLiteral: "I couldn't read \(time) as a time."))
            }
            clock = read
        }
        let today = PlannerVoice.logicalDay(Date())
        let slot = PlannerVoice.taskSlot(
            day: day.map { PlannerVoice.dayStamp($0) },
            time: clock,
            today: today,
            nowMinute: minutesNow()
        )
        do {
            let made = try await PlannerVoiceAPI.create(
                title: taskName, on: slot.date, at: PlannerVoice.parseClock(slot.time), lasting: minutes)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.addedSentence(
                made.title, date: slot.date, time: slot.time, today: today)))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Mark the gym done." Siri asks which when a phrase fits more than one.
@AppIntent(.tool)
struct CompleteTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Complete a task"
    static let description = IntentDescription(
        "Ticks one Planner OS task or habit off as done, or puts a ticked one back to not done."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Task",
        description: "The task or habit to tick off, found by its name.",
        requestValueDialog: "Which task?"
    )
    var task: PlannerTaskEntity

    @Parameter(
        title: "Done",
        description: "True to mark it done, false to put it back to not done.",
        default: true
    )
    var done: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("Mark \(\.$task) as \(\.$done)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Shown ticked straight away, then taken back if the server refuses:
        // the same bargain the widget already makes.
        PlannerSnapshot.mark(task.id, done: done)
        reloadWidget()
        do {
            try await PlannerWidgetAPI.setDone(task.id, done)
            return .result(dialog: done ? "\(task.title) is done." : "\(task.title) is open again.")
        } catch {
            PlannerSnapshot.mark(task.id, done: !done)
            reloadWidget()
            let message = (error as? PlannerVoiceAPI.Failure)?.message
                ?? (error as? PlannerWidgetAPI.Failure)?.message
                ?? "it could not be saved"
            return .result(dialog: IntentDialog(stringLiteral: "I could not save that: \(message)"))
        }
    }
}

/// "Which tasks mention transcripts?"
///
/// Also the first half of anything bulk: it hands back the tasks themselves,
/// so Siri can pass them straight into a move. "Move all the transcript ones
/// and the Shashank sir ones to today" is this twice and then one move.
@AppIntent(.tool)
struct FindTasksIntent: AppIntent {
    static let title: LocalizedStringResource = "Find tasks"
    static let description = IntentDescription(
        "Finds Planner OS tasks whose name contains a word or phrase, across the whole plan and on any date, soonest first, and returns them so they can be passed to another action such as moving them."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Word",
        description: "A word or short phrase from the tasks' names, for example \"transcripts\" or \"Shashank sir\". Case does not matter. At least two letters.",
        requestValueDialog: "What should I look for?"
    )
    var text: String

    @Parameter(
        title: "Include finished",
        description: "True to include tasks already done or dropped; false for only those still to do.",
        default: false
    )
    var includeDone: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("Find tasks matching \(\.$text)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<[PlannerTaskEntity]> & ProvidesDialog {
        let today = PlannerVoice.logicalDay(Date())
        do {
            let found = try await PlannerVoiceAPI.search(text, openOnly: !includeDone)
            let said = PlannerVoice.foundSentence(count: found.tasks.count, total: found.total, query: text)
            return .result(
                value: found.tasks.map { PlannerTaskEntity($0, today: today) },
                dialog: IntentDialog(stringLiteral: said)
            )
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(value: [], dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Move these to today." Always asks first and names the count: a word heard
/// wrongly should not quietly move forty tasks.
@AppIntent(.tool)
struct MoveTasksIntent: AppIntent {
    static let title: LocalizedStringResource = "Move tasks to a day"
    static let description = IntentDescription(
        "Moves the given Planner OS tasks to one day, with no set time on that day. Asks the person to confirm first, saying how many tasks will move."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Tasks",
        description: "The tasks to move, for example the ones Find tasks returned."
    )
    var tasks: [PlannerTaskEntity]

    @Parameter(
        title: "Day",
        description: "The day to move them to, such as today, tomorrow or a date. Only the date is used. It has to be today or later.",
        requestValueDialog: "Which day?"
    )
    var when: Date

    static var parameterSummary: some ParameterSummary {
        Summary("Move \(\.$tasks) to \(\.$when)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let today = PlannerVoice.logicalDay(Date())
        let day = PlannerVoice.dayStamp(when)
        let label = PlannerVoice.dayLabel(day, today: today)
        guard !tasks.isEmpty else { return .result(dialog: "There was nothing to move.") }
        try await requestConfirmation(
            result: .result(dialog: IntentDialog(
                stringLiteral: PlannerVoice.moveQuestion(count: tasks.count, to: label))),
            confirmationActionName: .go
        )
        do {
            let moved = try await PlannerVoiceAPI.move(tasks.map(\.id), to: day)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.movedSentence(count: moved, to: label)))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Move all the transcript tasks to today", in one go, for plain Siri. Still
/// asks before it moves.
@AppIntent(.tool)
struct MoveMatchingTasksIntent: AppIntent {
    static let title: LocalizedStringResource = "Move matching tasks to a day"
    static let description = IntentDescription(
        "Finds every unfinished Planner OS task whose name contains a word or phrase and moves them all to one day, with no set time. Asks the person to confirm first, saying how many tasks will move."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Word",
        description: "A word or short phrase from the tasks' names, for example \"transcripts\". Case does not matter. At least two letters.",
        requestValueDialog: "Which tasks? Give me a word from their names."
    )
    var text: String

    @Parameter(
        title: "Day",
        description: "The day to move them to, such as today, tomorrow or a date. Only the date is used. It has to be today or later.",
        requestValueDialog: "Which day?"
    )
    var when: Date

    static var parameterSummary: some ParameterSummary {
        Summary("Move tasks matching \(\.$text) to \(\.$when)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let today = PlannerVoice.logicalDay(Date())
        let day = PlannerVoice.dayStamp(when)
        let label = PlannerVoice.dayLabel(day, today: today)
        let found: PlannerVoiceAPI.Found
        do {
            found = try await PlannerVoiceAPI.search(text, limit: 200)
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
        guard !found.tasks.isEmpty else {
            return .result(dialog: IntentDialog(stringLiteral: "Nothing matches \(text)."))
        }
        try await requestConfirmation(
            result: .result(dialog: IntentDialog(
                stringLiteral: PlannerVoice.moveQuestion(count: found.tasks.count, to: label))),
            confirmationActionName: .go
        )
        do {
            let moved = try await PlannerVoiceAPI.move(found.tasks.map(\.id), to: day)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.movedSentence(count: moved, to: label)))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Move the CV to Saturday at 6 pm." One task, to a new day, a new time, or
/// both. A day alone keeps the task's time; a time alone keeps its day.
@AppIntent(.tool)
struct RescheduleTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Reschedule a task"
    static let description = IntentDescription(
        "Moves one Planner OS task to a different day, a different start time, or both. With a day only, the task keeps its time; with a time only, it keeps its day. Use it for requests to move, reschedule, postpone or bring forward a single task."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Task",
        description: "The task to move, found by its name.",
        requestValueDialog: "Which task?"
    )
    var task: PlannerTaskEntity

    @Parameter(
        title: "Day",
        description: "The new day, such as today, tomorrow or a date. Only the date is used. Leave empty to keep the task on its current day."
    )
    var day: Date?

    @Parameter(
        title: "Start time",
        description: "The new start time, only if a time was said, written as 24-hour HH:mm — for example 18:00 for 6 pm. Leave empty to keep the task's current time."
    )
    var time: String?

    static var parameterSummary: some ParameterSummary {
        Summary("Move \(\.$task) to \(\.$day) at \(\.$time)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        var clock: Int?
        if let time, !time.trimmingCharacters(in: .whitespaces).isEmpty {
            guard let read = PlannerVoice.parseSpokenTime(time) else {
                return .result(dialog: IntentDialog(stringLiteral: "I couldn't read \(time) as a time."))
            }
            clock = read
        }
        let stamp = day.map { PlannerVoice.dayStamp($0) }
        let today = PlannerVoice.logicalDay(Date())
        guard stamp != nil || clock != nil else {
            return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.rescheduledSentence(
                task.title, day: nil, time: nil, today: today)))
        }
        do {
            try await PlannerVoiceAPI.reschedule(task.id, day: stamp, time: clock)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.rescheduledSentence(
                task.title, day: stamp, time: clock, today: today)))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Delete the dentist task." Asks first: a deletion cannot be taken back.
@AppIntent(.tool)
struct DeleteTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Delete a task"
    static let description = IntentDescription(
        "Deletes one Planner OS task permanently. Asks the person to confirm first. To mark a task as finished instead, use Complete a task."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "Task",
        description: "The task to delete, found by its name.",
        requestValueDialog: "Which task?"
    )
    var task: PlannerTaskEntity

    static var parameterSummary: some ParameterSummary {
        Summary("Delete \(\.$task)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        try await requestConfirmation(
            result: .result(dialog: IntentDialog(stringLiteral: "Delete \(task.title)? This cannot be undone.")),
            confirmationActionName: .go
        )
        do {
            try await PlannerVoiceAPI.delete(task.id)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: "Deleted \(task.title)."))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Plan my overdue tasks." Works the plan out first, reads it back, and only
/// saves it once confirmed: it moves many tasks at once.
@AppIntent(.tool)
struct PlanOverdueIntent: AppIntent {
    static let title: LocalizedStringResource = "Plan overdue tasks"
    static let description = IntentDescription(
        "Gives every overdue Planner OS task a start time over the next seven days: today first, then each day after, only in free time between 12 pm and 9 pm, at most six hours a day, plus one hour inside office hours. Never double-books. Asks the person to confirm first, saying how many tasks and days. Use it for requests to clear, catch up on, spread out or replan overdue work or the backlog."
    )
    static let openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        do {
            let trial = try await PlannerVoiceAPI.spread(dryRun: true)
            guard trial.placed > 0 else {
                return .result(dialog: IntentDialog(stringLiteral: trial.spoken))
            }
            try await requestConfirmation(
                result: .result(dialog: IntentDialog(stringLiteral: PlannerVoice.spreadQuestion(
                    placed: trial.placed, days: trial.days, left: trial.left))),
                confirmationActionName: .go
            )
            let done = try await PlannerVoiceAPI.spread(dryRun: false)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: done.spoken))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Fix my afternoon." The server does the arithmetic, so this agrees with
/// both apps and the dashboard by construction.
@AppIntent(.tool)
struct FitDayIntent: AppIntent {
    static let title: LocalizedStringResource = "Fit my day"
    static let description = IntentDescription(
        "Gives today's Planner OS tasks that have no time, and tasks whose time has already passed without being done, the earliest free times that do not clash with anything else: between 12 pm and 9 pm, at most six hours of work, plus one hour inside office hours. Never double-books, never places anything in the past, and never moves habits or calendar events. Use it for requests to plan, sort out, fix or replan today."
    )
    static let openAppWhenRun = false

    @Parameter(
        title: "From now on",
        description: "True to only use time from now on; false to use the whole day's free time.",
        default: true
    )
    var fromNow: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("Fit my day \(\.$fromNow)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        do {
            let fitted = try await PlannerVoiceAPI.fit(on: nil, after: fromNow ? "now" : nil)
            reloadWidget()
            return .result(dialog: IntentDialog(stringLiteral: fitted.spoken))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

private func reloadWidget() {
    #if canImport(WidgetKit)
    WidgetCenter.shared.reloadAllTimelines()
    #endif
}

// MARK: - Fixed phrases, for plain Siri, Shortcuts and Spotlight

/// The phrases plain Siri listens for. Siri AI does not need these — it reads
/// the descriptions above — but Shortcuts, Spotlight, the Action button and
/// Siri without the AI preview still do. Apple allows ten.
struct PlannerShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ShowTodayIntent(),
            phrases: [
                "What's on in \(.applicationName)",
                "What's on today in \(.applicationName)",
                "Show today in \(.applicationName)",
                "Show my day in \(.applicationName)",
                "What do I have today in \(.applicationName)",
                "\(.applicationName) today",
            ],
            shortTitle: "Show today",
            systemImageName: "list.bullet.rectangle"
        )
        AppShortcut(
            intent: CurrentTaskIntent(),
            phrases: [
                "What am I doing in \(.applicationName)",
                "What am I doing now in \(.applicationName)",
                "\(.applicationName) now",
            ],
            shortTitle: "What am I doing?",
            systemImageName: "play.circle"
        )
        AppShortcut(
            intent: NextTaskIntent(),
            phrases: [
                "What's next in \(.applicationName)",
                "What is next on \(.applicationName)",
                "\(.applicationName) next",
            ],
            shortTitle: "What's next?",
            systemImageName: "arrow.right.circle"
        )
        AppShortcut(
            intent: RemainingTodayIntent(),
            phrases: [
                "What's left in \(.applicationName)",
                "How much is left in \(.applicationName)",
            ],
            shortTitle: "What's left?",
            systemImageName: "list.bullet"
        )
        AppShortcut(
            intent: AddTaskIntent(),
            phrases: [
                "Add a task to \(.applicationName)",
                "Add to \(.applicationName)",
                "Add an item to \(.applicationName)",
                "New task in \(.applicationName)",
            ],
            shortTitle: "Add a task",
            systemImageName: "plus.circle"
        )
        AppShortcut(
            intent: CompleteTaskIntent(),
            phrases: [
                "Mark a task done in \(.applicationName)",
                "Complete a task in \(.applicationName)",
                "Tick something off in \(.applicationName)",
            ],
            shortTitle: "Complete a task",
            systemImageName: "checkmark.circle"
        )
        AppShortcut(
            intent: FindTasksIntent(),
            phrases: [
                "Find tasks in \(.applicationName)",
                "Search \(.applicationName)",
            ],
            shortTitle: "Find tasks",
            systemImageName: "magnifyingglass"
        )
        AppShortcut(
            intent: MoveMatchingTasksIntent(),
            phrases: [
                "Move tasks in \(.applicationName)",
                "Reschedule tasks in \(.applicationName)",
            ],
            shortTitle: "Move matching tasks",
            systemImageName: "calendar.badge.clock"
        )
        AppShortcut(
            intent: PlanOverdueIntent(),
            phrases: [
                "Plan my overdue tasks in \(.applicationName)",
                "Clear my overdue in \(.applicationName)",
                "Catch up in \(.applicationName)",
            ],
            shortTitle: "Plan overdue",
            systemImageName: "tray.and.arrow.down"
        )
        AppShortcut(
            intent: FitDayIntent(),
            phrases: [
                "Fit my day in \(.applicationName)",
                "Fix my day in \(.applicationName)",
                "Replan \(.applicationName)",
            ],
            shortTitle: "Fit my day",
            systemImageName: "wand.and.stars"
        )
    }
}
#endif
