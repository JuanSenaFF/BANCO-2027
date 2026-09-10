"""Publish the public catalog to Supabase as an exact mirror of jobs.json."""
import json,os
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]


def requirement_rows(jobs):
    rows=[]
    for job in jobs:
        records=job.get('requirementsStructured') or [
            *({'text':text,'position':position,'mandatory':True,'requirementType':'mandatory','category':'other','relation':'single','profileSkillIds':[],'unmappedSkillCount':0,'transferable':False} for position,text in enumerate(job.get('requirements',[]))),
            *({'text':text,'position':position,'mandatory':False,'requirementType':'differential','category':'other','relation':'single','profileSkillIds':[],'unmappedSkillCount':0,'transferable':False} for position,text in enumerate(job.get('differentials',[]))),
        ]
        for record in records:
            rows.append({
                'job_key':job['key'],
                'position':record.get('position',0),
                'mandatory':bool(record.get('mandatory')),
                'requirement':record.get('text',''),
                'requirement_type':record.get('requirementType','mandatory' if record.get('mandatory') else 'differential'),
                'category':record.get('category','other'),
                'skill':record.get('skill'),
                'subskill':record.get('subskill'),
                'required_level':record.get('level'),
                'min_years':record.get('minYears'),
                'transferable':bool(record.get('transferable')),
                'relation':record.get('relation','single'),
                'profile_skill_ids':record.get('profileSkillIds') or [],
                'attributes':record,
            })
    return rows


def main():
    url=os.getenv('SUPABASE_URL');key=os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print('Supabase não configurado: catálogo público continua no GitHub Pages.');return

    data=json.loads((ROOT/'jobs.json').read_text())
    history=json.loads((ROOT/'market-history.json').read_text())
    jobs=data['jobs']
    current_keys={j['key'] for j in jobs}
    current_companies={j['company'] for j in jobs}

    session=requests.Session()
    session.headers.update({
        'apikey':key,
        'Authorization':'Bearer '+key,
        'Content-Type':'application/json',
        'Prefer':'resolution=merge-duplicates',
    })

    def endpoint(table):
        return url+'/rest/v1/'+table

    def upsert(table,rows):
        for start in range(0,len(rows),200):
            r=session.post(endpoint(table),json=rows[start:start+200],timeout=30)
            if not r.ok:
                raise RuntimeError(f'Supabase {table}: HTTP {r.status_code}: {r.text[:300]}')

    def select_values(table,column):
        r=session.get(endpoint(table),params={'select':column,'limit':'5000'},timeout=30)
        if not r.ok:
            raise RuntimeError(f'Supabase {table} read: HTTP {r.status_code}')
        return {row[column] for row in r.json() if row.get(column) is not None}

    def delete_eq(table,column,value):
        r=session.delete(endpoint(table),params={column:'eq.'+str(value)},timeout=30)
        if not r.ok:
            raise RuntimeError(f'Supabase {table} delete: HTTP {r.status_code}: {r.text[:300]}')

    # Parent rows first so all current jobs can be upserted.
    upsert('companies',[{'name':c} for c in sorted(current_companies)])

    # Remove jobs that no longer exist in jobs.json. Children are removed explicitly because
    # the current database foreign keys use NO ACTION rather than ON DELETE CASCADE.
    remote_keys=select_values('jobs','key')
    stale_keys=remote_keys-current_keys
    for job_key in sorted(stale_keys):
        delete_eq('job_requirements','job_key',job_key)
        delete_eq('job_sources','job_key',job_key)
        delete_eq('jobs','key',job_key)

    upsert('jobs',[{'key':j['key'],'company':j['company'],'payload':j} for j in jobs])

    # Replace structured children atomically per job so removed requirements/sources do not linger.
    for job_key in sorted(current_keys):
        delete_eq('job_requirements','job_key',job_key)
        delete_eq('job_sources','job_key',job_key)

    upsert('job_requirements',requirement_rows(jobs))
    upsert('job_sources',[
        {'job_key':j['key'],'url':source['url'],'last_verified_at':j.get('lastVerifiedAt')}
        for j in jobs
        for source in (
            j.get('sources')
            or ([{'url':j['source']}] if j.get('source') else [])
        )
        if source.get('url')
    ])

    # companies is also a catalog table, so remove names left with no current job.
    stale_companies=select_values('companies','name')-current_companies
    for company in sorted(stale_companies):
        delete_eq('companies','name',company)

    # Market snapshots are historical and intentionally append-only/upserted by week.
    upsert('market_snapshots',[{'week':s['week'],'payload':s} for s in history])
    upsert('collection_meta',[{'id':'current','payload':data['meta']}])

    # Fail the workflow if Supabase diverges from the catalog after synchronization.
    final_keys=select_values('jobs','key')
    if final_keys!=current_keys:
        missing=sorted(current_keys-final_keys)[:10]
        extra=sorted(final_keys-current_keys)[:10]
        raise RuntimeError(f'Divergência após sync: missing={missing}, extra={extra}')

    print(f'Catálogo sincronizado com Supabase: {len(current_keys)} vagas; {len(stale_keys)} obsoletas removidas.')


if __name__=='__main__':
    main()
