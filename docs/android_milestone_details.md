# Android milestone workspace — 1.0.17

Tapping an active or completed milestone from Day, a project Dashboard, or Dashboard milestone health opens a dedicated full-screen workspace. The former inline expansion no longer intercepts navigation.

The workspace shows project, workflow status, web-equivalent schedule health, task progress with elapsed-time marker, start/deadline and notes. Its task list includes completed tasks and split sessions, with All/Open/Done filters and local title/notes search. Checkbox actions toggle completion. The shared task editor provides title, date, time, duration, notes, project, Top Win, split, delete, timer and optional time logging. Moving a task to another project detaches an incompatible milestone and removes it only from this milestone's list. Adding a task assigns the milestone in one create request. Milestone details can be edited, marked complete or reopened; linked task statuses remain independent.

## Health parity

The backend calls the same `MetricsService._milestone_progress` and `_milestone_health` used by the web dashboard. `health_status` and `health` remain separate from editable `status`. The native progress bar, elapsed marker and chips use the palette and labels from Deutschland-Dash's `MilestoneHealth.tsx`: overdue red-600; at-risk red-500; slipping amber-500; on-track emerald-500; complete emerald-600; undated gray-400. Chips use the corresponding 100 backgrounds and 700 text in light mode, with readable equivalents in dark mode. Workflow completion and task-derived health completion are both recognized when grouping the milestone list. Root task counts match web; split session rows remain accessible without inflating those counts.

## API

- `GET /v2/native/dashboard?section=milestones[&row_id=UUID]` returns milestone metadata, root task counts, project name and health.
- `GET /v2/native/dashboard?section=tasks&milestone_id=UUID&include_parts=true&offset=N` returns scoped editable rows, notes, split context and work progress. Pages contain at most 100 records. The client verifies the echoed milestone ID and parts flag, preventing older servers that ignore query parameters from populating the page with unrelated tasks.
- `PATCH /v2/native/milestones/{UUID}` accepts only name, workflow status, start date, target date and notes through the existing app-key trust model.
- `POST /v2/day/tasks` accepts `milestone_id`, verifies ownership/project compatibility, and creates one linked record. Existing task PATCH/delete/split/work routes remain in use.

All routes scope reads and writes to the configured user/workspace. UUID filters, field allowlists and existing service validation remain enforced. Dashboard work retains its bounded worker pool so an expensive tracker does not block Day.

## Phone storage and refresh

Dashboard storage uses stable connection-generation/path keys and stamps saved revision/time separately. Task mutations make saved pages stale rather than deleting them. Legacy revision-keyed pages migrate only within the same connection generation. Cached milestone metadata and complete task lists render before network work; independent metadata/task refreshes run in parallel. Request mutexes deduplicate repeated loads across repository instances. Fresh cached pages avoid network for five minutes; manual refresh bypasses age. Combined pagination is saved for subsequent immediate reopening. Incomplete cold pages cannot be mistaken for complete fresh lists. Other account data cannot be reused after a connection change.

Task mutations reuse the shared task/group coordinator and Day/Inbox/planning snapshot projection. They update the visible task without downloading an entire day. Rollback restores only the failed task. Split/group propagation reconciles the affected milestone; successful server writes are not undone merely because a later local cache write or optional refresh fails. Timer/logging controls continue respecting the master off switch.

## Verification

Backend coverage checks web health parity, authentication, tenant/project/milestone boundaries, pagination, split DTOs, work progress, bounded milestone updates and one-request linked task creation. Android unit coverage checks cache generation/revision/TTL behavior, local filters/search/order and web health rules. Release validation includes compilation, native unit tests and lint. Physical Samsung interaction and layout verification still requires installation; build success does not establish device-tested behavior.

## Automatic tracking start — 1.0.18

Milestone tracking starts on the earliest linked root task date: its scheduled date, falling back to its due date. A manually stored milestone start does not override task dates. Rescheduling the earliest task updates the derived start. Undated tasks produce no elapsed-time marker; a first task on/after the target retains its actual start without inventing a positive tracking span. Existing root-task rollup semantics and the Postgres aggregation remain unchanged, so no migration or task-history rewrite is needed. The native API exposes `tracking_start_date` and `tracking_last_date` separately from saved metadata; the Android detail screen and local recalculation use these task dates. The milestone editor displays the automatic start instead of requesting another manual date. Complete cached task lists can update the span locally after a task edit; older cached milestone summaries refresh quietly to adopt the rule.
