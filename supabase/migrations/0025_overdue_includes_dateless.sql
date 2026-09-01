-- Count a loose task with no date at all as overdue.
--
-- planner_task_counts previously called a task overdue only when a due date or
-- a planned day had passed. A task with neither simply floated: never overdue,
-- never surfaced, easy to miss. This mirrors the widened _is_overdue in
-- planner_core so the dashboard count and the Python paths agree.
--
-- A future date is still not-yet-due and is not counted.

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
                  -- No deadline: a planned day that has passed counts.
                  or (t.due_date is null
                      and t.scheduled_date is not null
                      and t.scheduled_date < p_today)
                  -- No date at all: unplanned and unhandled, so it counts too.
                  or (t.due_date is null and t.scheduled_date is null)
              )
        ) as overdue_count
    from public.planner_tasks t
    where t.user_id = p_user_id
      and t.workspace_id = p_workspace_id
      and t.parent_task_id is null
    group by t.project_id;
$$;

grant execute on function public.planner_task_counts(uuid, uuid, date)
    to authenticated, service_role;
