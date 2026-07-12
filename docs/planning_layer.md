# Planner OS Product Planning Layer v1

## Status

This branch contains the Product Planning Layer implementation. The user has
explicitly requested that no tests be added, modified, or run during the
current continuation, so the latest changes are implementation-complete but
not newly verified.

No commit or push has been made.

## Architecture

The existing ownership boundaries remain intact:

- Excel remains the source of truth.
- `PlannerEngine` reads planner concepts and exposes store operations.
- `Writer` remains the only product component that initiates workbook
  mutations.
- Planning, capacity, distribution, check-in, and current-time modules are
  read-only.
- MCP and CLI remain adapters.
- Google Calendar remains an integration target, not planning storage.

## Implemented

### Capacity

`planner_engine/capacity.py` defines typed capacity requests and reports. It
subtracts sleep, work, fixed commitments, scheduled blocks, and elapsed time
today. It reports day/daypart capacity, overload, conflicts, and feasibility.

### Monthly Planning

`planner_engine/monthly_planner.py` reads monthly goals and produces weekly
milestones, daily proposals, feasibility data, warnings, proposed Excel
changes, and the proposed calendar range. It applies deterministic German,
piano, gym, IELTS, IGNOU, reading, and general-task heuristics.

It never writes Excel or Calendar.

### Daily Distribution

`planner_engine/daily_distributor.py` spreads milestone sessions across dates,
handles recurring cadence, gym's 9-session pattern, dance restrictions, daily
load limits, elapsed dates, and explicit spillover warnings.

### Preview And Apply

`planner_engine/planning_commands.py` provides month/week/day preview and apply
services. Month/week apply batches approved tasks through `Writer`, creating a
single backup and decision record. Calendar is not synced automatically.

Approved daily proposals are written as workbook-backed dated tasks in their
exact day columns. `overwrite_existing_plan=true` replaces only earlier
Planner-OS-generated dated rows inside the approved range; manual dated tasks
are preserved.

Preview payloads are stored under ignored `.planner-os/planning-previews/`
files, so an approved preview ID survives an MCP process restart. Apply accepts
either the preview ID or the returned preview object.

### Current-Time Planning

`planner_engine/current_time.py` preserves fixed/history blocks, removes past
flexible placement, and attempts to place flexible work after the injected
current time. Unplaceable work becomes a spillover conflict.

### Parameterized Calendar Sync

`planner_engine/calendar_sync.py` exposes current week, next week, workbook
week number, explicit range, month, and exact-date sync. Results name and report
the actual inclusive date range. The legacy `calendar_sync_week` remains and
explicitly means current week.

`GoogleCalendarClient.sync_plan` now accepts an explicit sync range and scope.

### Daily Check-In

`planner_engine/checkin.py` produces a read-only daily report with planned,
completed, partial, missed, recurring, streak, slippage, completion, action,
and carryover data.

### Command Router

`planner_engine/command_router.py` defines structured command/result models,
safe dispatch, preview-before-apply enforcement, ambiguity rejection, and a
small deterministic phrase parser. It does not call an LLM or external API.

Supported phrase families include weekend rules, complete/move task, plan or
replan from now, current/next-week sync, coming-week preview, daily check-in,
bounded gym requests, and tomorrow tasks.

MVP2 routing also covers local execution-target switching, active-target
publishing, preferences, planner repair previews, undo, and recurrence
preview/apply commands. Low-confidence phrases still require confirmation and
do not mutate planner state.

`shadow route` now dispatches high-confidence commands through the router.
Commands marked ambiguous or confirmation-required remain non-mutating. Split
requests such as "sort room half today and half tomorrow afternoon" produce two
dated-task proposals that can be approved as one backed-up batch using
`shadow route "..." --confirm`. Low-confidence commands remain blocked even
with `--confirm`.

### Workbook-Backed Dated Tasks

Dated tasks use the existing weekly row and exact day column in Excel. No JSON
fallback is used.

- Fixed tasks store `HH:MM-HH:MM` in the exact date cell.
- Flexible tasks store values such as `30 min · morning`.
- Reader support returns typed `DatedTask` objects.
- Semantic Writer supports add, update, delete, and list.
- Calendar exact-date sync includes dated tasks and never moves them to another
  date.
- Check-in and status include dated tasks.
- Dated rows are excluded from generic scheduler demand to prevent accidental
  placement on another day.

### MCP And CLI

The requested planning, current-time, calendar, check-in, router, and dated-task
entry points have been added. Existing MCP tools and CLI commands remain.

## Intended Flows

### Monthly

1. `preview_month_plan`
2. Review warnings, conflicts, spillover, and proposed Excel changes.
3. `apply_month_plan` with the returned preview ID.
4. Optionally call `calendar_sync_month` explicitly.

### Coming Week

1. `preview_week_plan` with next week's explicit dates or workbook week number.
2. `apply_week_plan` with the returned preview ID.
3. `calendar_sync_next_week` only after approval.

### Today

1. `daily_checkin`
2. `replan_today_from_now`
3. `apply_day_replan` if the preview proposes workbook changes.
4. `calendar_sync_date` for today only.

### Dated Task

1. `add_dated_task` writes the task into its weekly row and exact date column.
2. `list_dated_tasks` verifies the stored date and time/daypart marker.
3. `calendar_sync_date` schedules and syncs exactly that date.

## Remaining Work

Complete these in order:

1. When testing is authorized again, add focused coverage for all new modules,
   workbook dated-task behavior, and calendar range safety.
2. Add a separate calendar reconciliation preview before any sync expected to
   update or delete many events.
3. Expand check-in execution evidence. Workbook status is currently the primary
   signal; calendar data is not yet used as supporting evidence.

## Known Limitations

- The latest continuation has not been tested because testing was explicitly
  disabled by the user.
- Monthly unit extraction only recognizes simple numeric notes such as
  chapters, lessons, sessions, blocks, or units.
- Low-confidence goals use conservative deterministic estimates.
- Day replan apply writes approved future flexible blocks into exact-date
  workbook cells; it remains a no-op when the preview genuinely proposes no
  workbook changes.
- Calendar sync is always explicit, but large-delete preview/confirmation is not
  yet a separate command.
- The deterministic parser intentionally rejects unsupported or unclear text.

## Previous Verification Baseline

Run:

```sh
env PYTHONPATH=tests .venv/bin/python -m unittest discover -s tests
```

Before the no-tests instruction, the existing suite reported 90 tests passed.
Do not treat that earlier result as verification of subsequent changes.

## Safety Defaults

- Preview commands do not write the workbook.
- Apply commands do not sync Calendar.
- Calendar commands do not write the workbook.
- Check-in does not write workbook or Calendar.
- Dated-task add/update/delete are explicit workbook mutations and create
  backups through Semantic Writer.
- No operation writes to Calendar by default.
