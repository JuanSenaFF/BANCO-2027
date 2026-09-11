"""Build stable catalog, preserve archived records and weekly market snapshots."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from validate_auto import parse_jobs, canonical_url, req_similarity, valid
from quality import senior_conflict, verify, requirements_quality_conflict
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
    if job.get('status') == 'Ativa' and result.get('status') == 'Possivelmente encerrada':
        return {
            **result,
            'status': 'Ativa',
            'validationState': 'pending',
            'verificationReason': result.get('verificationReason') or 'Validação inconclusiva; status anterior preservado',
        }
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
        key=lambda j:(source_priority(j),bool(j.get('lastVerifiedAt')),str(j.get('firstSeenAt') or '')),
        reverse=True,
    )
    winners=[]
    for job in ordered:
        duplicate=next((
            winner for winner in winners
            if req_similarity(job.get('requirements',[]),winner.get('requirements',[]))>=DUPLICATE_SIMILARITY
            or (
                source_priority(job)!=source_priority(winner)
                and same_posting(job,winner,req_similarity)
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
    path=ROOT/'jobs.json';old=json.loads(path.read_text()) if path.exists() else {'jobs':[],'meta':{}}
    salary_path=ROOT/'salary-estimates.json'
    salary_estimates=json.loads(salary_path.read_text()) if salary_path.exists() else {}
    prior_all={j['key']:j for j in old['jobs']};now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records=[]
    for name in [*(f'data-{i}.js' for i in range(1,7)),'data-auto.js']:records+=parse_jobs(ROOT/name)
    prior,retired=reconcile_prior_records(prior_all,records)
    out={**prior}
    for j in records:
        key=job_key(j)
        previous=prior_all.get(key,{})
        # Conteúdo atual da fonte substitui a extração antiga; a evidência de verificação é preservada.
        merged={**previous,**j,'key':key}
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
    apply_source_preference(list(out.values()))
    for job in out.values():
        job['excluded']=excluded_by_quality(job)
    if online:
        import requests
        def check(j):
            with requests.Session() as session:
                session.headers['User-Agent']='Banco2027/2.0 (public job status verification)'
                return j['key'],verify(j,session)
        with ThreadPoolExecutor(max_workers=6) as pool:
            candidates=[j for j in out.values() if j['status']!='Encerrada' and not j['excluded']]
            for key,result in pool.map(check,candidates):out[key].update(apply_verification(out[key], result))
    for j in out.values():
        annotate_source(j)
        j['excluded']=excluded_by_quality(j)
        j['validationState']=validation_state(j)
        j['qualityScore'],j['confidenceLabel']=confidence_score(j)
        if requirements_quality_conflict(j.get('role',''),j.get('requirements',[])):
            j['qualityScore']=min(j['qualityScore'],35)
        j['requirementsStructured']=normalize_job_requirements(j)
        j['requirementsSchemaVersion']=REQUIREMENTS_SCHEMA_VERSION
    actual_added=len(set(out)-set(prior_all)) if online else old.get('meta',{}).get('added',0)
    meta={**old.get('meta',{}),'catalogBuiltAt':now,'total':len(out),'added':actual_added}
    if online:meta.update(lastCheckAttemptAt=now,verificationAttempted=len([j for j in out.values() if j.get('lastCheckedAt')]),verificationConfirmed=sum(j.get('lastVerifiedAt','')==now for j in out.values()))
    report_path=ROOT/'collection-report.json'
    if report_path.exists():
        report=json.loads(report_path.read_text())
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
        # "discovered" é o que o coletor encontrou antes da validação; "added" é o que realmente entrou no catálogo.
        meta.update(updatedAt=report.get('updatedAt'),discovered=report.get('added',0),candidateUrls=report.get('candidateUrls'))
        meta.update(validated=report.get('validated',meta.get('validated',0)),rejected=report.get('rejected',meta.get('rejected',0)),rejectionReasons=report.get('rejectionReasons',meta.get('rejectionReasons',{})))
    meta['included']=sum(not j.get('excluded') for j in out.values())
    meta['excluded']=sum(bool(j.get('excluded')) for j in out.values())
    meta['needsReview']=sum(bool(j.get('reviewRequired')) for j in out.values())
    meta['pendingValidation']=sum(j.get('validationState') in {'pending','review'} for j in out.values())
    meta['officialSources']=sum(bool(j.get('sourceOfficial')) and not j.get('excluded') for j in out.values())
    meta['linkedinFallbacks']=sum(j.get('sourceProvider')=='linkedin' and not j.get('excluded') for j in out.values())
    meta['officialCoveragePct']=round(100*meta['officialSources']/max(1,meta['included']),1)
    meta['requirementsNormalization']=normalization_summary(list(out.values()))
    data={'meta':meta,'jobs':list(out.values())};path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    history_path=ROOT/'market-history.json';history=json.loads(history_path.read_text()) if history_path.exists() else []
    week=(datetime.now(timezone.utc)-timedelta(days=datetime.now(timezone.utc).weekday())).date().isoformat()
    if online and any(j.get('lastVerifiedAt','')==now for j in out.values()) and not any(s['week']==week for s in history):
        active=[j for j in out.values() if j['status']=='Ativa' and not j['excluded']]
        history.append({'week':week,'at':now,'total':len(active),'technologies':dict(Counter(t for j in active for t in set(j.get('tags',[])))),'companies':dict(Counter(j['company'] for j in active)),'areas':dict(Counter(j.get('area','Não informada') for j in active))})
    history_path.write_text(json.dumps(history,ensure_ascii=False,indent=2)+'\n')
    print(f'Catálogo: {len(out)} vagas; {sum(not j.get("excluded") for j in out.values())} incluídas; {sum(j["status"]=="Ativa" and not j["excluded"] for j in out.values())} ativas confirmadas.')
    return data
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');run(p.parse_args().verify)
