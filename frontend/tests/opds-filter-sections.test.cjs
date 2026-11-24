const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const compiled={};function load(name){if(compiled[name])return compiled[name];const exports={};const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/'+name+'.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;vm.runInNewContext(code,{exports,URL,Date,require:value=>load(value.replace('./',''))});compiled[name]=exports;return exports}
const {OpdsFilterSections}=load('opds-filter-sections'),{defaultOpdsFilters}=load('opds-filters');
const filters=extra=>({...defaultOpdsFilters,...extra});
const entry=(id,extra={})=>({id,title:'Book '+id,authors:['One'],languages:['en'],acquisitions:[{url:'https://book.test/'+id+'.epub'}],...extra});
const feed=(id,entries,extra={})=>({url:'https://books.test/opds/sequence/'+id,title:'Книги в серии '+id,entries,navigation:[],...extra});

test('only completed known series hide when every book fails current metadata filters',()=>{
 const index=new OpdsFilterSections(),onlyEnglish=feed('english',[entry('one'),entry('two')]);
 assert.equal(index.record('catalog',onlyEnglish),true);
 assert.equal(index.shouldHide('catalog',onlyEnglish.url,filters({language:'ru'})),true);
 assert.equal(index.shouldHide('catalog',onlyEnglish.url,filters({language:'en'})),false);
 assert.equal(index.shouldHide('catalog',onlyEnglish.url,filters({})),false);
 assert.equal(index.shouldHide('another',onlyEnglish.url,filters({language:'ru'})),false);
 assert.equal(index.shouldHide('catalog','https://books.test/unknown',filters({language:'ru'})),false);
 index.record('catalog',feed('mixed',[entry('one'),entry('ru',{languages:['ru']})]));
 assert.equal(index.shouldHide('catalog',feed('mixed',[]).url,filters({language:'ru'})),false);
});

test('partial, last-page-only, directory, oversized and inaccessible sections stay visible',()=>{
 const index=new OpdsFilterSections({maxEntries:2});
 const cases=[feed('next',[entry('one')],{next:'https://books.test/page2'}),feed('prev',[entry('one')],{prev:'https://books.test/page1'}),feed('directory',[entry('one')],{navigation:[{title:'Child series',url:'https://books.test/child'}]}),feed('many',[entry('1'),entry('2'),entry('3')]),feed('author',[entry('one')],{url:'https://books.test/opds/author/1',title:'Книги автора Автор'})];
 for(const item of cases){assert.equal(index.record('catalog',item),false);assert.equal(index.shouldHide('catalog',item.url,filters({language:'ru'})),false)}
 assert.equal(index.shouldHide('catalog','https://books.test/forbidden',filters({language:'ru'})),false);
 const complete=feed('complete',[entry('one')],{up:'https://books.test/authors',navigation:[{title:'Начало каталога',url:'https://books.test/opds'},{title:'Автор',url:'https://books.test/authors'}]});
 assert.equal(index.record('catalog',complete),true);assert.equal(index.shouldHide('catalog',complete.url,filters({language:'ru'})),true);
 assert.equal(index.record('catalog',{...complete,next:'https://books.test/next'}),false);assert.equal(index.shouldHide('catalog',complete.url,filters({language:'ru'})),false);
});

test('compact records retain filter semantics without copying images, summaries or acquisition URLs',()=>{
 const index=new OpdsFilterSections();const item=feed('compact',[entry('one',{title:'Book [LiTrEs]',authors:['One','two','three','four'],author_details:[{name:'Five',links:[{url:'https://secret.test/author'}]}],languages:['en-GB'],cover_url:'https://secret.test/cover',summary:'Huge summary',series:[{name:'Cycle',links:[{url:'https://secret.test/series'}]}]})]);
 index.record('catalog',item);
 assert.equal(index.shouldHide('catalog',item.url,filters({maxTwoAuthors:true})),true);assert.equal(index.shouldHide('catalog',item.url,filters({litres:'only'})),false);assert.equal(index.shouldHide('catalog',item.url,filters({litres:'exclude'})),true);assert.equal(index.shouldHide('catalog',item.url,filters({language:'en'})),false);
 const retained=JSON.stringify([...index.sections.values()]);assert.ok(!retained.includes('secret.test'));assert.ok(!retained.includes('Huge summary'));assert.ok(!retained.includes('.epub'));assert.ok(!retained.includes('four'));
 item.entries[0].title='Changed';item.entries[0].authors.length=0;item.entries[0].languages.push('ru');
 assert.equal(index.shouldHide('catalog',item.url,filters({litres:'only'})),false);assert.equal(index.shouldHide('catalog',item.url,filters({language:'ru'})),true);
});

test('LRU limits, total metadata budget and fixed expiry do not hide evicted sections',()=>{
 let now=0;const index=new OpdsFilterSections({maxSections:2,maxBooks:3,ttlMs:100,now:()=>now}),first=feed('one',[entry('one')]),second=feed('two',[entry('two')]),third=feed('three',[entry('three')]);
 index.record('catalog',first);index.record('catalog',second);index.shouldHide('catalog',first.url,filters({language:'ru'}));index.record('catalog',third);
 assert.equal(index.size,2);assert.equal(index.shouldHide('catalog',second.url,filters({language:'ru'})),false);assert.equal(index.shouldHide('catalog',first.url,filters({language:'ru'})),true);
 index.record('catalog',feed('three',[entry('a'),entry('b'),entry('c')]));assert.equal(index.size,1);assert.equal(index.shouldHide('catalog',first.url,filters({language:'ru'})),false);
 now=99;assert.equal(index.shouldHide('catalog',third.url,filters({language:'ru'})),true);now=100;assert.equal(index.shouldHide('catalog',third.url,filters({language:'ru'})),false);assert.equal(index.size,0);
});

test('empty known series and explicit title scope work, but oversized fields are never truncated into wrong decisions',()=>{
 const index=new OpdsFilterSections(),empty=feed('empty',[]),opaque=feed('opaque',[entry('one')],{url:'https://books.test/opaque',title:'Books in series Cycle'});
 index.record('catalog',empty);assert.equal(index.shouldHide('catalog',empty.url,filters({language:'ru'})),true);assert.equal(index.shouldHide('catalog',empty.url,filters({})),false);
 assert.equal(index.record('catalog',opaque),true);assert.equal(index.shouldHide('catalog',opaque.url+'#anything',filters({language:'ru'})),true);
 for(const extra of [{title:'x'.repeat(2001)+'litres'},{authors:['x'.repeat(301)]},{languages:Array.from({length:21},(_,i)=>'lang'+i)}]){const item=feed('oversized',[entry('a',extra)]);assert.equal(index.record('catalog',item),false);assert.equal(index.shouldHide('catalog',item.url,filters({language:'ru'})),false)}
 index.clear();assert.equal(index.size,0);
});
