# Planner OS Technical Reference

This document inventories the public Planner OS interface as implemented on
2026-07-12. The source of truth for MCP exposure is
`planner_mcp/server.py`; the source of truth for CLI syntax is
`planner_engine/cli.py:build_parser()`.

The inventory covers all 90 STDIO MCP tools and all 25 top-level Shadow CLI
command groups. Private Python helpers are intentionally excluded because they
are implementation details rather than callable product functions.

## Runtime Architecture

```text
ChatGPT/Codex -> STDIO MCP -> Planner MCP tools -> Planner Engine
Terminal      -> Shadow CLI --------------------> Planner Engine
                                                   |
                                                   +-> Excel workbook
                                                   +-> Google Calendar
                                                   +-> Apple Calendar/EventKit
```

- Excel is the primary planner source of truth.
- Semantic Writer owns workbook mutations and creates backups.
- Planning previews are read-only; apply operations require an explicit call.
- Calendar publication is never implied by a workbook apply.
- Exactly one execution target is active: `google_calendar`,
  `apple_calendar`, or `none`.
- Generic `publish_*` tools use only the active execution target.
- The older `calendar_sync_*` tools explicitly target Google Calendar.

## Common Formats

Dates use `YYYY-MM-DD`. Datetimes use ISO 8601, preferably including an offset,
for example `2026-07-13T18:00:00+05:30`. Times use `HH:MM`. Month identifiers
use workbook labels such as `Jul 2026`. Week numbers are one-based workbook
week sections.

Preferred dayparts are `morning`, `afternoon`, `evening`, or `night`. Task
statuses must match workbook validation values, normally `Not Started`,
`In Progress`, or `Done`.

### MCP Response Envelope

Most MCP tools return this JSON-compatible structure:

```json
{
  "success": true,
  "message": "Operation completed",
  "data": {},
  "warnings": [],
  "errors": [],
  "preview_id": null,
  "requires_confirmation": false,
  "operation": null,
  "target": null,
  "decision_id": null
}
```

Some router and legacy responses preserve their established typed shape inside
or instead of `data`. Consumers must always inspect `success`, `errors`, and
`requires_confirmation` before treating an operation as complete.

### Scheduled Block Payload

Calendar update tools accept a `block` object:

```json
{
  "title": "German",
  "start": "2026-07-13T18:00:00+05:30",
  "end": "2026-07-13T18:30:00+05:30",
  "category": "learning",
  "source": "planner_update",
  "is_fixed": true,
  "metadata": {
    "planner_block_id": "permanent-block-id"
  }
}
```

`title`, `start`, and `end` are required. Calendar ownership and external-link
checks prevent Planner OS deletion commands from deleting unrelated events.

## MCP Tool Reference

### Validation And Rules

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `validate` | none | Reads workbook/rules and reports structural errors. No mutation. |
| `list_rules` | none | Returns permanent YAML rules. No mutation. |
| `update_rule` | `path: str`, `value: any` | Updates one existing rule path in YAML. Persistent mutation. |
| `set_work_days` | `days: list[str]` | Updates configured work days. Persistent rule mutation. |
| `set_no_work_days` | `days: list[str]` | Updates configured no-work days. Persistent rule mutation. |

### Execution Targets And Generic Publishing

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `list_execution_targets` | none | Lists supported targets, capabilities, and active target. |
| `get_active_execution_target` | none | Returns the persistent active target. |
| `set_active_execution_target` | `target: str` | Immediately changes future publishing target; does not migrate old events. |
| `preview_execution_target_switch` | `target: str` | Previews a future-publishing switch. No mutation. |
| `apply_execution_target_switch` | `preview_id: str` | Applies an approved switch preview. Settings mutation only. |
| `preview_move_external_items` | `source_target`, `destination_target`, `start_date`, `end_date` | Previews explicit cross-target event migration. |
| `apply_move_external_items` | `preview_id: str` | Creates destination items and removes approved source items; reports partial failures. |
| `publish_today` | none | Publishes today's blocks through only the active target. |
| `publish_date` | `date: str` | Publishes one exact date through only the active target. |
| `publish_range` | `start_date: str`, `end_date: str` | Publishes an inclusive range through only the active target. |
| `publish_current_week` | none | Publishes the Monday-Sunday current week through only the active target. |

With active target `none`, generic publishing succeeds as a local-only skip and
does not write either calendar.

### Apple Calendar

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `apple_calendar_status` | none | Reports EventKit permission, selected calendar, and capabilities. |
| `apple_calendar_calendars` | none | Lists Apple calendars and writability. |
| `create_apple_calendar` | `title: str = "Planner OS"` | Creates an Apple calendar and persists its identifier. |
| `set_apple_calendar` | `calendar_id: str` | Persists the selected Apple calendar identifier. |
| `apple_calendar_list_range` | `start_date`, `end_date` | Lists Planner OS-owned Apple events in an inclusive range. |
| `apple_calendar_reconcile_range` | `start_date`, `end_date` | Reports missing, orphaned, duplicate, and stale Apple mappings. |
| `apple_calendar_update_event` | `external_id`, `block` | Updates one explicitly identified Planner OS Apple event. |
| `apple_calendar_delete_event` | `external_id`, `delete_scope = "single"` | Deletes one identified event; scope is `single`, `future`, or `series`. |
| `preview_apple_calendar_delete_range` | `start_date`, `end_date` | Returns the exact Planner OS events proposed for deletion. No deletion. |
| `apply_apple_calendar_delete_range` | `preview_id` | Applies an approved Apple range-deletion preview. |

Apple Calendar uses a local signed Swift/EventKit helper. The selected calendar
ID is local configuration; OAuth and cloud hosting are not involved.

### Google Calendar CRUD

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `calendar_list_range` | `start_date`, `end_date` | Lists Planner OS-owned Google events in an inclusive range. |
| `calendar_import_external` | `start_date`, `end_date` | Imports non-Planner Google Calendar events as dated tasks. |
| `calendar_lookup_event` | `planner_block_id`, `start_date`, `end_date` | Finds events by stable Planner OS block identity. |
| `calendar_update_event` | `external_id`, `block` | Updates one explicitly identified Planner OS Google event. |
| `calendar_delete_event` | `external_id` | Deletes one identified Planner OS event. |
| `calendar_delete_series` | `external_id` | Deletes an identified Planner OS recurring series. |
| `calendar_delete_future_series` | `external_id` | Deletes the identified occurrence and future series events. |
| `preview_calendar_delete_range` | `start_date`, `end_date` | Lists exact Planner OS events proposed for range deletion. |
| `apply_calendar_delete_range` | `preview_id` | Applies an approved Google range-deletion preview. |
| `calendar_reconcile_range` | `start_date`, `end_date` | Reports drift between planned blocks, Google events, and mappings. |
| `preview_calendar_cleanup_orphans` | `start_date`, `end_date` | Previews cleanup of Planner OS-owned orphan events. |
| `apply_calendar_cleanup_orphans` | `preview_id` | Applies an approved orphan-cleanup preview. |
| `calendar_repair_mapping` | `external_id` | Rebuilds a local external link from Planner OS event metadata. |

Planner OS-created Google events use stable metadata where supported:
`planner_os`, `planner_task_id`, `planner_block_id`, `planner_source`, and
`planner_version`.

### Planning And Replanning

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `plan_today` | none | Generates today's schedule. No workbook/calendar mutation. |
| `plan_today_from_now` | `current_datetime?: str` | Plans flexible blocks only after the supplied/current time. Read-only. |
| `replan_today_from_now` | `current_datetime?: str` | Replans remaining time while preserving fixed/history blocks. Read-only. |
| `preview_month_plan` | `request: MonthlyPlanningRequest` | Produces milestones, dated tasks, feasibility, warnings, and a preview ID. |
| `apply_month_plan` | `preview_id?: str`, `preview?: object` | Writes approved monthly proposals, creates backup, does not sync calendar. |
| `preview_week_plan` | `request: WeekPlanningRequest` | Previews one explicit workbook week or date range. |
| `apply_week_plan` | `preview_id?: str`, `preview?: object` | Writes approved week proposals and creates a backup. |
| `preview_day_replan` | `request: DayReplanRequest` | Previews today's remaining-time changes. |
| `apply_day_replan` | `preview_id?: str`, `preview?: object` | Writes approved dated changes if present and creates a backup. |

`MonthlyPlanningRequest`:

```json
{
  "month": "Jul 2026",
  "start_date": "2026-07-12",
  "end_date": "2026-07-31",
  "planning_mode": "remaining_month",
  "include_existing_tasks": true,
  "overwrite_existing_plan": false,
  "preview_only": true,
  "current_datetime": "2026-07-12T15:00:00+05:30"
}
```

`planning_mode` is `remaining_month` or `full_month`.

`WeekPlanningRequest`:

```json
{
  "month": "Jul 2026",
  "week_number": 3,
  "start_date": null,
  "end_date": null,
  "overwrite_existing_plan": false,
  "preview_only": true,
  "current_datetime": null
}
```

Supply either `week_number` or both explicit dates.

`DayReplanRequest`:

```json
{
  "month": "Jul 2026",
  "target_date": "2026-07-12",
  "current_datetime": "2026-07-12T17:00:00+05:30",
  "preview_only": true,
  "bounded_sessions": []
}
```

Day replanning currently supports today only. Bounded-session requests include
`title`, `category`, window start/end, session count, session duration, and gap.

### Workbook Tasks And Dated Tasks

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `status` | none | Read-only daily/weekly/monthly progress and slippage summary. |
| `complete_task` | `task_name`, `month?` | Marks a matching task complete, updates progress, creates backup/log. |
| `add_task` | `task`, `week`, `month?`, `category?`, `status`, `notes?` | Adds a weekly workbook task with backup. |
| `update_task` | `task_name`, `month?`, plus optional fields | Updates name/category/priority/week/status/notes with backup. |
| `move_task` | `task_name`, `destination_week`, `month?`, `status?` | Moves a weekly task to another workbook week with backup. |
| `delete_task` | `task_name`, `month?` | Deletes a matching workbook task with backup. |
| `add_dated_task` | `date`, `title`, `estimated_minutes`, optional scheduling fields | Creates an exact-date workbook task with permanent ID and backup. |
| `add_dated_tasks` | `tasks` | Creates multiple exact-date workbook tasks with permanent IDs in a single operation. |
| `update_dated_task` | `task_id`, `changes: object` | Updates an exact-date task by permanent ID; date moves retain identity. |
| `delete_dated_task` | `task_id` | Deletes one exact-date task by permanent ID with backup. |
| `list_dated_tasks` | `date` | Lists tasks stored for exactly one date. Read-only. |

Optional dated-task fields are `preferred_daypart`, `start_time`, `end_time`,
`hard_time`, `category`, and `notes`. Supplying start/end makes the task fixed.
A dated task is never silently moved to another date.

### Import And Google Calendar Sync

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `import_plan` | `input_path` | Imports validated structured JSON through Writer; workbook backup required. |
| `calendar_sync_today` | none | Generates today and syncs Google Calendar. |
| `calendar_sync_week` | none | Legacy alias that explicitly means current week. |
| `calendar_sync_current_week` | none | Syncs the Monday-Sunday week containing today to Google Calendar. |
| `calendar_sync_next_week` | none | Syncs the following Monday-Sunday week to Google Calendar. |
| `calendar_sync_week_number` | `month`, `week_number` | Syncs one explicit workbook week to Google Calendar. |
| `calendar_sync_range` | `start_date`, `end_date` | Syncs one explicit inclusive range to Google Calendar. |
| `calendar_sync_month` | `month` | Syncs scheduled blocks for one workbook month to Google Calendar. |
| `calendar_sync_date` | `date` | Syncs exactly one date, including dated tasks, to Google Calendar. |

Every parameterized sync result reports its actual date range. Core routing
rejects an unspecified or ambiguous “week” operation.

### Check-In And Reviews

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `daily_checkin` | `date?: str` | Read-only planned/completed/missed/partial report with carryover actions. |
| `daily_review` | `date?: str` | Read-only daily execution review. |
| `weekly_review` | `date?: str` | Read-only review for the week containing the date. |
| `monthly_review` | `month: str` | Read-only workbook month review. |

Review recommendations never mutate the planner; a separate preview/apply flow
is required for any recommended change.

### Diagnostics, Preferences, Repair, And Undo

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `planner_doctor` | none | Runs read-only workbook, settings, preview, mapping, log, and backup checks. |
| `list_preferences` | none | Lists persistent planner preferences and editable aliases. |
| `get_preference` | `name` | Reads one preference. |
| `update_preference` | `name`, `value` | Validates and persists one preference/rule/target setting. |
| `reset_preference` | `name` | Restores a supported preference to its built-in default. |
| `explain_active_constraints` | none | Explains effective planning and publishing constraints. |
| `preview_planner_repair` | none | Produces a local consistency-repair preview. No mutation. |
| `apply_planner_repair` | `preview_id` | Applies only the approved local repairs. |
| `preview_undo` | `decision_id?: str` | Previews restoring a Decision Log-referenced workbook backup. |
| `apply_undo` | `preview_id` | Applies an approved undo and creates a safety backup first. |
| `undo_last_change` | none | Immediately undoes the latest eligible workbook decision. |

Undo does not expose arbitrary file restoration. External reversal failures are
reported and must not be represented as complete success.

### Recurrence

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `preview_recurrence` | `request: RecurrenceRequest` | Generates bounded dated occurrences and a preview ID. |
| `apply_recurrence` | `preview_id` | Writes occurrences as dated tasks and stores the recurrence definition. |
| `list_recurrences` | none | Reads definitions from `_RECURRENCES`. |
| `pause_recurrence` | `recurrence_id` | Sets a recurrence definition to paused. |
| `resume_recurrence` | `recurrence_id` | Sets a recurrence definition to active. |

`RecurrenceRequest`:

```json
{
  "title": "German",
  "frequency": "selected_weekdays",
  "start_date": "2026-07-13",
  "until_date": "2026-08-13",
  "count": null,
  "selected_weekdays": ["Monday", "Wednesday", "Friday"],
  "estimated_minutes": 30,
  "preferred_daypart": "evening",
  "category": "learning"
}
```

Frequency is `daily`, `weekdays`, `weekends`, `selected_weekdays`, `weekly`, or
`monthly`. At least one of `until_date` or `count` is required.

### Goal Planning

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `preview_goal_plan` | `request: GoalPlanningRequest` | Deterministically generates milestones, outcomes, dated tasks, feasibility, and preview metadata. |
| `apply_goal_plan` | `preview_id` | Rejects stale/expired/applied previews, then writes goal and dated tasks with backups. Calendar remains untouched. |

`GoalPlanningRequest`:

```json
{
  "title": "Finish German A1",
  "target_date": "2026-09-30",
  "start_date": "2026-07-13",
  "category": "learning",
  "current_level": "A0",
  "target_level": "A1",
  "weekly_capacity_minutes": 300,
  "allowed_days": ["Monday", "Wednesday", "Friday"],
  "preferred_dayparts": ["evening"],
  "fixed_daily_minutes": 45,
  "supporting_activities": [],
  "hard_constraints": [],
  "notes": null
}
```

### Command Router

| Tool | Parameters | Behavior and side effects |
|---|---|---|
| `parse_common_intent` | `text` | Deterministically parses supported phrases into a `PlannerCommand`; never mutates. |
| `route_planner_command` | `command: PlannerCommand` | Validates and dispatches one structured command; refuses ambiguity/unconfirmed writes. |

`PlannerCommand`:

```json
{
  "command_type": "add_dated_task",
  "payload": {
    "date": "2026-07-13",
    "title": "Call plumber",
    "estimated_minutes": 30,
    "preferred_daypart": "morning"
  },
  "preview_required": false,
  "source_text": "call plumber tomorrow",
  "confidence": "high",
  "requires_confirmation": false
}
```

Supported command types include task CRUD, dated-task CRUD, day/week/month
planning, Google sync, check-in/reviews, rules/preferences, goal planning,
execution-target switching/publishing/migration, recurrence, repair, undo, and
doctor. Low-confidence or materially ambiguous commands return recognized data
and require confirmation without mutation.

## Shadow CLI Reference

### Global Options

Global options must appear before the command:

| Option | Purpose |
|---|---|
| `--planner PATH` | Workbook path. |
| `--backup-dir PATH` | Workbook backup directory. |
| `--rules PATH` | Rules YAML path. |
| `--month LABEL` | Override inferred workbook month. |
| `--google-credentials PATH` | Google OAuth client credentials. |
| `--google-token PATH` | Google OAuth token. |
| `--google-calendar-id ID` | Google target calendar. |
| `--google-timezone ZONE` | Google scheduling timezone. |
| `--execution-settings PATH` | Active-target settings file. |
| `--external-links PATH` | External-link mapping file. |
| `--execution-preview-dir PATH` | Execution preview directory. |
| `--apple-calendar-helper PATH` | Native EventKit helper executable. |
| `--apple-calendar-id ID` | Override selected Apple calendar. |
| `--decision-log PATH` | Decision Log JSONL path. |

### Planning, Tasks, And Status

| Command | Behavior |
|---|---|
| `shadow import INPUT.json` | Imports structured planner data into workbook. |
| `shadow plan today [--from-now]` | Prints today's read-only plan. |
| `shadow plan week --week N [--preview|--apply]` | Previews or applies one workbook week. |
| `shadow plan month [--preview|--apply]` | Previews or applies remaining-month plan. |
| `shadow replan today --from-now` | Prints a read-only remaining-time replan. |
| `shadow complete "TASK"` | Marks a task complete with backup/progress update. |
| `shadow add-dated-task --date DATE --title TITLE --minutes N [--daypart PART] [--start-time HH:MM --end-time HH:MM] [--hard-time] [--category VALUE] [--notes TEXT]` | Adds an exact-date task. |
| `shadow dated-tasks --date DATE` | Lists exact-date tasks. |
| `shadow checkin [--date DATE]` | Prints a read-only daily check-in. |
| `shadow review daily [--date DATE]` | Daily review. |
| `shadow review weekly [--date DATE]` | Weekly review. |
| `shadow review monthly --month "Jul 2026"` | Monthly review. |
| `shadow status` | Prints progress, streaks, slippage, and dated tasks. |
| `shadow validate` | Validates workbook and rules. |

For week/month planning, `--apply` applies the preview generated in that same
invocation. MCP is preferred when a preview must be reviewed and applied later
by persistent preview ID.

### Google Authentication And Parameterized Sync

| Command | Behavior |
|---|---|
| `shadow calendar-auth` | Runs Google OAuth and persists the token. |
| `shadow calendar-sync today` | Syncs today's generated plan to Google Calendar. |
| `shadow calendar-sync date --date DATE` | Syncs exactly one date to Google Calendar. |
| `shadow calendar-sync current-week` | Syncs the current Monday-Sunday range. |
| `shadow calendar-sync next-week` | Syncs the following Monday-Sunday range. |
| `shadow calendar-sync week --month "Jul 2026" --week N` | Syncs an explicit workbook week. |
| `shadow calendar-sync range --start DATE --end DATE` | Syncs an explicit inclusive range. |
| `shadow calendar-sync month --month "Jul 2026"` | Syncs one workbook month. |
| `shadow calendar-sync week` | Rejected as ambiguous unless `--week` is supplied. |

### Google Calendar CRUD

| Command | Behavior |
|---|---|
| `shadow calendar list-range START END` | Lists Planner OS Google events. |
| `shadow calendar lookup-event BLOCK_ID START END` | Looks up events by stable block ID. |
| `shadow calendar update-event EVENT_ID --title TITLE --start DATETIME --end DATETIME [--category VALUE] [--source VALUE] [--planner-block-id ID]` | Updates one owned event. |
| `shadow calendar delete-event EVENT_ID` | Deletes one owned event. |
| `shadow calendar delete-series EVENT_ID` | Deletes an owned recurring series. |
| `shadow calendar delete-future-series EVENT_ID` | Deletes this and future series events. |
| `shadow calendar delete-range-preview START END` | Previews exact range deletion. |
| `shadow calendar delete-range-apply PREVIEW_ID` | Applies approved range deletion. |
| `shadow calendar reconcile-range START END` | Reports Google drift. |
| `shadow calendar cleanup-orphans-preview START END` | Previews owned orphan cleanup. |
| `shadow calendar cleanup-orphans-apply PREVIEW_ID` | Applies approved orphan cleanup. |
| `shadow calendar repair-mapping EVENT_ID` | Repairs a local Google mapping. |

### Execution Targets And Publishing

| Command | Behavior |
|---|---|
| `shadow execution-target list` | Lists targets and capabilities. |
| `shadow execution-target get` | Returns the active target. |
| `shadow execution-target set TARGET` | Immediately changes future publishing target. |
| `shadow execution-target switch-preview TARGET` | Previews target switch. |
| `shadow execution-target switch-apply PREVIEW_ID` | Applies approved target switch. |
| `shadow execution-target move-preview SOURCE DESTINATION START END` | Previews cross-target item migration. |
| `shadow execution-target move-apply PREVIEW_ID` | Applies approved migration. |
| `shadow publish today` | Publishes today using active target. |
| `shadow publish date --date DATE` | Publishes one date using active target. |
| `shadow publish current-week` | Publishes current week using active target. |
| `shadow publish range --start DATE --end DATE` | Publishes inclusive range using active target. |

Valid target values are exactly `google_calendar`, `apple_calendar`, and
`none`.

### Apple Calendar

| Command | Behavior |
|---|---|
| `shadow apple-calendar status` | Shows permission, selected calendar, and capabilities. |
| `shadow apple-calendar calendars` | Lists calendars. |
| `shadow apple-calendar create-calendar [--title TITLE]` | Creates/selects a dedicated calendar. |
| `shadow apple-calendar select CALENDAR_ID` | Selects target calendar. |
| `shadow apple-calendar publish-today` | Publishes today directly to Apple Calendar. |
| `shadow apple-calendar publish-date DATE` | Publishes one date directly to Apple Calendar. |
| `shadow apple-calendar publish-range START END` | Publishes a range directly to Apple Calendar. |
| `shadow apple-calendar list-range START END` | Lists Planner OS Apple events. |
| `shadow apple-calendar reconcile-range START END` | Reports Apple drift. |
| `shadow apple-calendar update-event EVENT_ID --title TITLE --start DATETIME --end DATETIME [--category VALUE] [--source VALUE] [--planner-block-id ID]` | Updates one owned Apple event. |
| `shadow apple-calendar delete-event EVENT_ID [--scope single|future|series]` | Deletes explicitly identified owned event(s). |
| `shadow apple-calendar delete-range-preview START END` | Previews exact range deletion. |
| `shadow apple-calendar delete-range-apply PREVIEW_ID` | Applies approved range deletion. |

Apple-specific publish commands are available in CLI. MCP callers should use
the generic `publish_*` tools after selecting `apple_calendar` as the active
target.

### Rules, Preferences, Repair, And Undo

| Command | Behavior |
|---|---|
| `shadow rules list` | Prints rules YAML. |
| `shadow rules set-work-days DAY...` | Persists work days. |
| `shadow preferences list` | Lists preferences. |
| `shadow preferences get NAME` | Reads one preference. |
| `shadow preferences update NAME VALUE` | Parses JSON when possible and persists the value. |
| `shadow preferences reset NAME` | Resets a supported preference. |
| `shadow preferences explain-active-constraints` | Explains effective constraints. |
| `shadow doctor` | Runs read-only diagnostics. |
| `shadow repair preview` | Generates local repair preview. |
| `shadow repair apply PREVIEW_ID` | Applies approved repair. |
| `shadow undo preview [--decision-id ID]` | Previews backup-based undo. |
| `shadow undo apply PREVIEW_ID` | Applies approved undo. |
| `shadow undo last` | Immediately undoes latest eligible workbook change. |

### Recurrence And Goals

| Command | Behavior |
|---|---|
| `shadow recurrence preview --title TITLE --frequency FREQUENCY --start-date DATE [--until DATE|--count N] [--weekday DAY] [--minutes N] [--daypart PART] [--category VALUE]` | Previews bounded occurrences. |
| `shadow recurrence apply PREVIEW_ID` | Writes occurrences and recurrence definition. |
| `shadow recurrence list` | Lists definitions. |
| `shadow recurrence pause RECURRENCE_ID` | Pauses a definition. |
| `shadow recurrence resume RECURRENCE_ID` | Resumes a definition. |
| `shadow goal preview --title TITLE --start-date DATE --target-date DATE [--category VALUE] [--weekly-capacity N] [--allowed-day DAY] [--daypart PART] [--minutes N] [--notes TEXT]` | Previews deterministic goal breakdown. |
| `shadow goal apply PREVIEW_ID` | Applies approved goal plan. |

### Natural-Language Adapter

| Command | Behavior |
|---|---|
| `shadow parse "TEXT"` | Parses supported phrase into a structured command. Never mutates. |
| `shadow route "TEXT"` | Routes only commands that do not require confirmation. |
| `shadow route "TEXT" --confirm` | Clears confirmation for medium/high-confidence commands; low confidence remains blocked. |

The parser is intentionally small and deterministic. It is not a general NLP
model and does not call an external LLM API.

## Persistence And Mutation Map

| State | Location | Mutated by |
|---|---|---|
| Visible planner data | Excel workbook | Writer-backed task, planning, goal, recurrence, progress operations |
| Recurrence definitions | Hidden `_RECURRENCES` workbook sheet | Recurrence apply/pause/resume |
| Rules | `config/rules.yaml` | Rules and preference updates |
| Execution target/settings | `.planner-os/execution-settings.json` | Target/calendar selection and preferences |
| External mappings | `.planner-os/external-links.json` | Publishing, reconciliation repair, migration, deletion |
| Planning previews | `.planner-os/planning-previews/` | Planning preview/apply |
| Execution previews | `.planner-os/execution-previews/` | Target migration, calendar deletion, repair, undo, recurrence, goal |
| Decision Log | `.planner-os/decision-log.jsonl` | Planner mutations |
| Backups | configured backup directory | Every workbook mutation |
| Google credentials/token | `.planner-os/credentials.json`, `.planner-os/token.json` | OAuth only; never stored in workbook |
| Apple helper | `.planner-os/bin/PlannerAppleCalendar.app` | Local build/setup only |

No SQL or embedded database is used.

## Preview And Apply Safety

- Preview tools make no workbook or calendar changes.
- Planning apply writes workbook only; calendar publication remains separate.
- Range deletions and orphan cleanup require preview/apply.
- Exact event update/delete may execute directly because the external ID is
  explicit and ownership is checked.
- Target switching does not migrate historical items.
- Cross-target migration requires explicit preview/apply.
- Dated-task identity survives title, time, row, and date changes.
- Repeated publication uses stable IDs and mappings to avoid duplicates.
- Stale, expired, mismatched, or already-applied previews are rejected through
  the shared preview contract (`planner_engine/preview_contract.py`). Each
  sealed preview records a content fingerprint of the planner state it depends
  on (workbook, rules, execution settings, external links); apply operations
  validate kind, expiry, single-use, and fingerprint in one place. Previews
  stored before the contract existed validate as legacy and keep their
  original service-level checks.

## Interface Differences

- MCP exposes direct weekly-task CRUD and dated-task update/delete; CLI exposes
  these through narrower commands or the structured router.
- CLI exposes Google OAuth because authentication is an interactive local
  workflow; MCP does not expose credential operations.
- CLI has direct Apple publish commands; MCP uses active-target generic
  publishing.
- `calendar_sync_*` is the legacy Google-specific family. `publish_*` is the
  active-target family and is preferred for target-neutral clients.

## Refreshing The MCP Connector

After changing `planner_mcp/server.py` or tool signatures, stop and restart the
local tunnel/STDIO process, then remove and re-add or refresh the ChatGPT
connector while the tunnel is running. Restarting ChatGPT alone does not reload
the server process or its cached tool registry.

