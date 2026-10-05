# Android 1.0.10: split repair and timeline alignment

General Split is one atomic, tenant-scoped database operation with a persisted request ID. Retrying a lost response returns the same result. Two open sessions divide only the remaining work; prior work is preserved as a completed session, including exact-second budgets and task metadata. The first open session retains the slot (or starts after the worked portion); the second goes to Inbox unscheduled.

Explicit partial time logging on a scheduled unfinished task defaults to splitting and scheduling its remainder, preselects a clear slot, and allows changing or disabling this. Returning from Log time closes the editor and refreshes the changed day. Scheduled timer expiry remains optional and creates no mandatory logging prompts.

The NOW line and hour dividers are centered on their exact time coordinates. Short task cards use their actual scheduled duration instead of stretching to a minimum height. Inline completion, star, timer, editing, and drag gestures remain available.

Requires `supabase/migrations/0036_atomic_task_split.sql` and the backend `/v2/day/tasks/{task_id}/split` route. Migration was confirmed live by a table read and non-existent-task function probe on October 5, 2026.

Validation: 75 Android unit tests, Android lint and APK build; 22 work-log/day API tests; 9 real PostgreSQL-engine migration tests including retry safety, rollback, metadata, work history and midnight rollover. Emulator smokechecks verified partial 90/180-minute logging yields exactly one completed90-minute block plus one scheduled90-minute remainder, and general120-minute splitting yields exactly two60-minute children with one retry ledger entry. No production tasks were changed by verification.

APK: `Planner-OS-Android-1.0.10.apk`, versionCode12. SHA-256: `b999ac2916839b0ff5211f82eb5e00522d915eea94a2db0376bf625fa7ed884b`. Signing identity matches prior releases. Copied to the user's configured Google Drive latest-app folder.
