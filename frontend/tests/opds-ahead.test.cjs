const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), ts = require('typescript');
const modules = new Map();
function load(name) {
 if (modules.has(name)) return modules.get(name);
 const exports = {};
 const source = fs.readFileSync(path.join(__dirname, `../src/${name}.ts`), 'utf8');
 vm.runInNewContext(ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,
  {exports, require: target => load(target.replace('./','')), URL, AbortController, structuredClone, setTimeout, clearTimeout});
 modules.set(name,exports);return exports;
}
const {OpdsCache} = load('opds-cache'), {OpdsAhead} = load('opds-ahead'), {OpdsPages} = load('opds-paging');
const url = n => `https://books.test/page/${n}`;
const entry = n => ({id:String(n),title:String(n),authors:[],acquisitions:[]});
const feed = (n, extra = {}) => ({url:url(n),title:`Page ${n}`,entries:[entry(n)],navigation:[],next:url(n+1),prev:null,...extra});
const tick = () => new Promise(resolve => setTimeout(resolve,5));
function deferred({respectAbort = false,maxEntries = 12} = {}) {
 const requests = [];
 const cache = new OpdsCache((target, query, signal) => new Promise((resolve,reject) => {
  requests.push({target,query,signal,resolve,reject});
  if (respectAbort) signal.addEventListener('abort', () => reject(Object.assign(new Error('abort'),{name:'AbortError'})), {once:true});
 }),{maxEntries});
 return {cache,requests,ahead:new OpdsAhead(cache)};
}

test('prepares two actual next feeds without appending visible pages or following categories', async () => {
 const {cache,requests,ahead}=deferred(), pages=new OpdsPages(feed(1,{next:url(7),navigation:[{title:'Do not crawl',url:url(99)}]}));
 ahead.warm('catalog/query',pages);
 assert.equal(requests.length,1);assert.equal(requests[0].target,url(7));
 requests[0].resolve(feed(7,{next:url(12)}));await tick();
 assert.equal(requests.length,2);assert.equal(requests[1].target,url(12));
 requests[1].resolve(feed(12));await tick();
 assert.equal(requests.length,2);assert.equal(pages.pageCount,1);assert.equal(pages.feed.entries.length,1);
 assert.equal(cache.size,2);
 const next=await cache.get(url(7));assert.equal(requests.length,2);assert.equal(next.url,url(7));
 next.entries[0].title='Changed';assert.equal(cache.readSnapshot(url(7)).entries[0].title,'7');
 ahead.dispose();cache.dispose();
});

test('scroll promotes pending work and advancing the visible tail retains then replenishes it', async () => {
 const {cache,requests,ahead}=deferred(),pages=new OpdsPages(feed(1));
 ahead.warm('same-section',pages);
 const foreground=cache.get(url(2));assert.equal(requests.length,1);
 requests[0].resolve(feed(2));const second=await foreground;await tick();
 assert.equal(requests.length,2);assert.equal(requests[1].target,url(3));
 pages.append(url(2),second);ahead.warm('same-section',pages);
 assert.equal(requests[1].signal.aborted,false);
 requests[1].resolve(feed(3));await tick();
 assert.equal(requests.length,3);assert.equal(requests[2].target,url(4));
 requests[2].resolve(feed(4));await tick();assert.equal(requests.length,3);
 assert.equal(pages.pageCount,2);assert.equal(cache.size,3);
 ahead.dispose();cache.dispose();
});

test('catalog/query change aborts speculative work and stale responses cannot populate cache or continue chains', async () => {
 const {cache,requests,ahead}=deferred();
 ahead.warm(JSON.stringify(['a','search','first']),new OpdsPages(feed(1)));
 ahead.warm(JSON.stringify(['a','search','second']),new OpdsPages(feed(40)));
 assert.equal(requests.length,2);assert.equal(requests[0].signal.aborted,true);
 requests[0].resolve(feed(2));await tick();assert.equal(cache.readSnapshot(url(2)),null);
 assert.equal(requests.length,2);
 requests[1].resolve(feed(41));await tick();assert.equal(requests.length,3);assert.equal(requests[2].target,url(42));
 ahead.clear();assert.equal(requests[2].signal.aborted,true);
 requests[2].resolve(feed(42));await tick();assert.equal(cache.readSnapshot(url(42)),null);assert.equal(requests.length,3);
 ahead.dispose();ahead.warm('closed',new OpdsPages(feed(100)));assert.equal(requests.length,3);cache.dispose();
});

test('clearing speculative observer never aborts a request promoted to foreground', async () => {
 const {cache,requests,ahead}=deferred({respectAbort:true});
 ahead.warm('section',new OpdsPages(feed(1)));
 const foreground=cache.get(url(2));ahead.clear();
 assert.equal(requests[0].signal.aborted,false);
 requests[0].resolve(feed(2));assert.equal((await foreground).url,url(2));await tick();
 assert.equal(requests.length,1);ahead.dispose();cache.dispose();
});

test('mouse leave cancels a hover without interrupting the next-page chain', async () => {
 const {cache,requests,ahead}=deferred({respectAbort:true});
 ahead.warm('section',new OpdsPages(feed(1)));
 cache.prefetch(url(99));await new Promise(resolve=>setTimeout(resolve,170));
 assert.equal(requests.length,2);cache.cancelHover();
 assert.equal(requests[0].signal.aborted,false);assert.equal(requests[1].signal.aborted,true);
 requests[0].resolve(feed(2));await tick();assert.equal(requests.length,3);assert.equal(requests[2].target,url(3));
 requests[2].resolve(feed(3));await tick();ahead.dispose();cache.dispose();
});

test('foreground navigation preempts prepared work and the speculative waiting queue is bounded', async () => {
 const {cache,requests,ahead}=deferred({respectAbort:true});
 ahead.warm('old-section',new OpdsPages(feed(1)));
 const foreground=cache.get(url(100));await tick();assert.equal(requests[0].signal.aborted,true);
 assert.equal(requests[1].target,url(100));requests[1].resolve(feed(100));await foreground;
 const a=cache.get(url(200)),b=cache.get(url(300));
 const abandoned=cache.prepare(url(400)).catch(error=>error);
 const last=cache.prepare(url(500));assert.equal(cache.queuedCount,1);
 assert.equal((await abandoned).name,'AbortError');assert.equal(cache.inFlightCount,2);
 requests[2].resolve(feed(200));await a;await tick();assert.equal(requests[4].target,url(500));
 requests[3].resolve(feed(300));requests[4].resolve(feed(500));await Promise.all([b,last]);
 ahead.dispose();cache.dispose();
});

test('existing automatic page and item budgets also stop speculative chains', async () => {
 const {cache,requests,ahead}=deferred(),pages=new OpdsPages(feed(1));
 for(let n=2;n<=9;n++)pages.append(url(n),feed(n));
 ahead.warm('near-page-cap',pages);requests[0].resolve(feed(10));await tick();
 assert.equal(requests.length,1,'must not fetch page 11 beyond the automatic budget');
 pages.append(url(10),feed(10));ahead.warm('near-page-cap',pages);await tick();assert.equal(requests.length,1);
 const large=new OpdsPages(feed(100,{entries:Array.from({length:590},(_,n)=>entry(n))}));
 ahead.warm('near-item-cap',large);assert.equal(requests.length,2);
 requests[1].resolve(feed(101,{entries:Array.from({length:20},(_,n)=>entry(n+590))}));await tick();
 assert.equal(requests.length,2);assert.equal(large.limited,false);assert.equal(large.feed.entries.length,590);
 ahead.dispose();cache.dispose();
});

test('loops and background errors stop without automatic retries; foreground may retry', async () => {
 const {cache,requests,ahead}=deferred();
 ahead.warm('loop',new OpdsPages(feed(1)));
 requests[0].resolve(feed(1,{url:url(1)+'#alias'}));await tick();assert.equal(requests.length,1);
 ahead.warm('offline',new OpdsPages(feed(10)));
 requests[1].reject(new Error('offline'));await tick();assert.equal(requests.length,2);assert.equal(cache.readSnapshot(url(11)),null);
 const retry=cache.get(url(11));assert.equal(requests.length,3);requests[2].resolve(feed(11));await retry;
 ahead.dispose();cache.dispose();
});

test('prefetch shares the bounded LRU rather than accumulating hidden page lists', async () => {
 const calls=[],cache=new OpdsCache(async target=>{calls.push(target);return feed(Number(target.split('/').at(-1)));},{maxEntries:3});
 const ahead=new OpdsAhead(cache);
 for(let n=1;n<20;n+=3){ahead.warm(`section${n}`,new OpdsPages(feed(n)));await tick();assert.ok(cache.size<=3)}
 assert.equal(calls.length,14);assert.equal(cache.size,3);ahead.dispose();cache.dispose();
});
