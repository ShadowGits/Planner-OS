# Planner OS

Planner OS combines projects, milestones, tasks, habits, daily time blocks, actual-work logging, reminders, progress and financial planning. The current source of truth is **Supabase Postgres**, shared by the FastAPI backend, cloud MCP tools, day-planner PWA and native Kotlin/Compose Android app.

## Documentation for developers and AI agents

Start with **[the complete product and technical handoff](docs/technical_reference.md)**. It covers features, source ownership, architecture, auth/tenancy, database/time conventions, calendars, reminders, timer/client differences, setup, tests, deployment, APK delivery, known gaps and unfinished work.

The **[generated interface inventory](docs/interface_inventory.md)** lists every statically declared HTTP route, MCP tool, request-model field, public core-service method, tracked migration and environment-variable usage from the documented commit. Regenerate it with `python3 scripts/generate_reference_inventory.py --ref HEAD`.

Focused guides: [Android](android/README.md), [PWA](docs/day_planner_pwa.md), [focus timer/list](docs/pwa_focus_and_list.md), [actual work](docs/actual_work_logging.md), [split repair](docs/android_split_repair.md), [completed-task deletion](docs/completed_task_deletion.md).

## Source layout

- Backend: `planner_api`, `planner_core`, `planner_platform`, `adapters`, `planner_integrations`.
- Database: `supabase/migrations`.
- Day PWA: `planner_api/static/pwa`, served by backend `/app/`.
- Android: `android`, with its own build and versioned APK delivery instructions.
- Root Next.js: `app`, `components`, `lib`; contains retained legacy console flows. The active Deutschland web dashboard is a separate repository.

Earlier Excel/STDIO/`shadow` CLI descriptions are historical and do not describe this checkout's complete implementation. Read the handoff's release boundary and known gaps before extending it. Local commits, delivered APKs and production deployments are distinct states.
