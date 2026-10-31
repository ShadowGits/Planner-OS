import SwiftUI

enum Palette {
    #if canImport(UIKit)
    static let header = Color(uiColor: .secondarySystemBackground)
    static let card = Color(uiColor: .systemBackground)
    #else
    static let header = Color(nsColor: .windowBackgroundColor)
    static let card = Color(nsColor: .textBackgroundColor)
    #endif

    /// Capsule colours: coral, slate, navy, sage, wine, amber, teal, lavender.
    static let blocks: [Color] = [
        Color(red: 0.95, green: 0.58, blue: 0.56), Color(red: 0.40, green: 0.52, blue: 0.69),
        Color(red: 0.17, green: 0.29, blue: 0.43), Color(red: 0.55, green: 0.76, blue: 0.40),
        Color(red: 0.56, green: 0.24, blue: 0.34), Color(red: 0.94, green: 0.68, blue: 0.30),
        Color(red: 0.24, green: 0.60, blue: 0.62), Color(red: 0.58, green: 0.50, blue: 0.80),
    ]

    static func block(_ task: PlannerTask) -> Color { blocks[paletteIndex(task, count: blocks.count)] }
}

/// The day as a timeline: month and week on top, all-day tasks as round chips,
/// then each timed task as a capsule on a spine, sized by its duration, with
/// free time between. Hold a task and drag it to a new time.
@MainActor
struct TodayView: View {
    @Environment(PlannerStore.self) private var store
    @Binding var editor: EditorRequest?
    @State private var pickingDate = false

    var body: some View {
        let date = store.selectedDate
        let items = store.days[date]?.items ?? []
        let allDay = items.filter { $0.time == nil }
        let entries = timelineItems(items)
        let now: Int? = date == store.calendarToday ? store.moment.minutes : nil
        let twentyFour = Civil.prefers24Hour
        VStack(spacing: 0) {
            header(date)
            WeekStrip(selected: date, today: store.logicalToday, marked: markedDays) { day in
                withAnimation(.snappy) { store.selectedDate = day }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        if !allDay.isEmpty {
                            AllDayRow(tasks: allDay, busy: store.busy,
                                      onOpen: { editor = EditorRequest(task: $0) },
                                      onToggle: { task in Task { await store.setDone(task, !task.done) } })
                                .padding(.bottom, 14)
                        }
                        if entries.isEmpty {
                            emptyState(hasAllDay: !allDay.isEmpty)
                        }
                        ForEach(entries) { entry in
                            switch entry {
                            case .task(let task, let showsStart):
                                TimelineRow(
                                    task: task,
                                    showsStart: showsStart,
                                    isFirst: entry.id == entries.first?.id,
                                    isLast: entry.id == entries.last?.id,
                                    now: now,
                                    busy: store.busy.contains(task.id),
                                    twentyFour: twentyFour,
                                    onOpen: { editor = EditorRequest(task: task) },
                                    onToggle: { Task { await store.setDone(task, !task.done) } },
                                    onMove: { start in store.rescheduleNow(task, date: date, start: start) }
                                )
                                .id(task.id)
                            case .gap(let start, let minutes, let next):
                                GapRow(start: start, minutes: minutes, next: next, now: now)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 18)
                    .padding(.bottom, 110)
                    .frame(maxWidth: 760)
                    .frame(maxWidth: .infinity)
                }
                .background(Palette.card, in: UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28, style: .continuous))
                .task(id: date) {
                    await store.loadDay(date)
                    let loaded = timelineItems(store.days[date]?.items ?? [])
                    let anchor = timelineAnchor(loaded, now: date == store.calendarToday ? store.moment.minutes : nil)
                    if let anchor { proxy.scrollTo(anchor, anchor: .center) }
                }
                .refreshable { await store.refreshAll() }
            }
        }
        .background(Palette.header)
        .overlay(alignment: .bottomTrailing) {
            AddButton { editor = EditorRequest(date: date) }
        }
        .hiddenNavigationBar()
        .sheet(isPresented: $pickingDate) {
            DayPickerSheet(day: date, timeZone: store.timeZone) { store.selectedDate = $0 }
        }
    }

    /// Days in view that have something planned, for the dots under the week.
    private var markedDays: Set<String> {
        var days = Set(store.days.compactMap { $0.value.items.isEmpty ? nil : $0.key })
        for task in store.week?.items ?? [] where !task.habit {
            if let day = task.date { days.insert(day) }
        }
        return days
    }

    private func header(_ date: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(Civil.monthName(date)).font(.system(size: 28, weight: .bold))
            Text(Civil.year(date)).font(.system(size: 28, weight: .bold)).foregroundStyle(Color.accentColor)
            Spacer()
            if date != store.logicalToday {
                Button("Today") { withAnimation(.snappy) { store.selectedDate = store.logicalToday } }
                    .font(.subheadline.weight(.semibold))
            }
            Button { pickingDate = true } label: {
                Image(systemName: "calendar").font(.title3.weight(.semibold))
            }
            .accessibilityLabel("Pick a day")
        }
        .buttonStyle(.borderless)
        .tint(Color.accentColor)
        .padding(.horizontal, 20)
        .padding(.top, 10)
        .padding(.bottom, 12)
    }

    private func emptyState(hasAllDay: Bool) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "sun.horizon").font(.system(size: 40)).foregroundStyle(.secondary)
            Text(hasAllDay ? "Nothing at a set time" : "Nothing planned").font(.headline)
            Text("Tap + to add a task.").font(.subheadline).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }
}

/// Mon to Sun with the selected day in a filled circle. Swipe for other weeks.
@MainActor
struct WeekStrip: View {
    let selected: String
    let today: String
    let marked: Set<String>
    let onSelect: (String) -> Void

    var body: some View {
        let start = Civil.weekStart(selected)
        HStack(spacing: 0) {
            ForEach(0..<7, id: \.self) { offset in
                let day = Civil.add(start, days: offset)
                let isSelected = day == selected
                Button { onSelect(day) } label: {
                    VStack(spacing: 5) {
                        Text(Civil.weekdayShort(day)).font(.caption).foregroundStyle(.secondary)
                        Text(String(Int(day.suffix(2)) ?? 0))
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(isSelected ? Color.white : (day == today ? Color.accentColor : Color.primary))
                            .frame(width: 34, height: 34)
                            .background(Circle().fill(isSelected ? Color.accentColor : Color.clear))
                        Circle()
                            .fill(marked.contains(day) && !isSelected ? Color.secondary.opacity(0.6) : Color.clear)
                            .frame(width: 4, height: 4)
                    }
                    .frame(maxWidth: .infinity)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Civil.short(day))
            }
        }
        .padding(.horizontal, 8)
        .padding(.bottom, 12)
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 24).onEnded { value in
                let dx = value.translation.width
                guard abs(dx) > 50, abs(dx) > abs(value.translation.height) else { return }
                onSelect(Civil.add(selected, days: dx < 0 ? 7 : -7))
            }
        )
    }
}

/// Tasks with no time, as round chips like all-day events.
@MainActor
struct AllDayRow: View {
    let tasks: [PlannerTask]
    let busy: Set<String>
    let onOpen: (PlannerTask) -> Void
    let onToggle: (PlannerTask) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 14) {
                ForEach(tasks) { task in
                    let color = Palette.block(task)
                    VStack(spacing: 6) {
                        Circle()
                            .fill(Color.secondary.opacity(0.12))
                            .frame(width: 58, height: 58)
                            .overlay(Image(systemName: taskSymbol(task)).font(.title3).foregroundStyle(color))
                            .overlay(alignment: .bottomTrailing) {
                                if task.done {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundStyle(color)
                                        .background(Circle().fill(Palette.card))
                                }
                            }
                        Text(task.title)
                            .strikethrough(task.done)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(task.done ? .secondary : .primary)
                            .multilineTextAlignment(.center)
                            .lineLimit(2)
                            .frame(width: 76)
                    }
                    .opacity(busy.contains(task.id) ? 0.5 : 1)
                    .contentShape(Rectangle())
                    .onTapGesture { onOpen(task) }
                    .contextMenu {
                        Button(task.done ? "Reopen" : "Mark done") { onToggle(task) }
                        Button("Edit") { onOpen(task) }
                    }
                }
            }
            .padding(.vertical, 2)
        }
    }
}

/// One timed task. Hold it, then drag: it follows the finger, the time on the
/// left ticks in five-minute steps with a light haptic each step, and on
/// release it settles into its new place.
@MainActor
struct TimelineRow: View {
    let task: PlannerTask
    let showsStart: Bool
    let isFirst: Bool
    let isLast: Bool
    let now: Int?
    let busy: Bool
    let twentyFour: Bool
    let onOpen: () -> Void
    let onToggle: () -> Void
    let onMove: (Int) -> Void

    static let timeColumn: CGFloat = 64
    static let pillWidth: CGFloat = 52
    private static let rowPadding: CGFloat = 5

    @State private var lifted = false
    @State private var dragY: CGFloat = 0
    @GestureState private var pressing = false

    private var height: CGFloat { CGFloat(pillHeight(task.minutes)) }
    private var color: Color { Palette.block(task) }
    private var start: Int { lifted ? preview : task.clockMinutes }
    private var preview: Int {
        snappedStart(task.clockMinutes, minutes: task.minutes, dragMinutes: Double(dragY) / timelinePointsPerMinute)
    }
    private var progress: Double? {
        guard let now, !task.done, now >= task.clockMinutes, now < task.clockMinutes + task.minutes else { return nil }
        return Double(now - task.clockMinutes) / Double(max(task.minutes, 1))
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            timeColumn
            spineAndPill
            details
            Spacer(minLength: 8)
            Button(action: onToggle) {
                Image(systemName: task.done ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 26))
                    .foregroundStyle(color)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(task.done ? "Reopen" : "Mark done")
        }
        .frame(height: height + Self.rowPadding * 2)
        .contentShape(Rectangle())
        .opacity(busy && !lifted ? 0.55 : 1)
        .scaleEffect(lifted ? 1.03 : 1, anchor: .leading)
        .shadow(color: .black.opacity(lifted ? 0.18 : 0), radius: 12, y: 6)
        .offset(y: dragY)
        .zIndex(lifted ? 1 : 0)
        .onTapGesture(perform: onOpen)
        .gesture(drag)
        .onChange(of: pressing) { _, isPressing in
            // The system can cancel a drag without ending it (a call, a scroll
            // taking over); put the task back where it was.
            if !isPressing && lifted {
                withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) { lifted = false; dragY = 0 }
            }
        }
        .sensoryFeedback(.impact(weight: .medium), trigger: lifted) { _, isLifted in isLifted }
        .sensoryFeedback(.selection, trigger: preview) { _, _ in lifted }
        .accessibilityHint("Hold, then drag to change the time")
    }

    private var timeColumn: some View {
        VStack(alignment: .trailing, spacing: 0) {
            Text(showsStart || lifted ? Civil.clockText(start, twentyFour: twentyFour) : " ")
            Spacer(minLength: 0)
            Text(Civil.clockText(start + task.minutes, twentyFour: twentyFour))
        }
        .font(.caption.monospacedDigit())
        .foregroundStyle(lifted ? Color.accentColor : Color.secondary)
        .frame(width: Self.timeColumn, height: height, alignment: .trailing)
    }

    private var spineAndPill: some View {
        let shape = RoundedRectangle(cornerRadius: Self.pillWidth / 2, style: .continuous)
        let full = height + Self.rowPadding * 2
        return ZStack {
            // The spine runs through every capsule and joins them up.
            Rectangle()
                .fill(Color.secondary.opacity(lifted ? 0 : 0.25))
                .frame(width: 2, height: full - (isFirst ? full / 2 : 0) - (isLast ? full / 2 : 0))
                .offset(y: (isFirst ? full / 4 : 0) - (isLast ? full / 4 : 0))
            ZStack(alignment: .top) {
                shape.fill(color.opacity(task.done ? 0.4 : (progress == nil ? 1 : 0.38)))
                if let progress {
                    Rectangle().fill(color).frame(height: height * progress)
                }
            }
            .frame(width: Self.pillWidth, height: height)
            .clipShape(shape)
            .overlay(
                Image(systemName: taskSymbol(task))
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
            )
        }
        .frame(width: Self.pillWidth, height: full)
    }

    private var details: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("\(Civil.clockText(start, twentyFour: twentyFour)) – \(Civil.clockText(start + task.minutes, twentyFour: twentyFour)) (\(durationText(task.minutes)))")
                .font(.caption.monospacedDigit())
                .foregroundStyle(lifted ? Color.accentColor : Color.secondary)
            Text(task.title)
                .strikethrough(task.done)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(task.done ? .secondary : .primary)
                .lineLimit(height > 64 ? 2 : 1)
        }
    }

    private var drag: some Gesture {
        LongPressGesture(minimumDuration: 0.25)
            .sequenced(before: DragGesture(minimumDistance: 0, coordinateSpace: .global))
            .updating($pressing) { _, state, _ in state = true }
            .onChanged { value in
                guard case .second(true, let drag) = value else { return }
                if !lifted { withAnimation(.spring(response: 0.25, dampingFraction: 0.75)) { lifted = true } }
                // No animation here: the task tracks the finger exactly.
                var still = Transaction()
                still.disablesAnimations = true
                withTransaction(still) { dragY = drag?.translation.height ?? 0 }
            }
            .onEnded { value in
                guard case .second(true, let drag?) = value else { return }
                let target = snappedStart(task.clockMinutes, minutes: task.minutes,
                                          dragMinutes: Double(drag.translation.height) / timelinePointsPerMinute)
                // The new time and the release animate together, so the task
                // glides from under the finger into its slot.
                withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                    lifted = false
                    dragY = 0
                    if target != task.clockMinutes { onMove(target) }
                }
            }
    }
}

/// Free time between two tasks: a dotted spine and how long it lasts, or how
/// long until the next task when now falls inside it.
@MainActor
struct GapRow: View {
    let start: Int
    let minutes: Int
    let next: String
    let now: Int?

    var body: some View {
        let height = CGFloat(gapHeight(minutes))
        HStack(spacing: 12) {
            Color.clear.frame(width: TimelineRow.timeColumn, height: 1)
            Path { path in
                path.move(to: CGPoint(x: 1, y: 0))
                path.addLine(to: CGPoint(x: 1, y: height))
            }
            .stroke(Color.secondary.opacity(0.35), style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [1, 6]))
            .frame(width: 2, height: height)
            .frame(width: TimelineRow.pillWidth)
            Text(label)
                .font(.caption)
                .foregroundStyle(isNow ? Color.accentColor : Color.secondary)
            Spacer()
        }
        .frame(height: height)
    }

    private var isNow: Bool {
        guard let now else { return false }
        return now >= start && now < start + minutes
    }

    private var label: String {
        if isNow, let now { return "Now · \(durationText(start + minutes - now)) until \(next)" }
        return "\(durationText(minutes)) free"
    }
}

/// The floating + button.
@MainActor
struct AddButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "plus")
                .font(.title2.weight(.semibold))
                .foregroundStyle(.white)
                .frame(width: 58, height: 58)
                .background(Circle().fill(Color.accentColor))
                .shadow(color: .black.opacity(0.2), radius: 8, y: 4)
        }
        .buttonStyle(.plain)
        .keyboardShortcut("n", modifiers: .command)
        .accessibilityLabel("Add task")
        .padding(20)
    }
}

@MainActor
struct DayPickerSheet: View {
    let day: String
    let timeZone: TimeZone
    let onPick: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date()

    var body: some View {
        NavigationStack {
            Form {
                DatePicker("Day", selection: $date, displayedComponents: .date)
                    .datePickerStyle(.graphical)
            }
            .formStyle(.grouped)
            .navigationTitle("Go to day")
            .inlineTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Go") {
                        onPick(Civil.iso(date, in: timeZone))
                        dismiss()
                    }
                }
            }
        }
        .environment(\.timeZone, timeZone)
        .presentationDetents([.large])
        .onAppear { date = Civil.pickerDate(day, in: timeZone) }
        .macSheetSize()
    }
}
