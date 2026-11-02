import SwiftUI
import UniformTypeIdentifiers

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

/// Structured's colours (docs/structured-ux.md).
enum Palette {
    #if canImport(UIKit)
    static let header = Color(uiColor: .systemGroupedBackground)
    static let card = Color(uiColor: .systemBackground)
    /// Capsules and spine still ahead of now.
    static let pale = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.17, alpha: 1) : UIColor(white: 0.922, alpha: 1) })
    #else
    static let header = Color(nsColor: .windowBackgroundColor)
    static let card = Color(nsColor: .textBackgroundColor)
    static let pale = Color(nsColor: NSColor(name: nil) { $0.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? NSColor(white: 0.17, alpha: 1) : NSColor(white: 0.922, alpha: 1) })
    #endif
    static let accent = Color(hex: 0xF19E98)
    /// Coral, orange, amber, green, blue, dark green, wine, navy.
    static let blocks: [Color] = [0xF19E98, 0xF19C74, 0xEAA93B, 0x91BE6C, 0x6085A8, 0x3A8564, 0x974667, 0x2B5073].map { Color(hex: $0) }

    static func block(_ task: PlannerTask) -> Color { blocks[paletteIndex(task, count: blocks.count)] }
}

private struct PlacedItem: Identifiable {
    var index: Int
    var item: TimelineItem
    var id: String { item.id }
}

/// The day as Structured shows it: "16. October 2025 ›", the week with each
/// day's task colours, all-day tasks as round chips, then the timeline. Hold a
/// task to pick it up: an outlined capsule shows where it will land, with the
/// new times in bold, and nothing else moves until it is dropped.
@MainActor
struct TodayView: View {
    @Environment(PlannerStore.self) private var store
    @Binding var editor: EditorRequest?
    @State private var pickingDate = false
    /// The time under the finger while a task is dragged over the timeline.
    @State private var hover: Int?

    var body: some View {
        let date = store.selectedDate
        let items = store.days[date]?.items ?? []
        let allDay = items.filter { $0.time == nil }
        let entries = timelineItems(items)
        let placed = entries.enumerated().map { PlacedItem(index: $0.offset, item: $0.element) }
        // The planner's day runs to 04:00, so at 01:30 it is 25:30 on the evening's day.
        let now = nowOnDay(date, today: store.logicalToday, minutes: logicalMinutes(store.moment))
        let twentyFour = Civil.prefers24Hour
        let dragged = items.first { $0.id == store.draggingID }
        ScrollViewReader { proxy in
        VStack(spacing: 0) {
            header(date, entries: entries, now: now, proxy: proxy)
            WeekStrip(selected: date, today: store.logicalToday, colors: dayColors, onSelect: { day in
                withAnimation(.snappy) { store.selectedDate = day }
            }, onDropTask: dropOnDay)
            WinsStrip(tasks: items) { task in
                withAnimation(.snappy) { proxy.scrollTo(task.id, anchor: .center) }
            }
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        Capsule().fill(Color.secondary.opacity(0.3)).frame(width: 36, height: 5)
                            .frame(maxWidth: .infinity).padding(.bottom, 10)
                        if !allDay.isEmpty {
                            AllDayRow(tasks: allDay,
                                      onOpen: { editor = EditorRequest(task: $0) },
                                      onToggle: { task in Task { await store.setDone(task, !task.done) } })
                                .padding(.bottom, 12)
                        }
                        if entries.isEmpty { emptyState(hasAllDay: !allDay.isEmpty) }
                        ZStack(alignment: .topLeading) {
                            VStack(alignment: .leading, spacing: 0) {
                                ForEach(placed) { place in
                                    switch place.item {
                                    case .task(let task, let showsStart):
                                        TimelineRow(
                                            task: task, showsStart: showsStart,
                                            isFirst: place.index == 0, isLast: place.index == entries.count - 1,
                                            now: now, twentyFour: twentyFour,
                                            hidden: hover != nil && store.draggingID == task.id,
                                            onOpen: { editor = EditorRequest(task: task) },
                                            onToggle: { Task { await store.setDone(task, !task.done) } },
                                            onStar: { Task { await store.toggleStar(task) } },
                                            onLift: { store.beginDrag(task.id) }
                                        )
                                        .id(task.id)
                                    case .overlap(let group):
                                        OverlapRow(group: group, now: now, twentyFour: twentyFour,
                                                   hiddenID: hover != nil ? store.draggingID : nil,
                                                   onOpen: { editor = EditorRequest(task: $0) },
                                                   onToggle: { task in Task { await store.setDone(task, !task.done) } },
                                                   onLift: { store.beginDrag($0) })
                                    case .gap(let start, let minutes, let next):
                                        GapRow(start: start, minutes: minutes, next: next,
                                               previous: color(of: entries, at: place.index - 1),
                                               following: color(of: entries, at: place.index + 1),
                                               now: now, twentyFour: twentyFour) {
                                            editor = EditorRequest(date: date, time: Civil.clock(((start + 4) / 5) * 5))
                                        }
                                    }
                                }
                                // While a task is held: the night, down to 04:00 the next morning.
                                if let dragged {
                                    NightRoom(entries: entries, heldMinutes: dragged.minutes, date: date, twentyFour: twentyFour,
                                              bold: hover.map { [dropStart($0), dropStart($0) + dragged.minutes] } ?? [])
                                }
                            }
                            if let barY = nowBarOffset(now, in: entries) {
                                NowBar(label: columnClock(now, twentyFour: twentyFour))
                                    .offset(y: CGFloat(barY) - 8)
                            }
                            if let hover, let dragged {
                                LandingOutline(task: dragged, start: dropStart(hover),
                                               entries: entries, twentyFour: twentyFour)
                            }
                        }
                        // Room to drop below the last task.
                        .padding(.bottom, entries.isEmpty ? 0 : 140)
                        .contentShape(Rectangle())
                        .onDrop(of: [UTType.plainText], delegate: TimelineDrop(entries: entries, hover: $hover, signal: { store.dragSignal = Date() }) { id, minute in
                            store.endDrag()
                            guard let task = items.first(where: { $0.id == id }) else { return }
                            let start = dropStart(minute)
                            guard start != task.clockMinutes || task.time == nil else { return }
                            withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                                store.rescheduleNow(task, date: date, start: start)
                            }
                        })
                        .sensoryFeedback(.selection, trigger: hover) { _, new in new != nil }
                    }
                    .padding(.horizontal, 12)
                    .padding(.top, 8)
                    .padding(.bottom, 40)
                    .frame(maxWidth: 760)
                    .frame(maxWidth: .infinity)
                }
                .background(Palette.card, in: UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28, style: .continuous))
                .task(id: date) {
                    await store.loadDay(date)
                    let loaded = timelineItems(store.days[date]?.items ?? [])
                    let anchor = timelineAnchor(loaded, now: date == store.logicalToday ? logicalMinutes(store.moment) : nil)
                    if let anchor { proxy.scrollTo(anchor, anchor: .center) }
                }
                .refreshable { await store.refreshAll() }
        }
        }
        .background(Palette.header)
        .hiddenNavigationBar()
        .sheet(isPresented: $pickingDate) {
            DayPickerSheet(day: date, timeZone: store.timeZone) { store.selectedDate = $0 }
        }
    }

    private func color(of entries: [TimelineItem], at index: Int) -> Color? {
        guard entries.indices.contains(index), case .task(let task, _) = entries[index] else { return nil }
        return Palette.block(task)
    }

    /// The colours of a day's tasks, for the circles under the week.
    private func dayColors(_ day: String) -> [Color] {
        let tasks = store.days[day]?.items ?? (store.week?.items ?? []).filter { $0.date == day }
        return tasks.filter { !$0.habit }.sorted { $0.clockMinutes < $1.clockMinutes }.map(Palette.block)
    }

    /// A task dropped on a day of the week strip moves to that day at the same time.
    private func dropOnDay(_ id: String, _ day: String) {
        store.endDrag()
        guard let task = store.days.values.lazy.flatMap(\.items).first(where: { $0.id == id }),
              task.date != day else { return }
        withAnimation(.snappy) {
            if task.time == nil { Task { await store.move([task], to: day) } }
            else { store.rescheduleNow(task, date: day, start: task.clockMinutes) }
        }
    }

    /// "16. October" bold, "2025 ›" in the accent colour; Today on another day,
    /// Now on today, which scrolls to the task under way or next.
    private func header(_ date: String, entries: [TimelineItem], now: Int, proxy: ScrollViewProxy) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            Button { pickingDate = true } label: {
                (Text("\(Int(date.suffix(2)) ?? 0). \(Civil.monthName(date))").foregroundStyle(Color.primary)
                    + Text(" \(Civil.year(date)) ›").foregroundStyle(Palette.accent))
                    .font(.system(size: 28, weight: .bold))
            }
            .buttonStyle(.plain)
            .accessibilityHint("Pick a day")
            Spacer()
            if date != store.logicalToday {
                Button("Today") { withAnimation(.snappy) { store.selectedDate = store.logicalToday } }
                    .font(.subheadline.weight(.semibold))
                    .tint(Palette.accent)
                    .buttonStyle(.borderless)
            } else if let anchor = timelineAnchor(entries, now: now) {
                Button("Now") { withAnimation(.snappy) { proxy.scrollTo(anchor, anchor: .center) } }
                    .font(.subheadline.weight(.semibold))
                    .tint(Palette.accent)
                    .buttonStyle(.borderless)
            }
        }
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

/// Mon to Sun. The selected day sits in a filled circle (accent when it is
/// today, black otherwise), today otherwise in accent; under each day, small
/// circles in the colours of its tasks. Swipe for other weeks.
@MainActor
struct WeekStrip: View {
    let selected: String
    let today: String
    let colors: (String) -> [Color]
    let onSelect: (String) -> Void
    /// A task's id dropped on a day.
    var onDropTask: (String, String) -> Void = { _, _ in }
    @State private var targeted: String?

    var body: some View {
        let start = Civil.weekStart(selected)
        HStack(spacing: 0) {
            ForEach(0..<7, id: \.self) { offset in
                let day = Civil.add(start, days: offset)
                let isSelected = day == selected, isToday = day == today
                let dots = Array(colors(day).prefix(4))
                Button { onSelect(day) } label: {
                    VStack(spacing: 5) {
                        Text(Civil.weekdayShort(day)).font(.caption).foregroundStyle(.secondary)
                        Text(String(Int(day.suffix(2)) ?? 0))
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(isSelected ? Palette.card : (isToday ? Palette.accent : Color.primary))
                            .frame(width: 32, height: 32)
                            .background(Circle().fill(isSelected ? (isToday ? Palette.accent : Color.primary) : Color.clear))
                        HStack(spacing: -4) {
                            ForEach(dots.indices, id: \.self) { index in
                                Circle().fill(dots[index]).frame(width: 9, height: 9)
                                    .overlay(Circle().stroke(Palette.header, lineWidth: 1))
                            }
                        }
                        .frame(height: 11)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 2)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Palette.accent.opacity(targeted == day ? 0.22 : 0)))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Civil.short(day))
                // Drag a task here to move it to this day, keeping its time.
                .onDrop(of: [UTType.plainText], isTargeted: Binding(
                    get: { targeted == day },
                    set: { inside in if inside { targeted = day } else if targeted == day { targeted = nil } })) { providers in
                    guard let provider = providers.first else { return false }
                    _ = provider.loadObject(ofClass: NSString.self) { object, _ in
                        guard let text = object as? NSString else { return }
                        let id = text as String
                        DispatchQueue.main.async { onDropTask(id, day) }
                    }
                    return true
                }
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

/// Tasks with no time, as round chips. Open: pale circle, icon in the task
/// colour. Done: solid colour, white icon, label struck through.
@MainActor
struct AllDayRow: View {
    let tasks: [PlannerTask]
    let onOpen: (PlannerTask) -> Void
    let onToggle: (PlannerTask) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 14) {
                ForEach(tasks) { task in
                    let color = Palette.block(task)
                    VStack(spacing: 6) {
                        Circle()
                            .fill(task.done ? color : Palette.pale)
                            .frame(width: 46, height: 46)
                            .overlay(Image(systemName: taskSymbol(task)).font(.system(size: 19, weight: .semibold))
                                .foregroundStyle(task.done ? Color.white : color))
                        Text(task.title)
                            .strikethrough(task.done)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(task.done ? .secondary : .primary)
                            .multilineTextAlignment(.center)
                            .lineLimit(2)
                            .frame(width: 72)
                    }
                    .contentShape(Rectangle())
                    .onTapGesture { onOpen(task) }
                    .contextMenu {
                        Button(task.done ? "Reopen" : "Mark done") { onToggle(task) }
                        Button("Edit") { onOpen(task) }
                    }
                }
            }
            .padding(.vertical, 2)
            .padding(.horizontal, 4)
        }
    }
}

private struct TimeLabel: Identifiable {
    var y: CGFloat
    var text: String
    var id: String { "\(Int(y))-\(text)" }
}

/// The left column: start and end, and whole hours inside long tasks. Labels
/// next to the now bar give way to its bold time.
private struct TimeColumn: View {
    let height: CGFloat
    let labels: [TimeLabel]
    let now: TimeLabel?

    var body: some View {
        let shown = labels.filter { label in now.map { abs($0.y - label.y) > 14 } ?? true }
        ZStack(alignment: .topLeading) {
            ForEach(shown) { label in
                Text(label.text).font(.caption2.monospacedDigit()).foregroundStyle(.secondary).lineLimit(1)
                    .offset(y: label.y - 7)
            }
        }
        .frame(width: TimelineRow.timeColumn, height: height, alignment: .topLeading)
    }
}

/// The now bar: the current time in bold, a small dot on the spine and a very
/// subtle line across the timeline.
private struct NowBar: View {
    let label: String

    var body: some View {
        ZStack(alignment: .leading) {
            Canvas { context, size in
                let x = TimelineRow.timeColumn + 4 + TimelineRow.pillWidth / 2, mid = size.height / 2
                var line = Path()
                line.move(to: CGPoint(x: x, y: mid))
                line.addLine(to: CGPoint(x: size.width, y: mid))
                context.stroke(line, with: .color(Palette.accent.opacity(0.35)), lineWidth: 1)
                context.fill(Path(ellipseIn: CGRect(x: x - 3, y: mid - 3, width: 6, height: 6)), with: .color(Palette.accent))
            }
            Text(label).font(.caption2.monospacedDigit().weight(.bold)).foregroundStyle(.primary).lineLimit(1)
        }
        .frame(height: 16)
        .frame(maxWidth: .infinity)
        .allowsHitTesting(false)
        .accessibilityLabel("Now, \(label)")
    }
}

/// One timed task. Ahead of now: pale capsule, icon in the task colour. Under
/// way: filled with colour down to now, "28m remaining". Passed or done: solid
/// colour, white icon; done also strikes the title and fills the tick circle.
@MainActor
struct TimelineRow: View {
    let task: PlannerTask
    let showsStart: Bool
    let isFirst: Bool
    let isLast: Bool
    let now: Int
    let twentyFour: Bool
    let hidden: Bool
    let onOpen: () -> Void
    let onToggle: () -> Void
    let onStar: () -> Void
    let onLift: () -> Void

    static let timeColumn: CGFloat = 44
    static let pillWidth = CGFloat(timelinePillWidth)
    fileprivate static let pad = CGFloat(timelineRowPadding)

    private var pill: CGFloat { CGFloat(pillHeight(task.minutes)) }
    private var rowHeight: CGFloat { pill + 2 * Self.pad }

    private func timeLabels(start: Int, end: Int) -> [TimeLabel] {
        var labels: [TimeLabel] = []
        if showsStart { labels.append(TimeLabel(y: Self.pad + 6, text: columnClock(start, twentyFour: twentyFour))) }
        for mark in hourMarks(task) {
            labels.append(TimeLabel(y: Self.pad + CGFloat(mark - start) / CGFloat(task.minutes) * pill,
                                    text: columnClock(mark, twentyFour: twentyFour)))
        }
        labels.append(TimeLabel(y: Self.pad + pill - 6, text: columnClock(end, twentyFour: twentyFour)))
        return labels
    }

    var body: some View {
        let color = Palette.block(task)
        let phase = taskPhase(task, now: now)
        let progress = CGFloat(taskProgress(task, now: now))
        let solid = phase == .past || phase == .done
        let start = task.clockMinutes, end = start + task.minutes
        let showsNow = phase == .underway || (phase == .done && now >= start && now < end)
        let nowLabel: TimeLabel? = showsNow ? TimeLabel(y: Self.pad + progress * pill, text: columnClock(now, twentyFour: twentyFour)) : nil
        HStack(spacing: 0) {
            TimeColumn(height: rowHeight, labels: hidden ? [] : timeLabels(start: start, end: end), now: hidden ? nil : nowLabel)
            Spacer().frame(width: 4)
            ZStack {
                Spine(isFirst: isFirst, isLast: isLast, color: color, reached: { size in
                    if now >= end { return size.height }
                    if now <= start { return 0 }
                    return Self.pad + progress * pill
                })
                capsule(color: color, phase: phase, progress: progress, solid: solid)
                    .opacity(hidden ? 0 : 1)
            }
            .frame(width: Self.pillWidth, height: rowHeight)
            Spacer().frame(width: 12)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 3) {
                    Text(phase == .underway ? remainingText(task, now: now)
                         : "\(rangeText(start, end, twentyFour: twentyFour)) (\(durationWords(task.minutes)))")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    if task.recurrenceKey != nil || task.habit {
                        Image(systemName: "repeat").font(.caption2).foregroundStyle(.secondary)
                    }
                    if let part = partText(task) {
                        Text("· \(part)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Text(task.title)
                    .strikethrough(task.done)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(task.done ? .secondary : .primary)
                    .lineLimit(pill > 60 ? 2 : 1)
                if task.workedSeconds > 0 {
                    Text(workedText(task)).font(.caption2.weight(.medium)).foregroundStyle(color).lineLimit(1)
                }
            }
            .opacity(hidden ? 0 : 1)
            Spacer(minLength: 8)
            // Top Win: tap the star, as on the old timeline.
            Button(action: onStar) {
                Image(systemName: task.starred ? "star.fill" : "star")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(task.starred ? Palette.accent : Color.secondary.opacity(0.55))
                    .frame(width: 32, height: 44)
            }
            .buttonStyle(.plain)
            .opacity(hidden ? 0 : 1)
            .accessibilityLabel("\(task.starred ? "Remove" : "Choose") \(task.title) as Top Win")
            Button(action: onToggle) {
                ZStack {
                    Circle().stroke(color, lineWidth: 2)
                    if task.done {
                        Circle().fill(color)
                        Image(systemName: "checkmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                    }
                }
                .frame(width: 24, height: 24)
                .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .opacity(hidden ? 0 : 1)
            .accessibilityLabel("\(task.done ? "Reopen" : "Complete") \(task.title)")
        }
        .frame(height: rowHeight)
        .contentShape(Rectangle())
        .onTapGesture(perform: onOpen)
        .onDrag {
            onLift()
            return NSItemProvider(object: task.id as NSString)
        } preview: {
            DragChip(task: task, twentyFour: twentyFour)
        }
        .accessibilityHint("Hold, then drag to change the time")
    }

    private func capsule(color: Color, phase: TaskPhase, progress: CGFloat, solid: Bool) -> some View {
        ZStack(alignment: .top) {
            Rectangle().fill(solid ? color : Palette.pale)
            if phase == .underway {
                Rectangle()
                    .fill(LinearGradient(stops: [.init(color: color, location: 0), .init(color: color, location: 0.8),
                                                 .init(color: color.opacity(0.4), location: 1)],
                                         startPoint: .top, endPoint: .bottom))
                    .frame(height: max(pill * progress, 1))
            }
        }
        .frame(width: Self.pillWidth, height: pill)
        .clipShape(RoundedRectangle(cornerRadius: Self.pillWidth / 2, style: .continuous))
        .overlay(
            Image(systemName: taskSymbol(task))
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(solid || (phase == .underway && progress > 0.5) ? Color.white : color)
        )
    }
}

/// Tasks that run at the same time, drawn beside each other.
///
/// A single file cannot say this: stacked, two things at eleven look like one
/// at eleven and one after it. Here each column is its own task, placed by its
/// own clock, so an overlap reads as an overlap. Nothing is moved, nothing is
/// hidden — running two things at once is a choice.
@MainActor
struct OverlapRow: View {
    let group: OverlapGroup
    let now: Int
    let twentyFour: Bool
    let hiddenID: String?
    let onOpen: (PlannerTask) -> Void
    let onToggle: (PlannerTask) -> Void
    let onLift: (String) -> Void

    var body: some View {
        let height = CGFloat(itemHeight(.overlap(group)))
        HStack(spacing: 0) {
            TimeColumn(height: height, labels: labels(height), now: nil)
            Spacer().frame(width: 4)
            GeometryReader { space in
                let columnWidth = space.size.width / CGFloat(group.columns)
                ForEach(group.placed) { placed in
                    OverlapBlock(placed: placed, columns: group.columns, now: now, twentyFour: twentyFour,
                                 onOpen: { onOpen(placed.task) }, onToggle: { onToggle(placed.task) },
                                 onLift: { onLift(placed.task.id) })
                        .frame(width: columnWidth - 4, height: CGFloat(placed.height))
                        .opacity(hiddenID == placed.task.id ? 0 : 1)
                        .offset(x: columnWidth * CGFloat(placed.column),
                                y: CGFloat(timelineRowPadding + placed.top))
                }
            }
        }
        .frame(height: height)
    }

    /// The start is already printed as the previous task's end where they meet.
    private func labels(_ height: CGFloat) -> [TimeLabel] {
        var out: [TimeLabel] = []
        if group.showsStart {
            out.append(TimeLabel(y: CGFloat(timelineRowPadding) + 6, text: columnClock(group.start, twentyFour: twentyFour)))
        }
        out.append(TimeLabel(y: height - CGFloat(timelineRowPadding) - 6, text: columnClock(group.end, twentyFour: twentyFour)))
        return out
    }
}

/// One task inside a side-by-side group: its own block, in its own column.
@MainActor
private struct OverlapBlock: View {
    let placed: OverlapGroup.Placed
    let columns: Int
    let now: Int
    let twentyFour: Bool
    let onOpen: () -> Void
    let onToggle: () -> Void
    let onLift: () -> Void

    var body: some View {
        let task = placed.task
        let color = Palette.block(task)
        let phase = taskPhase(task, now: now)
        let progress = CGFloat(taskProgress(task, now: now))
        let solid = phase == .past || phase == .done
        let ink: Color = solid || (phase == .underway && progress > 0.5) ? .white : color
        let narrow = columns > 2
        // A 30-minute block is one line tall: a time and a tick under the title
        // would be drawn straight through it.
        let roomy = placed.height >= 78

        ZStack(alignment: .topLeading) {
            Rectangle().fill(solid ? color : Palette.pale)
            if phase == .underway {
                VStack(spacing: 0) {
                    Rectangle()
                        .fill(LinearGradient(stops: [.init(color: color, location: 0), .init(color: color, location: 0.8),
                                                     .init(color: color.opacity(0.4), location: 1)],
                                             startPoint: .top, endPoint: .bottom))
                        .frame(height: max(CGFloat(placed.height) * progress, 1))
                    Spacer(minLength: 0)
                }
            }

            if roomy {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Image(systemName: taskSymbol(task)).font(.system(size: narrow ? 11 : 13, weight: .semibold))
                            .foregroundStyle(ink)
                        if !narrow {
                            Text(columnClock(task.clockMinutes, twentyFour: twentyFour))
                                .font(.system(size: 10).monospacedDigit())
                                .foregroundStyle(solid ? Color.white.opacity(0.85) : Color.secondary)
                        }
                    }
                    title(lines: placed.height > 110 ? 3 : 2, solid: solid, narrow: narrow)
                    Spacer(minLength: 0)
                }
                .padding(EdgeInsets(top: 5, leading: 7, bottom: 4, trailing: 28))
            } else {
                HStack(spacing: 5) {
                    Image(systemName: taskSymbol(task)).font(.system(size: 11, weight: .semibold)).foregroundStyle(ink)
                    title(lines: 1, solid: solid, narrow: narrow)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 7)
                .frame(maxHeight: .infinity)
            }

            // The tick floats in the corner rather than taking a row of its own.
            VStack {
                Spacer(minLength: 0)
                HStack {
                    Spacer(minLength: 0)
                    Button(action: onToggle) {
                        ZStack {
                            Circle().stroke(ink, lineWidth: 2)
                            if task.done {
                                Circle().fill(color)
                                Image(systemName: "checkmark").font(.system(size: 9, weight: .bold)).foregroundStyle(.white)
                            }
                        }
                        .frame(width: 18, height: 18)
                        .frame(width: 30, height: 30)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(task.done ? "Reopen" : "Complete") \(task.title)")
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture(perform: onOpen)
        .onDrag {
            onLift()
            return NSItemProvider(object: task.id as NSString)
        } preview: {
            DragChip(task: task, twentyFour: twentyFour)
        }
        .accessibilityHint("Hold, then drag to change the time")
    }

    private func title(lines: Int, solid: Bool, narrow: Bool) -> some View {
        Text(placed.task.title)
            .font(.system(size: narrow ? 11 : 13, weight: .semibold))
            .strikethrough(placed.task.done)
            .foregroundStyle(solid ? Color.white : Color.primary)
            .lineLimit(lines)
            .multilineTextAlignment(.leading)
    }
}

/// The line through the capsules: pale, and in the task's colour up to now.
private struct Spine: View {
    let isFirst: Bool
    let isLast: Bool
    let color: Color
    let reached: (CGSize) -> CGFloat

    var body: some View {
        Canvas { context, size in
            let x = size.width / 2
            let top: CGFloat = isFirst ? size.height / 2 : 0
            let bottom: CGFloat = isLast ? size.height / 2 : size.height
            guard bottom > top else { return }
            var line = Path()
            line.move(to: CGPoint(x: x, y: top))
            line.addLine(to: CGPoint(x: x, y: bottom))
            context.stroke(line, with: .color(Palette.pale), lineWidth: 3)
            let end = min(max(reached(size), top), bottom)
            if end > top {
                var passed = Path()
                passed.move(to: CGPoint(x: x, y: top))
                passed.addLine(to: CGPoint(x: x, y: end))
                context.stroke(passed, with: .color(color), lineWidth: 3)
            }
        }
    }
}

/// Below the last task while one is held: time carries on at scale to 04:00 the
/// next morning, with faint hours and the next day named at midnight.
private struct NightRoom: View {
    let entries: [TimelineItem]
    let heldMinutes: Int
    let date: String
    let twentyFour: Bool
    /// The landing's bold start and end: hours next to them give way.
    let bold: [Int]

    var body: some View {
        let end = timelineLastEnd(entries) ?? 0
        let line = CGFloat(max(timelineLastStart - end, 0)) * CGFloat(timelinePointsPerMinute)
        ZStack(alignment: .topLeading) {
            Canvas { context, _ in
                let x = TimelineRow.timeColumn + 4 + TimelineRow.pillWidth / 2
                var path = Path()
                path.move(to: CGPoint(x: x, y: 0))
                path.addLine(to: CGPoint(x: x, y: line))
                context.stroke(path, with: .color(Palette.pale), style: StrokeStyle(lineWidth: 3, dash: [4, 6]))
            }
            ForEach(nightHours(entries).filter { hour in bold.allSatisfy { Double(abs($0 - hour)) * timelinePointsPerMinute >= 14 } },
                    id: \.self) { hour in
                HStack(spacing: 0) {
                    Text(columnClock(hour, twentyFour: twentyFour)).font(.caption2.monospacedDigit())
                        .frame(width: TimelineRow.timeColumn, alignment: .leading)
                    if hour == 24 * 60 {
                        Text(Civil.short(Civil.add(date, days: 1))).font(.caption2.weight(.semibold))
                            .padding(.leading, 4 + TimelineRow.pillWidth + 12)
                    }
                }
                .foregroundStyle(Color.secondary.opacity(0.7))
                .offset(y: CGFloat(hour - end) * CGFloat(timelinePointsPerMinute) - 7)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(height: CGFloat(nightRoom(entries, heldMinutes: heldMinutes)), alignment: .topLeading)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Top Wins, as on the old timeline: once something is starred, the day's
/// starred tasks as chips (tap one to scroll to it), "Top Wins · 1 of 3", and
/// "Day won" when they are all done.
@MainActor
struct WinsStrip: View {
    let tasks: [PlannerTask]
    let onJump: (PlannerTask) -> Void

    var body: some View {
        let wins = tasks.filter(\.starred)
        if !wins.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Label(winsTitle(wins), systemImage: "star.fill")
                    .font(.footnote.weight(.semibold))
                    .labelStyle(WinsLabel())
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        ForEach(wins) { task in
                            Button { onJump(task) } label: {
                                HStack(spacing: 5) {
                                    Image(systemName: task.done ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(Palette.accent)
                                    Text(task.title).strikethrough(task.done).lineLimit(1).frame(maxWidth: 195, alignment: .leading)
                                }
                                .font(.footnote)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(Palette.card, in: Capsule())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Top Win \(task.title), \(task.done ? "complete" : "incomplete"). Reveal task")
                        }
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Palette.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .padding(.horizontal, 16)
            .padding(.bottom, 10)
        }
    }
}

private struct WinsLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 7) {
            configuration.icon.foregroundStyle(Palette.accent)
            configuration.title
        }
    }
}

/// The compact card that follows the finger while a task is dragged.
private struct DragChip: View {
    let task: PlannerTask
    let twentyFour: Bool

    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(Palette.block(task)).frame(width: 36, height: 36)
                .overlay(Image(systemName: taskSymbol(task)).font(.system(size: 16, weight: .semibold)).foregroundStyle(.white))
            VStack(alignment: .leading, spacing: 1) {
                Text("\(rangeText(task.clockMinutes, task.clockMinutes + task.minutes, twentyFour: twentyFour)) (\(durationWords(task.minutes)))")
                    .font(.caption2).foregroundStyle(.secondary)
                Text(task.title).font(.subheadline.weight(.semibold)).lineLimit(1)
            }
        }
        .padding(.leading, 6)
        .padding(.trailing, 14)
        .padding(.vertical, 6)
        .background(Palette.card, in: Capsule())
    }
}

/// Where a dragged task will land: an empty outlined capsule, with its new
/// start and end in bold on the left.
private struct LandingOutline: View {
    let task: PlannerTask
    let start: Int
    let entries: [TimelineItem]
    let twentyFour: Bool

    var body: some View {
        let pill = CGFloat(pillHeight(task.minutes))
        ZStack(alignment: .topLeading) {
            Text(fullClock(start, twentyFour: twentyFour)).font(.caption2.weight(.bold)).lineLimit(1).offset(y: -6)
            Text(fullClock(start + task.minutes, twentyFour: twentyFour)).font(.caption2.weight(.bold)).lineLimit(1).offset(y: pill - 8)
            Capsule()
                .fill(Palette.card)
                .overlay(Capsule().stroke(Color(hex: 0xB8B8BD), lineWidth: 1.5))
                .frame(width: TimelineRow.pillWidth, height: pill)
                .offset(x: TimelineRow.timeColumn + 4)
        }
        .offset(y: CGFloat(offsetFor(start, in: entries)))
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .animation(.snappy(duration: 0.12), value: start)
    }
}

/// Turns where the finger is over the timeline into a time while a task is
/// dragged, and moves the task there on drop.
struct TimelineDrop: DropDelegate {
    let entries: [TimelineItem]
    @Binding var hover: Int?
    let signal: () -> Void
    let onDrop: (String, Int) -> Void

    /// The finger holds a task near its top, so the capsule's top lands just above it.
    private static let grab = 20.0

    private func minute(_ info: DropInfo) -> Int { minuteAt(Double(info.location.y) - Self.grab, in: entries) }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        signal()
        let value = minute(info)
        if value != hover { hover = value }
        return DropProposal(operation: .move)
    }

    func dropExited(info: DropInfo) { hover = nil }

    func performDrop(info: DropInfo) -> Bool {
        let value = minute(info)
        hover = nil
        guard let provider = info.itemProviders(for: [UTType.plainText]).first else { return false }
        _ = provider.loadObject(ofClass: NSString.self) { object, _ in
            guard let text = object as? NSString else { return }
            let id = text as String
            DispatchQueue.main.async { onDrop(id, value) }
        }
        return true
    }
}

/// Free time: the spine (coloured up to now, blending from one task's colour to
/// the next), the current time in bold if now falls here, and Structured's words.
@MainActor
struct GapRow: View {
    let start: Int
    let minutes: Int
    let next: String
    let previous: Color?
    let following: Color?
    let now: Int
    let twentyFour: Bool
    let onAdd: () -> Void

    var body: some View {
        let height = CGFloat(gapHeight(minutes))
        let end = start + minutes
        let nowY: CGFloat? = now >= start && now < end ? CGFloat(now - start) / CGFloat(minutes) * height : nil
        let from = previous ?? following ?? Palette.pale
        let to = following ?? previous ?? Palette.pale
        HStack(spacing: 0) {
            TimeColumn(height: height, labels: [], now: nowY.map { TimeLabel(y: $0, text: columnClock(now, twentyFour: twentyFour)) })
            Spacer().frame(width: 4)
            Canvas { context, size in
                let x = size.width / 2
                var line = Path()
                line.move(to: CGPoint(x: x, y: 0))
                line.addLine(to: CGPoint(x: x, y: size.height))
                context.stroke(line, with: .color(Palette.pale), lineWidth: 3)
                let reached: CGFloat = now >= end ? size.height : (nowY ?? 0)
                if reached > 0 {
                    var passed = Path()
                    passed.move(to: CGPoint(x: x, y: 0))
                    passed.addLine(to: CGPoint(x: x, y: reached))
                    context.stroke(passed, with: .linearGradient(Gradient(colors: [from, to]), startPoint: .zero,
                                                                 endPoint: CGPoint(x: 0, y: size.height)), lineWidth: 3)
                }
            }
            .frame(width: TimelineRow.pillWidth, height: height)
            Spacer().frame(width: 12)
            if minutes >= 180 {
                VStack(alignment: .leading, spacing: 6) {
                    Label {
                        Text("A window: ") + Text(durationText(minutes)).foregroundStyle(Palette.accent) + Text(" of potential.")
                    } icon: {
                        Image(systemName: "clock")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    Button(action: onAdd) {
                        Label("Add Task", systemImage: "plus.circle.fill")
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(Palette.accent.opacity(0.14), in: Capsule())
                            .foregroundStyle(Palette.accent)
                    }
                    .buttonStyle(.plain)
                }
            } else if minutes >= 30 {
                Label {
                    Text("You'll have ") + Text(durationText(minutes)).foregroundStyle(Palette.accent) + Text(" free. Anything you'd like to fit in?")
                } icon: {
                    Image(systemName: "clock")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .frame(height: height)
        .contentShape(Rectangle())
        .onTapGesture(perform: onAdd)
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
