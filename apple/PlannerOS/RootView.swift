import SwiftUI

enum Screen: Hashable { case focus, timeline, settings }

/// What the task editor opens for: an existing task, or a new one with a suggested day and time.
struct EditorRequest: Identifiable {
    let id = UUID()
    var task: PlannerTask?
    var date: String?
    var time: String?
}

/// As in Structured: the screen above, and along the bottom a floating pill of
/// places (Inbox · Timeline · Settings) with a round + beside it that turns into
/// a bin while a task is being dragged. Opens on the Timeline.
@MainActor
struct RootView: View {
    @Environment(PlannerStore.self) private var store
    @Environment(\.scenePhase) private var phase
    @State private var screen: Screen = .timeline
    @State private var editor: EditorRequest?
    @State private var showMilestones = false
    /// Whether a held task is over the bin; the timeline says, as it tracks the drag.
    @State private var overBin = false

    var body: some View {
        Group {
            if store.connection == nil {
                NavigationStack { SettingsView(firstRun: true) }
            } else {
                ZStack(alignment: .bottom) {
                    Group {
                        switch screen {
                        case .focus:
                            NavigationStack { FocusView(screen: $screen, editor: $editor).toolbar { focusToolbar } }
                        case .timeline:
                            NavigationStack { TodayView(editor: $editor, overBin: $overBin) }
                        case .settings:
                            NavigationStack { SettingsView(firstRun: false) }
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .safeAreaInset(edge: .bottom) { Color.clear.frame(height: 72) }
                    BottomBar(screen: $screen, dragging: store.draggingID != nil, overBin: $overBin,
                              onAdd: { editor = EditorRequest(date: screen == .timeline ? store.selectedDate : store.logicalToday) })
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
        // An alert, not a confirmation dialog: on iOS 27 that is a popover
        // pointing at nothing, with no Cancel. The task is handed to it, as
        // closing it clears confirmingDelete before the button runs.
        .alert(deleteQuestion, isPresented: Binding(
            get: { store.confirmingDelete != nil }, set: { if !$0 { store.confirmingDelete = nil } }),
               presenting: store.confirmingDelete) { task in
            Button(task.habit ? "Skip" : "Delete", role: .destructive) { Task { await store.delete(task) } }
            Button("Cancel", role: .cancel) {}
        } message: { task in
            Text(task.habit ? "Only this day goes; the habit carries on every other day." : "This removes it for good.")
        }
        #if os(macOS)
        .onChange(of: store.connection, initial: true) {
            FloatingClock.shared.attach(store: store)
        }
        #endif
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

    private var deleteQuestion: String {
        guard let task = store.confirmingDelete else { return "" }
        return task.habit ? "Skip “\(task.title)” for this day?" : "Delete “\(task.title)”?"
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

    /// Moves "now" along so overdue cards and the now line stay current, and
    /// takes the chance to see what else has changed — a change made on the
    /// phone reaches a Mac window that has been open for hours.
    private func tick() async {
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 60_000_000_000)
            store.now = Date()
            await store.refreshIfStale()
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

/// The floating pill of places and the round + beside it, which is a bin while
/// a task is dragged: drop on it to delete.
@MainActor
struct BottomBar: View {
    @Environment(PlannerStore.self) private var store
    @Binding var screen: Screen
    let dragging: Bool
    @Binding var overBin: Bool
    let onAdd: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            HStack(spacing: 0) {
                tab("Inbox", "tray.fill", .focus)
                tab("Timeline", "list.bullet", .timeline)
                tab("Settings", "gearshape.fill", .settings)
            }
            .frame(height: 60)
            .background(Palette.card, in: Capsule())
            .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
            Button(action: onAdd) {
                Image(systemName: dragging ? "trash.fill" : "plus")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 60, height: 60)
                    .background(Circle().fill(dragging ? Color.red : Palette.accent))
                    .scaleEffect(overBin ? 1.12 : 1)
                    .shadow(color: .black.opacity(0.18), radius: 8, y: 4)
            }
            .buttonStyle(.hitArea)
            .keyboardShortcut("n", modifiers: .command)
            .accessibilityLabel(dragging ? "Drop here to delete" : "Add task")
            // The timeline tracks a held task itself, so it needs to know where the bin is.
            .background {
                GeometryReader { space in
                    let frame = space.frame(in: .global)
                    Color.clear
                        .onAppear { store.binFrame = frame }
                        .onChange(of: frame) { _, moved in store.binFrame = moved }
                }
            }
            .animation(.snappy, value: dragging)
            .animation(.snappy, value: overBin)
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 6)
    }

    private func tab(_ label: String, _ icon: String, _ target: Screen) -> some View {
        Button { screen = target } label: {
            VStack(spacing: 3) {
                Image(systemName: icon).font(.system(size: 19, weight: .semibold))
                Text(label).font(.caption2.weight(screen == target ? .semibold : .medium))
            }
            .foregroundStyle(screen == target ? Palette.accent : Color.primary)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.hitArea)
        .accessibilityLabel(label)
        .accessibilityAddTraits(screen == target ? .isSelected : [])
    }
}
