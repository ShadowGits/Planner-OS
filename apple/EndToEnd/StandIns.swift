// Stand-ins for the Keychain and notification pieces, which need an app
// bundle; the end-to-end run exercises the store and the API, not those.
import Foundation

enum UNAuthorizationStatus { case notDetermined, denied, authorized, provisional }

enum ConnectionStore {
    static func load() -> Connection? { nil }
    static func save(_ connection: Connection) throws {}
    static func clear() {}
}

enum Reminders {
    static func status() async -> UNAuthorizationStatus { .denied }
    static func requestPermission() async -> Bool { false }
    static func sync(api: PlannerAPI, timeZone: TimeZone, now: Date = Date()) async {}
    static func clear() {}
}
