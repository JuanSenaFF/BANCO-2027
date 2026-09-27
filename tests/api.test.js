const test=require('node:test'),assert=require('node:assert/strict');
const {wrap}=require('../lib/server');
function response(){return {code:200,headers:{},setHeader(k,v){this.headers[k]=v;},status(n){this.code=n;return this;},json(v){this.body=v;},end(){}};}
test('API rejects unsupported method before handler',async()=>{const r=response();await wrap(['POST'],()=>assert.fail())({method:'GET',headers:{}},r);assert.equal(r.code,405);});
test('untrusted origin cannot invoke mutation',async()=>{process.env.ALLOWED_ORIGINS='https://trusted.example';const r=response();await wrap(['POST'],()=>assert.fail())({method:'POST',headers:{origin:'https://attacker.example'}},r);assert.equal(r.code,403);});
test('official GitHub Pages origin is allowed by default',async()=>{delete process.env.ALLOWED_ORIGINS;const r=response();await wrap(['POST'],()=>r.status(200).json({ok:true}))({method:'POST',headers:{origin:'https://juansenaff.github.io'}},r);assert.equal(r.code,200);assert.equal(r.headers['Access-Control-Allow-Origin'],'https://juansenaff.github.io');});
test('state validator rejects corrupt skill and malformed payloads',()=>{const {valid}=require('../api/state');assert.equal(valid({}),false);assert.equal(valid({profile:{x:{l:9,e:0}},prefs:{},applications:{},answers:{},alertRules:{},history:[],skillHistory:[],dismissed:[]}),false);});
test('state validator rejects malformed historical match snapshot',()=>{const {valid}=require('../api/state'),state={profile:{x:{l:1,e:1}},prefs:{},applications:{a:{matchSnapshot:{version:1,score:999}}},answers:{},alertRules:{},history:[],skillHistory:[],dismissed:[]};assert.equal(valid(state),false);});
test('state validator accepts legacy snapshot and rejects invalid optional coverage',()=>{const {valid}=require('../api/state'),snapshot={version:1,score:80,decisionScore:85,capturedAt:'2026-09-11T00:00:00Z',queueId:'apply_now',confidence:.8},state={profile:{x:{l:1,e:1}},prefs:{},applications:{a:{matchSnapshot:snapshot}},answers:{},alertRules:{},history:[],skillHistory:[],dismissed:[]};assert.equal(valid(state),true);state.applications.a.matchSnapshot={...snapshot,knownCoverage:101};assert.equal(valid(state),false);});
test('state validator accepts structured evidence and rejects unsafe links',()=>{const {valid}=require('../api/state'),base={prefs:{},applications:{},answers:{},alertRules:{},history:[],skillHistory:[],dismissed:[]},item={id:'ev-1',type:'project',context:'personal',title:'API de crédito',lastUsedAt:'2026-09-10',url:'https://github.com/example/project',description:'API testada'};assert.equal(valid({...base,profile:{python:{l:2,e:0,evidences:[item]}}}),true);assert.equal(valid({...base,profile:{python:{l:2,e:0,evidences:[{...item,url:'javascript:alert(1)'}]}}}),false);});

function databaseEnv(t,values={}){
  for(const key of ['SUPABASE_URL','SUPABASE_PUBLISHABLE_KEY','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY']){
    const before=process.env[key];
    t.after(()=>{if(before===undefined)delete process.env[key];else process.env[key]=before;});
    delete process.env[key];
  }
  Object.assign(process.env,{SUPABASE_URL:'https://project.example',...values});
}
test('API accepts a publishable key without a legacy anon key',async t=>{
  databaseEnv(t,{SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test'});
  t.mock.method(global,'fetch',async(url,options)=>{
    assert.equal(options.headers.apikey,'sb_publishable_test');
    assert.equal(options.headers.Authorization,undefined);
    return {ok:true,json:async()=>[]};
  });
  assert.deepEqual(await require('../lib/server').db('jobs?select=payload'),[]);
});
test('publishable key takes precedence while authenticated requests retain the user JWT',async t=>{
  databaseEnv(t,{SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test',SUPABASE_ANON_KEY:'legacy-anon'});
  t.mock.method(global,'fetch',async(url,options)=>{
    assert.equal(options.headers.apikey,'sb_publishable_test');
    assert.equal(options.headers.Authorization,'Bearer user-jwt');
    return {ok:true,json:async()=>({id:'owner'})};
  });
  assert.equal((await require('../lib/server').auth({headers:{authorization:'Bearer user-jwt'}})).user.id,'owner');
});
test('legacy anon configuration remains compatible',async t=>{
  databaseEnv(t,{SUPABASE_ANON_KEY:'legacy-anon'});
  t.mock.method(global,'fetch',async(url,options)=>{
    assert.equal(options.headers.apikey,'legacy-anon');
    assert.equal(options.headers.Authorization,'Bearer legacy-anon');
    return {ok:true,json:async()=>[]};
  });
  assert.deepEqual(await require('../lib/server').db('jobs'),[]);
});
test('state validator rejects containers that break rendering and persistence',()=>{
  const {valid}=require('../api/state');
  const base={profile:{},prefs:{},applications:{},answers:{},alertRules:{},history:[],skillHistory:[],dismissed:[]};
  for(const field of ['profile','prefs','applications','answers','alertRules']){
    for(const value of [[],true,'invalid'])assert.equal(valid({...base,[field]:value}),false,field);
  }
  for(const patch of [{prefs:{priorityCompanies:'Itaú'}},{prefs:{years:'invalid'}},{applications:{a:'broken'}},{applications:{a:{history:{}}}},{answers:{a:[]}}, {history:[null]}]){
    assert.equal(valid({...base,...patch}),false,JSON.stringify(patch));
  }
});
