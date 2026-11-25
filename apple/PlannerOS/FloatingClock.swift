#if os(macOS)
import AppKit
import SwiftUI

/// The clock that floats over everything on the Mac: the task under way with
/// its time running down, or the next one with the time until it starts.
///
/// A panel of its own rather than a SwiftUI scene, because it must stay above
/// other apps, follow you across Spaces and full screen, and take a click
/// without pulling Planner OS in front of what you are working on.
@MainActor
final class FloatingClock: NSObject {
    static let shared = FloatingClock()
    /// Where "show the clock" is kept; on until switched off.
    static let shownKey = "floating_clock"
    private static let frameName = "FloatingClock"
    static let size = CGSize(width: 356, height: 124)

    private var store: PlannerStore?
    private var panel: NSPanel?

    /// Called whenever the main window appears or the connection changes.
    func attach(store: PlannerStore) {
        if self.store == nil {
            self.store = store
            NotificationCenter.default.addObserver(self, selector: #selector(defaultsChanged),
                                                   name: UserDefaults.didChangeNotification, object: nil)
            // PlannerStore owns the single network refresh loop, even with no window.
        }
        update()
    }

    // Defaults can change on any thread.
    @objc private nonisolated func defaultsChanged() {
        Task { @MainActor in FloatingClock.shared.update() }
    }

    private var wanted: Bool {
        // It would sit on top of what the UI tests click.
        guard let store, store.connection != nil, !ConnectionStore.isUITesting else { return false }
        return UserDefaults.standard.object(forKey: Self.shownKey) as? Bool ?? true
    }

    func update() {
        guard wanted, let store else {
            panel?.orderOut(nil)
            return
        }
        let panel = self.panel ?? makePanel(store)
        self.panel = panel
        if !panel.isVisible { panel.orderFrontRegardless() }
    }

    private func makePanel(_ store: PlannerStore) -> NSPanel {
        let panel = ClockPanel(contentRect: NSRect(origin: .zero, size: Self.size),
                               styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isExcludedFromWindowsMenu = true
        panel.isMovableByWindowBackground = true
        panel.becomesKeyOnlyIfNeeded = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.contentView = ClockHost(rootView: AnyView(FloatingClockView(onOpen: { [weak self] in self?.showMain() })
            .environment(store)))

        // Where it was left, unless that screen has since gone.
        let restored = panel.setFrameUsingName(Self.frameName)
        panel.setContentSize(Self.size)
        if !restored || !NSScreen.screens.contains(where: { $0.visibleFrame.intersects(panel.frame) }),
           let screen = NSScreen.main?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: screen.maxX - Self.size.width - 16, y: screen.maxY - Self.size.height - 16))
        }
        panel.setFrameAutosaveName(Self.frameName)
        return panel
    }

    /// Brings Planner OS forward, with its window if that was closed.
    func showMain() {
        NSApp.activate()
        if let window = NSApp.windows.first(where: { $0.canBecomeMain && ($0.isVisible || $0.isMiniaturized) }) {
            window.deminiaturize(nil)
            window.makeKeyAndOrderFront(nil)
        } else {
            reopen()
        }
    }
}

/// What a click on the Dock icon sends, which has SwiftUI open a window when
/// none is. `openWindow` would need the window group to have an id, and giving
/// it one renames the window macOS saved: the next launch after updating then
/// finds nothing to restore and opens no window at all.
private func reopen() {
    let event = NSAppleEventDescriptor.appleEvent(
        withEventClass: AEEventClass(kCoreEventClass), eventID: AEEventID(kAEReopenApplication),
        targetDescriptor: .currentProcess(), returnID: AEReturnID(kAutoGenerateReturnID),
        transactionID: AETransactionID(kAnyTransactionID))
    _ = try? event.sendEvent(options: [.noReply], timeout: 2)
}

private final class ClockPanel: NSPanel {
    override var canBecomeMain: Bool { false }
}

/// Takes the first click without activating, and lets the panel be dragged by its glass.
private final class ClockHost: NSHostingView<AnyView> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var mouseDownCanMoveWindow: Bool { true }
}

@MainActor
struct FloatingClockView: View {
    @Environment(PlannerStore.self) private var store
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let onOpen: () -> Void
    @State private var pulse = false

    var body: some View {
        // Once a second is all a ticking clock needs; a sweeping hand would
        // redraw all day on a panel that never goes away.
        TimelineView(.periodic(from: Date(timeIntervalSinceReferenceDate: Date().timeIntervalSinceReferenceDate.rounded(.down)), by: 1)) { tick in
            let time = WallTime(tick.date, zone: store.timeZone)
            let today = Civil.today(in: store.timeZone, now: tick.date)
            let focus = clockFocus(today: today, seconds: time.sinceMidnight) { store.days[$0]?.items ?? [] }
            panel(time: time, focus: focus)
                .onChange(of: focus?.running == true ? focus?.task.id : nil) { _, started in
                    if started != nil { celebrate() }
                }
        }
        .frame(width: FloatingClock.size.width, height: FloatingClock.size.height)
    }

    private func panel(time: WallTime, focus: ClockFocus?) -> some View {
        let color = focus.map { Palette.block($0.task) } ?? Palette.accent
        return HStack(spacing: 14) {
            ClockFace(time: time, color: color, progress: focus?.progress ?? 0, running: focus?.running == true)
                .frame(width: 100, height: 100)
                .scaleEffect(pulse ? 1.1 : 1)
                .allowsHitTesting(false)
            if let focus {
                words(focus, color: color)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("ALL CLEAR").font(.system(size: 10, weight: .heavy)).tracking(1.6).foregroundStyle(color)
                    Text("Nothing timed next").font(.system(size: 15, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(12)
        .frame(width: FloatingClock.size.width, height: FloatingClock.size.height)
        .background {
            ZStack {
                RoundedRectangle(cornerRadius: 30, style: .continuous).fill(.ultraThinMaterial)
                RoundedRectangle(cornerRadius: 30, style: .continuous)
                    .fill(LinearGradient(colors: [Color(hex: 0x1B1D29).opacity(0.93), Color(hex: 0x090A10).opacity(0.95)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                RoundedRectangle(cornerRadius: 30, style: .continuous)
                    .fill(RadialGradient(colors: [color.opacity(pulse ? 0.65 : 0.28), .clear],
                                         center: UnitPoint(x: 0.16, y: 0.5), startRadius: 10, endRadius: 190))
                RoundedRectangle(cornerRadius: 30, style: .continuous)
                    .strokeBorder(LinearGradient(colors: [.white.opacity(0.35), color.opacity(0.35), .white.opacity(0.06)],
                                                 startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1)
            }
            .allowsHitTesting(false)
        }
        .environment(\.colorScheme, .dark)
    }

    private func words(_ focus: ClockFocus, color: Color) -> some View {
        HStack(spacing: 4) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(focus.running ? "NOW" : "NEXT")
                        .font(.system(size: 10, weight: .heavy))
                        .tracking(1.6)
                        .foregroundStyle(color)
                    if focus.others > 0 {
                        Text("+\(focus.others)").font(.system(size: 10, weight: .bold)).foregroundStyle(.white.opacity(0.55))
                    }
                }
                Button(action: onOpen) {
                    Text(focus.task.title)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                .buttonStyle(.hitArea)
                .accessibilityHint("Shows Planner OS")
                Text(countdownText(focus.remaining))
                    .font(.system(size: 31, weight: .heavy, design: .rounded).monospacedDigit())
                    .foregroundStyle(LinearGradient(colors: [.white, color], startPoint: .top, endPoint: .bottom))
                    .contentTransition(.numericText(countsDown: true))
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                    .allowsHitTesting(false)
                Text(caption(focus))
                    .font(.system(size: 11, weight: .medium).monospacedDigit())
                    .foregroundStyle(.white.opacity(0.6))
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if focus.running {
                Button { Task { await store.setDone(focus.task) } } label: {
                    Image(systemName: "checkmark")
                        .font(.system(size: 14, weight: .heavy))
                        .foregroundStyle(.white)
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(color.opacity(0.35)))
                        .overlay(Circle().strokeBorder(color, lineWidth: 1.5))
                        .frame(width: 44, height: 44)
                }
                .buttonStyle(.hitArea)
                .accessibilityLabel("Complete \(focus.task.title) from the clock")
            }
        }
    }

    private func caption(_ focus: ClockFocus) -> String {
        let twentyFour = Civil.prefers24Hour
        let start = focus.task.clockMinutes
        return focus.running ? "left · ends \(fullClock(start + focus.task.minutes, twentyFour: twentyFour))"
            : "until it starts · \(fullClock(start, twentyFour: twentyFour))"
    }

    /// A task has just started: the face swells and the glow comes up, three times.
    private func celebrate() {
        guard !reduceMotion else { return }
        Task {
            for _ in 0..<3 {
                withAnimation(.easeOut(duration: 0.3)) { pulse = true }
                try? await Task.sleep(nanoseconds: 350_000_000)
                withAnimation(.easeInOut(duration: 0.4)) { pulse = false }
                try? await Task.sleep(nanoseconds: 450_000_000)
            }
        }
    }
}

/// The time of day in the planner's zone.
struct WallTime {
    var hour: Int
    var minute: Int
    var second: Int

    init(_ date: Date, zone: TimeZone) {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let parts = calendar.dateComponents([.hour, .minute, .second], from: date)
        hour = parts.hour ?? 0
        minute = parts.minute ?? 0
        second = parts.second ?? 0
    }

    var sinceMidnight: Int { hour * 3600 + minute * 60 + second }
}

/// An analogue face inside a ring that fills as the task, or the last hour
/// before it, runs out.
private struct ClockFace: View {
    let time: WallTime
    let color: Color
    let progress: Double
    let running: Bool

    var body: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.1), lineWidth: 6)
            Circle()
                .trim(from: 0, to: max(progress, 0.002))
                .stroke(AngularGradient(colors: [color.opacity(0.35), color, .white], center: .center,
                                        startAngle: .degrees(0), endAngle: .degrees(360 * max(progress, 0.01))),
                        style: StrokeStyle(lineWidth: 6, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .shadow(color: color.opacity(running ? 0.9 : 0.4), radius: 5)
            Canvas { context, size in
                let centre = CGPoint(x: size.width / 2, y: size.height / 2)
                let radius = min(size.width, size.height) / 2 - 8
                func at(_ turn: Double, _ length: Double) -> CGPoint {
                    CGPoint(x: Double(centre.x) + sin(turn * 2 * Double.pi) * length,
                            y: Double(centre.y) - cos(turn * 2 * Double.pi) * length)
                }
                let face = CGRect(x: centre.x - radius, y: centre.y - radius, width: radius * 2, height: radius * 2)
                context.fill(Path(ellipseIn: face),
                             with: .radialGradient(Gradient(colors: [Color(hex: 0x2C2F40), Color(hex: 0x0D0E15)]),
                                                   center: CGPoint(x: centre.x, y: centre.y - radius / 2),
                                                   startRadius: 0, endRadius: radius * 1.5))
                for mark in 0..<60 {
                    let long = mark % 5 == 0
                    var line = Path()
                    line.move(to: at(Double(mark) / 60, Double(radius) - (long ? 8 : 4.5)))
                    line.addLine(to: at(Double(mark) / 60, Double(radius) - 2.5))
                    context.stroke(line, with: .color(.white.opacity(long ? 0.85 : 0.22)),
                                   style: StrokeStyle(lineWidth: long ? 1.6 : 0.7, lineCap: .round))
                }
                func hand(_ turn: Double, _ length: Double, _ width: Double, _ ink: Color, tail: Double = 0) {
                    var line = Path()
                    line.move(to: at(turn, -tail))
                    line.addLine(to: at(turn, length))
                    context.stroke(line, with: .color(ink), style: StrokeStyle(lineWidth: width, lineCap: .round))
                }
                let minutes = Double(time.minute) + Double(time.second) / 60
                hand((Double(time.hour % 12) + minutes / 60) / 12, Double(radius) * 0.48, 4, .white)
                hand(minutes / 60, Double(radius) * 0.72, 2.6, .white.opacity(0.92))
                hand(Double(time.second) / 60, Double(radius) * 0.82, 1.2, color, tail: 8)
                context.fill(Path(ellipseIn: CGRect(x: centre.x - 3.5, y: centre.y - 3.5, width: 7, height: 7)), with: .color(color))
                context.fill(Path(ellipseIn: CGRect(x: centre.x - 1.4, y: centre.y - 1.4, width: 2.8, height: 2.8)), with: .color(.white))
            }
        }
        .accessibilityHidden(true)
    }
}
#endif
