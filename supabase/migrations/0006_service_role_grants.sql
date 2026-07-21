-- The v2 API and MCP core tools query the planner tables with the Supabase
-- service role. That role bypasses RLS but still needs table-level grants;
-- migration 0005 granted only to `authenticated`, so service-role queries
-- could hit "permission denied" and surface as 500s. Grant the service role
-- explicitly and reload the PostgREST schema cache so new tables are visible.

grant usage on schema public to service_role;

grant select, insert, update, delete on public.projects to service_role;
grant select, insert, update, delete on public.milestones to service_role;
grant select, insert, update, delete on public.planner_tasks to service_role;
grant select, insert, update, delete on public.task_completions to service_role;
grant select, insert, update, delete on public.reminder_log to service_role;

notify pgrst, 'reload schema';
