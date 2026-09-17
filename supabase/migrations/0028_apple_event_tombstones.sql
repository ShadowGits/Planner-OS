-- Remember Apple calendar events that were deleted here.
--
-- The ICS import keys on the calendar event's UID and skips anything already
-- imported, but it worked that out by reading the UIDs off existing tasks. So
-- deleting an imported task also deleted the only record that it had ever been
-- imported, and the next calendar sync created it again — a task that could not
-- be got rid of.
--
-- A deleted event is recorded here instead, and the import treats these UIDs as
-- already handled. The import stays one-directional: removing it here keeps it
-- gone, without touching the calendar it came from.

create table if not exists public.apple_event_tombstones (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    apple_uid text not null,
    created_at timestamptz not null default now(),
    unique (workspace_id, apple_uid)
);

create index if not exists apple_event_tombstones_tenant_idx
    on public.apple_event_tombstones(user_id, workspace_id);

alter table public.apple_event_tombstones enable row level security;

create policy apple_event_tombstones_owner_all on public.apple_event_tombstones
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

grant select, insert, update, delete on public.apple_event_tombstones to authenticated;
grant all on public.apple_event_tombstones to service_role;
