begin;

-- Keep the public RPC contract, but move elevated privileges outside the
-- exposed API schema. The private function is callable only by signed-in
-- users and validates auth.uid() before touching the rate-limit table.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;

alter default privileges for role postgres in schema private
  revoke execute on functions from public, anon, authenticated;

create or replace function private.claim_refresh()
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  requester uuid := (select auth.uid());
  affected integer;
begin
  if requester is null then
    return false;
  end if;

  insert into public.refresh_requests as requests (user_id, requested_at)
  values (requester, now())
  on conflict (user_id) do update
    set requested_at = excluded.requested_at
    where requests.requested_at < now() - interval '5 minutes';

  get diagnostics affected = row_count;
  return affected = 1;
end;
$$;

revoke all on function private.claim_refresh() from public, anon, authenticated;
grant execute on function private.claim_refresh() to authenticated;

create or replace function public.claim_refresh()
returns boolean
language sql
security invoker
set search_path = ''
as $$
  select private.claim_refresh();
$$;

revoke all on function public.claim_refresh() from public, anon, authenticated;
grant execute on function public.claim_refresh() to authenticated;

commit;
