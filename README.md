# Planner OS

Planner OS MVP3 adds an authenticated local/cloud interface while preserving the workbook-first planner, local CLI, and STDIO MCP. See [MVP3 deployment](docs/mvp3_deployment.md) for Supabase migrations, Vercel configuration, Google OAuth, and the two-user release check.

Planner OS is a workbook-first planner with local and authenticated cloud modes.
Excel is the source of truth; the CLI, STDIO MCP, web app, and API are interfaces
over Planner Engine.

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
