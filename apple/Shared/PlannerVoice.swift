import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// What Siri, Shortcuts and Spotlight are allowed to do, and what they say.
///
/// Kept apart from the App Intents themselves on purpose. The intents are
/// thin wrappers Apple's framework can see; everything that decides what
/// happens and how it is worded lives here, in plain Foundation, so it is
/// tested on every run rather than only when someone opens Xcode.
///
/// Reading is answered from the snapshot the app already shares with the
/// widget: instant, right on a train with no signal, and it costs the server
/// nothing. Changing anything goes to the server, because a change has to be
/// real before Siri says it is done.
enum PlannerVoice {

    // MARK: - Answering out loud

    // MARK: - Today as a list

    /// One line of today's list as Siri shows it.
    struct TodayRow: Equatable, Identifiable {
        enum State: Equatable { case done, now, next, later, missed }
        var id: String
        var title: String
        var time: String
        var state: State
        var palette: Int
    }

    /// The planner's day runs to four in the morning, so at half past midnight
    /// "today" is still the evening before.
    static func logicalDay(_ now: Date, calendar: Calendar = .current) -> String {
        dayStamp(now.addingTimeInterval(-4 * 3600), calendar: calendar)
    }

    /// Minutes into the planner's day: half past midnight is 24:30, so it can
    /// be compared with the evening's tasks rather than mistaken for morning.
    static func logicalMinute(_ now: Date, calendar: Calendar = .current) -> Int {
        let parts = calendar.dateComponents([.hour, .minute], from: now)
        let hour = parts.hour ?? 0, minute = parts.minute ?? 0
        return (hour < 4 ? hour + 24 : hour) * 60 + minute
    }

    /// Whether the copy the app left is of the day being asked about. The app
    /// only writes it while it runs, so a copy from yesterday is normal — and
    /// reading it as today is how Siri came to say the wrong thing.
    static func isFresh(_ snapshot: PlannerSnapshot?, today: String) -> Bool {
        snapshot?.date == today
    }

    /// Everything on today, in time order, each marked done, under way, next,
    /// missed or later — habits included, ticked ones included, so it reads
    /// like the timeline rather than a summary of it.
    static func todayRows(_ snapshot: PlannerSnapshot?, at minute: Int) -> [TodayRow] {
        guard let snapshot else { return [] }
        let ordered = snapshot.tasks.sorted { ($0.start, $0.title) < ($1.start, $1.title) }
        let current = snapshot.current(at: minute)?.id
        let next = ordered.first { !$0.done && $0.start >= minute && $0.id != current }?.id
        return ordered.map { item in
            let state: TodayRow.State
            if item.done { state = .done }
            else if item.id == current { state = .now }
            else if item.id == next { state = .next }
            else if item.end <= minute { state = .missed }
            else { state = .later }
            return TodayRow(id: item.id, title: item.title, time: spokenClock(item.start),
                            state: state, palette: item.palette)
        }
    }

    /// The one line said aloud above the list: the list is the answer, this
    /// only says what it adds up to.
    static func todaySummary(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot, !snapshot.tasks.isEmpty else { return "Nothing on today." + inboxTail(snapshot) }
        let total = snapshot.tasks.count
        let done = total - snapshot.remaining
        var line = "\(total) on today, \(done) done."
        if let current = snapshot.current(at: minute) {
            line += " Now: \(current.title)."
        } else if let next = snapshot.upcoming(after: minute).first {
            line += " Next: \(next.title) at \(spokenClock(next.start))."
        }
        return line + inboxTail(snapshot)
    }

    /// The same colour slot the app gives a task, so a list read from the
    /// server matches the timeline.
    static func paletteSlot(_ title: String, count: Int = 8) -> Int {
        var hash: UInt64 = 5381
        for scalar in title.unicodeScalars { hash = (hash &* 33) &+ UInt64(scalar.value) }
        return Int(hash % UInt64(max(count, 1)))
    }

    /// The server's day, in the shape the widget and the voice menu read.
    /// Only timed items, like the copy the app writes; an untimed task has no
    /// place in a list ordered by the clock.
    static func snapshot(fromDay data: [String: Any], waiting: Int, now: Date = Date()) -> PlannerSnapshot? {
        guard let date = data["date"] as? String, let rows = data["items"] as? [[String: Any]] else { return nil }
        let items: [PlannerSnapshot.Item] = rows.compactMap { row in
            guard let id = row["id"] as? String, let title = row["title"] as? String,
                  let start = parseClock(row["start_time"] as? String) else { return nil }
            let minutes = max((row["estimated_minutes"] as? Int) ?? 30, 1)
            return PlannerSnapshot.Item(id: id, title: title, start: start, minutes: minutes,
                                        done: (row["done"] as? Bool) ?? false, palette: paletteSlot(title))
        }
        return PlannerSnapshot(date: date, updated: now, tasks: items, waiting: waiting)
    }

    /// What is waiting in the Inbox — overdue or never given a day — added
    /// whenever the day itself has nothing to say. "Nothing on today" with
    /// twenty overdue behind it is true and still the wrong answer.
    static func inboxTail(_ snapshot: PlannerSnapshot?) -> String {
        guard let waiting = snapshot?.waiting, waiting > 0 else { return "" }
        return waiting == 1 ? " 1 task is waiting in your inbox." : " \(waiting) tasks are waiting in your inbox."
    }

    /// "Deep work, 29 minutes left." — what is happening right now.
    static func nowSentence(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot, !snapshot.tasks.isEmpty else { return "Nothing on today." + inboxTail(snapshot) }
        if let current = snapshot.current(at: minute) {
            let left = current.end - minute
            return "\(current.title), \(left) \(left == 1 ? "minute" : "minutes") left."
        }
        guard let next = snapshot.upcoming(after: minute).first else {
            return (snapshot.remaining == 0 ? "That is the day done." : "Nothing more is scheduled today.")
                + inboxTail(snapshot)
        }
        return "Next is \(next.title) at \(spokenClock(next.start))."
    }

    /// "Next is Standup at 9:30 am." — skips whatever is under way.
    static func nextSentence(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot else { return "Nothing on today." }
        guard let next = snapshot.upcoming(after: minute).first else {
            return "Nothing more is scheduled today." + inboxTail(snapshot)
        }
        return "Next is \(next.title) at \(spokenClock(next.start))."
    }

    /// "3 left, 2 hours 30 minutes of it." — how much of the day is still ahead.
    static func remainingSentence(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot, !snapshot.tasks.isEmpty else { return "Nothing on today." + inboxTail(snapshot) }
        let open = snapshot.tasks.filter { !$0.done }
        if open.isEmpty { return "Everything is ticked off." + inboxTail(snapshot) }
        let minutes = open.reduce(0) { $0 + max($1.minutes, 1) }
        return "\(open.count) left, \(durationSpoken(minutes)) of it."
    }

    /// "7:05 pm", for a sentence read out loud. After midnight reads as the
    /// small hours, so 25:30 is half past one in the morning.
    static func spokenClock(_ minutes: Int) -> String {
        let hour24 = (minutes / 60) % 24
        let minute = minutes % 60
        let suffix = hour24 < 12 ? "am" : "pm"
        let hour = hour24 % 12 == 0 ? 12 : hour24 % 12
        return "\(hour):\(String(format: "%02d", minute)) \(suffix)"
    }

    /// "2 hours 30 minutes", "45 minutes", "1 hour".
    static func durationSpoken(_ minutes: Int) -> String {
        let hours = minutes / 60, rest = minutes % 60
        let hourPart = "\(hours) \(hours == 1 ? "hour" : "hours")"
        let minutePart = "\(rest) \(rest == 1 ? "minute" : "minutes")"
        if hours == 0 { return minutePart }
        if rest == 0 { return hourPart }
        return "\(hourPart) \(minutePart)"
    }

    // MARK: - Reading a spoken time

    /// The clock an intent was handed, as minutes after midnight.
    ///
    /// Apple resolves "half seven tomorrow" into a real date for us, so this
    /// only has to turn that into the planner's own counting — and to carry a
    /// small-hours slot on as part of the evening, the way the timeline does.
    static func minutes(from date: Date, on day: String, calendar: Calendar = .current) -> Int? {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        guard let hour = parts.hour, let minute = parts.minute else { return nil }
        let stamp = Self.dayStamp(date, calendar: calendar)
        var total = hour * 60 + minute
        // Asked for 1 am tomorrow while planning tonight: the timeline calls
        // that 25:00, still part of this evening.
        if stamp != day, hour < 4 { total += 24 * 60 }
        return total
    }

    static func dayStamp(_ date: Date, calendar: Calendar = .current) -> String {
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        guard let year = parts.year, let month = parts.month, let day = parts.day else { return "" }
        return String(format: "%04d-%02d-%02d", year, month, day)
    }

    static func clockText(_ minutes: Int) -> String {
        String(format: "%02d:%02d", minutes / 60, minutes % 60)
    }

    // MARK: - Finding the task someone named

    /// The tasks worth offering when Siri has to ask "which one?".
    ///
    /// Open ones first and the nearest in time first, because that is almost
    /// always the one meant. A finished task still shows, so "put the gym
    /// back" works.
    static func candidates(_ snapshot: PlannerSnapshot?, matching text: String, at minute: Int) -> [PlannerSnapshot.Item] {
        guard let snapshot else { return [] }
        let needle = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let pool = needle.isEmpty
            ? snapshot.tasks
            : snapshot.tasks.filter { $0.title.lowercased().contains(needle) }
        return pool.sorted {
            if $0.done != $1.done { return !$0.done }
            let left = $0.end <= minute, right = $1.end <= minute
            if left != right { return !left }
            return ($0.start, $0.title) < ($1.start, $1.title)
        }
    }

    // MARK: - Talking about a set of tasks

    /// "Today", "Tomorrow", "30 November" — how a day is named out loud.
    static func dayLabel(_ stamp: String, today: String) -> String {
        if stamp == today { return "today" }
        if stamp == shift(today, by: 1) { return "tomorrow" }
        if stamp == shift(today, by: -1) { return "yesterday" }
        let parts = stamp.split(separator: "-")
        guard parts.count == 3, let day = Int(parts[2]), let month = Int(parts[1]),
              (1...12).contains(month) else { return stamp }
        let names = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November", "December"]
        return "\(day) \(names[month - 1])"
    }

    /// A date stamp moved by whole days, without a Calendar.
    static func shift(_ stamp: String, by days: Int) -> String {
        let parts = stamp.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return stamp }
        var components = DateComponents()
        components.year = parts[0]; components.month = parts[1]; components.day = parts[2]
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        guard let date = calendar.date(from: components),
              let moved = calendar.date(byAdding: .day, value: days, to: date) else { return stamp }
        return dayStamp(moved, calendar: calendar)
    }

    /// What Siri asks before moving a pile of tasks. Never skipped: a misheard
    /// word should not quietly move forty tasks.
    static func moveQuestion(count: Int, to label: String) -> String {
        count == 1 ? "Move 1 task to \(label)?" : "That is \(count) tasks. Move them all to \(label)?"
    }

    static func movedSentence(count: Int, to label: String) -> String {
        count == 1 ? "Moved 1 task to \(label)." : "Moved \(count) tasks to \(label)."
    }

    /// What came back from a search, said out loud.
    static func foundSentence(count: Int, total: Int, query: String) -> String {
        if count == 0 { return "Nothing matches \(query)." }
        let head = count == 1 ? "1 task matches \(query)" : "\(count) tasks match \(query)"
        return total > count ? "\(head), out of \(total)." : "\(head)."
    }

    /// The line under a task's name when Siri shows a list of them.
    static func describe(_ task: VoiceTask, today: String) -> String {
        if task.done { return "Done" }
        guard let date = task.date else { return "No date yet" }
        let day = dayLabel(date, today: today)
        guard let clock = parseClock(task.time) else { return day }
        return "\(day), \(spokenClock(clock))"
    }

    /// "09:30:00" or "25:30" to minutes after midnight.
    static func parseClock(_ text: String?) -> Int? {
        guard let text, !text.isEmpty else { return nil }
        let parts = text.split(separator: ":")
        guard let hours = Int(parts.first ?? ""), hours >= 0 else { return nil }
        let minutes = parts.count > 1 ? Int(parts[1]) ?? 0 : 0
        guard (0...59).contains(minutes) else { return nil }
        return hours * 60 + minutes
    }

    /// The single task a phrase can only mean, or nil when it is ambiguous.
    static func onlyMatch(_ snapshot: PlannerSnapshot?, matching text: String, at minute: Int) -> PlannerSnapshot.Item? {
        let found = candidates(snapshot, matching: text, at: minute)
        guard let first = found.first else { return nil }
        // An exact name wins outright, even when it is also part of another.
        let needle = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if let exact = found.first(where: { $0.title.lowercased() == needle }) { return exact }
        return found.count == 1 ? first : nil
    }
}

/// A task as the voice menu sees one, from anywhere in the workspace and on
/// any date — not only today, which is all the widget's snapshot holds.
struct VoiceTask: Codable, Equatable, Identifiable {
    var id: String
    var title: String
    var date: String?
    var time: String?
    var minutes: Int
    var done: Bool

    init(id: String, title: String, date: String? = nil, time: String? = nil,
         minutes: Int = 30, done: Bool = false) {
        self.id = id
        self.title = title
        self.date = date
        self.time = time
        self.minutes = minutes
        self.done = done
    }

    /// Reads one row of the server's task shape, which is also what search
    /// returns. Unknown fields are ignored and missing ones take a sane value,
    /// so a new column on the server cannot break the voice menu.
    init?(row: [String: Any]) {
        guard let id = row["id"] as? String, let title = row["title"] as? String else { return nil }
        self.id = id
        self.title = title
        date = row["scheduled_date"] as? String ?? row["due_date"] as? String
        time = row["start_time"] as? String
        minutes = max((row["estimated_minutes"] as? Int) ?? 30, 1)
        let status = (row["status"] as? String) ?? ""
        done = (row["done"] as? Bool) ?? ["done", "skipped"].contains(status)
    }
}

/// The calls the voice menu makes. Reading today is free from the snapshot;
/// these reach the server, because they either change something or need to see
/// past today.
enum PlannerVoiceAPI {
    struct Failure: Error { var message: String }

    struct Found: Equatable {
        var tasks: [VoiceTask]
        var total: Int
    }

    struct Created: Equatable {
        var id: String
        var title: String
    }

    struct Fitted: Equatable {
        var spoken: String
        var placed: Int
        var unplaced: Int
    }

    private static func request(_ path: String, _ method: String, _ body: [String: Any]) throws -> URLRequest {
        guard let connection = WidgetConnection.load(), let base = connection.url else {
            throw Failure(message: "Planner OS is not connected yet. Open the app once.")
        }
        guard let url = URL(string: base.absoluteString + path) else {
            throw Failure(message: "That server address cannot be used")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        // Someone is standing there waiting for an answer out loud.
        request.timeoutInterval = 10
        request.setValue(connection.key, forHTTPHeaderField: "X-App-Key")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return request
    }

    private static func send(_ request: URLRequest) async throws -> [String: Any] {
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if !(200..<300).contains(code) || json["success"] as? Bool == false {
            throw Failure(message: (json["message"] as? String) ?? "The server refused it (\(code))")
        }
        return json
    }

    /// Add a task. A time is optional: without one it lands in the day's tray
    /// and `fit` can find it a slot.
    static func create(title: String, on day: String?, at minutes: Int?, lasting: Int?) async throws -> Created {
        var body: [String: Any] = ["title": title]
        if let day { body["date"] = day }
        if let minutes { body["start_time"] = PlannerVoice.clockText(minutes) }
        if let lasting, lasting > 0 { body["estimated_minutes"] = lasting }
        let json = try await send(try request("/v2/day/tasks", "POST", body))
        let data = json["data"] as? [String: Any]
        let task = data?["task"] as? [String: Any]
        guard let id = task?["id"] as? String else {
            throw Failure(message: "The task was not saved")
        }
        return Created(id: id, title: (task?["title"] as? String) ?? title)
    }

    /// Tasks by what they are called, from anywhere in the workspace and on
    /// any date. This is what makes "the transcript ones" mean something: the
    /// widget's snapshot only holds today, so a task dated September could
    /// never be found without asking the server.
    static func search(_ text: String, openOnly: Bool = true, limit: Int = 50) async throws -> Found {
        let needle = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard needle.count >= 2 else { throw Failure(message: "Give at least two letters to search for") }
        guard let connection = WidgetConnection.load(), let base = connection.url else {
            throw Failure(message: "Planner OS is not connected yet. Open the app once.")
        }
        var parts = URLComponents(string: base.absoluteString + "/v2/tasks/search")
        parts?.queryItems = [
            URLQueryItem(name: "q", value: needle),
            URLQueryItem(name: "open", value: openOnly ? "true" : "false"),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        guard let url = parts?.url else { throw Failure(message: "That search cannot be made") }
        var ask = URLRequest(url: url)
        ask.timeoutInterval = 10
        ask.setValue(connection.key, forHTTPHeaderField: "X-App-Key")
        let json = try await send(ask)
        let data = json["data"] as? [String: Any] ?? [:]
        let rows = (data["tasks"] as? [[String: Any]]) ?? []
        let tasks = rows.compactMap(VoiceTask.init(row:))
        return Found(tasks: tasks, total: (data["total"] as? Int) ?? tasks.count)
    }

    /// Today straight from the server, for when the copy the app left is from
    /// another day. Saved back, so the widget catches up too.
    static func today(_ day: String, waiting: Int) async throws -> PlannerSnapshot {
        guard let connection = WidgetConnection.load(), let base = connection.url else {
            throw Failure(message: "Planner OS is not connected yet. Open the app once.")
        }
        var parts = URLComponents(string: base.absoluteString + "/v2/day")
        parts?.queryItems = [URLQueryItem(name: "date", value: day)]
        guard let url = parts?.url else { throw Failure(message: "That day cannot be read") }
        var ask = URLRequest(url: url)
        ask.timeoutInterval = 10
        ask.setValue(connection.key, forHTTPHeaderField: "X-App-Key")
        let json = try await send(ask)
        guard let data = json["data"] as? [String: Any],
              let snapshot = PlannerVoice.snapshot(fromDay: data, waiting: waiting) else {
            throw Failure(message: "The server's answer could not be read")
        }
        PlannerSnapshot.save(snapshot)
        return snapshot
    }

    /// Move a pile of tasks to one day, untimed, in a single request. The same
    /// call the apps' bulk move uses, so a broken deadline travels with the
    /// task and an overrun milestone is pushed out by the server.
    static func move(_ ids: [String], to day: String) async throws -> Int {
        guard !ids.isEmpty else { return 0 }
        let body: [String: Any] = ["task_ids": ids, "action": "move", "to_date": day]
        _ = try await send(try request("/v2/day/tasks/triage", "POST", body))
        return ids.count
    }

    /// Give the day's loose ends times that do not clash. The server does the
    /// arithmetic so voice, both apps and the dashboard cannot disagree.
    static func fit(on day: String?, after: String?, dryRun: Bool = false) async throws -> Fitted {
        var body: [String: Any] = ["dry_run": dryRun]
        if let day { body["date"] = day }
        if let after { body["after"] = after }
        let json = try await send(try request("/v2/day/fit", "POST", body))
        let data = json["data"] as? [String: Any] ?? [:]
        return Fitted(
            spoken: (data["spoken"] as? String) ?? (json["message"] as? String) ?? "Done.",
            placed: (data["placed_count"] as? Int) ?? 0,
            unplaced: ((data["unplaced"] as? [[String: Any]]) ?? []).count
        )
    }
}
