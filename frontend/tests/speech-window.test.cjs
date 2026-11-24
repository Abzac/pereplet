const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const exportsForTest={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/speech-window.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsForTest});
const {speechWindow,speechCacheLimit}=exportsForTest;
test('window includes all visible fragments and three following paragraphs, prioritizing forward playback',()=>{
 const parts=['a','b','b','c','d','e','e','f','g','h'].map(id=>({id}));
 assert.deepEqual([...speechWindow(parts,['a','b','c'],1)],[2,3,4,5,6,7,0]);
});
test('missing geometry starts with current paragraph and three more without exhausting the chapter',()=>{
 const parts=['a','a','b','c','d','e'].map(id=>({id}));
 assert.deepEqual([...speechWindow(parts,[],0)],[1,2,3,4]);
 assert.deepEqual([...speechWindow(parts,['e'],5)],[]);
});
test('cache has conservative default and optional smaller budget',()=>{
 assert.equal(speechCacheLimit(undefined),32*1024*1024);assert.equal(speechCacheLimit('unknown'),32*1024*1024);assert.equal(speechCacheLimit('small'),16*1024*1024);
});
