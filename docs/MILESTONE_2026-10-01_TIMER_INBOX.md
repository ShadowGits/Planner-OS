# Android 1.0.3 — timer sounds, wooden lock-screen dial and overdue Inbox

The Android timer now has distinct original start and completion chimes. Its floating wooden face is smaller (180×190dp), with brown wood, a cream face and a thicker 4dp shrinking track. The in-app countdown bar is brown and 5dp thick. Digits show whole seconds; the perimeter animates locally without network calls.

Completion is claimed and persisted once, including after process recovery. Pause, resume, metadata updates and cancel do not replay start/completion tones. Replacing a block at its ending boundary claims the old completion before starting the new block. Existing reminder channels and timing are unchanged; sound respects system notification permissions, channel settings, volume and Do Not Disturb.

The public ongoing timer notification no longer uses Android's silent notification group, requests immediate foreground display, and requests Android 16 Live Update promotion with the manifest permission. Tapping it opens a private wooden timer Activity above the keyguard, with task name, countdown, Pause/Resume and Cancel. Opening the normal planner requires unlocking. This is a user-opened timer window, not an automatic overlay above the secure lock screen; Samsung notification/privacy settings and OEM Live Update support still govern the visible lock-screen entry. Physical S24 Ultra verification remains necessary.

Inbox now includes open past scheduled tasks, elapsed blocks today and overdue deadlines, retaining original timeline dates/times. Current-day habit occurrences merge locally; historic habit occurrences are not generated. Completed overdue blocks disappear from global Inbox. Tasks can still be edited, completed, starred, scheduled, split or deleted. The editor/split date uses the task's original calendar date for backlog rows.

The new authenticated `/v2/day/inbox` and MCP `core_inbox_view` retain tenant/workspace scope, paginate every transport page, exclude split umbrellas and project only required fields. Calendar/day/reminder behavior remains unchanged. Android fetches the feed when Inbox opens, caches it separately for ten minutes and projects writes/rollbacks into both caches. Ordinary Inbox writes and returning to its tab require no whole-day or backlog download. A new calendar date refreshes the feed. Structural split/parent changes reconcile explicitly.

Validation: 271 Python tests passed, one skipped; 39 PWA tests passed; 65 Android unit tests passed. APK assembly and lint passed (zero errors). Emulator Inbox verification confirmed original overdue slots, correct completion, omission of future tasks and zero extra day/Inbox GET after edits or a tab return. Timer event and lock-screen view verification is recorded with ignored artifacts. The personal debug signing identity is unchanged.

APK version 1.0.3, versionCode 5. SHA-256: `693ec54a9ac0d9bcdbcb9ae7b8b578cb1bf806d71cedf3ddc7fc7bcd90bee21d`.

The deliver script puts the installable APK in the established Google Drive `PLANNER OS LATEST APP/Planner-OS-Android.apk` folder, plus local artifact copies. Install over the existing version; do not uninstall to preserve connection/cache settings.

## 1.0.4 minimize follow-up

Floating timer now has separate Minimize/Expand and Hide controls. The compact pill retains task name and whole-second countdown; the service, sounds and lock-screen timer continue running. Minimized preference survives service recovery. VersionCode6, version1.0.4, SHA256 `6687d47b6beb894e0039d1269ee06a9a15c6717a1df12677abaf88bc4679b298`. Final Android test/lint/assembly checks passed (65 tests, zero lint errors). The wooden activity was verified over a temporary emulator PIN lock with Pause/Resume, and completion sound event was verified at the end of a real one-minute timer. The live authenticated Inbox endpoint returned HTTP200 on revision9b01d38.
