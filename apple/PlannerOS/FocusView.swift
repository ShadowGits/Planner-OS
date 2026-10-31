import SwiftUI

private struct FocusItem: Identifiable {
    var task: PlannerTask
    var reason: FocusReason?
    var id: String { task.id }
}

/// Overdue cards ranked by deadline, what is left today, and the week as
/// milestone rows: the same Focus board as the web dashboard and Android.
@MainActor
struct FocusView: View {
    @Environment(PlannerStore.self) private var store
    @Binding var screen: Screen
    @Binding var editor: EditorRequest?
    @State private var showAll = false
    @State private var selecting = false
    @State private var selected: Set<String> = []
    @State private var dateTargets: [PlannerTask] = []
    @State private var pickingDate = false
    @State private var dropTargets: [PlannerTask] = []
    @State private var confirmingDrop = false

    private let preview = 9
    private let columns = [GridItem(.adaptive(minimum: 270), spacing: 12, alignment: .top)]

    var body: some View {
        let now = store.moment
        let overdue = store.focusOverdue.map { FocusItem(task: $0.task, reason: $0.reason) }
        let today = store.focusTodayTasks.map { FocusItem(task: $0, reason: nil) }
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if store.inbox == nil && store.loading {
                    ProgressView().frame(maxWidth: .infinity)
                }
                overdueSection(overdue, now)
                section("Today", icon: "sun.max", count: today.count) {
                    if today.isEmpty {
                        Text("Nothing else planned for today.").foregroundStyle(.secondary)
                    } else {
                        cards(today, now)
                    }
                }
                WeekMatrix(rows: store.weekRows, weekStart: store.week?.weekStart, today: store.calendarToday,
                           onWeek: { anchor in Task { await store.refreshWeek(anchor: anchor) } },
                           onDay: { day in store.selectedDate = day; screen = .timeline })
            }
            .padding()
            .frame(maxWidth: 1200, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("Focus")
        .refreshable { await store.refreshAll() }
        .safeAreaInset(edge: .bottom) {
            if selecting && !selected.isEmpty { bulkBar(overdue.map(\.task)) }
        }
        .toolbar {
            ToolbarItem(placement: .navigation) {
                if !overdue.isEmpty {
                    Button(selecting ? "Done" : "Select") {
                        selecting.toggle()
                        if !selecting { selected = [] }
                    }
                }
            }
        }
        .confirmationDialog("Drop \(plural(dropTargets.count, "task"))?", isPresented: $confirmingDrop, titleVisibility: .visible) {
            Button("Drop", role: .destructive) {
                let targets = dropTargets
                Task {
                    await store.drop(targets)
                    finishSelection()
                }
            }
        } message: {
            Text("They are closed as skipped, not deleted.")
        }
        .sheet(isPresented: $pickingDate) {
            MoveDateSheet(count: dateTargets.count, today: store.calendarToday, timeZone: store.timeZone) { date in
                let targets = dateTargets
                Task {
                    await store.move(targets, to: date)
                    finishSelection()
                }
            }
        }
    }

    private func summary(_ overdue: Int, _ today: Int) -> String {
        "\(overdue) overdue · \(today) left today"
    }

    @ViewBuilder
    private func overdueSection(_ overdue: [FocusItem], _ now: Moment) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Label("Overdue", systemImage: "exclamationmark.circle")
                    .font(.headline)
                    .foregroundStyle(overdue.isEmpty ? Color.secondary : Color.red)
                Text(summary(overdue.count, store.focusTodayTasks.count)).font(.subheadline).foregroundStyle(.secondary)
                Spacer()
                if overdue.count > preview {
                    Button(showAll ? "Top \(preview)" : "Show all \(overdue.count)") { showAll.toggle() }
                        .font(.subheadline)
                        .buttonStyle(.borderless)
                }
            }
            if overdue.isEmpty {
                Text("Nothing overdue.").foregroundStyle(.secondary)
            } else if showAll {
                ForEach(FocusReason.allCases, id: \.self) { reason in
                    let group = overdue.filter { $0.reason == reason }
                    if !group.isEmpty {
                        Text("\(reason.heading) · \(group.count)")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.top, 4)
                        cards(group, now)
                    }
                }
            } else {
                cards(Array(overdue.prefix(preview)), now)
            }
        }
    }

    private func section<Content: View>(_ title: String, icon: String, count: Int, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Label(title, systemImage: icon).font(.headline)
                Text("\(count)").font(.subheadline).foregroundStyle(.secondary)
            }
            content()
        }
    }

    private func cards(_ items: [FocusItem], _ now: Moment) -> some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
            ForEach(items) { item in card(item, now) }
        }
    }

    private func card(_ item: FocusItem, _ now: Moment) -> some View {
        let task = item.task
        let selectable = item.reason != nil
        return TaskCard(
            task: task,
            reason: item.reason,
            badge: item.reason.map { lateness(task, $0, now) } ?? (task.time ?? "Any time today"),
            context: store.context(task),
            soon: milestoneSoon(task, store.milestones, now),
            selecting: selecting && selectable,
            selected: selected.contains(task.id),
            onTap: {
                if selecting && selectable { toggle(task) } else { editor = EditorRequest(task: task) }
            },
            onLongPress: {
                guard selectable else { return }
                selecting = true
                selected.insert(task.id)
            },
            onDone: { Task { await store.setDone(task) } },
            onTomorrow: { Task { await store.move([task], to: Civil.add(store.calendarToday, days: 1)) } },
            onPickDate: { dateTargets = [task]; pickingDate = true },
            onDrop: { dropTargets = [task]; confirmingDrop = true }
        )
    }

    private func toggle(_ task: PlannerTask) {
        if selected.contains(task.id) { selected.remove(task.id) } else { selected.insert(task.id) }
    }

    private func finishSelection() {
        selected = []
        selecting = false
    }

    private func bulkBar(_ overdue: [PlannerTask]) -> some View {
        let chosen = overdue.filter { selected.contains($0.id) }
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("\(chosen.count) selected").font(.subheadline.weight(.semibold))
                Spacer()
                Button("All") { selected = Set(overdue.map(\.id)) }
                Button("Clear") { selected = [] }
            }
            .buttonStyle(.borderless)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(quickMoveDates(store.calendarToday)) { option in
                        Button(option.label) {
                            Task {
                                await store.move(chosen, to: option.date)
                                finishSelection()
                            }
                        }
                    }
                    Button { dateTargets = chosen; pickingDate = true } label: { Label("Date", systemImage: "calendar") }
                    Button(role: .destructive) { dropTargets = chosen; confirmingDrop = true } label: { Label("Drop", systemImage: "xmark") }
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(12)
        .background(.bar)
    }
}

/// A Focus card: what it is, how late, and one tap to act on it.
@MainActor
struct TaskCard: View {
    let task: PlannerTask
    let reason: FocusReason?
    let badge: String
    let context: String?
    let soon: String?
    let selecting: Bool
    let selected: Bool
    let onTap: () -> Void
    let onLongPress: () -> Void
    let onDone: () -> Void
    let onTomorrow: () -> Void
    let onPickDate: () -> Void
    let onDrop: () -> Void

    private var tint: Color {
        switch reason {
        case .deadline: return .red
        case .missedSlot: return .orange
        case .neverScheduled: return .gray
        case nil: return .accentColor
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                if selecting {
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(selected ? Color.accentColor : Color.secondary)
                }
                if isPinned(task) {
                    Image(systemName: "pin.fill").font(.caption).foregroundStyle(.pink)
                        .accessibilityLabel(task.starred ? "Starred" : "High priority")
                }
                Text(task.title).font(.subheadline.weight(.semibold)).lineLimit(2)
                Spacer(minLength: 0)
            }
            HStack(spacing: 6) {
                Text(badge)
                    .font(.caption.weight(.medium))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(tint.opacity(0.12), in: Capsule())
                    .foregroundStyle(tint)
                Label("\(task.minutes)m", systemImage: "clock").font(.caption).foregroundStyle(.secondary)
                if let soon { Text(soon).font(.caption.weight(.medium)).foregroundStyle(.purple) }
            }
            if let context {
                Text(context).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Divider()
            HStack(spacing: 2) {
                action("Done", "checkmark", .green, onDone)
                action("Tomorrow", "arrow.right", .accentColor, onTomorrow)
                action("Date", "calendar", .accentColor, onPickDate)
                Spacer(minLength: 0)
                action("Drop", "xmark", .secondary, onDrop)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.secondary.opacity(0.07)))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(selected ? Color.accentColor : Color.secondary.opacity(0.2), lineWidth: selected ? 2 : 1)
        )
        .contentShape(RoundedRectangle(cornerRadius: 12))
        .onTapGesture(perform: onTap)
        // A long-press gesture here would stop the list scrolling on iOS 18
        // and later; the system's context menu does not.
        .contextMenu {
            Button { onLongPress() } label: { Label("Select", systemImage: "checkmark.circle") }
            Button { onDone() } label: { Label("Done", systemImage: "checkmark") }
            Button { onTomorrow() } label: { Label("Tomorrow", systemImage: "arrow.right") }
            Button { onPickDate() } label: { Label("Pick a date", systemImage: "calendar") }
            Button(role: .destructive) { onDrop() } label: { Label("Drop", systemImage: "xmark") }
        }
    }

    private func action(_ title: String, _ icon: String, _ color: Color, _ perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Label(title, systemImage: icon).font(.caption.weight(.medium))
        }
        .buttonStyle(.borderless)
        .foregroundStyle(color)
        .disabled(selecting)
    }
}

/// The week as milestone rows: tap a day to open it on Today.
@MainActor
struct WeekMatrix: View {
    let rows: [FocusWeekRow]
    let weekStart: String?
    let today: String
    let onWeek: (String) -> Void
    let onDay: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Week", systemImage: "calendar").font(.headline)
                Spacer()
                if let weekStart {
                    Button { onWeek(Civil.add(weekStart, days: -7)) } label: { Image(systemName: "chevron.left") }
                        .accessibilityLabel("Previous week")
                    Text("\(Civil.dayMonth(weekStart)) – \(Civil.dayMonth(Civil.add(weekStart, days: 6)))")
                        .font(.subheadline.monospacedDigit())
                        .foregroundStyle(.secondary)
                    Button { onWeek(Civil.add(weekStart, days: 7)) } label: { Image(systemName: "chevron.right") }
                        .accessibilityLabel("Next week")
                }
            }
            .buttonStyle(.borderless)
            if let weekStart {
                Grid(alignment: .leading, horizontalSpacing: 4, verticalSpacing: 6) {
                    GridRow {
                        Color.clear.frame(width: 1, height: 1)
                        ForEach(0..<7, id: \.self) { offset in
                            dayHeader(Civil.add(weekStart, days: offset))
                        }
                    }
                    if rows.isEmpty {
                        GridRow {
                            Text("Nothing planned this week.").foregroundStyle(.secondary).gridCellColumns(8)
                        }
                    }
                    ForEach(rows) { row in
                        GridRow {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(row.label).font(.caption.weight(.semibold)).lineLimit(1)
                                if let sublabel = row.sublabel {
                                    Text(sublabel).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                                }
                            }
                            .frame(minWidth: 84, maxWidth: 180, alignment: .leading)
                            ForEach(0..<7, id: \.self) { offset in
                                cell(row.cells[offset], day: Civil.add(weekStart, days: offset))
                            }
                        }
                    }
                }
            } else {
                Text("Loading the week…").foregroundStyle(.secondary)
            }
        }
    }

    private func dayHeader(_ day: String) -> some View {
        Button { onDay(day) } label: {
            VStack(spacing: 0) {
                Text(String(Civil.short(day).prefix(3))).font(.caption2)
                Text(String(day.suffix(2))).font(.caption.weight(day == today ? .bold : .regular).monospacedDigit())
            }
            .frame(maxWidth: .infinity)
            .foregroundStyle(day == today ? Color.accentColor : Color.secondary)
        }
        .buttonStyle(.plain)
    }

    private func cell(_ tasks: [PlannerTask], day: String) -> some View {
        let open = tasks.filter { !$0.done }.count
        let fill: Color = tasks.isEmpty ? .clear : (open == 0 ? Color.green.opacity(0.18) : Color.accentColor.opacity(0.18))
        return Button { onDay(day) } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 6).fill(fill)
                if !tasks.isEmpty {
                    Text(open == 0 ? "✓" : "\(open)").font(.caption.weight(.semibold))
                }
            }
            .frame(maxWidth: .infinity, minHeight: 28)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(Civil.short(day)): \(open) open of \(tasks.count)")
    }
}

/// Pick any day from today on; the tasks land there untimed.
@MainActor
struct MoveDateSheet: View {
    let count: Int
    let today: String
    let timeZone: TimeZone
    let onMove: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date()

    var body: some View {
        NavigationStack {
            Form {
                DatePicker("Move to", selection: $date, in: Civil.pickerDate(today, in: timeZone)..., displayedComponents: .date)
                    .datePickerStyle(.graphical)
            }
            .formStyle(.grouped)
            .navigationTitle("Move \(plural(count, "task"))")
            .inlineTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Move") {
                        onMove(Civil.iso(date, in: timeZone))
                        dismiss()
                    }
                }
            }
        }
        .environment(\.timeZone, timeZone)
        .presentationDetents([.large])
        .onAppear { date = Civil.pickerDate(Civil.add(today, days: 1), in: timeZone) }
        .macSheetSize()
    }
}
