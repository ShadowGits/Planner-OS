-- The unique external_id index must only cover active rows: import retires
-- legacy event-keyed link rows to status 'inactive' before writing the
-- block-keyed row for the same external event, and both rows share
-- (user_id, workspace_id, provider, external_id).

drop index if exists public.calendar_event_mappings_provider_external;
create unique index calendar_event_mappings_provider_external
    on public.calendar_event_mappings(user_id, workspace_id, provider, external_id)
    where status = 'active';
