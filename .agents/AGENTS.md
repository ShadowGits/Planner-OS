# Agent Rules

## Strict Git Push Policy
**CRITICAL**: You MUST NEVER execute a `git push` command (or any deployment command) without explicitly asking for and receiving real-time permission from the user in the chat. 

A user's approval of an "implementation plan" DOES NOT count as authorization to push code. You must always stop your execution, ask the user if it is okay to push, and wait for the user to type their explicit approval before running any push commands.

## Cost and query budget — explicit user request required to increase

The user requires cost safeguards to survive future feature updates. Do not
increase automatic polling frequency, background network work, queried columns,
date ranges or full-planner downloads without an explicit request from the user
to make that increase. A generic feature request or redesign is not permission.

Monthly Cloud Run targets: aim for 108,000 allocated CPU seconds and 1.2 million
requests (60% of free allowances); maximum target 126,000 seconds and 1.4 million
requests (70%). Verify projected usage after deployment; do not claim these
targets achieved from unit tests or enforce them by dropping functionality.

- Apple automatic full refresh must be no more frequent than every 120 seconds.
  Local clock/timer animation must never cause network requests.
- Apple project names use `projects_only=true`; they must not fetch pending
  task notes or work history. Milestone labels use `details=false`; they must
  not calculate health/progress on each poll.
- Reminder queuing uses the bounded seven-day reminder-schedule feed. Do not
  replace it with seven full day/work-history downloads. Keep the older-server
  fallback, truthful errors, tenant scope and exact notification timing.
- Preserve the September/October narrow projections, date bounds, pagination
  and strict failure handling. Never implement dedup/reconciliation from an
  error disguised as an empty table.
- Obsolete deployment images and build archives expire after three days.
  Protect serving image digests. Do not increase retention or remove cleanup
  hooks unless the user specifically requests that change.
- Run the cost/query regressions in `tests/test_query_budget.py` and storage
  regressions in `tests/test_image_retention.py` when changing these paths.
  Update `docs/query_budget.md` with evidence for any authorized exception.
