import Foundation
#if canImport(WidgetKit)
import WidgetKit
#endif

/* What the app leaves for the widget.
 *
 * The widget cannot read the app's files or ask the server anything, so after
 * every sync the app writes today down in the App Group they share. Cheap
 * enough to do on each refresh: a few dozen tasks and a JSON encode.
 */
extension PlannerStore {
    func publishWidget() {
        // The widget ticks tasks off itself, so it needs the server as well as
        // the day. Cleared on disconnect, with everything else.
        if let connection {
            WidgetConnection.save(server: connection.base.absoluteString, key: connection.key)
        } else {
            WidgetConnection.clear()
        }

        let day = logicalToday
        let tasks = (days[day]?.items ?? [])
            .filter { $0.time != nil }
            .sorted { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) }
            .map {
                PlannerSnapshot.Item(id: $0.id, title: $0.title, start: $0.clockMinutes,
                                     minutes: $0.minutes, done: $0.done,
                                     palette: paletteIndex($0, count: 8))
            }
        PlannerSnapshot.save(PlannerSnapshot(date: day, updated: Date(),
                                             tasks: tasks, waiting: focusOverdue.count))
        #if canImport(WidgetKit)
        WidgetCenter.shared.reloadAllTimelines()
        #endif
    }
}
