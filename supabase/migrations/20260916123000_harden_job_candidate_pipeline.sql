begin;

create index if not exists job_candidates_published_job_idx
  on public.job_candidates (published_job_key)
  where published_job_key is not null;

-- Rediscovery refreshes evidence but must not move a terminal candidate back to
-- the qualification queue. Publication/closure transitions are explicit acts.
create or replace function private.preserve_candidate_terminal_state()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.processing_status in ('published', 'closed') then
    new.processing_status := old.processing_status;
    new.published_job_key := old.published_job_key;
  end if;
  new.first_discovered_at := old.first_discovered_at;
  return new;
end;
$$;

revoke all on function private.preserve_candidate_terminal_state() from public, anon, authenticated;

drop trigger if exists preserve_candidate_terminal_state on public.job_candidates;
create trigger preserve_candidate_terminal_state
before update on public.job_candidates
for each row execute function private.preserve_candidate_terminal_state();

commit;
