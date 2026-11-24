const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const exportsObject={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/library-scope.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsObject});
const {mediaType,booksForView,buildSeriesDirectory}=exportsObject;
const plain=value=>JSON.parse(JSON.stringify(value));
const books=[{id:'novel',format:'epub',series:'Общее имя'},{id:'scan',format:'pdf',series:'Книжная серия'},{id:'comic1',format:'cbz',series:'Общее имя'},{id:'comic2',format:'CBR',series:'Общее имя'},{id:'comic3',format:'cbz'}];

test('old CBZ/CBR metadata defaults to comics and PDF to books',()=>{
 assert.equal(mediaType({format:'cbz'}),'comic');assert.equal(mediaType({format:'CBR'}),'comic');assert.equal(mediaType({format:'pdf'}),'book');assert.equal(mediaType({format:'epub'}),'book');
});
test('book and comic sections and series never mix even with equal series names',()=>{
 for(const view of ['library','authors','series'])assert.deepEqual(plain(booksForView(books,view).map(b=>b.id)),['novel','scan']);
 for(const view of ['comics','comic-series'])assert.deepEqual(plain(booksForView(books,view).map(b=>b.id)),['comic1','comic2','comic3']);
 const bookSeries=buildSeriesDirectory(booksForView(books,'series')),comicSeries=buildSeriesDirectory(booksForView(books,'comic-series'));
 assert.equal(bookSeries.find(s=>s.name==='Общее имя').count,1);assert.equal(comicSeries.find(s=>s.name==='Общее имя').count,2);assert.equal(comicSeries.some(s=>s.name==='Книжная серия'),false);assert.equal(comicSeries.find(s=>s.key==='__no_series__').count,1);
});
test('manual PDF comic choice moves its series without altering reading state',()=>{
 const pdf={id:'pdf',format:'pdf',series:'Новая серия',progress:35,chapter:8,locator:{page:8},media_type:'comic'};
 assert.equal(mediaType(pdf),'comic');assert.equal(booksForView([pdf],'library').length,0);assert.equal(booksForView([pdf],'comics')[0],pdf);assert.equal(buildSeriesDirectory(booksForView([pdf],'comic-series'))[0].name,'Новая серия');
 assert.equal(pdf.progress,35);assert.equal(pdf.locator.page,8);assert.equal(mediaType({...pdf,media_type:'book'}),'book');assert.equal(mediaType({format:'cbz',media_type:'book'}),'book');
});
test('reading, planned and read remain shared collections',()=>{
 for(const view of ['reading','planned','read'])assert.equal(booksForView(books,view),books);
});
test('archive holds both media types and hides them from all active views and series counts',()=>{
 const items=[...books,{id:'archived-book',format:'fb2',archived:true,series:'Archived only',status:'planned'},{id:'archived-pdf',format:'pdf',media_type:'comic',archived:true,series:'Общее имя',status:'reading'}];
 assert.deepEqual(plain(booksForView(items,'archive').map(b=>b.id)),['archived-book','archived-pdf']);
 for(const view of ['library','authors','series','comics','comic-series','reading','planned','read'])assert.ok(booksForView(items,view).every(b=>!b.archived));
 assert.equal(buildSeriesDirectory(booksForView(items,'series')).some(s=>s.name==='Archived only'),false);
 assert.equal(buildSeriesDirectory(booksForView(items,'comic-series')).find(s=>s.name==='Общее имя').count,2);
});
test('restoring an archived PDF returns it to its explicit media type without changing reading state',()=>{
 const archived={id:'pdf',format:'pdf',media_type:'comic',archived:true,progress:40,chapter:7,status:'reading',locator:{page:7}};
 const restored={...archived,archived:false};
 assert.equal(booksForView([restored],'archive').length,0);assert.equal(booksForView([restored],'comics')[0],restored);assert.equal(booksForView([restored],'library').length,0);
 assert.equal(restored.progress,archived.progress);assert.equal(restored.locator,archived.locator);
});
