-- The handful of tasks that decide whether a day went well.
--
-- A day holds forty-odd tasks, most of them upkeep. Marking the two or three
-- that actually matter gives the day a shape: something to aim at, and an
-- honest answer in the evening about whether it went well — which a count of
-- "31 completed" never gives.
--
-- A plain column on the task, so the mark travels with it: a starred task
-- pushed to tomorrow arrives tomorrow still starred, because it did not stop
-- mattering by being missed.

alter table public.planner_tasks
    add column if not exists starred boolean not null default false;

-- Reading a day's starred tasks is the common query, so index the pair.
create index if not exists planner_tasks_starred_idx
    on public.planner_tasks(user_id, workspace_id, scheduled_date)
    where starred;
