import SwiftUI

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
    #else
    static let header = Color(nsColor: .windowBackgroundColor)
    static let card = Color(nsColor: .textBackgroundColor)
    #endif
    static let accent = Color(hex: 0xF19E98)
    /// Coral, orange, amber, green, blue, dark green, wine, navy.
    static let blocks: [Color] = [0xF19E98, 0xF19C74, 0xEAA93B, 0x91BE6C, 0x6085A8, 0x3A8564, 0x974667, 0x2B5073].map { Color(hex: $0) }

    static func block(_ task: PlannerTask) -> Color { blocks[paletteIndex(task, count: blocks.count)] }
}

/// What the gestures need to remember between a press and the button under it.
/// Not state: changing it draws nothing.
@MainActor
private final class PressMemory {
    /// A swipe or a hold ends with a finger lifting off the task's button; that is not a tap on it.
    var quietUntil = Date.distantPast
    /// This press put the swipe buttons away, which is all it does.
    var closedSwipe = false
}

private struct DragState: Equatable {
    var hit: TimelineHit
    /// Where it would land: nil over the bin, and for an untimed task among the untimed.
    var date: String?
    var start = 0
}

/// A finger's state, apart from the timeline's own. It changes on every frame
/// of a drag or a swipe, and only the little views that show it read it while
/// drawing. Were it the timeline's @State, each frame would lay out all 75 days
/// and redraw every task on screen, which is how a drag comes to stutter.
@MainActor
@Observable
private final class TimelineSession {
    var swipe: SwipeState?
    private(set) var drag: DragState?
    /// The task hidden while its outline moves. Set once, not per frame.
    private(set) var hiddenID: String?
    /// Goes up on lifting and at each five minutes or date it is moved to, for the haptic.
    private(set) var bumps = 0

    func setDrag(_ next: DragState?) {
        guard next != drag else { return }
        if let next, drag == nil || (next.date != nil && (next.date != drag?.date || next.start != drag?.start)) { bumps += 1 }
        drag = next
        let hidden = next?.date != nil ? next?.hit.task.id : nil
        if hidden != hiddenID { hiddenID = hidden }
    }
}

/// The last layout, kept until a day's tasks or the range of dates changes.
@MainActor
private final class LayoutMemo {
    private var range: (today: String, picked: String?)?
    private var dates: [String] = []
    private var items: [[PlannerTask]] = []
    private var layout = TimelineLayout()

    func layout(today: String, picked: String?, tasks: (String) -> [PlannerTask]) -> TimelineLayout {
        var changed = false
        if range?.today != today || range?.picked != picked {
            range = (today, picked)
            dates = timelineDates(today: today, reaching: picked)
            changed = true
        }
        let now = dates.map(tasks)
        if changed || now != items {
            items = now
            let byDate = Dictionary(uniqueKeysWithValues: zip(dates, now))
            layout = TimelineLayout(dates: dates) { byDate[$0] ?? [] }
        }
        return layout
    }
}

/// The timeline: one scroll from two weeks back to sixty days ahead, opening at
/// now. Days are midnight to midnight under a thick header, every hour the same
/// height, and the tile on top says which day is in view. Swipe a task left for
/// Next day, Archive and Delete; hold one to move it, across midnight too.
@MainActor
struct TodayView: View {
    @Environment(PlannerStore.self) private var store
    @Binding var editor: EditorRequest?
    @Binding var overBin: Bool
    var opening: UUID
    /// The day as a plain list instead of the timeline; remembered between launches.
    @AppStorage("day_list") private var listView = false
    #if os(macOS)
    @AppStorage(FloatingClock.shownKey) private var showClock = true
    @AppStorage(FloatingClock.smallKey) private var smallClock = false
    #endif
    @State private var pickingDate = false
    /// A picked day, which the scroll stretches to reach.
    @State private var picked: String?
    @State private var request: ScrollRequest?
    /// The dates drawn: those on screen and a little either side.
    @State private var drawn: [String] = []
    @State private var session = TimelineSession()
    @State private var memo = LayoutMemo()
    @State private var memory = PressMemory()
    /// An untimed task held and let go, for its Mark done and Edit.
    @State private var menuTask: PlannerTask?
    /// A Top Win tapped in the list.
    @State private var reveal: String?
    @State private var refreshing = false

    var body: some View {
        let today = store.calendarToday
        let layout = memo.layout(today: today, picked: picked) { store.days[$0]?.items ?? [] }
        VStack(spacing: 0) {
            top(today: today)
            if listView { list } else { timeline(layout, today: today) }
        }
        .background(Palette.header)
        .hiddenNavigationBar()
        .sheet(isPresented: $pickingDate) {
            DayPickerSheet(day: store.selectedDate, timeZone: store.timeZone, onPick: go(to:))
        }
        .onAppear {
            picked = store.selectedDate
            if store.selectedDate == today { openAtNow(today) } else { go(to: store.selectedDate) }
        }
        .onChange(of: opening) {
            endDrag()
            session.swipe = nil
            picked = store.calendarToday
            store.selectedDate = store.calendarToday
            openAtNow(store.calendarToday)
        }
        .alert(menuTask?.title ?? "", isPresented: Binding(get: { menuTask != nil }, set: { if !$0 { menuTask = nil } }),
               presenting: menuTask) { task in
            Button(task.done ? "Reopen" : "Mark done") { Task { await store.setDone(task, !task.done) } }
            Button("Edit") { editor = EditorRequest(task: task) }
            Button("Cancel", role: .cancel) {}
        }
        .onDisappear {
            if session.drag != nil { endDrag() }
        }
        .onChange(of: listView) { _, list in
            endDrag()
            session.swipe = nil
            guard !list else { return }
            if store.selectedDate == today { openAtNow(today) } else { go(to: store.selectedDate) }
        }
    }

    // MARK: The scroll

    private func timeline(_ layout: TimelineLayout, today: String) -> some View {
        GeometryReader { space in
            let width = min(max(Double(space.size.width), 1), 760)
            ScrollView {
                content(layout, today: today, width: width)
                    .background(TimelineScroll(layout: layout, request: request, input: input(layout, width: width)))
                    .frame(maxWidth: .infinity)
                    // The list runs on behind the bottom bar; the last evening has to clear it.
                    .padding(.bottom, 120)
            }
            .scrollIndicators(.never)
            .refreshable { await store.refreshAll() }
            .accessibilityIdentifier("timeline")
            .background(Palette.card)
            .overlay(alignment: .top) { LandingBadge(session: session, twentyFour: Civil.prefers24Hour) }
        }
    }

    private func content(_ layout: TimelineLayout, today: String, width: Double) -> some View {
        let around = drawn.isEmpty ? [Civil.add(today, days: -1), today, Civil.add(today, days: 1)] : drawn
        let shown = Set(around)
        let days = layout.days.filter { shown.contains($0.date) }
        let twentyFour = Civil.prefers24Hour
        let minute = store.moment.minutes
        return ZStack(alignment: .topLeading) {
            Color.clear.allowsHitTesting(false)
            ForEach(days) { day in
                DaySlot(session: session, day: day, width: width, today: today,
                        // Only today's drawing depends on the minute.
                        minute: day.date == today ? minute : 0, twentyFour: twentyFour, actions: actions)
                    .offset(y: day.top)
            }
            DragLayer(session: session, layout: layout, width: width, twentyFour: twentyFour)
        }
        .frame(width: width, height: layout.height, alignment: .topLeading)
    }

    private var actions: TimelineTaskActions {
        TimelineTaskActions(
            open: open,
            toggle: { task in
                guard mayPress else { return }
                Task { await store.setDone(task, !task.done) }
            },
            star: { task in
                guard mayPress else { return }
                Task { await store.toggleStar(task) }
            },
            act: act,
            add: add)
    }

    private func add(_ date: String, _ start: Int) {
        guard mayPress, !memory.closedSwipe else { return }
        if session.swipe != nil {
            withAnimation(.snappy) { session.swipe = nil }
        } else {
            let blocks = timelineBlocks(calendarDay(store.days[date]?.items ?? []))
            guard let gap = timelineGaps(blocks).first(where: { $0.addAt == start }) else { return }
            let slot = PendingSlot(day: date, start: start, end: gap.start + gap.minutes)
            editor = EditorRequest(date: slot.target.date, time: slot.target.time, pendingSlot: slot)
        }
    }

    private func jump(_ task: PlannerTask) {
        if listView {
            reveal = task.id
        } else {
            let date = store.selectedDate
            let place: ScrollRequest.Place = task.time == nil ? .untimed(date) : .clock(date: date, minute: task.clockMinutes)
            request = ScrollRequest(place: place, animated: true)
        }
    }

    private var mayPress: Bool { Date() >= memory.quietUntil }

    private func open(_ task: PlannerTask) {
        guard mayPress, !memory.closedSwipe else { return }
        if session.swipe != nil {
            withAnimation(.snappy) { session.swipe = nil }
        } else {
            editor = EditorRequest(task: task)
        }
    }

    private func act(_ action: SwipeAction, _ task: PlannerTask, _ date: String) {
        withAnimation(.snappy) { session.swipe = nil }
        switch action {
        case .nextDay: Task { await store.nextDay(task, shownOn: date) }
        case .archive: Task { await store.archive(task) }
        case .delete: store.confirmingDelete = task
        }
    }

    // MARK: Fingers and mouse

    private func input(_ layout: TimelineLayout, width: Double) -> TimelineInput {
        var input = TimelineInput()
        // Read as each event arrives, never while the timeline's body is drawn.
        let session = session
        let task = { (point: CGPoint, anywhere: Bool) -> TimelineHit? in
            if let swiped = session.swipe {
                // The swipe's buttons are on top of whatever they cover.
                if swiped.x < 0, swiped.bar(width: width).contains(point) { return nil }
                if swiped.isOpen, swiped.hit.frame.offsetBy(dx: CGFloat(swiped.x), dy: 0).contains(point) { return swiped.hit }
            }
            return layout.hit(point, width: width, anywhere: anywhere)
        }
        input.hit = { task($0, false) }
        input.swipeable = { task($0, true) }
        input.swiped = { session.swipe?.hit.task.id }
        input.pressed = { point in
            memory.closedSwipe = false
            guard let swiped = session.swipe, !swiped.bar(width: width).contains(point),
                  !swiped.hit.frame.offsetBy(dx: CGFloat(swiped.x), dy: 0).contains(point) else { return }
            memory.closedSwipe = true
            withAnimation(.snappy) { session.swipe = nil }
        }
        input.open = { open($0.task) }
        input.swipe = { hit, dx in
            quiet()
            var next = session.swipe ?? SwipeState(hit: hit)
            if next.hit.task.id != hit.task.id { next = SwipeState(hit: hit) }
            next.x = min(max(next.from + dx, -next.fullWidth), 0)
            if next != session.swipe { session.swipe = next }
        }
        input.swipeEnded = { hit, dx, velocity in
            quiet()
            guard var next = session.swipe, next.hit.task.id == hit.task.id else { return }
            let reached = next.from + dx
            let out = velocity < -500 || (velocity <= 500 && reached < -next.fullWidth * 0.35)
            next.x = out ? -next.fullWidth : 0
            next.from = next.x
            withAnimation(.snappy(duration: 0.22)) { session.swipe = out ? next : nil }
        }
        input.lift = { hit in
            quiet()
            if session.swipe != nil { session.swipe = nil }
            // A task still being added has no id the server knows yet.
            guard !hit.task.id.hasPrefix("pending:") else { return }
            // The outline is there the moment it is picked up, before it moves.
            let timed = hit.task.time != nil
            session.setDrag(DragState(hit: hit, date: timed ? hit.date : nil, start: timed ? hit.task.clockMinutes : 0))
            store.beginDrag(hit.task.id)
        }
        input.drag = { hit, top, window in
            quiet()
            guard var next = session.drag else { return }
            let bin = isBin(window)
            if bin != overBin { overBin = bin }
            let landing = bin ? nil : land(hit, top: top, in: layout)
            next.date = landing?.date
            next.start = landing?.start ?? 0
            session.setDrag(next)
        }
        input.drop = { hit, top, window in
            quiet()
            guard session.drag != nil else { return }
            let bin = isBin(window)
            endDrag()
            if bin {
                store.confirmingDelete = hit.task
                return
            }
            guard let landing = land(hit, top: top, in: layout),
                  landing.date != hit.date || hit.task.time == nil || landing.start != hit.task.clockMinutes else { return }
            store.rescheduleNow(hit.task, date: landing.date, start: landing.start)
        }
        input.cancelDrag = {
            quiet()
            endDrag()
        }
        input.heldStill = { hit, seconds in
            // A short press is a tap, which the hold took from the task's button.
            if seconds < 0.5 {
                memory.quietUntil = .distantPast
                open(hit.task)
            } else if hit.task.time == nil, !hit.task.id.hasPrefix("pending:") {
                menuTask = hit.task
            }
        }
        input.toTop = {
            session.swipe = nil
            request = ScrollRequest(place: .day(store.selectedDate), animated: true)
        }
        input.viewed = { top, height in viewed(layout, top: top, height: height) }
        let store = store
        input.barTop = { store.binFrame.height > 0 ? Double(store.binFrame.minY) : .infinity }
        return input
    }

    private func quiet() { memory.quietUntil = Date().addingTimeInterval(0.3) }

    private func isBin(_ window: CGPoint) -> Bool {
        store.binFrame.height > 0 && store.binFrame.insetBy(dx: -8, dy: -8).contains(window)
    }

    /// Where a held task lands. An untimed one let go among the untimed rows it
    /// came from stays untimed.
    private func land(_ hit: TimelineHit, top: Double, in layout: TimelineLayout) -> (date: String, start: Int)? {
        if hit.task.time == nil, let home = layout.day(hit.date),
           top >= home.top - timelineGridPadding, top < home.gridTop - timelineGridPadding { return nil }
        return layout.landing(at: top)
    }

    private func endDrag() {
        session.setDrag(nil)
        overBin = false
        store.endDrag()
    }

    /// What is on screen decides which days are drawn and read, and which date the tile says.
    private func viewed(_ layout: TimelineLayout, top: Double, height: Double) {
        guard let first = layout.index(at: top - 500), let last = layout.index(at: top + height + 500),
              let reading = layout.index(at: top + height / 3) else { return }
        let dates = layout.days[first...last].map(\.date)
        if dates != drawn {
            drawn = dates
            store.showDays(dates)
        }
        let date = layout.days[reading].date
        if date != store.selectedDate { store.selectedDate = date }
    }

    // MARK: Going places

    private func openAtNow(_ today: String) {
        var minute = store.moment.minutes
        #if DEBUG
        // The UI tests seed the morning and cannot choose the hour they run at.
        if let start = ConnectionStore.uiTestStart { minute = start }
        #endif
        request = ScrollRequest(place: .clock(date: today, minute: minute))
    }

    private func go(to date: String) {
        picked = date
        store.selectedDate = date
        if date == store.calendarToday {
            goToNow()
        } else if store.days[date] != nil {
            showStart(of: date)
        } else {
            request = ScrollRequest(place: .day(date))
            let asked = request?.id
            Task {
                await store.loadDay(date)
                // Unless somewhere else has been asked for meanwhile.
                if request?.id == asked, store.selectedDate == date { showStart(of: date) }
            }
        }
    }

    /// A day opens at its first task, or at its header with none.
    private func showStart(of date: String) {
        let first = timelineAnchor(calendarDay(store.days[date]?.items ?? []), now: -1)
        request = ScrollRequest(place: first.map { .clock(date: date, minute: $0.clockMinutes) } ?? .day(date))
    }

    private func goToNow() {
        let today = store.calendarToday
        session.swipe = nil
        if listView {
            store.selectedDate = today
        } else {
            let now = store.moment.minutes
            let task = timelineAnchor(calendarDay(store.days[today]?.items ?? []), now: now)
            request = ScrollRequest(place: .clock(date: today, minute: task?.clockMinutes ?? now), animated: true)
        }
    }

    // MARK: The top

    /// The date and, pinned under it, that day's Top Wins, over the timeline and the list alike.
    private func top(today: String) -> some View {
        let items = calendarDay(store.days[store.selectedDate]?.items ?? [])
        let wins = items.sorted { ($0.clockMinutes, $0.title) < ($1.clockMinutes, $1.title) }
        return VStack(spacing: 0) {
            header(today: today)
            WinsStrip(tasks: wins, onJump: jump)
        }
        .overlay(alignment: .top) {
            if refreshing { ProgressView().controlSize(.small).allowsHitTesting(false) }
        }
        #if os(iOS)
        .contentShape(Rectangle())
        // The timeline's own top is two weeks up, so pulling down from here refreshes.
        .simultaneousGesture(DragGesture(minimumDistance: 24).onEnded { value in
            guard !refreshing, value.translation.height > 70,
                  value.translation.height > abs(value.translation.width) * 2 else { return }
            quiet()
            Task {
                refreshing = true
                await store.refreshAll()
                refreshing = false
            }
        })
        #endif
    }

    /// The tile of the day in view, then Fit, Now and everything else.
    private func header(today: String) -> some View {
        let date = store.selectedDate
        let items = calendarDay(store.days[date]?.items ?? [])
        // Only offered when there is something to fit, and it says how
        // many, so pressing it is never a shot in the dark.
        let loose = looseEnds(items, now: date == today ? store.moment.minutes : nil)
        return HStack(spacing: 0) {
            Button { if mayPress { pickingDate = true } } label: {
                DateTile(date: date, isToday: date == today)
            }
            .buttonStyle(.hitArea)
            .accessibilityIdentifier("date-tile")
            .accessibilityLabel(Civil.short(date))
            .accessibilityHint("The day in view. Pick another")
            Spacer(minLength: 6)
            if !loose.isEmpty {
                Button { Task { await store.fitDay() } } label: {
                    Label("Fit \(loose.count)", systemImage: "wand.and.stars")
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(1)
                        .fixedSize()
                        .frame(height: 44)
                }
                .tint(Palette.accent)
                .buttonStyle(.borderless)
                .accessibilityLabel("Find a time for \(plural(loose.count, "loose task"))")
                .padding(.trailing, 10)
            }
            Button(action: goToNow) {
                Text("Now").font(.subheadline.weight(.semibold)).fixedSize().frame(height: 44)
            }
            .tint(Palette.accent)
            .buttonStyle(.borderless)
            // Everything else about the day lives behind one button, the same
            // on Android: the list or the timeline, and reading it again.
            Menu {
                Button { listView.toggle() } label: {
                    Label(listView ? "Show timeline" : "Show list",
                          systemImage: listView ? "calendar.day.timeline.left" : "list.bullet")
                }
                Button { Task { await store.refreshAll() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                #if os(macOS)
                Toggle("Floating clock", isOn: $showClock)
                Toggle("Small floating clock", isOn: $smallClock)
                #endif
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.system(size: 20))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 40, height: 44)
            }
            #if os(macOS)
            .menuStyle(.button)
            .buttonStyle(.borderless)
            .menuIndicator(.hidden)
            .fixedSize()
            .tint(Palette.accent)
            #endif
            .accessibilityLabel("More")
            .padding(.leading, 4)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }

    private var list: some View {
        let date = store.selectedDate
        let items = calendarDay(store.days[date]?.items ?? [])
        return ScrollViewReader { proxy in
        ScrollView {
            VStack(spacing: 0) {
                DayList(tasks: items, twentyFour: Civil.prefers24Hour,
                        onOpen: { editor = EditorRequest(task: $0) },
                        onToggle: { task in Task { await store.setDone(task, !task.done) } },
                        onStar: { task in Task { await store.toggleStar(task) } })
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)
            // Past the floating bar, or the last row can't be scrolled out from behind it.
            .padding(.bottom, 120)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .refreshable { await store.refreshAll() }
        .background(Palette.card)
        .onChange(of: reveal) { _, id in
            guard let id else { return }
            withAnimation(.snappy) { proxy.scrollTo(id, anchor: .center) }
            reveal = nil
        }
        }
        .task(id: date) { await store.loadDay(date) }
        .refreshable { await store.refreshAll() }
    }
}

/// A day as the finger has it: which of its tasks is pulled or picked up. Only
/// a day whose own answer changes is drawn again.
@MainActor
private struct DaySlot: View {
    let session: TimelineSession
    let day: TimelineDay
    let width: Double
    let today: String
    let minute: Int
    let twentyFour: Bool
    let actions: TimelineTaskActions

    var body: some View {
        let swipe = session.swipe?.hit.date == day.date ? session.swipe : nil
        let hidden = session.hiddenID.flatMap { id in
            day.blocks.contains { $0.id == id } || day.untimed.contains { $0.id == id } ? id : nil
        }
        TimelineDayView(day: day, width: width, today: today, minute: minute, twentyFour: twentyFour,
                        swipe: swipe, hiddenID: hidden, actions: actions)
            .equatable()
    }
}

/// The outline under the finger: all that is redrawn as a held task moves.
@MainActor
private struct DragLayer: View {
    let session: TimelineSession
    let layout: TimelineLayout
    let width: Double
    let twentyFour: Bool

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.clear.frame(width: 1, height: 1).allowsHitTesting(false)
            if let drag = session.drag, let date = drag.date, let day = layout.day(date) {
                LandingOutline(task: drag.hit.task, date: date, start: drag.start,
                               width: max(width - timelineLabelWidth - timelineTrailing, 1),
                               height: max(minuteOffset(drag.hit.task.minutes), timelineMinBlock),
                               twentyFour: twentyFour)
                    .offset(x: timelineLabelWidth, y: day.gridTop + minuteOffset(drag.start))
            }
        }
        .sensoryFeedback(.selection, trigger: session.bumps)
    }
}

/// Where a held task will land, pinned on top: the finger covers the outline,
/// and at the bottom edge, scrolling into later dates, the bar does too.
@MainActor
private struct LandingBadge: View {
    let session: TimelineSession
    let twentyFour: Bool

    var body: some View {
        if let drag = session.drag, let date = drag.date {
            HStack(spacing: 8) {
                Circle().fill(Palette.block(drag.hit.task)).frame(width: 10, height: 10)
                Text(Civil.short(date)).fontWeight(.heavy)
                Text(rangeText(drag.start, drag.start + drag.hit.task.minutes, twentyFour: twentyFour)).monospacedDigit()
            }
            .font(.subheadline.weight(.semibold))
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 14)
            .frame(height: 36)
            .background(Palette.card, in: Capsule())
            .overlay(Capsule().strokeBorder(Color.primary.opacity(0.15), lineWidth: 1))
            .shadow(color: .black.opacity(0.18), radius: 6, y: 2)
            .padding(.top, 8)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }
}

/// The day in view, as a calendar's tile, with its month beside it.
private struct DateTile: View {
    let date: String
    let isToday: Bool

    var body: some View {
        HStack(spacing: 10) {
            VStack(spacing: 0) {
                Text(Civil.weekdayShort(date).uppercased())
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 18)
                    .background(isToday ? Palette.accent : Color.secondary)
                Text(String(Int(date.suffix(2)) ?? 0))
                    .font(.system(size: 24, weight: .heavy).monospacedDigit())
                    .foregroundStyle(Color.primary)
                    .frame(maxHeight: .infinity)
            }
            .frame(width: 52, height: 54)
            .background(Palette.card)
            .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 11, style: .continuous).strokeBorder(Color.primary.opacity(0.18), lineWidth: 1))
            VStack(alignment: .leading, spacing: 0) {
                Text(Civil.monthName(date)).font(.system(size: 19, weight: .bold)).foregroundStyle(Color.primary)
                Text(Civil.year(date)).font(.subheadline.weight(.semibold)).foregroundStyle(Palette.accent)
            }
            .lineLimit(1)
            .minimumScaleFactor(0.7)
        }
    }
}

/// The day as a plain list: a tick, the name, when and how long, and a star.
/// What is done sinks under a "Completed" line, as on Android.
@MainActor
struct DayList: View {
    let tasks: [PlannerTask]
    let twentyFour: Bool
    let onOpen: (PlannerTask) -> Void
    let onToggle: (PlannerTask) -> Void
    let onStar: (PlannerTask) -> Void

    var body: some View {
        let lists = dayList(tasks)
        VStack(alignment: .leading, spacing: 0) {
            if tasks.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "sun.horizon").font(.system(size: 40)).foregroundStyle(.secondary)
                    Text("A clear day").font(.headline)
                    Text("Tap + to add a task, with or without a time.").font(.subheadline).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 60)
            }
            ForEach(lists.open) { row($0) }
            if !lists.done.isEmpty {
                HStack(spacing: 10) {
                    Text("Completed · \(lists.done.count)")
                        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    Rectangle().fill(Color.secondary.opacity(0.25)).frame(height: 1)
                }
                .padding(.top, 14).padding(.bottom, 4).padding(.horizontal, 8)
                ForEach(lists.done) { row($0) }
            }
        }
    }

    private func detail(_ task: PlannerTask) -> String {
        guard task.time != nil else { return "No time · \(durationWords(task.minutes))" }
        return "\(rangeText(task.clockMinutes, task.clockMinutes + task.minutes, twentyFour: twentyFour)) · \(durationWords(task.minutes))"
    }

    // The tick and the star are siblings of the part that opens the task,
    // never inside it, or the Mac gives their clicks to the row.
    private func row(_ task: PlannerTask) -> some View {
        let color = Palette.block(task)
        return HStack(spacing: 0) {
            Button { onToggle(task) } label: {
                ZStack {
                    Circle().stroke(color, lineWidth: 2)
                    if task.done {
                        Circle().fill(color)
                        Image(systemName: "checkmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                    }
                }
                .frame(width: 24, height: 24)
                .frame(width: 44, height: 48)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel("\(task.done ? "Reopen" : "Complete") \(task.title)")
            Button { onOpen(task) } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(task.title)
                        .font(.system(size: 16, weight: .medium))
                        .strikethrough(task.done)
                        .foregroundStyle(task.done ? .secondary : .primary)
                        .multilineTextAlignment(.leading)
                        .lineLimit(2)
                    HStack(spacing: 4) {
                        Text(detail(task)).font(.caption.monospacedDigit()).foregroundStyle(.secondary).lineLimit(1)
                        if task.recurrenceKey != nil || task.habit {
                            Image(systemName: "repeat").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 8)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel(task.title)
            .accessibilityValue(detail(task))
            Button { onStar(task) } label: {
                Image(systemName: task.starred ? "star.fill" : "star")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(task.starred ? Palette.accent : Color.secondary.opacity(0.55))
                    .frame(width: 40, height: 48)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel("\(task.starred ? "Remove" : "Choose") \(task.title) as Top Win")
        }
        .opacity(task.done ? 0.65 : 1)
        .id(task.id)
    }
}

/// A task with no time, on one line under its day's header: a tick, the
/// title, which opens it, and a star. Three buttons, none inside another.
@MainActor
struct UntimedRow: View {
    let task: PlannerTask
    let onOpen: () -> Void
    let onToggle: () -> Void
    let onStar: () -> Void

    var body: some View {
        let color = Palette.block(task)
        HStack(spacing: 0) {
            Button(action: onToggle) {
                TickCircle(done: task.done, ink: color, check: .white, size: 22)
                    .frame(width: timelineUntimedHeight, height: timelineUntimedHeight)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel("\(task.done ? "Reopen" : "Complete") \(task.title)")
            Button(action: onOpen) {
                Text(task.title)
                    .font(.system(size: 15, weight: .medium))
                    .strikethrough(task.done)
                    .foregroundStyle(task.done ? .secondary : .primary)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel(task.title)
            .accessibilityValue("No time")
            Button(action: onStar) {
                Image(systemName: task.starred ? "star.fill" : "star")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(task.starred ? Palette.accent : Color.secondary.opacity(0.55))
                    .frame(width: 44, height: timelineUntimedHeight)
            }
            .buttonStyle(.hitArea)
            .accessibilityLabel("\(task.starred ? "Remove" : "Choose") \(task.title) as Top Win")
        }
        .frame(height: timelineUntimedHeight)
    }
}

/// Top Wins, pinned under the date: "Top Wins · 1 of 3" (or "Day won"), then a
/// chip for each. Tap one to go to it.
@MainActor
struct WinsStrip: View {
    let tasks: [PlannerTask]
    let onJump: (PlannerTask) -> Void

    var body: some View {
        let wins = tasks.filter(\.starred)
        HStack(spacing: 8) {
            Image(systemName: wins.isEmpty ? "star" : "star.fill").font(.caption).foregroundStyle(Palette.accent)
            Text(wins.isEmpty ? "Top Wins" : winsTitle(wins))
                .font(.caption.weight(.semibold)).lineLimit(1).fixedSize()
                .accessibilityIdentifier("top-wins")
            if wins.isEmpty {
                Text("Tap ☆ on a task to pin it here.").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 0)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(wins) { task in
                            Button { onJump(task) } label: {
                                HStack(spacing: 5) {
                                    Image(systemName: task.done ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(Palette.accent)
                                    Text(task.title).strikethrough(task.done).lineLimit(1).frame(maxWidth: 160, alignment: .leading)
                                }
                                .font(.caption)
                                .padding(.horizontal, 9)
                                .frame(height: 30)
                                .background(Palette.card, in: Capsule())
                                .frame(height: timelineWinsHeight)
                            }
                            .buttonStyle(.hitArea)
                            .accessibilityLabel("Top Win \(task.title), \(task.done ? "complete" : "incomplete"). Reveal task")
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity)
        .frame(height: timelineWinsHeight)
        .background(Palette.accent.opacity(0.12))
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
