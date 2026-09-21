-- Funding plan: what the Germany move will cost, what will pay for it, and
-- whether the money arrives before the bills do.
--
-- finance_logs already answers "where did the money go". It cannot answer
-- "will I run out, and when" — that needs the estimates alongside the funding,
-- both carrying dates. Two tables do it:
--
--   finance_plans       one plan (the Germany move) and the rate used to put
--                       euro and rupee lines on the same axis.
--   finance_plan_items  every cost line and every funding line, each with the
--                       date the money moves. kind separates the two sides.
--
-- A plan item is an estimate. finance_logs.plan_item_id links what actually
-- got spent back to the line that predicted it, so estimate, actual and
-- remaining all read off the same row.

-- 1. The plan and its planning rate.
create table if not exists public.finance_plans (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    name text not null,
    -- Every headline is reported in this currency. Lines keep their own.
    base_currency text not null default 'INR',
    -- One euro in base currency. A single hand-set planning rate, shown next
    -- to every converted total, beats a live rate nobody can reproduce when
    -- the number is questioned six months from now.
    eur_rate numeric(12,4) not null default 100,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint finance_plans_eur_rate_check check (eur_rate > 0),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 2. Cost lines and funding lines, side by side in one table.
create table if not exists public.finance_plan_items (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    plan_id uuid not null references public.finance_plans(id) on delete cascade,
    -- 'cost' is money going out, 'fund' is money coming in.
    kind text not null,
    label text not null,
    category text,
    -- Per instalment, not the total: a monthly saving of 40,000 over ten
    -- months is amount 40000, instalments 10. A one-off leaves instalments 1.
    amount numeric(12,2) not null default 0,
    currency text not null default 'INR',
    -- A cost's due date, or the date a fund becomes available. Null means the
    -- money is already in hand (fund) or the date is not settled yet (cost);
    -- either way the row still counts towards the totals.
    due_date date,
    instalments int not null default 1,
    -- Unconfirmed funding is still worth planning around, but the shortfall
    -- has to be readable without it.
    certainty text not null default 'likely',
    notes text,
    sort_order int not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint finance_plan_items_kind_check check (kind in ('cost', 'fund')),
    constraint finance_plan_items_certainty_check
        check (certainty in ('confirmed', 'likely', 'maybe')),
    constraint finance_plan_items_amount_check check (amount >= 0),
    constraint finance_plan_items_instalments_check
        check (instalments between 1 and 600),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 3. Tie actual spending back to the line that estimated it. Dropping a plan
--    line must not delete the transaction — the money still left the account.
alter table public.finance_logs add column if not exists plan_item_id uuid;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'finance_logs_plan_item_id_fkey'
    ) then
        alter table public.finance_logs
            add constraint finance_logs_plan_item_id_fkey
            foreign key (plan_item_id) references public.finance_plan_items(id)
            on delete set null;
    end if;
end $$;

-- 4. Indexes. The widget reads one plan's items in sort order, then rolls the
--    linked transactions up per item.
create index if not exists finance_plans_tenant_idx
    on public.finance_plans (user_id, workspace_id);
create index if not exists finance_plan_items_plan_idx
    on public.finance_plan_items (plan_id, kind, sort_order);
create index if not exists finance_plan_items_tenant_idx
    on public.finance_plan_items (user_id, workspace_id);
create index if not exists finance_logs_plan_item_idx
    on public.finance_logs (plan_item_id) where plan_item_id is not null;

-- 5. Row level security, matching the rest of the finance tables.
alter table public.finance_plans enable row level security;
alter table public.finance_plan_items enable row level security;

drop policy if exists finance_plans_owner_all on public.finance_plans;
create policy finance_plans_owner_all on public.finance_plans
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

drop policy if exists finance_plan_items_owner_all on public.finance_plan_items;
create policy finance_plan_items_owner_all on public.finance_plan_items
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.finance_plans to authenticated, service_role;
grant select, insert, update, delete on public.finance_plan_items to authenticated, service_role;

-- 6. Start every active workspace off with one plan, so the screen opens on an
--    empty plan rather than on a "create a plan" step.
insert into public.finance_plans (user_id, workspace_id, name, base_currency, eur_rate)
select w.user_id, w.id, 'Germany move', 'INR', 100
from public.workspaces w
where not exists (
    select 1 from public.finance_plans p
    where p.user_id = w.user_id and p.workspace_id = w.id
);
