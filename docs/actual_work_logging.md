# Actual work logging

## Current behavior — Android 1.0.11 and PWA

Scheduled timer expiry creates no mandatory logging prompt or queue. Explicit scheduled Finish opens optional input; Ignore closes it. Task completion remains independent of logging. Android unscheduled timers retain a different entry/automatic elapsed-save policy. PWA expiry writes nothing and explicit Finish opens optional logging with elapsed focus seconds. Android scheduled Finish currently pre-fills planned duration rather than universal paused elapsed time; do not assume identical client behavior.

General task Split uses migration 0036 and a stable request/body. Actual-work-and-remainder scheduling uses migration 0035. See [split repair](android_split_repair.md) and [the complete technical handoff](technical_reference.md).

## Historical Android 1.0.8 behavior (superseded for scheduled timers)

An expired countdown stops at its planned end, posts an ongoing high-importance notification and opens an actual-time entry screen while Planner OS is visible. Android notification settings and DND still control heads-up display outside the app. Pending entries survive process death and reboot and appear on the next app visit.

Finishing a paused timer saves only elapsed focus seconds automatically, excluding paused time, without a confirmation dialog. A partial log keeps unfinished work open. Completed tasks expose **Log time** in their editor and Dashboard task details; adding a log alone preserves their completed status.

The entry screen separates planned, worked and remaining time. **Split & schedule remaining work** records a completed worked block and creates a remaining block for a chosen day/time, preserving task details and project links. Zero actual work simply reschedules the open block. A habit split moves only its current occurrence. Scheduling shows overlaps with other unfinished tasks. Seconds remain exact even though calendar blocks use whole-minute estimates.

Offline saves remain in an account-scoped durable outbox. WorkManager retries when connected. Each timer session has a stable request UUID; repeated requests return the original result. Logging, splitting and completion run in one PostgreSQL transaction, so a failed split cannot leave half-created tasks.

## Database setup

Run `supabase/migrations/0035_task_work_sessions.sql` in the live Supabase SQL editor before activating the APK. This migration adds actual-work history and the tenant-scoped `planner_log_work` RPC. It is standalone and does not require the uncommitted Day Recovery migration 0033. Existing Day/Inbox requests continue to work if migration 0035 is absent; logging returns a clear HTTP 409 until setup is complete.

## API

- `GET /v2/day/tasks/{task_ref}/work`: scoped task, split blocks, planned/worked/remaining seconds and work history.
- `POST /v2/day/tasks/{task_ref}/work`: request UUID, exact seconds, manual/timer source, finish flag, optional split/remainder date/time.

Day and Inbox feeds include compact work totals. Reads remain batched and avoid downloading unrelated task metadata. Dashboard loading retains its separate Activity, repository and cache.
