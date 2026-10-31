import SwiftUI

enum Screen: Hashable { case focus, timeline, settings }

/// What the task editor opens for: an existing task, or a new one with a suggested day and time.
struct EditorRequest: Identifiable {
    let id = UUID()
    var task: PlannerTask?
    var date: String?
    var time: String?
}

/// Focus · Timeline · Settings along the bottom, opening on the Timeline, with
/// a floating + for adding tasks.
@MainActor
struct RootView: View {
    @Environment(PlannerStore.self) private var store
    @Environment(\.scenePhase) private var phase
    @State private var screen: Screen = .timeline
    @State private var editor: EditorRequest?
    @State private var showMilestones = false

    var body: some View {
        Group {
            if store.connection == nil {
                NavigationStack { SettingsView(firstRun: true) }
            } else {
                TabView(selection: $screen) {
                    NavigationStack {
                        FocusView(screen: $screen, editor: $editor)
                            .toolbar { focusToolbar }
                            .overlay(alignment: .bottomTrailing) {
                                AddButton { editor = EditorRequest(date: store.logicalToday) }
                            }
                    }
                    .tabItem { Label("Focus", systemImage: "tray") }
                    .tag(Screen.focus)

                    NavigationStack { TodayView(editor: $editor) }
                        .tabItem { Label("Timeline", systemImage: "list.bullet.below.rectangle") }
                        .tag(Screen.timeline)

                    NavigationStack { SettingsView(firstRun: false) }
                        .tabItem { Label("Settings", systemImage: "gearshape") }
                        .tag(Screen.settings)
                }
            }
        }
        .overlay(alignment: .bottom) { ToastView() }
        .sheet(item: $editor) { request in
            NavigationStack { TaskEditor(request: request) }
                .environment(store)
        }
        .sheet(isPresented: $showMilestones) {
            NavigationStack { MilestonesView() }
                .environment(store)
        }
        .task { await store.start() }
        .task { await tick() }
        .onChange(of: phase) { _, phase in
            if phase == .active {
                store.now = Date()
                Task { await store.refreshAll() }
            }
            #if os(iOS)
            if phase == .background { BackgroundRefresh.schedule() }
            #endif
        }
    }

    @ToolbarContentBuilder
    private var focusToolbar: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Menu {
                Button { showMilestones = true } label: { Label("Milestones", systemImage: "flag") }
                Button { Task { await store.refreshAll() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
            } label: {
                Label("More", systemImage: "ellipsis.circle")
            }
        }
    }

    /// Moves "now" along so overdue cards and the now line stay current.
    private func tick() async {
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 60_000_000_000)
            store.now = Date()
        }
    }
}

@MainActor
struct ToastView: View {
    @Environment(PlannerStore.self) private var store

    var body: some View {
        if let message = store.toast {
            Text(message)
                .font(.callout)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                .padding(.horizontal)
                .padding(.bottom, 70)
                .onTapGesture { store.toast = nil }
                .transition(.opacity)
        }
    }
}

@MainActor
struct MilestonesView: View {
    @Environment(PlannerStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let today = store.calendarToday
        let rows = store.milestoneRows.sorted { ($0.targetDate ?? "9999-12-31", $0.name) < ($1.targetDate ?? "9999-12-31", $1.name) }
        List {
            if rows.isEmpty { Text("No milestones yet.").foregroundStyle(.secondary) }
            ForEach(rows) { row in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(row.name).font(.body.weight(.medium))
                        if let status = row.status {
                            Text(status.replacingOccurrences(of: "_", with: " ").capitalized)
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if let target = row.targetDate {
                        let days = Civil.between(today, target)
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(Civil.dayMonth(target)).font(.callout.monospacedDigit())
                            Text(days < 0 ? "\(-days)d past" : days == 0 ? "today" : "in \(days)d")
                                .font(.caption)
                                .foregroundStyle(days < 0 && row.status != "done" ? Color.red : Color.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("Milestones")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
        }
        .task { await store.refreshMilestones() }
        .macSheetSize()
    }
}
