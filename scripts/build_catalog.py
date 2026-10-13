"""Build stable catalog, preserve archived records and weekly market snapshots."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from validate_auto import parse_jobs, canonical_url, req_similarity, valid
from quality import (
    deduplicate_requirement_containers,
    requirements_quality_conflict,
    senior_conflict,
    verify,
)
from rules import (
    ACTIVE_VERIFICATION_DAYS,
    DUPLICATE_SIMILARITY,
    age_days,
    validation_state,
)
from official_sources import (
    merge_source_records,
    same_posting,
    source_metadata,
    source_priority,
)
from requirements_normalizer import (
    SCHEMA_VERSION as REQUIREMENTS_SCHEMA_VERSION,
    normalize_job_requirements,
    normalization_summary,
)
from market_model import annotate as annotate_market
from source_resolution import resolve_catalog, restore_source
from collection_audit import canonical_url as candidate_url
ROOT=Path(__file__).resolve().parents[1]


def job_key(job):
    return canonical_url(job.get('source','')) or 'legacy:'+str(job['id'])


def reconcile_prior_records(prior, current_records):
    """Retire only explicitly invalid automatic records, never mere absences.

    A source outage or an empty feed must not erase useful history. Automatic
    records absent from the current collection are therefore kept unless they
    were previously included and fail the current validator. Records already
    excluded remain as historical lineage and cannot re-enter action queues.
    """
    current_keys={job_key(job) for job in current_records}
    retained={}
    retired=[]
    for key,job in prior.items():
        should_revalidate=(
            bool(job.get('auto'))
            and not job.get('excluded')
            and key not in current_keys
        )
        if should_revalidate:
            ok,reason=valid(job)
            if not ok:
                retired.append({
                    'key':key,
                    'company':job.get('company'),
                    'role':job.get('role'),
                    'reason':reason,
                })
                continue
        retained[key]=job
    return retained,retired


def excluded_by_quality(j):
    reqs=j.get('requirements',[])
    return (
        bool(j.get('duplicateOf'))
        or len(reqs)<3
        or senior_conflict(j.get('role',''),' '.join(reqs))
        or requirements_quality_conflict(j.get('role',''),reqs)
    )


def confidence_score(j):
    """Score the reliability of an extracted record, independent of candidate fit."""
    source = str(j.get('sourceProvider') or j.get('sourceName') or '').lower()
    score = 0
    score += 25 if j.get('lastVerifiedAt') and age_days(j.get('lastVerifiedAt')) <= ACTIVE_VERIFICATION_DAYS else 0
    score += 20 if source in {'gupy', 'lever', 'greenhouse', 'ashby'} else 12 if source == 'linkedin' else 5
    score += 15 if len(j.get('requirements', [])) >= 3 else 0
    score += 10 if j.get('company') else 0
    score += 10 if j.get('role') else 0
    score += 8 if j.get('source') else 0
    score += 5 if j.get('location') else 0
    score += 5 if j.get('modality') else 0
    score += 2 if j.get('differentials') else 0
    if j.get('reviewRequired'):
        score -= 15
    score = max(0, min(100, score))
    label = 'Alta' if score >= 80 else 'Média' if score >= 60 else 'Baixa'
    return score, label


def apply_verification(job, result):
    """Do not close a previously active job on an inconclusive fetch failure."""
    if result.get('validationState') == 'pending' or result.get('status') == 'Possivelmente encerrada':
        pending = {
            **result,
            'status': 'Ativa' if job.get('status') == 'Ativa' else result.get('status', 'Possivelmente encerrada'),
            'validationState': 'pending',
            # The latest attempt supersedes old confirmation evidence. Keep the
            # historical timestamp separately, but never expose it as current.
            'lastVerifiedAt': None,
            'verificationReason': result.get('verificationReason') or 'Validação inconclusiva; status anterior preservado',
        }
        if job.get('lastVerifiedAt'):
            pending['previouslyVerifiedAt'] = job['lastVerifiedAt']
        return pending
    return result


def annotate_source(job):
    meta=source_metadata(job.get('source',''),structured=bool(job.get('sourceStructured')))
    # Reclassify known hosts on every build so catalog migrations do not keep
    # an older "unknown" classification stored in jobs.json.
    if meta['provider']!='unknown':
        job['sourceName']=meta['name']
        job['sourceProvider']=meta['provider']
        job['sourceOfficial']=meta['official']
        job['sourcePriority']=meta['priority']
    else:
        job['sourceName']=job.get('sourceName') or meta['name']
        job['sourceProvider']=job.get('sourceProvider') or meta['provider']
        job['sourceOfficial']=job.get('sourceOfficial',meta['official'])
        job['sourcePriority']=job.get('sourcePriority',meta['priority'])
    job['sources']=merge_source_records(job)
    return job


def apply_source_preference(jobs):
    """Prefer official representations and retain every discovery URL as lineage."""
    ordered=sorted(
        jobs,
        key=lambda j:(source_priority(j),j.get('sourceResolution',{}).get('state')=='resolved',bool(j.get('lastVerifiedAt')),str(j.get('firstSeenAt') or '')),
        reverse=True,
    )
    winners=[]
    for job in ordered:
        duplicate=next((
            winner for winner in winners
            if same_posting(job,winner,req_similarity)
            and (
                req_similarity(job.get('requirements',[]),winner.get('requirements',[]))>=DUPLICATE_SIMILARITY
                or source_priority(job)!=source_priority(winner)
            )
        ),None)
        if duplicate:
            job['duplicateOf']=duplicate['key']
            duplicate['sources']=merge_source_records(duplicate,job)
            aliases=set(duplicate.get('sourceAliases') or [])
            aliases.add(job['key'])
            duplicate['sourceAliases']=sorted(aliases)
        else:
            job['duplicateOf']=None
            winners.append(job)
    return jobs


def run(online=False):
    path=ROOT/'jobs.json';old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'jobs':[],'meta':{}}
    salary_path=ROOT/'salary-estimates.json'
    salary_estimates=json.loads(salary_path.read_text(encoding='utf-8')) if salary_path.exists() else {}
    prior_all={j['key']:j for j in old['jobs']};now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records=[]
    for name in [*(f'data-{i}.js' for i in range(1,8)),'data-auto.js']:records+=parse_jobs(ROOT/name)
    prior,retired=reconcile_prior_records(prior_all,records)
    out={**prior}
    resolved_keys={canonical_url(j['source']):j['key'] for j in prior.values()
                   if j.get('sourceResolution',{}).get('state')=='resolved'}
    for j in records:
        key=resolved_keys.get(job_key(j),job_key(j))
        previous=prior_all.get(key,{})
        # Conteúdo atual da fonte substitui a extração antiga; a evidência de verificação é preservada.
        merged={**previous,**j,'key':key}
        if previous.get('id') is not None:merged['id']=previous['id']
        merged=restore_source(previous,merged)
        advertised=merged.get('salary') if merged.get('salary',{}).get('kind')=='advertised' else None
        curated=salary_estimates.get(key)
        if advertised or curated:merged['salary']=advertised or curated
        else:merged.pop('salary',None)
        merged['firstSeenAt']=previous.get('firstSeenAt') or j.get('collectedAt')
        for field in ('lastVerifiedAt','lastCheckedAt','verificationReason'):
            if previous.get(field) is not None:
                merged[field]=previous[field]
        if previous.get('lastCheckedAt') and previous.get('status'):
            merged['status']=previous['status']
        merged.setdefault('lastVerifiedAt',None)
        merged.setdefault('status','Possivelmente encerrada')
        if not merged['lastVerifiedAt'] and merged['status']!='Encerrada':merged['status']='Possivelmente encerrada'
        merged=annotate_source(merged)
        merged['excluded']=excluded_by_quality(merged)
        merged['validationState']=validation_state(merged)
        out[key]=merged
    for key,job in list(out.items()):
        out[key]=annotate_source(job)
    resolution_counts=None
    if online:
        import requests
        with requests.Session() as session:
            session.headers['User-Agent']='Banco2027/2.0 (public job source resolution)'
            resolution_counts=resolve_catalog(list(out.values()),session)
    apply_source_preference(list(out.values()))
    for job in out.values():
        job['excluded']=excluded_by_quality(job)
    if online:
        import requests
        def check(j):
            if ((j.get('sourceProvider') in {'greenhouse','ashby','lever'}
                    or 'santander.wd3.myworkdayjobs.com' in j.get('source','')
                    or 'google.com/about/careers/applications/jobs/results/' in j.get('source',''))
                    and j.get('sourceResolution',{}).get('state')=='resolved'
                    and j.get('validationState')=='confirmed'):
                return j['key'],{'status':'Ativa','validationState':'confirmed',
                                  'lastCheckedAt':j.get('lastCheckedAt'),
                                  'lastVerifiedAt':j.get('lastVerifiedAt'),
                                  'verificationReason':j.get('verificationReason')}
            with requests.Session() as session:
                session.headers['User-Agent']='Banco2027/2.0 (public job status verification)'
                return j['key'],verify(j,session)
        with ThreadPoolExecutor(max_workers=6) as pool:
            candidates=[j for j in out.values() if j['status']!='Encerrada' and not j['excluded']]
            verification_results=list(pool.map(check,candidates))
            for key,result in verification_results:out[key].update(apply_verification(out[key], result))
        current_verified_keys={key for key,result in verification_results if result.get('validationState')=='confirmed'}
    for j in out.values():
        annotate_source(j)
        j['requirements']=deduplicate_requirement_containers(j.get('requirements',[]))
        j['differentials']=deduplicate_requirement_containers(j.get('differentials',[]))
        j['excluded']=excluded_by_quality(j)
        j['validationState']=validation_state(j)
        j['qualityScore'],j['confidenceLabel']=confidence_score(j)
        if requirements_quality_conflict(j.get('role',''),j.get('requirements',[])):
            j['qualityScore']=min(j['qualityScore'],35)
        j['requirementsStructured']=normalize_job_requirements(j)
        j['requirementsSchemaVersion']=REQUIREMENTS_SCHEMA_VERSION
        annotate_market(j)
    actual_added=len(set(out)-set(prior_all)) if online else old.get('meta',{}).get('added',0)
    meta={**old.get('meta',{}),'catalogBuiltAt':now,'total':len(out),'added':actual_added}
    if resolution_counts is not None:meta['sourceResolution']=resolution_counts
    if online:meta.update(lastCheckAttemptAt=now,verificationAttempted=len(verification_results),verificationConfirmed=len(current_verified_keys))
    report_path=ROOT/'collection-report.json'
    if report_path.exists():
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if retired:
            retirement_reasons=dict(Counter(item['reason'] for item in retired))
            report.update(
                catalogRetiredAt=now,
                catalogRetired=len(retired),
                catalogRetirementReasons=retirement_reasons,
                catalogRetiredJobs=retired,
            )
            report_path.write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
            meta.update(
                catalogRetiredAt=now,
                catalogRetired=len(retired),
                catalogRetirementReasons=retirement_reasons,
            )
        published_this_run=0
        confirmed_this_run=0
        catalog_by_source={candidate_url(url):job for job in out.values() if not job.get('excluded')
                           for url in [job.get('source'), *(item.get('url') for item in job.get('sources',[]) if isinstance(item,dict))]
                           if url}
        for row in report.get('candidates',[]):
            if row.get('status')!='accepted' or not any(t.get('stage')=='validated' for t in row.get('transitions',[])):
                continue
            job=catalog_by_source.get(row.get('canonical_url'))
            if not job:
                if not any(t.get('stage')=='review_required' for t in row['transitions']):
                    row['transitions'].append({'stage':'review_required','reason':'catalog_not_included'})
                continue
            if job.get('validationState')=='confirmed' and job.get('status')=='Ativa':
                if not any(t.get('stage')=='confirmed_active' for t in row['transitions']):
                    row['transitions'].append({'stage':'confirmed_active','reason':job.get('verificationReason') or 'official_evidence'})
                confirmed_this_run+=1
            if not any(t.get('stage')=='published' for t in row['transitions']):
                row['transitions'].append({'stage':'published','reason':'catalog_included'})
            published_this_run+=1
        report.update(publishedThisRun=published_this_run,confirmedThisRun=confirmed_this_run)
        report_path.write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        # "discovered" é o que o coletor encontrou antes da validação; "added" é o que realmente entrou no catálogo.
        meta.update(updatedAt=report.get('updatedAt'),discovered=report.get('discovered',report.get('candidateUrls')),
                    candidateUrls=report.get('candidateUrls'),collectionAdded=report.get('added',0),
                    collectionFunnel={key:report.get(key) for key in ('discovered','scheduled_for_scan','scanned','not_scanned','outcomes','reasons','validatedThisRun','publishedThisRun','confirmedThisRun')},
                    collectionSourceFunnel=report.get('sourceFunnel',{}))
        meta.update(validated=report.get('validated',meta.get('validated',0)),rejected=report.get('rejected',meta.get('rejected',0)),rejectionReasons=report.get('rejectionReasons',meta.get('rejectionReasons',{})))
    health_path=ROOT/'source-health.json'
    if health_path.exists():
        meta['sourceHealth']=json.loads(health_path.read_text(encoding='utf-8'))
    meta['included']=sum(not j.get('excluded') for j in out.values())
    meta['excluded']=sum(bool(j.get('excluded')) for j in out.values())
    meta['needsReview']=sum(bool(j.get('reviewRequired')) for j in out.values())
    meta['pendingValidation']=sum(j.get('validationState') in {'pending','review'} for j in out.values())
    meta['officialSources']=sum(bool(j.get('sourceOfficial')) and not j.get('excluded') for j in out.values())
    meta['linkedinFallbacks']=sum(j.get('sourceProvider')=='linkedin' and not j.get('excluded') for j in out.values())
    meta['officialCoveragePct']=round(100*meta['officialSources']/max(1,meta['included']),1)
    meta['requirementsNormalization']=normalization_summary(list(out.values()))
    meta['marketModel']={
        'version':1,
        'segments':dict(Counter(j.get('marketSegment','market_context') for j in out.values())),
        'alignments':dict(Counter(j.get('careerAlignment','context') for j in out.values())),
        'geographies':dict(Counter(j.get('geographyScope','unverified') for j in out.values())),
        'referenceInstitutions':sum(j.get('institutionTier')=='reference' for j in out.values()),
    }
    meta['indeed']={
        'individualVacanciesEnabled':False,
        'hiringLabTrendsEnabled':False,
        'reason':'API pública para vagas individuais indisponível; Hiring Lab requer acesso de parceiro/pesquisador',
    }
    data={'meta':meta,'jobs':list(out.values())};path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    history_path=ROOT/'market-history.json';history=json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else []
    week=(datetime.now(timezone.utc)-timedelta(days=datetime.now(timezone.utc).weekday())).date().isoformat()
    if online and current_verified_keys and not any(s['week']==week for s in history):
        active=[j for j in out.values() if j['status']=='Ativa' and not j['excluded']]
        technology_jobs=Counter(t for j in active for t in set(j.get('tags',[])))
        technology_companies={
            tag:len({j.get('company') for j in active if tag in set(j.get('tags',[])) and j.get('company')})
            for tag in technology_jobs
        }
        history.append({
            'week':week,
            'at':now,
            'total':len(active),
            'technologies':dict(technology_jobs),
            'technologyCompanies':technology_companies,
            'companies':dict(Counter(j['company'] for j in active)),
            'areas':dict(Counter(j.get('area','Não informada') for j in active)),
            'segments':dict(Counter(j.get('marketSegment','market_context') for j in active)),
        })
    history_path.write_text(json.dumps(history,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Catálogo: {len(out)} vagas; {sum(not j.get("excluded") for j in out.values())} incluídas; {sum(j["status"]=="Ativa" and not j["excluded"] for j in out.values())} ativas confirmadas.')
    return data
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');run(p.parse_args().verify)
