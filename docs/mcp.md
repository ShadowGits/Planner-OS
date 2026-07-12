# MCP Tool Reference

The complete signatures, payload schemas, side effects, safety rules, and CLI
equivalents are documented in [`technical_reference.md`](technical_reference.md).

MVP2 execution tools:

- `list_execution_targets`
- `get_active_execution_target`
- `set_active_execution_target`
- `preview_execution_target_switch`
- `apply_execution_target_switch`
- `preview_move_external_items`
- `apply_move_external_items`
- `publish_today`
- `publish_date`
- `publish_range`
- `publish_current_week`
- `apple_calendar_status`
- `apple_calendar_calendars`
- `create_apple_calendar`
- `set_apple_calendar`
- `apple_calendar_list_range`
- `apple_calendar_reconcile_range`
- `apple_calendar_update_event`
- `apple_calendar_delete_event`
- `preview_apple_calendar_delete_range`
- `apply_apple_calendar_delete_range`
- `planner_doctor`
- `list_preferences`
- `get_preference`
- `update_preference`
- `reset_preference`
- `explain_active_constraints`
- `preview_planner_repair`
- `apply_planner_repair`
- `preview_undo`
- `apply_undo`
- `undo_last_change`
- `preview_recurrence`
- `apply_recurrence`
- `list_recurrences`
- `pause_recurrence`
- `resume_recurrence`
- `preview_goal_plan`
- `apply_goal_plan`

Google Calendar CRUD tools include range listing, stable-ID lookup, exact event
update/delete, recurring series/future deletion, previewed range deletion,
reconciliation, previewed orphan cleanup, and mapping repair.

Generic publish tools resolve the persistent active target and never publish to
both downstream targets. Existing Planner OS MCP tools remain available.
