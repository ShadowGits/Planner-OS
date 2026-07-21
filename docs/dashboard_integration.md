# Deutschland-Dash ↔ Planner OS integration handoff

This file is the shared contract between two Claude sessions:
- **Planner OS session** — owns the backend API (`/v2/metrics`) and the Postgres
  project/task data.
- **Dashboard session (you)** — owns this Streamlit app and its deployment.

Keep this file the single source of truth for the integration. If the API shape
changes, it changes here first.

## The big picture

The user is moving to Germany for an Applied Mathematics master's. Work is tracked
in **three places today** that we are slowly merging into one:

1. **Excel workbook (Planner OS)** — daily tasks, publishes to Google Calendar →
   Structured app. Owns the **German A1 rollup** (70 sequential units).
2. **Postgres (Planner OS v2)** — the new **strategic layer**: projects, milestones,
   deadlines, streaks. Read via `/v2/metrics`. This is NEW.
3. **This dashboard's own workbook** — Study/maths goals, documents, finance sheets.

The dashboard is the "stand back and see the mission" view. It should show the
strategic layer (projects + milestones + deadline countdown) that the daily task
grind hides.

## What is live right now

- Base URL: `https://planner-os-api-645411441153.us-central1.run.app`
- `GET /v2/metrics` — requires `Authorization: Bearer <token>`. For a server-to-server
  read from the dashboard, use the MCP API key as the bearer (same key already used
  for the connector). Do NOT hardcode it — read from an env var (`PLANNER_API_TOKEN`).

### `/v2/metrics` response shape

```json
{
  "success": true,
  "data": {
    "snapshot": {
      "generated_on": "2026-07-21",
      "timezone": "Asia/Kolkata",
      "projects": [
        {
          "id": "uuid", "name": "Colleges", "track": "germany-move",
          "status": "active", "target_date": null, "days_to_target": null,
          "total_tasks": 3, "open_tasks": 3, "completion_pct": 0.0,
          "milestones_total": 1, "milestones_done": 0,
          "next_milestone": {"name": "Shortlist finalized", "target_date": "2026-10-15", "status": "not_started"}
        }
      ],
      "upcoming_deadlines": [
        {"kind": "milestone", "name": "APS certificate obtained", "date": "2026-10-31", "days_left": 102, "overdue": false}
      ],
      "streaks": {"gym": 1, "german": 0},
      "totals": {"open_tasks": 15, "overdue_tasks": 0, "completed_today": 2, "completions_last_7_days": 2}
    },
    "flat": {
      "open_tasks": "15",
      "germany_move_units_total": "3",
      "...": "..."
    }
  }
}
```

## CRITICAL: do not clobber the German rollup

The dashboard already derives German A1 progress from the workbook snapshot key
`german_units_left` (total 70). That pipeline **works** and must keep working.

The `flat` block from `/v2/metrics` uses project *track/name* slugs
(e.g. `germany_move_*`), NOT `german_*`. **Do not overwrite `german_units_left`
with anything from `/v2/metrics`.** German stays sourced from the workbook until the
full system merge. Treat `/v2/metrics` as *additive*: use it only for the new
project/milestone/deadline widgets.

## Recommended integration (additive, safe)

1. New module `backend/planner_api.py`: `fetch_metrics()` → GET `/v2/metrics`,
   returns `data.snapshot`. Fail soft: on any error return `None` and let the page
   show "strategic view unavailable" rather than crashing.
2. New page or Home section "Mission Control":
   - Project cards: name, `completion_pct`, `open_tasks`, `next_milestone`.
   - Deadline countdown list from `upcoming_deadlines` (color by `days_left`,
     red if `overdue`).
   - Streak chips from `streaks`.
3. Leave every existing page (German, Study, Finance) untouched.

## Deployment notes

- Set `PLANNER_API_TOKEN` in the deploy environment (Streamlit secrets / host env).
- The API host is public; the token gates it. Never commit the token.

## Open decisions (waiting on the user)

- **Math**: not yet in Postgres. Decide whether to add a "Mathematics" project +
  milestones, or keep maths on the existing Study page.
- **Full merge (post-trial)**: make Postgres the source of truth, import the 70
  German units + all workbook tasks, and let Postgres publish to the calendar.
  Until then the dashboard reads German from the workbook and strategy from the API.
