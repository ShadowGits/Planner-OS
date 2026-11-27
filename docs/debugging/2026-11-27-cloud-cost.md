# Cloud usage audit — November 27, 2026

## Verified billing snapshot

Read from the signed-in Google Cloud Billing console. Project grouping confirmed
all reported charges belong to `planner-os-502107` (Planner OS). Reported subtotal
for November 1–27: **₹155.84**. Tax is not shown in this report. Billing data lags
Monitoring; do not equate their different capture cutoffs.

| Billed item | Usage shown | Net subtotal |
| --- | --- | ---: |
| Cloud Run CPU, request-based | 224,123.06 seconds | ₹100.85 |
| Cloud Run international data transfer | 0.60 GiB | ₹6.87 |
| Cloud Run carrier-peering data transfer | 2.28 GiB | ₹4.35 |
| Artifact Registry storage | 5.09 GiB-month | ₹43.75 |
| Cloud Storage | rounded small storage/operations | ₹0.02 |
| Cloud Run memory | 223,462.60 GiB-seconds; fully offset | ₹0.00 |
| **Total** | | **₹155.84** |

Cloud Run service subtotal: ₹112.07. Its gross usage charge is ₹576.67 before
₹464.60 savings. Monetary columns are rounded independently. Request count is
well below the free allowance; the dominant charge is allocated CPU time,
not a per-request fee. The report's forecast is inconsistent with its accrued
total; do not rely on it for a new estimate.

[Daily billing report](https://console.cloud.google.com/billing/014930-210994-EA30FD/reports;timeGrouping=GROUP_BY_DAY?project=planner-os-502107)

## Actual daily costs from the chart

| Local calendar date | Cloud Run | Artifact Registry | Total shown |
| --- | ---: | ---: | ---: |
| November 22 | ₹8.080 | ₹1.993 | ₹10.07 |
| November 23 | ₹23.679 | ₹1.993 | ₹25.67 |
| November 24 | ₹27.048 | ₹1.993 | ₹29.04 |
| November 25 | ₹22.396 | ₹0.698 | ₹23.10 |
| November 26 | ₹19.145 | ₹0.027 | ₹19.17 |
| November 27, partial/lagging | ₹4.983 | ₹0.004 | ₹4.99 |

Cloud Storage contributes small fractions of a rupee to some daily totals.
Registry cleanup has reduced ongoing cost; the ₹43.75 is accrued usage, not the
current daily rate. Current inventory contains one serving digest, 91,076,061
bytes compressed, referenced by several tags. Tags are not separate image copies.

## Before/after production usage

Monitoring through `2026-11-27T17:00:00Z`. The comparison below uses full UTC days.
October CPU total was 140,256 seconds, averaging 4,524/day over 31 days.

| Metric | Nov 24, before rollout | Nov 26, after rollout |
| --- | ---: | ---: |
| Allocated CPU seconds | 10,584.78 | 8,433.94 |
| Requests | 8,417 | 4,113 |
| Container bytes sent | 290,155,800 | 116,738,508 |

Requests fell about 51%, bytes about 60%, but allocated CPU only about 20%.
Nov 26 CPU remains about twice the 4,200/day maximum target. No claim is made
that the 60–70% monthly target has been achieved.

## Exact request breakdown

Window: **Nov 26 00:00–24:00 UTC**, which is **Nov 26 05:30 through Nov 27 05:30 IST**.
All 4,113 request logs were retrieved; totals match Cloud Monitoring. This is a
different boundary from the billing console's local calendar-day chart.

| Endpoint | Requests | Mean seconds | Sum of request seconds | Estimated active-time share |
| --- | ---: | ---: | ---: | ---: |
| `POST /v2/reminders/run` | 1,439 | 4.432 | 6,378.01 | 75.81% |
| `GET /v2/day` | 1,117 | 3.397 | 3,794.27 | 10.54% |
| `GET /v2/week` | 375 | 4.383 | 1,643.73 | 6.36% |
| `POST /v2/calendar/sync` | 24 | 14.279 | 342.70 | 3.72% |
| `GET /v2/day/inbox` | 375 | 2.337 | 876.21 | 2.01% |
| `GET /v2/day/planning-context` | 369 | 1.160 | 428.19 | 0.82% |
| `GET /v2/native/dashboard` | 370 | 0.789 | 291.94 | 0.56% |
| `PATCH /v2/day/tasks/habit:{id}:2026-11-26` | 4 | 1.787 | 7.15 | 0.08% |
| `POST /mcp` | 12 | 0.347 | 4.16 | 0.03% |
| `POST /token` | 1 | 2.461 | 2.46 | 0.03% |
| `PATCH /v2/day/tasks/habit:{id}:2026-11-27` | 1 | 1.821 | 1.82 | 0.02% |
| `GET /app/icon-180.png` | 26 | 0.004 | 0.10 | 0.00% |

No direct Fit/Plan endpoint calls were present. Request logs do not identify
the individual tools inside `/mcp`, so they cannot prove the absence of every
possible planning tool invocation. Five task PATCHes were present.

**Attribution limit:** per-route billing is not supplied by Google. The last
column splits concurrent active-instance time equally among simultaneous requests.
It is an estimate, not exact CPU billing by endpoint. Summed request durations
overlap; do not add them and label the result billed CPU. Logged request interval
union is 8,208.40 seconds; Monitoring CPU allocation is 8,433.94 seconds.

Caller counts: Planner OS native app 2,611; Cloud Scheduler 1,463 (1,439 reminder
checks and 24 calendar syncs); browser icon fetches 26; Claude MCP 12; token
refresh 1. The native app can refresh while open/minimized without Fit/Plan use.

## Why October was cheaper

Cloud Audit Logs confirm:

- September 13 20:32 UTC: reminder schedule set to `*/5 * * * *`.
- **October 24 10:33:26 UTC / 16:03:26 IST:** changed to `* * * * *`.
- October 24 commit `4359f83` introduced one ten-minute alert with a 9–10 minute
  delivery window and explicitly documented this production schedule change.
- Checks therefore increased from about 288/day to 1,440/day. Most of October
  used the lower frequency; November is the first full month at the higher one.
- November 22 approximately exhausted the monthly CPU allowance. Increased client
  activity near that date compounded usage; the schedule change itself was October 24.

The Nov 25 fix reduced client traffic and registry retention. It did **not**
replace the reminder job's repeated database reconstruction. That was the major
missed optimization, and is now the dominant remaining cost.

## Why a no-alert check makes so many calls

A read-only profile using current production data, representing a 15:00 check,
returned **zero due reminders** yet issued 12 database HTTP calls. Writes and
notification delivery were blocked by the profiling client. No task content or
credentials were saved. This is a present-data sample, not a historical trace of
all 1,439 executions.

| Database endpoint | HTTP calls in sample |
| --- | ---: |
| workspaces | 1 |
| finance_recurring | 1 |
| reminder_log | 2 |
| planner_tasks | 3 |
| habits | 2 |
| habit_overrides | 1 |
| task_completions | 2 |

Eight logical selects became twelve HTTP calls because several nonempty reads
also fetch an empty next page to prove pagination is complete. The code reads
workspace metadata, recurring-finance rules, today's delivery ledger, timed tasks,
split-child references, habit rules, overrides and completions. Conditional daily
reports can perform additional work. A raw single request spends seconds waiting
for serial database network responses while Cloud Run CPU stays allocated.

## Current availability and spend cap

The console confirms an enforced **₹75** cap named `100 budget`, scoped to Cloud
Run in Planner OS, triggered **Nov 27 at 23:02:24 IST**. The cap tracks gross,
estimated costs (about ₹580.58 at inspection), excludes savings, and resets
December 1. The separate ₹100 monthly budget is an alert, not this enforcement.
The backend returned HTTP 503 during this audit. No cap was changed or lifted.

A gross-cost ₹75 cap is not a promise of ₹75 net charges after free-tier credits.
[Google spend-cap documentation](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

## Rebuild direction

Use a durable, indexed due-reminder queue maintained when source data changes.
A database-local scheduler should check that queue and contact Cloud Run only
when work is due. Move recurring finance and daily summaries out of the minute
reminder reconstruction path. See `../reminder_queue_design.md` for the concrete
architecture and migration/verification requirements.

Read-only raw metrics, sanitized request records, billing table captures, schedule
audit entries and profile aggregates remain under `/tmp/planner-usage-audit-2026-11-27`.
No app, scheduler, database schema, billing limit or production setting was changed
by this audit. New audit/design documentation is local until explicitly published.

## Subsequent user-approved temporary rollback

After this audit, the user explicitly selected five-minute checks and accepted
alerts arriving 5–10 minutes before a task. Updated only `planner-reminders`
schedule to `*/5 * * * *`, preserving its timezone, target and authentication.
Prepared the matching server-only five-minute window, truthful countdown text,
existing delivery-key deduplication and midnight handling. Native callers keep
the narrower window and existing wording; Apple apps were not changed.

309 targeted tests passed, including all 60 possible task-start minutes,
midnight delivery, authentication, Telegram fallback, native-window separation
and cost/storage regressions. The spend cap remains enforced. Final deployment
results are recorded in the local rollout log; the full queue is still a design.
