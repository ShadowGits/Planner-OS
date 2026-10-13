# Native Android timeline widget

Planner OS includes a resizable native home-screen widget, not a PWA shortcut or floating timer. On Samsung, long-press a blank home-screen area, choose **Widgets → Planner OS → Planner OS timeline**, then drag it onto the home screen. Long-press the placed widget to resize it.

## Behavior

- White/warm neutral surface, wine accent, compact date/completion header, and a live local time clock.
- Scrollable scheduled tasks, with a fixed start/end time column, readable two-line title, duration/status, and completion checkbox. Rows are chronological even after completion; their height does not pretend to represent duration.
- The current task gets a subtle accent. Finished tasks are checked/struck through; expired unfinished blocks say **Overdue**. Overnight times explicitly show **+1**.
- Tap a task title to open that exact task in the Day editor. Tap a checkbox to mark it complete/incomplete from the home screen, without opening the full Planner UI or asking for a timer/work log.
- Previous/next-day buttons, **Today**, and manual refresh. Each placed widget keeps its own date. Today follows the existing 04:00 logical-day boundary.
- Saved device data appears immediately. Offline data remains readable. Saving failures restore the previous row and provide a retry message; taps do not silently create tasks.

## Technical implementation

`TimelineWidgetProvider`, `TimelineWidgetService` and native `RemoteViews` layouts provide the launcher widget on Android 8/API 26 and newer. The launcher owns collection scrolling and resizing. `widget_timeline_info.xml` requests a 4×4 placement and supports resizing down to 220×180 dp. Native `previewLayout` shows three sample agenda rows for modern launcher previews.

Widget requests never include credentials. The receiver, collection service and entry activity are not exported; the service requires `BIND_REMOTEVIEWS`. Collection clicks use the standard mutable activity template (required for list fill-in actions), with distinct widget/account/date identity and per-row task/expected-state extras. The invisible entry activity validates current account generation, active widget, selected date and cached task membership. Title requests reach exported MainActivity only through a short-lived, one-use token in private app storage.

Checkbox writes use WorkManager, the shared process-wide `PlannerRepository.mutations` task/group coordinator, repository `beginSnapshotWrite`, `saveSnapshot`, `patch`, rollback and `confirmSnapshots`. Optimistic snapshots project changes into related cached views without replacing unrelated rows. A generation-scoped desired-state outbox makes retry after a lost response idempotent; it repeats a specific `done` value instead of toggling twice. Foreground MainActivity observes cache changes so its view stays in sync.

Cache writes coalesce widget paints without triggering network. Ordinary checkbox completion does not refetch the whole day; linked task parts reconcile only their affected date after the server propagates group completion. Network jobs have a 60-second overall budget, connected-network constraint, ten-minute cache freshness reuse, unique-work deduplication, and five-second manual-refresh debounce. Periodic updates are every 30 minutes. One local delayed WorkManager job repaints at the next scheduled start/end, midnight or logical-day boundary; it does not fetch just to update a clock. Android can delay these jobs in battery saver/Doze; the live `TextClock` still shows the actual current time. No exact-alarm or new notification permission is added.

The widget does not call timer start or work-log prompts, and it does not change the existing timers-off preference. Completing a task uses the existing task/notification invalidation and auto-focus schedule synchronization.

## Verification

`TimelineWidgetPolicyTest` covers ordering, completed/current/overdue boundaries, hidden unscheduled/pending rows, midnight/end-time rollover, intent identity, generation and repeated-tap guards, and concurrent task/group exclusions. XML parse checks cover resources and manifest. Build, unit tests and lint are run by the coordinating release chat; actual Samsung launcher/resize/interaction testing requires installation on the phone.
