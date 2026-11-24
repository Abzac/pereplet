import type {Entry,Feed} from './types';
import {matchesOpdsFilters,activeOpdsFilterCount} from './opds-filters';
import type {OpdsFilterState} from './opds-filters';

interface Section {books:Entry[];savedAt:number}
const address=(value:string)=>{try{const url=new URL(value);url.hash='';return url.href}catch{return value}};

/** Reuses already visited, complete series. It never requests a feed or a book. */
export class OpdsFilterSections {
 private sections=new Map<string,Section>();
 private readonly maxSections:number;
 private readonly maxEntries:number;
 private readonly maxBooks:number;
 private readonly ttlMs:number;
 private readonly now:()=>number;
 constructor(options:{maxSections?:number;maxEntries?:number;maxBooks?:number;ttlMs?:number;now?:()=>number}={}){
  this.maxSections=Math.max(1,Math.min(options.maxSections??50,50));
  this.maxEntries=Math.max(1,Math.min(options.maxEntries??600,600));
  this.maxBooks=Math.max(1,Math.min(options.maxBooks??6000,6000));
  this.ttlMs=Math.max(1,Math.min(options.ttlMs??600_000,600_000));
  this.now=options.now??Date.now;
 }
 get size(){this.expire();return this.sections.size}
 private key(catalogId:string,url:string){return JSON.stringify([catalogId,address(url)])}
 private expire(){const now=this.now();for(const [key,value] of this.sections)if(now-value.savedAt>=this.ttlMs)this.sections.delete(key)}
 private isLeafSeries(feed:Feed):boolean{
  let series=/^(?:книги в серии|все книги серии|книги серии|books in series)\s+/i.test(feed.title||'');
  try{series ||= /\/(?:sequence|authorsequence|series)\/[^/]+/i.test(new URL(feed.url).pathname)}catch{}
  if(!series||feed.next||feed.prev)return false;
  return !(feed.navigation||[]).some(link=>address(link.url)!==address(feed.up||'')&&address(link.url)!==address(feed.url)&&! /^(?:начало каталога|на уровень выше|home|start)$/i.test(link.title.trim()));
 }
 /** False means incomplete/unsupported metadata; previous knowledge is discarded too. */
 record(catalogId:string,feed:Feed):boolean{
  this.expire();const key=this.key(catalogId,feed.url);this.sections.delete(key);
  if(!this.isLeafSeries(feed)||feed.entries.length>this.maxEntries||feed.entries.length>this.maxBooks)return false;
  const books:Entry[]=[];
  for(const entry of feed.entries){
   const title=entry.title||'';
   // Three distinct names are sufficient for the current <=2-author filter.
   const authors=[...new Set([...(entry.authors||[]),...(entry.author_details||[]).map(item=>item.name)].map(name=>name.trim().toLocaleLowerCase('ru').replace(/\s+/g,' ')).filter(Boolean))].slice(0,3);
   const languages=[...new Set(entry.languages||[])];
   // Do not truncate searchable fields and accidentally turn a match into a miss.
   if(title.length>2000||authors.some(name=>name.length>300)||languages.length>20||languages.some(language=>language.length>32))return false;
   books.push({id:'',title,authors,languages,acquisitions:[]});
  }
  this.sections.set(key,{books,savedAt:this.now()});
  let count=[...this.sections.values()].reduce((total,section)=>total+section.books.length,0);
  while(this.sections.size>this.maxSections||count>this.maxBooks){const oldest=this.sections.keys().next().value!;count-=this.sections.get(oldest)!.books.length;this.sections.delete(oldest)}
  return true;
 }
 shouldHide(catalogId:string,url:string,filters:OpdsFilterState):boolean{
  if(!activeOpdsFilterCount(filters))return false;
  this.expire();const key=this.key(catalogId,url),section=this.sections.get(key);
  if(!section)return false;
  this.sections.delete(key);this.sections.set(key,section);
  return !section.books.some(book=>matchesOpdsFilters(book,filters));
 }
 clear(){this.sections.clear()}
}
