import Foundation
import XCTest

/// The local Planner OS API the UI tests run against (`python3 e2e/server.py 8765`,
/// app key "app-secret"). Tasks are seeded through the same /v2/day API the app
/// uses, and read back from it to check what a tap really changed.
///
/// Another address can be given with TEST_RUNNER_PLANNER_UI_TEST_SERVER.
struct TestServer {
    static let shared = TestServer()

    let base: String
    let key = "app-secret"

    init() {
        base = ProcessInfo.processInfo.environment["PLANNER_UI_TEST_SERVER"] ?? "http://127.0.0.1:8765"
    }

    /// The planner's day, as the app works it out: Asia/Kolkata, and before 04:00 still the evening before.
    var today: String { Self.civil(Date().addingTimeInterval(-4 * 3600)) }
    /// The calendar date, which Focus's Tomorrow counts from.
    var calendarToday: String { Self.civil(Date()) }

    static func civil(_ date: Date) -> String {
        let format = DateFormatter()
        format.calendar = Calendar(identifier: .gregorian)
        format.locale = Locale(identifier: "en_US_POSIX")
        format.timeZone = TimeZone(identifier: "Asia/Kolkata")
        format.dateFormat = "yyyy-MM-dd"
        return format.string(from: date)
    }

    static func add(_ day: String, days: Int) -> String {
        let format = DateFormatter()
        format.calendar = Calendar(identifier: .gregorian)
        format.locale = Locale(identifier: "en_US_POSIX")
        format.timeZone = TimeZone(identifier: "UTC")
        format.dateFormat = "yyyy-MM-dd"
        return format.string(from: format.date(from: day)!.addingTimeInterval(Double(days) * 86400))
    }

    @discardableResult
    func send(_ method: String, _ path: String, _ body: [String: Any]? = nil) throws -> [String: Any] {
        var request = URLRequest(url: URL(string: base + path)!)
        request.httpMethod = method
        request.timeoutInterval = 15
        request.setValue(key, forHTTPHeaderField: "X-App-Key")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let done = DispatchSemaphore(value: 0)
        var result: Result<Data, Error> = .failure(URLError(.timedOut))
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error { result = .failure(error) }
            else if let code = (response as? HTTPURLResponse)?.statusCode, !(200..<300).contains(code) {
                result = .failure(NSError(domain: "TestServer", code: code, userInfo: [
                    NSLocalizedDescriptionKey: "\(method) \(path) → \(code): \(String(data: data ?? Data(), encoding: .utf8) ?? "")"]))
            } else { result = .success(data ?? Data()) }
            done.signal()
        }.resume()
        done.wait()
        let data = try result.get()
        return (try JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    /// Empties the planner. Only the test server has this route.
    func reset() throws { try send("POST", "/e2e/reset") }

    /// Creates a task and returns its id.
    @discardableResult
    func create(_ title: String, date: String?, time: String? = nil, minutes: Int = 30) throws -> String {
        var body: [String: Any] = ["title": title, "estimated_minutes": minutes]
        if let date { body["date"] = date }
        if let time { body["start_time"] = time }
        let reply = try send("POST", "/v2/day/tasks", body)
        guard let id = ((reply["data"] as? [String: Any])?["task"] as? [String: Any])?["id"] as? String else {
            throw NSError(domain: "TestServer", code: 0, userInfo: [NSLocalizedDescriptionKey: "no id for \(title): \(reply)"])
        }
        return id
    }

    func day(_ date: String) throws -> [[String: Any]] {
        ((try send("GET", "/v2/day?date=\(date)")["data"] as? [String: Any])?["items"] as? [[String: Any]]) ?? []
    }

    func inbox() throws -> [[String: Any]] {
        ((try send("GET", "/v2/day/inbox")["data"] as? [String: Any])?["items"] as? [[String: Any]]) ?? []
    }

    /// The task as the server has it on a given day.
    func task(_ id: String, on date: String) throws -> [String: Any]? {
        try day(date).first { $0["id"] as? String == id }
    }
}

extension XCTestCase {
    /// Waits for something only the server or the screen will say in its own time.
    func eventually(_ what: String, timeout: TimeInterval = 8, file: StaticString = #filePath, line: UInt = #line,
                    _ condition: () throws -> Bool) {
        let deadline = Date().addingTimeInterval(timeout)
        var last: Error?
        repeat {
            do { if try condition() { return } } catch { last = error }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        XCTFail("Timed out waiting for: \(what)\(last.map { " (\($0.localizedDescription))" } ?? "")", file: file, line: line)
    }
}
