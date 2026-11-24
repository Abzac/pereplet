<script lang="ts">
 import {onDestroy} from 'svelte';
 import RemoteBooks from './RemoteBooks.svelte';
 import {OpdsPages} from './opds-paging';
 import {flibustaNavRole} from './flibusta';
 import {matchesOpdsFilters,groupOpdsSeries} from './opds-filters';
 import type {OpdsFilterState} from './opds-filters';
 import type {Feed,Entry} from './types';
 export let result:NonNullable<Feed['search_results']>;
 export let first:'books'|'authors'='books';
 export let filter='';export let filters:OpdsFilterState;
 export let view:'grid'|'list'|'table'='grid';export let coverSize=180;export let grouped=false;
 export let downloads:Record<string,boolean>={};export let batchBusy=false;export let selectedId='';
 export let load:(url:string)=>Promise<Feed>;
 export let onselect:(entry:Entry)=>void;export let ondownload:(entry:Entry)=>Promise<string|void>|void;
 async function download(entry:Entry){const local=await ondownload(entry);if(typeof local==='string'&&pages.books){pages.books.update(feed=>({...feed,entries:feed.entries.map(item=>item.id===entry.id?{...item,local_book_id:local}:item)}));pages={...pages}}}
 export let onbrowse:(url:string)=>void;export let onretry:()=>void;
 let source:typeof result,pages:{books:OpdsPages|null;authors:OpdsPages|null}={books:null,authors:null},busy={books:false,authors:false},errors={books:'',authors:''},generation=0;
 $: if(source!==result){source=result;generation++;pages={books:result.books?new OpdsPages(result.books):null,authors:result.authors?new OpdsPages(result.authors):null};errors={books:result.books_error,authors:result.authors_error};busy={books:false,authors:false}}
 $: order=first==='authors'?['authors','books'] as const:['books','authors'] as const;
 $: term=filter.trim().toLocaleLowerCase();
 $: entries=(pages.books?.feed.entries||[]).filter(entry=>(!term||[entry.title,...entry.authors].join(' ').toLocaleLowerCase().includes(term))&&matchesOpdsFilters(entry,filters));
 $: authors=(pages.authors?.feed.navigation||[]).filter(link=>flibustaNavRole(link,pages.authors?.feed)==='author'&&(!term||link.title.toLocaleLowerCase().includes(term)));
 async function more(kind:'books'|'authors'){
  const current=pages[kind],ticket=generation;if(!current?.canAppend||busy[kind])return;
  busy={...busy,[kind]:true};errors={...errors,[kind]:''};
  try{const next=await load(current.feed.next);if(ticket!==generation)return;current.append(current.feed.next,next);pages={...pages,[kind]:current}}catch(e){if(ticket===generation)errors={...errors,[kind]:e.message}}finally{if(ticket===generation)busy={...busy,[kind]:false}}
 }
 onDestroy(()=>generation++);
</script>
<div class="combined-search">
 {#each order as kind (kind)}
 <section class="search-result-section" aria-label={kind==='books'?'Книги по запросу':'Авторы по запросу'}>
  <div class="section-title"><h2>{kind==='books'?'Книги':'Авторы'} <span>{kind==='books'?entries.length:authors.length}</span></h2></div>
  {#if kind==='books'}
   {#if entries.length}
    {#if grouped}{#each groupOpdsSeries(entries) as group (group.name)}<section class="remote-series-group"><h2>{group.name||'Без серии'}<span>{group.entries.length}</span></h2><RemoteBooks entries={group.entries} {view} {coverSize} {downloads} {batchBusy} {selectedId} {onselect} ondownload={download}/></section>{/each}
    {:else}<RemoteBooks {entries} {view} {coverSize} {downloads} {batchBusy} {selectedId} {onselect} ondownload={download}/>{/if}
   {:else if !errors.books}<p class="muted">{filter?'В загруженных книгах нет совпадений с фильтром.':'По этому запросу книги не найдены.'}</p>{/if}
  {:else}
   {#if pages.authors?.feed.search_notice}<p class="muted small">{pages.authors.feed.search_notice}</p>{/if}
   {#if authors.length}<div class="flibusta-directory">{#each authors as author (author.url)}<button onclick={()=>onbrowse(author.url)}>{author.title}<span aria-hidden="true">›</span></button>{/each}</div>
   {:else if !errors.authors}<p class="muted">По этому запросу авторы не найдены.</p>{/if}
  {/if}
  {#if errors[kind]}<div class="inline-error" role="alert"><span>{errors[kind]}</span><button onclick={()=>pages[kind]?.feed.next?more(kind):onretry()}>Повторить поиск {kind==='books'?'книг':'авторов'}</button></div>{/if}
  {#if pages[kind]?.feed.next}<button class="load-more" disabled={busy[kind]} onclick={()=>pages[kind].canAppend?more(kind):onbrowse(pages[kind].feed.next)}>{busy[kind]?'Загружаем…':kind==='books'?'Показать ещё книги':'Показать ещё авторов'}</button>{/if}
 </section>
 {/each}
</div>
<style>
 .search-result-section+.search-result-section{border-top:1px solid var(--line);margin-top:28px;padding-top:24px}
 .section-title h2 span{font:12px Inter,sans-serif;color:var(--muted);margin-left:8px}
 .load-more{margin-top:20px}
</style>
