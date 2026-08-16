-- Turn the pre-generated gym, sleep and piano rows into habit rules, then
-- delete them.
--
-- These three were a year of daily task rows each: 295 gym, 294 sleep, 1
-- piano. Every day that passed unticked became overdue for ever and the count
-- grew by two a day. They are rules now, and their days are worked out on
-- read.
--
-- german stays as tasks on purpose. Missing a day of German means you are a
-- session behind, so it should keep nagging. Same for math and reading.
--
-- Completions are untouched, so every existing streak survives.

-- 1. One rule per series, taking the most common start time and duration from
--    the rows being replaced so the habit looks like what it is replacing.
insert into public.habits (
    user_id, workspace_id, title, recurrence_key, cadence,
    start_time, estimated_minutes, project_id, start_date
)
select
    t.user_id,
    t.workspace_id,
    -- titles repeat across the series; take the one used most
    (array_agg(t.title order by t.title))[1],
    t.recurrence_key,
    'daily',
    mode() within group (order by t.start_time),
    mode() within group (order by t.estimated_minutes),
    mode() within group (order by t.project_id),
    current_date
from public.planner_tasks t
where t.recurrence_key in ('gym', 'sleep', 'piano')
group by t.user_id, t.workspace_id, t.recurrence_key
on conflict do nothing;

-- 2. Drop the rows. Completions live in task_completions and are keyed by
--    recurrence_key, not by task id, so streaks are unaffected.
delete from public.planner_tasks
where recurrence_key in ('gym', 'sleep', 'piano');
