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
    static func sync(api: PlannerAPI, timeZone: TimeZone, overdue: [RankedTask] = [], now: Date = Date()) async {
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
        await scheduleDaily(days, overdue: overdue, timeZone: zone, now: now)
    }

    /// The morning callout and tonight's report, worded from what the app
    /// knows now; every sync — and every tick on the widget or through Siri —
    /// words them again.
    static func scheduleDaily(_ days: [DayView], overdue: [RankedTask], timeZone: TimeZone, now: Date) async {
        let center = UNUserNotificationCenter.current()
        let today = Civil.logicalToday(in: timeZone, now: now)
        let byDate = Dictionary(days.map { ($0.date, $0) }, uniquingKeysWith: { first, _ in first })

        if let items = byDate[today]?.items {
            let report = HarshReminders.Report(date: today, items: reportItems(items))
            HarshReminders.saveReport(report)
            await HarshReminders.scheduleEvening(report, timeZone: timeZone, now: now)
        }

        // Tomorrow morning — or this morning, if it is not yet eleven.
        var morningDay = Civil.today(in: timeZone, now: now)
        if let at = HarshReminders.moment(morningDay, HarshReminders.morningMinute, in: timeZone), at <= now {
            morningDay = Civil.add(morningDay, days: 1)
        }
        center.removePendingNotificationRequests(withIdentifiers: [HarshReminders.morningId])
        let planned = (byDate[morningDay]?.items ?? []).filter { !$0.fromCalendar && !$0.done }
        let first = planned.filter { $0.time != nil }.min { $0.clockMinutes < $1.clockMinutes }
        let worst = overdue.compactMap { ranked -> (title: String, daysLate: Int)? in
            guard let since = overdueSince(ranked.task, ranked.reason) else { return nil }
            return (ranked.task.title, Civil.days(from: since, to: morningDay))
        }.max { $0.daysLate < $1.daysLate }
        if let text = HarshReminders.morning(overdue: overdue.count, worst: worst, planned: planned.count,
                                             first: first.map { ($0.title, $0.clockMinutes) }),
           let fire = HarshReminders.moment(morningDay, HarshReminders.morningMinute, in: timeZone) {
            try? await center.add(HarshReminders.request(HarshReminders.morningId, text, at: fire, timeZone: timeZone))
        }
    }

    /// A day's items as the evening report counts them: calendar events are
    /// appointments, not work, and are left out.
    static func reportItems(_ items: [PlannerTask]) -> [HarshReminders.ReportItem] {
        items.filter { !$0.fromCalendar }.map {
            HarshReminders.ReportItem(id: $0.id, title: $0.title, start: $0.time == nil ? nil : $0.clockMinutes, done: $0.done)
        }
    }

    static func clear() { UNUserNotificationCenter.current().removeAllPendingNotificationRequests() }

    /// The packaged two-note pop, so a reminder is heard across a room rather
    /// than lost among every other app using the system default. iOS plays a
    /// bundled sound at the ringer's volume; a louder-than-everything alert
    /// needs Apple's critical-alert entitlement, which a free account cannot have.
    static let alert: UNNotificationSound = {
        guard Bundle.main.url(forResource: "task_reminder", withExtension: "wav") != nil else { return .default }
        return UNNotificationSound(named: UNNotificationSoundName("task_reminder.wav"))
    }()

    /// Why a reminder would arrive in silence on this phone, in one sentence.
    /// iOS will not say why it muted something, so the settings that decide it
    /// are read back instead of guessed at.
    static func soundReport() async -> String {
        if Bundle.main.url(forResource: "task_reminder", withExtension: "wav") == nil {
            return "The sound file is not in this build, so reminders fall back to the default sound."
        }
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        switch settings.authorizationStatus {
        case .denied:
            return "Notifications are off for Planner OS in iOS Settings, Notifications."
        case .notDetermined:
            return "Notifications have not been allowed yet. Send a test notification to be asked."
        default:
            break
        }
        if settings.soundSetting == .disabled {
            return "Sounds are off for Planner OS in iOS Settings, Notifications."
        }
        if settings.alertSetting == .disabled {
            return "Banners are off for Planner OS in iOS Settings, Notifications."
        }
        return "Ready, playing task_reminder. It uses the ringer volume, so the side switch, "
            + "a Focus and the volume buttons still silence it."
    }

    static func sendTest() async {
        let content = UNMutableNotificationContent()
        content.title = "Planner OS reminders work"
        content.body = "\(reminderLeadMinutes) minutes before each task, then again until you tick it."
        content.sound = alert
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 5, repeats: false)
        try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "test", content: content, trigger: trigger))
    }

    private static func request(_ reminder: Reminder, _ zone: TimeZone) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = reminder.title
        content.body = reminder.body
        content.sound = alert
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
