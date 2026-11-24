const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const result={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/reader-settings.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:result});
const {readerSettings,scopePreferences,appearanceOf,settingsOutsideAppearance}=result;
const global={theme:'navy',fontSize:24,width:1100,layout:'spread',cover:'separate',voice:'ruslan',rate:1.2};
test('books inherit shared appearance by default, including fixed-page defaults',()=>{
 const value=readerSettings(global,{});assert.equal(value.fontSize,24);assert.equal(value.pageGap,true);assert.equal(value.pageFit,true);assert.equal(value.pageSpreadWidth,1800);
 assert.equal(readerSettings({...global,fontSize:28},{}).fontSize,28);
});
test('personal snapshot isolates all appearance while speech still follows global settings',()=>{
 const own=scopePreferences({},false,readerSettings(global,{}));own.appearance.theme='moss';own.appearance.fontSize=30;
 const value=readerSettings({...global,theme:'white',fontSize:18,voice:'irina',pageGap:false},own);
 assert.equal(value.theme,'moss');assert.equal(value.fontSize,30);assert.equal(value.voice,'irina');assert.equal(value.pageGap,true);
 assert.equal(own.appearance.voice,undefined);assert.equal(settingsOutsideAppearance(value).fontSize,undefined);
});
test('returning to common settings and back restores the previous personal appearance',()=>{
 const own=scopePreferences({unrelated:'preserved'},false,{...global,fontSize:28,pageGap:false});
 const shared=scopePreferences(own,true,readerSettings(global,own));
 assert.equal(readerSettings(global,shared).fontSize,24);
 const restored=scopePreferences(shared,false,readerSettings(global,shared));
 assert.equal(restored.appearance.fontSize,28);assert.equal(restored.appearance.pageGap,false);assert.equal(restored.unrelated,'preserved');
});
test('malformed per-book fields cannot override voices or unrelated library controls',()=>{
 const value=readerSettings(global,{useGlobalAppearance:false,appearance:{fontSize:26,voice:'fake',rate:99,opdsView:'table'}});
 assert.equal(value.fontSize,26);assert.equal(value.voice,'ruslan');assert.equal(value.rate,1.2);assert.equal(value.opdsView,undefined);
 assert.equal(appearanceOf({pageSpreadWidth:1200,series:'test'}).series,undefined);
});
