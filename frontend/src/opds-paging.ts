import type {Entry, Feed} from './types';

export const AUTO_PAGE_LIMIT = 10;
export const PAGE_LIMIT = 20;
export const ITEM_LIMIT = 600;

const copy = <T>(value: T): T => structuredClone(value);
const urlKey = (value: string) => {try {const url = new URL(value); url.hash = ''; return url.href;} catch {return value;}};
const count = (feed: Feed) => feed.entries.length + feed.navigation.length;

function mergeEntries(first: Entry[], second: Entry[]): Entry[] {
  const result: Entry[] = [], ids = new Map<string, Entry>(), urls = new Map<string, Entry>();
  for (const entry of [...first, ...second]) {
    const duplicate = (entry.id && ids.get(entry.id)) || entry.acquisitions?.map(link => urls.get(urlKey(link.url))).find(Boolean);
    const target = duplicate || {...entry};
    if (!duplicate) result.push(target);
    else {
      if (entry.local_book_id) target.local_book_id = entry.local_book_id;
      const available = new Map((target.acquisitions || []).map(link => [urlKey(link.url), link]));
      for (const link of entry.acquisitions || []) available.set(urlKey(link.url), link);
      target.acquisitions = [...available.values()];
      if (target.acquisitions.length) target.unavailable_reason = undefined;
    }
    if (entry.id) ids.set(entry.id, target);
    for (const link of entry.acquisitions || []) urls.set(urlKey(link.url), target);
  }
  return result;
}

interface PageSnapshot {feed: Feed; requests: string[]; urls: string[]; previous: string | null; limited: boolean; itemLimit: number}

/** One visible section. Appending is atomic; its URL and history entry stay put. */
export class OpdsPages {
  feed: Feed;
  requests: string[] = [];
  private urls: string[];
  previous: string | null;
  limited = false;
  private itemLimit: number;

  constructor(first: Feed) {
    this.feed = copy(first);
    this.feed.entries = mergeEntries([],this.feed.entries);
    this.urls = [urlKey(first.url)];
    this.previous = first.prev || null;
    // A server's single large page is kept intact, even if it exceeds our budget.
    this.itemLimit = Math.max(ITEM_LIMIT, count(first));
  }
  get pageCount() {return this.urls.length;}
  get canAppend() {return !!this.feed.next && !this.limited && this.pageCount < PAGE_LIMIT;}
  get canAutoAppend() {return this.canAppend && this.pageCount < AUTO_PAGE_LIMIT;}

  append(requestUrl: string, next: Feed): boolean {
    if (!this.canAppend || urlKey(requestUrl) !== urlKey(this.feed.next!)) return false;
    if (this.urls.includes(urlKey(next.url))) throw new Error('Каталог повторил страницу. Автоподгрузка остановлена.');
    const entries = mergeEntries(this.feed.entries, next.entries);
    const seen = new Set<string>();
    const navigation = [...this.feed.navigation, ...next.navigation].filter(item => {
      const key = urlKey(item.url); if (seen.has(key)) return false; seen.add(key); return true;
    });
    if (entries.length + navigation.length > this.itemLimit) {this.limited = true; return false;}
    // Previous belongs before the first visible page. Appending must not link
    // back into records that are already present in this accumulated list.
    this.urls.push(urlKey(next.url));
    this.requests.push(requestUrl);
    this.feed = {...this.feed, entries, navigation, next: next.next};
    return true;
  }
  update(change: (feed: Feed) => Feed) {this.feed = change(this.feed);}
  snapshot(): PageSnapshot {return copy({feed: this.feed, requests: this.requests, urls: this.urls, previous: this.previous, limited: this.limited, itemLimit: this.itemLimit});}
  static restore(snapshot: PageSnapshot): OpdsPages {
    const saved = copy(snapshot), pages = new OpdsPages(saved.feed);
    pages.requests = saved.requests; pages.urls = saved.urls; pages.previous = saved.feed.prev || null;
    pages.limited = saved.limited; pages.itemLimit = saved.itemLimit;
    return pages;
  }
}

/** Small memory-only LRU. Browser storage holds page URLs, never whole feeds. */
export class OpdsPageStore {
  private snapshots = new Map<string, PageSnapshot>();
  private key(catalogId: string, url: string) {return JSON.stringify([catalogId, urlKey(url)]);}
  save(catalogId: string, pages: OpdsPages) {
    const key = this.key(catalogId, pages.feed.url);
    this.snapshots.delete(key); this.snapshots.set(key, pages.snapshot());
    while (this.snapshots.size > 3) this.snapshots.delete(this.snapshots.keys().next().value!);
  }
  read(catalogId: string, url: string, requests: string[]): OpdsPages | null {
    const key = this.key(catalogId, url), value = this.snapshots.get(key);
    if (!value || JSON.stringify(value.requests) !== JSON.stringify(requests)) return null;
    this.snapshots.delete(key); this.snapshots.set(key, value);
    return OpdsPages.restore(value);
  }
  update(change: (feed: Feed) => Feed) {for (const value of this.snapshots.values()) value.feed = change(value.feed);}
}

/** Rebuilds a saved section from the provider's actual next links, with all caps intact. */
export async function restorePages(first: Feed, requests: string[], load: (url: string) => Promise<Feed>, onError?: (error: unknown) => void): Promise<OpdsPages> {
  const pages = new OpdsPages(first);
  for (let index = 0; index < Math.min(requests.length, PAGE_LIMIT - 1) && pages.canAppend; index++) {
    const url = pages.feed.next!;
    try {
      if (!pages.append(url, await load(url))) break;
    } catch (error) {
      // Interrupted navigation must never commit a stale partial section.
      if ((error as {name?: string})?.name === 'AbortError' || !onError) throw error;
      onError(error);
      break;
    }
  }
  return pages;
}
