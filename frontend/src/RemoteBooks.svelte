<script lang="ts">
 import {BookOpen,Download,Clock} from 'phosphor-svelte';import Cover from './Cover.svelte';import type {Entry} from './types';
 import {acquisitionFormat,remoteSizeLabel,remoteSizeTitle,sortEntriesInSeries,compareSeriesPositions,type SeriesScope} from './book-metadata';
 export let entries:Entry[]=[];export let view:'grid'|'list'|'table'='grid';export let coverSize=180;
 export let seriesScope:SeriesScope|undefined=undefined;
 export let downloads:Record<string,boolean>={};export let batchBusy=false;export let selectedId='';
 export let onselect:(entry:Entry)=>void;export let ondownload:(entry:Entry)=>void;
 type SortKey='title'|'authors'|'series';let sortKey:SortKey|null=null,sortDirection:1|-1=1;
 const collator=new Intl.Collator('ru',{numeric:true,sensitivity:'base'});
 function authors(entry:Entry){return entry.authors?.filter(Boolean).join(', ')||'Автор не указан'}
 function series(entry:Entry){return(entry.series||[]).map(item=>`${item.name}${item.position!==undefined&&item.position!==null&&item.position!==''?` · ${item.position}`:''}`).join('; ')}
 function formats(entry:Entry){return [...new Set((entry.acquisitions||[]).map(acquisitionFormat))].join(' · ')}
 function sortValue(entry:Entry,key:SortKey){return key==='authors'?(entry.authors||[]).join(', '):key==='series'?series(entry):entry.title||''}
 function sorted(source:Entry[],key:SortKey|null,direction:1|-1){
  if(!key)return source;
  return source.map((entry,index)=>({entry,index})).sort((a,b)=>{
   const left=sortValue(a.entry,key),right=sortValue(b.entry,key);
   if(!left||!right)return left?-1:right?1:a.index-b.index;
   if(key==='series'){
    const aSeries=a.entry.series?.[0],bSeries=b.entry.series?.[0];
    const nameOrder=collator.compare(aSeries?.name||'',bSeries?.name||'');
    return nameOrder*direction||compareSeriesPositions(aSeries?.position,bSeries?.position,direction)||a.index-b.index;
   }
   return collator.compare(left,right)*direction||a.index-b.index;
  }).map(item=>item.entry);
 }
 $: shown=sortKey?sorted(entries,sortKey,sortDirection):sortEntriesInSeries(entries,seriesScope);
 function setSort(key:SortKey){sortDirection=sortKey===key?(sortDirection===1?-1:1):1;sortKey=key}
 function ariaSort(key:SortKey,active:SortKey|null,direction:1|-1):'ascending'|'descending'|'none'{return active===key?(direction===1?'ascending':'descending'):'none'}
 function unavailable(entry:Entry){return !entry.local_book_id&&!entry.acquisitions?.length}
 function actionLabel(entry:Entry,downloading:boolean){return downloading?'Скачиваем…':entry.local_book_id?'Читать':unavailable(entry)?entry.unavailable_reason||'Нет поддерживаемого формата':'В библиотеку'}
</script>

{#snippet action(entry:Entry)}
 <button class="download-book remote-action" class:unavailable={unavailable(entry)} disabled={!!downloads[entry.id]||(!entry.local_book_id&&(!entry.acquisitions?.length||batchBusy))} title={unavailable(entry)?entry.unavailable_reason||'Каталог не предоставил ссылку на поддерживаемый формат':undefined} onclick={()=>ondownload(entry)}>
  {#if downloads[entry.id]}<Clock size={16}/>{:else if entry.local_book_id}<BookOpen size={16}/>{:else if !unavailable(entry)}<Download size={16}/>{/if}<span>{actionLabel(entry,!!downloads[entry.id])}</span>
 </button>
{/snippet}

{#if view==='grid'}
 <div class="book-grid remote-grid remote-books" style={`--cover-size:${coverSize}px`} role="list" aria-label="Книги каталога">
  {#each shown as entry (entry.id)}
   <article class="book-card" class:selected={selectedId===entry.id} role="listitem" data-entry-id={entry.id}>
    <button class="cover-button" aria-label={`Сведения о книге ${entry.title}`} onclick={()=>onselect(entry)}><Cover book={entry}/></button>
    <button class="book-name" title={entry.title} onclick={()=>onselect(entry)}>{entry.title}</button><p title={authors(entry)}>{authors(entry)}</p>
    <span class="remote-series" title={series(entry)}>{series(entry)||'\u00a0'}</span><span class="remote-formats">{formats(entry)||'\u00a0'}<span class="remote-size" title={remoteSizeTitle(entry)}>{remoteSizeLabel(entry)||'\u00a0'}</span></span>
    {@render action(entry)}
   </article>
  {/each}
 </div>
{:else if view==='list'}
 <ul class="remote-list remote-books" aria-label="Книги каталога">
  {#each shown as entry (entry.id)}
   <li class:selected={selectedId===entry.id} data-entry-id={entry.id}>
    <button class="remote-cover" aria-label={`Сведения о книге ${entry.title}`} onclick={()=>onselect(entry)}><Cover book={entry}/></button>
    <div class="remote-list-info"><button class="remote-title" title={entry.title} onclick={()=>onselect(entry)}>{entry.title}</button><p class="remote-authors">{authors(entry)}</p>{#if series(entry)}<p class="remote-list-series">{series(entry)}</p>{/if}<p class="remote-formats">{formats(entry)||'Формат не указан'}{#if remoteSizeLabel(entry)}<span class="remote-size" title={remoteSizeTitle(entry)}>{remoteSizeLabel(entry)}</span>{/if}</p></div>
    <div class="remote-list-action">{@render action(entry)}</div>
   </li>
  {/each}
 </ul>
{:else}
 <div class="remote-table-wrap remote-books">
  <table class="remote-table" aria-label="Книги каталога">
   <thead><tr>
    {#each [{key:'title',name:'Название'},{key:'authors',name:'Авторы'},{key:'series',name:'Серия'}] as column}<th scope="col" aria-sort={ariaSort(column.key as SortKey,sortKey,sortDirection)}><button class="remote-sort" onclick={()=>setSort(column.key as SortKey)}>{column.name}<span aria-hidden="true">{sortKey===column.key?(sortDirection===1?'▲':'▼'):'↕'}</span></button></th>{/each}
    <th scope="col">Формат / размер</th><th scope="col"><span class="visually-hidden">Действие</span></th>
   </tr></thead>
   <tbody>{#each shown as entry (entry.id)}<tr class:selected={selectedId===entry.id} data-entry-id={entry.id}>
    <td><div class="remote-table-title"><button class="remote-cover compact" aria-label={`Сведения о книге ${entry.title}`} onclick={()=>onselect(entry)}><Cover book={entry}/></button><button class="remote-title" title={entry.title} onclick={()=>onselect(entry)}>{entry.title}</button></div></td>
    <td class="remote-table-authors">{authors(entry)}</td><td class="remote-table-series">{series(entry)||'—'}</td><td><span class="remote-formats">{formats(entry)||'—'}{#if remoteSizeLabel(entry)}<span class="remote-size" title={remoteSizeTitle(entry)}>{remoteSizeLabel(entry)}</span>{/if}</span></td><td class="remote-table-action">{@render action(entry)}</td>
   </tr>{/each}</tbody>
  </table>
 </div>
{/if}

<style>
 .remote-books{min-width:0}.remote-action{gap:7px;min-height:36px;line-height:1.4}.remote-action>span{min-width:0}.remote-action.unavailable{color:var(--muted)}
 .remote-grid .remote-action{margin-top:auto}.remote-series{display:block;min-height:1.6em;max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:10px;color:var(--muted);margin-top:5px}
 .remote-formats{font-size:10px;line-height:1.6;color:var(--muted);overflow-wrap:anywhere}.remote-grid .remote-formats{min-height:1.6em;margin:4px 0 10px}
 .remote-size{display:block;font-variant-numeric:tabular-nums}.remote-grid .remote-size{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:100%}
 .remote-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;border-top:1px solid var(--line)}
 .remote-list>li{display:grid;grid-template-columns:72px minmax(0,1fr) minmax(140px,190px);align-items:center;gap:22px;padding:17px 10px;border-bottom:1px solid var(--line)}
 .remote-list>li.selected,.remote-table tr.selected{background:var(--surface-alt)}
 .remote-cover{padding:0;border:0;border-radius:0;background:transparent;width:72px;height:104px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
 .remote-cover:hover{background:transparent}.remote-cover :global(img){height:100%;max-width:100%;object-fit:contain;background:white;box-shadow:2px 3px 6px #0003}
 .remote-cover :global(.cover-art){height:100%;max-width:100%;width:auto}.remote-cover.compact{width:36px;height:52px}
 .remote-title{display:-webkit-box;-webkit-line-clamp:2;line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;max-width:100%;padding:0;border:0;border-radius:0;background:none;text-align:left;font-family:Literata,Georgia,serif;font-size:14px;line-height:1.5;overflow-wrap:anywhere}
 .remote-title:hover{color:var(--accent);background:none}.remote-list-info{min-width:0}.remote-list-info>p{margin:5px 0 0;font-size:11px;line-height:1.6;color:var(--muted)}
 .remote-list-info>.remote-list-series{color:var(--text);opacity:.8}.remote-list-info>.remote-formats{font-size:10px}.remote-list-action .remote-action{margin:0}
 .remote-table-wrap{overflow:auto;border-top:1px solid var(--line)}.remote-table{width:100%;min-width:640px;border-collapse:collapse;table-layout:fixed;font-size:12px}
 .remote-table th,.remote-table td{padding:11px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle;overflow-wrap:anywhere}
 .remote-table th{font-size:10px;font-weight:500;color:var(--muted)}.remote-table th:first-child{width:32%}.remote-table th:nth-child(2){width:19%}.remote-table th:nth-child(3){width:17%}.remote-table th:nth-child(4){width:11%}.remote-table th:last-child{width:21%}
 .remote-sort{padding:3px 0;display:flex;width:100%;justify-content:space-between;border:0;background:none;color:inherit;font-size:10px;text-align:left}.remote-sort:hover{background:none;color:var(--accent)}.remote-sort>span{font-size:9px;opacity:.7}
 .remote-table-title{display:flex;gap:12px;align-items:center;min-width:0}.remote-table-title>.remote-title{font-family:inherit;font-size:12px;line-height:1.5}.remote-table-authors,.remote-table-series{font-size:11px;line-height:1.6;color:var(--muted)}
 .remote-table-action .remote-action{width:100%;padding:7px 8px;margin:0;font-size:10px}.remote-table-action .remote-action>span{overflow-wrap:normal;word-break:normal}.remote-table-action .remote-action :global(svg){width:14px;height:14px;flex-shrink:0}
 .visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
 @media(max-width:1000px){.remote-list>li{grid-template-columns:64px minmax(0,1fr) minmax(120px,150px);gap:16px;padding-left:0;padding-right:0}.remote-list .remote-cover{width:64px;height:94px}}
</style>

