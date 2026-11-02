import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// How the widget reaches the server.
///
/// Ticking a task off from the widget has to be a real change, not a note the
/// app applies later, so the widget needs the server and the app key itself.
/// It cannot read the app's Keychain — that would need a second shared
/// entitlement — so the app leaves a copy in the folder they already share,
/// written with iOS file protection so it is unreadable until the phone has
/// been unlocked once after a restart.
///
/// The Keychain is still where the app keeps the real one; this is a copy for
/// the widget, and it goes when you disconnect.
struct SharedConnection: Codable, Equatable {
    var server: String
    var key: String

    var url: URL? { URL(string: server) }
}

enum WidgetConnection {
    private static let file = "connection.json"

    private static var location: URL? {
        PlannerSnapshot.folder?.appendingPathComponent(file)
    }

    static func save(server: String, key: String) {
        guard let location, let folder = PlannerSnapshot.folder else { return }
        guard let data = try? JSONEncoder().encode(SharedConnection(server: server, key: key)) else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        #if canImport(Darwin)
        try? data.write(to: location, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
        try? data.write(to: location, options: .atomic)
        #endif
    }

    static func load() -> SharedConnection? {
        guard let location, let data = try? Data(contentsOf: location) else { return nil }
        return try? JSONDecoder().decode(SharedConnection.self, from: data)
    }

    static func clear() {
        guard let location else { return }
        try? FileManager.default.removeItem(at: location)
    }
}

/// The one request the widget makes: ticking a task off, or putting it back.
enum PlannerWidgetAPI {
    struct Failure: Error { var message: String }

    static func setDone(_ taskId: String, _ done: Bool) async throws {
        guard let connection = WidgetConnection.load(), let base = connection.url else {
            throw Failure(message: "No server saved yet")
        }
        let path = taskId.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? taskId
        guard let url = URL(string: base.absoluteString + "/v2/day/tasks/" + path) else {
            throw Failure(message: "That task has no address")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        // The widget is on screen waiting: better to give up and put the tick
        // back than to hold a frozen circle while a cold server wakes up.
        request.timeoutInterval = 5
        request.setValue(connection.key, forHTTPHeaderField: "X-App-Key")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["done": done])

        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        if !(200..<300).contains(code) || json?["success"] as? Bool == false {
            throw Failure(message: (json?["message"] as? String) ?? "The server refused it (\(code))")
        }
    }
}
