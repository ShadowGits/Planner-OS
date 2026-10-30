import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct PlannerError: LocalizedError {
    var message: String
    var status: Int?
    var errorDescription: String? { message }
}

/// A server origin and the app access key it accepts (the same key Android uses).
struct Connection: Equatable {
    var base: URL
    var key: String

    /// Only a bare HTTPS origin: no path, credentials, query or fragment.
    static func origin(_ text: String) throws -> URL {
        var trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        while trimmed.hasSuffix("/") { trimmed.removeLast() }
        guard let parts = URLComponents(string: trimmed), parts.scheme == "https",
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil, parts.path.isEmpty || parts.path == "/",
              let url = URL(string: trimmed) else {
            throw PlannerError(message: "Use your HTTPS server origin, without /app, credentials or query parameters.")
        }
        return url
    }
}

/// Talks to the Planner OS backend. Every request carries the app key, so
/// redirects are refused: the key never follows one to another host.
final class PlannerAPI: Sendable {
    let connection: Connection
    private let session: URLSession

    init(connection: Connection) {
        self.connection = connection
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 20
        config.timeoutIntervalForResource = 40
        session = URLSession(configuration: config, delegate: RefuseRedirects(), delegateQueue: nil)
    }

    static func taskPath(_ id: String) -> String {
        "/v2/day/tasks/" + (id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? id)
    }

    /// Sends one request and returns the raw body of a successful response.
    @discardableResult
    func send(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> Data {
        guard path.hasPrefix("/v2/"), !path.contains("://"), let url = URL(string: connection.base.absoluteString + path) else {
            throw PlannerError(message: "Invalid planner API path.")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(connection.key, forHTTPHeaderField: "X-App-Key")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        if !(200..<300).contains(code) || json?["success"] as? Bool == false {
            throw PlannerError(message: Self.message(json) ?? Self.fallback(code), status: code)
        }
        return data
    }

    /// GETs and decodes `data`, keeping the body so the screen can paint it offline next time.
    func get<T: Decodable>(_ path: String, cacheAs key: String? = nil) async throws -> T {
        let data = try await send("GET", path)
        let value = try JSONDecoder().decode(Envelope<T>.self, from: data).data
        ResponseCache.save(data, key: key ?? path)
        return value
    }

    func cached<T: Decodable>(_ key: String) -> T? {
        ResponseCache.load(key).flatMap { try? JSONDecoder().decode(Envelope<T>.self, from: $0).data }
    }

    private static func message(_ json: [String: Any]?) -> String? {
        if let detail = json?["detail"] as? [String: Any], let text = detail["message"] as? String { return text }
        if let detail = json?["detail"] as? String { return detail }
        if let detail = json?["detail"] as? [[String: Any]], let first = detail.first?["msg"] as? String { return first }
        return json?["message"] as? String
    }

    private static func fallback(_ code: Int) -> String {
        switch code {
        case 401, 403: return "The app key was not accepted. Check it in Settings."
        case 300..<400: return "The server tried to redirect. Use its final HTTPS origin."
        case 404: return "That item is no longer available."
        case 500...: return "The planner server had a problem (\(code)). Try again shortly."
        default: return "The planner server could not be reached."
        }
    }
}

private final class RefuseRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

/// The last good response per screen, on disk in Caches.
enum ResponseCache {
    private static var folder: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("planner-responses", isDirectory: true)
    }

    private static func file(_ key: String) -> URL {
        let name = key.unicodeScalars.map { CharacterSet.alphanumerics.contains($0) ? String($0) : "_" }.joined()
        return folder.appendingPathComponent(name + ".json")
    }

    static func save(_ data: Data, key: String) {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? data.write(to: file(key), options: .atomic)
    }

    static func load(_ key: String) -> Data? { try? Data(contentsOf: file(key)) }

    static func clear() { try? FileManager.default.removeItem(at: folder) }
}
