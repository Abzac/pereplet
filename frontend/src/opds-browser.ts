import type {Entry, Feed} from './types';

export interface CatalogLocation {
  url: string;
  requestUrl: string;
  requestQuery: string;
  query: string;
  scroll: number;
  title: string;
  timestamp: number;
  tab?: string;
  pages?: string[];
  contextUrl?: string;
  filter?: string;
}
export interface SavedLocation extends CatalogLocation {catalogId: string}
interface CatalogSession {root: string; trail: CatalogLocation[]; index: number; search?: {url: string; type?: string}}
export type NavigationCommit = 'push' | 'replace' | number;

function safeUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 4096) return false;
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password &&
      ![...url.searchParams.keys()].some(key => /^(?:password|passwd|token|access_token|api_?key|auth|authorization|secret|signature|credential|session)$/i.test(key));
  } catch { return false; }
}

function cleanLocation(value: any): CatalogLocation | null {
  if (!value || !safeUrl(value.url) || !safeUrl(value.requestUrl || value.url)) return null;
  return {url: value.url, requestUrl: value.requestUrl || value.url,
    requestQuery: String(value.requestQuery || '').slice(0, 500), query: String(value.query || '').slice(0, 500),
    title: String(value.title || 'Каталог').slice(0, 300), scroll: Math.max(0, Math.min(Number(value.scroll) || 0, 10_000_000)),
    timestamp: Math.max(0, Number(value.timestamp) || Date.now()),
    ...(safeUrl(value.contextUrl) ? {contextUrl: value.contextUrl} : {}),
    ...(typeof value.filter === 'string' ? {filter: value.filter.slice(0, 500)} : {}),
    ...(Array.isArray(value.pages) ? {pages: [...new Set(value.pages.filter(safeUrl))].slice(0, 19) as string[]} : {}),
    ...(typeof value.tab === 'string' && ['new', 'authors', 'series', 'genres'].includes(value.tab) ? {tab: value.tab} : {})};
}

const locationKey = (value: CatalogLocation) => JSON.stringify([value.requestUrl, value.requestQuery]);

/** Location metadata only. Feeds and book files never go into browser storage. */
export class OpdsHistory {
  sessions: Record<string, CatalogSession> = {};
  recent: SavedLocation[] = [];
  bookmarks: SavedLocation[] = [];

  constructor(serialized?: string | null) {
    try {
      const data = JSON.parse(serialized || '{}');
      if (data.version !== 1) return;
      for (const [id, raw] of Object.entries(data.sessions || {}).slice(-20)) {
        const item = raw as any;
        if (!safeUrl(item.root) || !Array.isArray(item.trail)) continue;
        const trail = item.trail.map(cleanLocation).filter(Boolean).slice(-30) as CatalogLocation[];
        const search = item.search && safeUrl(item.search.url) ? {url: item.search.url, type: String(item.search.type || '').slice(0, 100)} : undefined;
        this.sessions[id] = {root: item.root, trail, index: Math.min(Math.max(0, Number(item.index) || 0), trail.length - 1), search};
      }
      const saved = (items: any, cap: number): SavedLocation[] => (Array.isArray(items) ? items : []).slice(0, cap).flatMap(item => {
        const location = cleanLocation(item);
        return location && typeof item.catalogId === 'string' ? [{...location, catalogId: item.catalogId.slice(0, 100)}] : [];
      });
      this.recent = saved(data.recent, 100);
      this.bookmarks = saved(data.bookmarks, 200);
    } catch { /* Corrupt browser storage must not prevent the library from opening. */ }
  }

  session(id: string, root?: string): CatalogSession {
    if (!this.sessions[id] || (root && this.sessions[id].root !== root)) {
      this.sessions[id] = {root: root || '', trail: [], index: -1};
      const keys = Object.keys(this.sessions);
      if (keys.length > 20) delete this.sessions[keys.find(key => key !== id)!];
    }
    return this.sessions[id];
  }

  current(id: string): CatalogLocation | null {const s = this.sessions[id]; return s?.trail[s.index] || null;}
  target(id: string, delta: number): {index: number; location: CatalogLocation} | null {
    const s = this.sessions[id], index = (s?.index ?? -1) + delta;
    return s?.trail[index] ? {index, location: {...s.trail[index]}} : null;
  }
  checkpoint(id: string, query: string, scroll: number, pages?: string[], filter?: string) {
    const location = this.current(id);
    if (location) {
      location.query = query.slice(0, 500); location.scroll = Math.max(0, scroll || 0);
      if (pages) location.pages = [...pages].filter(safeUrl).slice(0, 19);
      if (filter !== undefined) location.filter = filter.slice(0, 500);
      this.recent = this.recent.map(item => item.catalogId === id && locationKey(item) === locationKey(location) ? {...location, catalogId: id} : item);
    }
  }
  commit(id: string, location: CatalogLocation, mode: NavigationCommit = 'push') {
    const s = this.session(id);
    const clean = cleanLocation(location);
    if (!clean) return;
    if (typeof mode === 'number' && s.trail[mode]) {s.index = mode; s.trail[mode] = clean;}
    else if (mode === 'replace' && s.index >= 0) s.trail[s.index] = clean;
    else if (this.current(id) && locationKey(this.current(id)!) === locationKey(clean)) s.trail[s.index] = clean;
    else {
      s.trail = [...s.trail.slice(0, s.index + 1), clean].slice(-30);
      s.index = s.trail.length - 1;
    }
    this.recent = [{...clean, catalogId: id}, ...this.recent.filter(item => item.catalogId !== id || locationKey(item) !== locationKey(clean))].slice(0, 100);
  }
  hasBookmark(id: string): boolean {
    const current = this.current(id);
    return !!current && this.bookmarks.some(item => item.catalogId === id && locationKey(item) === locationKey(current));
  }
  toggleBookmark(id: string): boolean {
    const current = this.current(id);
    if (!current) return false;
    if (this.hasBookmark(id)) {this.removeBookmark({...current, catalogId: id}); return false;}
    this.bookmarks = [{...current, catalogId: id}, ...this.bookmarks].slice(0, 200);
    return true;
  }
  removeBookmark(location: SavedLocation) {
    this.bookmarks = this.bookmarks.filter(item => item.catalogId !== location.catalogId || locationKey(item) !== locationKey(location));
  }
  removeCatalog(id: string) {
    delete this.sessions[id];
    this.recent = this.recent.filter(item => item.catalogId !== id);
    this.bookmarks = this.bookmarks.filter(item => item.catalogId !== id);
  }
  serialize(): string {
    // Revalidate at serialization too: incoming catalog links may contain credentials.
    const sessions = Object.fromEntries(Object.entries(this.sessions).filter(([, session]) => safeUrl(session.root)).map(([id, session]) => [id, {
      ...session, trail: session.trail.map(cleanLocation).filter(Boolean),
      search: session.search && safeUrl(session.search.url) ? session.search : undefined,
    }]));
    const saved = (items: SavedLocation[]) => items.flatMap(item => {const clean = cleanLocation(item); return clean ? [{...clean, catalogId: item.catalogId}] : [];});
    return JSON.stringify({version: 1, sessions, recent: saved(this.recent), bookmarks: saved(this.bookmarks)});
  }
}

export function preferredAcquisition(entry: Entry) {
  return entry.acquisitions?.find(item => /epub/i.test(item.type || '') || /\.epub(?:[?#]|$)/i.test(item.url)) ||
    entry.acquisitions?.find(item => /fb2|fictionbook/i.test(item.type || '') || /\.fb2(?:\.zip)?(?:[?#]|$)/i.test(item.url)) || entry.acquisitions?.[0];
}

export interface BatchProgress {
  phase: 'collecting' | 'downloading' | 'done' | 'cancelled';
  pages: number; total: number; processed: number; downloaded: number; skipped: number; failed: number;
  errors: string[]; limited: boolean; currentTitle: string;
}
export const emptyBatch = (): BatchProgress => ({phase: 'collecting', pages: 0, total: 0, processed: 0, downloaded: 0, skipped: 0, failed: 0, errors: [], limited: false, currentTitle: ''});

/** Only follows rel=next in the selected section. Never walks child categories. */
export async function downloadSection(first: Feed, options: {
  load: (url: string) => Promise<Feed>;
  download: (entry: Entry) => Promise<{duplicate?: boolean}>;
  cancelled: () => boolean;
  progress: (state: BatchProgress) => void;
  include?: (entry: Entry) => boolean;
  maxPages?: number; maxItems?: number;
}): Promise<BatchProgress> {
  const state = emptyBatch(), queue: Entry[] = [], seenIds = new Set<string>(), seenUrls = new Set<string>(), pages = new Set<string>();
  const maxPages = Math.max(1, Math.min(options.maxPages || 50, 50)), maxItems = Math.max(1, Math.min(options.maxItems || 500, 500));
  const publish = () => options.progress({...state, errors: [...state.errors]});
  const error = (message: string) => {state.failed++; if (state.errors.length < 20) state.errors.push(message);};
  let feed: Feed | null = first;
  publish();
  while (feed && !options.cancelled()) {
    if (pages.has(feed.url)) {error('Каталог повторил страницу; обход раздела остановлен.'); break;}
    pages.add(feed.url); state.pages++;
    for (let index = 0; index < feed.entries.length; index++) {
      const entry = feed.entries[index], url = preferredAcquisition(entry)?.url;
      if ((entry.id && seenIds.has(entry.id)) || (url && seenUrls.has(url))) continue;
      if (options.include && !options.include(entry)) continue;
      if (queue.length >= maxItems) {state.limited = true; break;}
      if (entry.id) seenIds.add(entry.id);
      if (url) seenUrls.add(url);
      queue.push(entry);
    }
    state.total = queue.length; publish();
    if (state.limited || !feed.next) break;
    if (state.pages >= maxPages || queue.length >= maxItems) {state.limited = true; break;}
    if (pages.has(feed.next)) {error('Каталог повторил страницу; обход раздела остановлен.'); break;}
    const next: string = feed.next;
    try {feed = await options.load(next);}
    catch (reason) {error(`Следующая страница: ${reason instanceof Error ? reason.message : String(reason)}`); break;}
  }
  state.phase = 'downloading'; publish();
  for (const entry of queue) {
    if (options.cancelled()) break;
    state.currentTitle = entry.title; publish();
    if (entry.local_book_id || !preferredAcquisition(entry)) state.skipped++;
    else {
      try {const result = await options.download(entry); if (result.duplicate) state.skipped++; else state.downloaded++;}
      catch (reason) {error(`${entry.title}: ${reason instanceof Error ? reason.message : String(reason)}`);}
    }
    state.processed++; publish();
  }
  state.phase = options.cancelled() ? 'cancelled' : 'done'; state.currentTitle = ''; publish();
  return {...state, errors: [...state.errors]};
}
