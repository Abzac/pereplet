const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const exportsObject={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/book-metadata.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsObject,URL});
const {compareSeriesPositions,numericSeriesPosition,formatFileSize,remoteSizeLabel,sortEntriesInSeries}=exportsObject;
const entry=(id,position,name='Мир')=>({id,title:`Book ${id}`,authors:[],series:[{name,position}],acquisitions:[]});

test('known zero and fractional positions sort numerically, unknown stays last in both directions',()=>{
 for(const direction of [1,-1]){
  const values=[undefined,'10','',2,'2,5',0,'broken',null].sort((a,b)=>compareSeriesPositions(a,b,direction));
  assert.deepEqual(values.filter(x=>numericSeriesPosition(x)!==null),direction===1?[0,2,'2,5','10']:['10','2,5',2,0]);
  assert.equal(compareSeriesPositions('broken',2,direction),1);
 }
 for(const value of [undefined,null,'',false,-1,Infinity,'2tail'])assert.equal(numericSeriesPosition(value),null);
});
test('series feed defaults to metadata order; unrelated feed and missing metadata preserve source order',()=>{
 const list=[entry('ten',10),entry('unknown',undefined),entry('two',2),entry('other',1,'Другая'),entry('zero',0)];
 assert.deepEqual(Array.from(sortEntriesInSeries(list,{url:'https://catalog.test/series/1',title:'Книги в серии Мир'}),x=>x.id),['zero','two','ten','unknown','other']);
 assert.equal(sortEntriesInSeries(list,{url:'https://catalog.test/author/1',title:'Книги автора Автор'}),list);
 assert.equal(sortEntriesInSeries(list),list);
});
test('published series links identify an otherwise opaque feed; ambiguous metadata is not guessed',()=>{
 const list=[entry('two',2),entry('one',1)];for(const book of list)book.series[0].links=[{url:'https://catalog.test/opaque'}];
 assert.deepEqual(Array.from(sortEntriesInSeries(list,{url:'https://catalog.test/opaque?page=2',title:'Books'}),x=>x.id),['one','two']);
 list[1].series.push({name:'Other',position:20,links:[{url:'https://catalog.test/opaque'}]});
 assert.deepEqual(Array.from(sortEntriesInSeries(list,{url:'https://catalog.test/opaque',title:'Books'}),x=>x.id),['two','one']);
});
test('size labels do not invent bytes or attribute source FB2 size to an EPUB',()=>{
 const book=entry('1',1);book.acquisitions=[{url:'https://test/book.epub',type:'application/epub+zip'}];
 assert.equal(remoteSizeLabel(book),'');book.catalog_size={bytes:1572864,format:'FB2'};
 assert.equal(remoteSizeLabel(book),'FB2 · 1,5 МБ');book.acquisitions[0].size_bytes=512000;
 assert.equal(remoteSizeLabel(book),'EPUB · 500 КБ');
 for(const size of [undefined,0,-1,NaN,Infinity,'512'])assert.equal(formatFileSize(size),'');
});
