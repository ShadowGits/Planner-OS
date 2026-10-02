-- A completion's task FK uses ON DELETE SET NULL, but the original source
-- check rejected that NULL for non-recurring tasks. Preserve the original ID
-- before deletion so completed tasks can be removed without losing history.
begin;

alter table public.task_completions
    add column if not exists deleted_task_id uuid;

do $$
declare old_check record;
begin
    for old_check in
        select conname from pg_catalog.pg_constraint
        where conrelid = 'public.task_completions'::regclass
          and contype = 'c'
          and pg_get_constraintdef(oid) ilike '%task_id IS NOT NULL%'
          and pg_get_constraintdef(oid) ilike '%recurrence_key IS NOT NULL%'
          and pg_get_constraintdef(oid) not ilike '%deleted_task_id%'
    loop
        execute format('alter table public.task_completions drop constraint %I', old_check.conname);
    end loop;
    if not exists (
        select 1 from pg_catalog.pg_constraint
        where conrelid = 'public.task_completions'::regclass
          and conname = 'task_completions_source_reference_check'
    ) then
        alter table public.task_completions
            add constraint task_completions_source_reference_check
            check (task_id is not null or recurrence_key is not null or deleted_task_id is not null);
    end if;
end $$;

create or replace function public.preserve_deleted_task_history()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    update public.task_completions
    set deleted_task_id = old.id
    where task_id = old.id
      and user_id = old.user_id
      and workspace_id = old.workspace_id;
    return old;
end;
$$;

drop trigger if exists preserve_deleted_task_history on public.planner_tasks;
create trigger preserve_deleted_task_history
    before delete on public.planner_tasks
    for each row execute function public.preserve_deleted_task_history();

commit;
