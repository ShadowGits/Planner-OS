-- Per-project task counts computed in Postgres.
--
-- The dashboard snapshot used to fetch every task row just to count them in
-- Python — around 2,000 rows on every page render, to produce a handful of
-- integers. This rolls the counting up in the database so the numbers come
-- back as one small row per project.
--
-- Deliberately SECURITY INVOKER (the default): row level security still
-- applies, so an authenticated caller cannot read another tenant's counts by
-- passing someone else's ids. The service role bypasses RLS as it always has.

create or replace function public.planner_task_counts(
    p_user_id uuid,
    p_workspace_id uuid,
    p_today date
)
returns table (
    project_id uuid,
    done_count bigint,
    total_count bigint,
    open_count bigint,
    overdue_count bigint
)
language sql
stable
set search_path = public
as $$
    select
        t.project_id,
        count(*) filter (where t.status = 'done') as done_count,
        count(*) filter (where t.status <> 'skipped') as total_count,
        count(*) filter (where t.status in ('todo', 'in_progress', 'blocked')) as open_count,
        count(*) filter (
            where t.status in ('todo', 'in_progress', 'blocked')
              and (
                  (t.due_date is not null and t.due_date < p_today)
                  -- No deadline: a day that has passed without finishing counts
                  -- as overdue, matching _is_overdue in planner_core.
                  or (t.due_date is null
                      and t.scheduled_date is not null
                      and t.scheduled_date < p_today)
              )
        ) as overdue_count
    from public.planner_tasks t
    where t.user_id = p_user_id
      and t.workspace_id = p_workspace_id
      -- Time-slot children are rolled into their parent everywhere else, so
      -- they must not be counted twice here either.
      and t.parent_task_id is null
    group by t.project_id;
$$;

grant execute on function public.planner_task_counts(uuid, uuid, date)
    to authenticated, service_role;
