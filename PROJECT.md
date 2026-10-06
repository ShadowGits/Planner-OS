# Planner OS — product scope

Planner OS is a personal planning and execution system: projects and milestones connect to tasks, recurring habits, time blocks, actual work, progress, reminders and financial plans. Supabase Postgres is the current planning source of truth; FastAPI, cloud MCP, the day PWA, Android and the separate web dashboard are interfaces to the same domain data.

The PWA and Android day planner follow a Structured-inspired layout: bright surfaces, wine accents, pastel task blocks, clear time alignment, direct task actions and a compact date area. Preserve timeline dragging, overlaps, Top Wins, day/inbox navigation, list toggle, task/habit edits and focus timers during redesigns.

Scheduled-task time logging is optional. Do not force expired/overdue tasks through a queue of logging forms. Keep actual work separate from planned time and use durable, atomic request contracts for logging and splitting.

## Engineering principles

1. Preserve existing behavior; a new client must not quietly remove features.
2. Scope every operation to the authenticated/configured owner and active workspace.
3. Keep stable task/occurrence identities across edits and calendar sync.
4. Keep animations and timer ticks local; avoid needless full-day downloads or loading locks.
5. Preserve history and exact work budgets. Use transactional RPCs and identical retries for uncertain writes.
6. Distinguish proposed, committed, delivered and deployed work; report failures and platform limits truthfully.
7. Keep credentials/signing keys private, preserve other chats' unfinished changes, and follow repository release authorization rules.

See [the complete product/developer handoff](docs/technical_reference.md) and [generated interface inventory](docs/interface_inventory.md). Workbook-era architecture and absent CLI/EventKit components are documented as historical rather than current capabilities.
