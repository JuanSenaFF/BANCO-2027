begin;

-- Existing catalog tables: readable through the Data API, never mutable by
-- browser roles. REVOKE ALL also removes TRUNCATE, REFERENCES, TRIGGER and
-- MAINTAIN, which are not constrained by the row policies used by the app.
revoke all privileges on table
  public.companies,
  public.jobs,
  public.job_requirements,
  public.job_sources,
  public.collection_meta,
  public.market_snapshots
from anon, authenticated;

grant select on table
  public.companies,
  public.jobs,
  public.job_requirements,
  public.job_sources,
  public.collection_meta,
  public.market_snapshots
to anon, authenticated;

alter policy public_read on public.companies to anon, authenticated using (true);
alter policy public_read on public.jobs to anon, authenticated using (true);
alter policy public_read on public.job_requirements to anon, authenticated using (true);
alter policy public_read on public.job_sources to anon, authenticated using (true);
alter policy public_read on public.collection_meta to anon, authenticated using (true);
alter policy public_read on public.market_snapshots to anon, authenticated using (true);

-- Personal tables: signed-in users keep CRUD, with owner_only RLS deciding
-- which rows are visible or mutable. Anonymous clients receive no privileges.
revoke all privileges on table
  public.user_state,
  public.skills,
  public.skill_history,
  public.applications,
  public.alerts,
  public.profile_snapshots
from anon, authenticated;

grant select, insert, update, delete on table
  public.user_state,
  public.skills,
  public.skill_history,
  public.applications,
  public.alerts,
  public.profile_snapshots
to authenticated;

-- The rate-limit table is only reached by the controlled claim_refresh RPC.
revoke all privileges on table public.refresh_requests from anon, authenticated;

-- Opt out of automatic Data API exposure for objects created in the future.
-- New migrations must grant their exact contract explicitly.
alter default privileges for role postgres in schema public
  revoke all privileges on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all privileges on sequences from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated;

-- Functions remain callable only by the role required by the application.
revoke all on function public.claim_refresh() from public, anon, authenticated;
grant execute on function public.claim_refresh() to authenticated;
revoke all on function public.save_career_state(jsonb) from public, anon, authenticated;
grant execute on function public.save_career_state(jsonb) to authenticated;

commit;
