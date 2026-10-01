# Planner OS for Android

Native Kotlin / Jetpack Compose companion for the same Planner OS backend as the iOS PWA. API26 minimum (Android8), API36 target (Android16). Android17 should retain backward compatibility; the Samsung S24 Ultra still needs device validation before claiming One UI9 certification.

## Install

The generated `artifacts/Planner-OS-Android.apk` is a debug-signed, installable APK for personal use. Transfer it to the phone, open it with My Files, and allow that source to install unknown apps. This build is not a Play Store release. Keep the same signing key for future upgrades; uninstalling loses local configuration and saved days.

On first launch, enter your existing HTTPS backend origin (without `/app/`) and `PWA_ACCESS_KEY` in Settings. No server key is embedded. The key is AES-GCM encrypted with a non-exportable Android Keystore key; backups and cleartext network traffic are disabled. HTTP redirects are rejected to keep credentials from following a redirect to another host.

Use **Allow floating timer** to grant “Appear on top” in Samsung Settings. Focus still works through the foreground notification without overlay permission. Grant notification permission and, optionally, **Allow precise alarms** for exact 30/5-minute alerts. Enable **Native reminders** only if you want them on this device, and disable PWA/browser notifications on this Android phone to avoid duplicate deliveries. Your iPhone PWA reminders can stay enabled.

For Samsung background delivery, Settings → Apps → Planner OS → Battery → Unrestricted, and remove it from sleeping/deep-sleeping apps. Android force-stop prevents services, alarms, and jobs until you open the app again. Do Not Disturb, denied notification permission, offline state, and OS power management can delay notification delivery.

## Features

Version 1.0.2 (version code 4) preserves the same private signing identity for in-place upgrades. Bright wine accents sit on white backgrounds and stable pastel blocks; Settings offers system, light and dark appearance.

* Proportional, overlapping day timeline with a dotted spine, duration/end-time labels, current-time marker and active block. Hold a block to drag on a five-minute grid; move sideways while dragging to choose the previous/next date. Failed saves restore the original schedule.
* Named Top Wins chips, direct stars in timeline/inbox, completion progress, week arrows, day swipes and native date/time pickers. Today rolls at 04:00 in the workspace timezone.
* Starred-first inbox with a Schedule action that finds a gap fitting the full task duration. Presets/custom durations, category icons, recurrence and split-session metadata are retained.
* Add/edit/reschedule/delete blocks and habits; split regular blocks into sessions using the existing parent-task model.
* Scheduled blocks start their timer automatically (enabled by default). Grant **Allow precise alarms** for starts while the app is closed; foreground catch-up otherwise starts the currently active block with its original end time. Pausing or canceling suppresses that occurrence, while the next scheduled block can still start. With overlapping blocks, the most recently starting active block wins.
* Square wooden watch dial with a reverse-moving seconds hand, countdown digits, local smooth animation, and task name. Public lockscreen notification carries task name, a system countdown chronometer, and pause/cancel/finish actions; lockscreen content still follows your phone settings.
* One active countdown per task, pause/resume, overtime, task name, draggable floating overlay, notification controls and explicit confirmation before marking done.
* Stored timer survives app process loss. Monotonic time handles manual clock changes while running; a wall-time anchor recovers after reboot. Relaunch to restore the foreground timer after reboot. Force-stop cannot be bypassed.
* Task saves update locally without a global loading lock or a whole-day download. Conflicting edits serialize by task/parent; unrelated tasks remain usable. Failed writes restore only their own task. Cross-day cache copies update together, and pending snapshots are never treated as confirmed schedules.
* Fresh selected-day views are reused for 10 minutes on resume/navigation. Automatic neighboring-day prefetch is removed. Ordinary edits, stars, completion, deletion, and dragging send only their write; split/parent completion reconciles affected backend group changes. Background schedules reuse today for 30 minutes and tomorrow for six hours; successful reminder-feed polls have a 15-minute minimum interval. Animation makes no API calls. These are freshness tradeoffs for remote edits; manual refresh remains available.
* Saved day views are readable offline; timers need no network. Edits require the server and errors remain visible.
* Local 30/5-minute task alarms plus the backend's unchanged morning/evening/deadline rules through `/v2/native/reminders`. A per-device delivery ledger prevents repeated notifications on retries. WorkManager polls every15minutes; task alarms use exact alarms when the user grants permission, otherwise Android may defer them.

## Build

Use JDK17, Android SDK platform36/build-tools36.0.0 and Gradle8.11.1. AGP8.9.2 supports API36; Kotlin/Compose compiler2.1.20 with Compose BOM2025.04.01 pins reproducible dependencies.

```sh
cd android
export JAVA_HOME=/path/to/jdk17
export ANDROID_HOME=/path/to/android-sdk
./gradlew testDebugUnitTest lintDebug assembleDebug
```

This workspace retains the personal debug signing key in ignored `android/.signing/debug.keystore` so subsequent local builds can update this installation. Preserve it privately. A fresh clone without that file generates a different debug key. No SDK, account credentials, or signing keystore is committed. Android Studio can import this directory directly. For a distributable release, use a privately retained release signing key and build a signed release APK in Android Studio; do not place signing passwords in tracked files.

To deliver a verified APK from the repository root:

```sh
python3 scripts/deliver_android_apk.py --sha256 <verified-apk-sha256>
```

The delivery script verifies the APK ZIP and SHA256, then replaces the copies in `android/artifacts`, root `artifacts`, and your configured Google Drive **PLANNER OS LATEST APP** folder.

## Device validation

1. Connect, load today, switch days/weeks, inspect overlap columns and use Now. Hold and drag an ordinary block and a habit, cross midnight/date boundaries, cancel gestures, and confirm a failed save restores its time.
2. Use named Top Wins chips to reveal timeline/inbox tasks. Complete/reopen and star directly; reject a sixth star without keeping it selected. Schedule an existing inbox item into a gap fitting its full duration, then cancel a second proposal. Add/edit with native pickers and duration presets; split/delete/skip the correct item.
3. Turn off network: reopen a cached day and start a timer; edits should report a connection error.
4. Start a short focus block, switch to another app, drag the floating timer, pause/resume, lock/unlock and let it run overtime.
5. Tap Finish: Continue preserves timer; End timer stops without completing; Mark done only stops after the server confirms success.
6. Deny overlay permission and verify notification timer still works; restore overlay permission and reopen the app.
7. Enable native reminders, schedule a block40minutes away, and validate30/5-minute reminders. Edit/delete/complete it and confirm stale alarms disappear after refresh.
8. Reboot then launch the app and verify timer recovery and reminder work restoration. Test notification permission denied, battery restrictions, force-stop, and Do Not Disturb explicitly.
9. Test S24 Ultra portrait/landscape, system font scaling, gesture navigation, lockscreen and One UI background controls. Build/unit tests cannot establish these physical-device behaviors.

Split creates child sessions with compensating deletion on partial failure. A dropped network response can still make a multi-request split ambiguous; an atomic backend split endpoint is a future improvement.
