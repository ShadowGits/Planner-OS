# Planner OS for iPhone, iPad and Mac

One SwiftUI app for all three, built from Xcode with a free Apple account.
It talks to the same backend as Android, with the same app key.

* **Timeline** (opens first), laid out like Structured:
  * The month and year sit on top, above a week strip (swipe it for other weeks, or use the calendar button).
  * Untimed tasks show as round chips.
  * Each timed task is a coloured capsule on a spine, with an icon taken from its title and a height that follows its duration.
  * Times are on the left, "start – end (duration)" and the title on the right, and a circle to tick it off at the far edge.
  * Free time between tasks is shown, with "Now · 25m until …" when you are in a gap.
  * The task under way fills up as time passes.
  * **Hold a task to lift it, then drag it**: a line under your finger shows the start time it will get, ticking in 5-minute steps with a haptic each step, and it moves there when you let go. This uses the system's drag and drop, so scrolling still works everywhere.
  * Tap a task to edit it.
* **Focus**: overdue cards ranked by deadline (starred and high priority, then broken deadlines, missed slots, never scheduled, then work for a milestone due within 14 days), today's remaining tasks, and the week as milestone rows.
  * Each card has Done, Tomorrow, Date and Drop. Drop closes a task as skipped and never deletes it.
  * Hold a card for its menu (Select, Done, Tomorrow, Pick a date, Drop), or tap **Select** to move or drop several.
  * Milestones are in the ⋯ menu.
* **Settings**: server, app key and reminders.
* The floating **+** adds a task (⌘N on iPad keyboards and Mac).
* **Every change shows at once** (add, edit, tick, star, drag, move, drop, delete) and saves in the background. If the server refuses it, just that change is undone and a message says what couldn't be saved and why.
* **Reminders** arrive 10 minutes before every timed task. They are local
  notifications, so no push service or paid account is needed.

## Build and run

You need Xcode 16 or later. Open `apple/PlannerOS.xcodeproj`, then:

1. Select the **PlannerOS** target, then **Signing & Capabilities**.
   * Set **Team** to your Personal Team (sign in under Xcode, Settings, Accounts if it isn't listed).
   * If Xcode says the bundle identifier is taken, change `dev.planneros.planner` to something of your own, e.g. `dev.planneros.planner.sparsh`.
2. **iPhone / iPad**: plug the device in.
   * On the device, turn on Settings, Privacy & Security, **Developer Mode** (it restarts).
   * Pick the device as the run destination, then press Run (⌘R).
   * The first time, trust your certificate on the device: Settings, General, VPN & Device Management.
3. **Mac**: pick **My Mac** as the destination, then press Run.
   * To keep the app, use Product, Show Build Folder in Finder, and drag `PlannerOS.app` into Applications.
4. On first launch, enter your server origin (HTTPS, without `/app`) and your `PWA_ACCESS_KEY`.
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
week rows, timeline lanes, drag snapping, reminder timing and API decoding.
From `apple/` on a Mac (or any machine with Swift):

```sh
swiftc PlannerOS/Models.swift PlannerOS/FocusPolicy.swift PlannerOS/PlannerAPI.swift PolicyTests/main.swift -o /tmp/policy && /tmp/policy
```

## Checking both apps together

`e2e/run.sh` at the repo root runs every backend test, these rules, this app's
store against a fresh local Planner OS API (add, drag, tick, star, edit, move,
drop, delete, and a failed save), and every Android test including its touch
tests and the same end-to-end flows. Run it before shipping either app.
