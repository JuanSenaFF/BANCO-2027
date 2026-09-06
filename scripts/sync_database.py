"""Publish public catalog to Supabase; no private profile is ever committed to Git."""
import json,os
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
def main():
    url=os.getenv('SUPABASE_URL');key=os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print('Supabase não configurado: catálogo público continua no GitHub Pages.');return
    data=json.loads((ROOT/'jobs.json').read_text());history=json.loads((ROOT/'market-history.json').read_text())
    session=requests.Session();session.headers.update({'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates'})
    def upsert(table,rows):
        for start in range(0,len(rows),200):
            r=session.post(url+'/rest/v1/'+table,json=rows[start:start+200],timeout=30)
            if not r.ok:raise RuntimeError(f'Supabase {table}: HTTP {r.status_code}')
    jobs=data['jobs'];upsert('companies',[{'name':c} for c in sorted({j['company'] for j in jobs})])
    upsert('jobs',[{'key':j['key'],'company':j['company'],'payload':j} for j in jobs])
    # Remove obsolete structured rows per job before replacing them. UI reads atomic job payloads.
    for j in jobs:
        r=session.delete(url+'/rest/v1/job_requirements',params={'job_key':'eq.'+j['key']},timeout=30)
        if not r.ok:raise RuntimeError('Could not refresh requirements')
    upsert('job_requirements',[{'job_key':j['key'],'position':i,'mandatory':mandatory,'requirement':text} for j in jobs for mandatory,field in [(True,'requirements'),(False,'differentials')] for i,text in enumerate(j.get(field,[]))])
    upsert('job_sources',[{'job_key':j['key'],'url':j['source'],'last_verified_at':j.get('lastVerifiedAt')} for j in jobs if j.get('source')])
    upsert('market_snapshots',[{'week':s['week'],'payload':s} for s in history])
    upsert('collection_meta',[{'id':'current','payload':data['meta']}]);print('Catálogo sincronizado com Supabase.')
if __name__=='__main__':main()
