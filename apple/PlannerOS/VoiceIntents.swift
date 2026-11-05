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
    var start: Int
    var done: Bool

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(title)",
            subtitle: "\(done ? "Done" : PlannerVoice.spokenClock(start))"
        )
    }

    init(_ item: PlannerSnapshot.Item) {
        id = item.id
        title = item.title
        start = item.start
        done = item.done
    }
}

struct PlannerTaskQuery: EntityStringQuery {
    private var nowMinutes: Int {
        let parts = Calendar.current.dateComponents([.hour, .minute], from: Date())
        return (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
    }

    func entities(for identifiers: [String]) async throws -> [PlannerTaskEntity] {
        let snapshot = PlannerSnapshot.load()
        return (snapshot?.tasks ?? []).filter { identifiers.contains($0.id) }.map(PlannerTaskEntity.init)
    }

    /// What Siri offers when it has to ask "which one?".
    func entities(matching string: String) async throws -> [PlannerTaskEntity] {
        PlannerVoice.candidates(PlannerSnapshot.load(), matching: string, at: nowMinutes)
            .map(PlannerTaskEntity.init)
    }

    func suggestedEntities() async throws -> [PlannerTaskEntity] {
        PlannerVoice.candidates(PlannerSnapshot.load(), matching: "", at: nowMinutes)
            .prefix(8)
            .map(PlannerTaskEntity.init)
    }
}

private func minutesNow() -> Int {
    let parts = Calendar.current.dateComponents([.hour, .minute], from: Date())
    return (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
}

// MARK: - Asking

/// "What am I doing?" — answered from the shared snapshot, so it is instant
/// and still right with no signal.
struct CurrentTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "What am I doing?"
    static var description = IntentDescription("Says what is under way, or what is next.")
    /// Nothing here changes anything, so there is no reason to open the app.
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let line = PlannerVoice.nowSentence(PlannerSnapshot.load(), at: minutesNow())
        return .result(dialog: IntentDialog(stringLiteral: line))
    }
}

/// "What's next?" — skips whatever is already running.
struct NextTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "What's next?"
    static var description = IntentDescription("Says the next thing due to start today.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let line = PlannerVoice.nextSentence(PlannerSnapshot.load(), at: minutesNow())
        return .result(dialog: IntentDialog(stringLiteral: line))
    }
}

/// "How much is left today?"
struct RemainingTodayIntent: AppIntent {
    static var title: LocalizedStringResource = "How much is left today?"
    static var description = IntentDescription("Says how many tasks are still open and how long they add up to.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let line = PlannerVoice.remainingSentence(PlannerSnapshot.load(), at: minutesNow())
        return .result(dialog: IntentDialog(stringLiteral: line))
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
            intent: CurrentTaskIntent(),
            phrases: [
                "What am I doing in \(.applicationName)",
                "What's on in \(.applicationName)",
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
