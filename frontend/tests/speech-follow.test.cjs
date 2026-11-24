const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const helpers={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/speech-follow.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:helpers});
test('split fragment maps repeated text after earlier audio, ignoring other paragraph IDs',()=>{
 const parts=[{id:'x',text:'Мимо.'},{id:'p',text:'Фраза.'},{id:'p',text:'Фраза.'},{id:'p',text:'Конец.'}];
 assert.deepEqual(JSON.parse(JSON.stringify(helpers.speechFragmentSpan(parts,2,'Фраза.  Фраза. Конец.'))),{start:8,end:14});
 assert.equal(helpers.speechFragmentSpan(parts,2,'Другой текст'),null);
});
test('approximate audio position advances through fragment and preserves emoji boundaries',()=>{
 const text='А🕮БВГД',span={start:0,end:text.length};
 assert.equal(helpers.speechCharacterAt(text,span,0,10),0);
 assert.equal(helpers.speechCharacterAt(text,span,3,10),1);
 assert.equal(helpers.speechCharacterAt(text,span,10,10),text.length-1);
 assert.equal(helpers.speechCharacterAt(text,span,3,NaN),null);
 assert.equal(helpers.speechCharacterAt(text,span,3,0),null);
});
