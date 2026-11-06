import Foundation
#if canImport(AppIntents)
import AppIntents
#if canImport(WidgetKit)
import WidgetKit
#endif

/// The menu Planner OS puts out front.
///
/// Siri cannot look at a screen and press things. What an app can do by voice
/// is whatever it writes down here, where the system can read it — and the
/// same list serves Siri, the Shortcuts app, Spotlight, the Action button and
/// Siri on the Mac, all from this one file.
///
/// Every one of these is a thin wrapper. What to do and what to say back lives
/// in PlannerVoice, which is plain Foundation and is tested on every run; none
/// of it waits on Xcode to be checked. The reading intents answer from the
/// snapshot the app shares with the widget, so they are instant and work with
/// no signal. The ones that change something go to the server and wait for it,
/// because Siri must not say "done" before it is true.

// MARK: - The task Siri is talking about

/// A task as Siri sees it, so "mark the gym done" can be narrowed to one
/// thing, and so Siri can ask which when a phrase fits more than one.
struct PlannerTaskEntity: AppEntity, Identifiable, Hashable {
    static var typeDisplayRepresentation: TypeDisplayRepresentation { "Task" }
    static var defaultQuery = PlannerTaskQuery()

    var id: String
    var title: String
    var subtitle: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(title: "\(title)", subtitle: "\(subtitle)")
    }

    init(_ task: VoiceTask, today: String) {
        id = task.id
        title = task.title
        subtitle = PlannerVoice.describe(task, today: today)
    }

    init(_ item: PlannerSnapshot.Item, today: String) {
        self.init(
            VoiceTask(id: item.id, title: item.title, date: today,
                      time: PlannerVoice.clockText(item.start), minutes: item.minutes, done: item.done),
            today: today
        )
    }
}

/// How Siri finds the task you named.
///
/// It asks the server, not the widget's snapshot: the snapshot holds today
/// only, so a task dated September — or any of the hundreds not on today —
/// could never be matched from it. With no signal it falls back to today,
/// which is better than refusing outright.
struct PlannerTaskQuery: EntityStringQuery {
    private var today: String { PlannerVoice.dayStamp(Date()) }

    private var nowMinutes: Int {
        let parts = Calendar.current.dateComponents([.hour, .minute], from: Date())
        return (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
    }

    func entities(for identifiers: [String]) async throws -> [PlannerTaskEntity] {
        let stamp = today
        let snapshot = PlannerSnapshot.load()
        let known = (snapshot?.tasks ?? [])
            .filter { identifiers.contains($0.id) }
            .map { PlannerTaskEntity($0, today: stamp) }
        if known.count == identifiers.count { return known }
        // Something is not on today. Find the rest by name, which is all the
        // server lets us search by, then keep the ids that were asked for.
        var found = known
        for id in identifiers where !found.contains(where: { $0.id == id }) {
            if let hit = try? await PlannerVoiceAPI.search(id, limit: 1).tasks.first, hit.id == id {
                found.append(PlannerTaskEntity(hit, today: stamp))
            }
        }
        return found
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
/// the copy is often from yesterday. Reading that as today is how Siri came to
/// give wrong answers. When the copy is not today's, ask the server; when the
/// server cannot be reached either, say so rather than guess.
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
/// line it says is only what the list adds up to. Habits and ticked tasks are
/// on it, in time order, the way the timeline has them.
struct ShowTodayIntent: AppIntent {
    static var title: LocalizedStringResource = "Show today"
    static var description = IntentDescription(
        "Shows everything on today's plan as a list: tasks and habits, done and still to do, with what is under way and what is next. Use this for any question about what is on today."
    )
    static var openAppWhenRun = false

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
struct CurrentTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "What am I doing now?"
    static var description = IntentDescription(
        "Says only the one task under way right now, or the next if nothing is. For the whole day, use Show today."
    )
    /// Nothing here changes anything, so there is no reason to open the app.
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let day = await currentDay() else { return .result(dialog: unreachable) }
        return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.nowSentence(day, at: minutesNow())))
    }
}

/// "What's next?" — skips whatever is already running.
struct NextTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "What's next?"
    static var description = IntentDescription("Says the next thing due to start today.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let day = await currentDay() else { return .result(dialog: unreachable) }
        return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.nextSentence(day, at: minutesNow())))
    }
}

/// "How much is left today?"
struct RemainingTodayIntent: AppIntent {
    static var title: LocalizedStringResource = "How much is left today?"
    static var description = IntentDescription("Says how many tasks are still open and how long they add up to.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let day = await currentDay() else { return .result(dialog: unreachable) }
        return .result(dialog: IntentDialog(stringLiteral: PlannerVoice.remainingSentence(day, at: minutesNow())))
    }
}

// MARK: - Changing

/// "Add call mom at 7pm tomorrow."
///
/// Apple turns the spoken date and time into a real one before it reaches
/// here, so this only has to carry it over in the planner's own counting —
/// including a small-hours slot, which belongs to the evening before.
struct AddTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Add a task"
    static var description = IntentDescription("Adds a task to Planner OS, with a time if you give one.")
    static var openAppWhenRun = false

    @Parameter(title: "Task", requestValueDialog: "What should it be called?")
    var title: String

    @Parameter(title: "When")
    var when: Date?

    @Parameter(title: "Minutes")
    var minutes: Int?

    static var parameterSummary: some ParameterSummary {
        Summary("Add \(\.$title) at \(\.$when)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            return .result(dialog: "A task needs a name.")
        }
        var day: String?
        var clock: Int?
        if let when {
            day = PlannerVoice.dayStamp(when)
            clock = PlannerVoice.minutes(from: when, on: day ?? "")
            // Past midnight counts as the evening before, the way the
            // timeline shows it, so the date steps back with it.
            if let clock, clock >= 24 * 60, let stamped = day {
                day = Self.dayBefore(stamped) ?? stamped
            }
        }
        do {
            let made = try await PlannerVoiceAPI.create(title: name, on: day, at: clock, lasting: minutes)
            reloadWidget()
            if let clock {
                return .result(dialog: "Added \(made.title) at \(PlannerVoice.spokenClock(clock)).")
            }
            return .result(dialog: "Added \(made.title). It is in today's tray with no time yet.")
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }

    private static func dayBefore(_ stamp: String) -> String? {
        var parts = DateComponents()
        let pieces = stamp.split(separator: "-").compactMap { Int($0) }
        guard pieces.count == 3 else { return nil }
        parts.year = pieces[0]; parts.month = pieces[1]; parts.day = pieces[2]
        guard let date = Calendar.current.date(from: parts),
              let earlier = Calendar.current.date(byAdding: .day, value: -1, to: date) else { return nil }
        return PlannerVoice.dayStamp(earlier)
    }
}

/// "Mark the gym done." Siri asks which when a phrase fits more than one.
struct CompleteTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Complete a task"
    static var description = IntentDescription("Ticks a task off, or puts it back.")
    static var openAppWhenRun = false

    @Parameter(title: "Task", requestValueDialog: "Which task?")
    var task: PlannerTaskEntity

    @Parameter(title: "Done", default: true)
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
/// so the assistant can pass them straight into a move without being told
/// twice. "Move all the transcript ones and the Shashank sir ones to today"
/// is this intent twice over and then one move.
struct FindTasksIntent: AppIntent {
    static var title: LocalizedStringResource = "Find tasks"
    static var description = IntentDescription(
        "Finds tasks by a word in their name, anywhere in the planner and on any date."
    )
    static var openAppWhenRun = false

    @Parameter(title: "Word", requestValueDialog: "What should I look for?")
    var text: String

    @Parameter(title: "Include finished", default: false)
    var includeDone: Bool

    static var parameterSummary: some ParameterSummary {
        Summary("Find tasks matching \(\.$text)")
    }

    func perform() async throws -> some IntentResult & ReturnsValue<[PlannerTaskEntity]> & ProvidesDialog {
        let today = PlannerVoice.dayStamp(Date())
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

/// "Move all the transcript tasks to today."
///
/// Always asks first, however it was reached. A word heard wrongly should not
/// silently move forty tasks, and the question names the count so the mistake
/// is obvious before it happens rather than after.
struct MoveTasksIntent: AppIntent {
    static var title: LocalizedStringResource = "Move tasks to a day"
    static var description = IntentDescription("Moves tasks to a day, keeping them untimed.")
    static var openAppWhenRun = false

    @Parameter(title: "Tasks")
    var tasks: [PlannerTaskEntity]

    @Parameter(title: "Day", requestValueDialog: "Which day?")
    var when: Date

    static var parameterSummary: some ParameterSummary {
        Summary("Move \(\.$tasks) to \(\.$when)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let today = PlannerVoice.dayStamp(Date())
        let day = PlannerVoice.dayStamp(when)
        let label = PlannerVoice.dayLabel(day, today: today)
        guard !tasks.isEmpty else {
            return .result(dialog: "There was nothing to move.")
        }
        try await requestConfirmation(
            result: .result(dialog: IntentDialog(
                stringLiteral: PlannerVoice.moveQuestion(count: tasks.count, to: label))),
            confirmationActionName: .go
        )
        do {
            let moved = try await PlannerVoiceAPI.move(tasks.map(\.id), to: day)
            reloadWidget()
            return .result(dialog: IntentDialog(
                stringLiteral: PlannerVoice.movedSentence(count: moved, to: label)))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Move all the transcript tasks to today", in one go.
///
/// The same two steps as finding and then moving, joined up, so plain Siri can
/// do it in a single phrase without the assistant chaining anything. It still
/// asks before it moves.
struct MoveMatchingTasksIntent: AppIntent {
    static var title: LocalizedStringResource = "Move matching tasks to a day"
    static var description = IntentDescription(
        "Finds every task with a word in its name and moves them all to one day."
    )
    static var openAppWhenRun = false

    @Parameter(title: "Word", requestValueDialog: "Which tasks? Give me a word from their names.")
    var text: String

    @Parameter(title: "Day", requestValueDialog: "Which day?")
    var when: Date

    static var parameterSummary: some ParameterSummary {
        Summary("Move tasks matching \(\.$text) to \(\.$when)")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let today = PlannerVoice.dayStamp(Date())
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
            return .result(dialog: IntentDialog(
                stringLiteral: PlannerVoice.movedSentence(count: moved, to: label)))
        } catch let failure as PlannerVoiceAPI.Failure {
            return .result(dialog: IntentDialog(stringLiteral: failure.message))
        }
    }
}

/// "Fix my afternoon." The server does the arithmetic, so this agrees with
/// both apps and the dashboard by construction.
struct FitDayIntent: AppIntent {
    static var title: LocalizedStringResource = "Fit my day"
    static var description = IntentDescription(
        "Gives everything without a time, and every slot already gone by, a time that does not clash."
    )
    static var openAppWhenRun = false

    @Parameter(title: "From now on", default: true)
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

// MARK: - What you can actually say

/// The phrases Siri listens for without the app having been opened first.
///
/// Each one names the app, because that is what plain Siri wants: it matches
/// phrases rather than understanding them. More ways of saying the same thing
/// cost nothing, so the obvious ones are all here.
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
                "Which \(.applicationName) tasks",
            ],
            shortTitle: "Find tasks",
            systemImageName: "magnifyingglass"
        )
        AppShortcut(
            intent: MoveMatchingTasksIntent(),
            phrases: [
                "Move tasks in \(.applicationName)",
                "Move matching tasks in \(.applicationName)",
                "Reschedule tasks in \(.applicationName)",
            ],
            shortTitle: "Move matching tasks",
            systemImageName: "calendar.badge.clock"
        )
        AppShortcut(
            intent: FitDayIntent(),
            phrases: [
                "Fit my day in \(.applicationName)",
                "Fix my day in \(.applicationName)",
                "Sort out my day in \(.applicationName)",
                "Replan \(.applicationName)",
            ],
            shortTitle: "Fit my day",
            systemImageName: "wand.and.stars"
        )
    }
}
#endif
