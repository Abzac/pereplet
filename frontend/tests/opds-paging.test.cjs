const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const exportsObject={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/opds-paging.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsObject,URL,Error,structuredClone});
const {OpdsPages,OpdsPageStore,restorePages}=exportsObject;
const url=n=>`https://books.test/page/${n}`;
const entry=(id,extra={})=>({id,title:id,authors:[],acquisitions:[{url:`https://books.test/${id}.epub`}],...extra});
const feed=(n,entries=[entry(String(n))],extra={})=>({url:url(n),title:`Page ${n}`,entries,navigation:[],next:url(n+1),prev:n>1?url(n-1):null,...extra});

test('append retains section identity and previous-before-first, next-after-last pagination',()=>{
 const pages=new OpdsPages(feed(1));
 assert.equal(pages.previous,null); assert.equal(pages.append(url(2),feed(2)),true);
 assert.equal(pages.feed.url,url(1));assert.equal(pages.feed.title,'Page 1');assert.equal(pages.feed.next,url(3));assert.equal(pages.previous,null);assert.equal(pages.feed.entries.length,2);
 assert.deepEqual(Array.from(pages.requests),[url(2)]);
});
test('directory accumulation never offers a previous page already visible; middle-page starts preserve real previous',()=>{
 const directory=n=>feed(n,[],{navigation:[{title:`Series ${n}`,url:`https://books.test/series/${n}`}],next:n<3?url(n+1):null});
 const pages=new OpdsPages(directory(1));pages.append(url(2),directory(2));pages.append(url(3),directory(3));
 assert.equal(pages.feed.navigation.length,3);assert.equal(pages.previous,null);assert.equal(pages.feed.next,null);
 const legacy=pages.snapshot();legacy.previous=url(2);assert.equal(OpdsPages.restore(legacy).previous,null);
 const middle=new OpdsPages(directory(2));middle.append(url(3),directory(3));assert.equal(middle.previous,url(1));
});
test('deduplication uses any acquisition, IDs and navigation URLs and preserves local markers',()=>{
 const first=entry('a'),second=entry('b',{acquisitions:[{url:'https://books.test/other.pdf'},{url:first.acquisitions[0].url}],local_book_id:'local'});
 const pages=new OpdsPages(feed(1,[first],{navigation:[{title:'Author',url:'https://books.test/author'}]}));
 pages.append(url(2),feed(2,[second,entry('c')],{navigation:[{title:'Author duplicate',url:'https://books.test/author'},{title:'Series',url:'https://books.test/series'}]}));
 assert.equal(pages.feed.entries.length,2);assert.equal(pages.feed.entries[0].local_book_id,'local');assert.equal(pages.feed.navigation.length,2);
});
test('wrong pending URL and final URL loop never alter the visible section',()=>{
 const pages=new OpdsPages(feed(1));
 assert.equal(pages.append(url(99),feed(99)),false);
 assert.throws(()=>pages.append(url(2),feed(1)),/повторил страницу/);
 assert.equal(pages.pageCount,1);assert.equal(pages.feed.entries.length,1);assert.equal(pages.feed.next,url(2));
 assert.throws(()=>pages.append(url(2),feed(1,[],{url:url(1)+'#different'})),/повторил страницу/);
});
test('later supported acquisition repairs an earlier unsupported duplicate',()=>{
 const pages=new OpdsPages(feed(1,[entry('a',{acquisitions:[],unavailable_reason:'Только DJVU'})]));
 pages.append(url(2),feed(2,[entry('a')]));assert.equal(pages.feed.entries.length,1);assert.equal(pages.feed.entries[0].acquisitions.length,1);assert.equal(pages.feed.entries[0].unavailable_reason,undefined);
});
test('auto and hard page caps leave explicit next available',()=>{
 const pages=new OpdsPages(feed(1));for(let n=2;n<=10;n++)pages.append(url(n),feed(n));
 assert.equal(pages.canAutoAppend,false);assert.equal(pages.canAppend,true);
 for(let n=11;n<=20;n++)pages.append(url(n),feed(n));
 assert.equal(pages.canAppend,false);assert.equal(pages.feed.next,url(21));assert.equal(pages.append(url(21),feed(21)),false);
});
test('item budget never drops part of a page; a large initial page stays intact',()=>{
 const pages=new OpdsPages(feed(1,Array.from({length:590},(_,n)=>entry(String(n)))));
 assert.equal(pages.append(url(2),feed(2,Array.from({length:20},(_,n)=>entry(String(n+590))))),false);
 assert.equal(pages.feed.entries.length,590);assert.equal(pages.feed.next,url(2));assert.equal(pages.limited,true);
 const large=new OpdsPages(feed(1,Array.from({length:700},(_,n)=>entry(String(n)))));assert.equal(large.feed.entries.length,700);
});
test('saved pages replay actual next links, never old arbitrary URLs, and failures stay atomic',async()=>{
 const calls=[];const pages=await restorePages(feed(1),['https://old.test/2','https://old.test/3'],async u=>{calls.push(u);return feed(Number(u.split('/').at(-1)))});
 assert.deepEqual(calls,[url(2),url(3)]);assert.equal(pages.pageCount,3);
 const first=feed(1);await assert.rejects(restorePages(first,[url(2)],async()=>{throw new Error('offline')}),/offline/);assert.equal(first.entries.length,1);
});
test('optional restore error handler preserves earlier pages and leaves failed next available to retry',async()=>{
 const first=feed(1),failure=new Error('third page offline'),errors=[],calls=[];
 const pages=await restorePages(first,[url(2),url(3)],async u=>{calls.push(u);if(u===url(3))throw failure;return feed(2)},error=>errors.push(error));
 assert.deepEqual(calls,[url(2),url(3)]);assert.deepEqual(errors,[failure]);
 assert.equal(pages.pageCount,2);assert.equal(pages.feed.entries.length,2);assert.equal(pages.feed.next,url(3));
 assert.deepEqual(Array.from(pages.requests),[url(2)]);assert.equal(first.entries.length,1);assert.equal(pages.canAppend,true);
 assert.equal(pages.append(url(3),feed(3,undefined,{next:null})),true);assert.equal(pages.pageCount,3);assert.equal(pages.feed.next,null);
});
test('optional restore error handler never swallows cancellation',async()=>{
 const aborted=Object.assign(new Error('navigation cancelled'),{name:'AbortError'}),errors=[];
 await assert.rejects(restorePages(feed(1),[url(2),url(3)],async u=>{if(u===url(3))throw aborted;return feed(2)},error=>errors.push(error)),error=>error===aborted);
 assert.deepEqual(errors,[]);
});
test('snapshot store is isolated, bounded and requires the exact saved page set',()=>{
 const store=new OpdsPageStore(),pages=new OpdsPages(feed(1));pages.append(url(2),feed(2));store.save('a',pages);
 assert.equal(store.read('a',url(1),[]),null);assert.equal(store.read('b',url(1),[url(2)]),null);
 const restored=store.read('a',url(1),[url(2)]);restored.append(url(3),feed(3));assert.equal(store.read('a',url(1),[url(2)]).pageCount,2);
 store.update(f=>({...f,entries:f.entries.map(e=>({...e,local_book_id:'local'}))}));assert.equal(store.read('a',url(1),[url(2)]).feed.entries[0].local_book_id,'local');
 for(let n=2;n<=4;n++)store.save('a',new OpdsPages(feed(n)));assert.equal(store.read('a',url(1),[url(2)]),null);
});
