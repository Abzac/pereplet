const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/opds-cache.ts'), 'utf8');
const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exportsForTest = {};
vm.runInNewContext(code, {exports: exportsForTest, URL, AbortController, structuredClone, setTimeout, clearTimeout});
const {OpdsCache, opdsCacheKey} = exportsForTest;
const delay = (ms = 5) => new Promise(resolve => setTimeout(resolve, ms));
const url = name => `https://books.example/${name}`;
const feed = (name, query = '') => ({title:`${name} ${query}`,url:url(name),entries:[{id:name,title:name,authors:['Author'],summary:'Description',acquisitions:[{url:url(`${name}.epub`),type:'application/epub+zip'}]}],navigation:[],next:null,search:null});
function deferredLoader({abort = false} = {}) {
 const requests = [];
 const loader = (target, query, signal) => new Promise((resolve, reject) => {
  const request = {url:target,query,signal,resolve,reject};requests.push(request);
  if (abort) signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'),{name:'AbortError'})), {once:true});
 });
 return {loader,requests};
}

test('canonical URL and captured query coalesce requests without sharing mutable feeds', async () => {
 const {loader,requests}=deferredLoader();
 const cache=new OpdsCache(loader);
 const a=cache.get('https://BOOKS.example:443/catalog#first','ёж');
 const b=cache.get('https://books.example/catalog#second','ёж');
 assert.equal(requests.length,1);
 assert.equal(requests[0].url,'https://BOOKS.example:443/catalog#first');
 assert.equal(requests[0].query,'ёж');
 requests[0].resolve(feed('catalog','ёж'));
 const [first,second]=await Promise.all([a,b]);
 first.entries[0].title='Changed';
 assert.equal(second.entries[0].title,'catalog');
 assert.equal(cache.readSnapshot(url('catalog'),'ёж').entries[0].title,'catalog');
 assert.notEqual(opdsCacheKey(url('catalog'),'ёж'),opdsCacheKey(url('catalog'),'ёлка'));
 cache.dispose();
});

test('raw path search templates and captured queries reach foreground and prefetch loaders verbatim', async () => {
 const {loader,requests}=deferredLoader();
 const cache=new OpdsCache(loader,{prefetchDelayMs:0});
 const template='https://books.example/search/{searchTerms}?author={atom:author}';
 const query='ёж & ёлка';
 const pending=cache.get(template,query);
 assert.equal(requests[0].url,template);assert.equal(requests[0].query,query);
 requests[0].resolve(feed('search',query));await pending;
 const hoverTemplate='https://books.example/find/{searchTerms?}';
 cache.prefetch(hoverTemplate,'ночь');await delay();
 assert.equal(requests[1].url,hoverTemplate);assert.equal(requests[1].query,'ночь');
 requests[1].resolve(feed('find'));await delay();
 const encoded='https://books.example/search/%7BsearchTerms%7D';
 const encodedRequest=cache.get(encoded,'literal');
 assert.equal(requests[2].url,encoded,'already encoded paths must not be decoded');
 requests[2].resolve(feed('literal'));await encodedRequest;
 cache.dispose();
});

test('fresh hits, expired snapshots, refresh bypass, and LRU stay bounded', async () => {
 let now=0,calls=0;
 const cache=new OpdsCache(async (target,query) => {calls++;return feed(new URL(target).pathname.slice(1),query);},{maxEntries:2,ttlMs:100,now:()=>now});
 await cache.get(url('a'));await cache.get(url('b'));await cache.get(url('a'));
 assert.equal(calls,2);
 await cache.get(url('c'));
 assert.equal(cache.size,2);assert.equal(cache.readSnapshot(url('b')),null);
 now=101;
 assert.ok(cache.readSnapshot(url('a')),'expired snapshot remains available while a fresh feed loads');
 await cache.get(url('a'));assert.equal(calls,4);
 await cache.get(url('a'),'',{refresh:true});assert.equal(calls,5);
 cache.dispose();
});

test('hover delay keeps only the latest target and mouseleave cancels the timer', async () => {
 const targets=[];
 const cache=new OpdsCache(async target => {targets.push(target);return feed('x');},{prefetchDelayMs:10});
 cache.prefetch(url('a'));cache.prefetch(url('b'));cache.cancelPrefetch();
 await delay(20);assert.deepEqual(targets,[]);
 cache.prefetch(url('a'));cache.prefetch(url('b'));
 await delay(20);assert.deepEqual(targets,[url('b')]);
 cache.dispose();
});

test('click promotes a pending prefetch and mouseleave cannot cancel foreground work', async () => {
 const {loader,requests}=deferredLoader({abort:true});
 const cache=new OpdsCache(loader,{prefetchDelayMs:0});
 cache.prefetch(url('a'),'search');await delay();
 const clicked=cache.get(url('a'),'search');
 cache.cancelPrefetch();
 assert.equal(requests.length,1);assert.equal(requests[0].signal.aborted,false);
 requests[0].resolve(feed('a'));assert.equal((await clicked).entries[0].id,'a');
 cache.dispose();
});

test('foreground navigation aborts speculative work and is never blocked behind queued hovers', async () => {
 const {loader,requests}=deferredLoader({abort:true});
 const cache=new OpdsCache(loader,{prefetchDelayMs:0,maxPending:2});
 cache.prefetch(url('a'));await delay();cache.prefetch(url('b'));await delay();
 assert.equal(cache.inFlightCount,2);
 const clicked=cache.get(url('clicked'),'captured');
 assert.equal(requests[0].signal.aborted,true);assert.equal(requests[1].signal.aborted,true);
 await delay();
 assert.equal(requests.length,3);assert.equal(requests[2].url,url('clicked'));assert.equal(requests[2].query,'captured');
 assert.ok(cache.inFlightCount<=2);
 requests[2].resolve(feed('clicked'));await clicked;cache.dispose();
});

test('rapid navigation preserves active foreground and bounds its waiting queue', async () => {
 const {loader,requests}=deferredLoader();
 const cache=new OpdsCache(loader,{maxPending:2});
 const first=cache.get(url('a')),second=cache.get(url('b'));
 const obsolete=cache.get(url('obsolete')).catch(error=>error);
 const latest=cache.get(url('latest'));
 assert.equal(cache.inFlightCount,2);assert.equal(cache.queuedCount,1);
 assert.equal(requests.length,2);assert.equal(requests[0].signal.aborted,false);assert.equal(requests[1].signal.aborted,false);
 assert.equal((await obsolete).name,'AbortError');
 requests[0].resolve(feed('a'));await first;await delay();
 assert.equal(requests.length,3);assert.equal(requests[2].url,url('latest'));assert.ok(cache.inFlightCount<=2);
 requests[1].resolve(feed('b'));requests[2].resolve(feed('latest'));
 await Promise.all([second,latest]);cache.dispose();
});

test('background failures are handled and failures are never cached', async () => {
 let calls=0;
 const cache=new OpdsCache(async () => {calls++;if(calls===1)throw new Error('offline');return feed('a');},{prefetchDelayMs:0});
 cache.prefetch(url('a'));await delay();
 assert.equal(cache.size,0);
 assert.equal((await cache.get(url('a'))).entries[0].id,'a');assert.equal(calls,2);
 cache.dispose();
});

test('download markers update cached and already-running responses', async () => {
 const {loader,requests}=deferredLoader();
 const cache=new OpdsCache(loader);
 const ready=cache.get(url('a'));requests[0].resolve(feed('a'));await ready;
 const pending=cache.get(url('b'));
 const mark=feed=>({...feed,entries:feed.entries.map(book=>({...book,local_book_id:`local-${book.id}`}))});
 cache.update(mark);
 assert.equal(cache.readSnapshot(url('a')).entries[0].local_book_id,'local-a');
 requests[1].resolve(feed('b'));
 assert.equal((await pending).entries[0].local_book_id,'local-b');
 cache.dispose();
});

test('clear and disposal suppress late results even when a loader ignores abort', async () => {
 const {loader,requests}=deferredLoader();
 const cache=new OpdsCache(loader);
 const pending=cache.get(url('a')).catch(error=>error);
 cache.clear();assert.equal((await pending).name,'AbortError');assert.equal(requests[0].signal.aborted,true);
 requests[0].resolve(feed('a'));await delay();assert.equal(cache.size,0);
 const next=cache.get(url('b')).catch(error=>error);cache.dispose();assert.equal((await next).name,'AbortError');
 requests[1].resolve(feed('b'));await delay();assert.equal(cache.size,0);
 await assert.rejects(cache.get(url('c')),error=>error.name==='AbortError');
});
