# PWA day list and focus timer

The existing timeline button switches between the calendar and a compact todo list of the selected day's scheduled and unscheduled tasks. Switching views does not fetch the day again. Completion, Top Wins, editing and calendar dragging remain available.

Task timers use a square wooden countdown without milliseconds, with pause, resume, cancel and explicit Finish controls. Scheduled tasks start automatically while the planner is running. Expiry does not mark a task complete or open mandatory logging. Finish opens optional logging; Ignore closes it without writing an entry. Partial scheduled work and general task splitting use the atomic, retry-safe backend operations introduced with migration 0036.

## Floating window on Mac

Start a timer and press **Float timer** in desktop Chrome or Edge. Where Document Picture-in-Picture is supported, this opens a separate always-on-top window containing the task name, countdown and controls. The browser controls window movement and sizing. Keep the parent planner open; closing it closes the floating window. Safari cannot provide this floating window through the current API. Unsupported browsers show an explanatory message.

The countdown uses a stored deadline, so delayed browser ticks do not accumulate drift. Scheduled auto-start and tones depend on the browser continuing to run; this is not a native background alarm service. Sound can require a user interaction first. Timer ticks and view toggles make no API requests.

## Verification — 2026-10-06

- Browser fixture: compact list, task editing, manual timer, pause, optional Finish form and Ignore without a work POST.
- Automated tests: timer deadlines, timezone and 04:00 logical-day handling, overlap suppression, account-scoped restore, floating-window controls and failure handling, optional work logging, exact retry payloads, compact list actions, atomic splitting and offline shell assets.
- Actual native Chrome/Edge Picture-in-Picture on Mac remains unverified: the available verification browser is the in-app browser. Floating-window tests use a mocked browser API.

The backend split route and PWA assets must be deployed together. Migration 0036 is already applied; publishing requires fresh user approval under the repository's agent rules.
