-- Day-planner view: tasks gain a time-of-day so they can sit on a vertical
-- timeline and be dragged to a new slot. Table-level grants from 0005/0006
-- already cover new columns. Apply, then reload PostgREST's schema cache.

alter table public.planner_tasks
    add column start_time time;

notify pgrst, 'reload schema';
