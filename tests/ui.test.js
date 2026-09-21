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
test('action queues explain minimum known coverage',()=>{const app=read('app.js');assert.match(app,/70% de cobertura para Aplicar agora/);assert.match(app,/60% para Aplicar e estudar/);assert.match(app,/40% para Preparar/);assert.match(app,/Cobertura conhecida/);});

test('match API exposes the same derived action decision',()=>{
  const api=read('api/match.js');
  assert.match(api,/action:E\.actionDecision\(j,analysis\)/);
  assert.match(api,/studyPriorities:E\.priorities/);
});

test('study page presents application impact instead of demand alone',()=>{
  const app=read('app.js');
  assert.match(app,/Candidaturas adicionais/);
  assert.match(app,/Horas por candidatura/);
  assert.match(app,/Vagas que mudam de fila/);
});

test('career goal and learning estimates use the annual 2027 horizon',()=>{
  const app=read('app.js'),index=read('index.html'),engine=read('engine.js');
  assert.match(index,/Meta · Jul–Dez de 2027/);
  assert.match(app,/ciclo de preparação de 12 meses/);
  assert.match(app,/8 horas por semana/);
  assert.match(engine,/Preparar em até 12 meses/);
  assert.doesNotMatch(app,/Preparar 1–2 semanas/);
});

test('pipeline freezes submission context and exposes score calibration',()=>{const app=read('app.js');assert.match(app,/captureMatchSnapshot/);assert.match(app,/O corte de 80% prevê entrevistas/);assert.match(app,/Desempenho por fonte/);assert.match(app,/Desempenho por fila de origem/);});

test('technology market dashboard is reachable and company-based',()=>{const app=read('app.js'),index=read('index.html');assert.match(index,/href="#technologies">Tecnologias/);assert.match(app,/function technologies\(\)/);assert.match(app,/DEMANDA POR EMPRESAS/);assert.match(app,/empresas exigem/);assert.match(app,/citam como diferencial/);assert.match(app,/Outra stack, como Java, permanece na visão ampla/);});

test('vacancy cards and radar expose market classification',()=>{const app=read('app.js');assert.match(app,/marketSegmentLabel/);assert.match(app,/careerAlignmentLabel/);assert.match(app,/geographyLabel/);assert.match(app,/Tipo de vaga/);assert.match(app,/Recorte geográfico/);});

test('beveled visual system is loaded and shipped in the production bundle',()=>{
  const index=read('index.html'),css=read('styles.css'),build=read('scripts/build_site.py');
  assert.match(index,/class="market-status"/);
  assert.match(index,/src="design\.js"/);
  assert.match(build,/'design\.js'/);
  assert.match(css,/--accent:#ff5912/);
  assert.match(css,/clip-path:polygon/);
  assert.match(css,/background-size:44px 44px/);
});

test('Spell-inspired text and label behavior stays accessible and motion-safe',()=>{
  const design=read('design.js'),css=read('styles.css');
  assert.match(design,/function specialText/);
  assert.match(design,/function enhanceLabels/);
  assert.match(design,/setAttribute\('aria-label',finalText\)/);
  assert.match(design,/prefers-reduced-motion: reduce/);
  assert.match(design,/password-toggle/);
  assert.match(css,/\.label-input__caption/);
  assert.match(css,/@media\(prefers-reduced-motion:reduce\)/);
  assert.doesNotMatch(css,/transition:\s*all/);
});
test('profile captures structured evidence and uses the evidence engine',()=>{const app=read('app.js'),engine=read('engine.js');assert.match(app,/profile:profileEvidence/);assert.match(app,/Projeto ou repositório/);assert.match(app,/Última utilização/);assert.match(app,/evidenceForm/);assert.match(engine,/function evidenceLevel/);});
