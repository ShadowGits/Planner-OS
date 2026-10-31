-- Budget and funding by category, with the itemised view switched on per
-- category rather than everywhere.
--
-- 0032 gave the plan cost lines and funding lines. Every number on the screen
-- had to be itemised to exist, which is the wrong shape for most of the plan:
-- "mom is sending 8 lakh" is one number, not a ledger. Two questions are being
-- asked, and they are both answered a category at a time:
--
--   1. what is budgeted for each thing (operational, mom, …)
--   2. how much money there will be by the horizon (end of July 2027)
--
-- (2) - (1) is the loan. Both lanes are typed numbers, so a category exists
-- without any lines under it. A category can then opt into the detailed view,
-- and its plan lines (0032's finance_plan_items) break the budget down and
-- carry the mark-paid tracking. Only the categories that need it get one.
--
--   finance_plan_categories  one row per lane entry: its budget, what has
--                            been paid against it, and whether it is detailed.
--   finance_plan_items       unchanged, now pointing at the category it
--                            belongs to.

-- 1. The horizon every funding figure is read at.
alter table public.finance_plans add column if not exists horizon_date date;
update public.finance_plans set horizon_date = date '2027-07-31' where horizon_date is null;

-- 2. The lanes.
create table if not exists public.finance_plan_categories (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    plan_id uuid not null references public.finance_plans(id) on delete cascade,
    -- 'cost' is the budget lane, 'fund' is the money-available lane, matching
    -- finance_plan_items.kind so a category and its lines are the same side.
    kind text not null,
    name text not null,
    -- The budget (cost) or what is expected by the horizon (fund). Typed, not
    -- summed: the lane has to total correctly whether or not it is itemised.
    amount numeric(12,2) not null default 0,
    -- Paid (cost) or received (fund) so far, for a category with no detail.
    -- A detailed category ignores this and adds up its lines instead, so the
    -- figure cannot drift from the payments recorded against them.
    paid numeric(12,2) not null default 0,
    currency text not null default 'INR',
    -- Whether this category shows the itemised plan-and-pay view.
    detailed boolean not null default false,
    notes text,
    sort_order int not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint finance_plan_categories_kind_check check (kind in ('cost', 'fund')),
    constraint finance_plan_categories_amount_check check (amount >= 0),
    constraint finance_plan_categories_paid_check check (paid >= 0),
    foreign key (user_id, workspace_id) references public.workspaces(user_id, id) on delete cascade
);

-- 3. Which category a plan line belongs to. Dropping a category takes its
--    lines with it (they are its breakdown), but never the transactions: the
--    money still left the account, and finance_logs.plan_item_id is cleared
--    by 0032's own foreign key.
alter table public.finance_plan_items add column if not exists category_id uuid;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'finance_plan_items_category_id_fkey'
    ) then
        alter table public.finance_plan_items
            add constraint finance_plan_items_category_id_fkey
            foreign key (category_id) references public.finance_plan_categories(id)
            on delete cascade;
    end if;
end $$;

-- 4. Indexes. The screen reads one plan's categories in sort order, then each
--    detailed category's lines.
create index if not exists finance_plan_categories_plan_idx
    on public.finance_plan_categories (plan_id, kind, sort_order);
create index if not exists finance_plan_categories_tenant_idx
    on public.finance_plan_categories (user_id, workspace_id);
create index if not exists finance_plan_items_category_idx
    on public.finance_plan_items (category_id) where category_id is not null;
-- One "Operational" per side of a plan, whatever it was typed as.
create unique index if not exists finance_plan_categories_name_idx
    on public.finance_plan_categories (plan_id, kind, lower(name));

-- 5. Row level security, matching the rest of the finance tables.
alter table public.finance_plan_categories enable row level security;

drop policy if exists finance_plan_categories_owner_all on public.finance_plan_categories;
create policy finance_plan_categories_owner_all on public.finance_plan_categories
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

grant select, insert, update, delete on public.finance_plan_categories to authenticated, service_role;

-- 6. Carry the existing plan across. Every distinct category already on a plan
--    line becomes a lane entry, budgeted at what its lines come to and opened
--    with the detailed view on, so nothing that was on screen disappears.
--    Lines are converted at the plan's own rate, exactly as the screen does.
insert into public.finance_plan_categories
    (user_id, workspace_id, plan_id, kind, name, amount, currency, detailed, sort_order)
select
    i.user_id,
    i.workspace_id,
    i.plan_id,
    i.kind,
    coalesce(nullif(btrim(i.category), ''), 'Other') as name,
    round(sum(
        i.amount * greatest(i.instalments, 1) *
        case
            when upper(i.currency) = upper(p.base_currency) then 1
            when upper(i.currency) = 'EUR' and upper(p.base_currency) = 'INR' then p.eur_rate
            when upper(i.currency) = 'INR' and upper(p.base_currency) = 'EUR' then 1 / p.eur_rate
            else 1
        end
    ), 2) as amount,
    p.base_currency,
    true,
    min(i.sort_order)
from public.finance_plan_items i
join public.finance_plans p on p.id = i.plan_id
group by i.user_id, i.workspace_id, i.plan_id, i.kind,
         coalesce(nullif(btrim(i.category), ''), 'Other'), p.base_currency
on conflict do nothing;

update public.finance_plan_items i
set category_id = c.id
from public.finance_plan_categories c
where i.category_id is null
  and c.plan_id = i.plan_id
  and c.kind = i.kind
  and lower(c.name) = lower(coalesce(nullif(btrim(i.category), ''), 'Other'));
