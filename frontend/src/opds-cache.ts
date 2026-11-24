import type {Feed} from './types';

type Loader = (url: string, query: string, signal: AbortSignal) => Promise<Feed>;
type Update = (feed: Feed) => Feed;
type Ready = {feed: Feed; expires: number};
type Pending = {
 key: string; url: string; query: string; foreground: boolean; prepared: boolean; order: number;
 state: 'queued' | 'loading'; cancelled: boolean; controller: AbortController;
 promise: Promise<Feed>; resolve: (feed: Feed) => void; reject: (error: unknown) => void;
 updates: Update[];
};

export class OpdsCacheCancelled extends Error {
 constructor() { super('Запрос каталога отменён'); this.name = 'AbortError'; }
}

/** A canonical network URL and the exact captured search query form one cache key. */
export function opdsCacheKey(url: string, query = ''): string {
 const target = new URL(url);
 target.hash = '';
 return JSON.stringify([target.href.replace(/%[\da-f]{2}/gi, value => value.toUpperCase()), query]);
}

/** Small LRU feed cache. Background requests never prevent the next user navigation. */
export class OpdsCache {
 private readonly ready = new Map<string, Ready>();
 private readonly pending = new Map<string, Pending>();
 private readonly active = new Set<Pending>();
 private readonly maxEntries: number;
 private readonly ttlMs: number;
 private readonly maxPending: number;
 private readonly prefetchDelayMs: number;
 private readonly now: () => number;
 private sequence = 0;
 private closed = false;
 private hoverTimer: ReturnType<typeof setTimeout> | undefined;
 private hoverKey: string | undefined;

 constructor(private readonly loader: Loader, options: {
  maxEntries?: number; ttlMs?: number; maxPending?: number; prefetchDelayMs?: number; now?: () => number;
 } = {}) {
  this.maxEntries = options.maxEntries ?? 12;
  this.ttlMs = options.ttlMs ?? 180_000;
  this.maxPending = options.maxPending ?? 2;
  this.prefetchDelayMs = options.prefetchDelayMs ?? 150;
  this.now = options.now ?? Date.now;
  if (!Number.isInteger(this.maxEntries) || this.maxEntries < 1
   || !Number.isInteger(this.maxPending) || this.maxPending < 1
   || !Number.isFinite(this.ttlMs) || this.ttlMs < 0
   || !Number.isFinite(this.prefetchDelayMs) || this.prefetchDelayMs < 0) {
   throw new RangeError('Неверные ограничения кэша OPDS');
  }
 }

 get size(): number { return this.ready.size; }
 get inFlightCount(): number { return this.active.size; }
 get queuedCount(): number { return [...this.pending.values()].filter(item => item.state === 'queued').length; }

 /** Shared requests, independent result objects. refresh bypasses a ready cached value. */
 async get(url: string, query = '', options: {refresh?: boolean} = {}): Promise<Feed> {
  if (this.closed) throw new OpdsCacheCancelled();
  const key = opdsCacheKey(url, query);
  if (this.hoverKey === key) this.clearHover();
  if (options.refresh) this.ready.delete(key);
  else {
   const cached = this.ready.get(key);
   if (cached && cached.expires > this.now()) {
    this.touch(key, cached);
    return structuredClone(cached.feed);
   }
  }
  let entry = this.pending.get(key);
  if (entry) {
   entry.foreground = true;
   entry.order = ++this.sequence;
  } else {
   // Keep at most one waiting navigation. Older queued navigation is no longer
   // useful after the user chooses another destination, but running foreground
   // requests retain their callers and are allowed to finish.
   for (const item of this.pending.values()) {
    if (!item.foreground || item.state === 'queued') this.cancel(item);
   }
   entry = this.create(key, url, query, true);
  }
  this.pump();
  return structuredClone(await entry.promise);
 }

 /** Immediate speculative fetch, shared with hover and foreground requests.
  * Aborting this observer never cancels a request already promoted by get(). */
 async prepare(url: string, query = '', signal?: AbortSignal): Promise<Feed> {
  if (this.closed || signal?.aborted) throw new OpdsCacheCancelled();
  const key = opdsCacheKey(url, query), cached = this.ready.get(key);
  if (cached && cached.expires > this.now()) {
   this.touch(key, cached);
   return structuredClone(cached.feed);
  }
  if (this.hoverKey === key) this.clearHover();
  let entry = this.pending.get(key);
  if (!entry) {
   // A speculative chain cannot grow an unbounded waiting queue while two
   // foreground requests are still running. Navigation always has priority.
   for (const item of this.pending.values()) {
    if (!item.foreground && item.state === 'queued') this.cancel(item);
   }
   entry = this.create(key, url, query, false);
  }
  entry.prepared = true;
  this.pump();
  if (!signal) return structuredClone(await entry.promise);
  const observed = entry;
  const value = await new Promise<Feed>((resolve, reject) => {
   const abort = () => {
    if (!observed.foreground && this.pending.get(key) === observed) this.cancel(observed);
    reject(new OpdsCacheCancelled());
    this.pump();
   };
   signal.addEventListener('abort', abort, {once:true});
   observed.promise.then(result => {signal.removeEventListener('abort', abort);resolve(result);},
    error => {signal.removeEventListener('abort', abort);reject(error);});
   if (signal.aborted) abort();
  });
  return structuredClone(value);
 }

 /** An immediate, independent snapshot, including an expired one for stale-while-loading UI. */
 readSnapshot(url: string, query = ''): Feed | null {
  const key = opdsCacheKey(url, query), cached = this.ready.get(key);
  if (!cached) return null;
  this.touch(key, cached);
  return structuredClone(cached.feed);
 }

 /** Only the latest hovered target is scheduled; pointer movement cannot grow a queue. */
 prefetch(url: string, query = ''): void {
  this.clearHover();
  if (this.closed) return;
  let key: string;
  try { key = opdsCacheKey(url, query); } catch { return; }
  if (this.pending.has(key) || (this.ready.get(key)?.expires ?? 0) > this.now()) return;
  this.hoverKey = key;
  this.hoverTimer = setTimeout(() => {
   this.hoverTimer = undefined; this.hoverKey = undefined;
   if (this.closed || this.pending.has(key) || this.active.size >= this.maxPending
    || [...this.pending.values()].some(item => item.state === 'queued' && item.foreground)) return;
   this.create(key, url, query, false);
   this.pump();
  }, this.prefetchDelayMs);
 }

 /** Pointer movement must not cancel the separate next-page preparation chain. */
 cancelHover(): void {
  this.clearHover();
  for (const entry of this.pending.values()) if (!entry.foreground && !entry.prepared) this.cancel(entry);
  this.pump();
 }

 /** A catalog switch or bulk work can discard all speculative requests. */
 cancelPrefetch(): void {
  this.clearHover();
  for (const entry of this.pending.values()) if (!entry.foreground) this.cancel(entry);
  this.pump();
 }

 /** Keep download markers fresh, also when an older in-flight response arrives later. */
 update(updater: Update): void {
  for (const item of this.ready.values()) item.feed = structuredClone(updater(structuredClone(item.feed)));
  for (const entry of this.pending.values()) entry.updates.push(updater);
 }

 clear(): void {
  this.clearHover();
  this.ready.clear();
  for (const entry of this.pending.values()) this.cancel(entry);
 }

 dispose(): void { this.closed = true; this.clear(); }

 private clearHover(): void {
  if (this.hoverTimer !== undefined) clearTimeout(this.hoverTimer);
  this.hoverTimer = undefined; this.hoverKey = undefined;
 }

 private touch(key: string, item: Ready): void {
  this.ready.delete(key); this.ready.set(key, item);
 }

 private create(key: string, url: string, query: string, foreground: boolean): Pending {
  // URL is only canonicalized for cache identity. Preserve the caller's request
  // verbatim: raw {searchTerms} in a path is an OPDS template, not encoded text.
  let resolve!: (feed: Feed) => void, reject!: (error: unknown) => void;
  const promise = new Promise<Feed>((yes, no) => {resolve = yes; reject = no;});
  // A speculative request may reject before anyone clicks it.
  void promise.catch(() => {});
  const entry: Pending = {key, url, query, foreground, prepared: false, order: ++this.sequence, state: 'queued',
   cancelled: false, controller: new AbortController(), promise, resolve, reject, updates: []};
  this.pending.set(key, entry);
  return entry;
 }

 private cancel(entry: Pending): void {
  if (this.pending.get(entry.key) === entry) this.pending.delete(entry.key);
  entry.cancelled = true;
  entry.controller.abort();
  entry.reject(new OpdsCacheCancelled());
  entry.updates.length = 0;
 }

 private pump(): void {
  if (this.closed) return;
  while (this.active.size < this.maxPending) {
   const next = [...this.pending.values()].filter(entry => entry.state === 'queued')
    .sort((a, b) => Number(b.foreground) - Number(a.foreground) || b.order - a.order)[0];
   if (!next) return;
   next.state = 'loading';
   this.active.add(next);
   void this.run(next);
  }
 }

 private async run(entry: Pending): Promise<void> {
  try {
   let feed = await this.loader(entry.url, entry.query, entry.controller.signal);
   if (entry.cancelled || this.closed || this.pending.get(entry.key) !== entry) return;
   feed = structuredClone(feed);
   for (const update of entry.updates) feed = update(feed);
   const cached = structuredClone(feed);
   this.touch(entry.key, {feed: cached, expires: this.now() + this.ttlMs});
   while (this.ready.size > this.maxEntries) this.ready.delete(this.ready.keys().next().value!);
   this.pending.delete(entry.key);
   entry.resolve(cached);
  } catch (error) {
   if (!entry.cancelled) {
    if (this.pending.get(entry.key) === entry) this.pending.delete(entry.key);
    entry.reject(error);
   }
  } finally {
   entry.updates.length = 0;
   this.active.delete(entry);
   this.pump();
  }
 }
}
