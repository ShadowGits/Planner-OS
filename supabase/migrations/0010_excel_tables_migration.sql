-- Migration 0010: Database tables for offline Excel data migration

-- 1. Study Logs
create table if not exists public.study_logs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    date date not null default current_date,
    task text not null,
    category text,
    topic text,
    duration_minutes integer default 0,
    priority text default 'medium',
    completed boolean default false,
    estimated_effort text,
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 2. Study Topics
create table if not exists public.study_topics (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    subject text not null,
    unit text,
    topic text not null,
    subtopic text,
    status text default 'not_started',
    confidence integer default 1,
    hours_spent numeric(6,2) default 0.0,
    problems_solved integer default 0,
    video_watched boolean default false,
    book_chapter text,
    notes text,
    difficulty text,
    importance text,
    dependencies text,
    last_revised date,
    next_revision date,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 3. Study Subjects
create table if not exists public.study_subjects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    subject text not null,
    description text,
    target_hours integer default 0,
    priority text default 'medium',
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 4. Study Revisions
create table if not exists public.study_revisions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    date date not null default current_date,
    topic text not null,
    subject text,
    confidence integer default 1,
    quality text,
    next_revision date,
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 5. Study Problems
create table if not exists public.study_problems (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    date date not null default current_date,
    topic text not null,
    difficulty text,
    source text,
    correct boolean default true,
    time_taken integer default 0,
    hints_used integer default 0,
    confidence integer default 1,
    mistakes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 6. Books Tracker
create table if not exists public.books (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    book text not null,
    chapter text,
    progress text,
    pages integer default 0,
    completion_pct integer default 0,
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 7. Colleges
create table if not exists public.colleges (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    university text not null,
    program text,
    city text,
    tuition_per_sem text,
    language_of_instruction text,
    requirements text,
    uni_assist boolean default false,
    application_open date,
    deadline date,
    status text default 'researching',
    priority text default 'medium',
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 8. College & Academic Applications
create table if not exists public.college_applications (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    institute text not null,
    professor text,
    research_area text,
    email text,
    website text,
    status text default 'planned',
    applied boolean default false,
    response text,
    interview date,
    offer boolean default false,
    notes text,
    deadline date,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 9. Germany Documents
create table if not exists public.germany_documents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    document text not null,
    category text,
    status text default 'pending',
    needs_apostille boolean default false,
    needs_translation boolean default false,
    deadline date,
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 10. Finance Goals
create table if not exists public.finance_goals (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    goal text not null,
    target_amount numeric(12,2) default 0.0,
    saved_amount numeric(12,2) default 0.0,
    deadline date,
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 11. Finance Logs
create table if not exists public.finance_logs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    date date not null default current_date,
    category text,
    description text,
    amount numeric(12,2) default 0.0,
    currency text default 'EUR',
    type text default 'expense',
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- Row level security
alter table public.study_logs enable row level security;
alter table public.study_topics enable row level security;
alter table public.study_subjects enable row level security;
alter table public.study_revisions enable row level security;
alter table public.study_problems enable row level security;
alter table public.books enable row level security;
alter table public.colleges enable row level security;
alter table public.college_applications enable row level security;
alter table public.germany_documents enable row level security;
alter table public.finance_goals enable row level security;
alter table public.finance_logs enable row level security;

-- Owner policies
create policy study_logs_owner_all on public.study_logs for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy study_topics_owner_all on public.study_topics for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy study_subjects_owner_all on public.study_subjects for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy study_revisions_owner_all on public.study_revisions for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy study_problems_owner_all on public.study_problems for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy books_owner_all on public.books for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy colleges_owner_all on public.colleges for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy college_applications_owner_all on public.college_applications for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy germany_documents_owner_all on public.germany_documents for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy finance_goals_owner_all on public.finance_goals for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy finance_logs_owner_all on public.finance_logs for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- Grants
grant select, insert, update, delete on public.study_logs to authenticated, service_role;
grant select, insert, update, delete on public.study_topics to authenticated, service_role;
grant select, insert, update, delete on public.study_subjects to authenticated, service_role;
grant select, insert, update, delete on public.study_revisions to authenticated, service_role;
grant select, insert, update, delete on public.study_problems to authenticated, service_role;
grant select, insert, update, delete on public.books to authenticated, service_role;
grant select, insert, update, delete on public.colleges to authenticated, service_role;
grant select, insert, update, delete on public.college_applications to authenticated, service_role;
grant select, insert, update, delete on public.germany_documents to authenticated, service_role;
grant select, insert, update, delete on public.finance_goals to authenticated, service_role;
grant select, insert, update, delete on public.finance_logs to authenticated, service_role;
