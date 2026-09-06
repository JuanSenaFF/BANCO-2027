-- Execute once in a dedicated Supabase project. Private records use auth.uid().
begin;
create table public.companies (name text primary key, domain text);
create table public.jobs (key text primary key, company text references public.companies(name), payload jsonb not null, updated_at timestamptz not null default now());
create table public.job_requirements (job_key text references public.jobs(key), position integer, mandatory boolean not null, requirement text not null, primary key(job_key,mandatory,position));
create table public.job_sources (job_key text references public.jobs(key), url text not null, last_verified_at timestamptz, primary key(job_key,url));
create table public.collection_meta (id text primary key, payload jsonb not null);
create table public.market_snapshots (week date primary key, payload jsonb not null);
create table public.user_state (user_id uuid primary key references auth.users(id) on delete cascade, payload jsonb not null, updated_at timestamptz default now());
create table public.skills (user_id uuid references auth.users(id) on delete cascade, skill_id text, level smallint check(level between 0 and 4), evidence smallint check(evidence between 0 and 4), note text, primary key(user_id,skill_id));
create table public.skill_history (user_id uuid references auth.users(id) on delete cascade, position integer, payload jsonb not null, primary key(user_id,position));
create table public.applications (user_id uuid references auth.users(id) on delete cascade, job_key text, payload jsonb not null, primary key(user_id,job_key));
create table public.alerts (user_id uuid references auth.users(id) on delete cascade, key text, payload jsonb not null, primary key(user_id,key));
create table public.profile_snapshots (user_id uuid references auth.users(id) on delete cascade, position integer, payload jsonb not null, primary key(user_id,position));
create table public.refresh_requests (user_id uuid primary key references auth.users(id) on delete cascade, requested_at timestamptz not null);

do $$ declare t text; begin
foreach t in array array['companies','jobs','job_requirements','job_sources','collection_meta','market_snapshots'] loop
execute format('alter table public.%I enable row level security',t);
execute format('create policy public_read on public.%I for select using (true)',t);
execute format('grant select on public.%I to anon, authenticated',t);
execute format('revoke insert, update, delete on public.%I from anon, authenticated',t);
end loop;
foreach t in array array['user_state','skills','skill_history','applications','alerts','profile_snapshots'] loop
execute format('alter table public.%I enable row level security',t);
execute format('create policy owner_only on public.%I for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()))',t);
execute format('grant select,insert,update,delete on public.%I to authenticated',t);
execute format('revoke all on public.%I from anon',t);
end loop;
end $$;
alter table public.refresh_requests enable row level security;
revoke all on public.refresh_requests from anon,authenticated;
create function public.claim_refresh() returns boolean language plpgsql security definer set search_path=public as $$
declare affected integer;
begin
if auth.uid() is null then return false; end if;
insert into refresh_requests(user_id,requested_at) values(auth.uid(),now()) on conflict(user_id) do update set requested_at=excluded.requested_at where refresh_requests.requested_at<now()-interval '5 minutes';
get diagnostics affected=row_count;
return affected=1;
end $$;
revoke all on function public.claim_refresh() from public,anon;
grant execute on function public.claim_refresh() to authenticated;

-- One transaction for the UI snapshot plus normalized career tables.
create function public.save_career_state(p_state jsonb) returns void language plpgsql security invoker set search_path=public as $$
declare u uuid:=auth.uid(); kv record;
begin
if u is null then raise exception 'Authentication required'; end if;
insert into user_state values(u,p_state,now()) on conflict(user_id) do update set payload=excluded.payload,updated_at=excluded.updated_at;
delete from skills where user_id=u;
insert into skills select u,key,(value->>'l')::smallint,(value->>'e')::smallint,value->>'note' from jsonb_each(p_state->'profile');
delete from applications where user_id=u;
insert into applications select u,key,value from jsonb_each(p_state->'applications');
delete from skill_history where user_id=u;
insert into skill_history select u,ordinality::integer,value from jsonb_array_elements(p_state->'skillHistory') with ordinality;
delete from profile_snapshots where user_id=u;
insert into profile_snapshots select u,ordinality::integer,value from jsonb_array_elements(p_state->'history') with ordinality;
delete from alerts where user_id=u;
insert into alerts values(u,'rules',jsonb_build_object('rules',p_state->'alertRules','dismissed',p_state->'dismissed'));
end $$;
revoke all on function public.save_career_state(jsonb) from public,anon;
grant execute on function public.save_career_state(jsonb) to authenticated;
commit;
