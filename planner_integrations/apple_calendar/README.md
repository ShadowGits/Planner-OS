# Apple Calendar Integration

Planner OS uses a small local Swift/EventKit helper. It communicates using one
JSON request on stdin and one JSON response on stdout. It does not automate the
Calendar UI or use private frameworks.

Build it once:

```sh
mkdir -p .planner-os/bin/PlannerAppleCalendar.app/Contents/MacOS
swiftc -target arm64-apple-macosx14.0 \
  planner_integrations/apple_calendar/PlannerAppleCalendar.swift \
  -o .planner-os/bin/PlannerAppleCalendar.app/Contents/MacOS/planner-apple-calendar
codesign --force --sign - .planner-os/bin/PlannerAppleCalendar.app
```

The app bundle must include `NSCalendarsFullAccessUsageDescription` in its
`Contents/Info.plist`; macOS does not reliably register a bare command-line
executable in Calendar privacy settings.

Planner OS launches the bundle through macOS and exchanges request/response
JSON through private temporary files. Direct JSON-over-stdin remains available
for tests and development helpers.

Then grant access at **System Settings > Privacy & Security > Calendars** for
Terminal (or the application running Planner OS). Status calls never trigger a
permission prompt or wait for one. If permission is denied, commands fail with
the exact System Settings path.

Use `shadow apple-calendar calendars` to find a writable calendar identifier,
then store it with `shadow preferences update apple_calendar.calendar_id ID`.
Planner OS can also request creation of a dedicated `Planner OS` calendar.

The helper supports list calendars, create/read/update/delete event, and range
listing. Unit tests inject a deterministic fake and never access EventKit.
