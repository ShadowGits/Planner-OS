-- Let reminder_log accept per-event reminder kinds.
--
-- The table's kind was constrained to the three daily digests. Per-event
-- reminders record kinds like 'event30:<task id>' and 'event5:<task id>', so
-- the constraint rejected the dedup write — the reminder fired, but nothing
-- recorded it, so it fired again every cron tick. kind is an internal label,
-- so the constraint is simply dropped.

alter table public.reminder_log drop constraint if exists reminder_log_kind_check;
