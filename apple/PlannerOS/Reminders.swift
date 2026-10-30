import Foundation
import UserNotifications

/// Local notifications ten minutes before each timed task. No push service is
/// involved: the coming week is queued on the device whenever the app syncs
/// (on open, after a change, and in background refresh on iPhone and iPad), and
/// the system delivers them even when the app is closed.
enum Reminders {
    private static let enabledKey = "reminders"
    static let horizonDays = 7

    static var enabled: Bool {
        get { UserDefaults.standard.object(forKey: enabledKey) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: enabledKey) }
    }

    static func requestPermission() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    static func status() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// Reads the next seven days and replaces the queued reminders with them.
    /// When nothing could be read, the reminders already queued stay.
    static func sync(api: PlannerAPI, timeZone: TimeZone, now: Date = Date()) async {
        let center = UNUserNotificationCenter.current()
        guard enabled else { center.removeAllPendingNotificationRequests(); return }
        let allowed = await status()
        guard allowed == .authorized || allowed == .provisional else { return }
        let start = Civil.today(in: timeZone, now: now)
        let dates = (0..<horizonDays).map { Civil.add(start, days: $0) }
        let days: [DayView] = await withTaskGroup(of: DayView?.self) { group in
            for date in dates {
                group.addTask { try? await api.get("/v2/day?date=\(date)") as DayView }
            }
            var views: [DayView] = []
            for await view in group { if let view { views.append(view) } }
            return views
        }
        guard !days.isEmpty else { return }
        let zone = TimeZone(identifier: days[0].timezone) ?? timeZone
        center.removeAllPendingNotificationRequests()
        for reminder in planReminders(days, now: now, timeZone: zone) {
            try? await center.add(request(reminder, zone))
        }
    }

    static func clear() { UNUserNotificationCenter.current().removeAllPendingNotificationRequests() }

    static func sendTest() async {
        let content = UNMutableNotificationContent()
        content.title = "Planner OS reminders work"
        content.body = "Tasks will remind you \(reminderLeadMinutes) minutes before they start."
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 5, repeats: false)
        try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "test", content: content, trigger: trigger))
    }

    private static func request(_ reminder: Reminder, _ zone: TimeZone) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = reminder.title
        content.body = reminder.body
        content.sound = .default
        content.threadIdentifier = "planner-tasks"
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        var when = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: reminder.fire)
        when.timeZone = zone
        return UNNotificationRequest(identifier: reminder.id, content: content,
                                     trigger: UNCalendarNotificationTrigger(dateMatching: when, repeats: false))
    }
}

/// Shows reminders as banners while the app is open, too.
final class NotificationPresenter: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationPresenter()

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }
}
