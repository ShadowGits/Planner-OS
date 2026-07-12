# Planner OS

Planner OS is a single-user, local, workbook-first planner. Excel is the source
of truth; the CLI and STDIO MCP are thin interfaces over Planner Engine.

## Active execution target

Exactly one downstream target is active: `google_calendar`, `apple_calendar`, or
`none`. Selection persists in `.planner-os/execution-settings.json`.

```sh
shadow execution-target list
shadow execution-target switch-preview apple_calendar
shadow execution-target switch-apply PREVIEW_ID
shadow publish today
```

A target switch never moves or deletes existing external items. Use
`move-preview` and `move-apply` for an explicit migration.

Apple Calendar uses a native EventKit helper. See
`planner_integrations/apple_calendar/README.md` for build and permission setup.

See `docs/technical_reference.md` for the complete public function reference.
Focused guides remain in `docs/cli.md`, `docs/mcp.md`, and
`docs/migrations.md`.
