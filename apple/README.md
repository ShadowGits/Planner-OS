# Planner OS for iPhone, iPad and Mac

One SwiftUI app for all three, built from Xcode with a free Apple account.
It talks to the same backend as Android, with the same app key.

* **Focus** (opens first): overdue cards ranked by deadline. Starred and high
  priority come first, then broken deadlines, missed slots and never-scheduled
  work, then work for a milestone due within 14 days. After that come today's
  remaining tasks and the week as milestone rows; tap a day to open it.
  * Each card has **Done**, **Tomorrow**, **Date** (any day from today) and
    **Drop**. Drop closes a task as skipped; nothing is deleted.
  * Long-press a card, or tap **Select**, to move or drop several at once.
  * Moving a task past its milestone's target pushes the milestone out.
* **Today**: untimed work on top, then a timeline.
  * Hold a block, then drag it to a new time (5-minute grid).
  * Tap a block to edit it, or an empty hour to add a task there.
  * Arrows and the date picker change the day.
* **+** adds a task (⌘N on iPad keyboards and Mac). **⋯** holds Milestones,
  Refresh and Settings.
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
