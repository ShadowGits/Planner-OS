# Planner OS Roadmap

## Completed

- Core workbook reader/writer, rules, scheduler, progress, backups, and decision log
- Local CLI and STDIO MCP
- Google Calendar synchronization
- Monthly/weekly/day planning previews and dated tasks
- Deterministic command router v1 and daily check-in

## MVP2 - Complete Local Planner

- [x] Workbook-first planning remains authoritative
- [x] Single-active execution-target model
- [x] Google Calendar execution-target adapter
- [x] Native Apple Calendar execution-target adapter
- [x] Persistent target selection and `none` target
- [x] Previewed target switching without automatic migration
- [x] Explicit cross-target migration with partial-failure repair information
- [x] Cross-target duplicate-link prevention
- [ ] Complete Calendar CRUD preview/apply and orphan cleanup commands
- [ ] Workbook capability detection and schema diagnostics
- [ ] Goal Breakdown Engine v2
- [ ] Command Router v2 phrase coverage
- [ ] Scheduler v2 metadata and dependency constraints
- [ ] Standard stale-preview/source-revision enforcement
- [ ] Undo across workbook, rules, progress, and execution targets
- [ ] Recurring Engine
- [ ] Detailed planner progress metrics and forecasts
- [ ] Daily, weekly, and monthly review suite
- [ ] Planner doctor and previewed repair
- [ ] Complete preference management

## MVP3 - Hosted Platform

- Hosting and remote MCP
- Vercel and cloud storage
- PlannerContext
- Multi-user and shared-planner support
- Web OAuth
- Public plugin/app publishing

MVP3 is intentionally not part of local MVP2.
