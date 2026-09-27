const test=require('node:test'),assert=require('node:assert/strict');
const {createSession,createSaveQueue}=require('../client-sync');
const {valid,prepare}=require('../state-model');
const deferred=()=>{let resolve,reject;const promise=new Promise((ok,no)=>{resolve=ok;reject=no;});return {promise,resolve,reject};};
function clock(){
  let time=0,next=0;
  const timers=new Map();
  return {timers,now:()=>time,schedule:(fn,ms)=>{const id=++next;timers.set(id,{fn,ms});return id;},cancel:id=>timers.delete(id),advance:ms=>{time+=ms;},fire(){const [id,{fn}]=timers.entries().next().value;timers.delete(id);fn();}};
}
const tokens=n=>({access_token:'access-'+n,refresh_token:'refresh-'+n,expires_in:3600});
const response=data=>({ok:true,json:async()=>data});
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('session refresh repeats across multiple expirations using the rotated token',async()=>{
  const time=clock(),used=[];let n=0;
  const session=createSession({url:'https://auth.example',key:'public',...time,fetcher:async(url,options)=>{used.push(JSON.parse(options.body).refresh_token);return response(tokens(++n));}});
  session.set(tokens(0));
  time.fire();await tick();
  assert.equal(time.timers.size,1);
  time.fire();await tick();
  assert.equal(time.timers.size,1);
  assert.deepEqual(used,['refresh-0','refresh-1']);
  assert.equal(await session.token(),'access-2');
  session.clear();assert.equal(time.timers.size,0);
});
test('logout during refresh does not resurrect the old session',async()=>{
  const time=clock(),network=deferred(),changes=[];
  const session=createSession({url:'https://auth.example',key:'public',...time,onChange:x=>changes.push(x),fetcher:()=>network.promise});
  session.set(tokens(0));const refresh=session.refresh();session.clear();
  network.resolve(response(tokens(1)));await refresh;
  assert.equal(changes.at(-1),null);assert.equal(time.timers.size,0);
  await assert.rejects(session.token(),/Entre/);
});
test('an old refresh cannot replace a newer login',async()=>{
  const time=clock(),network=deferred();
  const session=createSession({url:'https://auth.example',key:'public',...time,fetcher:()=>network.promise});
  session.set(tokens('old'));const refresh=session.refresh();session.clear();session.set(tokens('new'));
  network.resolve(response(tokens('stale')));await refresh;
  assert.equal(await session.token(),'access-new');
  session.clear();
});
test('requests refresh an expired session even when the browser timer was suspended',async()=>{
  const time=clock();let calls=0;
  const session=createSession({url:'https://auth.example',key:'public',...time,fetcher:async()=>{calls++;return response(tokens(1));}});
  session.set(tokens(0));time.advance(3600001);
  assert.deepEqual(await Promise.all([session.token(),session.token()]),['access-1','access-1']);
  assert.equal(calls,1);session.clear();
});
test('a rejected refresh ends the session and reports expiration',async()=>{
  const time=clock();let expired=0;
  const session=createSession({url:'https://auth.example',key:'public',...time,onExpired:()=>expired++,fetcher:async()=>({ok:false})});
  session.set(tokens(0));await assert.rejects(session.refresh(),/expirada/);
  assert.equal(expired,1);assert.equal(time.timers.size,0);
  await assert.rejects(session.token(),/Entre/);
});
test('slow saves are serialized and intermediate revisions coalesce to the latest state',async()=>{
  const first=deferred(),second=deferred(),sent=[],saved=[];
  const queue=createSaveQueue({send:state=>{sent.push(state);return sent.length===1?first.promise:second.promise;},onSaved:r=>saved.push(r)});
  const initial={value:1},done=queue.save(initial,1);initial.value=99;
  queue.save({value:2},2);queue.save({value:3},3);
  assert.deepEqual(sent,[{value:1}]);
  first.resolve();await tick();assert.deepEqual(sent,[{value:1},{value:3}]);
  second.resolve();await done;assert.deepEqual(saved,[1,3]);
});
test('logout drops pending saves and ignores completion messages from the old account',async()=>{
  const network=deferred(),sent=[],saved=[];
  const queue=createSaveQueue({send:s=>{sent.push(s);return network.promise;},onSaved:r=>saved.push(r)});
  const done=queue.save({value:1},1);queue.save({value:2},2);queue.reset();
  network.resolve();await done;assert.deepEqual(sent,[{value:1}]);assert.deepEqual(saved,[]);
});
test('a failed save preserves the next queued edit',async()=>{
  const network=deferred(),sent=[],errors=[];
  const queue=createSaveQueue({send:s=>{sent.push(s);return sent.length===1?network.promise:Promise.resolve();},onError:e=>errors.push(e.message)});
  const done=queue.save({value:1},1);queue.save({value:2},2);network.reject(Error('offline'));await done;
  assert.deepEqual(sent,[{value:1},{value:2}]);assert.deepEqual(errors,['offline']);
});
test('legacy backup fields receive defaults without altering the imported object',()=>{
  const old={profile:{python:{l:2,e:2}},prefs:{},applications:{job:{stage:'Interessante'}},answers:{},history:[]};
  const state=prepare(old);
  assert.ok(valid(state));assert.deepEqual(state.skillHistory,[]);assert.deepEqual(state.applications.job.history,[]);
  assert.equal(state.applications.job.key,'job');assert.equal(old.applications.job.history,undefined);
});
test('malformed backups fail validation before replacing the local draft',()=>{
  const base={profile:{},prefs:{},applications:{},answers:{},history:[]};
  assert.equal(prepare({...base,profile:[]}),null);
  assert.equal(prepare({...base,prefs:{priorityCompanies:'Itaú'}}),null);
  assert.equal(prepare({...base,skillHistory:'broken'}),null);
  assert.equal(prepare({...base,applications:{job:{history:{}}}}),null);
});
