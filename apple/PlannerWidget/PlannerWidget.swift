import SwiftUI
import WidgetKit

/* The home-screen and lock-screen widget.
 *
 * It reads the day the app left in the App Group and draws it — no network,
 * no app key, nothing to sign in to. It asks to be redrawn at each task's
 * start and end rather than on a timer, so "now" is right without waking it
 * every few minutes for nothing.
 */

struct PlannerEntry: TimelineEntry {
    let date: Date
    let snapshot: PlannerSnapshot?
    /// Minutes after midnight at `date`, in the device's zone.
    let minute: Int

    var current: PlannerSnapshot.Item? { snapshot?.current(at: minute) }
    var next: PlannerSnapshot.Item? { snapshot?.upcoming(after: minute).first }
    /// The day is only this snapshot's day; yesterday's leftovers are not today.
    var fresh: Bool {
        guard let snapshot else { return false }
        return snapshot.date == PlannerEntry.today()
    }

    /// The planner's day runs to 04:00, like the app: at 01:30 this is still
    /// the evening's date, and the clock reads 25:30 so a task after midnight
    /// sorts and counts down correctly.
    static func today(_ now: Date = Date()) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: now.addingTimeInterval(-4 * 3600))
    }

    static func minutes(_ now: Date = Date()) -> Int {
        let parts = Calendar.current.dateComponents([.hour, .minute], from: now)
        let minute = (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
        return minute < 4 * 60 ? minute + 24 * 60 : minute
    }
}

struct PlannerProvider: TimelineProvider {
    func placeholder(in context: Context) -> PlannerEntry {
        PlannerEntry(date: Date(), snapshot: PlannerWidgetSample.snapshot, minute: 9 * 60 + 40)
    }

    func getSnapshot(in context: Context, completion: @escaping (PlannerEntry) -> Void) {
        let snapshot = context.isPreview ? PlannerWidgetSample.snapshot : PlannerSnapshot.load()
        completion(PlannerEntry(date: Date(), snapshot: snapshot, minute: PlannerEntry.minutes()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<PlannerEntry>) -> Void) {
        let now = Date()
        let snapshot = PlannerSnapshot.load()
        let minute = PlannerEntry.minutes(now)
        // A redraw is also a chance to send any tick still waiting; it never
        // holds the drawing up.
        if !PendingTicks.all().isEmpty {
            Task.detached(priority: .utility) {
                if await PendingTicks.flush() { WidgetCenter.shared.reloadAllTimelines() }
            }
        }
        var entries = [PlannerEntry(date: now, snapshot: snapshot, minute: minute)]

        // Redraw when a task starts or finishes, and once more at midnight so
        // a finished day does not sit there looking like today's.
        let points = (snapshot?.turningPoints(from: minute) ?? []).prefix(24)
        let midnight = Calendar.current.startOfDay(for: now)
        for point in points {
            guard let at = Calendar.current.date(byAdding: .minute, value: point, to: midnight) else { continue }
            entries.append(PlannerEntry(date: at, snapshot: snapshot, minute: point))
        }
        let tomorrow = Calendar.current.date(byAdding: .day, value: 1, to: midnight) ?? now.addingTimeInterval(3600)
        completion(Timeline(entries: entries, policy: .after(min(tomorrow, now.addingTimeInterval(4 * 3600)))))
    }
}

// MARK: - Looks

enum PlannerWidgetPalette {
    /// The same eight colours the timeline uses, in the same order.
    static let blocks: [Color] = [0xF19E98, 0xF19C74, 0xEAA93B, 0x91BE6C,
                                  0x6085A8, 0x3A8564, 0x974667, 0x2B5073].map(color)
    static let accent = color(0xF19E98)

    static func color(_ hex: UInt32) -> Color {
        Color(red: Double((hex >> 16) & 0xFF) / 255,
              green: Double((hex >> 8) & 0xFF) / 255,
              blue: Double(hex & 0xFF) / 255)
    }

    static func block(_ item: PlannerSnapshot.Item) -> Color {
        blocks[min(max(item.palette, 0), blocks.count - 1)]
    }
}

func widgetClock(_ minute: Int) -> String {
    let m = ((minute % 1440) + 1440) % 1440, hour = m / 60
    let twentyFour = !(DateFormatter.dateFormat(fromTemplate: "j", options: 0, locale: .current) ?? "").contains("a")
    if twentyFour { return String(format: "%02d:%02d", hour, m % 60) }
    return "\(hour % 12 == 0 ? 12 : hour % 12):" + String(format: "%02d", m % 60)
}

/// "28m left", "1h 5m left".
func widgetRemaining(_ minutes: Int) -> String {
    let n = max(minutes, 1)
    if n < 60 { return "\(n)m left" }
    return n % 60 == 0 ? "\(n / 60)h left" : "\(n / 60)h \(n % 60)m left"
}

private struct TaskLine: View {
    let item: PlannerSnapshot.Item
    var underway = false
    /// Off on the lock screen and in the small size, where there is no room
    /// for a target big enough to hit.
    var tickable = true

    var body: some View {
        HStack(spacing: 7) {
            Capsule()
                .fill(PlannerWidgetPalette.block(item))
                .frame(width: 3)
            Text(widgetClock(item.start))
                .font(.caption2.monospacedDigit())
                .foregroundStyle(underway ? PlannerWidgetPalette.accent : .secondary)
                .frame(width: 42, alignment: .leading)
            Text(item.title)
                .font(.caption.weight(underway ? .bold : .medium))
                .strikethrough(item.done)
                .foregroundStyle(item.done ? .secondary : .primary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: 4)
            if tickable { TickButton(item: item) }
        }
    }
}

/// The tick itself. Tapping it marks the task done without opening the app —
/// the widget's own copy changes at once and the server is told behind it.
private struct TickButton: View {
    let item: PlannerSnapshot.Item

    var body: some View {
        Button(intent: ToggleTaskIntent(taskId: item.id, done: !item.done)) {
            ZStack {
                Circle()
                    .strokeBorder(PlannerWidgetPalette.block(item), lineWidth: 2)
                    .frame(width: 22, height: 22)
                if item.done {
                    Circle().fill(PlannerWidgetPalette.block(item)).frame(width: 22, height: 22)
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .frame(width: 34, height: 34)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(item.done ? "Reopen \(item.title)" : "Tick off \(item.title)")
    }
}

/// Nothing to draw: say which of the two reasons it is.
private struct EmptyLook: View {
    let entry: PlannerEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: entry.snapshot == nil ? "arrow.triangle.2.circlepath" : "sun.horizon")
                .font(.title3)
                .foregroundStyle(PlannerWidgetPalette.accent)
            Text(entry.snapshot == nil ? "Open Planner OS once" : "Nothing left today")
                .font(.caption.weight(.semibold))
            Text(entry.snapshot == nil ? "It fills in after the app syncs." : "The day is clear.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }
}

struct PlannerWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: PlannerEntry

    var body: some View {
        switch family {
        case .accessoryInline:
            Text(inlineText)
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                VStack(spacing: 0) {
                    Image(systemName: "checklist").font(.caption2)
                    Text("\(entry.fresh ? (entry.snapshot?.remaining ?? 0) : 0)")
                        .font(.headline.monospacedDigit())
                }
            }
        case .accessoryRectangular:
            VStack(alignment: .leading, spacing: 2) {
                Text(headline).font(.caption.weight(.semibold)).lineLimit(1)
                Text(subhead).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        case .systemMedium:
            medium
        case .systemLarge, .systemExtraLarge:
            large
        default:
            small
        }
    }

    private var upcoming: [PlannerSnapshot.Item] {
        entry.fresh ? (entry.snapshot?.upcoming(after: entry.minute) ?? []) : []
    }

    private var inlineText: String {
        guard entry.fresh else { return "Planner OS" }
        if let now = entry.current { return "\(now.title) · \(widgetRemaining(now.end - entry.minute))" }
        if let next = entry.next { return "\(widgetClock(next.start)) \(next.title)" }
        return "Nothing left today"
    }

    private var headline: String {
        guard entry.fresh else { return "Planner OS" }
        return entry.current?.title ?? entry.next?.title ?? "Nothing left today"
    }

    private var subhead: String {
        guard entry.fresh else { return "Open the app to refresh" }
        if let now = entry.current { return widgetRemaining(now.end - entry.minute) }
        if let next = entry.next { return "at \(widgetClock(next.start))" }
        return "The day is clear"
    }

    @ViewBuilder private var small: some View {
        if !entry.fresh || (entry.current == nil && upcoming.isEmpty) {
            EmptyLook(entry: entry)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                if let now = entry.current {
                    Text("NOW").font(.system(size: 9, weight: .bold)).foregroundStyle(PlannerWidgetPalette.accent)
                    Text(now.title).font(.subheadline.weight(.bold)).lineLimit(2)
                    Text(widgetRemaining(now.end - entry.minute))
                        .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                    ProgressView(value: Double(entry.minute - now.start), total: Double(max(now.minutes, 1)))
                        .tint(PlannerWidgetPalette.block(now))
                } else if let next = upcoming.first {
                    Text("NEXT").font(.system(size: 9, weight: .bold)).foregroundStyle(.secondary)
                    Text(next.title).font(.subheadline.weight(.bold)).lineLimit(2)
                    Text("at \(widgetClock(next.start))")
                        .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                Text(footer).font(.system(size: 9)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder private var medium: some View {
        if !entry.fresh || (entry.current == nil && upcoming.isEmpty) {
            EmptyLook(entry: entry)
        } else {
            VStack(alignment: .leading, spacing: 7) {
                if let now = entry.current {
                    HStack(alignment: .center, spacing: 6) {
                        Text(now.title).font(.subheadline.weight(.bold)).lineLimit(1)
                        Spacer(minLength: 0)
                        Text(widgetRemaining(now.end - entry.minute))
                            .font(.caption2.monospacedDigit()).foregroundStyle(PlannerWidgetPalette.accent)
                        TickButton(item: now)
                    }
                    ProgressView(value: Double(entry.minute - now.start), total: Double(max(now.minutes, 1)))
                        .tint(PlannerWidgetPalette.block(now))
                }
                ForEach(Array(upcoming.prefix(entry.current == nil ? 3 : 2))) { item in
                    TaskLine(item: item)
                }
                Spacer(minLength: 0)
                Text(footer).font(.system(size: 9)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }

    /// What is on now and the five after it, each tickable.
    ///
    /// Six rows, not as many as will fit: eight plus dividers, a progress bar
    /// and a "+2 more" ran into the widget's own margins and clipped the
    /// heading. A widget cannot scroll — it is a picture, not a view — so what
    /// does not fit is simply not shown, and the app is a tap away.
    @ViewBuilder private var large: some View {
        if !entry.fresh {
            EmptyLook(entry: entry)
        } else {
            let rows = entry.snapshot?.window(at: entry.minute, count: family == .systemExtraLarge ? 9 : 6) ?? []
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Today")
                        .font(.subheadline.weight(.bold))
                    Spacer(minLength: 8)
                    Text(footer)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .padding(.bottom, 10)

                if rows.isEmpty {
                    Text("Nothing planned.").font(.caption).foregroundStyle(.secondary)
                } else {
                    VStack(spacing: 0) {
                        ForEach(rows) { item in
                            TaskLine(item: item, underway: item.id == entry.current?.id)
                                .frame(maxHeight: .infinity)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var footer: String {
        guard let snapshot = entry.snapshot, entry.fresh else { return "" }
        let left = "\(snapshot.remaining) left"
        return snapshot.waiting > 0 ? "\(left) · \(snapshot.waiting) waiting" : left
    }
}

// MARK: - The widget

struct PlannerWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "PlannerOSToday", provider: PlannerProvider()) { entry in
            PlannerWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Today")
        .description("Your day, with a tick beside each task. The large size shows all of it.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge, .systemExtraLarge,
                            .accessoryInline, .accessoryCircular, .accessoryRectangular])
    }
}

@main
struct PlannerWidgetBundle: WidgetBundle {
    var body: some Widget { PlannerWidget() }
}

enum PlannerWidgetSample {
    static let snapshot = PlannerSnapshot(
        date: PlannerEntry.today(),
        updated: Date(),
        tasks: [
            .init(id: "1", title: "German — A1 unit 4", start: 9 * 60 + 30, minutes: 60, done: false, palette: 0),
            .init(id: "2", title: "Shortlist screening", start: 11 * 60, minutes: 90, done: false, palette: 4),
            .init(id: "3", title: "Gym", start: 17 * 60 + 30, minutes: 90, done: false, palette: 3),
        ],
        waiting: 2
    )
}
