# Project Inbox and project selection

Android 1.0.16 and the PWA add a workspace Inbox, compact Germany/Life project segments in task entry, and local suggestions for existing unscheduled tasks. Selecting a suggestion edits/schedules the existing task ID; it does not create a copy. At most six suggestion rows are visible, with scrolling for more. Notes, milestones, split links and saved history are preserved.

## Data and API

`GET /v2/day/planning-context` requires the existing app key and reads only the authenticated workspace. It returns active canonical projects, `project_aliases`, and open tasks without a start time, including future dates and excluding split umbrella rows. Work-progress fields use the existing batched calculation. Inbox merges those tasks with overdue items from `/v2/day/inbox`. Task PATCH supports scoped `project_id` and notes updates. Explicit project changes detach incompatible milestones; linking a milestone alone still adopts its project.

Both clients display persisted context immediately, then refresh quietly when its ten-minute TTL or date expires. Typing and view toggles do not refetch fresh context. Ordinary creates merge the returned task locally. Android uses account-generation guards and its existing mutation coordinator. Cached old project IDs resolve through aliases; unchanged unknown legacy IDs are omitted from PATCH to avoid reverting the consolidation.

## Consolidation

The owner ran the prepared atomic transaction successfully on 2026-10-14. Verified live totals: Germany 1,370 tasks and 23 milestones; Life other than Germany 189 tasks. All source projects remain present and active; no habits were changed. The transaction changed project ownership while retaining record IDs and saved histories. Private SQL and backups remain under ignored `backups/` and are not published.

`scripts/prepare_project_consolidation.py` generates a tenant-scoped transaction and backup; `scripts/consolidate_planning_projects.py` contains read-only helpers. The generator never applies changes. The transaction locks records, checks expected ownership, moves tasks/milestones and verifies history counts before committing; changed ownership or any later failure rolls back the whole transaction. A previously applied prepared file should not be rerun: generate a fresh plan when needed.

## Native widget

See [Android timeline widget](android_timeline_widget.md). The versioned APK is delivered to the established Google Drive latest-app folder. Physical Samsung launcher behavior remains to be confirmed on the device.
