# Android saved days and immediate task updates

Android 1.0.21 (version code 23).

- All date controls paint the saved day synchronously before scrolling or requesting fresh data. Saved days remain readable regardless of cache age. Previously viewed pages stay in memory; their persistent snapshots survive reopening the app.
- The selected day revalidates in the background. The three neighbouring days on either side warm independently, with at most two requests at a time and no Dashboard dependency.
- Create, edit, complete, star, drag, delete and split update the visible plan immediately. Disk projections and network writes run off the UI thread. Saves continue when the Activity is recreated or Dashboard opens, while the application process remains alive.
- Changed tasks project into every affected saved page, including an unopened destination and both copies of a pre-04:00 event. Partial pages remain dirty until a complete server response arrives, so they cannot masquerade as a fresh, complete alarm schedule.
- Rejected updates restore only their own rows across affected days, preserving other successful changes. Editor drafts remain available when reopening the editor. A persistent in-app error names the task and explicitly reports the restored state; Android also posts a save-error notification when notification permission permits.
- Network responses that race a write cannot overwrite the local edit. When writes finish, the current day and planning context reconcile automatically. Local refresh races no longer require a manual Refresh tap.
- The existing time-tracking switch and single ten-minute reminder policy remain in place.

Validation: Android unit tests, lint and APK assembly. The regression suite covers unopened destinations, offline saved reads, pre-persistence navigation, overnight copies, concurrent rollback, temporary-to-server IDs, exact split budgets and full task names in failure messages. Physical-device interaction is not verified in this workspace.

This is optimistic online saving, not a durable offline task outbox. A connection failure restores the affected change and reports it; it does not silently queue an indefinite retry. Unfinished requests are not guaranteed to survive Android terminating the process.
