# Planner OS Tools Reference
This document contains the exact schemas for all Planner OS tools.
When calling the multiplexed `/api/v1/tools/{tool_name}/invoke` endpoint, you MUST use the exact arguments specified below for the corresponding tool_name.
Arguments marked with an asterisk (*) are required.

## add_dated_task
**Description:** Add a task to one exact workbook date column.
**tool_arguments:**
```json
{
  "date*": "string",
  "title*": "string",
  "estimated_minutes*": "integer",
  "preferred_daypart": "string",
  "start_time": "string",
  "end_time": "string",
  "hard_time": "boolean",
  "category": "string",
  "notes": "string"
}
```

## add_task
**Description:** Add a weekly task.
**tool_arguments:**
```json
{
  "task*": "string",
  "week*": "integer",
  "month": "string",
  "category": "string",
  "status": "string",
  "notes": "string"
}
```

## apple_calendar_calendars
**Description:** List writable local Apple calendars.
**tool_arguments:**
```json
{}
```

## apple_calendar_delete_event
**Description:** Delete one explicitly identified Planner OS Apple event.
**tool_arguments:**
```json
{
  "external_id*": "string",
  "delete_scope": "string"
}
```

## apple_calendar_list_range
**Description:** List Planner OS-owned Apple events in a range.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## apple_calendar_reconcile_range
**Description:** Reconcile Apple Calendar events in a range.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## apple_calendar_status
**Description:** Report native Apple Calendar permission and capabilities.
**tool_arguments:**
```json
{}
```

## apple_calendar_update_event
**Description:** Update one explicitly identified Planner OS Apple event.
**tool_arguments:**
```json
{
  "external_id*": "string",
  "block*": "object"
}
```

## apply_apple_calendar_delete_range
**Description:** Apply an approved Apple Calendar range deletion.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_calendar_cleanup_orphans
**Description:** Apply an approved orphan cleanup.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_calendar_delete_range
**Description:** Apply an approved Google event range deletion.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_day_replan
**Description:** Apply an explicitly approved day replan.
**tool_arguments:**
```json
{
  "preview_id": "string",
  "preview": "object"
}
```

## apply_execution_target_switch
**Description:** Apply an approved target-switch preview.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_goal_plan
**Description:** Apply an approved goal plan preview to the workbook.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_month_plan
**Description:** Apply an explicitly approved monthly planning preview.
**tool_arguments:**
```json
{
  "preview_id": "string",
  "preview": "object"
}
```

## apply_move_external_items
**Description:** Apply an approved explicit cross-target migration.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_planner_repair
**Description:** Apply an approved local repair preview.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_recurrence
**Description:** Apply an approved recurrence preview as dated workbook tasks.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_undo
**Description:** Apply an approved workbook undo preview.
**tool_arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_week_plan
**Description:** Apply an explicitly approved weekly planning preview.
**tool_arguments:**
```json
{
  "preview_id": "string",
  "preview": "object"
}
```

## calendar_delete_event
**Description:** Delete one explicitly identified Planner OS Google event.
**tool_arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_delete_future_series
**Description:** Delete this and future Planner OS Google recurring events.
**tool_arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_delete_series
**Description:** Delete a Planner OS Google recurring series.
**tool_arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_list_range
**Description:** List Planner OS-owned Google events in a range.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_lookup_event
**Description:** Find Google events by stable planner block ID.
**tool_arguments:**
```json
{
  "planner_block_id*": "string",
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_reconcile_range
**Description:** Reconcile planner blocks with Google Calendar.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_repair_mapping
**Description:** Repair a local mapping from Planner OS Google event metadata.
**tool_arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_sync_current_week
**Description:** Sync the Monday-Sunday range containing today.
**tool_arguments:**
```json
{}
```

## calendar_sync_date
**Description:** Sync exactly one date, including workbook-backed dated tasks.
**tool_arguments:**
```json
{
  "date*": "string"
}
```

## calendar_sync_month
**Description:** Sync all scheduled blocks in one explicit planner month.
**tool_arguments:**
```json
{
  "month*": "string"
}
```

## calendar_sync_next_week
**Description:** Sync the Monday-Sunday range after the current week.
**tool_arguments:**
```json
{}
```

## calendar_sync_range
**Description:** Sync one explicit inclusive date range.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_sync_today
**Description:** Generate today's plan and sync it to Google Calendar.
**tool_arguments:**
```json
{}
```

## calendar_sync_week
**Description:** Backward-compatible alias that explicitly syncs current week.
**tool_arguments:**
```json
{}
```

## calendar_sync_week_number
**Description:** Sync one explicit planner workbook week section.
**tool_arguments:**
```json
{
  "month*": "string",
  "week_number*": "integer"
}
```

## calendar_update_event
**Description:** Update one explicitly identified Planner OS Google event.
**tool_arguments:**
```json
{
  "external_id*": "string",
  "block*": "object"
}
```

## complete_task
**Description:** Mark a task complete.
**tool_arguments:**
```json
{
  "task_name*": "string",
  "month": "string"
}
```

## create_apple_calendar
**Description:** Create and select a dedicated local Apple calendar.
**tool_arguments:**
```json
{
  "title": "string"
}
```

## daily_checkin
**Description:** Generate a read-only daily progress check-in.
**tool_arguments:**
```json
{
  "date": "string"
}
```

## daily_review
**Description:** Generate a read-only daily review.
**tool_arguments:**
```json
{
  "date": "string"
}
```

## delete_dated_task
**Description:** Delete a workbook-backed exact-date task.
**tool_arguments:**
```json
{
  "task_id*": "string"
}
```

## delete_task
**Description:** Delete a task.
**tool_arguments:**
```json
{
  "task_name*": "string",
  "month": "string"
}
```

## explain_active_constraints
**Description:** Explain the constraints currently affecting planning and publishing.
**tool_arguments:**
```json
{}
```

## get_active_execution_target
**Description:** Return the persistent active downstream target.
**tool_arguments:**
```json
{}
```

## get_preference
**Description:** Read one planner preference.
**tool_arguments:**
```json
{
  "name*": "string"
}
```

## import_plan
**Description:** Import a structured JSON planner file.
**tool_arguments:**
```json
{
  "input_path*": "string"
}
```

## list_dated_tasks
**Description:** List workbook tasks assigned to one exact date.
**tool_arguments:**
```json
{
  "date*": "string"
}
```

## list_execution_targets
**Description:** List supported targets and the one active target.
**tool_arguments:**
```json
{}
```

## list_preferences
**Description:** List persistent planner preferences and editable aliases.
**tool_arguments:**
```json
{}
```

## list_recurrences
**Description:** List workbook-backed recurrence definitions.
**tool_arguments:**
```json
{}
```

## list_rules
**Description:** List permanent planner rules.
**tool_arguments:**
```json
{}
```

## monthly_review
**Description:** Generate a read-only monthly review.
**tool_arguments:**
```json
{
  "month*": "string"
}
```

## move_task
**Description:** Move a weekly task to another week.
**tool_arguments:**
```json
{
  "task_name*": "string",
  "destination_week*": "integer",
  "month": "string",
  "status": "string"
}
```

## parse_common_intent
**Description:** Parse a small supported set of common planner phrases.
**tool_arguments:**
```json
{
  "text*": "string"
}
```

## pause_recurrence
**Description:** Pause a workbook-backed recurrence definition.
**tool_arguments:**
```json
{
  "recurrence_id*": "string"
}
```

## plan_today
**Description:** Generate today's schedule without writing to Excel.
**tool_arguments:**
```json
{}
```

## plan_today_from_now
**Description:** Plan today using only remaining time for flexible blocks.
**tool_arguments:**
```json
{
  "current_datetime": "string"
}
```

## planner_doctor
**Description:** Run read-only local Planner OS diagnostics.
**tool_arguments:**
```json
{}
```

## preview_apple_calendar_delete_range
**Description:** Preview exact Planner OS Apple events to delete.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_calendar_cleanup_orphans
**Description:** Preview orphaned Planner OS Google events for cleanup.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_calendar_delete_range
**Description:** Preview exact Planner OS Google events to delete.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_day_replan
**Description:** Preview today's remaining-time replan without writing.
**tool_arguments:**
```json
{
  "request*": "object"
}
```

## preview_execution_target_switch
**Description:** Preview changing future publishing to one target.
**tool_arguments:**
```json
{
  "target*": "string"
}
```

## preview_goal_plan
**Description:** Preview deterministic breakdown of a structured goal.
**tool_arguments:**
```json
{
  "request*": "object"
}
```

## preview_month_plan
**Description:** Preview monthly milestones and dated daily proposals without writing.
**tool_arguments:**
```json
{
  "request*": "object"
}
```

## preview_move_external_items
**Description:** Preview explicit cross-target migration of external items.
**tool_arguments:**
```json
{
  "source_target*": "string",
  "destination_target*": "string",
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_planner_repair
**Description:** Preview local Planner OS consistency repairs.
**tool_arguments:**
```json
{}
```

## preview_recurrence
**Description:** Preview generated occurrences for a recurrence definition.
**tool_arguments:**
```json
{
  "request*": "object"
}
```

## preview_undo
**Description:** Preview restoring a workbook backup referenced by Decision Log.
**tool_arguments:**
```json
{
  "decision_id": "string"
}
```

## preview_week_plan
**Description:** Preview an explicit workbook week or date range without writing.
**tool_arguments:**
```json
{
  "request*": "object"
}
```

## publish_current_week
**Description:** Publish current week using only the active execution target.
**tool_arguments:**
```json
{}
```

## publish_date
**Description:** Publish one date using only the active execution target.
**tool_arguments:**
```json
{
  "date*": "string"
}
```

## publish_range
**Description:** Publish a range using only the active execution target.
**tool_arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## publish_today
**Description:** Publish today using only the active execution target.
**tool_arguments:**
```json
{}
```

## replan_today_from_now
**Description:** Replan today from the current time without writing.
**tool_arguments:**
```json
{
  "current_datetime": "string"
}
```

## reset_preference
**Description:** Reset one preference when a safe built-in reset exists.
**tool_arguments:**
```json
{
  "name*": "string"
}
```

## resume_recurrence
**Description:** Resume a workbook-backed recurrence definition.
**tool_arguments:**
```json
{
  "recurrence_id*": "string"
}
```

## route_planner_command
**Description:** Route one validated structured planner command safely.
**tool_arguments:**
```json
{
  "command*": "object"
}
```

## set_active_execution_target
**Description:** Set future publishing target without moving existing items.
**tool_arguments:**
```json
{
  "target*": "string"
}
```

## set_apple_calendar
**Description:** Persist the selected Apple Calendar identifier.
**tool_arguments:**
```json
{
  "calendar_id*": "string"
}
```

## set_no_work_days
**Description:** Set no-work days.
**tool_arguments:**
```json
{
  "days*": "array"
}
```

## set_work_days
**Description:** Set active work days.
**tool_arguments:**
```json
{
  "days*": "array"
}
```

## status
**Description:** Return progress status and active slippage alerts.
**tool_arguments:**
```json
{}
```

## undo_last_change
**Description:** Undo the most recent workbook change with a Decision Log backup.
**tool_arguments:**
```json
{}
```

## update_dated_task
**Description:** Update a workbook-backed exact-date task.
**tool_arguments:**
```json
{
  "task_id*": "string",
  "changes*": "object"
}
```

## update_preference
**Description:** Update one planner preference through a validated local store.
**tool_arguments:**
```json
{
  "name*": "string",
  "value*": "string"
}
```

## update_rule
**Description:** Update an existing permanent rule path.
**tool_arguments:**
```json
{
  "path*": "string",
  "value*": "string"
}
```

## update_task
**Description:** Update an existing task.
**tool_arguments:**
```json
{
  "task_name*": "string",
  "month": "string",
  "new_name": "string",
  "category": "string",
  "priority": "string",
  "target_week": "string",
  "status": "string",
  "notes": "string"
}
```

## validate
**Description:** Check workbook readability, rules, and planner structure.
**tool_arguments:**
```json
{}
```

## weekly_review
**Description:** Generate a read-only weekly review.
**tool_arguments:**
```json
{
  "date": "string"
}
```
