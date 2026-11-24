import type {Entry} from './types';
import {compareSeriesPositions} from './book-metadata';

export interface OpdsFilterState {
 maxTwoAuthors:boolean;
 language:'all'|'ru'|'en'|'ru-en-unknown';
 litres:'all'|'only'|'exclude';
}
export const defaultOpdsFilters:OpdsFilterState={maxTwoAuthors:false,language:'all',litres:'all'};
export function normalizeOpdsFilters(value:unknown):OpdsFilterState {
 const item=value&&typeof value==='object'?value as Partial<OpdsFilterState>:{};
 return {maxTwoAuthors:item.maxTwoAuthors===true,language:['all','ru','en','ru-en-unknown'].includes(item.language)?item.language:'all',litres:['all','only','exclude'].includes(item.litres)?item.litres:'all'};
}
export function activeOpdsFilterCount(filters:OpdsFilterState):number {
 return Number(filters.maxTwoAuthors)+Number(filters.language!=='all')+Number(filters.litres!=='all');
}
export function opdsAuthorCount(entry:Entry):number {
 return new Set([...(entry.authors||[]),...(entry.author_details||[]).map(author=>author.name)].map(name=>name.trim().toLocaleLowerCase('ru').replace(/\s+/g,' ')).filter(Boolean)).size;
}
export function opdsLanguages(entry:Entry):string[] {
 return [...new Set((entry.languages||[]).map(language=>language.trim().toLowerCase().replace(/_/g,'-').split('-')[0]).filter(language=>language&&language!=='und').map(language=>language==='rus'?'ru':language==='eng'?'en':language))];
}
export function matchesOpdsFilters(entry:Entry,filters:OpdsFilterState):boolean {
 if(filters.maxTwoAuthors&&opdsAuthorCount(entry)>2)return false;
 const languages=opdsLanguages(entry);
 if(filters.language==='ru'||filters.language==='en'){if(!languages.includes(filters.language))return false;}
 else if(filters.language==='ru-en-unknown'&&languages.length&&!languages.some(language=>language==='ru'||language==='en'))return false;
 const litres=(entry.title||'').toLocaleLowerCase('en').includes('litres');
 return filters.litres==='only'?litres:filters.litres==='exclude'?!litres:true;
}

/** Call after filtering. Each publication belongs only to its first named series. */
export function groupOpdsSeries(entries:Entry[]):Array<{name:string;entries:Entry[]}> {
 const groups=new Map<string,{name:string;entries:Entry[]}>(),primary=(entry:Entry)=>(entry.series||[]).find(series=>series.name?.trim());
 for(const entry of entries){const name=primary(entry)?.name.trim()||'',key=name.toLocaleLowerCase('ru').replace(/\s+/g,' ');let group=groups.get(key);if(!group){group={name,entries:[]};groups.set(key,group)}group.entries.push(entry)}
 return [...groups.values()].sort((a,b)=>(!a.name||!b.name)?(a.name?-1:b.name?1:0):a.name.localeCompare(b.name,'ru',{numeric:true,sensitivity:'base'})).map(group=>({...group,entries:[...group.entries].sort((a,b)=>compareSeriesPositions(primary(a)?.position,primary(b)?.position))}));
}
