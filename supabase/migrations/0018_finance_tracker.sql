-- Personal finance tracker.
--
-- finance_goals and finance_logs were both declared in 0010, but only the
-- goals half reached the live database. This migration creates whatever is
-- missing and then adds what the expense side needs: where the money went,
-- how it was paid, and an optional link from a savings transfer to the
-- Germany goal it funds, so saved_amount stops being a hand-typed number.

-- 0. Create the base tables if 0010 never landed them.
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

create table if not exists public.finance_logs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    date date not null default current_date,
    category text,
    description text,
    amount numeric(12,2) default 0.0,
    currency text default 'INR',
    type text default 'expense',
    notes text,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

alter table public.finance_goals enable row level security;
alter table public.finance_logs enable row level security;

drop policy if exists finance_goals_owner_all on public.finance_goals;
create policy finance_goals_owner_all on public.finance_goals
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists finance_logs_owner_all on public.finance_logs;
create policy finance_logs_owner_all on public.finance_logs
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.finance_goals to authenticated, service_role;
grant select, insert, update, delete on public.finance_logs to authenticated, service_role;

-- 1. Expense log: the passbook.
alter table public.finance_logs add column if not exists merchant text;
alter table public.finance_logs add column if not exists payment_method text;
alter table public.finance_logs add column if not exists goal_id uuid;
alter table public.finance_logs add column if not exists recurring_id uuid;
alter table public.finance_logs add column if not exists updated_at timestamptz not null default now();

-- Day-to-day spending is in rupees; the EUR default came from the Germany
-- goals sharing this schema. Every row still carries its own currency.
alter table public.finance_logs alter column currency set default 'INR';

-- A transaction funding a savings goal points at it. Clearing the goal must
-- not delete the transaction — the money still left the account.
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'finance_logs_goal_id_fkey'
    ) then
        alter table public.finance_logs
            add constraint finance_logs_goal_id_fkey
            foreign key (goal_id) references public.finance_goals(id) on delete set null;
    end if;
end $$;

-- The passbook reads newest-first within a tenant; the summary groups by
-- category over a month.
create index if not exists finance_logs_tenant_date_idx
    on public.finance_logs (user_id, workspace_id, date desc);
create index if not exists finance_logs_category_idx
    on public.finance_logs (user_id, workspace_id, category);
create index if not exists finance_logs_goal_idx
    on public.finance_logs (goal_id) where goal_id is not null;

-- 2. Goals carry a currency so a Rs 500 lunch can never be mistaken for a
--    EUR 500 contribution to the blocked account.
alter table public.finance_goals add column if not exists currency text not null default 'EUR';

-- 3. Recurring charges: rent, subscriptions, EMIs. Rows here are templates;
--    the cron materialises them into finance_logs as each one falls due.
create table if not exists public.finance_recurring (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    description text not null,
    amount numeric(12,2) not null,
    currency text not null default 'INR',
    category text,
    merchant text,
    payment_method text,
    type text not null default 'expense',
    cadence text not null default 'monthly',
    day_of_month int,
    day_of_week int,
    start_date date not null default current_date,
    end_date date,
    active boolean not null default true,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint finance_recurring_cadence_check
        check (cadence in ('weekly', 'monthly', 'yearly')),
    constraint finance_recurring_type_check
        check (type in ('expense', 'income')),
    constraint finance_recurring_day_of_month_check
        check (day_of_month is null or day_of_month between 1 and 31),
    constraint finance_recurring_day_of_week_check
        check (day_of_week is null or day_of_week between 0 and 6),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'finance_logs_recurring_id_fkey'
    ) then
        alter table public.finance_logs
            add constraint finance_logs_recurring_id_fkey
            foreign key (recurring_id) references public.finance_recurring(id) on delete set null;
    end if;
end $$;

create index if not exists finance_recurring_tenant_active_idx
    on public.finance_recurring (user_id, workspace_id, active);

-- Idempotency for the materialiser: one generated row per rule per date, so a
-- cron that fires twice (or a retry) cannot double-charge the passbook.
create unique index if not exists finance_logs_recurring_date_uniq
    on public.finance_logs (recurring_id, date) where recurring_id is not null;

-- 4. RLS. finance_logs and finance_goals were already covered in 0010.
alter table public.finance_recurring enable row level security;

drop policy if exists finance_recurring_owner_all on public.finance_recurring;
create policy finance_recurring_owner_all on public.finance_recurring
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.finance_recurring to authenticated, service_role;
