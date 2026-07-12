# MVP3 Stage 1 Repository Audit

Stage 1 establishes the cloud migration baseline without changing local Planner
OS behavior. The audit was performed against commit `0e40af4` and the public
interface documented in `docs/technical_reference.md`.

## Public Interface Baseline

- The STDIO MCP server exposes 90 decorated tools.
- The Shadow CLI exposes 25 top-level command groups.
- Appendix A of the MVP3 design lists only 36 tools and is therefore not a
  complete implementation inventory.
- `planner_platform/function_manifest.json` is the canonical generated
  inventory. It combines documentation metadata with signatures parsed from
  `planner_mcp/server.py`.
- Final effect classification: 26 read, 12 preview, 18 workbook write, 10
  local-state write, 23 external write, and 1 mixed command-router tool.
- Final cloud classification: 79 tenant-adaptation candidates, 10 local-only
  Apple Calendar tools explicitly disabled in cloud mode, and 1 mandatory
  adaptation for `import_plan`.
- `python -m planner_platform.function_manifest --check` fails when the
  technical reference, live MCP registration, or checked-in manifest diverges.
- Apple Calendar tools are explicitly marked cloud-disabled because EventKit
  requires local macOS execution. `import_plan` is marked as requiring a cloud
  upload adaptation because its current public input is a local filesystem path.

## Reusable Modules

| Area | Existing implementation retained for MVP3 |
|---|---|
| Workbook | `ExcelPlannerStore`, dynamic schema detection, reader/writer mixins |
| Planning | Planner, monthly planner, goal planner, current-time planner |
| Scheduling | Scheduler package, capacity engine, daily distributor |
| Mutation | Semantic `Writer`, workbook backups, stable dated-task IDs |
| Rules | Rules engine, rules manager, preferences |
| Safety | Preview/apply services, Decision Log, undo, repair, doctor |
| Progress | Progress engine, check-ins, daily/weekly/monthly reviews |
| External execution | Shared execution-target contract and Google adapter |
| Interfaces | Shadow CLI and STDIO MCP remain local adapters |

The cloud layer must call these modules through context-bound dependencies. It
must not duplicate their planning, scheduling, rules, progress, workbook, or
calendar reconciliation behavior.

## Local Assumptions Requiring Ports

| Current assumption | Evidence | Required boundary |
|---|---|---|
| One hard-coded workbook | `planner_engine/config.py` contains an absolute personal workbook path | Workspace/workbook repository |
| Process-global MCP adapter | `planner_mcp/server.py` creates one `PlannerMCPTools` instance at import | Request-scoped execution service |
| Cached mutable services | `PlannerMCPTools` caches planning, calendar, router, and execution-manager objects | Context-scoped dependency factory |
| Local workbook writes | `ExcelPlannerStore` reads and saves one filesystem path directly | Workbook session plus local/cloud storage adapters |
| Local backup directory | Workbook backups are copied into `backups/` | Revisioned backup repository |
| Local rules and settings | YAML and JSON files are addressed by process-local paths | Settings/preferences repository |
| Fragmented preview files | Planning, target, calendar, repair, undo, recurrence, and goal previews use local JSON files | Owner-scoped preview repository |
| Local JSON mappings | External links are stored without user/workspace fields | Tenant-scoped event-mapping repository |
| Local JSONL decisions | Decision Log writes a process-local JSONL file | Tenant-scoped operation/audit repository |
| Desktop Google OAuth | Google client reads plaintext local credential/token files and may launch a local OAuth server | Server-side OAuth connection repository and encrypted token service |
| Local Apple EventKit | Apple integration launches a signed helper on the host Mac | Explicit cloud-disabled policy |
| Caller-supplied import path | `import_plan(input_path)` opens a local path | Validated upload/body adapter |
| In-memory progress | Fresh `ProgressEngine` instances are frequently constructed per call | Explicit progress source/repository where persistence is required |

## Security And Concurrency Findings

1. There is currently no authenticated user or workspace concept in the domain
   call chain. Cloud requests must create identity only from a verified JWT.
2. External-link records contain block, target, external ID, status, timestamps,
   and checksum, but no tenant keys. Cloud mappings require both `user_id` and
   `workspace_id`.
3. Workbook writes back up before mutation but do not acquire a cross-request
   lock or compare a server-side workspace revision at commit time.
4. Preview source-revision checks are implemented by individual services and
   are not yet one owner-scoped, expiry-bound, single-use contract.
5. Google event operations can use injected fakes safely in tests, but the
   default client resolves one local token and one local mapping file.
6. Local OAuth files and workbook backups are ignored by Git. No credential,
   token, workbook, backup, or decision-log file is tracked. The local
   `backups/` tree currently contains copied OAuth files; cloud backup logic must
   strictly back up workbook objects only.
7. Errors currently include raw exception text and may reveal local paths.
   Cloud responses require stable sanitized error codes.
8. Apple Calendar cannot execute in Vercel and must remain available only to
   local CLI/STDIO consumers.

## Persistence Inventory

| State | Current persistence |
|---|---|
| Planner data, recurrence definitions | Excel workbook and planner-owned sheets |
| Rules and preferences | YAML plus execution-target JSON |
| Planning and mutation previews | JSON files below `.planner-os/` |
| External event mappings | `.planner-os/external-links.json` |
| Decision history | JSONL |
| Google OAuth | Local `credentials.json` and `token.json` |
| Backups | Local `.xlsx` copies |

No SQLite or other embedded database is present.

## Stage 1 Gate Result

- Manifest tests: 5 passed.
- Full local regression suite after Stage 1: 138 passed.
- `git diff --check`: passed.
- No runtime behavior, MCP signature, CLI command, workbook, calendar, token,
  or local setting was changed by Stage 1.

## Stage 2 Entry Contract

Stage 2 may add `PlannerContext`, repository protocols, policies, a guarded Tool
Registry, and local adapters. It must preserve all current defaults and tests.
The Tool Registry must consume the canonical manifest and require every one of
the 90 tools to declare effect, confirmation, resource requirements, timeout,
audit policy, and cloud status. No API, Supabase, JWT, or deployment code should
be introduced until the Stage 2 local-adapter gate is green.
