-- Habits: things you do repeatedly where the unit of success is "did I do it
-- today", not "is this piece of work finished".
--
-- These used to be ordinary tasks, pre-generated a year ahead — 295 gym rows,
-- 294 sleep rows. Every day that passed unticked became overdue for ever, and
-- the count grew by two a day. They also sat in every task query.
--
-- A habit is a rule now. Occurrences are worked out on read, so there are no
-- rows to go stale. Ticking one writes to task_completions, which is where
-- streaks already come from, so that keeps working untouched.
--
-- Deliberately separate from planner_tasks: a habit has no deadline, is never
-- overdue and is never counted as open work. Keeping it in the same table is
-- what made those three things hard to express in the first place.

create table if not exists public.habits (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    title text not null,
    -- matches task_completions.recurrence_key, so existing streaks carry over
    recurrence_key text not null,
    cadence text not null default 'daily',        -- daily | weekly
    -- 0=Sunday .. 6=Saturday. Empty means every day.
    days_of_week smallint[] not null default '{}',
    start_time time,
    estimated_minutes integer,
    project_id uuid,
    start_date date not null default current_date,
    end_date date,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- One occurrence that got moved, retimed or skipped. Absence of a row means
-- the occurrence is exactly what the rule says, so a year of unchanged days
-- costs nothing.
create table if not exists public.habit_overrides (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    habit_id uuid not null references public.habits(id) on delete cascade,
    -- the day the rule put it on
    on_date date not null,
    -- where it went; null with skipped=false means same day, retimed only
    moved_to date,
    start_time time,
    estimated_minutes integer,
    skipped boolean not null default false,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

create unique index if not exists habit_overrides_one_per_day
    on public.habit_overrides (habit_id, on_date);

create index if not exists habits_workspace_active
    on public.habits (user_id, workspace_id, is_active);

create index if not exists habit_overrides_lookup
    on public.habit_overrides (habit_id, on_date, moved_to);

-- Completions are matched by (recurrence_key, completed_on), so the day view
-- can tell at a glance which occurrences are already ticked.
create index if not exists task_completions_key_day
    on public.task_completions (recurrence_key, completed_on);

alter table public.habits enable row level security;
alter table public.habit_overrides enable row level security;

drop policy if exists habits_owner_all on public.habits;
create policy habits_owner_all on public.habits
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists habit_overrides_owner_all on public.habit_overrides;
create policy habit_overrides_owner_all on public.habit_overrides
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.habits to authenticated, service_role;
grant select, insert, update, delete on public.habit_overrides to authenticated, service_role;
