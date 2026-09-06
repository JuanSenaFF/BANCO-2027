const test=require('node:test'),assert=require('node:assert/strict');
const {wrap}=require('../lib/server');
function response(){return {code:200,headers:{},setHeader(k,v){this.headers[k]=v;},status(n){this.code=n;return this;},json(v){this.body=v;},end(){}};}
test('API rejects unsupported method before handler',async()=>{const r=response();await wrap(['POST'],()=>assert.fail())({method:'GET',headers:{}},r);assert.equal(r.code,405);});
test('untrusted origin cannot invoke mutation',async()=>{process.env.ALLOWED_ORIGINS='https://trusted.example';const r=response();await wrap(['POST'],()=>assert.fail())({method:'POST',headers:{origin:'https://attacker.example'}},r);assert.equal(r.code,403);});
test('state validator rejects corrupt skill and malformed payloads',()=>{const {valid}=require('../api/state');assert.equal(valid({}),false);assert.equal(valid({profile:{x:{l:9,e:0}},prefs:{},applications:{},answers:{},alertRules:{},history:[],skillHistory:[],dismissed:[]}),false);});
