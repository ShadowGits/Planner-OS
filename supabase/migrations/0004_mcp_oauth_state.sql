-- Persistent MCP OAuth state: registered clients, authorization codes, and
-- access/refresh tokens. Previously kept in process memory, which forced a
-- full claude.ai reconnect after every Cloud Run deploy or cold start.
--
-- record_key holds the client_id for kind 'client' and a SHA-256 hash of the
-- secret for codes and tokens, so raw bearer credentials are never stored.
-- Only the service role touches this table; RLS is enabled with no policies
-- so anon/authenticated roles have no access.

create table public.mcp_oauth_records (
    kind text not null
        check (kind in ('client', 'auth_code', 'access_token', 'refresh_token')),
    record_key text not null,
    payload jsonb not null,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    primary key (kind, record_key)
);

create index mcp_oauth_records_expiry_idx
    on public.mcp_oauth_records(expires_at)
    where expires_at is not null;

alter table public.mcp_oauth_records enable row level security;
