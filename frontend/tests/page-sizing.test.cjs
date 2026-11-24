const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const output={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/page-sizing.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:output});
const {spreadWidths}=output;
test('spread fills available height; a lone cover is not forced into half width',()=>{
 const two=spreadWidths(1800,900,[1.5,1.5],18);assert.equal(two[0],600);assert.equal(two[1],600);
 const one=spreadWidths(900,1200,[1.5],18);assert.equal(one[0],800);
});
test('equal height keeps each source aspect ratio and fits total width',()=>{
 for(const width of [600,1800]){const values=spreadWidths(width,900,[1.5,1.4],0,true);assert.ok(Math.abs(values[0]*1.5-values[1]*1.4)<.0001);assert.ok(values[0]+values[1]<=width+.0001);assert.ok(values[0]*1.5<=900);assert.notEqual(values[0],values[1])}
 const values=spreadWidths(1200,900,[1.5,1.4],18,false);assert.equal(values[0],values[1]);assert.ok(values[0]*1.5!==values[1]*1.4);
});
