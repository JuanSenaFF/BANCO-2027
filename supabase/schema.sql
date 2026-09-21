-- Execute once in a dedicated Supabase project. Private records use auth.uid().
begin;

-- New objects are private by default. Every Data API grant is declared below.
alter default privileges for role postgres in schema public
  revoke all privileges on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all privileges on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated;

create table public.companies (name text primary key, domain text);
create table public.jobs (key text primary key, company text references public.companies(name), payload jsonb not null, updated_at timestamptz not null default now());
create table public.job_requirements (
  job_key text references public.jobs(key),
  position integer,
  mandatory boolean not null,
  requirement text not null,
  requirement_type text not null default 'mandatory' check(requirement_type in ('mandatory','differential','eliminatory')),
  category text not null default 'other' check(category in ('technical','experience','education','language','location','modality','eligibility','behavioral','domain','other')),
  skill text,
  subskill text,
  required_level smallint check(required_level between 1 and 4),
  min_years numeric(4,1) check(min_years >= 0),
  transferable boolean not null default false,
  relation text not null default 'single' check(relation in ('single','any','all')),
  profile_skill_ids text[] not null default '{}',
  attributes jsonb not null default '{}',
  primary key(job_key,mandatory,position)
);
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
create table public.source_registry (
  id text primary key, provider text not null, display_name text not null, base_url text not null,
  priority smallint not null default 3 check(priority between 1 and 5), enabled boolean not null default false,
  credentials_required boolean not null default false, daily_request_limit integer check(daily_request_limit is null or daily_request_limit > 0),
  lifetime_request_limit integer check(lifetime_request_limit is null or lifetime_request_limit > 0),
  health_status text not null default 'unknown' check(health_status in ('unknown','healthy','degraded','unavailable','quota_exhausted','credentials_missing')),
  last_success_at timestamptz, last_failure_at timestamptz, consecutive_failures integer not null default 0 check(consecutive_failures >= 0),
  last_error text, metadata jsonb not null default '{}', updated_at timestamptz not null default now()
);
create table public.job_candidates (
  candidate_key text primary key, provider text not null, external_id text, source_url text not null, apply_url text,
  title_raw text not null default '', company_raw text not null default '', location_raw text not null default '', description_raw text not null default '',
  published_at timestamptz, source_updated_at timestamptz, first_discovered_at timestamptz not null default now(), last_discovered_at timestamptz not null default now(),
  processing_status text not null default 'discovered' check(processing_status in ('discovered','qualified','review_required','rejected','published','closed')),
  attempt_count integer not null default 0 check(attempt_count >= 0), next_retry_at timestamptz, rejection_reason text,
  payload_hash text not null, dedupe_key text not null, qualification jsonb not null default '{}', raw_payload jsonb not null default '{}',
  published_job_key text references public.jobs(key) on delete set null, unique(provider,external_id)
);
create index job_candidates_processing_idx on public.job_candidates(processing_status,next_retry_at,last_discovered_at desc);
create index job_candidates_dedupe_idx on public.job_candidates(dedupe_key);
create index job_candidates_provider_idx on public.job_candidates(provider,last_discovered_at desc);
create index job_candidates_published_job_idx on public.job_candidates(published_job_key) where published_job_key is not null;
create table public.source_runs (
  id bigint generated by default as identity primary key, source_id text not null references public.source_registry(id),
  started_at timestamptz not null, finished_at timestamptz not null default now(), status text not null check(status in ('success','partial','failed','skipped')),
  request_count integer not null default 0 check(request_count >= 0), discovered_count integer not null default 0 check(discovered_count >= 0),
  persisted_count integer not null default 0 check(persisted_count >= 0), error_count integer not null default 0 check(error_count >= 0),
  error text, metadata jsonb not null default '{}'
);
create index source_runs_source_started_idx on public.source_runs(source_id,started_at desc);

do $$ declare t text; begin
foreach t in array array['companies','jobs','job_requirements','job_sources','collection_meta','market_snapshots'] loop
execute format('alter table public.%I enable row level security',t);
execute format('create policy public_read on public.%I for select to anon, authenticated using (true)',t);
execute format('revoke all privileges on table public.%I from anon, authenticated',t);
execute format('grant select on public.%I to anon, authenticated',t);
end loop;
foreach t in array array['user_state','skills','skill_history','applications','alerts','profile_snapshots'] loop
execute format('alter table public.%I enable row level security',t);
execute format('create policy owner_only on public.%I for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()))',t);
execute format('revoke all privileges on table public.%I from anon, authenticated',t);
execute format('grant select,insert,update,delete on public.%I to authenticated',t);
end loop;
end $$;
alter table public.refresh_requests enable row level security;
revoke all privileges on table public.refresh_requests from anon,authenticated;
do $$ declare t text; begin
foreach t in array array['source_registry','job_candidates','source_runs'] loop
execute format('alter table public.%I enable row level security',t);
execute format('revoke all privileges on table public.%I from anon, authenticated',t);
execute format('grant select,insert,update,delete on public.%I to service_role',t);
end loop;
end $$;
revoke all privileges on sequence public.source_runs_id_seq from anon,authenticated;
grant usage,select on sequence public.source_runs_id_seq to service_role;
insert into public.source_registry
  (id,provider,display_name,base_url,priority,enabled,credentials_required,daily_request_limit,lifetime_request_limit,health_status,metadata)
values
  ('api_br','api_br','API BR Vagas Aggregator','https://apibr.com/vagas/api/v2',3,true,false,null,null,'unknown','{"role":"discovery","confidence":"low"}'),
  ('adzuna_br','adzuna','Adzuna Brasil','https://api.adzuna.com/v1/api/jobs/br',3,false,true,250,null,'credentials_missing','{"role":"discovery","confidence":"medium","requires_terms_review":true}'),
  ('jooble_br','jooble','Jooble Brasil','https://br.jooble.org/api',4,false,true,null,500,'credentials_missing','{"role":"targeted_gap_recovery","confidence":"medium"}');
create schema if not exists private;
revoke all on schema private from public,anon,authenticated;
grant usage on schema private to authenticated;
alter default privileges for role postgres in schema private
  revoke execute on functions from public,anon,authenticated;

create function private.preserve_candidate_terminal_state() returns trigger language plpgsql set search_path='' as $$
begin
if old.processing_status in ('published','closed') then
new.processing_status:=old.processing_status;
new.published_job_key:=old.published_job_key;
end if;
new.first_discovered_at:=old.first_discovered_at;
return new;
end $$;
revoke all on function private.preserve_candidate_terminal_state() from public,anon,authenticated;
create trigger preserve_candidate_terminal_state before update on public.job_candidates for each row execute function private.preserve_candidate_terminal_state();

create function private.claim_refresh() returns boolean language plpgsql security definer set search_path = '' as $$
declare requester uuid := (select auth.uid()); affected integer;
begin
if requester is null then return false; end if;
insert into public.refresh_requests as requests(user_id,requested_at) values(requester,now()) on conflict(user_id) do update set requested_at=excluded.requested_at where requests.requested_at<now()-interval '5 minutes';
get diagnostics affected=row_count;
return affected=1;
end $$;
revoke all on function private.claim_refresh() from public,anon,authenticated;
grant execute on function private.claim_refresh() to authenticated;

create function public.claim_refresh() returns boolean language sql security invoker set search_path = '' as $$
select private.claim_refresh();
$$;
revoke all on function public.claim_refresh() from public,anon,authenticated;
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
revoke all on function public.save_career_state(jsonb) from public,anon,authenticated;
grant execute on function public.save_career_state(jsonb) to authenticated;
commit;
