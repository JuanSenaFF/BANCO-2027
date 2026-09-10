alter table public.job_requirements
  add column if not exists requirement_type text,
  add column if not exists category text,
  add column if not exists skill text,
  add column if not exists subskill text,
  add column if not exists required_level smallint,
  add column if not exists min_years numeric(4,1),
  add column if not exists transferable boolean,
  add column if not exists relation text,
  add column if not exists profile_skill_ids text[],
  add column if not exists attributes jsonb;

update public.job_requirements
set requirement_type=case when mandatory then 'mandatory' else 'differential' end,
    category=coalesce(category,'other'),
    transferable=coalesce(transferable,false),
    relation=coalesce(relation,'single'),
    profile_skill_ids=coalesce(profile_skill_ids,'{}'),
    attributes=coalesce(attributes,'{}');

alter table public.job_requirements
  alter column requirement_type set not null,
  alter column requirement_type set default 'mandatory',
  alter column category set not null,
  alter column category set default 'other',
  alter column transferable set not null,
  alter column transferable set default false,
  alter column relation set not null,
  alter column relation set default 'single',
  alter column profile_skill_ids set not null,
  alter column profile_skill_ids set default '{}',
  alter column attributes set not null,
  alter column attributes set default '{}';

do $$ begin
  if not exists (select 1 from pg_constraint where conname='job_requirements_type_check') then
    alter table public.job_requirements add constraint job_requirements_type_check
      check(requirement_type in ('mandatory','differential','eliminatory'));
  end if;
  if not exists (select 1 from pg_constraint where conname='job_requirements_category_check') then
    alter table public.job_requirements add constraint job_requirements_category_check
      check(category in ('technical','experience','education','language','location','modality','eligibility','behavioral','domain','other'));
  end if;
  if not exists (select 1 from pg_constraint where conname='job_requirements_level_check') then
    alter table public.job_requirements add constraint job_requirements_level_check
      check(required_level between 1 and 4);
  end if;
  if not exists (select 1 from pg_constraint where conname='job_requirements_years_check') then
    alter table public.job_requirements add constraint job_requirements_years_check check(min_years >= 0);
  end if;
  if not exists (select 1 from pg_constraint where conname='job_requirements_relation_check') then
    alter table public.job_requirements add constraint job_requirements_relation_check
      check(relation in ('single','any','all'));
  end if;
end $$;
