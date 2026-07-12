# CLI Reference

The complete CLI and MCP inventory, structured payload schemas, side effects,
and persistence map are documented in
[`technical_reference.md`](technical_reference.md).

## Execution targets

```sh
shadow execution-target list
shadow execution-target get
shadow execution-target set google_calendar
shadow execution-target set apple_calendar
shadow execution-target set none
shadow execution-target switch-preview apple_calendar
shadow execution-target switch-apply PREVIEW_ID
shadow execution-target move-preview google_calendar apple_calendar 2026-07-13 2026-07-19
shadow execution-target move-apply PREVIEW_ID
```

`set` is retained for explicit administrative use. Conversational workflows
should use switch preview/apply.

## Generic publishing

```sh
shadow publish today
shadow publish date --date 2026-07-13
shadow publish current-week
shadow publish range --start 2026-07-13 --end 2026-07-19
```

These commands publish only through the active target. With `none`, they report
that external publication was skipped.

## Apple Calendar

```sh
shadow apple-calendar calendars
shadow apple-calendar status
shadow apple-calendar create-calendar --title "Planner OS"
shadow apple-calendar select CALENDAR_ID
shadow apple-calendar publish-today
shadow apple-calendar publish-date 2026-07-13
shadow apple-calendar publish-range 2026-07-13 2026-07-19
shadow apple-calendar list-range 2026-07-13 2026-07-19
shadow apple-calendar reconcile-range 2026-07-13 2026-07-19
shadow apple-calendar delete-event EVENT_ID
shadow apple-calendar update-event EVENT_ID --title "German" --start 2026-07-13T18:00:00 --end 2026-07-13T18:30:00
shadow apple-calendar delete-range-preview 2026-07-13 2026-07-19
shadow apple-calendar delete-range-apply PREVIEW_ID
```

## Diagnostics

```sh
shadow doctor
```

`doctor` is read-only. Repairs remain preview-first and are not exposed as
automatic mutations in this build.

## Preferences

```sh
shadow preferences list
shadow preferences get active_execution_target
shadow preferences update active_execution_target apple_calendar
shadow preferences update no_work_days '["Saturday","Sunday"]'
shadow preferences reset active_execution_target
shadow preferences explain-active-constraints
```

Preference writes are validated through the same local rules and execution
settings stores used by the planner.

## Repair And Undo

```sh
shadow doctor
shadow repair preview
shadow repair apply PREVIEW_ID
shadow undo preview
shadow undo preview --decision-id DECISION_ID
shadow undo apply PREVIEW_ID
shadow undo last
```

Repair is local and preview-first. Undo restores only workbook backups that are
referenced by Decision Log records, and creates a fresh backup before restoring.
It does not claim external calendar reversal.

## Recurrence

```sh
shadow recurrence preview --title "German" --frequency daily --start-date 2026-07-13 --count 7 --minutes 30 --daypart evening
shadow recurrence apply PREVIEW_ID
shadow recurrence list
shadow recurrence pause RECURRENCE_ID
shadow recurrence resume RECURRENCE_ID
```

Recurrence definitions are stored in the hidden workbook sheet `_RECURRENCES`.
Generated occurrences are written as dated tasks only after apply.

## Goal Plans

```sh
shadow goal preview --title "Finish German A1" --start-date 2026-07-10 --target-date 2026-07-31 --category learning --allowed-day Monday --allowed-day Wednesday --daypart evening
shadow goal apply PREVIEW_ID
```

Goal planning is deterministic and structured-input only. Preview stores the
workbook revision and apply rejects stale previews. Calendar publication is not
automatic.

## Google Calendar CRUD

```sh
shadow calendar list-range 2026-07-13 2026-07-19
shadow calendar lookup-event PLANNER_BLOCK_ID 2026-07-13 2026-07-19
shadow calendar update-event EVENT_ID --title "German" --start 2026-07-13T18:00:00 --end 2026-07-13T18:30:00
shadow calendar delete-event EVENT_ID
shadow calendar delete-series EVENT_ID
shadow calendar delete-future-series EVENT_ID
shadow calendar delete-range-preview 2026-07-13 2026-07-19
shadow calendar delete-range-apply PREVIEW_ID
shadow calendar reconcile-range 2026-07-13 2026-07-19
shadow calendar cleanup-orphans-preview 2026-07-13 2026-07-19
shadow calendar cleanup-orphans-apply PREVIEW_ID
shadow calendar repair-mapping EVENT_ID
```

Delete-range and orphan cleanup operations are preview/apply. Exact event
delete/update commands first verify Planner OS ownership metadata.
