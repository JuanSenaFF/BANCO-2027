"""Build stable catalog, preserve archived records and weekly market snapshots."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from validate_auto import parse_jobs, canonical_url, req_similarity
from quality import senior_conflict, verify, requirements_quality_conflict
ROOT=Path(__file__).resolve().parents[1]


def excluded_by_quality(j):
    reqs=j.get('requirements',[])
    return (
        bool(j.get('duplicateOf'))
        or len(reqs)<3
        or senior_conflict(j.get('role',''),' '.join(reqs))
        or requirements_quality_conflict(j.get('role',''),reqs)
    )


def run(online=False):
    path=ROOT/'jobs.json';old=json.loads(path.read_text()) if path.exists() else {'jobs':[],'meta':{}}
    prior={j['key']:j for j in old['jobs']};now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records=[]
    for name in [*(f'data-{i}.js' for i in range(1,7)),'data-auto.js']:records+=parse_jobs(ROOT/name)
    out={**prior};seen=[]
    for j in records:
        key=canonical_url(j.get('source','')) or 'legacy:'+str(j['id'])
        previous=prior.get(key,{})
        # Conteúdo atual da fonte substitui a extração antiga; a evidência de verificação é preservada.
        merged={**previous,**j,'key':key}
        merged['firstSeenAt']=previous.get('firstSeenAt') or j.get('collectedAt')
        for field in ('lastVerifiedAt','lastCheckedAt','verificationReason'):
            if previous.get(field) is not None:
                merged[field]=previous[field]
        if previous.get('lastCheckedAt') and previous.get('status'):
            merged['status']=previous['status']
        merged.setdefault('lastVerifiedAt',None)
        merged.setdefault('status','Possivelmente encerrada')
        if not merged['lastVerifiedAt'] and merged['status']!='Encerrada':merged['status']='Possivelmente encerrada'
        merge_duplicate=next((x for x in seen if x['key']!=key and req_similarity(j.get('requirements',[]),x.get('requirements',[]))>=.90),None)
        merged['duplicateOf']=merge_duplicate['key'] if merge_duplicate else None
        merged['excluded']=excluded_by_quality(merged)
        out[key]=merged;seen.append(merged)
    if online:
        import requests
        def check(j):
            with requests.Session() as session:
                session.headers['User-Agent']='Banco2027/2.0 (public job status verification)'
                return j['key'],verify(j,session)
        with ThreadPoolExecutor(max_workers=6) as pool:
            candidates=[j for j in out.values() if j['status']!='Encerrada' and not j['excluded']]
            for key,result in pool.map(check,candidates):out[key].update(result)
    for j in out.values():
        j['excluded']=excluded_by_quality(j)
        j['qualityScore']=min(100,(30 if len(j.get('requirements',[]))>=3 else 0)+(15 if j.get('lastVerifiedAt') else 0)+(10 if j.get('company') else 0)+(10 if j.get('role') else 0)+(10 if j.get('source') else 0)+(10 if j.get('location') else 0)+(5 if j.get('modality') else 0)+(10 if j.get('differentials') else 0))
        if requirements_quality_conflict(j.get('role',''),j.get('requirements',[])):
            j['qualityScore']=min(j['qualityScore'],35)
        j['requirementsStructured']=[{'text':t,'mandatory':True} for t in j.get('requirements',[])]+[{'text':t,'mandatory':False} for t in j.get('differentials',[])]
    actual_added=len(set(out)-set(prior)) if online else old.get('meta',{}).get('added',0)
    meta={**old.get('meta',{}),'catalogBuiltAt':now,'total':len(out),'added':actual_added}
    if online:meta.update(lastCheckAttemptAt=now,verificationAttempted=len([j for j in out.values() if j.get('lastCheckedAt')]),verificationConfirmed=sum(j.get('lastVerifiedAt','')==now for j in out.values()))
    report_path=ROOT/'collection-report.json'
    if report_path.exists():
        report=json.loads(report_path.read_text())
        # "discovered" é o que o coletor encontrou antes da validação; "added" é o que realmente entrou no catálogo.
        meta.update(updatedAt=report.get('updatedAt'),discovered=report.get('added',0),candidateUrls=report.get('candidateUrls'))
    meta['included']=sum(not j.get('excluded') for j in out.values())
    meta['excluded']=sum(bool(j.get('excluded')) for j in out.values())
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
