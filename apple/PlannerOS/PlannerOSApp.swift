import SwiftUI
import UserNotifications
#if os(iOS)
import BackgroundTasks
#endif

@main
struct PlannerOSApp: App {
    @State private var store = PlannerStore()

    init() {
        UNUserNotificationCenter.current().delegate = NotificationPresenter.shared
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
        }
        #if os(iOS)
        .backgroundTask(.appRefresh(BackgroundRefresh.identifier)) {
            await BackgroundRefresh.run()
        }
        #endif
        #if os(macOS)
        .defaultSize(width: 1100, height: 760)
        #endif
    }
}

#if os(iOS)
/// Keeps reminders current when the app has not been opened for a while. iOS
/// decides when this actually runs; opening the app always syncs.
enum BackgroundRefresh {
    static let identifier = (Bundle.main.bundleIdentifier ?? "dev.planneros.planner") + ".refresh"

    static func schedule() {
        let request = BGAppRefreshTaskRequest(identifier: identifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 2 * 3600)
        try? BGTaskScheduler.shared.submit(request)
    }

    static func run() async {
        schedule()
        guard let connection = ConnectionStore.load() else { return }
        let zone = TimeZone(identifier: UserDefaults.standard.string(forKey: "timezone") ?? "Asia/Kolkata") ?? .current
        await Reminders.sync(api: PlannerAPI(connection: connection), timeZone: zone)
    }
}
#endif

extension View {
    /// A compact title in sheets on iPhone and iPad.
    func inlineTitle() -> some View {
        #if os(iOS)
        navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }

    /// Mac sheets size to their content, which is too small for a form.
    func macSheetSize() -> some View {
        #if os(macOS)
        frame(minWidth: 440, minHeight: 520)
        #else
        self
        #endif
    }

    /// The Timeline draws its own header, as Structured does.
    func hiddenNavigationBar() -> some View {
        #if os(iOS)
        toolbar(.hidden, for: .navigationBar)
        #else
        self
        #endif
    }

    func urlEntry() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never).keyboardType(.URL).autocorrectionDisabled()
        #else
        autocorrectionDisabled()
        #endif
    }
}
