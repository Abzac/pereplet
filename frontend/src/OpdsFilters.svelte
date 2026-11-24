<script lang="ts">
 import {tick} from 'svelte';
 import {Funnel,X} from 'phosphor-svelte';
 import {defaultOpdsFilters,activeOpdsFilterCount,type OpdsFilterState} from './opds-filters';
 export let filters:OpdsFilterState={...defaultOpdsFilters};
 export let onchange:(filters:OpdsFilterState)=>void;
 export let label='Фильтры каталога';export let sourceNote='По данным каталога. Книги без указанных авторов тоже показываются.';export let idPrefix='opds-filter';
 let open=false,trigger:HTMLButtonElement,popover:HTMLDivElement,popoverLeft=16,popoverTop=16;
 $: count=activeOpdsFilterCount(filters);
 function update(change:Partial<OpdsFilterState>){filters={...filters,...change};onchange(filters)}
 function position(){if(!open||!trigger||!popover)return;const rect=trigger.getBoundingClientRect(),width=popover.offsetWidth,height=popover.offsetHeight;popoverLeft=Math.max(16,Math.min(rect.right-width,innerWidth-width-16));popoverTop=Math.max(16,Math.min(rect.bottom+8,innerHeight-height-16))}
 async function toggle(){open=!open;if(open){await tick();position();popover?.querySelector<HTMLElement>('input,select')?.focus()}}
 function close(returnFocus=false){open=false;if(returnFocus)trigger?.focus()}
 function dismiss(node:HTMLElement){
  const outside=(event:PointerEvent)=>{if(open&&!node.contains(event.target as Node))close()};
  const escape=(event:KeyboardEvent)=>{if(open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true)}};
  const focus=(event:FocusEvent)=>{if(open&&!node.contains(event.target as Node))close()};
  document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape,true);document.addEventListener('focusin',focus);window.addEventListener('resize',position);document.addEventListener('scroll',position,true);
  return{destroy(){document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape,true);document.removeEventListener('focusin',focus);window.removeEventListener('resize',position);document.removeEventListener('scroll',position,true)}};
 }
</script>

<div class="opds-filters" use:dismiss>
 <button class="filter-trigger" class:active={count>0} bind:this={trigger} aria-label={count?`${label}: ${count}`:label} aria-expanded={open} aria-controls={`${idPrefix}-popover`} onclick={toggle}><Funnel size={17}/><span>Фильтры</span>{#if count}<span class="filter-count">{count}</span>{/if}</button>
 {#if open}<div class="filter-popover" id={`${idPrefix}-popover`} bind:this={popover} role="dialog" aria-label={label} tabindex="-1" style:left={`${popoverLeft}px`} style:top={`${popoverTop}px`}>
  <div class="filter-heading"><strong>{label}</strong><button class="icon-button" aria-label="Закрыть фильтры" onclick={()=>close(true)}><X size={17}/></button></div>
  <label class="filter-check"><input type="checkbox" checked={filters.maxTwoAuthors} onchange={event=>update({maxTwoAuthors:event.currentTarget.checked})}/>Не больше двух авторов</label>
  <p class="filter-note">{sourceNote}</p>
  <label class="filter-label" for={`${idPrefix}-language`}>Язык книги</label>
  <select id={`${idPrefix}-language`} value={filters.language} onchange={event=>update({language:event.currentTarget.value as OpdsFilterState['language']})}>
   <option value="all">Все языки</option><option value="ru">Русский</option><option value="en">Английский</option><option value="ru-en-unknown">Русский, английский и не указан</option>
  </select>
  <label class="filter-label" for={`${idPrefix}-litres`}>Метка «litres» в названии</label>
  <select id={`${idPrefix}-litres`} value={filters.litres} onchange={event=>update({litres:event.currentTarget.value as OpdsFilterState['litres']})}>
   <option value="all">Все книги</option><option value="only">Только с «litres»</option><option value="exclude">Без «litres»</option>
  </select>
  <p class="filter-note">Латиницей, без учёта регистра.</p>
  <button class="filter-reset" disabled={!count} onclick={()=>update({...defaultOpdsFilters})}>Сбросить фильтры</button>
 </div>{/if}
</div>

<style>
 .opds-filters{position:relative;flex:none}.filter-trigger{display:flex;align-items:center;gap:7px;min-height:36px;padding:8px 11px;font-size:11px}.filter-trigger.active{border-color:var(--accent);color:var(--accent)}
 .filter-count{display:inline-flex;align-items:center;justify-content:center;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:var(--accent);color:white;font-size:10px}
 .filter-popover{position:fixed;z-index:45;width:min(310px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;background:var(--surface);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);padding:16px;color:var(--text);text-align:left}
 .filter-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:16px}.filter-heading>strong{font-size:13px;font-weight:600}.filter-heading .icon-button{width:28px;height:28px;min-width:28px;padding:4px}
 .filter-check{display:flex;align-items:center;gap:9px;font-size:12px;line-height:1.5;cursor:pointer}.filter-check input{width:16px;height:16px;margin:0;accent-color:var(--accent);flex:none}
 .filter-note{font-size:10px;line-height:1.55;color:var(--muted);margin:8px 0 0}.filter-label{display:block;font-size:11px;margin:17px 0 8px}.filter-popover select{display:block;width:100%;min-height:36px;padding:7px 9px;font-size:11px;box-sizing:border-box}
 .filter-reset{width:100%;min-height:34px;margin-top:18px;font-size:11px}
</style>
