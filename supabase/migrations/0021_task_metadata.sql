-- Columns that belong to a task but that no fixed field covers — the study
-- plan's Subject and Source, for instance. The project views read whatever
-- keys are present and render them as table columns, so a project can carry
-- its own columns without a schema change each time.
--
-- Deliberately free-form: this replaces per-project CSV files that were being
-- hand-maintained alongside the tasks they described.

alter table planner_tasks
  add column if not exists metadata jsonb;
