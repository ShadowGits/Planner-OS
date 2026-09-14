-- Per-milestone progress computed in Postgres.
--
-- The dashboard's milestone health panel needs, for every milestone, how many
-- of its tasks are done and when its work actually starts. Counting that in
-- Python would mean pulling every task row back on each snapshot, which is the
-- egress problem migration 0019 already solved for per-project counts. Same
-- shape here: one small row per milestone.
--
-- Milestones carried a target_date but no start date. One is added below; when
-- it is left unset the start falls back to the earliest date the milestone's
-- tasks are scheduled or due, so existing milestones still rate correctly.

alter table public.milestones
    add column if not exists start_date date;
--
-- Deliberately SECURITY INVOKER (the default): row level security still
-- applies, so an authenticated caller cannot read another tenant's milestones
-- by passing someone else's ids. The service role bypasses RLS as it always has.

create or replace function public.planner_milestone_progress(
    p_user_id uuid,
    p_workspace_id uuid
)
returns table (
    milestone_id uuid,
    done_count bigint,
    total_count bigint,
    first_date date,
    last_date date
)
language sql
stable
set search_path = public
as $$
    select
        t.milestone_id,
        count(*) filter (where t.status = 'done') as done_count,
        count(*) filter (where t.status <> 'skipped') as total_count,
        min(coalesce(t.scheduled_date, t.due_date)) as first_date,
        max(coalesce(t.scheduled_date, t.due_date)) as last_date
    from public.planner_tasks t
    where t.user_id = p_user_id
      and t.workspace_id = p_workspace_id
      and t.milestone_id is not null
      -- Time-slot children are rolled into their parent everywhere else, so
      -- they must not be counted twice here either.
      and t.parent_task_id is null
    group by t.milestone_id;
$$;

grant execute on function public.planner_milestone_progress(uuid, uuid)
    to authenticated, service_role;
