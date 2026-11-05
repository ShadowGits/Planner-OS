# Planner OS for iPhone, iPad and Mac

One SwiftUI app for all three, built from Xcode with a free Apple account.
It talks to the same backend as Android, with the same app key.

* **Timeline** (opens first), matching Structured as measured in `docs/structured-ux.md`:
  * "16. October 2025 ›" on top, the week strip with each day's task colours under it, untimed tasks as round chips.
  * Time runs down the page at 1.6 pt a minute. Capsules ahead of now are pale with a coloured icon; the one under way fills with colour down to now and says "28m remaining"; passed and done ones are solid. The line is coloured up to now, and a very subtle now bar runs across the timeline with the current time in bold on the left.
  * Free time reads "You'll have 30m free. Anything you'd like to fit in?"; a long stretch offers "Add Task".
  * Tasks at the same time sit **side by side**, each in its own column placed
    by its own clock. Nothing is moved or hidden — a clash is yours to make.
  * **Hold a task and drag it**: an outlined capsule shows where it will land with the new times in bold, a chip follows your finger, and the + turns into a bin to delete. Scrolling still works everywhere.
    * Drag past the last task, through midnight, to as late as 3:55 the next morning without leaving the day, as the old timeline did: the night's hours show faintly while you drag, and a drop after midnight saves on the next date and stays at the end of this day.
    * Drop it on a day in the week strip to move it to that day at the same time.
  * Tap the ☆ on a task to make it a Top Win. Once something is starred, the Top Wins row shows under the week ("Top Wins · 1 of 3", "Day won"); tap a chip to jump to it.
  * Split tasks show "Part 2/3", and logged focus time shows as "25m worked · 35m left".
  * **Now** (on today) scrolls to the task under way or next; **Today** (on another day) goes back.
  * Tap a task to edit it.
* **Inbox** (the Focus board): overdue cards ranked by deadline (starred and high priority, then broken deadlines, missed slots, never scheduled, then work for a milestone due within 14 days), today's remaining tasks, and the week as milestone rows.
  * Each card has Done, Tomorrow, Date and Drop. Drop closes a task as skipped and never deletes it.
  * Hold a card for its menu (Select, Done, Tomorrow, Pick a date, Drop), or tap **Select** to move or drop several.
  * Milestones are in the ⋯ menu.
* **Settings**: server, app key and reminders, and a line saying why a reminder
  would arrive in silence — notifications off, sounds off, or the file missing.
* The bottom is a floating pill (Inbox · Timeline · Settings) with a round **+** beside it (⌘N on iPad keyboards and Mac).
* **A change made somewhere else turns up on its own.** An open window re-reads
  the server about every minute and a half, so what the phone does appears on
  the Mac without touching it. Skipped while you are saving or dragging.
* **Every change shows at once** (add, edit, tick, star, drag, move, drop, delete) and saves in the background. If the server refuses it, just that change is undone and a message says what couldn't be saved and why.
* **Reminders** arrive 10 minutes before every timed task, with their own
  two-note pop rather than the system default. They are local notifications,
  so no push service or paid account is needed. iOS plays them at the ringer's
  volume; an alert that overrides silent mode needs Apple's critical-alert
  entitlement, which a free account cannot get.

## The Today widget

A home-screen and lock-screen widget showing what you are on now and what is
next, in the same colours as the timeline.

* **Tick a task off from the widget itself** — tap the circle; it fills at once
  and the server is told behind it. If that fails, the tick is taken back, the
  same as in the app. No need to open anything.
* **Large** shows six: what is on now and the five after it, each with its own
  tick, the one under way in the accent colour. **Extra large** (iPad) shows
  nine. A widget cannot scroll — it is a picture iOS redraws, not a view — so
  the rest is a tap away in the app.
* Small and medium show what is on now with the time left, then what is next.
  The lock screen has inline, circular and rectangular.
* It draws what the app last synced, so it paints instantly and still says
  something with no signal, and it redraws when a task starts or ends rather
  than on a timer.
* Add it like any widget: hold the home screen, **+**, search Planner OS.

The one compromise: ticking from the widget means the widget needs the server
and app key, and it cannot read the app's Keychain without a second shared
entitlement. So the app writes a copy into the App Group, with iOS file
protection, unreadable until the phone has been unlocked once after a restart.
Disconnecting in Settings removes it. The Keychain is still where the app's own
copy lives.

The app and the widget are separate programs and cannot see each other's
files, so they share one folder — an **App Group**, `group.dev.planneros.planner`.
Both targets are already set up for it.

* If you change the bundle identifier (see below), change the group to match
  in `apple/PlannerOS.entitlements`, `apple/PlannerWidget.entitlements`, their
  two `-Mac` counterparts and `apple/Shared/PlannerSnapshot.swift`, and set the
  widget's identifier to your app's with `.widget` on the end.
* If Xcode refuses to sign the App Group on your free account, the widget will
  not read anything and shows "Open Planner OS once" for good. Tell me and
  I'll switch it to a widget you configure with the server and key directly,
  which needs no shared entitlement.

## Build and run

You need Xcode 16 or later. Open `apple/PlannerOS.xcodeproj`, then:

1. Select the **PlannerOS** target, then **Signing & Capabilities**.
   * Set **Team** to your Personal Team (sign in under Xcode, Settings, Accounts if it isn't listed).
   * If Xcode says the bundle identifier is taken, change `dev.planneros.planner` to something of your own, e.g. `dev.planneros.planner.sparsh`.
2. Do the same for the **PlannerWidget** target: same Team, and if you changed
   the app's identifier, set this one to it with `.widget` on the end.
3. **iPhone / iPad**: plug the device in.
   * On the device, turn on Settings, Privacy & Security, **Developer Mode** (it restarts).
   * Pick the device as the run destination, then press Run (⌘R).
   * The first time, trust your certificate on the device: Settings, General, VPN & Device Management.
4. **Mac**: pick **My Mac** as the destination, then press Run.
   * To keep the app, use Product, Show Build Folder in Finder, and drag `PlannerOS.app` into Applications.
5. On first launch, enter your server origin (HTTPS, without `/app`) and your `PWA_ACCESS_KEY`.
   * The key is stored in the Keychain.
   * Allow notifications when asked.
   * Settings has a **Send a test notification** button.

### Free-account limits

* Apps installed with a Personal Team expire after **7 days** on iPhone and iPad. Plug in and press Run again to renew; your data is on the server, so nothing is lost.
* A free account can have 3 such apps on a device at once.

## How reminders work

Each time the app syncs, it reads the next 7 days and queues a notification
10 minutes before each timed task. The app syncs:
* when it opens or comes to the front;
* after every change you make in it;
* in iOS background refresh, which iOS runs when it chooses.

The system delivers queued notifications even when the app is closed.

* A change made somewhere else (web, Android, Claude) reaches this device's reminders the next time the app syncs.
* iOS allows 64 pending notifications, so the soonest 60 are kept.
* If the PWA also sends notifications on this device, turn those off to avoid getting each reminder twice.

## Checking the rules

`PolicyTests/main.swift` checks the Focus rules against the same cases as
Android's `FocusPolicyTest`: ranking, lateness, today, moves, quick dates,
week rows, timeline lanes, drag snapping, reminder timing, API decoding, the
day's loose ends, and what Siri is allowed to do and says back.
From `apple/` on a Mac (or any machine with Swift):

```sh
swiftc -swift-version 5 PlannerOS/Models.swift PlannerOS/FocusPolicy.swift \
    PlannerOS/TimelinePolicy.swift PlannerOS/PlannerAPI.swift \
    Shared/PlannerSnapshot.swift Shared/SharedConnection.swift Shared/PlannerVoice.swift \
    PolicyTests/main.swift -o /tmp/policy && /tmp/policy
```

The screens themselves need Xcode, so `e2e/run.sh` parses them instead and
refuses a tap gesture or drag source laid over a button — the fault that made
the Mac open a task when the tick was clicked.

## Siri, Shortcuts and Spotlight

`PlannerOS/VoiceIntents.swift` is the menu the app puts out front: what is
under way, what is next, what is left, add a task, complete a task, and fit
the day. Siri cannot look at a screen and press things, so this list is the
whole of what it can do — and the same list serves the Shortcuts app,
Spotlight, the Action button and Siri on the Mac.

Those are thin wrappers on purpose. Everything that decides what happens, and
every word said back, lives in `Shared/PlannerVoice.swift`, which is plain
Foundation and is checked by the command above on every run rather than only
when someone opens Xcode. Reading is answered from the snapshot the app
already shares with the widget, so it is instant and works with no signal;
anything that changes something waits for the server, because Siri must not
say "done" before it is true.

Nothing here needs an entitlement, a paid account or a beta OS.

## Checking both apps together

`e2e/run.sh` at the repo root runs every backend test, these rules, this app's
store against a fresh local Planner OS API (add, drag, tick, star, edit, move,
drop, delete, and a failed save), and every Android test including its touch
tests and the same end-to-end flows. Run it before shipping either app.
