-- Atomic Google OAuth callback state consumption. Apply after 0001_mvp3_foundation.sql.

create or replace function public.consume_google_oauth_state(p_state_hash text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    update public.oauth_states as s
       set consumed_at = now()
     where s.state_hash = p_state_hash
       and s.provider = 'google_calendar'
       and s.consumed_at is null
       and s.expires_at > now()
    returning to_jsonb(s) into v_result;
    return v_result;
end;
$$;

revoke execute on function public.consume_google_oauth_state(text) from public, anon, authenticated;
grant execute on function public.consume_google_oauth_state(text) to service_role;
