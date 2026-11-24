import type {CatalogLink, Entry} from './types';

export interface RelatedDestination {kind:'author'|'series';name:string;url?:string;position?:number|string}
const normalized=(value:string)=>(value||'').trim().toLocaleLowerCase().replace(/\s+/g,' ');
const isFeed=(link:CatalogLink)=>/atom\+xml|opds\+json/i.test(link.type||'')&&/^https?:\/\//i.test(link.url);
function kind(link:CatalogLink,flibusta:boolean):'author'|'series'|null {
 const rel=(link.rel||[]).join(' '),title=normalized(link.title||'');
 if(/(?:^|[\s/#])author(?:$|\s)/i.test(rel)||/^(?:все книги автора|книги автора|books by|author:)\s/.test(title))return 'author';
 if(/(?:^|[\s/#])(?:series|collection)(?:$|\s)/i.test(rel)||/^(?:все книги серии|книги серии|серия:|series:)\s/.test(title))return 'series';
 if(flibusta){try{const path=new URL(link.url).pathname;if(/\/opds\/author\//.test(path))return 'author';if(/\/opds\/(?:sequence|authorsequence)\//.test(path))return 'series'}catch{}}
 return null;
}
const cleanTitle=(title:string)=>title.replace(/^(?:все книги автора|книги автора|все книги серии|книги серии|books by|author:|series:|серия:)\s*/i,'').trim();

/** Never manufactures author IDs or routes from names. */
export function relatedDestinations(entry:Entry,flibusta=false):RelatedDestination[] {
 const links=(entry.related_links||[]).filter(link=>isFeed(link)&&!(link.rel||[]).some(rel=>['self','start','up','search'].includes(rel))),authors=[...new Set([...(entry.authors||[]),...(entry.author_details||[]).map(a=>a.name)].filter(Boolean))];
 const result:RelatedDestination[]=authors.map(name=>{
  const direct=(entry.author_details||[]).find(a=>normalized(a.name)===normalized(name))?.links?.find(isFeed);
  const candidates=links.filter(link=>(kind(link,flibusta)==='author'||normalized(link.title||'')===normalized(name))&&(normalized(cleanTitle(link.title||''))===normalized(name)||(authors.length===1&&!link.title)));
  return{kind:'author',name,url:direct?.url||(candidates.length===1?candidates[0].url:undefined)};
 });
 for(const series of entry.series||[]){
  const direct=series.links?.find(isFeed),candidates=links.filter(link=>(kind(link,flibusta)==='series'||normalized(link.title||'')===normalized(series.name))&&(normalized(cleanTitle(link.title||''))===normalized(series.name)||((entry.series||[]).length===1&&!link.title)));
  if(series.name)result.push({kind:'series',name:series.name,position:series.position,url:direct?.url||(candidates.length===1?candidates[0].url:undefined)});
 }
 for(const link of links){const role=kind(link,flibusta),name=cleanTitle(link.title||'');if(role&&name&&!result.some(item=>item.kind===role&&(item.url===link.url||normalized(item.name)===normalized(name))))result.push({kind:role,name,url:link.url})}
 return result;
}
