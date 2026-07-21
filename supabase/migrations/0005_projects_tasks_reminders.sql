-- Planner OS v2 core: Postgres-backed projects, milestones, tasks,
-- completions, and reminder log. Tasks become queryable rows instead of
-- workbook cells so the dashboard and reminder cron can read them directly.
-- Apply through the Supabase migration runner before deploying the API.

create table public.projects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    name text not null,
    track text,
    description text,
    status text not null default 'active'
        check (status in ('active', 'paused', 'done', 'archived')),
    target_date date,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (workspace_id, name),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create table public.milestones (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    name text not null,
    status text not null default 'not_started'
        check (status in ('not_started', 'in_progress', 'blocked', 'done')),
    target_date date,
    sort_order integer not null default 0,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project_id, name),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create table public.planner_tasks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid references public.projects(id) on delete set null,
    milestone_id uuid references public.milestones(id) on delete set null,
    title text not null,
    status text not null default 'todo'
        check (status in ('todo', 'in_progress', 'blocked', 'done', 'skipped')),
    priority text not null default 'medium'
        check (priority in ('low', 'medium', 'high', 'critical')),
    due_date date,
    scheduled_date date,
    estimated_minutes integer check (estimated_minutes is null or estimated_minutes > 0),
    recurrence_key text,
    depends_on uuid references public.planner_tasks(id) on delete set null,
    notes text,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create table public.task_completions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    task_id uuid references public.planner_tasks(id) on delete set null,
    recurrence_key text,
    completed_on date not null default current_date,
    source text not null default 'api'
        check (source in ('mcp', 'telegram', 'dashboard', 'api')),
    note text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade,
    check (task_id is not null or recurrence_key is not null)
);

create table public.reminder_log (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    kind text not null
        check (kind in ('morning_brief', 'evening_nudge', 'deadline_alert')),
    sent_on date not null default current_date,
    channel text not null default 'telegram',
    payload jsonb,
    created_at timestamptz not null default now(),
    unique (workspace_id, kind, sent_on),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create index projects_tenant_idx on public.projects(user_id, workspace_id);
create index milestones_tenant_idx on public.milestones(user_id, workspace_id);
create index milestones_project_idx on public.milestones(project_id);
create index planner_tasks_tenant_idx on public.planner_tasks(user_id, workspace_id);
create index planner_tasks_due_idx on public.planner_tasks(workspace_id, due_date)
    where status not in ('done', 'skipped');
create index planner_tasks_scheduled_idx on public.planner_tasks(workspace_id, scheduled_date)
    where status not in ('done', 'skipped');
create index task_completions_tenant_day_idx
    on public.task_completions(user_id, workspace_id, completed_on);

alter table public.projects enable row level security;
alter table public.milestones enable row level security;
alter table public.planner_tasks enable row level security;
alter table public.task_completions enable row level security;
alter table public.reminder_log enable row level security;

create policy projects_owner_all on public.projects
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy milestones_owner_all on public.milestones
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy planner_tasks_owner_all on public.planner_tasks
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy task_completions_owner_all on public.task_completions
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy reminder_log_owner_all on public.reminder_log
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.projects to authenticated;
grant select, insert, update, delete on public.milestones to authenticated;
grant select, insert, update, delete on public.planner_tasks to authenticated;
grant select, insert, update, delete on public.task_completions to authenticated;
grant select, insert, update, delete on public.reminder_log to authenticated;
