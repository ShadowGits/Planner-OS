# Dashboard wiring: Streamlit on the same Supabase project (no Excel)

How to point the Streamlit dashboard at the **same** Supabase project the bot,
MCP, and PWA already use — read-only, with **no new tables**, and with the Excel
workbook removed from the loop entirely.

## 1. Principles

- **One project, one source of truth.** The dashboard reads the same tables the
  rest of Planner OS writes. Do **not** spin up a second Supabase project — a
  dashboard is a *view*, not a separate store.
- **Read-only.** The dashboard never writes. Writes happen through Claude chat
  (MCP), the Telegram bot, and the PWA. This keeps the data honest and means a
  dashboard bug can never corrupt the planner.
- **No new tables needed.** Everything a dashboard shows is derivable from the
  five existing tables (below). The only *optional* table you'd ever add is one
  for dashboard preferences (saved layout / custom targets) — skip it until you
  actually miss it; for a single user a config value does the job.

## 2. What each table already gives the dashboard

| Table | Feeds |
| --- | --- |
| `projects` | Track list, per-track % done, `target_date` countdowns |
| `milestones` | Milestone progress, upcoming deadlines (`target_date`) |
| `planner_tasks` | Open / overdue / done counts, per-project totals, today's plan (`scheduled_date`, `start_time`) |
| `task_completions` | **The time-series.** Every tick is a timestamped row → streaks, "completed today", completions-over-time charts |
| `reminder_log` | What reminders went out and when (optional audit widget) |

`task_completions` is the key insight: because each completion is its own dated
row, trend charts ("units done per day/week") need **no new storage** — they are
just `GROUP BY` over rows you already have.

## 3. Two ways to connect (pick per widget)

### Option A — read the computed snapshot over HTTP (preferred for headline numbers)

`MetricsService.snapshot()` already computes projects, deadlines, streaks, and
totals. Reuse it instead of re-deriving "% done" in a second codebase.

**Why not `/v2/metrics`:** that route is gated behind OAuth login
(`Depends(current_user)`), which a headless Streamlit app can't satisfy with a
simple key. So there is a dedicated, key-guarded route for the dashboard:

**`GET /v2/dashboard/metrics`** (in `planner_api/dashboard.py`) — same
`X-App-Key` trust model as the PWA. It returns the full computed snapshot plus
the flat map:

```json
{ "data": { "snapshot": { "totals": {...}, "projects": [...],
                          "upcoming_deadlines": [...], "streaks": {...} },
            "flat": { "german_units_left": "12", ... } } }
```

Auth: set `DASHBOARD_ACCESS_KEY` on Cloud Run (or leave it unset to fall back to
`PWA_ACCESS_KEY`). Send it as the `X-App-Key` header.

Streamlit side:

```python
import streamlit as st, requests
BASE = "https://planner-os-api-645411441153.us-central1.run.app"
r = requests.get(f"{BASE}/v2/dashboard/metrics",
                 headers={"X-App-Key": st.secrets["APP_KEY"]}, timeout=10)
data = r.json()["data"]["snapshot"]
st.metric("Open tasks", data["totals"]["open_tasks"])
st.metric("Completed today", data["totals"]["completed_today"])
for p in data["projects"]:
    st.progress(p["completion_pct"] / 100, text=f'{p["name"]} · {p["completion_pct"]}%')
```

### Option B — connect Streamlit straight to Supabase Postgres (for custom charts)

Use the project's Postgres connection string for raw, ad-hoc queries the API
doesn't pre-compute. Use a **read-only** role or the anon/service key stored in
Streamlit secrets — never hard-coded.

```python
# .streamlit/secrets.toml
# [connections.supabase]
# url = "postgresql://<readonly_user>:<pwd>@<host>:5432/postgres?sslmode=require"

conn = st.connection("supabase", type="sql")
daily = conn.query("""
    select completed_on::date as day, count(*) as done
    from task_completions
    group by 1 order by 1
""", ttl=300)
st.line_chart(daily, x="day", y="done")
```

Get the connection string from **Supabase → Project Settings → Database →
Connection string** (use the *pooler* / "Session" string for serverless hosts
like Streamlit Cloud).

### Recommendation

Do **both, in order**: Option A for the headline metric tiles and progress bars
(one place owns the math, no DB creds in the dashboard), and drop to Option B
only for a couple of custom time-series charts where raw SQL is easier. Same
Supabase project for both.

## 4. Removing Excel completely

Once the dashboard reads Postgres, the Excel path is dead weight and can go:

- The dashboard stops importing/parsing any `.xlsx`; it reads the DB/API instead.
- `MetricsService.flat_snapshot()` exists **only** to shape data for the old
  Excel "Planner_Snapshot" sheet. Keep it while anything still consumes the flat
  map; delete it once the dashboard uses `snapshot()` directly.
- The workbook bucket (`workspaces.workbook_bucket` / `workbook_key` /
  `workbook_sha256`, revisions) is the Excel-centric storage. Going
  Postgres-native, nothing new is written there; it can be retired later.
- Net result: writes → Postgres (MCP / Telegram / PWA); reads → Postgres
  (dashboard). Excel is out of the loop.

## 5. Secrets & safety

- Store the API key (`APP_KEY`) or the DB connection string in **Streamlit
  secrets**, never in the repo.
- Prefer a **read-only** Postgres role for Option B so the dashboard physically
  cannot write.
- Both the dashboard and the planner point at the **same** project — that's the
  whole point; do not duplicate the database.

## 6. Storage outlook

Planner rows are tiny text records. A heavy year is on the order of ~10–50 MB,
so the 0.5 GB free tier has years of headroom. The dashboard adds effectively
zero storage — it reads, it does not accumulate rows. The only thing that grows
meaningfully is the Excel workbook bucket, which retiring Excel removes.
