const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const exportsForTest={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/reading-position.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsForTest});
const {positionInBook,locateInBook}=exportsForTest;
test('book seek uses chapter lengths, boundaries and exact beginning/end',()=>{
 const chapters=[{length:100},{length:800},{length:100}];
 assert.equal(positionInBook(chapters,3,1,.5),.5);
 const middle=locateInBook(chapters,3,.5);assert.equal(middle.chapter,1);assert.equal(middle.ratio,.5);
 assert.equal(locateInBook(chapters,3,.1).chapter,1);
 assert.equal(locateInBook(chapters,3,0).chapter,0);
 const end=locateInBook(chapters,3,1);assert.equal(end.chapter,2);assert.equal(end.end,true);
});
test('missing metadata stays bounded and positions round-trip without full book rendering',()=>{
 assert.equal(locateInBook([],4,.5).chapter,2);
 assert.equal(positionInBook([],4,2,0),.5);
 assert.equal(locateInBook([],0,-3).chapter,0);
 assert.equal(locateInBook([],4,500).chapter,3);
 const chapters=[{length:27},{length:89},{length:41}];
 for(const part of [.02,.21,.5,.78,.99]){const loc=locateInBook(chapters,3,part);assert.ok(Math.abs(positionInBook(chapters,3,loc.chapter,loc.ratio)-part)<1e-9);}
});
