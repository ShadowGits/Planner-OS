-- Migration 0012: Add custom tables for Germany and Colleges applications
-- These tables map to the legacy Excel sheets and link to the projects table.

create table public.germany_tests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    test text not null,
    target_score text,
    registration_deadline text,
    test_date text,
    result text,
    status text,
    fee text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create table public.colleges (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    university text not null,
    program text,
    city text,
    tuition_per_sem text,
    language_of_instruction text,
    requirements text,
    uni_assist text,
    application_open text,
    deadline text,
    status text,
    priority text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create table public.applications (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    institute text not null,
    professor text,
    research_area text,
    email text,
    website text,
    status text,
    applied text,
    response text,
    interview text,
    offer text,
    notes text,
    deadline text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create table public.professors (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    institute text not null,
    professor text not null,
    research_area text,
    email text,
    website text,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create table public.research_papers (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    title text not null,
    authors text,
    link text,
    pdf text,
    status text,
    summary text,
    key_ideas text,
    mathematics_used text,
    questions text,
    implementation_ideas text,
    tags text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- Indexes for performance
create index germany_tests_tenant_idx on public.germany_tests(user_id, workspace_id);
create index germany_tests_project_idx on public.germany_tests(project_id);

create index colleges_tenant_idx on public.colleges(user_id, workspace_id);
create index colleges_project_idx on public.colleges(project_id);

create index applications_tenant_idx on public.applications(user_id, workspace_id);
create index applications_project_idx on public.applications(project_id);

create index professors_tenant_idx on public.professors(user_id, workspace_id);
create index professors_project_idx on public.professors(project_id);

create index research_papers_tenant_idx on public.research_papers(user_id, workspace_id);
create index research_papers_project_idx on public.research_papers(project_id);

-- Row Level Security
alter table public.germany_tests enable row level security;
alter table public.colleges enable row level security;
alter table public.applications enable row level security;
alter table public.professors enable row level security;
alter table public.research_papers enable row level security;

-- Policies for Authenticated Users
create policy germany_tests_owner_all on public.germany_tests for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy colleges_owner_all on public.colleges for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy applications_owner_all on public.applications for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy professors_owner_all on public.professors for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy research_papers_owner_all on public.research_papers for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- Grants
grant select, insert, update, delete on public.germany_tests to authenticated;
grant select, insert, update, delete on public.colleges to authenticated;
grant select, insert, update, delete on public.applications to authenticated;
grant select, insert, update, delete on public.professors to authenticated;
grant select, insert, update, delete on public.research_papers to authenticated;

-- Service Role Grants
grant all privileges on public.germany_tests to service_role;
grant all privileges on public.colleges to service_role;
grant all privileges on public.applications to service_role;
grant all privileges on public.professors to service_role;
grant all privileges on public.research_papers to service_role;
