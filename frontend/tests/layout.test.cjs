const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/types.ts'),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exportsForTest={};vm.runInNewContext(code,{exports:exportsForTest});
const {defaultSettings,layoutSettings,normalizeSettings}=exportsForTest;
test('switching between reader layouts remembers each chosen width',()=>{
 let settings=layoutSettings(defaultSettings,'single');
 assert.equal(settings.width,760);
 settings={...settings,width:920,singleWidth:920};
 settings=layoutSettings(settings,'spread');assert.equal(settings.width,1120);
 settings=layoutSettings(settings,'scroll');assert.equal(settings.width,840);
 settings=layoutSettings(settings,'single');assert.equal(settings.width,920);
 assert.equal(normalizeSettings(settings).width,920);
});
test('old single-page settings do not inherit the wide spread default',()=>{
 assert.equal(normalizeSettings({layout:'single',width:1120}).width,760);
 assert.equal(normalizeSettings({layout:'spread',width:1280}).width,1280);
 assert.equal(normalizeSettings({layout:'scroll',scrollWidth:960,width:960}).width,960);
});
