const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const output={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/reading-status.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:output});
const {normalizeReadStatus,plannedReturnStatus}=output;
test('reading status aliases normalize without using position or assuming unknown completion',()=>{
 for(const value of ['unread','reading','planned','read'])assert.equal(normalizeReadStatus(value),value);
 assert.equal(normalizeReadStatus('finished'),'read');assert.equal(normalizeReadStatus('want'),'planned');
 for(const value of [undefined,null,'complete',100,{},'READ'])assert.equal(normalizeReadStatus(value),'unread');
});
test('removing a book from plans restores its explicit previous state without changing its position',()=>{
 for(const state of ['unread','reading','read']){const book={planned_previous_status:state,progress:76,last_opened:'2026-10-27'};assert.equal(plannedReturnStatus(book),state);assert.equal(book.progress,76)}
 assert.equal(plannedReturnStatus({planned_previous_status:'finished'}),'read');
});
test('legacy plans use started state as fallback; reaching 100 percent never marks a book read',()=>{
 assert.equal(plannedReturnStatus({progress:0}),'unread');assert.equal(plannedReturnStatus({last_opened:'2026-10-27',progress:0}),'reading');
 assert.equal(plannedReturnStatus({progress:100}),'reading');assert.equal(plannedReturnStatus({planned_previous_status:'planned',progress:100}),'reading');
 assert.equal(plannedReturnStatus({planned_previous_status:'broken'}),'unread');
});
