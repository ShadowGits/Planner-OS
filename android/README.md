# Planner OS for Android

Native Kotlin / Jetpack Compose companion for the same Planner OS backend as the iOS PWA. API26 minimum (Android8), API36 target (Android16). Android17 should retain backward compatibility; the Samsung S24 Ultra still needs device validation before claiming One UI9 certification.

## Install

The generated `artifacts/Planner-OS-Android.apk` is a debug-signed, installable APK for personal use. Transfer it to the phone, open it with My Files, and allow that source to install unknown apps. This build is not a Play Store release. Keep the same signing key for future upgrades; uninstalling loses local configuration and saved days.

On first launch, enter your existing HTTPS backend origin (without `/app/`) and `PWA_ACCESS_KEY` in Settings. No server key is embedded. The key is AES-GCM encrypted with a non-exportable Android Keystore key; backups and cleartext network traffic are disabled. HTTP redirects are rejected to keep credentials from following a redirect to another host.

Use **Allow floating timer** to grant “Appear on top” in Samsung Settings. Focus still works through the foreground notification without overlay permission. Grant notification permission and, optionally, **Allow precise reminders** for exact 30/5-minute alerts. Enable **Native reminders** only if you want them on this device, and disable PWA/browser notifications on this Android phone to avoid duplicate deliveries. Your iPhone PWA reminders can stay enabled.

For Samsung background delivery, Settings → Apps → Planner OS → Battery → Unrestricted, and remove it from sleeping/deep-sleeping apps. Android force-stop prevents services, alarms, and jobs until you open the app again. Do Not Disturb, denied notification permission, offline state, and OS power management can delay notification delivery.

## Features

* Soft pastel day timeline, week strip, swipe days, date navigation, per-day inbox, completion and starred priorities.
* Add/edit/reschedule/delete blocks and habits; split regular blocks into sessions using the existing parent-task model.
* One active countdown per task, pause/resume, overtime, task name, draggable floating overlay, notification controls and explicit confirmation before marking done.
* Stored timer survives app process loss. Monotonic time handles manual clock changes while running; a wall-time anchor recovers after reboot. Relaunch to restore the foreground timer after reboot. Force-stop cannot be bypassed.
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

## Device validation

1. Connect, load today, switch days, use inbox, add a block, edit its time, complete/reopen, star, split and delete.
2. Turn off network: reopen a cached day and start a timer; edits should report a connection error.
3. Start a short focus block, switch to another app, drag the floating timer, pause/resume, lock/unlock and let it run overtime.
4. Tap Finish: Continue preserves timer; End timer stops without completing; Mark done only stops after the server confirms success.
5. Deny overlay permission and verify notification timer still works; restore overlay permission and reopen the app.
6. Enable native reminders, schedule a block40minutes away, and validate30/5-minute reminders. Edit/delete/complete it and confirm stale alarms disappear after refresh.
7. Reboot then launch the app and verify timer recovery and reminder work restoration. Test notification permission denied, battery restrictions, force-stop, and Do Not Disturb explicitly.
8. Test S24 Ultra portrait/landscape, system font scaling, gesture navigation, lockscreen and One UI background controls. Build/unit tests cannot establish these physical-device behaviors.

Split creates child sessions with compensating deletion on partial failure. A dropped network response can still make a multi-request split ambiguous; an atomic backend split endpoint is a future improvement.
