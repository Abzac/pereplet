const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');const ts=require('typescript');
const source=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/api.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function load(fetch){const exports={};vm.runInNewContext(source,{exports,fetch,FormData,DOMException});return exports}
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json'}});
test('server restart renews one token for simultaneous rejected operations and replays each once',async()=>{let session=0,accepted=0,rejected=0,serverToken='old';const api=load(async(url,options)=>{if(url==='/api/session'){session++;await new Promise(r=>setTimeout(r,5));return json({token:serverToken})}if(options.headers['X-Pereplet-Token']!==serverToken){rejected++;return json({detail:'Запрос должен выполняться из приложения'},403)}accepted++;return json({ok:true})});await api.initApi();serverToken='new';await Promise.all([api.api('/api/a','PATCH',{x:1}),api.api('/api/b','POST',{x:2})]);assert.equal(session,2);assert.equal(rejected,2);assert.equal(accepted,2)});
test('other forbidden responses, server errors and network failures are never replayed',async()=>{for(const status of [403,500]){let attempts=0;const api=load(async()=>{attempts++;return json({detail:'Другая причина'},status)});await assert.rejects(api.api('/api/x','POST',{}),/Другая причина/);assert.equal(attempts,1)}let attempts=0;const api=load(async()=>{attempts++;throw new Error('network')});await assert.rejects(api.api('/api/x','POST',{}),/network/);assert.equal(attempts,1)});
test('repeated token rejection has a strict one-retry limit',async()=>{let attempts=0,sessions=0;const api=load(async url=>{if(url==='/api/session'){sessions++;return json({token:'key'})}attempts++;return json({detail:'Запрос должен выполняться из приложения'},403)});await assert.rejects(api.api('/api/x','POST',{}),/Запрос должен/);assert.equal(attempts,2);assert.equal(sessions,1)});
test('cancellation during renewal does not replay a write',async()=>{const controller=new AbortController();let writes=0;const api=load(async url=>{if(url==='/api/session'){controller.abort();return json({token:'key'})}writes++;return json({detail:'Запрос должен выполняться из приложения'},403)});await assert.rejects(api.api('/api/x','PATCH',{},controller.signal),error=>error.name==='AbortError');assert.equal(writes,1)});

test('abort settles while shared renewal is pending and another caller can finish',async()=>{
 let release,started;const waiting=new Promise(resolve=>started=resolve),gate=new Promise(resolve=>release=resolve);
 let sessions=0,accepted=0,rejected=0;const controller=new AbortController();
 const api=load(async(url,options)=>{
  if(url==='/api/session'){sessions++;started();await gate;return json({token:'fresh'})}
  if(options.headers['X-Pereplet-Token']!=='fresh'){rejected++;return json({detail:'Запрос должен выполняться из приложения'},403)}
  accepted++;return json({ok:true});
 });
 const cancelled=api.api('/api/a','PATCH',{x:1},controller.signal).then(()=>null,error=>error.name);
 const other=api.api('/api/b','PATCH',{x:2});
 await waiting;controller.abort();
 let timer;
 try{assert.equal(await Promise.race([cancelled,new Promise(resolve=>timer=setTimeout(()=>resolve('still pending'),100))]),'AbortError')}
 finally{clearTimeout(timer);release()}
 assert.deepEqual(await other,{ok:true});assert.equal(sessions,1);assert.equal(rejected,2);assert.equal(accepted,1);
});

test('failed shared renewal clears its state so a later operation can recover',async()=>{
 let sessions=0,attempts=0;
 const api=load(async(url,options)=>{if(url==='/api/session'){sessions++;if(sessions===1)throw new Error('session offline');return json({token:'fresh'})}attempts++;return options.headers['X-Pereplet-Token']==='fresh'?json({ok:true}):json({detail:'Запрос должен выполняться из приложения'},403)});
 await assert.rejects(api.api('/api/a','PATCH',{}),/session offline/);
 assert.equal(attempts,1);assert.deepEqual(await api.api('/api/b','PATCH',{}),{ok:true});assert.equal(sessions,2);assert.equal(attempts,3);
});

test('a late old-token rejection reuses the already renewed token',async()=>{
 let sessions=0,serverToken='old',release,started,accepted=0;
 const waiting=new Promise(resolve=>started=resolve),gate=new Promise(resolve=>release=resolve);
 const api=load(async(url,options)=>{if(url==='/api/session'){sessions++;return json({token:serverToken})}if(options.headers['X-Pereplet-Token']!==serverToken){if(url==='/api/slow'){started();await gate}return json({detail:'Запрос должен выполняться из приложения'},403)}accepted++;return json({ok:true})});
 await api.initApi();serverToken='new';const slow=api.api('/api/slow','PATCH',{});await waiting;
 await api.api('/api/fast','PATCH',{});release();await slow;
 assert.equal(sessions,2);assert.equal(accepted,2);
});
