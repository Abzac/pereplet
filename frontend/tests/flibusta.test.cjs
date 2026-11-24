const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/flibusta.ts'),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const helpers={};vm.runInNewContext(code,{exports:helpers,URL});
const {isFlibustaCatalog,flibustaTabs,flibustaNavigation,getFeedArea,resolveFlibustaTab,resolveFlibustaAuthor,resolveFlibustaFeed,searchFlibusta}=helpers;
const plain=value=>JSON.parse(JSON.stringify(value));
const base='https://flibusta.is';
const nav=(title,url)=>({title,url:base+url});
const feed=(url,title='Feed',navigation=[],entries=[])=>({url:base+url,title,navigation,entries});
const root=()=>({...feed('/opds','Flibusta catalog',[
 nav('Начало каталога','/opds'),nav('Новинки','/published-news?version=2'),
 nav('По авторам','/published-authors'),nav('По сериям','/published-series'),
 nav('По жанрам','/published-genres'),nav('Моя полка','/private-books'),
 ]),search:{url:base+'/opds/search?searchTerm={searchTerms}',type:'application/atom+xml'}});

test('recognition requires a Flibusta host or a same-host identifying root feed',()=>{
 assert.equal(isFlibustaCatalog('http://flibusta.is/opds'),true);
 assert.equal(isFlibustaCatalog('https://www.flibusta.site/opds'),true);
 assert.equal(isFlibustaCatalog('https://flibusta.is.attacker.example/opds'),false);
 assert.equal(isFlibustaCatalog('javascript:alert(1)'),false);
 assert.equal(isFlibustaCatalog('https://mirror.example/catalog',{...root(),url:'https://mirror.example/catalog'}),true);
 assert.equal(isFlibustaCatalog('https://another.example/catalog',root()),false);
});

test('root tabs use only unambiguous published URLs, even when routes change',()=>{
 const source=root();
 assert.deepEqual(plain(flibustaTabs(source)),[
  {id:'new',label:'Новинки',url:base+'/published-news?version=2'},
  {id:'authors',label:'Авторы',url:base+'/published-authors'},
  {id:'series',label:'Серии',url:base+'/published-series'},
  {id:'genres',label:'Жанры',url:base+'/published-genres'},
 ]);
 source.navigation.push(nav('Авторы','/ambiguous-authors'));
 assert.equal(flibustaTabs(source).some(tab=>tab.id==='authors'),false);
 assert.deepEqual(plain(flibustaTabs(feed('/other','Other',[]))),[]);
});

test('navigation removes root, parent, self and duplicates while preserving real choices and roles',()=>{
 const source=feed('/opds/search?searchType=authors','Результат поиска',[
 nav('Начало каталога','/opds'),nav('На уровень выше','/opds/search'),
 nav('This page','/opds/search?searchType=authors'),nav('Пратчетт Терри','/opds/author/19740'),
 nav('Пратчетт Терри duplicate','/opds/author/19740'),nav('А','/opds/authorsindex/%D0%90'),
 ]);
 source.up=base+'/opds/search';
 assert.deepEqual(plain(flibustaNavigation(source,root())),[
  {...nav('Пратчетт Терри','/opds/author/19740'),role:'author'},
  {...nav('А','/opds/authorsindex/%D0%90'),role:'alphabet'},
 ]);
});

test('feed areas distinguish author choices, author results, series indexes and server search',()=>{
 assert.equal(getFeedArea(feed('/opds/author/19740','Книги автора Пратчетт Терри')),'author');
 assert.equal(getFeedArea(feed('/opds/author/19740/alphabet','Книги по алфавиту')),'author');
 assert.equal(getFeedArea(feed('/opds/search?searchType=authors&searchTerm=x')),'authors');
 assert.equal(getFeedArea(feed('/opds/authorsequences/19740','Книжные серии Пратчетт Терри')),'series');
 assert.equal(getFeedArea(feed('/opds/authorsequence/19740/35124')),'books');
 assert.equal(getFeedArea(feed('/published-genres'),root()),'genres');
});

test('news tab skips the published all-news service page and returns the final actual URL',async()=>{
 const calls=[],tab=flibustaTabs(root())[0];
 const menu=feed('/published-news?version=2','Новинки',[
  nav('Все новинки','/actual-news?date=2026'),nav('По жанрам','/news-genres'),
 ]);
 const result=feed('/actual-news?date=2026','Новинки',[],[{id:'book'}]);
 const loaded=await resolveFlibustaTab(tab,async url=>{calls.push(url);return calls.length===1?menu:result});
 assert.deepEqual(calls,[tab.url,base+'/actual-news?date=2026']);assert.equal(loaded.url,result.url);
});

test('selected author opens the real alphabet book list and preserves the author and series menu',async()=>{
 const menu=feed('/opds/author/19740','Книги автора Пратчетт Терри',[
  nav('Начало каталога','/opds'),nav('Книги по сериям','/opds/authorsequences/19740'),
  nav('Книги вне серий','/opds/author/19740/authorsequenceless'),
  nav('Книги по алфавиту','/opds/author/19740/alphabet'),
  nav('Книги по дате поступления','/opds/author/19740/time'),
 ]);
 const before=JSON.stringify(menu),calls=[];
 const result=await resolveFlibustaAuthor(menu,async url=>{calls.push(url);return feed('/opds/author/19740/alphabet','Книги по алфавиту',[nav('Начало каталога','/opds')],[{id:'book'}])});
 assert.deepEqual(calls,[base+'/opds/author/19740/alphabet']);
 assert.equal(result.title,menu.title);assert.equal(result.url,calls[0]);
 assert.equal(result.context_url,menu.url);
 assert.ok(result.navigation.some(link=>link.title==='Книги по сериям'));
 assert.equal(result.navigation.some(link=>link.url===result.url),false);
 assert.equal(JSON.stringify(menu),before,'input is immutable');
});

test('ambiguous author choices, actual books and alphabet directories are not auto-followed',async()=>{
 const forbidden=async()=>{throw new Error('unexpected request')};
 const ambiguous=feed('/opds/author/1','Книги автора A',[nav('Все книги автора','/one'),nav('Все книги автора','/two')]);
 assert.equal(await resolveFlibustaAuthor(ambiguous,forbidden),ambiguous);
 const books=feed('/opds/author/1','Книги автора A',[nav('Книги по алфавиту','/alphabet')],[{id:'book'}]);
 assert.equal(await resolveFlibustaAuthor(books,forbidden),books);
 const alphabet=feed('/opds/authorsindex','Авторы',[nav('А','/opds/authorsindex/A')]);
 assert.equal(await resolveFlibustaFeed(alphabet,forbidden),alphabet);
});

test('series service menu collapses only when its sole actual choice is all books',async()=>{
 const source=feed('/opds/sequences/series','Серия',[nav('Начало каталога','/opds'),nav('Все книги серии','/real-series-books')]);
 const calls=[];
 const result=await resolveFlibustaFeed(source,async url=>{calls.push(url);return feed('/real-series-books','Books',[],[{id:'b'}])});
 assert.deepEqual(calls,[base+'/real-series-books']);assert.equal(result.url,calls[0]);
 const choices={...source,navigation:[...source.navigation,nav('Порядок чтения','/order')]};
 assert.equal(await resolveFlibustaFeed(choices,async()=>{throw new Error('choice must stay')}),choices);
});

test('author search calls the root raw template once and follows the observed scoped link',async()=>{
 const calls=[],scope=base+'/found-authors?term=%D1%91%D0%B6&scope=writer';
 const searchResult=feed('/opds/search?searchTerm=encoded','Результат поиска',[
  {title:'Поиск авторов',url:scope},nav('Поиск книг','/found-books'),
 ]);
 const authors=feed('/found-authors?term=encoded','Результат поиска',[nav('Ёжиков Алексей','/opds/author/42')]);
 const result=await searchFlibusta(root(),'authors','ёж & ёлка',async(url,query)=>{calls.push({url,query});return calls.length===1?searchResult:authors});
 assert.deepEqual(calls,[{url:root().search.url,query:'ёж & ёлка'},{url:scope,query:undefined}]);
 assert.equal(result,authors);
});

test('missing series search reports unsupported without inventing another endpoint',async()=>{
 const calls=[];
 await assert.rejects(searchFlibusta(root(),'series','Плоский мир',async(url,query)=>{
  calls.push({url,query});return feed('/opds/search','Результат поиска',[nav('Поиск авторов','/actual-authors'),nav('Поиск книг','/actual-books')]);
 }),error=>error.name==='FlibustaSearchUnavailable'&&error.message.includes('поиск по сериям'));
 assert.equal(calls.length,1);
});

test('already scoped empty book search remains a valid empty result',async()=>{
 const empty=feed('/opds/search?searchType=books&searchTerm=none','Результат поиска');
 const result=await searchFlibusta(root(),'books','none',async()=>empty);
 assert.equal(result,empty);
});

test('history resume restores the published author menu without replacing accumulated books',async()=>{
 const source=feed('/opds/author/42/alphabet','Книги по алфавиту',[],[{id:'b'}]);source.next=base+'/page2';
 const menu=feed('/opds/author/42','Книги автора Автор',[nav('Книги по сериям','/opds/authorsequences/42'),nav('Книги по алфавиту','/opds/author/42/alphabet')]);
 const calls=[];const result=await helpers.restoreFlibustaContext(source,async url=>{calls.push(url);return menu},menu.url);
 assert.deepEqual(calls,[menu.url]);assert.equal(result.url,source.url);assert.equal(result.next,source.next);assert.equal(result.entries,source.entries);assert.equal(result.navigation.length,1);assert.equal(result.context_url,menu.url);
 const again=await helpers.restoreFlibustaContext(result,async()=>{throw Error('already restored')},menu.url);assert.equal(again,result);
});
test('legacy author history recovers from the entry related link, not a constructed endpoint',async()=>{
 const source=feed('/opds/author/42/alphabet','Книги по алфавиту',[],[{id:'b',related_links:[{url:base+'/opds/author/7',title:'Соавтор'},{url:base+'/opds/author/42',title:'Все книги автора Автор'}]}]);
 const calls=[];const result=await helpers.restoreFlibustaContext(source,async url=>{calls.push(url);return feed('/opds/author/42','Книги автора Автор',[nav('Книги по сериям','/series42')])});
 assert.deepEqual(calls,[base+'/opds/author/42']);assert.ok(result.navigation.some(link=>link.url.endsWith('/series42')));
 const noLinks={...source,entries:[{id:'b'}]};assert.equal(await helpers.restoreFlibustaContext(noLinks,async()=>{throw Error('must not guess')}),noLinks);
});
test('menu failure keeps books, and foreign context URLs are never requested',async()=>{
 const source=feed('/opds/author/42/alphabet','Книги по алфавиту',[],[{id:'b'}]);
 const result=await helpers.restoreFlibustaContext(source,async()=>{throw Error('offline')},base+'/opds/author/42');assert.equal(result.entries,source.entries);assert.equal(result.context_url,base+'/opds/author/42');
 assert.equal(await helpers.restoreFlibustaContext(source,async()=>{throw Error('foreign request')},'https://other.example/menu'),source);
});
test('author series directory keeps its own title and entries while recovering author actions',async()=>{
 const source=feed('/opds/authorsequences/42','Книжные серии Автора',[nav('Цикл А','/opds/authorsequence/42/1')]);
 const result=await helpers.restoreFlibustaContext(source,async()=>feed('/opds/author/42','Книги автора Автор',[nav('Книги по сериям','/opds/authorsequences/42'),nav('Книги вне серий','/opds/author/42/without')]),base+'/opds/author/42');
 assert.equal(result.title,source.title);assert.equal(result.context_url,base+'/opds/author/42');assert.ok(result.navigation.some(link=>link.title==='Цикл А'));assert.ok(result.navigation.some(link=>link.title==='Книги вне серий'));assert.equal(result.navigation.some(link=>link.url===source.url),false);
});

test('author full names fall back to a term and match every name token regardless of order',async()=>{
 for(const query of ['Терри Пратчетт','Пратчетт Терри','Terry Pratchett','Роулинг Джоан','Джоан Роулинг']){
  const calls=[];
  const load=async(url,q)=>{calls.push(q);return {...feed('/opds/search?searchType=authors'),navigation:q?.includes(' ')?[]:[nav('Пратчетт Терри','/opds/author/1'),nav('Роулинг Джоан','/opds/author/2'),nav('Роулинг Марджори','/opds/author/3')]}};
  const result=await searchFlibusta(root(),'authors',query,load);
  assert.equal(result.navigation.length,1);
  assert.equal(result.navigation[0].title,query.includes('Роулинг')?'Роулинг Джоан':'Пратчетт Терри');
  assert.equal(calls.length,2);
 }
});
test('combined search retains one successful section if the other fails',async()=>{
 const load=async(url,q)=>{if(url.endsWith('/authors'))throw Error('author service unavailable');if(url.endsWith('/books'))return feed('/opds/search?searchType=books','Books',[],[{id:'1',title:'Book'}]);return feed('/search','Search',[nav('Поиск авторов','/authors'),nav('Поиск книг','/books')])};
 const result=await helpers.searchFlibustaBoth(root(),'authors','Имя',load);
 assert.equal(result.search_results.books.entries.length,1);
 assert.match(result.search_results.authors_error,/unavailable/);
 assert.equal(result.search_results.authors,null);
});
