const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const root=path.resolve(__dirname,'..');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');

test('action queues are reachable from navigation and router',()=>{
  assert.match(read('index.html'),/href="#actions">Filas de ação/);
  assert.match(read('app.js'),/const renderers=\{dashboard,actions,/);
});

test('radar exposes the action queue filter',()=>{
  const app=read('app.js');
  assert.match(app,/data-filter="queue"/);
  assert.match(app,/filters\.queue/);
});

test('queue board has responsive styles and all four visual states',()=>{
  const css=read('styles.css');
  assert.match(css,/\.queue-board/);
  for(const id of ['apply_now','apply_study','prepare','monitor'])assert.match(css,new RegExp(`queue-${id}`));
});

test('match API exposes the same derived action decision',()=>{
  assert.match(read('api/match.js'),/action:E\.actionDecision\(job,analysis\)/);
});
