const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const exportsObject={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/opds-related.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsObject,URL});
const {relatedDestinations}=exportsObject;const feedLink=(title,url,rel=['related'])=>({title,url,type:'application/atom+xml',rel});const entry=extra=>({id:'1',title:'Book',authors:[],acquisitions:[],...extra});
test('published Flibusta author and series feeds win over author website URIs',()=>{
 const result=relatedDestinations(entry({authors:['Автор Первый'],author_details:[{name:'Автор Первый',uri:'https://flibusta.is/a/42'}],related_links:[feedLink('Все книги автора Автор Первый','https://flibusta.is/opds/author/42'),feedLink('Все книги серии Космос','https://flibusta.is/opds/sequence/8')]}),true);
 assert.equal(result.length,2);assert.equal(result[0].url,'https://flibusta.is/opds/author/42');assert.equal(result[1].name,'Космос');assert.equal(result[1].kind,'series');
});
test('nested JSON links retain each author and named series without guessing routes',()=>{
 const result=relatedDestinations(entry({authors:['First','Second'],author_details:[{name:'First',links:[feedLink('', 'https://books.test/first')]},{name:'Second',links:[feedLink('', 'https://books.test/second')]}],series:[{name:'Серия',position:3,links:[feedLink('','https://books.test/series')]}]}));
 assert.deepEqual(Array.from(result,x=>x.url),['https://books.test/first','https://books.test/second','https://books.test/series']);assert.equal(result[2].position,3);
});
test('metadata-only names are explicit search fallbacks; HTML/self links are not catalog routes',()=>{
 const result=relatedDestinations(entry({authors:['Name'],author_details:[{name:'Name',uri:'https://books.test/a/1'}],series:[{name:'Series'}],related_links:[{title:'Все книги автора Name',url:'https://books.test/a/1',type:'text/html',rel:['related']},feedLink('Name','https://books.test/book',['self'])]}));
 assert.deepEqual(Array.from(result,x=>[x.kind,x.name,x.url]),[['author','Name',undefined],['series','Series',undefined]]);
});
test('two authors are matched by title and cannot accidentally share one unnamed relation',()=>{
 const result=relatedDestinations(entry({authors:['One','Two'],related_links:[feedLink('Все книги автора Two','https://books.test/two'),feedLink('','https://books.test/unknown',['author'])]}));assert.equal(result[0].url,undefined);assert.equal(result[1].url,'https://books.test/two');
});
