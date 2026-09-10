(function(root){
  'use strict';
  const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const level=t=>/especialista|expert|arquitetura avancada/.test(norm(t))?4:/avancad|solido|dominio/.test(norm(t))?3:/basic|fundamento|nocao|nocoes/.test(norm(t))?1:2;
  const factor=[0,.70,.9,1,1];
  function normalizeSalary(s){
    if(!s||!['advertised','estimate'].includes(s.kind))return null;
    const min=Number(s.min),max=Number(s.max),median=Number(s.median);
    if(!Number.isFinite(min)||!Number.isFinite(max)||min<0||max<min)return null;
    return {...s,min,max,median:Number.isFinite(median)&&median>=min&&median<=max?median:null,currency:s.currency||'BRL',period:s.period||'month'};
  }
  function canonical(url){try{const u=new URL(url);const id=u.pathname.match(/(?:jobs?\/view\/.*?|jobs?\/)(\d{7,})(?:\/|$)/);return u.hostname.endsWith('linkedin.com')&&id?'linkedin:'+id[1]:u.hostname.replace(/^www\./,'')+u.pathname.replace(/\/$/,'');}catch{return '';}}
  function requirementRecords(j){
    const structured=Array.isArray(j.requirementsStructured)&&j.requirementsStructured.length&&j.requirementsStructured.every(r=>r&&typeof r==='object'&&r.requirementType);
    if(structured)return j.requirementsStructured;
    return [...(j.requirements||[]).map((text,position)=>({text,position,mandatory:true,requirementType:'mandatory'})),...(j.differentials||[]).map((text,position)=>({text,position,mandatory:false,requirementType:'differential'}))];
  }
  function normalize(j){
    const title=norm(j.role), req=(j.requirements||[]).join(' ');
    const conflict=/\b(pleno|senior|staff|lead|especialista)\b/.test(title)||/experiencia\s+(?:como|de|em nivel)\s+(?:profissional\s+)?(?:pleno|senior)|(?:exigimos|requer|nivel de experiencia)\s*[:\-]?\s*(?:pleno|senior)/.test(norm(req));
    const last=j.lastVerifiedAt||null;
    const stale=!last||Date.now()-new Date(last).getTime()>7*864e5;
    let status=j.status==='Encerrada'?'Encerrada':j.status==='Ativa'&&!stale?'Ativa':'Possivelmente encerrada';
    const sufficient=(j.requirements||[]).length>=3;
    const quality=j.qualityScore??Math.min(85,(sufficient?30:5)+(j.company?10:0)+(j.role?10:0)+(canonical(j.source)?10:0)+(last?15:0)+(j.location?5:0)+(j.modality?5:0));
    const review=Boolean(j.reviewRequired);
    const validationState=review?'review':status==='Encerrada'?'closed':status==='Ativa'&&!stale?'confirmed':'pending';
    return {...j,key:j.key||canonical(j.source)||'legacy:'+j.id,legacyStatus:j.status,status,validationState,firstSeenAt:j.firstSeenAt||j.collectedAt||null,lastVerifiedAt:last,location:j.location||'Não informada',modality:j.modality||'Não informada',salary:normalizeSalary(j.salary),sourceName:j.sourceName||(()=>{try{return new URL(j.source).hostname;}catch{return 'Não informada';}})(),qualityScore:quality,eligible:sufficient&&!conflict&&!j.excluded&&!review,qualityIssues:[...(j.qualityIssues||[]),...(!sufficient?['Requisitos insuficientes']:[]),...(conflict?['Senioridade contraditória']:[]),...(stale?['Validade precisa ser confirmada']:[]),...(review?[j.reviewReason||'Revisão humana necessária']:[])]};
  }
  function evaluate(j,profile,skills,prefs={},answers={}){
    const technical=(requirement)=>{
      const text=requirement.text||String(requirement||'');
      const exact=Array.isArray(requirement.profileSkillIds);
      const mentioned=(exact?requirement.profileSkillIds.map(id=>skills.find(s=>s.id===id)).filter(Boolean):skills.filter(s=>s.re.test(norm(text))).filter(s=>!(s.id==='cloud'&&skills.some(x=>['aws','azure','gcp'].includes(x.id)&&x.re.test(norm(text))))));
      const need=exact?(requirement.level||1):level(text);
      if(!mentioned.length)return {ratio:0,unknown:true,skills:[]};
      const xs=mentioned.map(s=>{const p=profile[s.id]||{l:0,e:0};return {id:s.id,label:s.label,req:need,current:p.l||0,evidence:p.e||0,ratio:Math.min((p.l||0)/need,1)*(factor[p.e]||0)};});
      const alternative=requirement.relation==='any'||(!exact&&/\bou\b|\bor\b|aws\s*\/\s*azure|azure\s*\/\s*gcp/.test(norm(text)));
      const ratio=alternative?Math.max(...xs.map(x=>x.ratio)):Math.min(...xs.map(x=>x.ratio));
      const unmapped=exact&&Number(requirement.unmappedSkillCount||0)>0;
      return {ratio,unknown:unmapped&&(alternative?ratio<.85:true),skills:xs,alternative};
    };
    const one=(requirement,index,mandatory)=>{
      const text=requirement.text||String(requirement||'');
      let r=technical(requirement), n=norm(text), confirm=answers[j.key]?.[(mandatory?'r':'d')+index];
      const requiredYears=requirement.minYears??(Number(n.match(/(\d+(?:[.,]\d+)?)\s*anos?/)?.[1]?.replace(',','.'))||null);
      if(requiredYears!=null){const experience={unknown:prefs.years==null,ratio:prefs.years==null?0:Math.min(prefs.years/requiredYears,1)};r={...r,unknown:r.skills.length?r.unknown||experience.unknown:experience.unknown,ratio:r.skills.length?Math.min(r.ratio,experience.ratio):experience.ratio};}
      else if(/superior|graduacao|formacao academica/.test(n)){r={...r,unknown:!prefs.education,ratio:prefs.education==='completed'?1:prefs.education==='studying'&&/cursando|em andamento/.test(n)?1:0};}
      else if(/ingles|english/.test(n)){const need=/fluente|fluent|avancad/.test(n)?3:/intermedi/.test(n)?2:1;r={...r,unknown:prefs.english==null,ratio:prefs.english==null?0:Math.min(prefs.english/need,1)};}
      if(confirm==='yes')r={...r,ratio:1,unknown:false,confirmed:true};
      if(confirm==='partial')r={...r,ratio:.5,unknown:false,confirmed:true};
      if(confirm==='no')r={...r,ratio:0,unknown:false,confirmed:true};
      return {...requirement,...r,text,index,mandatory,state:r.unknown?'unknown':r.ratio>=.85?'ok':r.ratio>0?'partial':'gap'};
    };
    const records=requirementRecords(j);
    const rows=records.filter(r=>r.requirementType==='mandatory').map((r,i)=>one(r,i,true));
    const diffs=records.filter(r=>r.requirementType==='differential').map((r,i)=>one(r,i,false));
    const gates=records.filter(r=>r.requirementType==='eliminatory').map(r=>{
      if(r.category==='education')return {...r,state:!prefs.education?'unknown':prefs.education==='completed'||(prefs.education==='studying'&&/cursando|em andamento/.test(norm(r.text)))?'ok':'gap'};
      if(r.category==='eligibility')return {...r,state:answers[j.key]?.eligibility==='yes'?'ok':answers[j.key]?.eligibility==='no'?'gap':'unknown'};
      if(r.category==='location')return {...r,state:!prefs.location?'unknown':norm(r.text).includes(norm(prefs.location))?'ok':'gap'};
      return {...r,state:'unknown'};
    });
    if(!gates.some(g=>g.category==='eligibility')&&/\bpcd\b|pessoas com deficiencia/.test(norm(j.role)))gates.push({text:'Elegibilidade para vaga afirmativa: confirmar no anúncio',category:'eligibility',requirementType:'eliminatory',state:answers[j.key]?.eligibility==='yes'?'ok':answers[j.key]?.eligibility==='no'?'gap':'unknown'});
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
  const ACTION_QUEUES={
    apply_now:{id:'apply_now',label:'Aplicar agora',order:1},
    apply_study:{id:'apply_study',label:'Aplicar e estudar',order:2},
    prepare:{id:'prepare',label:'Preparar por 1–2 semanas',order:3},
    monitor:{id:'monitor',label:'Acompanhar',order:4}
  };
  function vacancyConfidence(j){
    const state=j.validationState||'';
    if(state==='closed'||j.status==='Encerrada')return 0;
    const checked=Date.parse(j.lastVerifiedAt||''),recent=Number.isFinite(checked)&&Date.now()-checked<=7*864e5;
    if(state==='confirmed')return j.sourceOfficial?1:.9;
    if(recent)return .8;
    if(j.sourceOfficial)return .55;
    if((j.sourceProvider||'').toLowerCase()==='linkedin')return .3;
    if(!state&&j.status==='Ativa')return .8;
    return .4;
  }
  function knownFit(a){
    const rows=a.rows.filter(r=>!r.unknown),diffs=a.diffs.filter(r=>!r.unknown);
    if(!rows.length)return {score:0,coverage:0,known:0,total:a.rows.length};
    const weighted=rows.reduce((n,r)=>n+r.ratio,0)+diffs.reduce((n,r)=>n+r.ratio*.25,0);
    return {score:Math.round(100*weighted/(rows.length+diffs.length*.25)),coverage:Math.round(100*rows.length/Math.max(1,a.rows.length)),known:rows.length,total:a.rows.length};
  }
  function isSmallGap(r){
    if(!r.skills.length)return false;
    const candidates=r.alternative?[r.skills.slice().sort((a,b)=>b.ratio-a.ratio)[0]]:r.skills;
    return candidates.every(s=>s.req-s.current<=1);
  }
  function actionDecision(j,a){
    if(j.validationState==='closed'||j.status==='Encerrada'||j.excluded)return null;
    const confidence=vacancyConfidence(j),fit=knownFit(a),gapRows=a.rows.filter(r=>r.state==='gap'||r.state==='partial');
    const gateBlocks=a.gates.filter(g=>g.state==='gap'),small=gapRows.filter(isSmallGap),lowConfidence=confidence<.55;
    let queue=ACTION_QUEUES.monitor,reason='Distância alta para o perfil atual';
    if(lowConfidence){reason='Confirmar se o anúncio continua aberto';}
    else if(!j.eligible||gateBlocks.length){reason=gateBlocks.length?'Há regra eliminatória incompatível':'Vaga fora do recorte qualificado';}
    else if(!fit.known){reason='Ainda não há requisitos conhecidos suficientes';}
    else if(!gapRows.length&&fit.score>=70){queue=ACTION_QUEUES.apply_now;reason=a.unknown?'Boa aderência conhecida; confirmar itens pendentes':'Boa aderência e nenhum impeditivo conhecido';}
    else if(gapRows.length===1&&small.length===1&&fit.score>=60&&a.hours<=20){queue=ACTION_QUEUES.apply_study;reason='Um gap pequeno e fechável em paralelo';}
    else if(gapRows.length<=3&&gapRows.length===small.length&&a.hours<=40&&fit.score>=40){queue=ACTION_QUEUES.prepare;reason=`${gapRows.length} gap${gapRows.length===1?'':'s'} fechável${gapRows.length===1?'':'is'} em até 40h`;}
    else if(a.unknown&&!gapRows.length){reason='Confirmar requisitos antes de decidir';}
    return {...queue,reason,confidence,confidenceLabel:confidence>=.8?'Alta':confidence>=.55?'Média':'Baixa',decisionScore:fit.score,knownCoverage:fit.coverage,knownRequirements:fit.known,totalRequirements:fit.total,gapCount:gapRows.length,unknownCount:a.unknown,hours:a.hours,blockerCount:gateBlocks.length};
  }
  function actionQueues(jobs,profile,skills,prefs={},answers={}){
    const decisions=jobs.map(j=>{const analysis=evaluate(j,profile,skills,prefs,answers);return {j,analysis,decision:actionDecision(j,analysis)};}).filter(x=>x.decision);
    return Object.values(ACTION_QUEUES).map(queue=>({queue,items:decisions.filter(x=>x.decision.id===queue.id).sort((a,b)=>b.decision.decisionScore-a.decision.decisionScore||b.decision.confidence-a.decision.confidence)}));
  }
  function priorities(jobs,profile,skills,prefs,answers){
    const qualified=d=>d&&['apply_now','apply_study'].includes(d.id),round=(n,d=2)=>Number(n.toFixed(d));
    const base=jobs.map(j=>{const a=evaluate(j,profile,skills,prefs,answers);return {j,a,d:actionDecision(j,a)};}).filter(x=>x.d);
    return skills.map(s=>{const affected=base.filter(x=>x.a.skillGaps.some(g=>g.id===s.id));const p=profile[s.id]||{l:0,e:0};if(p.l>=4||!affected.length)return null;
      const simulated={...profile,[s.id]:{...p,l:Math.min(4,p.l+1),e:Math.max(2,p.e)}};
      const after=affected.map(x=>{const analysis=evaluate(x.j,simulated,skills,prefs,answers);return {...x,after:analysis,next:actionDecision(x.j,analysis)};});
      const unlockedJobs=after.filter(x=>!qualified(x.d)&&qualified(x.next)),promotedJobs=after.filter(x=>x.next&&x.next.order<x.d.order);
      const hours=12+(p.e<2?8:0),weightedUnlocked=unlockedJobs.reduce((n,x)=>n+x.d.confidence,0),weightedPromoted=promotedJobs.reduce((n,x)=>n+x.d.confidence,0);
      const weightedFrequency=affected.reduce((n,x)=>n+x.d.confidence,0),gain=after.reduce((n,x)=>n+Math.max(0,x.next.decisionScore-x.d.decisionScore)*x.d.confidence,0);
      const applicationsPerHour=weightedUnlocked/hours,impactPerHour=(weightedUnlocked+weightedPromoted*.25+gain/100*.1)/hours;
      const examples=(unlockedJobs.length?unlockedJobs:promotedJobs).slice(0,3).map(x=>({key:x.j.key,company:x.j.company,role:x.j.role,before:x.d.label,after:x.next.label,confidence:x.d.confidence}));
      return {skill:s,frequency:affected.length,weightedFrequency:round(weightedFrequency),close:affected.filter(x=>x.d.order<=3).length,unlocked:unlockedJobs.length,weightedUnlocked:round(weightedUnlocked),promoted:promotedJobs.length,weightedPromoted:round(weightedPromoted),gain:round(gain,1),hours,target:Math.min(4,p.l+1),applicationsPerHour:round(applicationsPerHour,3),hoursPerApplication:weightedUnlocked?round(hours/weightedUnlocked,1):null,impactPerHour:round(impactPerHour,3),priority:round(impactPerHour*100,1),examples};
    }).filter(Boolean).sort((a,b)=>b.applicationsPerHour-a.applicationsPerHour||b.impactPerHour-a.impactPerHour||b.weightedFrequency-a.weightedFrequency);
  }
  function applicationSnapshot(j,a,d,capturedAt=new Date().toISOString()){
    if(!j||!a||!d)return null;
    return {version:1,capturedAt,score:a.score,decisionScore:d.decisionScore,queueId:d.id,queueLabel:d.label,confidence:d.confidence,sourceProvider:j.sourceProvider||'',sourceName:j.sourceName||'Não informada',company:j.company||'',role:j.role||'',gapCount:d.gapCount,unknownCount:d.unknownCount};
  }
  function feedbackAnalytics(applications,now=new Date().toISOString()){
    const apps=Array.isArray(applications)?applications:Object.values(applications||{}),nowMs=Date.parse(now),responseStages=new Set(['Teste técnico','Entrevista RH','Entrevista técnica','Rejeitado','Oferta']),interviewStages=new Set(['Entrevista RH','Entrevista técnica','Oferta']);
    const submitted=apps.filter(a=>a&&a.appliedAt),records=submitted.map(a=>{const stages=(a.history||[]).map(h=>h.stage),response=stages.some(s=>responseStages.has(s)),interview=stages.some(s=>interviewStages.has(s)),offer=stages.includes('Oferta'),rejected=stages.includes('Rejeitado'),applied=Date.parse(a.appliedAt),aged=Number.isFinite(nowMs)&&Number.isFinite(applied)&&nowMs-applied>=21*864e5;return {app:a,snapshot:a.matchSnapshot||null,response,interview,offer,rejected,mature:interview||rejected||aged};});
    const snapshotted=records.filter(r=>r.snapshot&&Number.isFinite(Number(r.snapshot.decisionScore))),mature=snapshotted.filter(r=>r.mature),rate=(n,d)=>d?Math.round(n/d*100):null;
    const summarize=rows=>({applications:rows.length,mature:rows.filter(r=>r.mature).length,responses:rows.filter(r=>r.response).length,interviews:rows.filter(r=>r.interview).length,offers:rows.filter(r=>r.offer).length,responseRate:rate(rows.filter(r=>r.response).length,rows.length),interviewRate:rate(rows.filter(r=>r.interview).length,rows.length)});
    const bands=[{id:'under50',label:'Abaixo de 50%',min:0,max:49},{id:'50to64',label:'50–64%',min:50,max:64},{id:'65to79',label:'65–79%',min:65,max:79},{id:'80plus',label:'80–100%',min:80,max:100}].map(b=>{const rows=snapshotted.filter(r=>Number(r.snapshot.decisionScore)>=b.min&&Number(r.snapshot.decisionScore)<=b.max),done=rows.filter(r=>r.mature);return {...b,...summarize(rows),matureInterviews:done.filter(r=>r.interview).length,matureInterviewRate:rate(done.filter(r=>r.interview).length,done.length)};});
    const groupBy=field=>{const groups={};for(const r of snapshotted){const key=r.snapshot[field]||'Não informada';(groups[key]??=[]).push(r);}return Object.entries(groups).map(([label,rows])=>({label,...summarize(rows)})).sort((a,b)=>b.interviews-a.interviews||b.applications-a.applications||a.label.localeCompare(b.label,'pt-BR'));};
    const high=mature.filter(r=>Number(r.snapshot.decisionScore)>=80),lower=mature.filter(r=>Number(r.snapshot.decisionScore)<80),highRate=rate(high.filter(r=>r.interview).length,high.length),lowerRate=rate(lower.filter(r=>r.interview).length,lower.length),ready=mature.length>=10&&high.length>=3&&lower.length>=3,difference=highRate==null||lowerRate==null?null:highRate-lowerRate;
    return {funnel:summarize(records),snapshotted:snapshotted.length,uncalibrated:records.length-snapshotted.length,mature:mature.length,bands,sources:groupBy('sourceName'),queues:groupBy('queueLabel'),calibration:{threshold:80,minimumMature:10,ready,high:{mature:high.length,interviews:high.filter(r=>r.interview).length,rate:highRate},lower:{mature:lower.length,interviews:lower.filter(r=>r.interview).length,rate:lowerRate},difference,status:!ready?'insufficient':difference>=10?'promising':'weak'}};
  }
  const api={norm,level,canonical,requirementRecords,normalize,evaluate,vacancyConfidence,knownFit,actionDecision,actionQueues,priorities,applicationSnapshot,feedbackAnalytics,ACTION_QUEUES};root.BancoEngine=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
