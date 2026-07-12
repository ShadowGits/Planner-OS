-- Planner OS MVP3 Supabase foundation.
-- Apply once through the Supabase migration runner before deploying the API.

create table public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    display_name text,
    timezone text not null default 'UTC',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.workspaces (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    timezone text not null default 'UTC',
    active_execution_target text not null default 'none'
        check (active_execution_target in ('google_calendar', 'apple_calendar', 'none')),
    workbook_bucket text not null default 'planner-workbooks'
        check (workbook_bucket = 'planner-workbooks'),
    workbook_key text not null,
    workbook_sha256 text check (workbook_sha256 is null or workbook_sha256 ~ '^[0-9a-f]{64}$'),
    revision bigint not null default 0 check (revision >= 0),
    settings_revision bigint not null default 0 check (settings_revision >= 0),
    is_active boolean not null default false,
    lock_owner uuid,
    locked_until timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id),
    unique (user_id, workbook_key),
    check (workbook_key = user_id::text || '/' || id::text || '/current.xlsx')
);

create table public.calendar_connections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    provider text not null check (provider in ('google_calendar')),
    encrypted_credentials bytea not null,
    encryption_key_version integer not null default 1,
    provider_account_id text,
    target_calendar_id text not null default 'primary',
    status text not null default 'active' check (status in ('active', 'expired', 'revoked', 'error')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, workspace_id, provider),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create table public.calendar_event_mappings (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    provider text not null check (provider in ('google_calendar', 'apple_calendar')),
    planner_task_id text,
    planner_block_id text not null,
    external_id text not null,
    status text not null default 'active'
        check (status in ('active', 'inactive', 'orphaned', 'retired_unsupported')),
    checksum text not null,
    published_at timestamptz not null default now(),
    last_synced_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create unique index calendar_event_mappings_active_block
    on public.calendar_event_mappings(user_id, workspace_id, planner_block_id)
    where status = 'active';
create unique index calendar_event_mappings_provider_external
    on public.calendar_event_mappings(user_id, workspace_id, provider, external_id);

create table public.planner_previews (
    id text not null,
    user_id uuid not null,
    workspace_id uuid not null,
    operation_type text not null,
    payload jsonb not null,
    source_revision bigint not null check (source_revision >= 0),
    settings_revision bigint not null default 0 check (settings_revision >= 0),
    active_execution_target text not null
        check (active_execution_target in ('google_calendar', 'apple_calendar', 'none')),
    external_source_fingerprint text,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    consumed_at timestamptz,
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade,
    primary key (user_id, workspace_id, id),
    check (expires_at > created_at)
);

create table public.planner_operations (
    id uuid primary key,
    user_id uuid not null,
    workspace_id uuid not null,
    tool_name text not null,
    status text not null check (status in ('running', 'succeeded', 'failed', 'partial')),
    source_revision bigint,
    result_revision bigint,
    sanitized_result jsonb not null default '{}'::jsonb,
    error_code text,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (user_id, workspace_id, id),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade
);

create table public.audit_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    operation_id uuid,
    event_type text not null,
    severity text not null default 'info' check (severity in ('info', 'warning', 'error', 'security')),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade,
    foreign key (user_id, workspace_id, operation_id)
        references public.planner_operations(user_id, workspace_id, id) on delete restrict
);

create table public.oauth_states (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid not null,
    provider text not null check (provider = 'google_calendar'),
    state_hash text not null unique check (state_hash ~ '^[0-9a-f]{64}$'),
    redirect_uri text not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    consumed_at timestamptz,
    foreign key (user_id, workspace_id)
        references public.workspaces(user_id, id) on delete cascade,
    check (expires_at > created_at)
);

create table public.tool_registry_versions (
    id bigint generated always as identity primary key,
    manifest_sha256 text not null unique check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    schema_version integer not null,
    tool_count integer not null check (tool_count > 0),
    manifest jsonb not null,
    created_at timestamptz not null default now()
);

create index workspaces_user_id_idx on public.workspaces(user_id);
create unique index workspaces_one_active_per_user
    on public.workspaces(user_id) where is_active;
create index calendar_connections_tenant_idx on public.calendar_connections(user_id, workspace_id);
create index calendar_event_mappings_tenant_idx on public.calendar_event_mappings(user_id, workspace_id);
create index planner_previews_tenant_idx on public.planner_previews(user_id, workspace_id);
create index planner_previews_expiry_idx on public.planner_previews(expires_at) where consumed_at is null;
create index planner_operations_tenant_idx on public.planner_operations(user_id, workspace_id);
create index audit_events_tenant_idx on public.audit_events(user_id, workspace_id);
create index oauth_states_tenant_idx on public.oauth_states(user_id, workspace_id);

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.calendar_connections enable row level security;
alter table public.calendar_event_mappings enable row level security;
alter table public.planner_previews enable row level security;
alter table public.planner_operations enable row level security;
alter table public.audit_events enable row level security;
alter table public.oauth_states enable row level security;
alter table public.tool_registry_versions enable row level security;

create policy profiles_owner_all on public.profiles
    for all to authenticated
    using ((select auth.uid()) = id)
    with check ((select auth.uid()) = id);

create policy workspaces_owner_all on public.workspaces
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy calendar_connections_owner_all on public.calendar_connections
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy calendar_event_mappings_owner_all on public.calendar_event_mappings
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy planner_previews_owner_all on public.planner_previews
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy planner_operations_owner_all on public.planner_operations
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy audit_events_owner_select on public.audit_events
    for select to authenticated
    using ((select auth.uid()) = user_id);

create policy audit_events_owner_insert on public.audit_events
    for insert to authenticated
    with check ((select auth.uid()) = user_id);

create policy oauth_states_owner_all on public.oauth_states
    for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy tool_registry_authenticated_read on public.tool_registry_versions
    for select to authenticated using (true);

grant select, insert, update, delete on public.profiles to authenticated;
grant select, insert, update, delete on public.workspaces to authenticated;
grant select, insert, update, delete on public.calendar_connections to authenticated;
grant select, insert, update, delete on public.calendar_event_mappings to authenticated;
grant select, insert, update, delete on public.planner_previews to authenticated;
grant select, insert, update on public.planner_operations to authenticated;
grant select, insert on public.audit_events to authenticated;
grant select, insert, update, delete on public.oauth_states to authenticated;
grant select on public.tool_registry_versions to authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'planner-workbooks',
    'planner-workbooks',
    false,
    52428800,
    array[
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/json'
    ]
)
on conflict (id) do update set
    public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create policy planner_workbooks_owner_select on storage.objects
    for select to authenticated
    using (
        bucket_id = 'planner-workbooks'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
            select 1 from public.workspaces w
            where w.user_id = (select auth.uid())
              and w.id::text = (storage.foldername(name))[2]
        )
    );

create policy planner_workbooks_owner_insert on storage.objects
    for insert to authenticated
    with check (
        bucket_id = 'planner-workbooks'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
            select 1 from public.workspaces w
            where w.user_id = (select auth.uid())
              and w.id::text = (storage.foldername(name))[2]
        )
    );

create policy planner_workbooks_owner_update on storage.objects
    for update to authenticated
    using (
        bucket_id = 'planner-workbooks'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
            select 1 from public.workspaces w
            where w.user_id = (select auth.uid())
              and w.id::text = (storage.foldername(name))[2]
        )
    )
    with check (
        bucket_id = 'planner-workbooks'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
            select 1 from public.workspaces w
            where w.user_id = (select auth.uid())
              and w.id::text = (storage.foldername(name))[2]
        )
    );

create policy planner_workbooks_owner_delete on storage.objects
    for delete to authenticated
    using (
        bucket_id = 'planner-workbooks'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
            select 1 from public.workspaces w
            where w.user_id = (select auth.uid())
              and w.id::text = (storage.foldername(name))[2]
        )
    );

create or replace function public.acquire_workspace_lock(
    p_workspace_id uuid,
    p_lock_owner uuid,
    p_ttl_seconds integer default 60
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    if (select auth.uid()) is null then
        return null;
    end if;
    if p_ttl_seconds < 5 or p_ttl_seconds > 300 then
        raise exception 'lock TTL must be between 5 and 300 seconds';
    end if;
    update public.workspaces as w
       set lock_owner = p_lock_owner,
           locked_until = now() + make_interval(secs => p_ttl_seconds),
           updated_at = now()
     where w.id = p_workspace_id
       and w.user_id = (select auth.uid())
       and (w.lock_owner is null or w.locked_until <= now() or w.lock_owner = p_lock_owner)
    returning to_jsonb(w) into v_result;
    return v_result;
end;
$$;

create or replace function public.activate_workspace(p_workspace_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    if (select auth.uid()) is null then
        return null;
    end if;
    if not exists (
        select 1 from public.workspaces w
        where w.id = p_workspace_id
          and w.user_id = (select auth.uid())
    ) then
        return null;
    end if;
    update public.workspaces as w
       set is_active = false,
           updated_at = now()
     where w.user_id = (select auth.uid())
       and w.is_active;
    update public.workspaces as w
       set is_active = true,
           updated_at = now()
     where w.id = p_workspace_id
       and w.user_id = (select auth.uid())
    returning to_jsonb(w) into v_result;
    return v_result;
end;
$$;

create or replace function public.release_workspace_lock(
    p_workspace_id uuid,
    p_lock_owner uuid
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_count integer;
begin
    update public.workspaces as w
       set lock_owner = null,
           locked_until = null,
           updated_at = now()
     where w.id = p_workspace_id
       and w.user_id = (select auth.uid())
       and w.lock_owner = p_lock_owner;
    get diagnostics v_count = row_count;
    return v_count = 1;
end;
$$;

create or replace function public.consume_planner_preview(
    p_preview_id text,
    p_workspace_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    update public.planner_previews as p
       set consumed_at = now()
     where p.id = p_preview_id
       and p.workspace_id = p_workspace_id
       and p.user_id = (select auth.uid())
       and p.consumed_at is null
       and p.expires_at > now()
    returning to_jsonb(p) into v_result;
    return v_result;
end;
$$;

revoke execute on function public.acquire_workspace_lock(uuid, uuid, integer) from public, anon;
revoke execute on function public.activate_workspace(uuid) from public, anon;
revoke execute on function public.release_workspace_lock(uuid, uuid) from public, anon;
revoke execute on function public.consume_planner_preview(text, uuid) from public, anon;
grant execute on function public.acquire_workspace_lock(uuid, uuid, integer) to authenticated;
grant execute on function public.activate_workspace(uuid) to authenticated;
grant execute on function public.release_workspace_lock(uuid, uuid) to authenticated;
grant execute on function public.consume_planner_preview(text, uuid) to authenticated;
