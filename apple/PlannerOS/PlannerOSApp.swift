import SwiftUI
import UserNotifications
#if os(iOS)
import BackgroundTasks
#endif

@main
struct PlannerOSApp: App {
    @State private var store = PlannerStore()
    #if os(macOS)
    @AppStorage(FloatingClock.shownKey) private var showClock = true
    #endif

    init() {
        UNUserNotificationCenter.current().delegate = NotificationPresenter.shared
    }

    var body: some Scene {
        // No id: macOS saves the window under the group's name, and a new name
        // means no window at the first launch after updating.
        WindowGroup {
            RootView()
                .environment(store)
        }
        #if os(iOS)
        .backgroundTask(.appRefresh(BackgroundRefresh.identifier)) {
            await BackgroundRefresh.run(store: store)
        }
        #endif
        #if os(macOS)
        .defaultSize(width: 1100, height: 760)
        .commands {
            CommandGroup(after: .windowArrangement) {
                Toggle("Floating Clock", isOn: $showClock)
                    .keyboardShortcut("k", modifiers: [.command, .shift])
            }
        }
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
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    static func cancel() {
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: identifier)
    }

    @MainActor
    static func run(store: PlannerStore) async {
        guard store.connection != nil else { cancel(); return }
        schedule()
        await store.refreshInBackground()
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
