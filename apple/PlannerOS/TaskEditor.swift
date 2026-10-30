import SwiftUI

/// Add a task, or edit, finish or delete one.
@MainActor
struct TaskEditor: View {
    @Environment(PlannerStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let request: EditorRequest

    @State private var title = ""
    @State private var hasDate = true
    @State private var date = Date()
    @State private var hasTime = false
    @State private var time = Date()
    @State private var minutes = 30
    @State private var notes = ""
    @State private var starred = false
    @State private var saving = false
    @State private var confirmingDelete = false
    @State private var loaded = false

    private static let durations = [5, 10, 15, 20, 25, 30, 45, 60, 75, 90, 120, 150, 180, 240]
    private var existing: PlannerTask? { request.task }
    private var durationOptions: [Int] { Array(Set(Self.durations + [existing?.minutes ?? 30])).sorted() }
    private var canSave: Bool { !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !saving }

    var body: some View {
        Form {
            Section {
                TextField("What needs doing?", text: $title)
                Toggle(isOn: $starred) { Label("Top win", systemImage: "star") }
            }
            Section("When") {
                Toggle("On a day", isOn: $hasDate.animation())
                if hasDate {
                    DatePicker("Day", selection: $date, displayedComponents: .date)
                    Toggle("At a time", isOn: $hasTime.animation())
                    if hasTime {
                        DatePicker("Starts", selection: $time, displayedComponents: .hourAndMinute)
                    }
                }
                Picker("Duration", selection: $minutes) {
                    ForEach(durationOptions, id: \.self) { Text(Self.durationLabel($0)).tag($0) }
                }
            }
            Section("Notes") {
                TextField("Notes", text: $notes, axis: .vertical).lineLimit(3...10)
            }
            if let task = existing {
                Section {
                    Button(task.done ? "Reopen" : "Mark done") { save(done: !task.done) }
                    Button("Delete", role: .destructive) { confirmingDelete = true }
                }
            }
        }
        .formStyle(.grouped)
        .disabled(saving)
        .navigationTitle(existing == nil ? "New task" : "Edit task")
        .inlineTitle()
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button(existing == nil ? "Add" : "Save") { save(done: nil) }.disabled(!canSave)
            }
        }
        .confirmationDialog("Delete this task?", isPresented: $confirmingDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { remove() }
        } message: {
            Text("This removes it for good. Drop it from Focus instead to keep it as skipped.")
        }
        .environment(\.timeZone, store.timeZone)
        .onAppear(perform: load)
        .macSheetSize()
    }

    static func durationLabel(_ minutes: Int) -> String {
        if minutes < 60 { return "\(minutes) min" }
        return minutes % 60 == 0 ? "\(minutes / 60) h" : "\(minutes / 60) h \(minutes % 60) min"
    }

    private func load() {
        guard !loaded else { return }
        loaded = true
        let zone = store.timeZone
        if let task = existing {
            let day = task.date ?? store.logicalToday
            title = task.title
            hasDate = task.date != nil
            date = Civil.pickerDate(day, in: zone)
            hasTime = task.time != nil
            time = Civil.instant(day, task.time ?? "09:00", in: zone) ?? Date()
            minutes = task.minutes
            notes = task.notes ?? ""
            starred = task.starred
        } else {
            let day = request.date ?? store.logicalToday
            let nextHalfHour = Civil.clock((store.moment.minutes / 30 + 1) * 30)
            hasDate = true
            date = Civil.pickerDate(day, in: zone)
            hasTime = request.time != nil
            time = Civil.instant(day, request.time ?? nextHalfHour, in: zone) ?? Date()
        }
    }

    private func save(done: Bool?) {
        let zone = store.timeZone
        let cleanTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        let day = hasDate ? Civil.iso(date, in: zone) : nil
        let clock = hasDate && hasTime ? Civil.clock(Civil.minutesOfDay(time, in: zone)) : nil
        saving = true
        Task {
            let saved: Bool
            if let task = existing {
                var edited = task
                edited.title = cleanTitle.isEmpty ? task.title : cleanTitle
                edited.date = day
                edited.time = clock
                edited.minutes = minutes
                edited.notes = cleanNotes.isEmpty ? nil : cleanNotes
                edited.starred = starred
                if let done { edited.done = done }
                saved = await store.update(task, to: edited)
            } else {
                saved = await store.create(title: cleanTitle, date: day, time: clock, minutes: minutes,
                                           notes: cleanNotes, starred: starred)
            }
            saving = false
            if saved { dismiss() }
        }
    }

    private func remove() {
        guard let task = existing else { return }
        saving = true
        Task {
            let removed = await store.delete(task)
            saving = false
            if removed { dismiss() }
        }
    }
}
