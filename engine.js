(function(root){
  'use strict';
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const level=t=>/especialista|expert|arquitetura avancada/.test(norm(t))?4:/avancad|solido|dominio/.test(norm(t))?3:/basic|fundamento|nocao|nocoes/.test(norm(t))?1:2;
  const factor=[0,.70,.9,1,1];
  function canonical(url){try{const u=new URL(url);const id=u.pathname.match(/(?:jobs?\/view\/.*?|jobs?\/)(\d{7,})(?:\/|$)/);return u.hostname.endsWith('linkedin.com')&&id?'linkedin:'+id[1]:u.hostname.replace(/^www\./,'')+u.pathname.replace(/\/$/,'');}catch{return '';}}
  function normalize(j){
    const title=norm(j.role), req=(j.requirements||[]).join(' ');
    const conflict=/\b(pleno|senior|staff|lead|especialista)\b/.test(title)||/experiencia\s+(?:como|de|em nivel)\s+(?:profissional\s+)?(?:pleno|senior)|(?:exigimos|requer|nivel de experiencia)\s*[:\-]?\s*(?:pleno|senior)/.test(norm(req));
    const last=j.lastVerifiedAt||null;
    const stale=!last||Date.now()-new Date(last).getTime()>7*864e5;
    let status=j.status==='Encerrada'?'Encerrada':j.status==='Ativa'&&!stale?'Ativa':'Possivelmente encerrada';
    const sufficient=(j.requirements||[]).length>=3;
    const quality=j.qualityScore??Math.min(85,(sufficient?30:5)+(j.company?10:0)+(j.role?10:0)+(canonical(j.source)?10:0)+(last?15:0)+(j.location?5:0)+(j.modality?5:0));
    return {...j,key:j.key||canonical(j.source)||'legacy:'+j.id,legacyStatus:j.status,status,firstSeenAt:j.firstSeenAt||j.collectedAt||null,lastVerifiedAt:last,location:j.location||'Não informada',modality:j.modality||'Não informada',sourceName:j.sourceName||(()=>{try{return new URL(j.source).hostname;}catch{return 'Não informada';}})(),qualityScore:quality,eligible:sufficient&&!conflict&&!j.excluded,qualityIssues:[...(j.qualityIssues||[]),...(!sufficient?['Requisitos insuficientes']:[]),...(conflict?['Senioridade contraditória']:[]),...(stale?['Validade precisa ser confirmada']:[])]};
  }
  function evaluate(j,profile,skills,prefs={},answers={}){
    const technical=(text)=>{
      const mentioned=skills.filter(s=>s.re.test(norm(text))).filter(s=>!(s.id==='cloud'&&skills.some(x=>['aws','azure','gcp'].includes(x.id)&&x.re.test(norm(text)))));
      const need=level(text);
      if(!mentioned.length)return {ratio:0,unknown:true,skills:[]};
      const xs=mentioned.map(s=>{const p=profile[s.id]||{l:0,e:0};return {id:s.id,label:s.label,req:need,current:p.l||0,evidence:p.e||0,ratio:Math.min((p.l||0)/need,1)*(factor[p.e]||0)};});
      const alternative=/\bou\b|\bor\b|aws\s*\/\s*azure|azure\s*\/\s*gcp/.test(norm(text));
      return {ratio:alternative?Math.max(...xs.map(x=>x.ratio)):Math.min(...xs.map(x=>x.ratio)),unknown:false,skills:xs,alternative};
    };
    const one=(text,index,mandatory)=>{
      let r=technical(text), n=norm(text), confirm=answers[j.key]?.[(mandatory?'r':'d')+index];
      if(/anos?\s+(?:de\s+)?experiencia/.test(n)){const years=n.match(/(\d+)\s*anos?/);r={...r,unknown:prefs.years==null||!years,ratio:years&&prefs.years!=null?Math.min(prefs.years/+years[1],1):0};}
      else if(/superior|graduacao|formacao academica/.test(n)){r={...r,unknown:!prefs.education,ratio:prefs.education==='completed'?1:prefs.education==='studying'&&/cursando|em andamento/.test(n)?1:0};}
      else if(/ingles|english/.test(n)){const need=/fluente|fluent|avancad/.test(n)?3:/intermedi/.test(n)?2:1;r={...r,unknown:prefs.english==null,ratio:prefs.english==null?0:Math.min(prefs.english/need,1)};}
      if(confirm==='yes')r={...r,ratio:1,unknown:false,confirmed:true};
      if(confirm==='partial')r={...r,ratio:.5,unknown:false,confirmed:true};
      if(confirm==='no')r={...r,ratio:0,unknown:false,confirmed:true};
      return {...r,text,index,mandatory,state:r.unknown?'unknown':r.ratio>=.85?'ok':r.ratio>0?'partial':'gap'};
    };
    const rows=(j.requirements||[]).map((t,i)=>one(t,i,true)), diffs=(j.differentials||[]).map((t,i)=>one(t,i,false));
    const gates=[];
    if(/\bpcd\b|pessoas com deficiencia/.test(norm(j.role)))gates.push({text:'Elegibilidade para vaga afirmativa: confirmar no anúncio',state:answers[j.key]?.eligibility==='yes'?'ok':answers[j.key]?.eligibility==='no'?'gap':'unknown'});
    if(prefs.location&&j.modality!=='Remoto')gates.push({text:'Localização',state:j.location==='Não informada'?'unknown':norm(j.location).includes(norm(prefs.location))?'ok':'gap'});
    if(prefs.modality)gates.push({text:'Modalidade desejada',state:j.modality==='Não informada'?'unknown':j.modality===prefs.modality?'ok':'gap'});
    if(prefs.area)gates.push({text:'Área desejada',state:j.area===prefs.area?'ok':'gap'});
    if(prefs.role)gates.push({text:'Função desejada',state:norm(j.role).includes(norm(prefs.role))?'ok':'gap'});
    const weighted=rows.reduce((n,r)=>n+r.ratio,0)+diffs.reduce((n,r)=>n+r.ratio*.25,0);
    const score=rows.length?Math.round(100*weighted/(rows.length+diffs.length*.25)):0;
    const unknown=rows.filter(r=>r.unknown).length+gates.filter(g=>g.state==='unknown').length;
    const critical=rows.filter(r=>r.state==='gap').length+gates.filter(g=>g.state==='gap').length;
    const gaps=rows.filter(r=>r.state==='gap'||r.state==='partial');
    const skillGaps=[...new Map(gaps.flatMap(r=>r.alternative?[r.skills.slice().sort((a,b)=>b.ratio-a.ratio)[0]].filter(Boolean):r.skills).filter(s=>s.ratio<.85).map(s=>[s.id,s])).values()];
    const hours=skillGaps.reduce((n,s)=>n+Math.max(1,s.req-s.current)*12+(s.evidence<2?8:0),0);
    const potentialRows=rows.map(r=>!r.confirmed&&!r.unknown&&r.skills.length&&r.skills.every(s=>s.req-s.current<=1)?1:r.ratio);
    const potential=rows.length?Math.max(score,Math.round(100*(potentialRows.reduce((a,b)=>a+b,0)+diffs.reduce((n,r)=>n+r.ratio*.25,0))/(rows.length+diffs.length*.25))):0;
    const canApply=j.eligible&&j.status==='Ativa'&&score>=80&&!unknown&&!critical;
    const label=!j.eligible||gates.some(g=>g.state==='gap')?'Inviável no recorte':canApply?'Aplicar agora':unknown?'Confirmar requisitos':score>=65?'Boa com poucos gaps':score>=40?'Possível':'Gaps relevantes';
    return {score,potential,rows,diffs,gates,unknown,critical,gaps,skillGaps,hours,canApply,label,ok:rows.filter(r=>r.state==='ok').length,partial:rows.filter(r=>r.state==='partial').length};
  }
  function priorities(jobs,profile,skills,prefs,answers){
    const active=jobs.filter(j=>j.status==='Ativa'&&j.eligible),base=active.map(j=>({j,a:evaluate(j,profile,skills,prefs,answers)}));
    return skills.map(s=>{const affected=base.filter(x=>x.a.skillGaps.some(g=>g.id===s.id));const p=profile[s.id]||{l:0,e:0};if(p.l>=4||!affected.length)return null;
      const simulated={...profile,[s.id]:{...p,l:Math.min(4,p.l+1),e:Math.max(2,p.e)}};
      const after=base.map(x=>({before:x.a,after:evaluate(x.j,simulated,skills,prefs,answers)}));
      const unlocked=after.filter(x=>!x.before.canApply&&x.after.canApply).length, gain=after.reduce((n,x)=>n+x.after.score-x.before.score,0),hours=12+(p.e<2?8:0);
      return {skill:s,frequency:affected.length,close:affected.filter(x=>x.a.score>=65).length,unlocked,gain,hours,target:Math.min(4,p.l+1),priority:Math.round((affected.length+affected.filter(x=>x.a.score>=65).length*2+unlocked*5+gain/10)/hours*100)};
    }).filter(Boolean).sort((a,b)=>b.priority-a.priority);
  }
  const api={norm,level,canonical,normalize,evaluate,priorities};root.BancoEngine=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
