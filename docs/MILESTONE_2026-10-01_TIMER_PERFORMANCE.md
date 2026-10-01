# Android 1.0.2: immediate saves and automatic focus

The previous native build refreshed a day after ordinary writes and serialized
unrelated edits behind one busy flag. This release updates affected tasks locally,
serializes only conflicting task/parent writes, and rolls back only failed rows.
The rest of the day remains usable during slow saves. Cached cross-day and
after-midnight copies receive the same diff; pending snapshots are never treated
as confirmed alarm data, including after process loss.

Ordinary edit, drag, star, completion and delete operations send their write
without a follow-up day GET. Split and parent completion still reconcile backend
propagation. Navigation/resume reuse fresh selected-day caches for ten minutes.
Automatic six-neighbor prefetch is removed. Background workers reuse today for
30 minutes and tomorrow for six hours, and successful reminder feeds are polled
no more often than every 15 minutes. Manual refresh remains available. Changes
made from another device can wait until these freshness windows expire.

Scheduled timers are enabled by default. Exact alarms start known blocks while
the app is in the background; foreground catch-up retains the scheduled end
instead of restarting the full duration. Latest-starting active blocks win
an overlap. A persisted per-occurrence ledger keeps paused/canceled blocks
stopped while allowing the next scheduled occurrence to start. Manual starts,
credentials, reminder revisions and queued service requests retain their guards.

The floating timer has a square wooden watch case, decreasing perimeter progress,
reverse seconds sweep and countdown/centiseconds. Its static wooden face is
rendered once and reused; animation interpolates monotonic time locally without
network calls or state writes. The foreground notification exposes task name,
a public lockscreen countdown chronometer, and pause/cancel/finish actions.
The timer uses a default-importance channel without sound or vibration so it
can appear on the lockscreen; explicit old user channel restrictions carry
forward. Appearance and lockscreen content remain subject to phone settings.
See [Android notification importance](https://developer.android.com/reference/android/app/NotificationManager#IMPORTANCE_DEFAULT).

Backend day and habit queries now select only required display columns, preserving
notes, stars, split context and overnight tasks. Tasks due today but scheduled on
another day are excluded before transfer. Habit completion/override mutations
read only the selected occurrence, and failed lookups abort writes rather than
creating duplicates. These queries remain tenant-scoped.

## Validation

- 262 backend tests passed; one existing integration test skipped.
- 39 PWA JavaScript/service-worker tests passed.
- 52 Android unit tests passed; lint: zero errors, 60 warnings.
- Android 16 emulator: a delayed eight-second failing completion did not block
  another task's successful completion. Rollback retained the other completion.
  Two PATCH requests produced zero additional day GETs; returning from Home also
  produced zero additional day GETs.
- Android 16 emulator: a scheduled block started with the app backgrounded.
  Notification diagnostics verified public visibility, task title, system
  countdown chronometer and all three actions. Pause retained elapsed time;
  cancel left the task incomplete and foreground catch-up did not restart it.
  The next block started automatically in the background after cancellation,
  with zero extra day GETs across the entire sequence. A separate PIN-locked
  screen render verified the task name and running timer; the old low-importance
  channel hid it, so the timer now has a quiet default-importance channel.
- Synthetic rows with 100 KB metadata verify metadata exclusion, visible-day
  filtering, and bounded occurrence reads across 200 days of history.

The emulator originally resynchronized its clock during a short scheduling test;
its clock was stabilized before rerunning. No physical S24 Ultra/One UI testing
or force-stop bypass is claimed. Grant **Allow precise alarms**, notification
permission and **Allow floating timer** for the requested background experience.

## Artifact

- Package `dev.planneros.android`, version 1.0.2, version code 4.
- 17,763,971 bytes; retains the existing install's private debug signer.
- APK SHA-256: `dd6336e1510be212861b8887dee4f39141ea69c47234afb4ca326c1e6d098840`.
- Deliver with `scripts/deliver_android_apk.py --sha256 <verified-hash>` to the
  established Google Drive `PLANNER OS LATEST APP` directory and local copies.

APKs, fixture screenshots, credentials and signing material remain ignored.
