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
    @State private var confirmingDelete = false
    @State private var loaded = false
    /// The fields as they opened, so saving sends only what was changed.
    @State private var opened: EditorFields?

    private static let durations = [5, 10, 15, 20, 25, 30, 45, 60, 75, 90, 120, 150, 180, 240]
    private var existing: PlannerTask? { request.task }
    private var durationOptions: [Int] { Array(Set(Self.durations + [existing?.minutes ?? 30])).sorted() }
    private var canSave: Bool { !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        Form {
            if existing == nil, let slot = request.pendingSlot {
                Section {
                    NavigationLink {
                        PendingTaskPicker(slot: slot, onFitted: { dismiss() })
                    } label: {
                        Label("Fit previous pending here", systemImage: "tray.and.arrow.down")
                    }
                    .accessibilityIdentifier("fit-previous-pending")
                } header: {
                    Text("\(Self.durationLabel(slot.minutes)) free · \(Civil.clockText(slot.start, twentyFour: Civil.prefers24Hour))–\(Civil.clockText(slot.end, twentyFour: Civil.prefers24Hour))")
                } footer: {
                    Text("Choose an unfinished task, or add a new task below.")
                }
            }
            Section {
                TextField("What needs doing?", text: $title)
                Toggle(isOn: $starred) { Label("Top win", systemImage: "star") }
            } footer: {
                if existing?.habit == true { Text("This is a habit: a new name renames it on every day.") }
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
            // A habit keeps no notes (the server has nowhere to put them), so it does not offer them.
            if existing?.habit != true {
                Section("Notes") {
                    TextField("Notes", text: $notes, axis: .vertical).lineLimit(3...10)
                }
            }
            if let task = existing {
                Section {
                    Button(task.done ? "Reopen" : "Mark done") { save(done: !task.done) }
                    Button(task.habit ? "Skip this day" : "Delete", role: .destructive) { confirmingDelete = true }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle(existing == nil ? "New task" : "Edit task")
        .inlineTitle()
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button(existing == nil ? "Add" : "Save") { save(done: nil) }.disabled(!canSave)
            }
        }
        .confirmationDialog(existing?.habit == true ? "Skip this day of the habit?" : "Delete this task?",
                            isPresented: $confirmingDelete, titleVisibility: .visible) {
            Button(existing?.habit == true ? "Skip" : "Delete", role: .destructive) { remove() }
        } message: {
            Text(existing?.habit == true ? "Only this day goes; the habit carries on every other day."
                 : "This removes it for good. Drop it from Focus instead to keep it as skipped.")
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
            // An evening's 25:30 is 01:30 on the task's own (next) date.
            time = Civil.instant(day, task.time == nil ? "09:00" : Civil.clock(task.clockMinutes), in: zone) ?? Date()
            minutes = task.minutes
            notes = task.notes ?? ""
            starred = task.starred
            opened = fields(title: title, hasDate: hasDate, date: date, hasTime: hasTime, time: time,
                            minutes: minutes, notes: notes, starred: starred)
        } else {
            let day = request.date ?? store.logicalToday
            let nextHalfHour = Civil.clock((store.moment.minutes / 30 + 1) * 30)
            hasDate = true
            date = Civil.pickerDate(day, in: zone)
            hasTime = request.time != nil
            time = Civil.instant(day, request.time ?? nextHalfHour, in: zone) ?? Date()
        }
    }

    /// The editor's fields as plain values, read the same way when it opens and when it saves.
    private func fields(title: String, hasDate: Bool, date: Date, hasTime: Bool, time: Date,
                        minutes: Int, notes: String, starred: Bool) -> EditorFields {
        let zone = store.timeZone
        return EditorFields(title: title,
                            date: hasDate ? Civil.iso(date, in: zone) : nil,
                            time: hasDate && hasTime ? Civil.clock(Civil.minutesOfDay(time, in: zone)) : nil,
                            minutes: minutes, notes: notes, starred: starred)
    }

    private func save(done: Bool?) {
        let zone = store.timeZone
        let cleanTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        let day = hasDate ? Civil.iso(date, in: zone) : nil
        let clock = hasDate && hasTime ? Civil.clock(Civil.minutesOfDay(time, in: zone)) : nil
        let now = fields(title: title, hasDate: hasDate, date: date, hasTime: hasTime, time: time,
                         minutes: minutes, notes: notes, starred: starred)
        let start = opened
        // Close now: the change shows on screen straight away and saves in the
        // background. If the server refuses it, it is undone with a message.
        dismiss()
        Task {
            if let task = existing {
                // Only what was changed: a rename saves the name and nothing else.
                var edited = editedTask(task, from: start ?? now, to: now)
                if let done { edited.done = done }
                await store.update(task, to: edited)
            } else {
                await store.create(title: cleanTitle, date: day, time: clock, minutes: minutes,
                                   notes: cleanNotes, starred: starred)
            }
        }
    }

    private func remove() {
        guard let task = existing else { return }
        dismiss()
        Task { await store.delete(task) }
    }
}

/// The same picker on iPhone, iPad and Mac. Selecting a card moves its task;
/// navigating back or cancelling leaves both the task and the new-task draft alone.
@MainActor
private struct PendingTaskPicker: View {
    @Environment(PlannerStore.self) private var store
    let slot: PendingSlot
    let onFitted: () -> Void
    @State private var tasks: [PlannerTask] = []
    @State private var loading = true
    @State private var saving: String?
    @State private var error: String?
    @State private var query = ""

    private var matching: [PlannerTask] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return needle.isEmpty ? tasks : tasks.filter { $0.title.localizedCaseInsensitiveContains(needle) }
    }

    var body: some View {
        List {
            Section {
                Label("\(Civil.short(slot.target.date)) · \(Civil.clockText(slot.start, twentyFour: Civil.prefers24Hour))", systemImage: "calendar")
                Text("\(TaskEditor.durationLabel(slot.minutes)) available. Choose a task to move here.")
                    .font(.callout).foregroundStyle(.secondary)
                TextField("Search pending tasks", text: $query)
                    .accessibilityIdentifier("pending-task-search")
            }
            if let error {
                Section {
                    Text(error).foregroundStyle(.red).accessibilityIdentifier("pending-task-error")
                    Button("Refresh pending tasks") { Task { await load() } }
                        .disabled(loading || saving != nil)
                }
            }
            if loading {
                ProgressView("Loading pending tasks…")
            } else if matching.isEmpty {
                Text(tasks.isEmpty ? "No previous pending tasks. Go back to add a new task." : "No tasks match your search.")
                    .foregroundStyle(.secondary)
            } else {
                Section("Fits this gap") {
                    let fitting = matching.filter { slot.fits($0) }
                    if fitting.isEmpty { Text("No pending tasks fit this gap.").foregroundStyle(.secondary) }
                    ForEach(fitting) { task in card(task) }
                }
                let longer = matching.filter { !slot.fits($0) }
                if !longer.isEmpty {
                    Section("Needs a larger gap") {
                        ForEach(longer) { task in card(task) }
                    }
                }
            }
        }
        .navigationTitle("Previous pending")
        .inlineTitle()
        .navigationBarBackButtonHidden(saving != nil)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel", action: onFitted).disabled(saving != nil)
            }
        }
        .interactiveDismissDisabled(saving != nil)
        .task { await load() }
        .macSheetSize()
    }

    private func card(_ task: PlannerTask) -> some View {
        Button {
            saving = task.id
            error = nil
            Task {
                do {
                    try await store.fitPending(task, into: slot)
                    onFitted()
                } catch {
                    self.error = error.localizedDescription
                }
                saving = nil
            }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: task.starred ? "star.fill" : "arrow.down.to.line")
                    .foregroundStyle(Palette.accent)
                VStack(alignment: .leading, spacing: 5) {
                    Text(task.title).font(.body.weight(.semibold)).foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(originalDate(task)).font(.caption).foregroundStyle(.secondary)
                    if let context = store.context(task) {
                        Text(context).font(.caption).foregroundStyle(.secondary)
                    }
                    if !slot.fits(task) {
                        Text("Needs \(TaskEditor.durationLabel(task.minutes - slot.minutes)) more")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 4)
                if saving == task.id { ProgressView() }
                else { Text(TaskEditor.durationLabel(task.minutes)).font(.callout.monospacedDigit()).foregroundStyle(.primary) }
            }
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.hitArea)
        .disabled(!slot.fits(task) || saving != nil || loading)
        .accessibilityIdentifier("pending-task-\(task.id)")
    }

    private func originalDate(_ task: PlannerTask) -> String {
        if let date = task.date {
            return "Planned \(Civil.short(date))" + (task.time == nil ? " · No time" : " · \(Civil.clockText(task.clockMinutes, twentyFour: Civil.prefers24Hour))")
        }
        if let due = task.dueDate { return "Unscheduled · Due \(Civil.short(due))" }
        return "Unscheduled · No date"
    }

    private func load() async {
        loading = true
        error = nil
        do { tasks = try await store.pendingTasks(for: slot) }
        catch { self.error = error.localizedDescription }
        loading = false
    }
}
