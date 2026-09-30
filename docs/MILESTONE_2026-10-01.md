# Android feature restoration — 2026-10-01

The first APK omitted several day-planner interactions from the PWA. This
follow-up restores proportional task positions and overlap columns, hold-to-drag
scheduling with five-minute snapping and failure rollback, named Top Wins and
direct stars, inbox scheduling into the next free slot, date/week/Now navigation,
progress, native date/time pickers, and duration presets. Existing task, habit,
split-session and focus-timer behavior remains available.

The app uses a brighter wine accent (#A32C53), white backgrounds and pastel task
colors, with system/light/dark appearance. The adaptive launcher icon combines a
wine clock and mint check, including a monochrome variant for themed icons.

API failures, including HTTP 200 `success:false`, no longer appear successful.
Task mutations invalidate cached copies across dates; in-flight old reads cannot
overwrite a newer plan. Changing connection credentials cancels old timers,
alarms and workers before saving the new account. Reminder snapshots, queued
timer actions and broadcasts carry revision/connection guards. Reminder dates
respect the backend timezone, and posted alerts use collision-free task tags.
The test-notification action leaves the delivery ledger unchanged.

Split sessions preserve odd-minute budgets and normalize midnight dates once.
The existing split operation still uses multiple requests; an ambiguous network
result explicitly requires refresh before retry. An atomic split endpoint is a
separate future backend improvement.

## Build

- Package: `dev.planneros.android`.
- Version: 1.0.1, version code 2; same private debug signing identity as 1.0.0.
- APK: 17,966,956 bytes.
- SHA-256: `4422082f3b2e1fab7e42f9d905bf96cf4cb1e44ccc4ea79a786dc76963fe87d3`.
- 37 Android unit tests passed; lint: zero errors, 38 warnings.
- All 39 existing PWA JavaScript/service-worker regression tests passed.
- All 14 native reminder API tests passed.

The delivery command is `python3 scripts/deliver_android_apk.py --sha256 <hash>`.
It verifies the built APK and atomically updates both repository artifact copies
and the established Google Drive `PLANNER OS LATEST APP` directory. APKs,
credentials and signing keys remain ignored by Git.

See `ANDROID_PARITY.md` for the complete acceptance checklist and actual emulator
evidence. Physical S24 Ultra testing remains necessary for Samsung battery,
lockscreen, exact-alarm and overlay restrictions. No Android 17/One UI 9
certification is claimed.

## Existing live web/backend state

The calendar/security/PWA fixes from September 30 are deployed and the service
health endpoint still reports revision `9dbe209` before this follow-up push.
Calendar cleanup removed all 5,710 excess copies, retained all canonical mapped
events and non-Planner events, and ended with zero duplicate groups. Hourly sync
was resumed. This Android follow-up does not alter the iOS PWA or calendar sync.
