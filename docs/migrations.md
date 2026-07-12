# Local Migration Notes

No workbook, OAuth token, calendar-event, or rules migration is required.

On first execution-target use, Planner OS creates ignored local files under
`.planner-os/`:

- `execution-settings.json`
- `external-links.json`
- `execution-previews/`
- `bin/planner-apple-calendar` after the user builds the native helper

The initial target defaults to `google_calendar` for backward compatibility.
Existing external items are not imported or moved automatically. Their future
migration must be explicitly previewed and applied.

## Retired target migration

Older local settings that selected the retired Structured downstream target are backed up
and changed to `none`. Old external-link records are backed up and marked
`retired_unsupported`; they are never relabeled as Apple Calendar links and no
external data is deleted. The user must explicitly choose Google Calendar or
Apple Calendar.
