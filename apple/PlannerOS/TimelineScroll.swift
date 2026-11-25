import SwiftUI
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// Somewhere the timeline has been asked to go.
struct ScrollRequest: Equatable {
    enum Place: Equatable {
        /// A day's header at the top of the screen.
        case day(String)
        /// A clock time a third of the way down, where the date tile reads from.
        case clock(date: String, minute: Int)
        /// A day's untimed list, a third of the way down.
        case untimed(String)
    }

    let id = UUID()
    var place: Place
    var animated = false
}

/// What the timeline does with a finger, a mouse or a scroll. Points are in the
/// scroll's content; `window` points are the window's, as SwiftUI's global space is.
struct TimelineInput {
    var hit: (CGPoint) -> TimelineHit? = { _ in nil }
    /// The task a sideways swipe from here would pull, which can start on its tick or star.
    var swipeable: (CGPoint) -> TimelineHit? = { _ in nil }
    /// The task whose swipe buttons are out, if any.
    var swiped: () -> String? = { nil }
    /// A press somewhere, before anything is made of it.
    var pressed: (CGPoint) -> Void = { _ in }
    var open: (TimelineHit) -> Void = { _ in }
    var swipe: (TimelineHit, _ dx: Double) -> Void = { _, _ in }
    var swipeEnded: (TimelineHit, _ dx: Double, _ velocity: Double) -> Void = { _, _, _ in }
    var lift: (TimelineHit) -> Void = { _ in }
    var drag: (TimelineHit, _ top: Double, _ window: CGPoint) -> Void = { _, _, _ in }
    var drop: (TimelineHit, _ top: Double, _ window: CGPoint) -> Void = { _, _, _ in }
    var cancelDrag: () -> Void = {}
    /// A hold let go without moving: `seconds` from the finger landing.
    var heldStill: (TimelineHit, _ seconds: Double) -> Void = { _, _ in }
    /// The iPhone's status bar was tapped.
    var toTop: () -> Void = {}
    var viewed: (_ top: Double, _ height: Double) -> Void = { _, _ in }
    /// Below this height in the window is the bottom bar, which keeps its own clicks.
    var barTop: () -> Double = { .infinity }
}

/// Where the scroll is and where it should be, worked out the same for both platforms.
///
/// SwiftUI's lazy stacks only guess the height of what they have not drawn, so
/// "open at now", two weeks down, lands somewhere else, and a day above the
/// screen gaining a task shoves everything along. The timeline knows every
/// height exactly, so it sets the platform's own scroll view by arithmetic.
@MainActor
final class ScrollKeeper {
    var input = TimelineInput()
    private(set) var layout = TimelineLayout()
    private var handled: UUID?
    private var pending: (y: Double, animated: Bool)?
    private var lastReport: (top: Double, height: Double)?
    /// The last request met, and the height of screen it was worked out for.
    private var placed: (place: ScrollRequest.Place, y: Double, viewport: Double)?

    /// Takes a new layout and request, keeping what is in view where it was.
    func update(layout next: TimelineLayout, request: ScrollRequest?, top: Double?, viewport: Double) {
        let old = layout
        layout = next
        if let request, request.id != handled {
            guard viewport > 0 else { return }
            if let y = target(request.place, viewport: viewport) {
                handled = request.id
                pending = (y, request.animated)
                placed = (request.place, y, viewport)
                return
            }
        }
        // The first height is not the last: the bars are still settling. Until it is
        // scrolled, what was asked for stays at the third of the screen the tile reads.
        if let was = placed, viewport > 0, abs(was.viewport - viewport) > 0.5,
           pending != nil || top.map({ abs($0 - was.y) < 1.5 }) == true,
           let y = target(was.place, viewport: viewport) {
            placed = (was.place, y, viewport)
            pending = (y, false)
            return
        }
        guard pending == nil, let top, viewport > 0, !old.days.isEmpty,
              old.days.map(\.gridTop) != next.days.map(\.gridTop) || old.days.map(\.date) != next.days.map(\.date)
        else { return }
        let probe = top + viewport / 3
        guard let spot = old.spot(at: probe), let moved = next.y(of: spot), abs(moved - probe) > 0.5 else { return }
        pending = (max(moved - viewport / 3, 0), false)
    }

    private func target(_ place: ScrollRequest.Place, viewport: Double) -> Double? {
        let y: Double?
        switch place {
        case .day(let date):
            y = layout.day(date)?.top
        case .clock(let date, let minute):
            y = layout.y(of: .clock(date: date, minute: Double(minute))).map { $0 - viewport / 3 }
        case .untimed(let date):
            y = layout.day(date).map { $0.untimedTop - viewport / 3 }
        }
        return y.map { min(max($0, 0), max(layout.height - viewport, 0)) }
    }

    /// Where to scroll to now, once the content is tall enough to get there.
    func take(contentHeight: Double) -> (y: Double, animated: Bool)? {
        guard let next = pending, contentHeight >= layout.height - 1 else { return nil }
        pending = nil
        return next
    }

    func report(top: Double, height: Double) {
        guard handled != nil, pending == nil, height > 0, lastReport?.top != top || lastReport?.height != height else { return }
        lastReport = (top, height)
        let viewed = input.viewed
        // Scrolling can happen inside a view update, where state may not change.
        DispatchQueue.main.async { viewed(top, height) }
    }

    /// Points a second to scroll while a held task is near the top or bottom edge. The
    /// bottom edge is the bar's top where the list runs on behind the bar.
    /// `y` is the pointer in the content and `windowY` the same one in the window.
    func edgeSpeed(_ y: Double, windowY: Double, top: Double, height: Double) -> Double {
        let zone = 56.0
        let bottom = min(top + height, y + input.barTop() - windowY)
        // Gentle as the finger enters the zone, full speed at the edge itself.
        let fastest = 720.0
        if y < top + zone {
            let depth = min((top + zone - y) / zone, 1)
            return -depth * depth * fastest
        }
        if y > bottom - zone {
            let depth = min((y - (bottom - zone)) / zone, 1)
            return depth * depth * fastest
        }
        return 0
    }
}

#if os(iOS)

struct TimelineScroll: UIViewRepresentable {
    let layout: TimelineLayout
    let request: ScrollRequest?
    let input: TimelineInput

    func makeUIView(context: Context) -> TimelineTracker { TimelineTracker() }

    func updateUIView(_ view: TimelineTracker, context: Context) {
        view.apply(layout: layout, request: request, input: input)
    }

    static func dismantleUIView(_ view: TimelineTracker, coordinator: ()) { view.detach() }
}

/// Sits behind the timeline's content and puts two gestures on its scroll view:
/// a sideways pan that only starts on a task, and a hold that picks one up.
/// SwiftUI's own drag gestures on a task stop the list scrolling under it.
final class TimelineTracker: UIView, UIGestureRecognizerDelegate {
    private let keeper = ScrollKeeper()
    private weak var scroll: UIScrollView?
    private var watching: [NSKeyValueObservation] = []
    private lazy var pan = UIPanGestureRecognizer(target: self, action: #selector(panned(_:)))
    private lazy var hold = UILongPressGestureRecognizer(target: self, action: #selector(held(_:)))
    private var pressed: (point: CGPoint, hit: TimelineHit?, swipeable: TimelineHit?, at: TimeInterval)?
    private var swiping: TimelineHit?
    private var held: (hit: TimelineHit, grab: Double, start: CGPoint, moved: Bool)?
    private var finger = CGPoint.zero
    private var edgeLink: CADisplayLink?
    private var lastCreep: CFTimeInterval?
    private var lastRequest: ScrollRequest?
    private let catcher = TopTapCatcher()

    override init(frame: CGRect) {
        super.init(frame: frame)
        isUserInteractionEnabled = false
        backgroundColor = .clear
        pan.maximumNumberOfTouches = 1
        pan.delegate = self
        // Quick, as the system's own drag and drop was. A press let go sooner than
        // half a second without moving still opens the task, as a tap does.
        hold.minimumPressDuration = 0.25
        hold.allowableMovement = 10
        hold.delegate = self
    }

    required init?(coder: NSCoder) { fatalError("not from a nib") }

    func apply(layout: TimelineLayout, request: ScrollRequest?, input: TimelineInput) {
        keeper.input = input
        lastRequest = request
        keeper.update(layout: layout, request: request, top: visibleTop, viewport: viewport)
        settle()
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        guard window != nil else { return }
        attach()
        setNeedsLayout()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        attach()
        keeper.update(layout: keeper.layout, request: lastRequest, top: visibleTop, viewport: viewport)
        settle()
        report()
    }

    private func attach() {
        guard scroll == nil else { return }
        var parent = superview
        while let view = parent, !(view is UIScrollView) { parent = view.superview }
        guard let found = parent as? UIScrollView else { return }
        scroll = found
        // Its own top is two weeks back, so a tap on the clock is caught and goes to the top of the day in view.
        found.scrollsToTop = false
        catcher.action = { [weak self] in self?.keeper.input.toTop() }
        if let host = found.superview {
            // The whole width: iOS looks straight down from where the bar was tapped.
            catcher.frame = CGRect(x: 0, y: found.frame.minY, width: host.bounds.width, height: 10)
            host.insertSubview(catcher, belowSubview: found)
        }
        found.addGestureRecognizer(pan)
        found.addGestureRecognizer(hold)
        watching = [
            found.observe(\.contentOffset) { [weak self] _, _ in MainActor.assumeIsolated { self?.report() } },
            found.observe(\.bounds, options: [.old, .new]) { [weak self] _, change in
                // The first real height is what a request was waiting for. The
                // origin is the scrolling itself, which needs no layout.
                guard change.oldValue?.size != change.newValue?.size else { return }
                MainActor.assumeIsolated { self?.setNeedsLayout() }
            },
        ]
    }

    func detach() {
        stopEdge()
        if held != nil { keeper.input.cancelDrag() }
        held = nil
        watching = []
        scroll?.removeGestureRecognizer(pan)
        scroll?.removeGestureRecognizer(hold)
        catcher.removeFromSuperview()
        scroll = nil
    }

    private var viewport: Double {
        guard let scroll else { return 0 }
        return max(Double(scroll.bounds.height - scroll.adjustedContentInset.top - scroll.adjustedContentInset.bottom), 0)
    }

    private var visibleTop: Double? {
        guard let scroll else { return nil }
        let origin = Double(convert(CGPoint.zero, to: scroll).y)
        return Double(scroll.contentOffset.y + scroll.adjustedContentInset.top) - origin
    }

    private func settle() {
        guard let scroll, let next = keeper.take(contentHeight: Double(bounds.height)) else { return }
        let origin = Double(convert(CGPoint.zero, to: scroll).y)
        let offset = CGPoint(x: scroll.contentOffset.x, y: next.y + origin - Double(scroll.adjustedContentInset.top))
        let near = abs(Double(scroll.contentOffset.y) - Double(offset.y)) < viewport * 4
        scroll.setContentOffset(offset, animated: next.animated && near && !UIAccessibility.isReduceMotionEnabled)
    }

    private func report() {
        guard let top = visibleTop else { return }
        keeper.report(top: top, height: viewport)
    }

    // MARK: Gestures

    func gestureRecognizer(_ recognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        let point = touch.location(in: self)
        guard recognizer === pan else { return keeper.input.hit(point) != nil }
        let swipeable = keeper.input.swipeable(point)
        pressed = (point, keeper.input.hit(point), swipeable, touch.timestamp)
        keeper.input.pressed(point)
        return swipeable != nil
    }

    override func gestureRecognizerShouldBegin(_ recognizer: UIGestureRecognizer) -> Bool {
        guard recognizer === pan else { return pressed?.hit != nil }
        guard let hit = pressed?.swipeable else { return false }
        let speed = pan.velocity(in: self)
        guard abs(speed.x) > abs(speed.y) else { return false }
        return speed.x < 0 || keeper.input.swiped() == hit.task.id
    }

    func gestureRecognizer(_ recognizer: UIGestureRecognizer,
                           shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
        // Never with the list's own scrolling or with each other.
        !(other === scroll?.panGestureRecognizer || other === pan || other === hold)
    }

    func gestureRecognizer(_ recognizer: UIGestureRecognizer,
                           shouldBeRequiredToFailBy other: UIGestureRecognizer) -> Bool {
        // The list waits only long enough to see the finger is not going sideways.
        recognizer === pan && other === scroll?.panGestureRecognizer
    }

    @objc private func panned(_ recognizer: UIPanGestureRecognizer) {
        let dx = Double(recognizer.translation(in: self).x)
        switch recognizer.state {
        case .began:
            swiping = pressed?.swipeable
            if let swiping { keeper.input.swipe(swiping, dx) }
        case .changed:
            if let swiping { keeper.input.swipe(swiping, dx) }
        case .ended, .cancelled, .failed:
            if let swiping { keeper.input.swipeEnded(swiping, dx, Double(recognizer.velocity(in: self).x)) }
            swiping = nil
        default:
            break
        }
    }

    @objc private func held(_ recognizer: UILongPressGestureRecognizer) {
        let point = recognizer.location(in: self)
        finger = recognizer.location(in: nil)
        switch recognizer.state {
        case .began:
            guard let start = pressed, let hit = start.hit else { return }
            held = (hit, Double(start.point.y - hit.frame.minY), finger, false)
            scroll?.panGestureRecognizer.isEnabled = false
            keeper.input.lift(hit)
            startEdge()
        case .changed:
            guard var now = held else { return }
            if !now.moved, hypot(finger.x - now.start.x, finger.y - now.start.y) < 6 { return }
            now.moved = true
            held = now
            keeper.input.drag(now.hit, Double(point.y) - now.grab, finger)
        case .ended:
            if let now = held, now.moved { keeper.input.drop(now.hit, Double(point.y) - now.grab, finger) }
            else {
                keeper.input.cancelDrag()
                if let still = held?.hit {
                    keeper.input.heldStill(still, ProcessInfo.processInfo.systemUptime - (pressed?.at ?? 0))
                }
            }
            letGo()
        case .cancelled, .failed:
            if held != nil { keeper.input.cancelDrag() }
            letGo()
        default:
            break
        }
    }

    private func letGo() {
        held = nil
        stopEdge()
        scroll?.panGestureRecognizer.isEnabled = true
    }

    private func startEdge() {
        stopEdge()
        // In step with the screen, and by the time that has passed, so the speed
        // holds steady at 60 or 120 Hz and through a late frame.
        let link = CADisplayLink(target: self, selector: #selector(creep(_:)))
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 120, preferred: 120)
        link.add(to: .main, forMode: .common)
        edgeLink = link
    }

    private func stopEdge() {
        // The link holds on to this view until it is invalidated.
        edgeLink?.invalidate()
        edgeLink = nil
        lastCreep = nil
    }

    @objc private func creep(_ link: CADisplayLink) {
        let passed = min(link.targetTimestamp - (lastCreep ?? link.timestamp), 0.05)
        lastCreep = link.targetTimestamp
        guard let held, held.moved, let scroll, let top = visibleTop else { return }
        let point = convert(finger, from: nil)
        // Over the bottom bar the finger is on its way to the bin.
        guard Double(finger.y) < keeper.input.barTop() else { return }
        let step = keeper.edgeSpeed(Double(point.y), windowY: Double(finger.y), top: top, height: viewport) * passed
        guard step != 0 else { return }
        let next = min(max(top + step, 0), max(keeper.layout.height - viewport, 0))
        guard next != top else { return }
        scroll.contentOffset.y += next - top
        keeper.input.drag(held.hit, Double(convert(finger, from: nil).y) - held.grab, finger)
    }
}

/// Never seen or touched: the one scroll view iOS offers a status bar tap to.
private final class TopTapCatcher: UIScrollView, UIScrollViewDelegate {
    var action: () -> Void = {}

    init() {
        super.init(frame: .zero)
        autoresizingMask = .flexibleWidth
        contentSize = CGSize(width: 10, height: 100)
        contentOffset = CGPoint(x: 0, y: 50)
        contentInsetAdjustmentBehavior = .never
        backgroundColor = .clear
        isAccessibilityElement = false
        accessibilityElementsHidden = true
        delegate = self
    }

    required init?(coder: NSCoder) { fatalError("not from a nib") }

    func scrollViewShouldScrollToTop(_ scrollView: UIScrollView) -> Bool {
        action()
        return false
    }
}

#else

struct TimelineScroll: NSViewRepresentable {
    let layout: TimelineLayout
    let request: ScrollRequest?
    let input: TimelineInput

    func makeNSView(context: Context) -> TimelineTracker { TimelineTracker() }

    func updateNSView(_ view: TimelineTracker, context: Context) {
        view.apply(layout: layout, request: request, input: input)
    }

    static func dismantleNSView(_ view: TimelineTracker, coordinator: ()) { view.detach() }
}

/// Sits behind the timeline's content and reads the mouse on task bodies: a
/// click opens, a pull to the left swipes, a hold or a pull up or down moves.
/// A tap gesture and a drag on one SwiftUI view fight over the Mac's mouse, so
/// one place decides. Ticks, stars and buttons are never taken from SwiftUI.
final class TimelineTracker: NSView {
    private enum Mode { case pressed, swiping, moving }

    private let keeper = ScrollKeeper()
    private weak var scroll: NSScrollView?
    private var monitor: Any?
    private var watching: [NSObjectProtocol] = []
    private var press: (hit: TimelineHit, start: NSPoint, grab: Double, at: TimeInterval, moved: Bool, mode: Mode)?
    private var holdTimer: Timer?
    private var edgeTimer: Timer?
    private var lastCreep: TimeInterval?
    private var mouse = NSPoint.zero
    private var wheel: (hit: TimelineHit, dx: Double)?
    private var wheelUndecided = false
    private var eatMomentum = false
    private var lastRequest: ScrollRequest?

    override var isFlipped: Bool { true }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }

    func apply(layout: TimelineLayout, request: ScrollRequest?, input: TimelineInput) {
        keeper.input = input
        lastRequest = request
        keeper.update(layout: layout, request: request, top: visibleTop, viewport: viewport)
        settle()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window == nil { detach() } else { attach(); needsLayout = true }
    }

    override func layout() {
        super.layout()
        attach()
        refit()
    }

    override func setFrameSize(_ size: NSSize) {
        super.setFrameSize(size)
        needsLayout = true
    }

    private func refit() {
        keeper.update(layout: keeper.layout, request: lastRequest, top: visibleTop, viewport: viewport)
        settle()
        report()
    }

    private func attach() {
        guard scroll == nil, window != nil, let found = enclosingScrollView else { return }
        scroll = found
        let clip = found.contentView
        clip.postsBoundsChangedNotifications = true
        clip.postsFrameChangedNotifications = true
        let centre = NotificationCenter.default
        watching = [
            centre.addObserver(forName: NSView.boundsDidChangeNotification, object: clip, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.report() }
            },
            centre.addObserver(forName: NSView.frameDidChangeNotification, object: clip, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.needsLayout = true }
            },
        ]
        monitor = NSEvent.addLocalMonitorForEvents(
            matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp, .scrollWheel]
        ) { [weak self] event in
            guard let self else { return event }
            return MainActor.assumeIsolated { self.take(event) } ? nil : event
        }
    }

    func detach() {
        if press?.mode == .moving { keeper.input.cancelDrag() }
        endPress()
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        watching.forEach(NotificationCenter.default.removeObserver)
        watching = []
        scroll = nil
    }

    private var viewport: Double {
        guard let scroll else { return 0 }
        let clip = scroll.contentView
        return max(Double(clip.bounds.height - clip.contentInsets.top - clip.contentInsets.bottom), 0)
    }

    private var visibleTop: Double? {
        guard let clip = scroll?.contentView else { return nil }
        let origin = Double(convert(NSPoint.zero, to: clip).y)
        return Double(clip.bounds.origin.y + clip.contentInsets.top) - origin
    }

    private func settle() {
        guard let scroll, let next = keeper.take(contentHeight: Double(bounds.height)) else { return }
        let clip = scroll.contentView
        let origin = Double(convert(NSPoint.zero, to: clip).y)
        let target = NSPoint(x: clip.bounds.origin.x, y: next.y + origin - Double(clip.contentInsets.top))
        let near = abs(Double(clip.bounds.origin.y - target.y)) < viewport * 4
        if next.animated, near, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.3
                clip.animator().setBoundsOrigin(target)
            }
        } else {
            clip.scroll(to: target)
        }
        scroll.reflectScrolledClipView(clip)
    }

    private func report() {
        guard let top = visibleTop else { return }
        keeper.report(top: top, height: viewport)
    }

    // MARK: Mouse

    /// The window's point as SwiftUI's global space has it: from the top left.
    private func inWindow(_ point: NSPoint) -> CGPoint {
        guard let content = window?.contentView else { return point }
        let local = content.convert(point, from: nil)
        return content.isFlipped ? local : CGPoint(x: local.x, y: content.bounds.height - local.y)
    }

    /// True when the timeline has dealt with the event itself.
    private func take(_ event: NSEvent) -> Bool {
        guard let window, event.window === window, window.attachedSheet == nil else { return false }
        switch event.type {
        case .leftMouseDown: return down(event, window)
        case .leftMouseDragged: return dragged(event)
        case .leftMouseUp: return up(event)
        case .scrollWheel: return scrolled(event)
        default: return false
        }
    }

    /// A point of the content, when the event is on the part of it in view.
    private func onTimeline(_ event: NSEvent) -> CGPoint? {
        guard let clip = scroll?.contentView, clip.bounds.contains(clip.convert(event.locationInWindow, from: nil)),
              Double(inWindow(event.locationInWindow).y) < keeper.input.barTop() else { return nil }
        return convert(event.locationInWindow, from: nil)
    }

    private func down(_ event: NSEvent, _ window: NSWindow) -> Bool {
        endPress()
        guard let point = onTimeline(event) else { return false }
        keeper.input.pressed(point)
        guard !event.modifierFlags.contains(.control), let hit = keeper.input.hit(point) else { return false }
        if !window.isKeyWindow {
            // The click is not passed on, so it cannot bring the window forward itself.
            NSApp.activate()
            window.makeKeyAndOrderFront(nil)
        }
        mouse = event.locationInWindow
        press = (hit, mouse, Double(point.y - hit.frame.minY), event.timestamp, false, .pressed)
        let timer = Timer(timeInterval: 0.4, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.startMove() }
        }
        RunLoop.main.add(timer, forMode: .common)
        holdTimer = timer
        return true
    }

    private func startMove() {
        guard var now = press, now.mode == .pressed else { return }
        now.mode = .moving
        press = now
        holdTimer?.invalidate()
        holdTimer = nil
        keeper.input.lift(now.hit)
        let timer = Timer(timeInterval: 1.0 / 120, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.creep() }
        }
        RunLoop.main.add(timer, forMode: .common)
        edgeTimer = timer
    }

    private func dragged(_ event: NSEvent) -> Bool {
        guard var now = press else { return false }
        mouse = event.locationInWindow
        let dx = Double(mouse.x - now.start.x), dy = Double(mouse.y - now.start.y)
        if !now.moved, hypot(dx, dy) < 6 { return true }
        now.moved = true
        press = now
        if now.mode == .pressed {
            let opened = keeper.input.swiped() == now.hit.task.id
            if abs(dx) > abs(dy), dx < 0 || opened {
                holdTimer?.invalidate()
                holdTimer = nil
                press?.mode = .swiping
            } else {
                startMove()
            }
        }
        guard let current = press else { return true }
        if current.mode == .swiping {
            keeper.input.swipe(current.hit, dx)
        } else {
            keeper.input.drag(current.hit, Double(convert(mouse, from: nil).y) - current.grab, inWindow(mouse))
        }
        return true
    }

    private func up(_ event: NSEvent) -> Bool {
        guard let now = press else { return false }
        endPress()
        let dx = Double(event.locationInWindow.x - now.start.x)
        switch now.mode {
        case .pressed:
            keeper.input.open(now.hit)
        case .swiping:
            keeper.input.swipeEnded(now.hit, dx, dx / max(event.timestamp - now.at, 0.05))
        case .moving:
            guard now.moved else { keeper.input.cancelDrag(); break }
            keeper.input.drop(now.hit, Double(convert(event.locationInWindow, from: nil).y) - now.grab,
                              inWindow(event.locationInWindow))
        }
        return true
    }

    private func endPress() {
        holdTimer?.invalidate()
        edgeTimer?.invalidate()
        holdTimer = nil
        edgeTimer = nil
        lastCreep = nil
        press = nil
    }

    private func creep() {
        let clock = ProcessInfo.processInfo.systemUptime
        let passed = min(clock - (lastCreep ?? clock), 0.05)
        lastCreep = clock
        guard let now = press, now.mode == .moving, now.moved, let scroll, let top = visibleTop,
              Double(inWindow(mouse).y) < keeper.input.barTop() else { return }
        let step = keeper.edgeSpeed(Double(convert(mouse, from: nil).y), windowY: Double(inWindow(mouse).y),
                                    top: top, height: viewport) * passed
        guard step != 0 else { return }
        let next = min(max(top + step, 0), max(keeper.layout.height - viewport, 0))
        guard next != top else { return }
        let clip = scroll.contentView
        clip.scroll(to: NSPoint(x: clip.bounds.origin.x, y: clip.bounds.origin.y + next - top))
        scroll.reflectScrolledClipView(clip)
        keeper.input.drag(now.hit, Double(convert(mouse, from: nil).y) - now.grab, inWindow(mouse))
    }

    /// Two fingers sideways on a trackpad swipe a task, as they do in Mail.
    private func scrolled(_ event: NSEvent) -> Bool {
        guard event.hasPreciseScrollingDeltas else { return false }
        if !event.momentumPhase.isEmpty { return eatMomentum }
        if event.phase == .mayBegin || event.phase == .began {
            wheel = nil
            eatMomentum = false
            wheelUndecided = true
        }
        let sideways = Double(event.scrollingDeltaX) * (event.isDirectionInvertedFromDevice ? 1 : -1)
        let along = Double(event.scrollingDeltaY)
        if wheelUndecided, sideways != 0 || along != 0 {
            wheelUndecided = false
            if abs(sideways) > abs(along), let point = onTimeline(event), let hit = keeper.input.swipeable(point),
               sideways < 0 || keeper.input.swiped() == hit.task.id {
                wheel = (hit, 0)
            }
        }
        guard var current = wheel else { return false }
        if event.phase == .ended || event.phase == .cancelled {
            keeper.input.swipeEnded(current.hit, current.dx, 0)
            wheel = nil
            eatMomentum = true
        } else {
            current.dx += sideways
            wheel = current
            keeper.input.swipe(current.hit, current.dx)
        }
        return true
    }
}

#endif
