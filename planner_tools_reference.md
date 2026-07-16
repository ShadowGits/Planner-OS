# Planner OS Tools Reference
This document contains the exact schemas for all Planner OS tools.
When calling the multiplexed `/api/v1/tools/{tool_name}/invoke` endpoint, you MUST use the exact arguments specified below for the corresponding tool_name.
Arguments marked with an asterisk (*) are required.

## add_dated_task
**Description:** Add a task to one exact workbook date column.
**Arguments:**
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
**Arguments:**
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
**Arguments:**
```json
{}
```

## apple_calendar_delete_event
**Description:** Delete one explicitly identified Planner OS Apple event.
**Arguments:**
```json
{
  "external_id*": "string",
  "delete_scope": "string"
}
```

## apple_calendar_list_range
**Description:** List Planner OS-owned Apple events in a range.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## apple_calendar_reconcile_range
**Description:** Reconcile Apple Calendar events in a range.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## apple_calendar_status
**Description:** Report native Apple Calendar permission and capabilities.
**Arguments:**
```json
{}
```

## apple_calendar_update_event
**Description:** Update one explicitly identified Planner OS Apple event.
**Arguments:**
```json
{
  "external_id*": "string",
  "block*": "object"
}
```

## apply_apple_calendar_delete_range
**Description:** Apply an approved Apple Calendar range deletion.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_calendar_cleanup_orphans
**Description:** Apply an approved orphan cleanup.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_calendar_delete_range
**Description:** Apply an approved Google event range deletion.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_day_replan
**Description:** Apply an explicitly approved day replan.
**Arguments:**
```json
{
  "preview_id": "string",
  "preview": "object"
}
```

## apply_execution_target_switch
**Description:** Apply an approved target-switch preview.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_goal_plan
**Description:** Apply an approved goal plan preview to the workbook.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_month_plan
**Description:** Apply an explicitly approved monthly planning preview.
**Arguments:**
```json
{
  "preview_id": "string",
  "preview": "object"
}
```

## apply_move_external_items
**Description:** Apply an approved explicit cross-target migration.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_planner_repair
**Description:** Apply an approved local repair preview.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_recurrence
**Description:** Apply an approved recurrence preview as dated workbook tasks.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_undo
**Description:** Apply an approved workbook undo preview.
**Arguments:**
```json
{
  "preview_id*": "string"
}
```

## apply_week_plan
**Description:** Apply an explicitly approved weekly planning preview.
**Arguments:**
```json
{
  "preview_id": "string",
  "preview": "object"
}
```

## calendar_delete_event
**Description:** Delete one explicitly identified Planner OS Google event.
**Arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_delete_future_series
**Description:** Delete this and future Planner OS Google recurring events.
**Arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_delete_series
**Description:** Delete a Planner OS Google recurring series.
**Arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_list_range
**Description:** List Planner OS-owned Google events in a range.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_lookup_event
**Description:** Find Google events by stable planner block ID.
**Arguments:**
```json
{
  "planner_block_id*": "string",
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_reconcile_range
**Description:** Reconcile planner blocks with Google Calendar.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_repair_mapping
**Description:** Repair a local mapping from Planner OS Google event metadata.
**Arguments:**
```json
{
  "external_id*": "string"
}
```

## calendar_sync_current_week
**Description:** Sync the Monday-Sunday range containing today.
**Arguments:**
```json
{}
```

## calendar_sync_date
**Description:** Sync exactly one date, including workbook-backed dated tasks.
**Arguments:**
```json
{
  "date*": "string"
}
```

## calendar_sync_month
**Description:** Sync all scheduled blocks in one explicit planner month.
**Arguments:**
```json
{
  "month*": "string"
}
```

## calendar_sync_next_week
**Description:** Sync the Monday-Sunday range after the current week.
**Arguments:**
```json
{}
```

## calendar_sync_range
**Description:** Sync one explicit inclusive date range.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## calendar_sync_today
**Description:** Generate today's plan and sync it to Google Calendar.
**Arguments:**
```json
{}
```

## calendar_sync_week
**Description:** Backward-compatible alias that explicitly syncs current week.
**Arguments:**
```json
{}
```

## calendar_sync_week_number
**Description:** Sync one explicit planner workbook week section.
**Arguments:**
```json
{
  "month*": "string",
  "week_number*": "integer"
}
```

## calendar_update_event
**Description:** Update one explicitly identified Planner OS Google event.
**Arguments:**
```json
{
  "external_id*": "string",
  "block*": "object"
}
```

## complete_task
**Description:** Mark a task complete.
**Arguments:**
```json
{
  "task_name*": "string",
  "month": "string"
}
```

## create_apple_calendar
**Description:** Create and select a dedicated local Apple calendar.
**Arguments:**
```json
{
  "title": "string"
}
```

## daily_checkin
**Description:** Generate a read-only daily progress check-in.
**Arguments:**
```json
{
  "date": "string"
}
```

## daily_review
**Description:** Generate a read-only daily review.
**Arguments:**
```json
{
  "date": "string"
}
```

## delete_dated_task
**Description:** Delete a workbook-backed exact-date task.
**Arguments:**
```json
{
  "task_id*": "string"
}
```

## delete_task
**Description:** Delete a task.
**Arguments:**
```json
{
  "task_name*": "string",
  "month": "string"
}
```

## explain_active_constraints
**Description:** Explain the constraints currently affecting planning and publishing.
**Arguments:**
```json
{}
```

## get_active_execution_target
**Description:** Return the persistent active downstream target.
**Arguments:**
```json
{}
```

## get_preference
**Description:** Read one planner preference.
**Arguments:**
```json
{
  "name*": "string"
}
```

## import_plan
**Description:** Import a structured JSON planner file.
**Arguments:**
```json
{
  "input_path*": "string"
}
```

## list_dated_tasks
**Description:** List workbook tasks assigned to one exact date.
**Arguments:**
```json
{
  "date*": "string"
}
```

## list_execution_targets
**Description:** List supported targets and the one active target.
**Arguments:**
```json
{}
```

## list_preferences
**Description:** List persistent planner preferences and editable aliases.
**Arguments:**
```json
{}
```

## list_recurrences
**Description:** List workbook-backed recurrence definitions.
**Arguments:**
```json
{}
```

## list_rules
**Description:** List permanent planner rules.
**Arguments:**
```json
{}
```

## monthly_review
**Description:** Generate a read-only monthly review.
**Arguments:**
```json
{
  "month*": "string"
}
```

## move_task
**Description:** Move a weekly task to another week.
**Arguments:**
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
**Arguments:**
```json
{
  "text*": "string"
}
```

## pause_recurrence
**Description:** Pause a workbook-backed recurrence definition.
**Arguments:**
```json
{
  "recurrence_id*": "string"
}
```

## plan_today
**Description:** Generate today's schedule without writing to Excel.
**Arguments:**
```json
{}
```

## plan_today_from_now
**Description:** Plan today using only remaining time for flexible blocks.
**Arguments:**
```json
{
  "current_datetime": "string"
}
```

## planner_doctor
**Description:** Run read-only local Planner OS diagnostics.
**Arguments:**
```json
{}
```

## preview_apple_calendar_delete_range
**Description:** Preview exact Planner OS Apple events to delete.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_calendar_cleanup_orphans
**Description:** Preview orphaned Planner OS Google events for cleanup.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_calendar_delete_range
**Description:** Preview exact Planner OS Google events to delete.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## preview_day_replan
**Description:** Preview today's remaining-time replan without writing.
**Arguments:**
```json
{
  "request*": "object"
}
```

## preview_execution_target_switch
**Description:** Preview changing future publishing to one target.
**Arguments:**
```json
{
  "target*": "string"
}
```

## preview_goal_plan
**Description:** Preview deterministic breakdown of a structured goal.
**Arguments:**
```json
{
  "request*": "object"
}
```

## preview_month_plan
**Description:** Preview monthly milestones and dated daily proposals without writing.
**Arguments:**
```json
{
  "request*": "object"
}
```

## preview_move_external_items
**Description:** Preview explicit cross-target migration of external items.
**Arguments:**
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
**Arguments:**
```json
{}
```

## preview_recurrence
**Description:** Preview generated occurrences for a recurrence definition.
**Arguments:**
```json
{
  "request*": "object"
}
```

## preview_undo
**Description:** Preview restoring a workbook backup referenced by Decision Log.
**Arguments:**
```json
{
  "decision_id": "string"
}
```

## preview_week_plan
**Description:** Preview an explicit workbook week or date range without writing.
**Arguments:**
```json
{
  "request*": "object"
}
```

## publish_current_week
**Description:** Publish current week using only the active execution target.
**Arguments:**
```json
{}
```

## publish_date
**Description:** Publish one date using only the active execution target.
**Arguments:**
```json
{
  "date*": "string"
}
```

## publish_range
**Description:** Publish a range using only the active execution target.
**Arguments:**
```json
{
  "start_date*": "string",
  "end_date*": "string"
}
```

## publish_today
**Description:** Publish today using only the active execution target.
**Arguments:**
```json
{}
```

## replan_today_from_now
**Description:** Replan today from the current time without writing.
**Arguments:**
```json
{
  "current_datetime": "string"
}
```

## reset_preference
**Description:** Reset one preference when a safe built-in reset exists.
**Arguments:**
```json
{
  "name*": "string"
}
```

## resume_recurrence
**Description:** Resume a workbook-backed recurrence definition.
**Arguments:**
```json
{
  "recurrence_id*": "string"
}
```

## route_planner_command
**Description:** Route one validated structured planner command safely.
**Arguments:**
```json
{
  "command*": "object"
}
```

## set_active_execution_target
**Description:** Set future publishing target without moving existing items.
**Arguments:**
```json
{
  "target*": "string"
}
```

## set_apple_calendar
**Description:** Persist the selected Apple Calendar identifier.
**Arguments:**
```json
{
  "calendar_id*": "string"
}
```

## set_no_work_days
**Description:** Set no-work days.
**Arguments:**
```json
{
  "days*": "array"
}
```

## set_work_days
**Description:** Set active work days.
**Arguments:**
```json
{
  "days*": "array"
}
```

## status
**Description:** Return progress status and active slippage alerts.
**Arguments:**
```json
{}
```

## undo_last_change
**Description:** Undo the most recent workbook change with a Decision Log backup.
**Arguments:**
```json
{}
```

## update_dated_task
**Description:** Update a workbook-backed exact-date task.
**Arguments:**
```json
{
  "task_id*": "string",
  "changes*": "object"
}
```

## update_preference
**Description:** Update one planner preference through a validated local store.
**Arguments:**
```json
{
  "name*": "string",
  "value*": "string"
}
```

## update_rule
**Description:** Update an existing permanent rule path.
**Arguments:**
```json
{
  "path*": "string",
  "value*": "string"
}
```

## update_task
**Description:** Update an existing task.
**Arguments:**
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
**Arguments:**
```json
{}
```

## weekly_review
**Description:** Generate a read-only weekly review.
**Arguments:**
```json
{
  "date": "string"
}
```
