-- Migration 0008: Add monthly and weekly goals tables.
-- These tables support high-level planning that is divided into actionable tasks.

create table public.monthly_goals (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    month date not null,
    description text not null,
    status text not null default 'active' check (status in ('active', 'done')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project_id, month),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create table public.weekly_goals (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    week_start date not null,
    description text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project_id, week_start),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create index monthly_goals_tenant_idx on public.monthly_goals(user_id, workspace_id);
create index monthly_goals_project_idx on public.monthly_goals(project_id);
create index weekly_goals_tenant_idx on public.weekly_goals(user_id, workspace_id);
create index weekly_goals_project_idx on public.weekly_goals(project_id);

alter table public.monthly_goals enable row level security;
alter table public.weekly_goals enable row level security;

create policy monthly_goals_owner_all on public.monthly_goals
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy weekly_goals_owner_all on public.weekly_goals
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.monthly_goals to authenticated;
grant select, insert, update, delete on public.weekly_goals to authenticated;
