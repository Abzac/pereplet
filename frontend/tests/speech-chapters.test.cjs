const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
function load(name){const exports={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/'+name+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:id=>id==='./speech'?load('speech'):{api:()=>Promise.resolve()}});return exports;}
const {nextSpeechChapter}=load('speech-chapters');
test('lookahead skips empty chapters once, stopping at next readable chapter',async()=>{
 const calls=[];const result=await nextSpeechChapter(0,5,async index=>{calls.push(index);return {paragraphs:index<3?[{id:'x',text:'   '}]:[{id:'p',text:'Следующая глава.'}]};},new AbortController().signal);
 assert.deepEqual(calls,[1,2,3]);assert.equal(result.index,3);assert.equal(result.parts[0].text,'Следующая глава.');
});
test('all remaining empty chapters end the book without wrapping or repeating',async()=>{
 const calls=[];assert.equal(await nextSpeechChapter(1,4,async index=>{calls.push(index);return {paragraphs:[]};},new AbortController().signal),null);assert.deepEqual(calls,[2,3]);
});
test('stop during chapter fetch prevents further scans and returning stale chapter',async()=>{
 const controller=new AbortController(),calls=[];
 await assert.rejects(nextSpeechChapter(0,4,async index=>{calls.push(index);controller.abort();return {paragraphs:[{id:'p',text:'Поздний ответ.'}]};},controller.signal),{name:'AbortError'});assert.deepEqual(calls,[1]);
});
