import AppIntents
import WidgetKit

/// Ticking a task off from the widget itself.
///
/// A widget redraws only when this action has finished, so it must not wait
/// for the server: it changes the widget's own copy, notes the tick as still
/// to be sent, and finishes. The circle fills as fast as it does in the app.
/// Sending happens straight afterwards and again from anywhere that gets the
/// chance — see PendingTicks. A tick the server refuses is taken back.
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
        PendingTicks.add(taskId, done: done)
        WidgetCenter.shared.reloadAllTimelines()
        // Not awaited: waiting here is what kept the circle empty for seconds.
        Task.detached(priority: .userInitiated) {
            if await PendingTicks.flush() { WidgetCenter.shared.reloadAllTimelines() }
        }
        return .result()
    }
}
