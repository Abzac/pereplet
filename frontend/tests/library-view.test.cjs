const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const modules=new Map();function moduleOf(name){if(modules.has(name))return modules.get(name);const exports={};modules.set(name,exports);vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,`../src/${name}.ts`),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,URL,require:id=>moduleOf(id.replace(/^\.\//,''))});return exports}
const {filterLibrary,libraryFacets,groupLibraryBySeries}=moduleOf('library-view');
const plain=value=>JSON.parse(JSON.stringify(value)),ids=values=>Array.from(values,book=>book.id);
const book=(id,author,series,status='unread',extra={})=>({id,title:id,authors:[author],author,series,status,format:'FB2',...extra});
const books=[book('cycle-two','Автор А','Цикл 2','reading',{series_index:2}),book('cycle-ten','Автор А','Цикл 2','planned',{series_index:10}),book('solo','Автор А','','read'),book('other','Автор Б','Другая','unread'),book('shared','Автор А','Общая','reading',{authors:['Автор А','Автор Б']}),book('comic','Автор А','Комиксы','reading',{format:'CBZ'}),book('archived','Автор А','Архивная','reading',{archived:true})];

test('literal top and current-list queries compose without escaping the author scope',()=>{
 const list=[book('one','Фёдор Автор','Большой цикл','reading',{title:'Ёжик   и море'}),book('two','Другой','Большой цикл','reading',{title:'Ёжик и море'}),book('three','Фёдор Автор','Другой цикл','reading',{title:'Лес'})];
 assert.deepEqual(ids(filterLibrary(list,{view:'library',query:'ЦИКЛ',localQuery:'ежик и',author:'Федор Автор'})),['one']);
 assert.deepEqual(ids(filterLibrary(list,{localQuery:'[ёжик]'})),[]);
 assert.equal(list[0].title,'Ёжик   и море');
});

test('scope separates books/comics/archive and shared statuses include canonical legacy aliases',()=>{
 assert.deepEqual(ids(filterLibrary(books,{view:'library'})),['cycle-two','cycle-ten','solo','other','shared']);
 assert.deepEqual(ids(filterLibrary(books,{view:'comics'})),['comic']);
 assert.deepEqual(ids(filterLibrary(books,{view:'archive'})),['archived']);
 assert.deepEqual(ids(filterLibrary(books,{view:'reading'})),['cycle-two','shared','comic']);
 const legacy=[book('old-read','Автор','','finished'),book('old-plan','Автор','','want'),book('current-read','Автор','','read')];
 assert.deepEqual(ids(filterLibrary(legacy,{view:'read'})),['old-read','current-read']);
 assert.deepEqual(ids(filterLibrary(legacy,{view:'planned'})),['old-plan']);
});

test('series facet contains only the selected author and keeps alternate series when its own filter is set',()=>{
 const result=libraryFacets(books,{view:'library',author:'Автор А',series:'Цикл 2'});
 assert.deepEqual(plain(result.series),['Общая','Цикл 2']);assert.equal(result.hasNoSeries,true);assert.ok(!result.series.includes('Другая'));
 assert.deepEqual(plain(result.statuses),['reading','planned']);
});

test('author and status facets obey other active facets, including coauthored books and current substring',()=>{
 const shared=libraryFacets(books,{view:'library',author:'Автор А',series:'Общая'});
 assert.deepEqual(plain(shared.authors),['Автор А','Автор Б']);assert.deepEqual(plain(shared.statuses),['reading']);
 const local=libraryFacets(books,{view:'library',author:'Автор А',localQuery:'solo'});
 assert.deepEqual(plain(local.series),[]);assert.equal(local.hasNoSeries,true);assert.deepEqual(plain(local.statuses),['read']);
 const reading=libraryFacets(books,{view:'reading',status:'read'});
 assert.deepEqual(plain(reading.statuses),['reading']);
});

test('facets do not reintroduce unrelated or archived metadata and empty combinations stay empty',()=>{
 const result=libraryFacets(books,{view:'library',author:'Автор Б',status:'planned'});
 assert.deepEqual(plain(result.series),[]);assert.equal(result.hasNoSeries,false);
 assert.deepEqual(ids(filterLibrary(books,{view:'library',author:'Автор Б',series:'Цикл 2'})),[]);
 assert.equal(libraryFacets(books,{view:'library'}).series.includes('Архивная'),false);
});

test('valid selections retain their imported spelling; letters include a secondary author',()=>{
 const list=[book('one','Фёдор Автор','Серия','reading'),book('two','Федор Автор','серия','unread'),book('coauthor','Другой','Общая','reading',{authors:['Другой','Фёдор Автор']})];
 const result=libraryFacets(list,{author:'Федор Автор',series:'серия'});
 assert.deepEqual(plain(result.authors),['Федор Автор']);assert.ok(result.series.includes('серия'));
 assert.deepEqual(ids(filterLibrary(list,{letter:'Ф'})),['one','two','coauthor']);
});

test('filtered grouping hides empty series, orders numeric positions and leaves unknown positions stable',()=>{
 const input=[book('unknown-a','Автор','Цикл 2'),book('ten','Автор','Цикл 2','reading',{series_index:10}),book('half','Автор','Цикл 2','reading',{series_index:'2,5'}),book('zero','Автор','Цикл 2','reading',{series_index:0}),book('two','Автор','Цикл 2','reading',{series_index:2}),book('unknown-b','Автор','Цикл 2'),book('blank','Автор',''),book('cycle10','Автор','Цикл 10'),book('other','Другой','Нет в выборке')];
 const before=ids(input);const groups=groupLibraryBySeries(filterLibrary(input,{author:'Автор'}));
 assert.deepEqual(Array.from(groups,g=>g.name),['Цикл 2','Цикл 10','']);
 assert.deepEqual(ids(groups[0].books),['zero','two','half','ten','unknown-a','unknown-b']);
 assert.equal(groups.at(-1).key,'__no_series__');assert.deepEqual(ids(input),before);
 assert.deepEqual(plain(groupLibraryBySeries([])),[]);
});

test('ungrouped filtering and the no-series group retain caller ordering',()=>{
 const input=[book('z','Автор',''),book('a','Автор',''),book('m','Автор','Цикл')];
 assert.deepEqual(ids(filterLibrary(input,{series:'__no_series__'})),['z','a']);
 assert.deepEqual(ids(groupLibraryBySeries(input).at(-1).books),['z','a']);
});
