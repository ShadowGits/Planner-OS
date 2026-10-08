# PWA day list and focus timer

The existing timeline button switches between the calendar and a compact todo list of the selected day's scheduled and unscheduled tasks. Switching views does not fetch the day again. Completion, Top Wins, editing and calendar dragging remain available.

Task timers use a square countdown with a white surface, dark digits and wine progress border (with a matching dark mode) without milliseconds, with pause, resume, cancel and explicit Finish controls. Scheduled tasks start automatically while the planner is running. Expiry does not mark a task complete or open mandatory logging. Finish opens optional logging; Ignore closes it without writing an entry. Partial scheduled work and general task splitting use the atomic, retry-safe backend operations introduced with migration 0036.

## Floating window on Mac

Start a timer and press **Float timer** in desktop Chrome or Edge. Where Document Picture-in-Picture is supported, this opens a separate always-on-top window containing the task name, countdown and controls. The browser controls window movement and sizing. Keep the parent planner open; closing it closes the floating window. Safari cannot provide this floating window through the current API. Unsupported browsers show an explanatory message.

The countdown uses a stored deadline, so delayed browser ticks do not accumulate drift. Scheduled auto-start and tones depend on the browser continuing to run; this is not a native background alarm service. Sound can require a user interaction first. Timer ticks and view toggles make no API requests.

## Verification — 2026-10-06

- Browser fixture: compact list, task editing, manual timer, pause, optional Finish form and Ignore without a work POST.
- Automated tests: timer deadlines, timezone and 04:00 logical-day handling, overlap suppression, account-scoped restore, floating-window controls and failure handling, optional work logging, exact retry payloads, compact list actions, atomic splitting and offline shell assets.
- Actual native Chrome/Edge Picture-in-Picture on Mac remains unverified: the available verification browser is the in-app browser. Floating-window tests use a mocked browser API.

The backend split route and PWA assets were deployed together in `c212a4f`; migration 0036 was verified live. Production was later verified at `f28645e`, including compact headers and task-first system notification text. The notification diagnostics and white timer described here are a subsequent local change pending publication approval. Each push/deploy requires fresh user approval under the repository rules.

## Browser notification diagnostics

The reminder scheduler runs every five minutes. Browser permission and a local PushSubscription alone are insufficient: the PWA marks its bell enabled only after registering that subscription with the backend. A failed registration offers reconnect instead. Each installation stores a random stable `day-planner-push-device` ID; user-agent strings alone must not identify devices because multiple profiles can share them. The existing backend replacement logic matches the resulting unique device label when endpoints rotate.

Enabling notifications sends a test to the current subscription only (`POST /v2/day/push/test` with its endpoint). The server filters by configured user, active workspace and endpoint; accepting another provider URL cannot send to someone else's subscription. Legacy callers without an endpoint retain the all-device behavior. Zero successful sends and request failures are visible instead of being silently ignored. Provider acceptance still does not prove that the OS displayed a banner. Check the installed browser/web app's permission, macOS Notifications settings and Focus rules when a test is accepted but absent.

Useful platform references: [Chrome notifications](https://support.google.com/chrome/answer/3220216), [Safari web app notifications](https://support.apple.com/en-au/104996), and [macOS Focus](https://support.apple.com/en-gb/guide/mac-help/mchl613dc43f/26/mac/26).
