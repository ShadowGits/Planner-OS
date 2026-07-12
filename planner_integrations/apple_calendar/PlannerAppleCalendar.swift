import EventKit
import Foundation

let store = EKEventStore()
let arguments = Array(CommandLine.arguments.dropFirst())

func optionValue(_ name: String) -> String? {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
        return nil
    }
    return arguments[index + 1]
}

let responseFilePath = optionValue("--response-file")

func output(_ success: Bool, data: [String: Any] = [:], errors: [String] = []) -> Never {
    let result: [String: Any] = ["success": success, "data": data, "errors": errors]
    var encoded = try! JSONSerialization.data(withJSONObject: result)
    encoded.append("\n".data(using: .utf8)!)
    if let responseFilePath {
        try? encoded.write(to: URL(fileURLWithPath: responseFilePath), options: .atomic)
    } else {
        FileHandle.standardOutput.write(encoded)
    }
    exit(success ? 0 : 2)
}

func isoDate(_ value: Any?) -> Date? {
    guard let text = value as? String else { return nil }
    return ISO8601DateFormatter().date(from: text)
}

func eventData(_ event: EKEvent) -> [String: Any] {
    return [
        "external_id": event.eventIdentifier ?? "",
        "calendar_id": event.calendar.calendarIdentifier,
        "title": event.title ?? "",
        "start": ISO8601DateFormatter().string(from: event.startDate),
        "end": ISO8601DateFormatter().string(from: event.endDate),
        "notes": event.notes ?? "",
        "location": event.location ?? "",
        "all_day": event.isAllDay
    ]
}

let stdinInput = FileHandle.standardInput.readDataToEndOfFile()
let input: Data
if let requestFilePath = optionValue("--request-file"),
   let requestFileInput = try? Data(contentsOf: URL(fileURLWithPath: requestFilePath)) {
    input = requestFileInput
} else if stdinInput.isEmpty, let inlineRequest = arguments.first, !inlineRequest.hasPrefix("--") {
    input = Data(inlineRequest.utf8)
} else {
    input = stdinInput
}
guard let request = try? JSONSerialization.jsonObject(with: input) as? [String: Any],
      let operation = request["operation"] as? String else {
    output(false, errors: ["Invalid JSON request"])
}

var authorization = EKEventStore.authorizationStatus(for: .event)
if operation == "permission_status" {
    let permission: String
    switch authorization {
    case .notDetermined:
        permission = "not_determined"
    case .restricted:
        permission = "restricted"
    case .denied:
        permission = "denied"
    case .fullAccess:
        permission = "full_access"
    case .writeOnly:
        permission = "write_only"
    case .authorized:
        permission = "authorized"
    @unknown default:
        permission = "unknown"
    }
    output(true, data: ["permission": permission])
}

if authorization == .notDetermined {
    let semaphore = DispatchSemaphore(value: 0)
    var granted = false
    var requestError: Error?
    if #available(macOS 14.0, *) {
        store.requestFullAccessToEvents { ok, error in
            granted = ok
            requestError = error
            semaphore.signal()
        }
    } else {
        store.requestAccess(to: .event) { ok, error in
            granted = ok
            requestError = error
            semaphore.signal()
        }
    }
    _ = semaphore.wait(timeout: .now() + 30)
    if !granted {
        let message = requestError?.localizedDescription ?? "Calendar permission was not granted. Open System Settings > Privacy & Security > Calendars."
        output(false, errors: [message])
    }
    authorization = EKEventStore.authorizationStatus(for: .event)
}

guard authorization == .authorized || authorization == .fullAccess || authorization == .writeOnly else {
    output(false, errors: ["Calendar permission is not granted. Open System Settings > Privacy & Security > Calendars."])
}

let calendarID = request["calendar_id"] as? String
func selectedCalendar() -> EKCalendar? {
    if let id = calendarID { return store.calendar(withIdentifier: id) }
    return store.defaultCalendarForNewEvents
}

switch operation {
case "list_calendars":
    let values = store.calendars(for: .event).map { ["id": $0.calendarIdentifier, "title": $0.title, "writable": $0.allowsContentModifications] as [String: Any] }
    output(true, data: ["calendars": values])
case "create_calendar":
    let calendar = EKCalendar(for: .event, eventStore: store)
    calendar.title = request["title"] as? String ?? "Planner OS"
    calendar.source = store.defaultCalendarForNewEvents?.source ?? store.sources.first(where: { $0.sourceType == .local })
    do { try store.saveCalendar(calendar, commit: true); output(true, data: ["id": calendar.calendarIdentifier, "title": calendar.title]) }
    catch { output(false, errors: [error.localizedDescription]) }
case "create_event":
    guard let values = request["event"] as? [String: Any], let calendar = selectedCalendar(), let start = isoDate(values["start"]), let end = isoDate(values["end"]) else { output(false, errors: ["Missing calendar/start/end"])}
    let event = EKEvent(eventStore: store); event.calendar = calendar; event.title = values["title"] as? String ?? ""; event.startDate = start; event.endDate = end; event.notes = values["notes"] as? String; event.location = values["location"] as? String; event.isAllDay = values["all_day"] as? Bool ?? false
    do { try store.save(event, span: .thisEvent, commit: true); output(true, data: eventData(event)) }
    catch { output(false, errors: [error.localizedDescription]) }
case "read_event":
    guard let id = request["external_id"] as? String, let event = store.event(withIdentifier: id) else { output(false, errors: ["Event not found"])}
    output(true, data: eventData(event))
case "update_event":
    guard let id = request["external_id"] as? String, let event = store.event(withIdentifier: id), let values = request["event"] as? [String: Any] else { output(false, errors: ["Event not found"])}
    if let value = values["title"] as? String { event.title = value }; if let value = isoDate(values["start"]) { event.startDate = value }; if let value = isoDate(values["end"]) { event.endDate = value }; if let value = values["notes"] as? String { event.notes = value }
    do { try store.save(event, span: .thisEvent, commit: true); output(true, data: eventData(event)) }
    catch { output(false, errors: [error.localizedDescription]) }
case "delete_event":
    guard let id = request["external_id"] as? String, let event = store.event(withIdentifier: id) else { output(false, errors: ["Event not found"])}
    let scope = request["delete_scope"] as? String ?? "single"; let span: EKSpan = scope == "future" || scope == "series" ? .futureEvents : .thisEvent
    do { try store.remove(event, span: span, commit: true); output(true) }
    catch { output(false, errors: [error.localizedDescription]) }
case "list_events":
    guard let start = isoDate(request["start"]), let end = isoDate(request["end"]), let calendar = selectedCalendar() else { output(false, errors: ["Missing calendar/start/end"])}
    let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: [calendar])).map(eventData)
    output(true, data: ["events": events])
default:
    output(false, errors: ["Unsupported operation: \(operation)"])
}
