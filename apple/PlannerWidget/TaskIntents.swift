import AppIntents
import WidgetKit

/// Ticking a task off from the widget itself.
///
/// The widget's copy changes first, so the circle fills under your finger,
/// then the server is told. If the server refuses — no signal, the task
/// deleted elsewhere — the tick is taken back, the same as in the app.
struct ToggleTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Tick off a task"
    static var description = IntentDescription("Mark a Planner OS task done, or put it back.")
    /// The widget is already on screen; opening the app would be a punishment.
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Task") var taskId: String
    @Parameter(title: "Done") var done: Bool

    init() {}

    init(taskId: String, done: Bool) {
        self.taskId = taskId
        self.done = done
    }

    func perform() async throws -> some IntentResult {
        guard PlannerSnapshot.mark(taskId, done: done) else { return .result() }
        do {
            try await PlannerWidgetAPI.setDone(taskId, done)
        } catch {
            PlannerSnapshot.mark(taskId, done: !done)
        }
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}
