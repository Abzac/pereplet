<script lang="ts">
 import {tick} from 'svelte';
 import {DotsThree,Books,Stack,Archive,ArrowUUpLeft,Info,Heart,CheckCircle,BookOpen,Circle} from 'phosphor-svelte';
 import {mediaType} from './library-scope';
 import {normalizeReadStatus} from './reading-status';import type {ReadingStatus} from './reading-status';
 import type {Book} from './types';

 export let book:Book;
 export let busy=false;
 export let onmedia:(book:Book,type:'book'|'comic')=>void;
 export let onarchive:(book:Book,archived:boolean)=>void;
 export let ondetails:(book:Book)=>void;
 export let onseries:(book:Book)=>void;
 export let onstatus:(book:Book,status:ReadingStatus)=>void;
 export let onplanned:(book:Book)=>void;
 let open=false,trigger:HTMLButtonElement,menu:HTMLDivElement,container:HTMLDivElement,left=16,top=16;
 $: menuId=`book-actions-${book.id}`;
 $: comic=mediaType(book)==='comic';
 $: archived=book.archived===true;
 $: status=normalizeReadStatus(book.status);
 $: planned=status==='planned';

 function close(returnFocus=false){open=false;if(returnFocus&&trigger?.isConnected)trigger.focus({preventScroll:true})}
 function position(){
  if(!open||!trigger||!menu)return;
  const rect=trigger.getBoundingClientRect(),width=menu.offsetWidth,height=menu.offsetHeight;
  // The menu must remain reachable near the edges of a scrollable grid/table.
  left=Math.max(12,Math.min(rect.right-width,innerWidth-width-12));
  const below=rect.bottom+6;
  top=Math.max(12,Math.min(below+height>innerHeight-12?rect.top-height-6:below,innerHeight-height-12));
 }
 function items(){return Array.from(menu?.querySelectorAll<HTMLButtonElement>('button:not([disabled])')||[])}
 async function show(last=false){
  if(busy)return;open=true;await tick();position();const buttons=items();(last?buttons.at(-1):buttons[0])?.focus({preventScroll:true});
 }
 function toggle(){if(open)close(true);else void show()}
 function triggerKey(event:KeyboardEvent){if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();void show(event.key==='ArrowUp')}}
 function menuKey(event:KeyboardEvent){
  const buttons=items(),index=buttons.indexOf(document.activeElement as HTMLButtonElement);
  if(event.key==='Tab'){close(true);return;}
  if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
   event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
   buttons[next]?.focus({preventScroll:true});
  }
 }
 function run(action:()=>void){if(busy)return;close(true);action()}
 function togglePlan(){if(busy)return;close();onplanned(book)}
 function dismiss(node:HTMLElement){
  const outside=(event:PointerEvent)=>{if(open&&!container.contains(event.target as Node))close()};
  const focus=(event:FocusEvent)=>{if(open&&!container.contains(event.target as Node))close()};
  const escape=(event:KeyboardEvent)=>{if(open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true)}};
  const scroll=(event:Event)=>{if(open&&!menu?.contains(event.target as Node))close()};
  document.addEventListener('pointerdown',outside);document.addEventListener('focusin',focus);document.addEventListener('keydown',escape,true);document.addEventListener('scroll',scroll,true);window.addEventListener('resize',position);
  return{destroy(){document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',focus);document.removeEventListener('keydown',escape,true);document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',position)}};
 }
</script>

<div class="book-actions" class:is-open={open} bind:this={container}>
 <button class="book-planned-trigger" class:is-planned={planned} aria-label={`${planned?'Убрать из «Хочу прочитать»':'Хочу прочитать'}: ${book.title}`} title={planned?'Убрать из «Хочу прочитать»':'Хочу прочитать'} aria-pressed={planned} disabled={busy} onclick={togglePlan}><Heart size={20} weight={planned?'fill':'regular'}/></button>
 <button class="book-actions-trigger" bind:this={trigger} aria-label={`Действия: ${book.title}`} title="Действия с изданием" aria-haspopup="menu" aria-expanded={open} aria-controls={open?menuId:undefined} disabled={busy} onclick={toggle} onkeydown={triggerKey}><DotsThree size={22} weight="bold"/></button>
 {#if open}<div class="book-actions-menu" bind:this={menu} use:dismiss id={menuId} role="menu" aria-label={`Действия с изданием ${book.title}`} tabindex="-1" onkeydown={menuKey} style:left={`${left}px`} style:top={`${top}px`}>
  <button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>ondetails(book))}><Info size={18}/><span>Сведения о книге</span></button>
  <div class="book-actions-divider" role="separator"></div>
  <button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onplanned(book))}><Heart size={18} weight={planned?'fill':'regular'}/><span>{planned?'Убрать из «Хочу прочитать»':'Хочу прочитать'}</span></button>
  <button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onstatus(book,status==='read'?'reading':'read'))}>{#if status==='read'}<BookOpen size={18}/><span>Вернуть в «Сейчас читаю»</span>{:else}<CheckCircle size={18}/><span>Отметить прочитанным</span>{/if}</button>
  {#if status!=='reading'&&status!=='read'}<button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onstatus(book,'reading'))}><BookOpen size={18}/><span>Сейчас читаю</span></button>{/if}
  {#if status!=='unread'}<button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onstatus(book,'unread'))}><Circle size={18}/><span>Отметить неначатым</span></button>{/if}
  <div class="book-actions-divider" role="separator"></div>
  <button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onseries(book))}><Stack size={18}/><span>Назначить серию</span></button>
  <button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onmedia(book,comic?'book':'comic'))}>{#if comic}<Books size={18}/>{:else}<Stack size={18}/>{/if}<span>{comic?'В книги':'В комиксы'}</span></button>
  <div class="book-actions-divider" role="separator"></div>
  <button role="menuitem" tabindex="-1" disabled={busy} onclick={()=>run(()=>onarchive(book,!archived))}>{#if archived}<ArrowUUpLeft size={18}/>{:else}<Archive size={18}/>{/if}<span>{archived?'Восстановить из архива':'В архив'}</span></button>
 </div>{/if}
</div>

<style>
 .book-actions{display:inline-flex;gap:4px;flex:none;position:relative;vertical-align:middle}.book-actions.is-open{z-index:70}
 .book-actions-trigger,.book-planned-trigger{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;padding:4px;border:1px solid var(--line);border-radius:7px;background:var(--surface);color:var(--text);box-shadow:0 2px 5px #00000012;opacity:1}
 .book-actions-trigger:hover,.book-actions-trigger[aria-expanded=true],.book-planned-trigger:hover,.book-planned-trigger.is-planned{background:var(--surface-alt);border-color:var(--accent);color:var(--accent)}
 .book-actions-trigger:focus-visible,.book-planned-trigger:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
 :global(.book-card)>.book-actions{position:absolute;right:4px;top:4px;z-index:5}:global(.book-card)>.book-actions.is-open{z-index:70}
 .book-actions-menu{position:fixed;z-index:70;width:min(238px,calc(100vw - 24px));max-height:calc(100vh - 24px);overflow:auto;box-sizing:border-box;background:var(--surface);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:6px;box-shadow:0 10px 30px #0003;text-align:left}
 .book-actions-menu>button{display:flex;width:100%;min-height:40px;justify-content:flex-start;gap:10px;padding:10px;border:0;background:transparent;border-radius:5px;font-size:12px;line-height:1.4;text-align:left}
 .book-actions-menu>button:hover,.book-actions-menu>button:focus-visible{background:var(--surface-alt);color:var(--accent)}.book-actions-menu>button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
 .book-actions-divider{height:1px;background:var(--line);margin:5px 4px}
</style>
