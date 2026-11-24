<script lang="ts">
 import {onMount,tick} from 'svelte';import {X} from 'phosphor-svelte';
 import {recentSearches,removeSearch,clearSearches} from './search-history';import type {RecentSearch} from './search-history';
 export let scope:string;export let label='Поиск';export let onselect:(query:string)=>void;export let input:HTMLInputElement;
 export let open=false;
 let items:RecentSearch[]=[],element:HTMLElement,previousScope=scope,suppressFocus=false;
 $: if(scope!==previousScope){previousScope=scope;items=open?recentSearches(scope):[]}
 export function show(){if(suppressFocus)return;items=recentSearches(scope);open=true}
 export function close(restoreFocus=false){open=false;if(restoreFocus){suppressFocus=true;input?.focus({preventScroll:true});suppressFocus=false}}
 function inside(target:Node){return element?.contains(target)||input?.closest('.global-search')?.contains(target)}
 function outside(event:Event){if(open&&!inside(event.target as Node))close()}
 function choices(){return Array.from(element?.querySelectorAll<HTMLButtonElement>('.recent-search-choice')||[])}
 export async function inputKey(event:KeyboardEvent){
  if(event.key==='Escape'&&open){event.preventDefault();event.stopPropagation();close(true);return;}
  if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;
  event.preventDefault();show();await tick();const buttons=choices();(event.key==='ArrowUp'?buttons.at(-1):buttons[0])?.focus();
 }
 function key(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
  if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
  const buttons=choices();if(!buttons.length)return;event.preventDefault();
  const active=document.activeElement as HTMLElement,index=buttons.indexOf(active?.closest('.recent-search-row')?.querySelector('.recent-search-choice') as HTMLButtonElement),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
  buttons[next]?.focus();
 }
 function choose(query:string){close(true);onselect(query)}
 async function remove(query:string){const index=items.findIndex(item=>item.query===query);removeSearch(scope,query);items=recentSearches(scope);await tick();const buttons=Array.from(element?.querySelectorAll<HTMLButtonElement>('.recent-search-row .icon-button')||[]);(buttons[Math.min(index,buttons.length-1)]||element?.querySelector<HTMLButtonElement>('.search-history-heading button'))?.focus()}
 async function clear(){clearSearches(scope);items=[];await tick();element?.querySelector<HTMLButtonElement>('.search-history-heading button')?.focus()}
 onMount(()=>{document.addEventListener('pointerdown',outside);document.addEventListener('focusin',outside);return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',outside)}});
</script>
<div class="search-history-control" bind:this={element}>
 {#if open}<div id="global-search-history" class="search-history-popup" role="dialog" aria-label="История поисковых запросов" tabindex="-1" onkeydown={key}>
  <div class="search-history-heading"><strong>{label}</strong><button class="icon-button" aria-label="Закрыть историю поиска" onclick={()=>close(true)}><X size={16}/></button></div>
  {#if items.length}<div class="recent-search-items">{#each items as item (item.query)}<div class="recent-search-row"><button class="recent-search-choice" title={item.query} onclick={()=>choose(item.query)}>{item.query}</button><button class="icon-button" aria-label={`Удалить запрос ${item.query}`} onclick={()=>remove(item.query)}><X size={14}/></button></div>{/each}</div><button class="text-button clear-search-history" onclick={clear}>Очистить эту историю</button>{:else}<p>Здесь появятся ваши поисковые запросы.</p>{/if}
 </div>{/if}
</div>
<style>
 :global(.global-search){position:relative}.search-history-control{display:contents}
 .search-history-popup{position:absolute;z-index:70;top:calc(100% + 8px);left:0;right:0;padding:12px;background:var(--surface);color:var(--text);border:1px solid var(--line);border-radius:9px;box-shadow:0 12px 35px #0003}
 .search-history-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 4px 8px;font-size:12px}.search-history-heading strong{font-weight:500}
 .recent-search-items{max-height:320px;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin}.recent-search-row{display:flex;gap:4px;align-items:center;border-radius:5px}.recent-search-row:hover{background:var(--surface-alt)}
 .recent-search-choice{justify-content:flex-start;flex:1;min-width:0;text-align:left;padding:9px 8px;border:0;background:transparent;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-search-row .icon-button{width:28px;height:30px;color:var(--muted)}
 .clear-search-history{width:100%;justify-content:flex-start;margin-top:8px;padding:9px 8px;font-size:11px;color:var(--muted);border-top:1px solid var(--line);border-radius:0}
 .search-history-popup p{font-size:12px;color:var(--muted);line-height:1.6;padding:8px}
 @media(max-width:650px){.search-history-popup{position:fixed;top:60px;left:16px;right:16px;width:auto;max-width:none}}
</style>
