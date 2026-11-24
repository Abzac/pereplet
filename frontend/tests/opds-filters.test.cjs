const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
function load(name){const exportsObject={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,`../src/${name}.ts`),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsObject,URL,require:module=>load(module.replace('./',''))});return exportsObject;}
const {defaultOpdsFilters,normalizeOpdsFilters,activeOpdsFilterCount,matchesOpdsFilters,opdsAuthorCount,groupOpdsSeries}=load('opds-filters');
const entry=value=>({id:'b',title:'Book',authors:[],acquisitions:[],...value});
const filters=value=>({...defaultOpdsFilters,...value});
test('author limit deduplicates metadata names and allows missing authors without guessing anthology status',()=>{
 const same=entry({authors:['First',' SECOND ','first'],author_details:[{name:'Second'}]});assert.equal(opdsAuthorCount(same),2);assert.ok(matchesOpdsFilters(same,filters({maxTwoAuthors:true})));
 assert.ok(!matchesOpdsFilters(entry({authors:['One','Two','Three']}),filters({maxTwoAuthors:true})));
 assert.ok(matchesOpdsFilters(entry({}),filters({maxTwoAuthors:true})));
});
test('language filters support BCP47 tags and ISO aliases with honest unknown handling',()=>{
 for(const language of ['ru','RU-ru','ru_RU','rus'])assert.ok(matchesOpdsFilters(entry({languages:[language]}),filters({language:'ru'})));
 for(const language of ['en','EN-us','en_GB','eng'])assert.ok(matchesOpdsFilters(entry({languages:[language]}),filters({language:'en'})));
 assert.ok(!matchesOpdsFilters(entry({}),filters({language:'ru'})));assert.ok(!matchesOpdsFilters(entry({languages:['pl']}),filters({language:'en'})));
 for(const languages of [undefined,[],['und'],['ru'],['en'],['de','en']])assert.ok(matchesOpdsFilters(entry({languages}),filters({language:'ru-en-unknown'})));
 assert.ok(!matchesOpdsFilters(entry({languages:['pl','de']}),filters({language:'ru-en-unknown'})));
});
test('litres is the requested literal substring, independent from language and author filters',()=>{
 const withMark=entry({title:'Book [LiTrEs]',languages:['en'],authors:['One','Two','Three']});
 assert.ok(matchesOpdsFilters(withMark,filters({litres:'only'})));assert.ok(!matchesOpdsFilters(withMark,filters({litres:'exclude'})));assert.ok(!matchesOpdsFilters(withMark,filters({litres:'only',maxTwoAuthors:true})));
 assert.ok(!matchesOpdsFilters(entry({title:'Книга [Литрес]'}),filters({litres:'only'})));assert.ok(matchesOpdsFilters(entry({title:'nolITresuffix'}),filters({litres:'only'})));
});
test('saved filters are normalized and active count reflects independent criteria',()=>{
 assert.equal(activeOpdsFilterCount(filters({})),0);assert.equal(activeOpdsFilterCount(filters({maxTwoAuthors:true,language:'ru-en-unknown',litres:'exclude'})),3);
 assert.equal(JSON.stringify(normalizeOpdsFilters(null)),JSON.stringify(defaultOpdsFilters));assert.equal(JSON.stringify(normalizeOpdsFilters({language:'pl',litres:'maybe',maxTwoAuthors:'yes'})),JSON.stringify(defaultOpdsFilters));
 assert.equal(JSON.stringify(normalizeOpdsFilters({language:'en',maxTwoAuthors:true,other:'ignored'})),JSON.stringify(filters({language:'en',maxTwoAuthors:true})));
});
test('groups contain only filtered publications, use one primary series and keep unknown numbers last',()=>{
 const books=[entry({id:'ten',series:[{name:'Цикл',position:10}]}),entry({id:'none'}),entry({id:'unknown',series:[{name:'цикл'}]}),entry({id:'two',series:[{name:'Цикл',position:2},{name:'Другой',position:1}]}),entry({id:'filtered',languages:['pl'],series:[{name:'Пустая серия',position:1}]})];
 const groups=groupOpdsSeries(books.filter(book=>matchesOpdsFilters(book,filters({language:'ru-en-unknown'}))));
 assert.deepEqual(Array.from(groups,group=>group.name),['Цикл','']);assert.deepEqual(Array.from(groups[0].entries,book=>book.id),['two','ten','unknown']);assert.equal(groups.flatMap(group=>Array.from(group.entries)).length,4);assert.deepEqual(Array.from(groupOpdsSeries([])),[]);
 assert.deepEqual(books.map(book=>book.id),['ten','none','unknown','two','filtered']);
});
