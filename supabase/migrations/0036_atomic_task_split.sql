-- Run this entire file in a fresh SQL editor query; replace the previous query contents.
-- General splitting must not use multiple independently committed task writes.
-- Existing work/completion history is retained; no actual work is fabricated.
begin;
create table if not exists public.task_split_requests (
 id uuid primary key,user_id uuid not null,workspace_id uuid not null,
 request_payload jsonb not null,result jsonb not null,created_at timestamptz not null default now(),
 foreign key(user_id,workspace_id) references public.workspaces(user_id,id) on delete cascade
);
alter table public.task_split_requests enable row level security;
grant select,insert,update,delete on public.task_split_requests to service_role;

create or replace function public.planner_split_task(
 p_user_id uuid,p_workspace_id uuid,p_request_id uuid,p_task_id uuid,
 p_first_seconds integer,p_expected_remaining integer
) returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare
 t planner_tasks%rowtype; prior task_split_requests%rowtype;
 payload jsonb; output jsonb; planned integer; worked integer; remaining integer;
 v_split_group_root uuid; first_id uuid; second_id uuid; worked_id uuid; patch jsonb; first_start timestamp;
begin
 if coalesce(auth.role(),'')<>'service_role' and auth.uid() is distinct from p_user_id then raise exception 'SPLIT_NOT_FOUND'; end if;
 if not exists(select 1 from workspaces where id=p_workspace_id and user_id=p_user_id) then raise exception 'SPLIT_NOT_FOUND'; end if;
 if p_request_id is null or p_first_seconds is null or p_expected_remaining is null then raise exception 'SPLIT_INVALID: Missing split details.'; end if;
 payload=jsonb_build_object('task',p_task_id,'first_seconds',p_first_seconds,'expected_remaining',p_expected_remaining);
 perform pg_advisory_xact_lock(hashtextextended('planner-split:'||p_request_id::text,0));
 select * into prior from task_split_requests where id=p_request_id;
 if found then
  if prior.user_id<>p_user_id or prior.workspace_id<>p_workspace_id or prior.request_payload<>payload then raise exception 'SPLIT_INVALID: This split id was already used for different details.'; end if;
  return prior.result;
 end if;
 select * into t from planner_tasks where id=p_task_id and user_id=p_user_id and workspace_id=p_workspace_id;
 if not found then raise exception 'SPLIT_NOT_FOUND'; end if;
 v_split_group_root=coalesce(t.parent_task_id,t.id);
 perform 1 from planner_tasks where id=v_split_group_root and user_id=p_user_id and workspace_id=p_workspace_id for update;
 if not found then raise exception 'SPLIT_NOT_FOUND'; end if;
 select * into t from planner_tasks where id=p_task_id and user_id=p_user_id and workspace_id=p_workspace_id for update;
 if not found then raise exception 'SPLIT_NOT_FOUND'; end if;
 if t.status in ('done','skipped') then raise exception 'SPLIT_INVALID: Only an unfinished task can be split.'; end if;
 if exists(select 1 from planner_tasks where parent_task_id=t.id and user_id=p_user_id and workspace_id=p_workspace_id) then raise exception 'SPLIT_INVALID: This task is already split. Refresh and choose an individual session.'; end if;
 planned=coalesce(t.estimated_minutes,30)*60;
 if t.metadata->'_work_budget'->>'minutes'=coalesce(t.estimated_minutes,30)::text
    and coalesce(t.metadata->'_work_budget'->>'seconds','') ~ '^[0-9]{1,6}$' then
  planned=greatest(1,(t.metadata->'_work_budget'->>'seconds')::integer);
 end if;
 select coalesce(sum(seconds),0)::int into worked from task_work_sessions where task_ref=t.id::text and user_id=p_user_id and workspace_id=p_workspace_id;
 remaining=greatest(0,planned-worked);
 if remaining<>p_expected_remaining then raise exception 'SPLIT_INVALID: The remaining work changed. Refresh before splitting.'; end if;
 if p_first_seconds<=0 or p_first_seconds>=remaining then raise exception 'SPLIT_INVALID: Both sessions need some remaining work.'; end if;
 -- Keep previously logged work in one completed session, separate from both open sessions.
 if worked>0 then
  worked_id=case when t.parent_task_id is null then gen_random_uuid() else t.id end;
  patch=jsonb_build_object('id',worked_id,'parent_task_id',v_split_group_root,'status','done','completed_at',now(),
    'estimated_minutes',(worked+59)/60,'starred',false,
    'metadata',coalesce(t.metadata,'{}')||jsonb_build_object('_work_budget',jsonb_build_object('seconds',worked,'minutes',(worked+59)/60)));
  if t.parent_task_id is null then
   insert into planner_tasks select (jsonb_populate_record(null::planner_tasks,to_jsonb(t)||patch)).*;
   update task_work_sessions set task_ref=worked_id::text where task_ref=t.id::text and user_id=p_user_id and workspace_id=p_workspace_id;
   update task_completions set task_id=worked_id where task_id=t.id and user_id=p_user_id and workspace_id=p_workspace_id;
  else
   update planner_tasks set status='done',completed_at=now(),estimated_minutes=(worked+59)/60,starred=false,metadata=patch->'metadata' where id=t.id;
  end if;
  if not exists(select 1 from task_completions where task_id=worked_id and user_id=p_user_id and workspace_id=p_workspace_id) then
   insert into task_completions(user_id,workspace_id,task_id,completed_on,source)
   values(p_user_id,p_workspace_id,worked_id,(now() at time zone (select timezone from workspaces where id=p_workspace_id and user_id=p_user_id))::date,'dashboard');
  end if;
 end if;
 first_id=case when t.parent_task_id is not null and worked=0 then t.id else gen_random_uuid() end;
 second_id=gen_random_uuid();
 patch=jsonb_build_object('id',first_id,'parent_task_id',v_split_group_root,'status','todo','completed_at',null,
   'estimated_minutes',(p_first_seconds+59)/60,
   'metadata',coalesce(t.metadata,'{}')||jsonb_build_object('_work_budget',jsonb_build_object('seconds',p_first_seconds,'minutes',(p_first_seconds+59)/60)));
 if worked>0 and t.scheduled_date is not null and t.start_time is not null then
  first_start=t.scheduled_date+t.start_time+make_interval(mins=>(worked+59)/60);
  patch=patch||jsonb_build_object('scheduled_date',first_start::date,'start_time',first_start::time);
 end if;
 if first_id=t.id then
  update planner_tasks set estimated_minutes=(p_first_seconds+59)/60,metadata=patch->'metadata' where id=t.id;
 else
  insert into planner_tasks select (jsonb_populate_record(null::planner_tasks,to_jsonb(t)||patch)).*;
 end if;
 patch=jsonb_build_object('id',second_id,'parent_task_id',v_split_group_root,'status','todo','completed_at',null,
   'start_time',null,'estimated_minutes',(remaining-p_first_seconds+59)/60,
   'metadata',coalesce(t.metadata,'{}')||jsonb_build_object('_work_budget',jsonb_build_object('seconds',remaining-p_first_seconds,'minutes',(remaining-p_first_seconds+59)/60)));
 insert into planner_tasks select (jsonb_populate_record(null::planner_tasks,to_jsonb(t)||patch)).*;
 update planner_tasks set status='in_progress',completed_at=null where id=v_split_group_root;
 output=jsonb_build_object('parent_id',v_split_group_root,'first_id',first_id,'second_id',second_id,'worked_id',worked_id,
   'first_seconds',p_first_seconds,'second_seconds',remaining-p_first_seconds,'worked_seconds',worked);
 insert into task_split_requests(id,user_id,workspace_id,request_payload,result) values(p_request_id,p_user_id,p_workspace_id,payload,output);
 return output;
end $$;
revoke all on function public.planner_split_task(uuid,uuid,uuid,uuid,integer,integer) from public;
grant execute on function public.planner_split_task(uuid,uuid,uuid,uuid,integer,integer) to service_role;
commit;
