-- Let one day of a habit be marked as a win.
--
-- Starring lives on the task row, but a habit occurrence has no row — it is
-- generated from the rule — so a star on "gym" had nothing to write to and the
-- patch fell through to "nothing to change", ticking on screen and springing
-- back. Going to the gym can absolutely be what a day is judged by, so it gets
-- the same per-day override the skip and reschedule already use: the rule is
-- untouched, only that one day carries the star.

alter table public.habit_overrides
    add column if not exists starred boolean not null default false;
