import SwiftUI
import UserNotifications

/// Server connection and reminders.
@MainActor
struct SettingsView: View {
    @Environment(PlannerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let firstRun: Bool

    @State private var server = ""
    @State private var key = ""
    @State private var connecting = false
    @State private var failure: String?
    @State private var reminders = Reminders.enabled
    @State private var permission = "Checking…"

    var body: some View {
        Form {
            Section {
                TextField("https://your-planner-server", text: $server)
                    .urlEntry()
                SecureField(store.connection == nil ? "App access key" : "App access key (blank keeps the saved one)", text: $key)
                Button(connecting ? "Connecting…" : (store.connection == nil ? "Connect" : "Save and reconnect")) { connect() }
                    .disabled(connecting || server.isEmpty || (key.isEmpty && store.connection == nil))
                if let failure {
                    Text(failure).font(.callout).foregroundStyle(.red)
                }
            } header: {
                Text("Server")
            } footer: {
                Text("The same server origin and PWA_ACCESS_KEY the Android app uses, without /app. The key stays in this device's Keychain.")
            }
            if store.connection != nil {
                Section {
                    Toggle("Remind me \(reminderLeadMinutes) minutes before", isOn: $reminders)
                    LabeledContent("Notifications", value: permission)
                    Button("Send a test notification") { Task { await Reminders.sendTest() } }
                } header: {
                    Text("Reminders")
                } footer: {
                    Text("The next 7 days of reminders are queued on this device each time the app syncs, so they arrive even when it is closed. Open the app every few days to pick up changes. Turn off browser (PWA) notifications on this device to avoid getting each reminder twice.")
                }
                Section {
                    Button("Disconnect", role: .destructive) {
                        store.disconnect()
                        dismiss()
                    }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle(firstRun ? "Connect Planner OS" : "Settings")
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if !firstRun { Button("Done") { dismiss() } }
            }
        }
        .onAppear { server = store.connection?.base.absoluteString ?? "" }
        .task { await refreshPermission() }
        .onChange(of: reminders) { _, on in
            Reminders.enabled = on
            Task {
                let status = await Reminders.status()
                if on && status == .notDetermined { _ = await Reminders.requestPermission() }
                await refreshPermission()
                store.syncReminders()
            }
        }
        .macSheetSize()
    }

    private func refreshPermission() async {
        switch await Reminders.status() {
        case .authorized, .provisional: permission = "Allowed"
        case .denied: permission = "Off — allow them in Settings"
        case .notDetermined: permission = "Not asked yet"
        default: permission = "Limited"
        }
    }

    private func connect() {
        connecting = true
        failure = nil
        let typedKey = key.isEmpty ? (store.connection?.key ?? "") : key
        Task {
            do {
                try await store.connect(server: server, key: typedKey)
                key = ""
                if !firstRun { dismiss() }
            } catch {
                failure = error.localizedDescription
            }
            connecting = false
        }
    }
}
