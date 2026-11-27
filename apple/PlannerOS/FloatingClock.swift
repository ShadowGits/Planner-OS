#if os(macOS)
import AppKit
import SwiftUI

/// The clock that floats over everything on the Mac: the task under way with
/// its time running down, or that the time is vacant and for how long. What is
/// next is only ever the small line underneath.
///
/// A panel of its own rather than a SwiftUI scene, because it must stay above
/// other apps, follow you across Spaces and full screen, and take a click
/// without pulling Planner OS in front of what you are working on.
@MainActor
final class FloatingClock: NSObject {
    static let shared = FloatingClock()
    /// Where "show the clock" is kept; on until switched off.
    static let shownKey = "floating_clock"
    /// The small view: a slim pill. Off until chosen.
    static let smallKey = "floating_clock_small"
    private static let frameName = "FloatingClock"
    static let bigSize = CGSize(width: 356, height: 124)
    static let smallSize = CGSize(width: 268, height: 40)
    static func size(small: Bool) -> CGSize { small ? smallSize : bigSize }
    private var small: Bool { UserDefaults.standard.bool(forKey: Self.smallKey) }

    private var store: PlannerStore?
    private var panel: ClockPanel?

    /// Called whenever the main window appears or the connection changes.
    func attach(store: PlannerStore) {
        if self.store == nil {
            self.store = store
            NotificationCenter.default.addObserver(self, selector: #selector(defaultsChanged),
                                                   name: UserDefaults.didChangeNotification, object: nil)
            NotificationCenter.default.addObserver(self, selector: #selector(defaultsChanged),
                                                   name: NSApplication.didChangeScreenParametersNotification, object: nil)
            NotificationCenter.default.addObserver(self, selector: #selector(defaultsChanged),
                                                   name: NSApplication.didBecomeActiveNotification, object: nil)
            NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(defaultsChanged),
                                                              name: NSWorkspace.didWakeNotification, object: nil)
            // PlannerStore owns the single bounded network loop, even without a window.
        }
        update()
    }

    // Defaults can change on any thread.
    @objc private nonisolated func defaultsChanged() {
        Task { @MainActor in FloatingClock.shared.update() }
    }

    private var wanted: Bool {
        // It would sit on top of what the UI tests click.
        guard let store, store.connection != nil else { return false }
        if ConnectionStore.isUITesting {
            // Only the dedicated clock suite exposes the real panel.
            return ProcessInfo.processInfo.environment["PLANNER_UI_TEST_CLOCK"] == "1"
        }
        return UserDefaults.standard.object(forKey: Self.shownKey) as? Bool ?? true
    }

    func update() {
        guard wanted, let store else {
            panel?.orderOut(nil)
            return
        }
        let panel = self.panel ?? makePanel(store)
        self.panel = panel
        let size = Self.size(small: small)
        if panel.frame.size != size { panel.resize(to: size) }
        panel.ensureOnScreen()
        if !panel.isVisible { panel.orderFrontRegardless() }
    }

    private func makePanel(_ store: PlannerStore) -> ClockPanel {
        let size = Self.size(small: small)
        let panel = ClockPanel(contentRect: NSRect(origin: .zero, size: size),
                               styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Floating clock"
        panel.identifier = NSUserInterfaceItemIdentifier("floating-clock")
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isExcludedFromWindowsMenu = true
        panel.becomesKeyOnlyIfNeeded = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        // Every point of it takes the mouse, not only its buttons: a click that
        // fell through to the app behind is why it could be dragged by its tick alone.
        panel.ignoresMouseEvents = false
        panel.contentView = ClockHost(rootView: AnyView(FloatingClockView(onOpen: { [weak self] in self?.showMain() })
            .environment(store)))

        // Where it was left, unless that screen has since gone.
        let restored = panel.setFrameUsingName(Self.frameName)
        panel.setContentSize(size)
        if !restored || !NSScreen.screens.contains(where: { $0.visibleFrame.intersects(panel.frame) }),
           let screen = NSScreen.main?.visibleFrame {
            panel.setFrameOrigin(NSPoint(x: screen.maxX - size.width - 16, y: screen.maxY - size.height - 16))
        }
        // Saved on the drop rather than autosaved, which writes defaults on every step of a drag.
        panel.dropped = { $0.saveFrame(usingName: Self.frameName) }
        #if DEBUG
        if ConnectionStore.isUITesting,
           let raw = ProcessInfo.processInfo.environment["PLANNER_UI_TEST_CLOCK_FRAME"] {
            panel.setFrame(NSRectFromString(raw), display: false)
        }
        #endif
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

/// Moves itself when dragged from any point, the title and tick included.
/// `isMovableByWindowBackground` can't be relied on over a hosting view, so
/// the panel reads the mouse before SwiftUI does.
private final class ClockPanel: NSPanel {
    var dropped: ((NSWindow) -> Void)?
    private var press: (pointer: CGPoint, origin: NSPoint)?
    private var dragging = false
    /// Further than this is a drag; less is a click with an unsteady hand.
    private static let slop: CGFloat = 4

    override var canBecomeMain: Bool { false }

    /// Display rearrangements can strand a visible panel outside every screen.
    /// Recover on wake/activation as well as display changes; keep valid drops.
    func ensureOnScreen() {
        guard !NSScreen.screens.contains(where: { $0.visibleFrame.contains(frame) }) else { return }
        let before = frame
        settle()
        if frame != before { dropped?(self) }
    }

    /// Big to small and back about its top right corner, which is where it sits
    /// unless moved, and still wholly on screen.
    func resize(to size: CGSize) {
        setFrame(NSRect(x: frame.maxX - size.width, y: frame.maxY - size.height, width: size.width, height: size.height),
                 display: true)
        settle()
        dropped?(self)
    }

    override func sendEvent(_ event: NSEvent) {
        switch event.type {
        case .leftMouseDown:
            dragging = false
            press = event.cgEvent.map { ($0.location, frame.origin) }
        case .leftMouseDragged:
            guard let press, let pointer = event.cgEvent?.location else { break }
            // The screen's point, not the window's, which moves along with the drag.
            let dx = pointer.x - press.pointer.x
            let dy = pointer.y - press.pointer.y
            if !dragging {
                guard hypot(dx, dy) > Self.slop else { return }
                dragging = true
                releaseOutside(event)
            }
            setFrameOrigin(NSPoint(x: press.origin.x + dx, y: press.origin.y - dy))
            return
        case .leftMouseUp:
            press = nil
            guard dragging else { break }
            dragging = false
            settle()
            dropped?(self)
            return
        default: break
        }
        super.sendEvent(event)
    }

    /// Ends whatever the press began without clicking it: a drag from the tick must not tick.
    private func releaseOutside(_ event: NSEvent) {
        guard let up = NSEvent.mouseEvent(with: .leftMouseUp, location: NSPoint(x: -10_000, y: -10_000),
                                          modifierFlags: [], timestamp: event.timestamp, windowNumber: windowNumber,
                                          context: nil, eventNumber: event.eventNumber, clickCount: 1, pressure: 0)
        else { return }
        super.sendEvent(up)
    }

    /// Wholly on the screen it was mostly dropped on, clear of the menu bar and Dock.
    private func settle() {
        func shared(_ screen: NSScreen) -> CGFloat {
            let part = screen.frame.intersection(frame)
            return part.width * part.height
        }
        guard let area = NSScreen.screens.max(by: { shared($0) < shared($1) })?.visibleFrame else { return }
        setFrameOrigin(NSPoint(x: min(max(frame.minX, area.minX), area.maxX - frame.width),
                               y: min(max(frame.minY, area.minY), area.maxY - frame.height)))
    }
}

/// Takes the first click without activating, wherever on the clock it lands.
private final class ClockHost: NSHostingView<AnyView> {
    override func hitTest(_ point: NSPoint) -> NSView? {
        super.hitTest(point) ?? (frame.contains(point) ? self : nil)
    }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var mouseDownCanMoveWindow: Bool { false }
}

@MainActor
struct FloatingClockView: View {
    @Environment(PlannerStore.self) private var store
    @AppStorage(FloatingClock.smallKey) private var small = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let onOpen: () -> Void
    @State private var pulse = false
    private static let vacant = Color(hex: 0x7FD1C1)

    var body: some View {
        // Once a second is all a ticking clock needs; a sweeping hand would
        // redraw all day on a panel that never goes away.
        TimelineView(.periodic(from: Date(timeIntervalSinceReferenceDate: Date().timeIntervalSinceReferenceDate.rounded(.down)), by: 1)) { tick in
            let time = WallTime(tick.date, zone: store.timeZone)
            let today = Civil.today(in: store.timeZone, now: tick.date)
            let focus = clockFocus(today: today, seconds: time.sinceMidnight) { store.days[$0]?.items ?? [] }
            Group {
                if small { pill(focus) } else { panel(time: time, focus: focus) }
            }
                .onChange(of: focus?.running == true ? focus?.task.id : nil) { _, started in
                    if started != nil { celebrate() }
                }
        }
        .frame(width: FloatingClock.size(small: small).width, height: FloatingClock.size(small: small).height)
    }

    /// Switches between the full clock and the slim pill.
    private func sizeButton(_ symbol: String, _ label: String) -> some View {
        Button { small.toggle() } label: {
            Image(systemName: symbol)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(.white.opacity(0.7))
                .frame(width: 20, height: 20)
                .background(Circle().fill(.white.opacity(0.12)))
                .frame(width: 30, height: 30)
        }
        .buttonStyle(.hitArea)
        .accessibilityLabel(label)
        .help(label)
    }

    /// The small view: what is running or that the time is free, its countdown, and the tick.
    private func pill(_ focus: ClockFocus?) -> some View {
        let color = focus.flatMap { $0.running ? Palette.block($0.task) : nil } ?? Self.vacant
        return HStack(spacing: 7) {
            Circle().fill(color).frame(width: 9, height: 9)
                .shadow(color: color.opacity(0.9), radius: pulse ? 6 : 2)
                .padding(.leading, 6)
            if let focus {
                Text(countdownText(focus.remaining))
                    .font(.system(size: 15, weight: .heavy, design: .rounded).monospacedDigit())
                    .foregroundStyle(.white)
                    .contentTransition(.numericText(countsDown: true))
                    .fixedSize()
                Button(action: onOpen) {
                    Text(focus.running ? focus.task.title : "Free" + (focus.next.map { " · next \($0.title)" } ?? ""))
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.white.opacity(focus.running ? 0.9 : 0.6))
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.hitArea)
                .accessibilityHint("Shows Planner OS")
                if focus.running {
                    Button { Task { await store.setDone(focus.task) } } label: {
                        Image(systemName: "checkmark")
                            .font(.system(size: 10, weight: .heavy))
                            .foregroundStyle(.white)
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(color.opacity(0.35)))
                            .overlay(Circle().strokeBorder(color, lineWidth: 1.2))
                            .frame(width: 30, height: 30)
                    }
                    .buttonStyle(.hitArea)
                    .accessibilityLabel("Complete \(focus.task.title) from the clock")
                }
            } else {
                Text("Vacant").font(.system(size: 13, weight: .bold)).foregroundStyle(color)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            sizeButton("arrow.up.left.and.arrow.down.right", "Show the full clock")
        }
        .padding(.trailing, 4)
        .frame(width: FloatingClock.smallSize.width, height: FloatingClock.smallSize.height)
        .background {
            ZStack {
                Capsule().fill(.ultraThinMaterial)
                Capsule().fill(Color(hex: 0x10111A).opacity(0.94))
                Capsule().strokeBorder(color.opacity(0.45), lineWidth: 1)
            }
        }
        .environment(\.colorScheme, .dark)
    }

    private func panel(time: WallTime, focus: ClockFocus?) -> some View {
        // A task's colour is only for while it runs; vacant time is not the next one's.
        let color = focus.flatMap { $0.running ? Palette.block($0.task) : nil } ?? Self.vacant
        return HStack(spacing: 14) {
            ClockFace(time: time, color: color, progress: focus?.progress ?? 0, running: focus?.running == true)
                .frame(width: 100, height: 100)
                .scaleEffect(pulse ? 1.1 : 1)
            if let focus {
                words(focus, color: color)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("VACANT").font(.system(size: 10, weight: .heavy)).tracking(1.6).foregroundStyle(color)
                    Text("Nothing timed next").font(.system(size: 15, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(12)
        .frame(width: FloatingClock.bigSize.width, height: FloatingClock.bigSize.height)
        .overlay(alignment: .topTrailing) {
            sizeButton("arrow.down.right.and.arrow.up.left", "Make the clock small").padding(5)
        }
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
        }
        .environment(\.colorScheme, .dark)
    }

    private func words(_ focus: ClockFocus, color: Color) -> some View {
        HStack(spacing: 4) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(focus.running ? "NOW" : "VACANT")
                        .font(.system(size: 10, weight: .heavy))
                        .tracking(1.6)
                        .foregroundStyle(color)
                    if focus.running, focus.others > 0 {
                        Text("+\(focus.others)").font(.system(size: 10, weight: .bold)).foregroundStyle(.white.opacity(0.55))
                    }
                }
                Button(action: onOpen) {
                    Text(focus.running ? focus.task.title : "Free time")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                .buttonStyle(.hitArea)
                .accessibilityHint("Shows Planner OS")
                Text(countdownText(focus.remaining))
                    .font(.system(size: 28, weight: .heavy, design: .rounded).monospacedDigit())
                    .foregroundStyle(LinearGradient(colors: [.white, color], startPoint: .top, endPoint: .bottom))
                    .contentTransition(.numericText(countsDown: true))
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(caption(focus))
                    .font(.system(size: 11, weight: .medium).monospacedDigit())
                    .foregroundStyle(.white.opacity(0.6))
                    .lineLimit(1)
                if let next = focus.next {
                    Button(action: onOpen) {
                        Text(nextLine(next, focus))
                            .font(.system(size: 10, weight: .medium).monospacedDigit())
                            .foregroundStyle(.white.opacity(0.5))
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    .buttonStyle(.hitArea)
                    .accessibilityHint("Shows Planner OS")
                }
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
            : "free until \(focus.nextIsTomorrow ? "tomorrow " : "")\(fullClock(start, twentyFour: twentyFour))"
    }

    /// "Next 10:00 PM: Reading", the time first so a long name cuts short, not it. In vacant time the line above has the time already.
    private func nextLine(_ next: PlannerTask, _ focus: ClockFocus) -> String {
        if !focus.running {
            return "Next: \(next.title)" + (focus.others > 0 ? " +\(focus.others)" : "")
        }
        let day = focus.nextIsTomorrow ? "tomorrow " : ""
        return "Next \(day)\(fullClock(next.clockMinutes, twentyFour: Civil.prefers24Hour)): \(next.title)"
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
            // Dashed while nothing fills it.
            Circle().stroke(.white.opacity(running ? 0.1 : 0.22),
                            style: StrokeStyle(lineWidth: 6, dash: running ? [] : [3, 4]))
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
