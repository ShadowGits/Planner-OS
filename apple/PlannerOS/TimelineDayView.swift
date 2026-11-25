import SwiftUI

// One day of the timeline's scroll: where it starts, its untimed tasks, and
// its 24 hours. Positions all come from TimelinePolicy, which the gestures
// hit-test with too.

/// The buttons a swipe to the left uncovers.
enum SwipeAction: CaseIterable, Identifiable {
    case nextDay, archive, delete

    var id: Self { self }
    static let width = 68.0

    var label: String {
        switch self {
        case .nextDay: return "Next day"
        case .archive: return "Archive"
        case .delete: return "Delete"
        }
    }

    var symbol: String {
        switch self {
        case .nextDay: return "arrow.turn.up.right"
        case .archive: return "archivebox.fill"
        case .delete: return "trash.fill"
        }
    }

    var color: Color {
        switch self {
        case .nextDay: return Color(hex: 0x3B6EA8)
        case .archive: return Color(hex: 0x3A8564)
        case .delete: return Color(hex: 0xC7372F)
        }
    }

    /// A habit's day and a calendar event have no place in the Inbox, and
    /// neither does work that is finished, so those have no Archive.
    static func offered(for task: PlannerTask) -> [SwipeAction] {
        task.habit || task.fromCalendar || task.done ? [.nextDay, .delete] : allCases
    }
}

/// A task pulled to the left, part way or all the way.
struct SwipeState: Equatable {
    var hit: TimelineHit
    /// Zero at rest, negative as it uncovers the buttons.
    var x = 0.0
    /// Where this pull started from.
    var from = 0.0

    var actions: [SwipeAction] { SwipeAction.offered(for: hit.task) }
    var fullWidth: Double { Double(actions.count) * SwipeAction.width }
    var isOpen: Bool { x <= -fullWidth + 1 }

    /// Where the buttons are, in the scroll's coordinates: against the right
    /// edge, level with the task, and never too thin to hit.
    func bar(width: Double) -> CGRect {
        let height = min(max(Double(hit.frame.height), 44), 76)
        return CGRect(x: width - timelineTrailing + x, y: Double(hit.frame.minY), width: -x, height: height)
    }
}

/// What a day's buttons do.
struct TimelineTaskActions {
    var open: (PlannerTask) -> Void
    var toggle: (PlannerTask) -> Void
    var star: (PlannerTask) -> Void
    var act: (SwipeAction, PlannerTask, _ shownOn: String) -> Void
    var add: (_ date: String, _ start: Int) -> Void
}

@MainActor
struct TimelineDayView: View, Equatable {
    let day: TimelineDay
    let width: Double
    let today: String
    /// Minutes since midnight, now.
    let minute: Int
    let twentyFour: Bool
    let swipe: SwipeState?
    /// The task in the hand, which is drawn where it will land instead.
    let hiddenID: String?
    let actions: TimelineTaskActions

    // Everything drawn is compared. The actions are not: they act on what is
    // current when they run, whichever copy of them that is.
    nonisolated static func == (a: TimelineDayView, b: TimelineDayView) -> Bool {
        a.day == b.day && a.width == b.width && a.today == b.today && a.minute == b.minute
            && a.twentyFour == b.twentyFour && a.swipe == b.swipe && a.hiddenID == b.hiddenID
    }

    var body: some View {
        let now = nowOnDay(day.date, today: today, minutes: minute)
        ZStack(alignment: .topLeading) {
            DayHeader(date: day.date, today: today)
                .frame(width: width, height: timelineHeaderHeight)
            untimed
                .offset(y: day.untimedTop - day.top)
            HourGrid(width: width, twentyFour: twentyFour, now: day.date == today ? minute : nil)
                .offset(y: day.gridTop - day.top)
            freeTime
                .offset(x: timelineLabelWidth, y: day.gridTop - day.top)
            blocks(now: now)
                .offset(x: timelineLabelWidth, y: day.gridTop - day.top)
            if day.date == today {
                NowBar(label: columnClock(minute, twentyFour: twentyFour))
                    .frame(width: width, height: 16)
                    .offset(y: day.gridTop - day.top + minuteOffset(minute) - 8)
            }
            if let swipe, swipe.hit.date == day.date, swipe.x < 0 {
                let bar = swipe.bar(width: width)
                SwipeBar(swipe: swipe) { actions.act($0, swipe.hit.task, day.date) }
                    .frame(width: Double(bar.width), height: Double(bar.height))
                    .offset(x: Double(bar.minX), y: Double(bar.minY) - day.top)
            }
        }
        .frame(width: width, height: day.bottom - day.top, alignment: .topLeading)
    }

    private var untimed: some View {
        let rowWidth = max(width - 2 * timelineTrailing, 1)
        return VStack(spacing: 0) {
            ForEach(day.untimed) { task in
                UntimedRow(task: task, onOpen: { actions.open(task) }, onToggle: { actions.toggle(task) },
                           onStar: { actions.star(task) })
                    #if os(macOS)
                    // On the iPhone this is a hold let go without moving, as holding also drags.
                    .contextMenu {
                        Button(task.done ? "Reopen" : "Mark done") { actions.toggle(task) }
                        Button("Edit") { actions.open(task) }
                    }
                    #endif
                    .frame(width: rowWidth)
                    .offset(x: slide(task.id))
                    .opacity(hiddenID == task.id ? 0 : 1)
                    .taskActions(task, day: day.date, actions: actions)
            }
        }
        .frame(width: rowWidth, alignment: .topLeading)
        .clipped()
        .offset(x: timelineTrailing)
    }

    /// Under the blocks: what is free between them, or that nothing is planned at all.
    private var freeTime: some View {
        let space = max(width - timelineLabelWidth - timelineTrailing, 1)
        let current = day.date == today ? minute : nil
        return ZStack(alignment: .topLeading) {
            Color.clear.allowsHitTesting(false)
            ForEach(day.gaps) { gap in
                GapSlot(gap: gap, now: current, twentyFour: twentyFour) { actions.add(day.date, gap.addAt) }
                    .frame(width: space, height: gap.height)
                    .offset(y: gap.top)
            }
            if day.blocks.isEmpty {
                EmptyDay(hasUntimed: !day.untimed.isEmpty)
                    .frame(width: space)
                    // Just under now today; at nine, where a day usually starts, on the others.
                    .offset(y: min(current.map { minuteOffset($0) + 30 } ?? minuteOffset(9 * 60), timelineDayHeight - 130))
            }
        }
        .frame(width: space, height: timelineDayHeight, alignment: .topLeading)
    }

    private func blocks(now: Int) -> some View {
        let space = max(width - timelineLabelWidth - timelineTrailing, 1)
        return ZStack(alignment: .topLeading) {
            Color.clear.allowsHitTesting(false)
            ForEach(day.blocks) { block in
                let frame = block.frame(width: space)
                TaskBlock(block: block, width: Double(frame.width), now: now, twentyFour: twentyFour,
                          onOpen: { actions.open(block.task) }, onToggle: { actions.toggle(block.task) },
                          onStar: { actions.star(block.task) })
                    .taskActions(block.task, day: day.date, actions: actions)
                    .opacity(hiddenID == block.id ? 0 : 1)
                    .offset(x: Double(frame.minX) + slide(block.id), y: block.top)
            }
        }
        .frame(width: space, height: timelineDayHeight, alignment: .topLeading)
        .clipped()
    }

    private func slide(_ id: String) -> Double {
        guard let swipe, swipe.hit.date == day.date, swipe.hit.task.id == id else { return 0 }
        return swipe.x
    }
}

private extension View {
    /// The swipe's buttons for VoiceOver, which cannot swipe.
    func taskActions(_ task: PlannerTask, day: String, actions: TimelineTaskActions) -> some View {
        accessibilityElement(children: .contain)
            .accessibilityActions {
                ForEach(SwipeAction.offered(for: task)) { action in
                    Button(action.label) { actions.act(action, task, day) }
                }
            }
    }
}

/// Where a day starts: a thick line right across, and the date in bold.
private struct DayHeader: View {
    let date: String
    let today: String

    private var relative: String? {
        switch Civil.between(today, date) {
        case 0: return "Today"
        case 1: return "Tomorrow"
        case -1: return "Yesterday"
        default: return nil
        }
    }

    var body: some View {
        let isToday = date == today
        VStack(spacing: 0) {
            Rectangle().fill(isToday ? Palette.accent : Color.primary).frame(height: 5)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Civil.longDay(date))
                    .font(.system(size: 22, weight: .heavy))
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .accessibilityIdentifier("day-\(date)")
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                if let relative {
                    Text(relative)
                        .font(.subheadline.weight(.bold))
                        .foregroundStyle(isToday ? Palette.accent : Color.secondary)
                }
            }
            .padding(.horizontal, 14)
            .frame(maxHeight: .infinity)
            .background(isToday ? Palette.accent.opacity(0.2) : Color.primary.opacity(0.09))
        }
        .allowsHitTesting(false)
    }
}

/// All 24 hours, each 50 points: a line and its time on the left.
private struct HourGrid: View {
    let width: Double
    let twentyFour: Bool
    /// The now bar's minute, whose bold time the labels beside it give way to.
    let now: Int?

    var body: some View {
        ZStack(alignment: .topLeading) {
            // Plain one-point layers: a Canvas here is a bitmap 1200 points tall
            // for every day, made just as that day scrolls in under a drag.
            ForEach(0...24, id: \.self) { hour in
                Rectangle()
                    .fill(Color.secondary.opacity(0.22))
                    .frame(width: max(width - timelineLabelWidth, 0), height: 1)
                    .offset(x: timelineLabelWidth, y: min(minuteOffset(hour * 60), timelineDayHeight - 1))
            }
            ForEach(0..<24, id: \.self) { hour in
                if now.map({ abs(minuteOffset($0) - minuteOffset(hour * 60)) >= 14 }) ?? true {
                    Text(hourLabel(hour, twentyFour: twentyFour))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .frame(width: timelineLabelWidth - 8, height: 14, alignment: .trailing)
                        .offset(y: minuteOffset(hour * 60) - 7)
                }
            }
        }
        .frame(width: width, height: timelineDayHeight, alignment: .topLeading)
        .allowsHitTesting(false)
    }
}

/// Free time, all of which taps to add a task that starts with it.
@MainActor
private struct GapSlot: View {
    let gap: TimelineGap
    let now: Int?
    let twentyFour: Bool
    let onAdd: () -> Void

    private var wordsHeight: Double { gap.minutes >= 180 ? 64 : 34 }

    /// At the gap's top, or just under now while now is in it, which is where the screen opens.
    private var inset: Double {
        guard let now, now >= gap.start, now < gap.start + gap.minutes else { return 4 }
        let below = minuteOffset(now) - gap.top + 10
        return below >= 4 && below + wordsHeight <= gap.height ? below : 4
    }

    var body: some View {
        let free = Text(durationText(gap.minutes)).foregroundStyle(Palette.accent)
        Button(action: onAdd) {
            VStack(alignment: .leading, spacing: 6) {
                if gap.minutes >= 180, gap.height >= 60 {
                    Label {
                        Text("A window: ") + free + Text(" of potential.")
                    } icon: {
                        Image(systemName: "clock")
                    }
                    .font(.caption)
                    Label("Add Task", systemImage: "plus.circle.fill")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Palette.accent.opacity(0.14), in: Capsule())
                        .foregroundStyle(Palette.accent)
                } else if gap.minutes >= 30, gap.height >= 14 {
                    Label {
                        Text("You'll have ") + free + Text(" free. Anything you'd like to fit in?")
                    } icon: {
                        Image(systemName: "clock")
                    }
                    .font(.caption)
                    .lineLimit(gap.height >= 40 ? 2 : 1)
                    .minimumScaleFactor(0.75)
                }
            }
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.leading)
            .padding(.leading, 10)
            .padding(.trailing, 4)
            .padding(.top, gap.height < 34 ? max((gap.height - 16) / 2, 0) : inset)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .clipped()
        }
        .buttonStyle(.hitArea)
        .accessibilityLabel("Add a task at \(fullClock(gap.addAt, twentyFour: twentyFour)), \(durationText(gap.minutes)) free")
        .accessibilityIdentifier("timeline-gap-\(gap.addAt)")
    }
}

private struct EmptyDay: View {
    let hasUntimed: Bool

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "sun.horizon").font(.system(size: 36)).foregroundStyle(.secondary)
            Text(hasUntimed ? "Nothing at a set time" : "Nothing planned").font(.headline)
            Text("Tap + to add a task.").font(.subheadline).foregroundStyle(.secondary)
        }
        .allowsHitTesting(false)
    }
}

/// The now bar: the time in bold on the left and a line across the day.
private struct NowBar: View {
    let label: String

    var body: some View {
        HStack(spacing: 4) {
            Text(label)
                .font(.caption2.monospacedDigit().weight(.bold))
                .lineLimit(1)
                .frame(width: timelineLabelWidth - 8, alignment: .trailing)
            Circle().fill(Color.red).frame(width: 7, height: 7)
            Rectangle().fill(Color.red.opacity(0.75)).frame(height: 1.5)
        }
        .allowsHitTesting(false)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Now, \(label)")
    }
}

/// One timed task. Pale ahead of now, filled down to now while it runs, solid
/// once passed or done.
///
/// The body, the star and the tick are three buttons side by side in a stack,
/// the body underneath. None is inside another, and none is a bare tap gesture:
/// on the Mac those are how a click on the tick came to open the editor.
@MainActor
private struct TaskBlock: View {
    let block: TimelineBlock
    let width: Double
    let now: Int
    let twentyFour: Bool
    let onOpen: () -> Void
    let onToggle: () -> Void
    let onStar: () -> Void

    var body: some View {
        let task = block.task
        let parts = BlockParts(width: width, height: block.height)
        let color = Palette.block(task)
        let phase = taskPhase(task, now: now)
        let progress = taskProgress(task, now: now)
        let solid = phase == .past || phase == .done
        let controlsSolid = solid || (phase == .underway && progress > 0.75)
        ZStack(alignment: .topLeading) {
            fill(color: color, phase: phase, progress: progress, solid: solid)
            Button(action: onOpen) {
                label(task, parts: parts, color: color, phase: phase, solid: solid)
                    .frame(width: width, height: block.height, alignment: .topLeading)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel(task.title)
            .accessibilityValue(detail(task, phase: phase))
            .accessibilityHint("Swipe left for more. Hold, then drag to change the time")
            if let star = parts.star {
                Button(action: onStar) {
                    Image(systemName: task.starred ? "star.fill" : "star")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(starColor(task.starred, solid: controlsSolid))
                        .frame(width: Double(star.width), height: Double(star.height))
                }
                .buttonStyle(.hitArea)
                .accessibilityLabel("\(task.starred ? "Remove" : "Choose") \(task.title) as Top Win")
                .offset(x: Double(star.minX), y: Double(star.minY))
            }
            Button(action: onToggle) {
                TickCircle(done: task.done, ink: controlsSolid ? .white : color, check: controlsSolid ? color : .white,
                           size: min(22, Double(parts.tick.height) - 6, Double(parts.tick.width) - 4))
                    .frame(width: Double(parts.tick.width), height: Double(parts.tick.height))
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel("\(task.done ? "Reopen" : "Complete") \(task.title)")
            .offset(x: Double(parts.tick.minX), y: Double(parts.tick.minY))
        }
        .frame(width: width, height: block.height, alignment: .topLeading)
        .clipShape(RoundedRectangle(cornerRadius: min(9, block.height / 3), style: .continuous))
    }

    private func fill(color: Color, phase: TaskPhase, progress: Double, solid: Bool) -> some View {
        ZStack(alignment: .topLeading) {
            Palette.card
            color.opacity(solid ? 1 : 0.2)
            if phase == .underway { color.frame(height: max(block.height * progress, 1)) }
            if !solid { color.frame(width: 4) }
        }
        .frame(width: width, height: block.height, alignment: .topLeading)
        .allowsHitTesting(false)
    }

    private func starColor(_ starred: Bool, solid: Bool) -> Color {
        if solid { return .white.opacity(starred ? 1 : 0.75) }
        return starred ? Palette.accent : Color.secondary
    }

    private func detail(_ task: PlannerTask, phase: TaskPhase) -> String {
        [fullWhen(task, phase: phase), extras(task)].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func fullWhen(_ task: PlannerTask, phase: TaskPhase) -> String {
        phase == .underway ? remainingText(task, now: now)
            : "\(rangeText(task.clockMinutes, task.clockMinutes + task.minutes, twentyFour: twentyFour)) (\(durationWords(task.minutes)))"
    }

    /// When and how long, for where there is little room: "9:00 · 30m".
    private func brief(_ task: PlannerTask, phase: TaskPhase) -> String {
        phase == .underway ? "\(durationText(max(task.clockMinutes + task.minutes - now, 1))) left"
            : "\(columnClock(task.clockMinutes, twentyFour: twentyFour)) · \(durationText(task.minutes))"
    }

    private func extras(_ task: PlannerTask) -> String {
        ([partText(task)].compactMap { $0 } + (task.workedSeconds > 0 ? [workedText(task)] : [])).joined(separator: " · ")
    }

    /// One line in a short block; the title, then when, then the extras as room allows.
    private func label(_ task: PlannerTask, parts: BlockParts, color: Color, phase: TaskPhase, solid: Bool) -> some View {
        let height = block.height
        let narrow = width < 120
        let more = extras(task)
        let ink: Color = solid || (phase == .underway && taskProgress(task, now: now) * height > 24) ? .white : .primary
        // Clear of the buttons, unless the block is tall enough to write above them.
        let clear = height >= 100 ? 6 : width - Double(parts.star?.minX ?? parts.tick.minX) + 2
        return VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 5) {
                if !narrow {
                    Image(systemName: taskSymbol(task))
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(ink == .white ? Color.white : color)
                }
                Text(task.title)
                    .font(.system(size: narrow ? 11 : 14, weight: .semibold))
                    .strikethrough(task.done)
                    .lineLimit(height >= 80 ? 2 : 1)
                    .multilineTextAlignment(.leading)
                if !narrow, task.recurrenceKey != nil || task.habit {
                    Image(systemName: "repeat").font(.system(size: 9))
                }
                // Too short for a second line, so it all goes on the first.
                if height < 40, width >= 160 {
                    Text(brief(task, phase: phase))
                        .font(.caption2.monospacedDigit())
                        .opacity(0.85)
                        .fixedSize()
                    if !more.isEmpty {
                        Text(more).font(.caption2).opacity(0.85).lineLimit(1).layoutPriority(-1)
                    }
                }
            }
            if height >= 40 {
                ViewThatFits(in: .horizontal) {
                    if height >= 64 || more.isEmpty { Text(fullWhen(task, phase: phase)) }
                    Text([brief(task, phase: phase), height >= 64 ? "" : more].filter { !$0.isEmpty }.joined(separator: " · "))
                    Text(brief(task, phase: phase))
                }
                .font(.caption2.monospacedDigit())
                .opacity(0.85)
                .lineLimit(1)
            }
            if height >= 64, !more.isEmpty {
                Text(more).font(.caption2.weight(.medium)).opacity(0.85).lineLimit(height >= 80 ? 2 : 1)
            }
        }
        .foregroundStyle(ink)
        .padding(.leading, narrow ? 7 : 10)
        .padding(.trailing, clear)
        .padding(.top, height < 40 ? max((height - 18) / 2, 0) : 5)
    }
}

/// A hollow circle, filled and checked once done.
struct TickCircle: View {
    let done: Bool
    let ink: Color
    let check: Color
    let size: Double

    var body: some View {
        ZStack {
            Circle().stroke(ink, lineWidth: 2)
            if done {
                Circle().fill(ink)
                Image(systemName: "checkmark").font(.system(size: size * 0.5, weight: .bold)).foregroundStyle(check)
            }
        }
        .frame(width: size, height: size)
    }
}

/// Next day, Archive and Delete, uncovered from the right as in Mail.
@MainActor
private struct SwipeBar: View {
    let swipe: SwipeState
    let act: (SwipeAction) -> Void

    var body: some View {
        HStack(spacing: 0) {
            ForEach(swipe.actions) { action in
                Button { act(action) } label: {
                    VStack(spacing: 2) {
                        Image(systemName: action.symbol).font(.system(size: 14, weight: .semibold))
                        Text(action.label).font(.system(size: 11, weight: .semibold)).lineLimit(1).fixedSize()
                    }
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(action.color)
                }
                .buttonStyle(.hitArea)
                .accessibilityLabel(action.label)
                .accessibilityIdentifier("swipe-\(action.label)")
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        .allowsHitTesting(swipe.isOpen)
    }
}

/// Where a held task will land: its outline, with the new day and time in bold.
struct LandingOutline: View {
    let task: PlannerTask
    let date: String
    let start: Int
    let width: Double
    let height: Double
    let twentyFour: Bool

    var body: some View {
        let color = Palette.block(task)
        ZStack(alignment: .topLeading) {
            // Opaque, or its words and those of the task under it are read as one.
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Palette.card)
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(color.opacity(0.3))
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .strokeBorder(color, lineWidth: 2)
            HStack(spacing: 6) {
                Text("\(Civil.short(date)), \(rangeText(start, start + task.minutes, twentyFour: twentyFour))").fontWeight(.bold)
                Text(task.title).foregroundStyle(.secondary)
            }
            .font(.caption)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
        }
        .frame(width: width, height: height)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
