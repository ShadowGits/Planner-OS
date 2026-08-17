-- Streaks and completion counts computed in Postgres.
--
-- The dashboard snapshot pulled ninety days of task_completions on every
-- render — every row, every time — to produce a streak number per habit and
-- two integers. That was the single largest read on the page, and the page is
-- refetched whenever anything is ticked.
--
-- This returns the finished numbers instead: a few hundred bytes rather than
-- the whole history.
--
-- Deliberately SECURITY INVOKER (the default), like planner_task_counts: row
-- level security still applies, so an authenticated caller cannot read another
-- tenant's history by passing someone else's ids.

create or replace function public.planner_completion_summary(
    p_user_id uuid,
    p_workspace_id uuid,
    p_today date
)
returns jsonb
language sql
stable
set search_path = public
as $$
    with mine as (
        select c.recurrence_key, c.completed_on
        from public.task_completions c
        where c.user_id = p_user_id
          and c.workspace_id = p_workspace_id
          and c.completed_on is not null
    ),
    -- One row per habit per day: ticking the same habit twice in a day must
    -- not count as two days of a streak.
    days as (
        select distinct recurrence_key, completed_on
        from mine
        where recurrence_key is not null
          and completed_on <= p_today
    ),
    -- Today is still in progress, so a habit not yet done today keeps the
    -- streak it had yesterday rather than dropping to zero.
    anchored as (
        select
            d.recurrence_key,
            d.completed_on,
            case
                when exists (
                    select 1 from days x
                    where x.recurrence_key = d.recurrence_key
                      and x.completed_on = p_today
                ) then p_today
                else p_today - 1
            end as anchor
        from days d
    ),
    -- Walk back from the anchor. The nth most recent day belongs to the run
    -- only if it sits exactly n days before it; once a day is missed the two
    -- drift apart and never meet again, so counting the matches gives the
    -- length of the unbroken run.
    runs as (
        select
            recurrence_key,
            (anchor - completed_on) as gap,
            row_number() over (
                partition by recurrence_key order by completed_on desc
            ) - 1 as position
        from anchored
        where completed_on <= anchor
    ),
    streaks as (
        select recurrence_key, count(*) as streak
        from runs
        where gap = position
        group by recurrence_key
    ),
    -- Habits that have lapsed have no run at all, and the dashboard still
    -- wants to show them sitting at zero.
    all_keys as (
        select distinct recurrence_key from days
    )
    select jsonb_build_object(
        'streaks', coalesce(
            (
                select jsonb_object_agg(k.recurrence_key, coalesce(s.streak, 0))
                from all_keys k
                left join streaks s on s.recurrence_key = k.recurrence_key
            ),
            '{}'::jsonb
        ),
        'completed_today', (
            select count(*) from mine where completed_on = p_today
        ),
        'completions_last_7_days', (
            select count(*) from mine
            where completed_on between p_today - 6 and p_today
        )
    );
$$;

grant execute on function public.planner_completion_summary(uuid, uuid, date)
    to authenticated, service_role;
