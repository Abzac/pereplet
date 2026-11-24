export type RecentSearch={query:string;time:number};
type HistoryGroup={scope:string;items:RecentSearch[]};
type StorageLike=Pick<Storage,'getItem'|'setItem'>;
const key='pereplet.search-history.v1',maxGroups=32,maxItems=20;
function storage():StorageLike|null{try{return localStorage}catch{return null}}
function read(store:StorageLike|null):HistoryGroup[]{
 try{const parsed=JSON.parse(store?.getItem(key)||'[]');if(!Array.isArray(parsed))return [];
  return parsed.filter(group=>typeof group?.scope==='string'&&group.scope.length<=240&&Array.isArray(group.items)).slice(0,maxGroups).map(group=>({scope:group.scope,items:group.items.filter(item=>typeof item?.query==='string'&&item.query.trim()&&item.query.length<=160&&Number.isFinite(item.time)).slice(0,maxItems)}));
 }catch{return []}
}
function write(groups:HistoryGroup[],store:StorageLike|null){try{store?.setItem(key,JSON.stringify(groups.slice(0,maxGroups)))}catch{/* History is optional if browser storage is full or disabled. */}}
export function recentSearches(scope:string,store:StorageLike|null=storage()):RecentSearch[]{return read(store).find(group=>group.scope===scope)?.items||[]}
export function rememberSearch(scope:string,query:string,store:StorageLike|null=storage(),time=Date.now()){
 const value=query.trim().replace(/\s+/gu,' ').slice(0,160);if(!value||!scope||scope.length>240)return;
 const groups=read(store),old=groups.find(group=>group.scope===scope)?.items||[],folded=value.toLocaleLowerCase();
 const items=[{query:value,time},...old.filter(item=>item.query.toLocaleLowerCase()!==folded)].slice(0,maxItems);
 write([{scope,items},...groups.filter(group=>group.scope!==scope)],store);
}
export function removeSearch(scope:string,query:string,store:StorageLike|null=storage()){
 const groups=read(store);for(const group of groups)if(group.scope===scope)group.items=group.items.filter(item=>item.query!==query);write(groups.filter(group=>group.items.length),store);
}
export function clearSearches(scope:string,store:StorageLike|null=storage()){write(read(store).filter(group=>group.scope!==scope),store)}
