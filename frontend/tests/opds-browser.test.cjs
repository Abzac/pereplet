const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const exportsObject={};
const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/opds-browser.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
vm.runInNewContext(code,{exports:exportsObject,URL,Date,Error});
const {OpdsHistory,downloadSection,preferredAcquisition}=exportsObject;
const location=(name,extra={})=>({url:`https://books.test/${name}`,requestUrl:`https://books.test/${name}`,requestQuery:'',query:'',scroll:0,title:name,timestamp:Date.now(),...extra});
const entry=(id,extra={})=>({id,title:id,authors:[],acquisitions:[{url:`https://books.test/${id}.epub`,type:'application/epub+zip'}],...extra});
const feed=(url,entries,next=null)=>({url,title:url,entries,navigation:[],next});
const plain=value=>JSON.parse(JSON.stringify(value));

test('EPUB and FB2 stay preferred to PDF, CBZ and TXT, including extension-only links',()=>{
 const cbz={url:'https://books.test/a.cbz',type:'application/vnd.comicbook+zip'},pdf={url:'https://books.test/a.pdf',type:'application/pdf'},fb2={url:'https://books.test/a.fb2.zip'},epub={url:'https://books.test/a.epub'};
 assert.equal(preferredAcquisition(entry('a',{acquisitions:[cbz,pdf,fb2]})),fb2);
 assert.equal(preferredAcquisition(entry('a',{acquisitions:[cbz,pdf,fb2,epub]})),epub);
});

test('accumulated page URLs survive checkpoints, bookmarks and reload without credential links',()=>{
 const history=new OpdsHistory();history.session('a','https://books.test/');history.commit('a',location('root'));
 history.checkpoint('a','query',1500,['https://books.test/2','https://books.test/3']);history.toggleBookmark('a');
 history.checkpoint('a','query',2000,['https://books.test/2','https://books.test/3','https://books.test/4']);
 const restored=new OpdsHistory(history.serialize());assert.equal(restored.current('a').pages.length,3);assert.equal(restored.bookmarks[0].pages.length,2);assert.equal(restored.current('a').scroll,2000);
 history.commit('a',location('unsafe',{pages:['https://books.test/2','https://books.test/secret?token=x']}));
 assert.deepEqual(plain(new OpdsHistory(history.serialize()).current('a').pages),['https://books.test/2']);
});

test('back to index zero preserves forward history, query and scroll',()=>{
 const history=new OpdsHistory();history.session('a','https://books.test/');
 history.commit('a',location('root'));history.checkpoint('a','draft',640);
 history.commit('a',location('author'));
 const back=history.target('a',-1);assert.equal(back.index,0);assert.equal(back.location.query,'draft');assert.equal(back.location.scroll,640);
 history.commit('a',back.location,back.index);assert.equal(history.current('a').title,'root');assert.equal(history.target('a',1).location.title,'author');
 history.commit('a',location('another'));assert.equal(history.target('a',1),null);assert.equal(history.sessions.a.trail.length,2);
});

test('catalog locations are independent and survive serialized storage',()=>{
 const history=new OpdsHistory();history.session('a','https://books.test/');history.session('b','https://other.test/');
 history.commit('a',location('search',{requestUrl:'https://books.test/search/{searchTerms}',requestQuery:'Толстой',query:'Толстой',scroll:431}));
 history.commit('b',location('series',{scroll:1200}));history.toggleBookmark('a');
 const restored=new OpdsHistory(history.serialize());assert.equal(restored.current('a').requestQuery,'Толстой');assert.equal(restored.current('a').scroll,431);assert.equal(restored.current('b').scroll,1200);assert.equal(restored.bookmarks[0].title,'search');
 restored.removeBookmark(restored.bookmarks[0]);assert.equal(restored.bookmarks.length,0);assert.equal(restored.recent.length,2);
});

test('history, bookmarks and session trails are bounded and do not store credential URLs',()=>{
 const history=new OpdsHistory();history.session('a','https://books.test/');
 for(let i=0;i<205;i++){history.commit('a',location(String(i)));history.toggleBookmark('a');}
 assert.equal(history.sessions.a.trail.length,30);assert.equal(history.recent.length,100);assert.equal(history.bookmarks.length,200);
 history.commit('a',location('unsafe',{requestUrl:'https://user:secret@books.test/'}));
 history.commit('a',location('unsafe',{requestUrl:'https://books.test/?access_token=SECRET'}));
 assert.ok(!history.serialize().includes('SECRET'));assert.ok(!history.serialize().includes('user:secret'));
 assert.equal(new OpdsHistory('{broken').recent.length,0);
});

test('checkpoint updates visible history scroll without changing saved bookmark position',()=>{
 const history=new OpdsHistory();history.session('a','https://books.test/');history.commit('a',location('root'));history.toggleBookmark('a');history.checkpoint('a','q',840);
 assert.equal(history.recent[0].scroll,840);assert.equal(history.bookmarks[0].scroll,0);
});

test('author context and local filter survive history, bookmarks and cold browser reload',()=>{
 const history=new OpdsHistory();history.session('a','https://books.test/');
 history.commit('a',location('author-books',{contextUrl:'https://books.test/author-menu',filter:'цикл'}));history.toggleBookmark('a');
 history.checkpoint('a','server query',320,['https://books.test/2'],'амбер');
 const restored=new OpdsHistory(history.serialize());assert.equal(restored.current('a').contextUrl,'https://books.test/author-menu');assert.equal(restored.current('a').filter,'амбер');assert.equal(restored.bookmarks[0].filter,'цикл');assert.equal(restored.recent[0].filter,'амбер');
 history.commit('a',location('unsafe',{contextUrl:'https://books.test/menu?token=secret',filter:'x'.repeat(600)}));const sanitized=new OpdsHistory(history.serialize()).current('a');assert.equal(sanitized.contextUrl,undefined);assert.equal(sanitized.filter.length,500);
});

test('section download follows next only, deduplicates, skips local/unsupported, continues after errors',async()=>{
 const loaded=[],downloaded=[];let active=0,peak=0;
 const first=feed('https://books.test/1',[entry('one'),entry('local',{local_book_id:'local'}),entry('scan',{acquisitions:[]})],'https://books.test/2');first.navigation=[{title:'Do not visit',url:'https://books.test/child'}];
 const result=await downloadSection(first,{load:async url=>{loaded.push(url);return feed(url,[entry('one'),entry('bad'),entry('duplicate'),entry('last')])},download:async item=>{active++;peak=Math.max(peak,active);await Promise.resolve();active--;downloaded.push(item.id);if(item.id==='bad')throw new Error('Unavailable');return {duplicate:item.id==='duplicate'}},cancelled:()=>false,progress:()=>{}});
 assert.deepEqual(loaded,['https://books.test/2']);assert.deepEqual(downloaded,['one','bad','duplicate','last']);assert.equal(peak,1);
 assert.equal(result.total,6);assert.equal(result.processed,6);assert.equal(result.downloaded,2);assert.equal(result.skipped,3);assert.equal(result.failed,1);assert.equal(result.phase,'done');
});

test('item and page caps stop traversal visibly',async()=>{
 let loads=0;const options={load:async()=>{loads++;return feed('https://books.test/2',[entry('three')],'https://books.test/3')},download:async()=>({}),cancelled:()=>false,progress:()=>{}};
 const itemLimit=await downloadSection(feed('https://books.test/1',[entry('one'),entry('two'),entry('three')]),{...options,maxItems:2});assert.equal(itemLimit.total,2);assert.equal(itemLimit.limited,true);assert.equal(loads,0);
 const pageLimit=await downloadSection(feed('https://books.test/1',[entry('one')],'https://books.test/2'),{...options,maxPages:1});assert.equal(pageLimit.pages,1);assert.equal(pageLimit.limited,true);assert.equal(loads,0);
});

test('cancellation finishes the current download and never starts the next one',async()=>{
 let cancelled=false;const downloaded=[];
 const result=await downloadSection(feed('https://books.test/1',[entry('one'),entry('two')]),{load:async()=>{throw new Error('Unexpected page')},download:async item=>{downloaded.push(item.id);cancelled=true;return {}},cancelled:()=>cancelled,progress:()=>{}});
 assert.deepEqual(downloaded,['one']);assert.equal(result.phase,'cancelled');assert.equal(result.processed,1);
});

test('redirected pagination loops and next-page failures preserve collected books',async()=>{
 const first=feed('https://books.test/1',[entry('one')],'https://books.test/2');const downloaded=[];
 const result=await downloadSection(first,{load:async()=>first,download:async item=>{downloaded.push(item.id);return {}},cancelled:()=>false,progress:()=>{}});
 assert.equal(result.failed,1);assert.deepEqual(downloaded,['one']);assert.equal(result.pages,1);
 const failed=await downloadSection(first,{load:async()=>{throw new Error('offline')},download:async()=>({}),cancelled:()=>false,progress:()=>{}});
 assert.equal(failed.failed,1);assert.equal(failed.downloaded,1);assert.ok(failed.errors[0].includes('offline'));
});

test('same acquisition under different IDs is downloaded once',async()=>{
 const original=entry('one'), alias=entry('alias',{acquisitions:original.acquisitions});let downloads=0;
 const result=await downloadSection(feed('https://books.test/1',[original,alias]),{load:async()=>null,download:async()=>{downloads++;return {}},cancelled:()=>false,progress:()=>{}});
 assert.equal(downloads,1);assert.equal(result.total,1);
});

test('cancel while collecting never starts downloads or a third page',async()=>{
 let cancelled=false,loads=0,downloads=0;
 const result=await downloadSection(feed('https://books.test/1',[entry('one')],'https://books.test/2'),{load:async()=>{loads++;cancelled=true;return feed('https://books.test/2',[entry('two')],'https://books.test/3')},download:async()=>{downloads++;return {}},cancelled:()=>cancelled,progress:()=>{}});
 assert.equal(loads,1);assert.equal(downloads,0);assert.equal(result.phase,'cancelled');
});

test('caller cannot raise hard caps above 500 books and 50 pages',async()=>{
 const options={load:async()=>null,download:async()=>({}),cancelled:()=>false,progress:()=>{}};
 const many=await downloadSection(feed('https://books.test/1',Array.from({length:501},(_,index)=>entry(String(index)))),{...options,maxItems:5000});
 assert.equal(many.total,500);assert.equal(many.limited,true);
 let page=1;
 const pages=await downloadSection(feed('https://books.test/1',[],'https://books.test/2'),{...options,maxPages:500,load:async url=>{page++;return feed(url,[],`https://books.test/${page+1}`)}});
 assert.equal(pages.pages,50);assert.equal(page,50);assert.equal(pages.limited,true);
});

test('filtered download applies predicate on every page before deduplication and never downloads exclusions',async()=>{
 const keep=entry('one',{title:'Keep one'}),sameFile=entry('alias',{title:'Keep alias',acquisitions:keep.acquisitions}),downloaded=[],loaded=[];
 const first=feed('https://books.test/1',[entry('excluded'),entry('one',{title:'Excluded alias'}),keep],'https://books.test/2');
 const result=await downloadSection(first,{include:item=>item.title.startsWith('Keep'),load:async url=>{loaded.push(url);return feed(url,[keep,sameFile,entry('two',{title:'Keep two'}),entry('no')])},download:async item=>{downloaded.push(item.id);return {}},cancelled:()=>false,progress:()=>{}});
 assert.deepEqual(loaded,['https://books.test/2']);assert.deepEqual(downloaded,['one','two']);assert.equal(result.total,2);assert.equal(result.processed,2);assert.equal(result.phase,'done');
});

test('all-filtered feeds finish empty without downloading and obey the page cap',async()=>{
 let downloads=0,loads=0;const options={include:()=>false,download:async()=>{downloads++;return {}},cancelled:()=>false,progress:()=>{}};
 const empty=await downloadSection(feed('https://books.test/1',[entry('excluded')]),{...options,load:async()=>{throw new Error('Unexpected page')}});
 assert.equal(empty.total,0);assert.equal(empty.phase,'done');assert.equal(empty.limited,false);
 const capped=await downloadSection(feed('https://books.test/1',[entry('excluded')],'https://books.test/2'),{...options,maxPages:2,load:async url=>{loads++;return feed(url,[entry('excluded2')],'https://books.test/3')}});
 assert.equal(capped.total,0);assert.equal(capped.pages,2);assert.equal(capped.limited,true);assert.equal(loads,1);assert.equal(downloads,0);
});

test('filtered item limit counts matches and collecting cancellation still prevents downloads',async()=>{
 const options={include:item=>item.title.startsWith('Keep'),download:async()=>({}),cancelled:()=>false,progress:()=>{}};
 const capped=await downloadSection(feed('https://books.test/1',[entry('excluded'),entry('one',{title:'Keep one'}),entry('two',{title:'Keep two'}),entry('three',{title:'Keep three'})]),{...options,maxItems:2,load:async()=>null});
 assert.equal(capped.total,2);assert.equal(capped.limited,true);
 let cancelled=false,downloads=0;const interrupted=await downloadSection(feed('https://books.test/1',[entry('one',{title:'Keep one'})],'https://books.test/2'),{...options,cancelled:()=>cancelled,download:async()=>{downloads++;return {}},load:async url=>{cancelled=true;return feed(url,[entry('two',{title:'Keep two'})])}});
 assert.equal(interrupted.phase,'cancelled');assert.equal(downloads,0);
});
