# Reminder delivery queue redesign

Status: proposed architecture, November 27, 2026. Not implemented or deployed.
The production audit is in `debugging/2026-11-27-cloud-cost.md`.

## Decision

Store scheduled delivery work when the underlying task or habit changes. Check
an indexed due-work queue inside Postgres. Wake Cloud Run only when work is due.
Keep existing task/habit records and existing reminder behavior.

The current scheduled HTTP request reconstructs reminders from workspace,
finance, history, task and habit data every minute. A measured ordinary check
with no alert due made eight logical reads / twelve HTTP calls. Combining those
reads alone would retain unnecessary reconstruction and idle Cloud Run wakeups.

Supabase supports database-local Cron SQL/functions and asynchronous HTTP via
pg_net. Confirm these extensions are available and enabled on this actual
project before applying the design; provider support is not evidence that they
are already enabled here.

## Data model

Add a tenant-scoped `reminder_jobs` table with:

| Field | Purpose |
| --- | --- |
| id, user_id, workspace_id | Identity and tenant ownership |
| source_type, source_key | Task, habit occurrence, or scheduled daily work |
| dedup_key | Existing kind/occurrence/delivery-date identity |
| deliver_at, expires_at | UTC delivery time and valid delivery window |
| version | Increment when a schedule or relevant source field changes |
| status | pending, leased, sent, cancelled, expired, failed |
| lease_token, lease_until | Prevent simultaneous workers claiming the same work |
| attempts, next_attempt_at | Bounded retry control |
| payload | Small delivery fields; never full notes or metadata |
| created_at, updated_at | Operational diagnostics |

Use composite tenant foreign keys and RLS consistent with existing tables.
Restrict claiming, acknowledgement and dispatcher configuration to trusted
backend/database roles. Clients must not gain access to credentials or other
tenants' notification work. Preserve the existing delivery ledger.

The critical index is a partial index over pending work ordered by eligibility:

```sql
create index reminder_jobs_pending_due
on public.reminder_jobs (next_attempt_at, deliver_at)
where status = 'pending';
```

This is a design sketch, not an application-ready migration. Claiming also
checks expiry, tenant scope, current source status and version. Use a unique
constraint on tenant plus dedup_key. Rescheduling advances the version of the
same pending job; it must not revive an already delivered daily alert.

## Update scheduling at the source

Use database triggers/outbox records so changes from Apple, Android, PWA, MCP
and calendar sync follow the same lifecycle. Do not rely on one app calling a
new scheduling endpoint.

- Timed task creation schedules its existing ten-minute alert.
- Time/date changes update that job. Completion, skip or deletion cancels it.
- Reopening a still-future task restores eligible work under the existing
  delivery-date deduplication rules. Split parents remain excluded.
- Title/duration changes update only the relevant delivery fields.
- Ignore updates whose scheduling-relevant values have not changed. A calendar
  sync rewriting unchanged metadata must not regenerate notifications.
- Habit rule, override, move, skip and completion changes mark the affected
  schedule for regeneration. Reuse the existing habit occurrence and timezone
  policy instead of creating a second independent interpretation of recurrence.
- Maintain a bounded rolling horizon for habits. Refill once daily and after
  relevant changes. A rebuild runs only when that work exists, not every minute.
  Include overrides moved in from dates outside the horizon.
- Workspace timezone changes invalidate/rebuild affected future jobs.

Store queue/outbox changes in the same transaction as their source mutation.
External notification network work must run after commit and must not hold up
the task save. Completed or cancelled operational queue rows can be cleaned up
after three days; existing task data and reminder history are not deleted.

## Idle path

Supabase Cron runs a small SQL function locally once per minute. It checks only
the indexed eligibility fields. It issues an HTTP wakeup only when due work or
a due retry exists. An empty queue results in:

- one small database-local eligibility check;
- zero HTTP calls to Cloud Run;
- zero database HTTP round trips for the reminder worker;
- zero Cloud Run CPU time for that empty reminder check.

This does not claim zero database CPU. It removes the repeated network/server
work, rather than moving the same eight-table scan into a database cron.

## Delivery path

1. The database wakes an authenticated `/v2/reminders/dispatch` handler only
   when work is eligible. Do not send a huge snapshot in that wakeup.
2. One claim RPC atomically leases due work using `FOR UPDATE SKIP LOCKED` and
   returns only valid delivery fields and current recipient information. Check
   task completion/cancellation and source version before returning work.
3. Send existing web push / Telegram messages with the current wording and
   fallback policy. Reuse stable push tags and delivery keys.
4. One acknowledgement RPC records successful deliveries, applies retry state
   and handles expired subscriptions. Match lease token and version so a stale
   worker cannot overwrite a newly rescheduled or cancelled job.

Expected ordinary delivery overhead is one claim/read HTTP call and one
acknowledgement/write HTTP call for the due group, plus actual notification
provider calls. The existing sender must accept pre-resolved recipients;
calling its old subscription-fetching path again would reintroduce reads.

Retry persistent work when delivery fails, with backoff and an expiry. A lost
async wakeup is recoverable from the durable pending job. Expired minute-window
alerts must not flood the user after an outage or spend-cap pause. Expired
leases may be reclaimed; multiple workers must not send the same live lease.

Do not promise end-to-end exactly-once notification delivery: a crash after an
external provider accepts a message but before acknowledgement can be ambiguous.
Document channel-specific handling, deduplicate with existing keys/tags, and
test this failure path instead of hiding it.

## Separate daily work

Morning brief, evening report, deadline summary and recurring finance get their
own due work. Their calculations run at delivery time, once when required.
Recurring finance rules schedule their next due work and catch up safely after
an outage. Newly created/changed due rules trigger work immediately; moving to
daily scheduling must not make a newly due charge wait until tomorrow.

Preserve the current daily-report windows and behavior when relevant tasks
change after an initially empty summary. Preserve once-per-day delivery history.
None of this belongs in an unconditional per-minute task-alert reconstruction.

## Client compatibility

Apple local notifications, Android alarms, the pending-task picker, timeline
features and floating clock remain intact. Keep the existing seven-day client
feed and all cost/query contracts. The new queue replaces the server's web-push
/ Telegram polling path. Existing native polling APIs need explicit compatibility
tests before any change to their per-device ledgers.

## Cutover and proof

1. Verify DB extension availability, permissions and an isolated Postgres test
   environment. Protect dispatcher authentication in restricted configuration /
   Vault; never put secrets in committed migrations or ordinary queue payloads.
2. Add queue, indexes, narrow claim/ack functions, source triggers and a disabled
   dispatcher. Backfill only eligible future work and existing delivery history.
3. Test create/edit/reschedule/complete/delete/reopen, split tasks, all habit
   overrides, midnight reminders, timezone/DST behavior, report windows, finance
   catch-up, tenant isolation, retries and concurrent claims.
4. Assert that an empty minute invokes no HTTP wakeup and that a real due group
   uses only claim + acknowledgement database HTTP calls. Assert that irrelevant
   edits/calendar metadata changes do not wake or rebuild schedules.
5. Compare old/new due outputs without sending duplicate notifications. Enable
   the database dispatcher and pause the old Google Scheduler reminder job in
   a controlled cutover. Keep the old route/job available for rollback.
6. Verify actual delivery and measure 24–48 hours of production CPU, requests
   and queue delay. The maximum target remains 4,200 CPU-seconds/day and
   126,000/month. Do not claim the target from tests or promise zero total cost.

No production DB migration, scheduler change, cap change or deployment has been
performed as part of this design. The current enforced Cloud Run spend cap must
be handled as an explicit budget decision before the sender can operate again.

Sources: [Supabase Cron](https://supabase.com/docs/guides/cron),
[database webhooks](https://supabase.com/docs/guides/database/webhooks),
[pg_net](https://supabase.com/docs/guides/database/extensions/pg_net).
