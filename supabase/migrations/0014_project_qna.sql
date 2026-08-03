-- Migration 0014: Add project_qna table for interview questions and notes

create table public.project_qna (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    question text not null,
    answer text,
    status text not null default 'Drafting',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create index project_qna_tenant_idx on public.project_qna(user_id, workspace_id);
create index project_qna_project_idx on public.project_qna(project_id);

alter table public.project_qna enable row level security;

create policy project_qna_owner_all on public.project_qna 
    for all to authenticated 
    using ((select auth.uid()) = user_id) 
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.project_qna to authenticated;
grant all privileges on public.project_qna to service_role;
