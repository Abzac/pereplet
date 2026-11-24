<script lang="ts">
 import {BookOpen,Check} from 'phosphor-svelte';import Cover from './Cover.svelte';import BookActions from './BookActions.svelte';
 import {statusNames} from './types';import type {Book} from './types';import {normalizeReadStatus} from './reading-status';import type {ReadingStatus} from './reading-status';
 export let books:Book[]=[];export let view='grid';export let coverSize=180;export let selectedId='';export let selecting=false;export let selectedIds:string[]=[];export let busy=false;
 export let sortKey='title';export let sortDirection='asc';
 export let onselect:(book:Book)=>void;export let onread:(book:Book)=>void;export let onstatus:(book:Book,status:ReadingStatus)=>void;export let onplanned:(book:Book)=>void;
 export let onmedia:(book:Book,type:'book'|'comic')=>void;export let onarchive:(book:Book,archived:boolean)=>void;export let onseries:(book:Book)=>void;export let oncheck:(id:string,checked:boolean)=>void;export let onsort:(key:string)=>void;
 function author(book:Book){return book.authors?.filter(Boolean).join(', ')||book.author||'Автор не указан'}
 function series(book:Book){return book.series?`${book.series}${book.series_index!=null?` · ${book.series_index}`:''}`:''}
 function status(book:Book){return statusNames[normalizeReadStatus(book.status)]}
 function ariaSort(key:string):'ascending'|'descending'|'none'{return sortKey===key?(sortDirection==='desc'?'descending':'ascending'):'none'}
</script>

{#snippet selection(book:Book)}<label class="table-select"><input type="checkbox" aria-label={`Выбрать ${book.title}`} disabled={busy} checked={selectedIds.includes(book.id)} onchange={e=>oncheck(book.id,e.currentTarget.checked)}/></label>{/snippet}
{#snippet actions(book:Book)}<BookActions {book} {busy} {onmedia} {onarchive} {onseries} {onstatus} {onplanned} ondetails={onselect}/>{/snippet}

{#if view==='table'}
 <div class="book-table-wrap"><table class="book-table" aria-label="Издания библиотеки"><thead><tr>{#if selecting}<th aria-label="Выбор изданий"></th>{/if}
  {#each [{key:'title',label:'Книга'},{key:'author',label:'Автор'},{key:'series',label:'Серия'},{key:'progress',label:'Позиция'},{key:'format',label:'Формат'}] as col}<th aria-sort={ariaSort(col.key)}><button class="table-sort" class:active={sortKey===col.key} onclick={()=>onsort(col.key)}>{col.label}<span class="table-sort-indicator" aria-hidden="true">{sortKey===col.key?(sortDirection==='asc'?'▲':'▼'):'↕'}</span></button></th>{/each}<th aria-label="Действия"></th>
 </tr></thead><tbody>{#each books as book (book.id)}<tr class:selected={selectedId===book.id} data-book-id={book.id}>
  {#if selecting}<td>{@render selection(book)}</td>{/if}
  <td><button class="table-book" onclick={()=>onselect(book)}><Cover {book}/><span>{book.title}<small>{status(book)}</small></span></button></td><td>{author(book)}</td><td>{series(book)||'—'}</td><td title="Сохранённое место в книге; статус завершения задаётся отдельно">{Math.round(book.progress||0)}%</td><td><span class="format-tag">{book.format||'FB2'}</span></td>
  <td><div class="table-actions">{@render actions(book)}<button class="icon-button" title="Читать" aria-label={`Читать ${book.title}`} disabled={busy} onclick={()=>onread(book)}><BookOpen size={20}/></button></div></td>
 </tr>{/each}</tbody></table></div>
{:else if view==='list'}
 <ul class="local-book-list" aria-label="Издания библиотеки">{#each books as book (book.id)}<li class:selected={selectedId===book.id} data-book-id={book.id}>
  {#if selecting}{@render selection(book)}{/if}<button class="local-list-cover" aria-label={`Читать ${book.title}`} disabled={busy} onclick={()=>onread(book)}><Cover {book}/></button>
  <div class="local-list-info"><button class="book-name" onclick={()=>onselect(book)}>{book.title}</button><p>{author(book)}</p>{#if series(book)}<p>{series(book)}</p>{/if}<small>{book.format} · {status(book)}{book.last_opened?` · Позиция ${Math.round(book.progress||0)}%`:''}</small></div>
  <div class="local-list-actions">{@render actions(book)}<button class="secondary" disabled={busy} onclick={()=>onread(book)} aria-label={`Читать ${book.title}`}><BookOpen size={17}/><span>Читать</span></button></div>
 </li>{/each}</ul>
{:else}
 <div class="book-grid" class:shelf-grid={view==='shelf'} style={`--cover-size:${coverSize}px`}>
  {#each books as book (book.id)}<article class="book-card" class:selected={selectedId===book.id} data-book-id={book.id}>
   <BookActions {book} {busy} {onmedia} {onarchive} {onseries} {onstatus} {onplanned} ondetails={onselect}/>
   {#if selecting}<label class="book-select"><input type="checkbox" aria-label={`Выбрать ${book.title}`} disabled={busy} checked={selectedIds.includes(book.id)} onchange={e=>oncheck(book.id,e.currentTarget.checked)}/></label>{/if}
   <button class="cover-button" disabled={busy} onclick={()=>onread(book)} aria-label={`Читать ${book.title}`}><Cover {book}/>{#if normalizeReadStatus(book.status)==='read'}<span class="cover-status" title="Прочитано"><Check size={15}/></span>{/if}{#if normalizeReadStatus(book.status)==='reading'}<span class="cover-progress" title={`Позиция ${Math.round(book.progress||0)}%`}><span style:width={`${book.progress||0}%`}></span></span>{/if}<span class="cover-read"><BookOpen size={18}/>Читать</span></button>
   <button class="book-name" onclick={()=>onselect(book)}>{book.title}</button><p title={author(book)}>{author(book)}</p><span class="book-meta">{series(book)||status(book)}</span>
  </article>{/each}
 </div>
{/if}

<style>
 .local-book-list{list-style:none;margin:0;padding:0}.local-book-list>li{display:flex;align-items:center;gap:18px;padding:15px 6px;border-bottom:1px solid var(--line);min-width:0}.local-book-list>li.selected{background:var(--surface-alt)}
 .local-list-cover{width:62px;height:91px;flex:none;padding:0;border:0;background:transparent;display:flex;align-items:center;justify-content:center}.local-list-cover :global(img){display:block;width:auto;height:auto;max-width:100%;max-height:100%;object-fit:contain}.local-list-cover :global(.cover-art){height:100%;max-width:100%;width:auto}
 .local-list-info{flex:1;min-width:0}.local-list-info .book-name{font-size:15px}.local-list-info p{margin:6px 0;color:var(--muted);font-size:12px}.local-list-info small{color:var(--muted);font-size:11px}
 .local-list-actions{display:flex;align-items:center;gap:14px;flex:none}.local-list-actions>.secondary{font-size:11px}
 @media(max-width:700px){.local-book-list>li{gap:10px}.local-list-cover{width:45px;height:70px}.local-list-actions{flex-direction:column;gap:6px}.local-list-actions>.secondary{padding:6px 10px}.local-list-info .book-name{font-size:13px}}
</style>
