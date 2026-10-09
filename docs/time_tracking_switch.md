# Timers and time logging switch

PWA: tap the settings gear beside the view toggle. Android: open Settings. Turn **Timers & time logging** off.

The setting applies immediately and is saved independently on each device/browser. Off stops the active timer, closes floating timers, cancels native scheduled timer alarms, and hides timer actions, work-history labels, manual time entry, completion prompts, and timer notifications. Task completion, scheduling, splitting and ordinary task reminders remain available. Saved work logs and explicitly submitted retry entries are retained.

Turning the switch back on restores the controls and future automatic timers, retaining the Android automatic-focus preference. The current scheduled occurrence stays stopped. Stale service intents, notification taps, browser state events and late floating-window responses cannot restore tracking while off.

No database migration is needed.

Validation on 2026-10-09: 85 Android unit tests passed, lint completed with zero errors, APK 1.0.15/code17 built and its existing signing certificate verified. 89 PWA tests passed against the clean release snapshot; the additional separate Day Recovery tests also pass in the working checkout (92 total). Mobile settings preview verified at 360px width.

APK SHA256: `27ffb8d9d9c624c8bba5ef24fc409694c806653dbab9a8370543bd3c69514868`.

The APK is prepared locally in `artifacts`. PWA publishing and delivery to the synced latest-app folder await fresh user release approval under `.agents/AGENTS.md`.
