<script lang="ts">
 import {onMount,tick} from 'svelte';import Cover from './Cover.svelte';import './reader-cover.css';import {api} from './api';import type {Book,Chapter} from './types';
 import {WholeBookPaginator,abortable,physicalPageCount,paginationSignature,paginationState} from './whole-book-pagination';import type {PaginationState} from './whole-book-pagination';
 export let book:Book;export let settings:any;export let frame:HTMLElement;export let flow:HTMLElement;export let columns=1;export let gap=64;export let onupdate:(state:PaginationState)=>void;
 const counter=new WholeBookPaginator<Chapter>();
 let mounted=false,disposed=false,revision=0,runEpoch=0,activeSignature='',timer:any,observer:ResizeObserver,observed:HTMLElement;
 let measureFrame:HTMLElement,measureFlow:HTMLElement,chapterIndex=-1,chapterHtml='',measuredWidth=1,measuredHeight=1,measuredColumns=1,measuredGap=64,flowStyle='';
 let frozenSettings:any={cover:'skip'},frozenBook:Book=book;
 export function retry(){activeSignature='';revision++}
 function styles(source:HTMLElement,width:number,height:number,cols:number){
  const computed=getComputedStyle(source),parts:string[]=[];
  for(const name of Array.from(computed))parts.push(`${name}:${computed.getPropertyValue(name)};`);
  return parts.join('')+`width:${width}px;height:${height}px;min-height:0;max-height:none;min-width:0;max-width:none;column-count:${cols};column-gap:${gap}px;transform:none!important;will-change:auto;visibility:hidden;`;
 }
 function withoutSources(html:string){
  const template=document.createElement('template');template.innerHTML=html;
  for(const image of Array.from(template.content.querySelectorAll('img'))){const source=image.getAttribute('src');if(source)image.setAttribute('data-measure-src',source);image.removeAttribute('src');image.removeAttribute('srcset')}
  for(const element of Array.from(template.content.querySelectorAll('[id]')))element.removeAttribute('id');
  return template.innerHTML;
 }
 async function imageReady(image:HTMLImageElement,signal:AbortSignal){
  const source=image.getAttribute('data-measure-src');if(source){image.loading='eager';image.src=source}
  let timeout:any;
  try{await abortable(Promise.race([image.decode().catch(()=>{}),new Promise<void>((_,reject)=>{timeout=setTimeout(()=>reject(new Error('Не удалось дождаться иллюстрации при подсчёте страниц')),8000)})]),signal)}
  finally{clearTimeout(timeout)}
 }
 async function measure(index:number,chapter:Chapter,signal:AbortSignal){
  signal.throwIfAborted();chapterIndex=index;chapterHtml=withoutSources(chapter.html);await tick();signal.throwIfAborted();
  await abortable(document.fonts.ready,signal);
  const images=Array.from(measureFlow.querySelectorAll('img'));let cursor=0;
  const decode=async()=>{while(cursor<images.length){signal.throwIfAborted();const image=images[cursor++];await imageReady(image,signal)}};
  await Promise.all(Array.from({length:Math.min(4,images.length)},decode));signal.throwIfAborted();
  await abortable(new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())),signal);signal.throwIfAborted();
  const count=physicalPageCount(measureFlow,measuredWidth,measuredColumns,measuredGap);
  chapterHtml='';chapterIndex=-1;await tick();return count;
 }
 function schedule(){
  if(!mounted||!frame||!flow||disposed)return;
  const width=frame.clientWidth,height=frame.clientHeight,count=book.chapters?.length||book.chapter_count||1;
  if(settings.layout==='scroll'||width<1||height<1){runEpoch++;clearTimeout(timer);counter.cancel();activeSignature='';chapterHtml='';chapterIndex=-1;return}
  const signature=paginationSignature(book.id,count,settings,width,height,columns,gap,book.cover_url||'');
  if(signature===activeSignature)return;const epoch=++runEpoch;activeSignature=signature;clearTimeout(timer);counter.cancel();chapterHtml='';chapterIndex=-1;
  onupdate?.(paginationState(signature,Array(count).fill(null)));
  const snapshotSettings={...settings},snapshotBook=book,snapshotColumns=columns,snapshotGap=gap;
  timer=setTimeout(()=>{
   if(disposed||signature!==activeSignature)return;
   frozenSettings=snapshotSettings;frozenBook=snapshotBook;measuredWidth=width;measuredHeight=height;measuredColumns=snapshotColumns;measuredGap=snapshotGap;flowStyle=styles(flow,width,height,snapshotColumns);
   void counter.start({signature,count,load:(index,signal)=>api<Chapter>(`/api/books/${snapshotBook.id}/chapters/${index}`,'GET',undefined,signal),measure,update:state=>onupdate?.(state)})
    .finally(()=>{if(!disposed&&epoch===runEpoch&&signature===activeSignature){chapterHtml='';chapterIndex=-1}});
  },180);
 }
 $: if(mounted&&frame&&frame!==observed){observer?.disconnect();observed=frame;observer=new ResizeObserver(()=>revision++);observer.observe(frame)}
 $: {book;settings;frame;flow;columns;gap;revision;mounted;schedule()}
 onMount(()=>{mounted=true;return()=>{disposed=true;counter.dispose();clearTimeout(timer);observer?.disconnect();chapterHtml=''}});
</script>

<div class="whole-book-measure" aria-hidden="true" inert style:width={`${measuredWidth}px`} style:height={`${measuredHeight}px`}>
 <div class="pagination-measure-viewport" bind:this={measureFrame} style:width={`${measuredWidth}px`} style:height={`${measuredHeight}px`}>
  <div class="pagination-measure-flow" bind:this={measureFlow} style={flowStyle}>
   {#if chapterIndex===0&&frozenSettings.cover!=='skip'}<div class:separate-cover={frozenSettings.cover==='separate'} class="book-cover-page"><Cover book={frozenBook} lazy={false}/></div>{/if}
   {@html chapterHtml}
  </div>
 </div>
</div>

<style>.whole-book-measure{position:fixed;left:-100000px;top:0;visibility:hidden;pointer-events:none;overflow:hidden;contain:layout style;z-index:-1000}.pagination-measure-viewport{position:relative;overflow:hidden}</style>
