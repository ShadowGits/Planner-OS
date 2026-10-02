-- Standalone migration: actual seconds, atomic splitting, retry-safe saves.
-- Does not depend on the separate Day Recovery migration 0033.
create table if not exists public.task_work_sessions (
 id uuid primary key,
 user_id uuid not null,
 workspace_id uuid not null,
 task_ref text not null,
 seconds integer not null check(seconds between 0 and 86400),
 planned_seconds integer not null check(planned_seconds > 0),
 source text not null check(source in ('manual','timer')),
 request_payload jsonb not null,
 result jsonb not null default '{}',
 created_at timestamptz not null default now(),
 foreign key(user_id,workspace_id) references public.workspaces(user_id,id) on delete cascade
);
-- Immutable source refs deliberately have no task FK: deleting a task keeps
-- its actual-work history, including habit occurrence refs.
create index if not exists task_work_sessions_lookup on public.task_work_sessions(user_id,workspace_id,task_ref);
alter table public.task_work_sessions enable row level security;
drop policy if exists task_work_sessions_owner on public.task_work_sessions;
create policy task_work_sessions_owner on public.task_work_sessions for select to authenticated using ((select auth.uid())=user_id);
grant select on public.task_work_sessions to authenticated;
grant select,insert,update,delete on public.task_work_sessions to service_role;

create or replace function public.planner_log_work(
 p_user_id uuid,p_workspace_id uuid,p_request_id uuid,p_task_ref text,p_seconds integer,p_source text,
 p_finish boolean default false,p_split boolean default false,p_remainder_date date default null,p_remainder_time time default null
) returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare
 t planner_tasks%rowtype; h habits%rowtype; o habit_overrides%rowtype;
 prior task_work_sessions%rowtype; payload jsonb; output jsonb;
 planned integer; worked integer; remaining integer; habit_day date; shown date;
 habit_uuid uuid; child uuid; rest uuid; leader uuid; finished boolean; today date;
begin
 if coalesce(auth.role(),'') <> 'service_role' and auth.uid() is distinct from p_user_id then raise exception 'WORK_NOT_FOUND'; end if;
 if not exists(select 1 from workspaces where id=p_workspace_id and user_id=p_user_id) then raise exception 'WORK_NOT_FOUND'; end if;
 if p_seconds is null or p_seconds not between 0 and 86400 or p_source not in ('manual','timer') then raise exception 'WORK_INVALID: Enter 0–24 hours of work.'; end if;
 if p_split and p_remainder_date is null then raise exception 'WORK_INVALID: Choose a date for the remaining work.'; end if;
 payload=jsonb_build_object('task',p_task_ref,'seconds',p_seconds,'source',p_source,'finish',p_finish,'split',p_split,'date',p_remainder_date,'time',p_remainder_time);
 -- Serialize the retry key even if a caller accidentally reuses it on another task.
 perform pg_advisory_xact_lock(hashtextextended('planner-work:'||p_request_id::text,0));
 select * into prior from task_work_sessions where id=p_request_id;
 if found then
  if prior.user_id<>p_user_id or prior.workspace_id<>p_workspace_id or prior.request_payload<>payload then raise exception 'WORK_INVALID: This save id was already used. Refresh before saving again.'; end if;
  return prior.result;
 end if;
 select (now() at time zone timezone)::date into today from workspaces where id=p_workspace_id and user_id=p_user_id;
 if p_task_ref like 'habit:%' then
  begin habit_uuid=split_part(p_task_ref,':',2)::uuid; habit_day=split_part(p_task_ref,':',3)::date;
  exception when others then raise exception 'WORK_NOT_FOUND'; end;
  select * into h from habits where id=habit_uuid and user_id=p_user_id and workspace_id=p_workspace_id for update;
  if not found then raise exception 'WORK_NOT_FOUND'; end if;
  select * into o from habit_overrides where habit_id=h.id and on_date=habit_day and user_id=p_user_id and workspace_id=p_workspace_id;
  if coalesce(o.skipped,false) then raise exception 'WORK_INVALID: This occurrence was skipped.'; end if;
  shown=coalesce(o.moved_to,habit_day);
  planned=coalesce(o.estimated_minutes,h.estimated_minutes,30)*60;
  select planned_seconds into remaining from task_work_sessions where task_ref=p_task_ref and user_id=p_user_id and workspace_id=p_workspace_id order by created_at,id limit 1;
  planned=coalesce(remaining,planned);
 else
  begin select * into t from planner_tasks where id=p_task_ref::uuid and user_id=p_user_id and workspace_id=p_workspace_id;
  exception when invalid_text_representation then raise exception 'WORK_NOT_FOUND'; end;
  if t.id is null then raise exception 'WORK_NOT_FOUND'; end if;
  leader=coalesce(t.parent_task_id,t.id);
  perform 1 from planner_tasks where id=leader and user_id=p_user_id and workspace_id=p_workspace_id for update;
  if not found then raise exception 'WORK_NOT_FOUND'; end if;
  select * into t from planner_tasks where id=t.id and user_id=p_user_id and workspace_id=p_workspace_id for update;
  planned=coalesce(t.estimated_minutes,30)*60;
  if t.metadata->'_work_budget'->>'minutes'=coalesce(t.estimated_minutes,30)::text then
   planned=coalesce((t.metadata->'_work_budget'->>'seconds')::integer,planned);
  end if;
 end if;
 if t.id is not null and exists(select 1 from planner_tasks where parent_task_id=t.id and user_id=p_user_id and workspace_id=p_workspace_id) then
  raise exception 'WORK_INVALID: Choose an individual split block to log its time.';
 end if;
 select coalesce(sum(seconds),0)::int+p_seconds into worked from task_work_sessions where task_ref=p_task_ref and user_id=p_user_id and workspace_id=p_workspace_id;
 remaining=greatest(0,planned-worked);
 if p_split and remaining=0 then raise exception 'WORK_INVALID: There is no remaining time to split.'; end if;
 insert into task_work_sessions(id,user_id,workspace_id,task_ref,seconds,planned_seconds,source,request_payload)
 values(p_request_id,p_user_id,p_workspace_id,p_task_ref,p_seconds,planned,p_source,payload);
 if h.id is not null then
  finished=exists(select 1 from task_completions where user_id=p_user_id and workspace_id=p_workspace_id and recurrence_key=h.recurrence_key and completed_on=shown);
  if p_split then
   -- Retiming only this occurrence preserves the recurring rule and streak.
   delete from task_completions where user_id=p_user_id and workspace_id=p_workspace_id and recurrence_key=h.recurrence_key and completed_on=shown;
   insert into habit_overrides(user_id,workspace_id,habit_id,on_date,moved_to,start_time,estimated_minutes)
   values(p_user_id,p_workspace_id,h.id,habit_day,p_remainder_date,p_remainder_time,(remaining+59)/60)
   on conflict(habit_id,on_date) do update set moved_to=excluded.moved_to,start_time=excluded.start_time,estimated_minutes=excluded.estimated_minutes;
   finished=false; rest=h.id;
  elsif p_finish and remaining=0 and not finished then
   insert into task_completions(user_id,workspace_id,recurrence_key,completed_on,source) values(p_user_id,p_workspace_id,h.recurrence_key,shown,'dashboard'); finished=true;
  end if;
 else
  finished=t.status='done';
  if p_split and worked=0 then
   update planner_tasks set scheduled_date=p_remainder_date,start_time=p_remainder_time,status='todo',completed_at=null where id=t.id;
   delete from task_completions where user_id=p_user_id and workspace_id=p_workspace_id and task_id=t.id;
   finished=false; rest=t.id;
  elsif p_split then
   child=case when t.parent_task_id is not null then t.id else gen_random_uuid() end; rest=gen_random_uuid();
   if t.parent_task_id is null then
    insert into planner_tasks(id,user_id,workspace_id,title,status,estimated_minutes,scheduled_date,start_time,parent_task_id,project_id,milestone_id,priority,due_date,notes,metadata,starred,completed_at)
    values(child,p_user_id,p_workspace_id,t.title,'done',(worked+59)/60,t.scheduled_date,t.start_time,t.id,t.project_id,t.milestone_id,t.priority,t.due_date,t.notes,coalesce(t.metadata,'{}')||jsonb_build_object('_work_budget',jsonb_build_object('seconds',worked,'minutes',(worked+59)/60)),false,now());
    update task_work_sessions set task_ref=child::text where user_id=p_user_id and workspace_id=p_workspace_id and task_ref=p_task_ref;
    update task_completions set task_id=child where user_id=p_user_id and workspace_id=p_workspace_id and task_id=t.id;
    update planner_tasks set status='in_progress',completed_at=null where id=t.id;
   else
    update planner_tasks set status='done',completed_at=now(),estimated_minutes=(worked+59)/60,metadata=coalesce(t.metadata,'{}')||jsonb_build_object('_work_budget',jsonb_build_object('seconds',worked,'minutes',(worked+59)/60)) where id=t.id;
   end if;
   insert into planner_tasks(id,user_id,workspace_id,title,status,estimated_minutes,scheduled_date,start_time,parent_task_id,project_id,milestone_id,priority,due_date,notes,metadata,starred)
   values(rest,p_user_id,p_workspace_id,t.title,'todo',(remaining+59)/60,p_remainder_date,p_remainder_time,leader,t.project_id,t.milestone_id,t.priority,t.due_date,t.notes,coalesce(t.metadata,'{}')||jsonb_build_object('_work_budget',jsonb_build_object('seconds',remaining,'minutes',(remaining+59)/60)),t.starred);
   if not exists(select 1 from task_completions where user_id=p_user_id and workspace_id=p_workspace_id and task_id=child) then
    insert into task_completions(user_id,workspace_id,task_id,completed_on,source) values(p_user_id,p_workspace_id,child,today,'dashboard');
   end if;
   update planner_tasks set status='in_progress',completed_at=null where id=leader;
   finished=true;
  elsif p_finish and remaining=0 and not finished then
   update planner_tasks set status='done',completed_at=now() where id=t.id;
   insert into task_completions(user_id,workspace_id,task_id,completed_on,source) values(p_user_id,p_workspace_id,t.id,today,'dashboard');
   if t.parent_task_id is not null and not exists(select 1 from planner_tasks where parent_task_id=leader and user_id=p_user_id and workspace_id=p_workspace_id and status not in ('done','skipped')) then update planner_tasks set status='done',completed_at=now() where id=leader; end if;
   finished=true;
  end if;
 end if;
 output=jsonb_build_object('task_ref',p_task_ref,'worked_seconds',worked,'remaining_seconds',remaining,'done',finished,'remainder_id',rest,'remainder_date',p_remainder_date,'remainder_time',p_remainder_time);
 update task_work_sessions set result=output where id=p_request_id;
 return output;
end $$;
revoke all on function public.planner_log_work(uuid,uuid,uuid,text,integer,text,boolean,boolean,date,time) from public;
grant execute on function public.planner_log_work(uuid,uuid,uuid,text,integer,text,boolean,boolean,date,time) to authenticated,service_role;
