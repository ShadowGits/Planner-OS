import SwiftUI

/// One day: untimed work on top, then the timeline. Hold a block, then drag
/// it to a new time on a five-minute grid; tap an empty hour to add a task there.
@MainActor
struct TodayView: View {
    @Environment(PlannerStore.self) private var store
    @Binding var editor: EditorRequest?

    static let hourHeight: CGFloat = 64
    static let gutter: CGFloat = 48

    var body: some View {
        let date = store.selectedDate
        let items = store.days[date]?.items ?? []
        let timed = items.filter { $0.time != nil }
        let untimed = items.filter { $0.time == nil }
        let isToday = date == store.calendarToday
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header(date, items)
                    if !untimed.isEmpty { untimedList(untimed) }
                    timeline(timed, date: date, isToday: isToday)
                }
                .padding(.horizontal)
                .padding(.bottom, 24)
                .frame(maxWidth: 900)
                .frame(maxWidth: .infinity)
            }
            .task(id: date) {
                await store.loadDay(date)
                let starts = (store.days[date]?.items ?? []).filter { $0.time != nil }.map(\.clockMinutes)
                let minutes = isToday ? store.moment.minutes : (starts.min() ?? 8 * 60)
                proxy.scrollTo(max(0, min(23, minutes / 60 - 1)), anchor: .top)
            }
        }
        .navigationTitle(isToday ? "Today" : Civil.short(date))
        .refreshable { await store.refreshAll() }
    }

    private var dateBinding: Binding<Date> {
        Binding(get: { Civil.pickerDate(store.selectedDate, in: store.timeZone) },
                set: { store.selectedDate = Civil.iso($0, in: store.timeZone) })
    }

    private func header(_ date: String, _ items: [PlannerTask]) -> some View {
        let done = items.filter(\.done).count
        return HStack(spacing: 10) {
            Button { store.selectedDate = Civil.add(date, days: -1) } label: { Image(systemName: "chevron.left") }
                .accessibilityLabel("Previous day")
            VStack(alignment: .leading, spacing: 1) {
                Text(Civil.short(date)).font(.headline)
                Text(items.isEmpty ? "Nothing planned" : "\(done) of \(items.count) done")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Button { store.selectedDate = Civil.add(date, days: 1) } label: { Image(systemName: "chevron.right") }
                .accessibilityLabel("Next day")
            Spacer()
            if date != store.logicalToday {
                Button("Today") { store.selectedDate = store.logicalToday }.buttonStyle(.bordered)
            }
            DatePicker("Day", selection: dateBinding, displayedComponents: .date)
                .labelsHidden()
                .environment(\.timeZone, store.timeZone)
        }
        .buttonStyle(.borderless)
        .padding(.top, 8)
    }

    private func untimedList(_ tasks: [PlannerTask]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Any time").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            ForEach(tasks) { task in
                HStack(spacing: 10) {
                    Button { Task { await store.setDone(task, !task.done) } } label: {
                        Image(systemName: task.done ? "checkmark.circle.fill" : "circle").font(.title3)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(task.done ? "Reopen" : "Mark done")
                    Text(task.title)
                        .strikethrough(task.done)
                        .foregroundStyle(task.done ? .secondary : .primary)
                        .lineLimit(2)
                    Spacer()
                    if task.starred { Image(systemName: "star.fill").font(.caption).foregroundStyle(.pink) }
                    Text("\(task.minutes)m").font(.caption).foregroundStyle(.secondary)
                }
                .padding(.vertical, 8)
                .padding(.horizontal, 10)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.secondary.opacity(0.08)))
                .contentShape(Rectangle())
                .opacity(store.busy.contains(task.id) ? 0.5 : 1)
                .onTapGesture { editor = EditorRequest(task: task) }
            }
        }
    }

    private func timeline(_ tasks: [PlannerTask], date: String, isToday: Bool) -> some View {
        let lanes = timelineLanes(tasks)
        return VStack(spacing: 0) {
            ForEach(0..<24, id: \.self) { hour in
                HStack(alignment: .top, spacing: 6) {
                    Text(Civil.clock(hour * 60))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: Self.gutter - 6, alignment: .trailing)
                        .offset(y: -7)
                    Rectangle().fill(Color.secondary.opacity(0.18)).frame(height: 1)
                }
                .frame(height: Self.hourHeight, alignment: .top)
                .contentShape(Rectangle())
                .onTapGesture { editor = EditorRequest(date: date, time: Civil.clock(hour * 60)) }
                .id(hour)
            }
        }
        .overlay(alignment: .topLeading) {
            GeometryReader { geo in
                let width = max(geo.size.width - Self.gutter, 60)
                ZStack(alignment: .topLeading) {
                    ForEach(tasks) { task in
                        let lane = lanes[task.id] ?? (index: 0, count: 1)
                        let laneWidth = width / CGFloat(lane.count)
                        TimelineBlock(
                            task: task,
                            width: laneWidth - 3,
                            hourHeight: Self.hourHeight,
                            busy: store.busy.contains(task.id),
                            onTap: { editor = EditorRequest(task: task) },
                            onToggle: { Task { await store.setDone(task, !task.done) } },
                            onMove: { start in Task { await store.reschedule(task, date: date, start: start) } }
                        )
                        .offset(x: Self.gutter + laneWidth * CGFloat(lane.index),
                                y: CGFloat(task.clockMinutes) / 60 * Self.hourHeight)
                    }
                    if isToday {
                        HStack(spacing: 0) {
                            Circle().fill(Color.red).frame(width: 8, height: 8)
                            Rectangle().fill(Color.red).frame(height: 1.5)
                        }
                        .frame(width: width + 4)
                        .offset(x: Self.gutter - 4, y: CGFloat(store.moment.minutes) / 60 * Self.hourHeight - 4)
                        .allowsHitTesting(false)
                    }
                }
            }
        }
    }
}

/// A timed task on the timeline. Hold, then drag: it shows the new start as it
/// moves and saves on release.
@MainActor
struct TimelineBlock: View {
    let task: PlannerTask
    let width: CGFloat
    let hourHeight: CGFloat
    let busy: Bool
    let onTap: () -> Void
    let onToggle: () -> Void
    let onMove: (Int) -> Void

    @GestureState private var dragY: CGFloat = 0
    @GestureState private var lifted = false

    private var height: CGFloat { max(CGFloat(task.minutes) / 60 * hourHeight, 28) }
    private var preview: Int {
        snappedStart(task.clockMinutes, minutes: task.minutes, dragMinutes: Double(dragY / hourHeight * 60))
    }
    private var tint: Color { task.habit ? .teal : (task.starred ? .pink : .accentColor) }

    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Button(action: onToggle) {
                Image(systemName: task.done ? "checkmark.circle.fill" : "circle")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel(task.done ? "Reopen" : "Mark done")
            VStack(alignment: .leading, spacing: 1) {
                Text(task.title)
                    .font(.footnote.weight(.semibold))
                    .strikethrough(task.done)
                    .lineLimit(height > 44 ? 2 : 1)
                if height >= 40 || lifted {
                    Text(lifted ? "Move to \(Civil.clock(preview))"
                                : "\(Civil.clock(task.clockMinutes))–\(Civil.clock(task.clockMinutes + task.minutes))")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            if task.starred { Image(systemName: "star.fill").font(.caption2).foregroundStyle(.pink) }
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .frame(width: max(width, 30), height: height, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 8).fill(tint.opacity(task.done ? 0.10 : 0.20)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(tint.opacity(lifted ? 0.9 : 0.35), lineWidth: lifted ? 2 : 1))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .opacity(busy ? 0.5 : 1)
        .shadow(color: .black.opacity(lifted ? 0.25 : 0), radius: 8, y: 3)
        .offset(y: lifted ? CGFloat(preview - task.clockMinutes) / 60 * hourHeight : 0)
        .zIndex(lifted ? 10 : 0)
        .contentShape(RoundedRectangle(cornerRadius: 8))
        .onTapGesture(perform: onTap)
        .gesture(drag)
        .animation(.snappy(duration: 0.15), value: lifted)
        .accessibilityHint("Hold, then drag to move")
    }

    private var drag: some Gesture {
        LongPressGesture(minimumDuration: 0.3)
            .sequenced(before: DragGesture(minimumDistance: 0, coordinateSpace: .global))
            .updating($lifted) { value, state, _ in
                if case .second(true, _) = value { state = true }
            }
            .updating($dragY) { value, state, _ in
                if case .second(true, let drag?) = value { state = drag.translation.height }
            }
            .onEnded { value in
                guard case .second(true, let drag?) = value else { return }
                let start = snappedStart(task.clockMinutes, minutes: task.minutes,
                                         dragMinutes: Double(drag.translation.height / hourHeight * 60))
                if start != task.clockMinutes { onMove(start) }
            }
    }
}
