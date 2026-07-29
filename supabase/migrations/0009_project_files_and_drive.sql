-- Migration 0009: Project Files and Google Drive Folder metadata

alter table public.projects add column if not exists drive_folder_id text;

create table public.project_files (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    project_id uuid not null references public.projects(id) on delete cascade,
    name text not null,
    file_type text not null check (file_type in ('text', 'excel', 'pdf', 'other')),
    drive_file_id text not null,
    drive_web_view_link text,
    drive_embed_link text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create index project_files_tenant_idx on public.project_files(user_id, workspace_id);
create index project_files_project_idx on public.project_files(project_id);

alter table public.project_files enable row level security;

create policy project_files_owner_all on public.project_files
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.project_files to authenticated;
grant select, insert, update, delete on public.project_files to service_role;
