import type {Feed} from './types';

export type FlibustaTabId = 'new' | 'authors' | 'series' | 'genres';
export type FlibustaSearchKind = 'authors' | 'books' | 'series';
export type FlibustaTab = {id: FlibustaTabId; label: string; url: string};
export type FlibustaFeedArea = 'root' | 'new' | 'authors' | 'author' | 'series' | 'genres' | 'search' | 'books' | 'other';
export type FlibustaNavRole = 'root' | 'up' | 'alphabet' | 'author' | 'series' | 'all-books' | 'search-authors' | 'search-books' | 'search-series' | 'section';
export type FlibustaNav = Feed['navigation'][number] & {role: FlibustaNavRole};
export type FlibustaLoader = (url: string, query?: string) => Promise<Feed>;

const normalized = (value: string) => (value || '').trim().toLocaleLowerCase('ru').replace(/\s+/g, ' ');
const rootTitles = new Set(['начало каталога', 'в начало каталога', 'главная', 'start', 'catalog home']);
const upTitles = new Set(['на уровень выше', 'уровень выше', 'up']);
const searchTitles: Record<FlibustaSearchKind, string> = {authors: 'поиск авторов', books: 'поиск книг', series: 'поиск серий'};

function parsedUrl(value: string): URL | null {
 try { const url = new URL(value); return /^https?:$/.test(url.protocol) ? url : null; } catch { return null; }
}
function address(value: string): string {
 const url = parsedUrl(value);
 if (!url) return value;
 url.hash = '';
 return url.href.replace(/%[\da-f]{2}/gi, value => value.toUpperCase());
}
function sameAddress(a: string, b: string | undefined): boolean { return !!b && address(a) === address(b); }

/** Recognize the host, or a matching-host root document that identifies itself as Flibusta. */
export function isFlibustaCatalog(catalogUrl: string, rootFeed?: Feed): boolean {
 const catalog = parsedUrl(catalogUrl);
 if (!catalog) return false;
 if (/^(?:[a-z\d-]+\.)*flibusta\.[a-z]{2,}$/i.test(catalog.hostname)) return true;
 const source = rootFeed && parsedUrl(rootFeed.url);
 return !!source && source.host === catalog.host
  && /^(?:flibusta(?: catalog)?|флибуста|каталог флибусты)$/.test(normalized(rootFeed.title));
}

/** Labels are adapted; URLs always come from actual links published in the root feed. */
export function flibustaTabs(rootFeed: Feed): FlibustaTab[] {
 const definitions: {id: FlibustaTabId; label: string; titles: string[]}[] = [
  {id: 'new', label: 'Новинки', titles: ['новинки']},
  {id: 'authors', label: 'Авторы', titles: ['по авторам', 'авторы']},
  {id: 'series', label: 'Серии', titles: ['по сериям', 'серии']},
  {id: 'genres', label: 'Жанры', titles: ['по жанрам', 'жанры']},
 ];
 return definitions.flatMap(definition => {
  const matches = uniqueLinks(rootFeed.navigation.filter(link => definition.titles.includes(normalized(link.title))));
  return matches.length === 1 ? [{id: definition.id, label: definition.label, url: matches[0].url}] : [];
 });
}

function uniqueLinks(links: Feed['navigation']): Feed['navigation'] {
 const seen = new Set<string>();
 return links.filter(link => {
  if (!parsedUrl(link.url)) return false;
  const key = address(link.url);
  if (seen.has(key)) return false;
  seen.add(key); return true;
 });
}

/** Classification observes URLs; it never constructs a route to request. */
export function getFeedArea(feed: Feed, rootFeed?: Feed): FlibustaFeedArea {
 const url = parsedUrl(feed.url), title = normalized(feed.title);
 if (sameAddress(feed.url, rootFeed?.url) || /^(?:flibusta(?: catalog)?|каталог флибусты)$/.test(title)) return 'root';
 if (!url) return feed.entries.length ? 'books' : 'other';
 const path = url.pathname;
 if (url.searchParams.get('searchType') === 'authors') return 'authors';
 if (url.searchParams.get('searchType') === 'books') return 'books';
 if (url.searchParams.get('searchType') === 'sequences' || url.searchParams.get('searchType') === 'series') return 'series';
 if (/\/author\//.test(path) || /^книги автора\s/.test(title)) return 'author';
 if (/\/(?:authorsequence|sequence)\//.test(path)) return 'books';
 if (/\/(?:authorsindex|authors)(?:\/|$)/.test(path)) return 'authors';
 if (/\/(?:sequencesindex|sequences|authorsequences)(?:\/|$)/.test(path) || /^книжные серии\s/.test(title)) return 'series';
 if (/\/new[^/]*(?:\/|$)/.test(path) || /^новинки(?:\s|$)/.test(title)) return 'new';
 if (/\/genres(?:\/|$)/.test(path)) return 'genres';
 if (/\/search(?:\/|$)/.test(path)) return feed.entries.length ? 'books' : 'search';
 const tab = rootFeed && flibustaTabs(rootFeed).find(tab => sameAddress(tab.url, feed.url));
 return tab?.id || (feed.entries.length ? 'books' : 'other');
}

export function flibustaNavRole(link: Feed['navigation'][number], feed?: Feed, rootFeed?: Feed): FlibustaNavRole {
 const title = normalized(link.title), path = parsedUrl(link.url)?.pathname || '';
 if (rootTitles.has(title) || sameAddress(link.url, rootFeed?.url)) return 'root';
 if (upTitles.has(title) || sameAddress(link.url, feed?.up)) return 'up';
 for (const kind of Object.keys(searchTitles) as FlibustaSearchKind[]) if (title === searchTitles[kind]) return `search-${kind}`;
 if (/^(?:все книги(?: автора| серии)?(?:\s.*)?|книги по алфавиту)$/.test(title)) return 'all-books';
 if (/\/author\/[^/]+\/?$/.test(path)) return 'author';
 if (/\/(?:authorsequence|sequence)\//.test(path)) return 'series';
 if ([...link.title.trim()].length === 1 && !feed?.entries.length) return 'alphabet';
 return 'section';
}

/** Browser controls already expose root and parent navigation; do not repeat those as content tiles. */
export function flibustaNavigation(feed: Feed, rootFeed?: Feed): FlibustaNav[] {
 return uniqueLinks(feed.navigation).map(link => ({...link, role: flibustaNavRole(link, feed, rootFeed)}))
  .filter(link => link.role !== 'root' && link.role !== 'up' && !sameAddress(link.url, feed.url));
}

function oneLink(feed: Feed, accepts: (title: string) => boolean): Feed['navigation'][number] | null {
 const matches = uniqueLinks(feed.navigation.filter(link => accepts(normalized(link.title)) && !sameAddress(link.url, feed.url)));
 return matches.length === 1 ? matches[0] : null;
}

async function follow(feed: Feed, link: Feed['navigation'][number] | null, load: FlibustaLoader, preserveContext = false): Promise<Feed> {
 if (!link || feed.entries.length) return feed;
 const next = await load(link.url);
 if (!preserveContext) return next;
 // Keep the author's name and real alternative menus (series/date) after skipping
 // the service page. The returned URL remains the URL actually fetched.
 return {...next, title: feed.title, context_url: feed.url,
  navigation: uniqueLinks([...next.navigation, ...feed.navigation.filter(item => !sameAddress(item.url, link.url))])};
}

/** Recover the author's real menu when reopening its already-resolved book URL. */
export async function restoreFlibustaContext(feed:Feed,load:FlibustaLoader,contextUrl?:string):Promise<Feed>{
 if(!feed.entries.length&&!contextUrl&&!feed.context_url)return feed;
 const source=parsedUrl(feed.url);if(!source)return feed;
 const eligible=(value:string)=>{const url=parsedUrl(value);return !!url&&url.origin===source.origin&&!url.username&&!url.password&&!sameAddress(url.href,feed.url)};
 let menuUrl=[contextUrl,feed.context_url].find(value=>value&&eligible(value));
 if(!menuUrl&&getFeedArea(feed)==='author'){
  // Compare published links with the current author ID. Never fabricate a route.
  const authorPath=source.pathname.match(/^(.*\/author\/[^/]+)(?:\/.*)?$/)?.[1];
  const authorName=normalized(feed.title.replace(/^книги автора\s+/i,''));
  const links=[...feed.navigation,...(feed.up?[{url:feed.up,title:''}]:[]),...feed.entries.flatMap(entry=>[
   ...(entry.related_links||[]),...(entry.author_details||[]).flatMap(author=>(author.links||[]).map(link=>({...link,title:link.title||author.name})))
  ])];
  const candidates=uniqueLinks(links.filter(link=>{
   if(!eligible(link.url))return false;
   const target=parsedUrl(link.url),title=normalized((link.title||'').replace(/^(?:все книги автора|книги автора)\s+/i,''));
   return authorPath?target.pathname.replace(/\/$/,'')===authorPath:title===authorName&&/\/author\/[^/]+\/?$/.test(target.pathname);
  }).map(link=>({title:link.title||'',url:link.url})));
  if(candidates.length===1)menuUrl=candidates[0].url;
 }
 if(!menuUrl)return feed;
 if(feed.context_url&&feed.navigation.some(link=>/^(?:книги по сериям|книги вне серий|книги по дате поступления)$/i.test(link.title)))return feed;
 try{
  const menu=await load(menuUrl);if(!eligible(menu.url)||getFeedArea(menu)!=='author')return feed;
  return{...feed,context_url:menu.url,title:getFeedArea(feed)==='author'?menu.title:feed.title,navigation:uniqueLinks([...feed.navigation,...menu.navigation]).filter(link=>!sameAddress(link.url,feed.url))};
 }catch{return{...feed,context_url:menuUrl}} // Keep the book list usable during a transient menu failure.
}

/** One tab click opens the published tab link and skips the redundant "Все новинки" menu. */
export async function resolveFlibustaTab(tab: FlibustaTab, load: FlibustaLoader): Promise<Feed> {
 const feed = await load(tab.url);
 return tab.id === 'new' ? follow(feed, oneLink(feed, title => title === 'все новинки'), load) : feed;
}

/** The live author menu offers "Книги по алфавиту" as the complete author book list. */
export async function resolveFlibustaAuthor(feed: Feed, load: FlibustaLoader): Promise<Feed> {
 if (getFeedArea(feed) !== 'author' || feed.entries.length) return feed;
 const explicit = uniqueLinks(feed.navigation.filter(link => /^все книги(?: автора(?:\s.*)?)?$/.test(normalized(link.title))));
 if (explicit.length > 1) return feed;
 const target = explicit[0] || oneLink(feed, title => title === 'книги по алфавиту');
 return follow(feed, target && !sameAddress(target.url, feed.url) ? target : null, load, true);
}

/** Only unambiguous service menus are collapsed; alphabet indexes and actual choices stay visible. */
export async function resolveFlibustaFeed(feed: Feed, load: FlibustaLoader): Promise<Feed> {
 if (feed.entries.length) return feed;
 const area = getFeedArea(feed);
 if (area === 'author') return resolveFlibustaAuthor(feed, load);
 if (area === 'new') return follow(feed, oneLink(feed, title => title === 'все новинки'), load);
 if (area === 'series') {
  const links = flibustaNavigation(feed);
  if (links.length === 1 && /^все книги(?: серии)?$/.test(normalized(links[0].title))) return follow(feed, links[0], load, true);
 }
 return feed;
}

export class FlibustaSearchUnavailable extends Error {
 constructor(kind: FlibustaSearchKind) {
  super(kind === 'series' ? 'Флибуста не предоставила поиск по сериям. Откройте серию через алфавит или отфильтруйте текущий список.'
   : `Каталог не предоставил поиск ${kind === 'authors' ? 'по авторам' : 'по книгам'}.`);
  this.name = 'FlibustaSearchUnavailable';
 }
}

/** Ask the published search endpoint, then follow its actual authors/books scope link. */
async function searchScope(rootFeed: Feed, kind: FlibustaSearchKind, query: string, load: FlibustaLoader): Promise<Feed> {
 const target = rootFeed.search?.url;
 if (typeof target !== 'string' || !target || !query.trim()) throw new FlibustaSearchUnavailable(kind);
 const result = await load(target, query);
 const scoped = oneLink(result, title => title === searchTitles[kind]);
 if (scoped) return load(scoped.url);
 const area = getFeedArea(result);
 if ((kind === 'books' && (result.entries.length || area === 'books')) || (kind === 'authors' && area === 'authors')
  || (kind === 'series' && area === 'series')) return result;
 throw new FlibustaSearchUnavailable(kind);
}

/** The catalog may have no series search; open its published alphabetical index. */
export async function findFlibustaSeries(rootFeed: Feed, name: string, load: FlibustaLoader): Promise<Feed> {
 const tab=flibustaTabs(rootFeed).find(item=>item.id==='series');
 if(!tab)throw new FlibustaSearchUnavailable('series');
 const index=await load(tab.url),initial=[...name.trim()][0]?.toLocaleUpperCase();
 const letters=uniqueLinks(index.navigation.filter(link=>link.title.trim().toLocaleUpperCase()===initial));
 return letters.length===1?load(letters[0].url):index;
}

const nameWords=(value:string)=>normalized(value).replace(/ё/g,'е').match(/[\p{L}\p{N}]+/gu)||[];
const latinName=(value:string)=>value.replace(/дж/g,'j').replace(/[а-я]/g,c=>({а:'a',б:'b',в:'v',г:'g',д:'d',е:'e',ж:'zh',з:'z',и:'i',й:'i',к:'k',л:'l',м:'m',н:'n',о:'o',п:'p',р:'r',с:'s',т:'t',у:'u',ф:'f',х:'kh',ц:'ts',ч:'ch',ш:'sh',щ:'shch',ъ:'',ы:'y',ь:'',э:'e',ю:'yu',я:'ya'}[c]||c)).replace(/y/g,'i').replace(/w/g,'u');
const authorLinks=(feed:Feed)=>uniqueLinks(feed.navigation.filter(link=>flibustaNavRole(link,feed)==='author'));

/** Some catalogs search name fields separately and reject even their own full display name. */
export async function searchFlibusta(root:Feed,kind:FlibustaSearchKind,query:string,load:FlibustaLoader):Promise<Feed>{
 const exact=await searchScope(root,kind,query,load);
 const words=[...new Set(nameWords(query))];
 if(kind!=='authors'||words.length<2||authorLinks(exact).length)return exact;
 const candidates:Feed['navigation']=[];
 // Longest terms usually identify the surname. Bound work rather than crawling the author index.
 for(const term of [...words].filter(word=>word.length>1).sort((a,b)=>b.length-a.length).slice(0,3)){
  let page=await searchScope(root,'authors',term,load);
  for(let i=0;i<2;i++){
   candidates.push(...authorLinks(page));
   const matches=uniqueLinks(candidates).filter(link=>{const names=nameWords(link.title).map(latinName);return words.every(word=>names.some(name=>name.startsWith(latinName(word))))});
   if(matches.length)return {...exact,navigation:[...exact.navigation.filter(link=>flibustaNavRole(link,exact)!=='author'),...matches],next:undefined,prev:undefined};
   if(!page.next)break;
   page=await load(page.next);
  }
 }
 return {...exact,navigation:[...exact.navigation,...uniqueLinks(candidates)],next:undefined,prev:undefined,search_notice:candidates.length?'Полное имя не найдено. Ниже — совпадения по отдельным словам запроса.':undefined};
}

export async function searchFlibustaBoth(root:Feed,first:'books'|'authors',query:string,load:FlibustaLoader):Promise<Feed>{
 const results=await Promise.allSettled([searchFlibusta(root,'books',query,load),searchFlibusta(root,'authors',query,load)]);
 if(results.every(result=>result.status==='rejected'))throw (results[0] as PromiseRejectedResult).reason;
 const books=results[0].status==='fulfilled'?results[0].value:null,authors=results[1].status==='fulfilled'?results[1].value:null;
 const primary=(first==='books'?books:authors)||books||authors;
 return {...primary,title:`Поиск: ${query}`,entries:books?.entries||[],navigation:authors?.navigation||[],next:undefined,prev:undefined,
  search:root.search,search_results:{query,books,authors,books_error:results[0].status==='rejected'?String(results[0].reason.message||results[0].reason):'',authors_error:results[1].status==='rejected'?String(results[1].reason.message||results[1].reason):''}};
}
