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

    /// "Deep work, 29 minutes left." — what is happening right now.
    static func nowSentence(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot, !snapshot.tasks.isEmpty else { return "Nothing on today." }
        if let current = snapshot.current(at: minute) {
            let left = current.end - minute
            return "\(current.title), \(left) \(left == 1 ? "minute" : "minutes") left."
        }
        guard let next = snapshot.upcoming(after: minute).first else {
            return snapshot.remaining == 0 ? "That is the day done." : "Nothing more is scheduled today."
        }
        return "Next is \(next.title) at \(spokenClock(next.start))."
    }

    /// "Next is Standup at 9:30 am." — skips whatever is under way.
    static func nextSentence(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot else { return "Nothing on today." }
        guard let next = snapshot.upcoming(after: minute).first else {
            return "Nothing more is scheduled today."
        }
        return "Next is \(next.title) at \(spokenClock(next.start))."
    }

    /// "3 left, 2 hours 30 minutes of it." — how much of the day is still ahead.
    static func remainingSentence(_ snapshot: PlannerSnapshot?, at minute: Int) -> String {
        guard let snapshot, !snapshot.tasks.isEmpty else { return "Nothing on today." }
        let open = snapshot.tasks.filter { !$0.done }
        if open.isEmpty { return "Everything is ticked off." }
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

/// The calls the voice menu makes. Reading is free from the snapshot; these
/// are the ones that change something and so have to reach the server.
enum PlannerVoiceAPI {
    struct Failure: Error { var message: String }

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
