import Foundation
import Security

/// The server origin lives in UserDefaults; the app key only in the Keychain.
enum ConnectionStore {
    private static let service = "dev.planneros.connection"
    private static let account = "app-key"
    private static let serverKey = "server"

    static func load() -> Connection? {
        guard let server = UserDefaults.standard.string(forKey: serverKey), let base = URL(string: server),
              let key = readKey(), !key.isEmpty else { return nil }
        return Connection(base: base, key: key)
    }

    static func save(_ connection: Connection) throws {
        deleteKey()
        let item: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: Data(connection.key.utf8),
            // Background refresh reads it while the phone is locked.
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw PlannerError(message: "The key could not be saved to the Keychain (\(status)).") }
        UserDefaults.standard.set(connection.base.absoluteString, forKey: serverKey)
    }

    static func clear() {
        deleteKey()
        UserDefaults.standard.removeObject(forKey: serverKey)
    }

    private static func readKey() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func deleteKey() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
