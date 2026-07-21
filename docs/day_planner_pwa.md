# Day Planner PWA

A Structured-style day timeline served by the Planner OS API at `/app`.
It reads and writes the v2 Postgres tables, so ticking a task here updates
the same data the Telegram bot, MCP tools, and dashboard metrics see.

## Features

- Vertical day timeline with hour grid, "now" line, and week strip
- Tap a task's icon circle to mark it done (green check, strikethrough)
- Press-and-hold a card, then drag to move it to a new time (5-minute snap)
- Inbox tray for tasks on the day without a start time; one tap schedules
  them into the next free slot
- "+" button quick-adds a task with start time and duration
- Installable on iPhone, iPad, and Mac: open `/app` in Safari →
  Share → Add to Home Screen / Dock
- Light and dark themes follow the system setting

## Deploy configuration

1. Apply migration `supabase/migrations/0007_task_start_time.sql`
   (adds `planner_tasks.start_time`; run in the Supabase SQL editor).
2. Set an access key on the Cloud Run service:

   ```bash
   gcloud run services update planner-os \
     --region <region> \
     --update-env-vars PWA_ACCESS_KEY=<long-random-string>
   ```

3. Open `https://<service-url>/app/`, enter the key once per device.

The app authenticates with the `X-App-Key` header and acts on the
workspace of `MCP_USER_ID` — the same single-user model as the Telegram
webhook.

## API surface

| Route | Method | Purpose |
| --- | --- | --- |
| `/v2/day?date=YYYY-MM-DD` | GET | Tasks for one date (timeline + inbox) |
| `/v2/day/tasks` | POST | Quick-add a task to a date |
| `/v2/day/tasks/{id}` | PATCH | Tick/untick (`done`), reschedule (`start_time`, `scheduled_date`), resize (`estimated_minutes`), rename (`title`) |

Unticking removes the task's completion rows for the day, so streaks and
`done_count` stay honest.
