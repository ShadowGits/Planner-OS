import SwiftUI

/// Persistent across the main screens and every selected day.
@MainActor
struct ASAPStrip: View {
    @Environment(PlannerStore.self) private var store
    @State private var adding = false
    @State private var title = ""
    @State private var saving = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Label("ASAP", systemImage: "exclamationmark.circle.fill")
                    .font(.headline).foregroundStyle(.orange)
                Spacer()
                Button { Task { await store.connectAppleASAP() } } label: {
                    Image(systemName: "list.bullet.clipboard")
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.hitArea)
                .accessibilityLabel("Connect ASAP to Apple Reminders")
                Button { adding = true } label: { Label("Add ASAP", systemImage: "plus") }
                    .buttonStyle(.hitArea).disabled(saving)
            }
            if let items = store.inbox?.asapItems, !items.isEmpty {
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(items) { task in
                            HStack(spacing: 8) {
                                Text(task.title).font(.subheadline.weight(.semibold)).lineLimit(2)
                                Button { Task { await store.setDone(task, true) } } label: {
                                    Image(systemName: "checkmark.circle")
                                        .frame(width: 36, height: 36)
                                }
                                .buttonStyle(.hitArea)
                                .disabled(store.busy.contains(task.id))
                                .accessibilityLabel("Close ASAP: \(task.title)")
                            }
                            .padding(.leading, 12)
                            .background(.orange.opacity(0.15), in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }.scrollIndicators(.never)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .background(.orange.opacity(0.06))
        .accessibilityIdentifier("asap-strip")
        .alert("Add ASAP", isPresented: $adding) {
            TextField("What needs doing?", text: $title)
            Button("Add") {
                let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !name.isEmpty else { return }
                saving = true
                Task {
                    if await store.addASAP(name) { title = "" }
                    saving = false
                }
            }
            Button("Cancel", role: .cancel) { }
        } message: { Text("Stays at the top until closed. Reminds you every four hours.") }
    }
}
