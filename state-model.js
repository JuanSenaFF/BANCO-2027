(function(root){
  'use strict';
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const text=(x,max=5000)=>typeof x==='string'&&x.length<=max;
  const optional=(x,check)=>x==null||check(x);
  const date=x=>typeof x==='string'&&Number.isFinite(Date.parse(x));
  const array=(x,check)=>Array.isArray(x)&&x.every(check);
  const stages=['Não avaliada','Interessante','Aplicar','Candidatado','Teste técnico','Entrevista RH','Entrevista técnica','Rejeitado','Oferta'];
  function validSnapshot(x){return x==null||(object(x)&&x.version===1&&Number.isFinite(x.score)&&x.score>=0&&x.score<=100&&Number.isFinite(x.decisionScore)&&x.decisionScore>=0&&x.decisionScore<=100&&optional(x.knownCoverage,v=>Number.isFinite(v)&&v>=0&&v<=100)&&date(x.capturedAt)&&text(x.queueId,100)&&Number.isFinite(x.confidence)&&x.confidence>=0&&x.confidence<=1);}
  function validEvidence(x){
    if(!object(x)||!text(x.id,200)||!x.id||!['project','work','course','certification'].includes(x.type)||!['study','personal','production'].includes(x.context)||!text(x.title,160)||!x.title.trim()||!date(x.lastUsedAt)||!text(x.description,1000)||!text(x.url,1000))return false;
    if(x.url){try{if(!['http:','https:'].includes(new URL(x.url).protocol))return false;}catch{return false;}}
    return true;
  }
  function valid(s){
    if(!object(s)||!['profile','prefs','applications','answers','alertRules'].every(k=>object(s[k]))||!array(s.history,object)||!array(s.skillHistory,object)||!array(s.dismissed,x=>text(x)))return false;
    const p=s.prefs;
    if(!optional(p.years,v=>Number.isFinite(v)&&v>=0&&v<=60)||!optional(p.english,v=>Number.isInteger(v)&&v>=0&&v<=3)||!optional(p.priorityCompanies,v=>array(v,x=>text(x,200))))return false;
    if(!['education','location','modality','area','role'].every(k=>optional(p[k],v=>text(v,500))))return false;
    if(!Object.values(s.alertRules).every(v=>typeof v==='boolean'))return false;
    if(!Object.values(s.answers).every(v=>object(v)&&Object.values(v).every(x=>['','yes','partial','no'].includes(x))))return false;
    if(!Object.values(s.profile).every(v=>object(v)&&Number.isInteger(v.l)&&v.l>=0&&v.l<=4&&Number.isInteger(v.e)&&v.e>=0&&v.e<=4&&optional(v.note,x=>text(x))&&(!('evidences' in v)||array(v.evidences,validEvidence))))return false;
    return Object.values(s.applications).every(a=>object(a)&&validSnapshot(a.matchSnapshot)&&optional(a.key,x=>text(x,1000))&&optional(a.stage,x=>stages.includes(x))&&optional(a.history,x=>array(x,h=>object(h)&&stages.includes(h.stage)&&date(h.at)))&&['nextAction','dueDate','notes','feedback','createdAt','appliedAt'].every(k=>optional(a[k],x=>text(x))));
  }
  // Older v3 backups may omit fields introduced after their export.
  function prepare(value){
    if(!object(value))return null;
    const s={...value,skillHistory:value.skillHistory??[],alertRules:value.alertRules??{},dismissed:value.dismissed??[]};
    if(!valid(s))return null;
    const copy=JSON.parse(JSON.stringify(s));
    for(const [key,a] of Object.entries(copy.applications)){
      a.key=key;
      a.stage??='Interessante';
      a.history??=[];
    }
    return copy;
  }
  const api={valid,prepare};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.BancoState=api;
})(typeof window!=='undefined'?window:globalThis);
