-- Additive: ASAP uses existing task metadata; no task rows are rewritten.
create index if not exists planner_tasks_open_asap
on public.planner_tasks(user_id, workspace_id, created_at, id)
where metadata->>'asap' = 'true' and status in ('todo', 'in_progress', 'blocked');
