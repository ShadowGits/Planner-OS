# Cost and query budget

Requested by the user on 2026-11-25. Future updates must preserve these limits
unless the user explicitly requests the increase. A general feature request is
not permission to increase polling, data downloaded or retention. Record any
authorized exception here with its reason, measured impact and tests.

## Monthly targets

Aim for 60% and stay within 70% of the request-billed Cloud Run free allowances:

| Measure | Aim (60%) | Maximum target (70%) |
| --- | ---: | ---: |
| Allocated CPU seconds/month | 108,000 | 126,000 |
| Requests/month | 1,200,000 | 1,400,000 |

For a 30-day month the maximum target is 4,200 allocated CPU seconds/day and
46,667 requests/day. These are optimization targets, not a verified production
cap. Do not enforce them by dropping reminders, writes or normal reads. Free
allowances are shared across the billing account. Monthly resets can hide an
unsustainable daily rate; assess projected whole-month usage as well as totals.

## Query contract

- One store-owned automatic refresh loop, never faster than 120 seconds.
  UI clock drawing must not request server data.
- Use fresh cached dates when scrolling; coalesce simultaneous reads of the
  same date. Refresh only visible dates and dates required by the clock.
- Project-name lookup uses `projects_only=true`, reading project names and
  aliases without pending task notes or work history.
- Milestone-name lookup uses `details=false`, a paginated ID/name/date/status
  projection without health/progress calculations. Full detail defaults remain
  available to other callers.
- Local reminders use one seven-day projected feed. Preserve completions,
  untimed tasks, due-only tasks, habit overrides, calendar provenance and the
  final day's after-midnight spillover for existing reminder/report behavior.
  No notes, work sessions or milestone calculations. Query failures propagate;
  retain queued reminders on incomplete reads. Older servers use the existing
  full-day fallback only when the new endpoint returns 404.
- Keep tenant filters, pagination, bounded queries and strict error handling.
  The September/October narrow scheduled-reminder query remains in place.
- Keep obsolete deployment images/build archives at three days maximum;
  preserve serving image digests. See `storage_retention.md`.

## Verification

Run `tests/test_query_budget.py` and `tests/test_image_retention.py` plus relevant
day, project-planning, native-dashboard and reminder tests. Apple changes also
require iOS/macOS compilation and the background-refresh harness. These tests
protect individual query shapes and behavior; they cannot certify a monthly
production bill. After deployment/install, compare 24–48 hours of CPU allocation,
requests and bytes, then project a full month. If CPU exceeds 4,200 seconds/day,
continue profiling instead of declaring the budget achieved.

Keep investigation evidence and validation results in
`docs/debugging/2026-11-25-cloud-cost.md`. Do not store access keys, tokens or
private task content in logs.
