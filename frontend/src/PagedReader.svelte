<script lang="ts">
 import {onDesktopClose} from './desktop';
 import {onMount,tick} from 'svelte';
 import {ArrowLeft,ArrowRight,CaretLeft,CaretRight,SkipBack,SkipForward,CornersOut,CornersIn,SlidersHorizontal,BookmarkSimple,List,X} from 'phosphor-svelte';
 import {api} from './api';import {themes} from './types';import type {Book} from './types';
 import {spreadWidths} from './page-sizing';
 import {PageBuffer} from './page-buffer';
 import {clamp,visibleSpread,spreadStart,adjacentPage,pageOffsets,placeAtOffset,offsetForPlace,windowForOffset} from './page-position';
 import type {PageMode,PagePlace} from './page-position';import './paged-reader.css';
 import {nativeFullscreenBridge} from './window-state';
 import {createReaderImmersion} from './reader-immersion';import './reader-immersion.css';
 import ReadingCompletion from './ReadingCompletion.svelte';import {completionOffer,serialReadingWriter} from './reading-completion';import type {CompletionReason,CompletionSource} from './reading-completion';import {normalizeReadStatus} from './reading-status';
 export let book:Book;export let settings:any;export let onclose:()=>void;export let onsettings:(s:any)=>void;export let onupdate:(b:Book)=>void;export let notify:(s:string)=>void;
 export let useGlobalSettings=true;export let onsettingsscope:(global:boolean)=>Promise<any>;
 type PageImage={url:string;width:number;height:number;pixels:number;element:HTMLImageElement};
 const count=Math.max(1,book.page_count||book.chapter_count||1),gap=24;
 let page=clamp(book.chapter||0,0,count-1),pageInput=page+1,editing=false;
 let mode:PageMode=['single','spread','scroll'].includes(settings.pageLayout)?settings.pageLayout:'single';
 function widthKey(value:PageMode){return `page${value[0].toUpperCase()+value.slice(1)}Width`}
 let width=Number(settings[widthKey(mode)])||(mode==='spread'?1800:900);
 let fitWindow=settings.pageFit!==false,coverFirst=settings.pageCoverFirst??settings.cover==='separate',pageGap=settings.pageGap!==false,equalHeight=settings.pageEqualHeight===true,scopeBusy=false;
 let shell:HTMLElement,frame:HTMLElement,loading=false,pageError='',panel='',autoHide=false,fullscreen=false,controlsVisible=true,disposed=false,request=0,saveTimer:any,widthTimer:any,resizeTimer:any,resizeObserver:ResizeObserver;
 const immersion=createReaderImmersion({fullscreenBridge:nativeFullscreenBridge(),changed:state=>{autoHide=state.autoHide;fullscreen=state.fullscreen;controlsVisible=state.controlsVisible},notify:message=>notify(message)});
 $: immersion.setAutoHide(settings.autoHideTools===true);
 let completionReason:CompletionReason=null,completionDismissed=false,completionBusy=false,completionDone=false,completionPrevious='reading',completionScrollUntil=0;
 const writeReading=serialReadingWriter<Book>(()=>book,values=>api<Book>(`/api/books/${book.id}`,'PATCH',values),updated=>{book={...book,...updated};onupdate(book)});
 let ratio=Number(book.locator?.ratio)||0,lastTarget:PagePlace={page,ratio},stablePlace:PagePlace={page,ratio},widthOrigin:PagePlace=null,bookmarks=book.bookmarks||[];
 let viewportW=900,viewportH=600,images:Record<number,PageImage>={},aspects:Record<number,number>={},displayed:number[]=[],windowPages:number[]=[];
 let buffer:PageBuffer<PageImage>=null,bufferWidth=0,bufferEpoch=0,planKey='',wheelTime=0,scrollFrame=0;
 let heldImages=new Map<number,PageImage>();const retiredImages=new Set<PageImage>();
 let bufferOptions={maxItems:8,maxPending:2,changed:()=>{}};
 let displayedMode:PageMode=mode;
 $: renderWidth=Math.max(80,Math.min(fitWindow&&mode!=='scroll'?viewportW:width,viewportW-16));
 $: spreadGap=pageGap?18:0;
 $: offsets=pageOffsets(count,renderWidth,aspects,gap);
 $: if(!editing)pageInput=page+1;
 $: progress=count===1?ratio:page/(count-1);
 $: imageWidths=spreadWidths(renderWidth,viewportH-10,displayed.map(index=>aspects[index]||Math.SQRT2),spreadGap,displayedMode==='spread'&&equalHeight);
 $: spreadWidth=imageWidths.reduce((sum,value)=>sum+value,0)+Math.max(0,displayed.length-1)*spreadGap;
 $: backTarget=adjacentPage(page,-1,count,mode,coverFirst);
 $: nextTarget=adjacentPage(page,1,count,mode,coverFirst);
 function place():PagePlace{return mode==='scroll'&&frame?placeAtOffset(offsets,frame.scrollTop,gap):{page,ratio:0}}
 function savedPlace(){return widthOrigin?.page===page?widthOrigin:loading&&lastTarget.page===page?lastTarget:place()}
 function restorePosition(position:PagePlace){if(!frame)return;if(mode==='scroll')frame.scrollTop=offsetForPlace(offsets,position,gap);else frame.scrollTop=0;stablePlace={...position};ratio=position.ratio}
 function rasterWidth(target=page,known=aspects){
  const needed=mode==='spread'?visibleSpread(target,count,coverFirst):[target];
  // Fit-to-height often makes the artwork much narrower than its viewport.
  // Rendering at the viewport's full width wastes the prefetch lead time.
  const fitted=mode==='scroll'?renderWidth:Math.max(...spreadWidths(renderWidth,viewportH-10,needed.map(index=>known[index]||Math.SQRT2),spreadGap,mode==='spread'&&equalHeight));
  const desired=fitted*Math.min(devicePixelRatio||1,2);return [480,800,1200,1600,2000,2400].find(value=>value>=desired)||2400;
 }
 function releaseImage(image:PageImage){image.element.remove();image.element.removeAttribute('src');URL.revokeObjectURL(image.url)}
 function retireImage(image:PageImage){retiredImages.add(image);void tick().then(()=>{if(retiredImages.delete(image))releaseImage(image)})}
 function disposeImages(){buffer?.dispose();for(const image of heldImages.values())releaseImage(image);heldImages.clear();for(const image of retiredImages)releaseImage(image);retiredImages.clear()}
 function showImage(node:HTMLElement,value:{image:PageImage;width?:number;index:number}){
  function update(value:{image:PageImage;width?:number;index:number}){const element=value.image.element;element.className='document-page';element.alt=`Страница ${value.index+1} из ${count}`;element.draggable=false;element.dataset.page=String(value.index);element.style.width=value.width===undefined?'':`${value.width}px`;if(node.firstChild!==element)node.replaceChildren(element)}
  update(value);return{update};
 }
 function syncImages(epoch:number){
  if(disposed||epoch!==bufferEpoch||!buffer)return;
  const previous=mode==='scroll'&&!loading?place():null;const entries=buffer.entries();
  for(const [index,image] of entries){const held=heldImages.get(index);if(held&&held!==image){heldImages.delete(index);retireImage(held)}}
  bufferOptions.maxItems=Math.max(1,8-heldImages.size);
  images=Object.fromEntries([...heldImages,...entries]);aspects={...aspects,...Object.fromEntries(entries.map(([index,image])=>[index,image.height/image.width]))};
  if(previous)void tick().then(()=>{if(!disposed&&epoch===bufferEpoch&&mode==='scroll'&&!loading)restorePosition(previous)});
 }
 function ensureBuffer(target:number){
  const pixels=rasterWidth(target),needed=mode==='spread'?visibleSpread(target,count,coverFirst):[target];
  if(buffer&&(pixels<=bufferWidth||needed.every(index=>(buffer.peek(index)?.pixels||0)>=pixels)))return;
  // A narrower settings panel can reuse sharper pages. On a real upgrade,
  // preserve the actual displayed Image nodes until their replacements decode.
  const keep=displayedMode==='scroll'?windowPages:displayed;
  const nextHeld=new Map<number,PageImage>();for(const index of keep){if(heldImages.has(index))nextHeld.set(index,heldImages.get(index)!)}
  for(const [index,image] of buffer?.take(keep)||[])nextHeld.set(index,image);
  for(const [index,image] of heldImages)if(nextHeld.get(index)!==image)retireImage(image);
  heldImages=nextHeld;buffer?.dispose();bufferWidth=pixels;planKey='';const epoch=++bufferEpoch;
  bufferOptions={maxItems:Math.max(1,8-heldImages.size),maxPending:2,changed:()=>syncImages(epoch)};
  buffer=new PageBuffer<PageImage>(async(index,signal)=>{
   async function decode(width:number):Promise<PageImage>{
    const response=await fetch(`/api/books/${book.id}/pages/${index}?width=${width}`,{signal});
    if(!response.ok){let message=`Не удалось открыть страницу (${response.status})`;try{message=(await response.json()).detail||message}catch{}throw new Error(message)}
    const blob=await response.blob();signal.throwIfAborted();const url=URL.createObjectURL(blob);
    try{const preview=new Image();preview.src=url;await preview.decode();signal.throwIfAborted();return{url,width:preview.naturalWidth,height:preview.naturalHeight,pixels:width,element:preview}}
    catch(error){URL.revokeObjectURL(url);throw error}
   }
   let image=await decode(pixels);
   // The first dimensions may reveal a landscape scan. Correct its estimate
   // once before publishing; the prior displayed spread remains in place.
   const corrected=rasterWidth(index,{...aspects,[index]:image.height/image.width});
   if(corrected>pixels&&image.width>=pixels){releaseImage(image);image=await decode(corrected)}
   return image;
  },releaseImage,bufferOptions);
 }
 function planPages(required:number[],retained:number[]=[]){
  if(!buffer)return;const last=Math.max(...required,0),visible=[...new Set([...required,...retained])].slice(0,8);
  const ahead=Array.from({length:4},(_,i)=>last+i+1).filter(index=>index<count);
  if(!loading)for(const [index,image] of heldImages)if(!visible.includes(index)){heldImages.delete(index);retireImage(image)}
  const key=JSON.stringify([visible,ahead]);if(key===planKey)return;planKey=key;buffer.plan(visible,ahead);syncImages(bufferEpoch);
 }
 function updateWindow(position?:PagePlace){
  if(mode!=='scroll'||!frame)return;
  const top=position?offsetForPlace(offsets,position,gap):frame.scrollTop;windowPages=windowForOffset(offsets,top,viewportH);
  const current=position?.page??placeAtOffset(offsets,top,gap).page;
  planPages([current,...windowPages.filter(index=>index!==current)]);
 }
 async function loadPage(index:number,position=0){
  if(disposed)return;completionScrollUntil=0;clearTimeout(widthTimer);widthOrigin=null;
  const target=clamp(Math.round(index),0,count-1),generation=++request;lastTarget={page:target,ratio:clamp(position,0,1)};loading=true;pageError='';ensureBuffer(target);
  const currentBuffer=buffer;
  try{
   const needed=mode==='spread'?visibleSpread(target,count,coverFirst):[target];
   if(mode==='scroll'){const top=offsetForPlace(offsets,lastTarget,gap),nextWindow=windowForOffset(offsets,top,viewportH);planPages([target,...nextWindow.filter(index=>index!==target)],displayedMode==='scroll'?windowPages:displayed)}else planPages(needed,displayed);
   await Promise.all(needed.map(index=>currentBuffer.get(index)));
   if(disposed||generation!==request||currentBuffer!==buffer)return;
   page=mode==='spread'?spreadStart(target,count,coverFirst):target;ratio=lastTarget.ratio;displayed=needed;displayedMode=mode;
   if(mode==='scroll')windowPages=windowForOffset(offsets,offsetForPlace(offsets,lastTarget,gap),viewportH);
   syncImages(bufferEpoch);await tick();
   if(disposed||generation!==request)return;restorePosition({page,ratio});loading=false;
   if(mode==='scroll')updateWindow();else planPages(displayed);queueSave();
  }catch(error){if(!disposed&&generation===request&&error.name!=='AbortError')pageError=error.message}
  finally{if(generation===request)loading=false}
 }
 function viewportScroll(){
  if(mode!=='scroll'||loading||disposed)return;if(scrollFrame)return;
  scrollFrame=requestAnimationFrame(()=>{scrollFrame=0;if(disposed||loading||mode!=='scroll')return;const current=place();page=current.page;ratio=current.ratio;stablePlace=current;updateWindow();queueSave();if(performance.now()<completionScrollUntil)offerCompletion('scroll')});
 }
 function queueSave(){if(loading||disposed||!displayed.length)return;stablePlace=savedPlace();ratio=stablePlace.ratio;clearTimeout(saveTimer);saveTimer=setTimeout(save,450)}
 async function save(){
  if(!displayed.length)return false;const position=savedPlace();
  const values={chapter:position.page,locator:{...position,mode},progress:Math.min(100,100*(count===1?position.ratio:position.page/(count-1)))};
  try{await writeReading(current=>({...values,status:normalizeReadStatus(current.status)==='read'?'read':'reading'}));return true}catch(error){notify(error.message);return false}
 }
 function offerCompletion(source:CompletionSource,ended=false){
  if(disposed||!displayed.length||!frame)return;
  const last=mode==='scroll'?page:Math.max(...displayed),fraction=mode==='scroll'?(page+ratio)/count:(last+1)/count;
  const atEnd=ended||(mode==='scroll'?frame.scrollTop+frame.clientHeight>=frame.scrollHeight-5:last===count-1);
  const offered=completionOffer(fraction,source,atEnd,completionDismissed,normalizeReadStatus(book.status)==='read');
  if(offered){completionReason=offered;immersion.activity()}
 }
 function dismissCompletion(){completionReason=null;completionDone=false;completionDismissed=true}
 async function completeReading(){
  if(completionBusy)return;completionBusy=true;clearTimeout(saveTimer);
  try{if(await save()===false)return;completionPrevious=normalizeReadStatus(book.status);await writeReading(()=>({status:'read'}));completionDone=true;completionReason=null;completionDismissed=true;immersion.activity()}
  catch(error){notify(error.message)}finally{completionBusy=false}
 }
 async function undoCompletion(){if(completionBusy)return;completionBusy=true;try{await writeReading(()=>({status:completionPrevious==='read'?'reading':completionPrevious}));completionDone=false;completionReason=null;notify('Отметка о прочтении отменена. Позиция сохранена.')}catch(error){notify(error.message)}finally{completionBusy=false}}
 async function leave(){if(disposed)return;clearTimeout(saveTimer);clearTimeout(widthTimer);clearTimeout(resizeTimer);disposed=true;request++;await save();disposeImages();onclose()}
 function jump(){completionScrollUntil=0;const value=Number(pageInput);if(Number.isFinite(value)){editing=false;void loadPage(value-1)}}
 async function next(direction:number){const target=adjacentPage(page,direction,count,mode,coverFirst);if(loading)return;if(target!==null)await loadPage(target);if(direction>0&&!pageError)offerCompletion('forward',target===null)}
 function saveAppearance(change:any={}){settings={...settings,pageLayout:mode,[widthKey(mode)]:width,pageFit:fitWindow,pageCoverFirst:coverFirst,pageGap,pageEqualHeight:equalHeight,...change};onsettings(settings)}
 async function changeScope(global:boolean){if(scopeBusy)return;scopeBusy=true;const current=savedPlace();try{settings=await onsettingsscope(global);mode=['single','spread','scroll'].includes(settings.pageLayout)?settings.pageLayout:'single';width=Number(settings[widthKey(mode)])||(mode==='spread'?1800:900);fitWindow=settings.pageFit!==false;coverFirst=settings.pageCoverFirst??settings.cover==='separate';pageGap=settings.pageGap!==false;equalHeight=settings.pageEqualHeight===true;await tick();await loadPage(current.page,current.ratio)}catch(error){notify(error.message)}finally{scopeBusy=false}}
 async function changeMode(value:PageMode){if(value===mode)return;const current=savedPlace();mode=value;width=Number(settings[widthKey(mode)])||(mode==='spread'?1800:900);saveAppearance();await tick();void loadPage(current.page,current.ratio)}
 async function changeFit(value:boolean){const current=savedPlace();fitWindow=value;saveAppearance();await tick();void loadPage(current.page,current.ratio)}
 function changeWidth(value:number){
  if(!widthOrigin)widthOrigin=savedPlace();const origin=widthOrigin;width=value;saveAppearance();
  void tick().then(()=>{if(!disposed&&widthOrigin===origin)restorePosition(origin)});
  clearTimeout(widthTimer);widthTimer=setTimeout(()=>loadPage(origin.page,origin.ratio),180);
 }
 async function addBookmark(){const current=savedPlace();const item={chapter:current.page,locator:{...current,mode},title:`Страница ${current.page+1}`,created_at:new Date().toISOString()};bookmarks=[...bookmarks,item];try{const result=await api<Book>(`/api/books/${book.id}`,'PATCH',{bookmarks});book={...book,...result};onupdate(book);notify('Закладка сохранена')}catch(error){notify(error.message)}}
 async function fullScreen(){await immersion.toggleFullscreen()}
 function wheel(event:WheelEvent){if(event.ctrlKey||event.metaKey)return;if(mode==='scroll'){completionScrollUntil=event.deltaY>0?performance.now()+700:0;if(event.deltaY>0)offerCompletion('scroll');return;}event.preventDefault();if(Math.abs(event.deltaY)<8||Date.now()-wheelTime<220)return;wheelTime=Date.now();next(event.deltaY>0?1:-1)}
 function wheelEvents(node:HTMLElement){node.addEventListener('wheel',wheel,{passive:false});return{destroy(){node.removeEventListener('wheel',wheel);}}}
 function keydown(event:KeyboardEvent){
  if(event.key==='F11'){event.preventDefault();void fullScreen();return}
  if(event.key==='Escape'){if(panel){event.preventDefault();panel='';immersion.activity()}else if(immersion.handleEscape())event.preventDefault();return}
  const target=event.target as HTMLElement;if(target?.closest('input,select,textarea,[contenteditable="true"]'))return;
  if(event.ctrlKey||event.metaKey||event.altKey)return;if(target?.closest('button,a')&&[' ','Enter'].includes(event.key))return;
  if(mode==='scroll'&&['PageDown','PageUp',' ','ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const backward=['PageUp','ArrowUp'].includes(event.key)||event.shiftKey;completionScrollUntil=backward?0:performance.now()+700;frame.scrollBy({top:(backward?-1:1)*frame.clientHeight*.87,behavior:'smooth'});if(!backward)offerCompletion('forward')}
  else if(['ArrowRight','ArrowDown','PageDown',' '].includes(event.key)){event.preventDefault();next(event.shiftKey?-1:1)}
  else if(['ArrowLeft','ArrowUp','PageUp'].includes(event.key)){event.preventDefault();next(-1)}
  else if(event.key==='Home'){event.preventDefault();void loadPage(0)}
  else if(event.key==='End'){event.preventDefault();void loadPage(count-1,mode==='scroll'?1:0)}
  else if(event.code==='KeyB')void addBookmark()
 }
 onMount(()=>{const offDesktop=onDesktopClose(async()=>{clearTimeout(saveTimer);return await save();});
  viewportW=frame.clientWidth;viewportH=frame.clientHeight;
  const unmountImmersion=immersion.mount(shell);window.addEventListener('keydown',keydown);
  void tick().then(()=>loadPage(page,ratio));
  resizeObserver=new ResizeObserver(()=>{if(disposed||!frame||frame.clientWidth===viewportW&&frame.clientHeight===viewportH)return;const origin=widthOrigin||stablePlace;viewportW=frame.clientWidth;viewportH=frame.clientHeight;widthOrigin=origin;clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>loadPage(origin.page,origin.ratio),130)});resizeObserver.observe(frame);
  return()=>{offDesktop();disposed=true;request++;disposeImages();resizeObserver?.disconnect();clearTimeout(saveTimer);clearTimeout(widthTimer);clearTimeout(resizeTimer);cancelAnimationFrame(scrollFrame);unmountImmersion();window.removeEventListener('keydown',keydown)};
 });
</script>

<div class="reader-shell paged-reader" class:reader-autohide={autoHide} class:reader-controls-visible={controlsVisible} bind:this={shell} style={`--book-width:${mode==='scroll'?renderWidth:spreadWidth||renderWidth}px`} data-page-index={page} data-page-mode={mode}>
 <ReadingCompletion reason={completionReason} busy={completionBusy} done={completionDone} oncomplete={completeReading} onundo={undoCompletion} ondismiss={dismissCompletion}/>
 <header class="reader-toolbar">
  <button class="text-button back-library" data-reader-controls inert={autoHide&&!controlsVisible} onclick={leave}><ArrowLeft size={21}/><span>Библиотека</span></button>
  <div class="reading-title"><strong>{book.title}</strong><span>{book.format} · {count} стр.</span></div>
  <div class="toolbar-actions" data-reader-controls inert={autoHide&&!controlsVisible}>
   <button class="icon-button" aria-label="Закладки документа" title="Закладки" onclick={()=>panel=panel==='bookmarks'?'':'bookmarks'}><List size={23}/></button>
   <button class="icon-button" aria-label="Настройки страниц" title="Расположение страниц и оформление" onclick={()=>panel=panel==='settings'?'':'settings'}><SlidersHorizontal size={23}/></button>
   <button class="icon-button" aria-label="Добавить закладку" title="Закладка (B)" onclick={addBookmark}><BookmarkSimple size={21}/></button>
   <button class="icon-button fullscreen-button" class:active={fullscreen} aria-pressed={fullscreen} aria-label={fullscreen?'Выйти из полного экрана':'Полный экран'} title={fullscreen?'Выйти из полного экрана (Esc)':'Полный экран (F11)'} onclick={fullScreen}>{#if fullscreen}<CornersIn size={22}/>{:else}<CornersOut size={22}/>{/if}</button>
  </div>
 </header>
 <main class="paged-stage" class:textured={settings.texture}>
  <button class="page-edge prev" data-reader-controls inert={autoHide&&!controlsVisible} aria-label="Предыдущая страница" disabled={loading||backTarget===null} onclick={()=>next(-1)}><CaretLeft size={26}/></button>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="paged-viewport" class:continuous={displayedMode==='scroll'} bind:this={frame} use:wheelEvents onscroll={viewportScroll} role="document" tabindex="0" aria-label="Страница документа" aria-busy={loading}>
   {#if displayedMode==='scroll'}
    <div class="continuous-pages" style:width={`${renderWidth}px`}>
     <div class="page-spacer" style:height={`${offsets[windowPages[0]||0]}px`}></div>
     {#each windowPages as index (index)}
      <div class="continuous-page" data-page={index} style:height={`${offsets[index+1]-offsets[index]-gap}px`} style:margin-bottom={`${gap}px`}>
       {#if images[index]}<div class="document-page-host" use:showImage={{image:images[index],index}}></div>{:else}<button class="page-placeholder" onclick={()=>loadPage(index)} aria-label={`Загрузить страницу ${index+1}`}>Страница {index+1}<span>Подготавливаем изображение…</span></button>{/if}
      </div>
     {/each}
     <div class="page-spacer" style:height={`${windowPages.length?Math.max(0,offsets[count]-offsets[windowPages[windowPages.length-1]+1]):0}px`}></div>
    </div>
   {:else}
    <div class="paged-spread" class:two-page-spread={displayedMode==='spread'&&displayed.length===2} class:joined-pages={!pageGap} style:gap={`${spreadGap}px`}>
     {#each displayed as index,i (index)}{#if images[index]}<div class="document-page-host" use:showImage={{image:images[index],width:imageWidths[i],index}}></div>{/if}{/each}
    </div>
   {/if}
  </div>
  <button class="page-edge next" data-reader-controls inert={autoHide&&!controlsVisible} aria-label="Следующая страница" disabled={loading||nextTarget===null} onclick={()=>next(1)}><CaretRight size={26}/></button>
  {#if loading}<div class="paged-status" role="status">Открываем страницу…</div>{/if}
  {#if pageError}<div class="paged-error" role="alert"><span>{pageError}</span><button onclick={()=>{planKey='';loadPage(lastTarget.page,lastTarget.ratio)}}>Повторить</button></div>{/if}
 </main>
 <footer class="reader-footer" data-reader-controls inert={autoHide&&!controlsVisible}>
  <div class="book-scrubber" title="Переход по страницам документа"><input type="range" min="0" max={count-1} step="1" value={page} disabled={loading||count===1} aria-label="Положение в документе" aria-valuetext={`Страница ${page+1} из ${count}`} onchange={event=>loadPage(+event.currentTarget.value)}/></div>
  <span class="paged-format">{book.format} · {mode==='spread'&&displayed.length===2?`${displayed[0]+1}–${displayed[1]+1}`:`Страница ${page+1}`} из {count}</span>
  <div class="reader-navigation" aria-label="Переход по документу">
   <button class="icon-button" aria-label="В начало документа" disabled={loading||page===0} onclick={()=>loadPage(0)}><SkipBack size={17}/></button>
   <button class="icon-button" aria-label="Назад на страницу" disabled={loading||backTarget===null} onclick={()=>next(-1)}><CaretLeft size={18}/></button>
   <form class="page-jump" onsubmit={event=>{event.preventDefault();jump()}}><input type="number" min="1" max={count} step="1" bind:value={pageInput} aria-label="Номер страницы документа" onfocus={()=>editing=true} onblur={event=>{if(!event.currentTarget.form?.contains(event.relatedTarget as Node))editing=false}}/><span>/ {count}</span><button type="submit" class="icon-button" aria-label="Перейти к указанной странице" disabled={loading}><ArrowRight size={14}/></button></form>
   <button class="icon-button" aria-label="Вперёд на страницу" disabled={loading||nextTarget===null} onclick={()=>next(1)}><CaretRight size={18}/></button>
   <button class="icon-button" aria-label="В конец документа" disabled={loading||page===count-1} onclick={()=>loadPage(count-1,mode==='scroll'?1:0)}><SkipForward size={17}/></button>
  </div>
  <span class="book-position-label">{Math.round(progress*100)}%</span>
  <div class="reader-shortcuts" aria-label="Горячие клавиши"><span>← → <kbd>Пробел</kbd> страницы</span><span><kbd>F11</kbd> экран · <kbd>Esc</kbd> выход</span></div>
 </footer>
 {#if panel}<aside class="reader-panel" aria-label={panel==='settings'?'Настройки страниц':'Закладки документа'}>
  <div class="panel-heading"><h2>{panel==='settings'?'Страница и окружение':'Закладки'}</h2><button class="icon-button" aria-label="Закрыть панель" onclick={()=>panel=''}><X size={21}/></button></div>
  {#if panel==='settings'}
   <label class="setting-check"><input type="checkbox" checked={settings.autoHideTools===true} onchange={e=>saveAppearance({autoHideTools:e.currentTarget.checked})}/> Скрывать инструменты при чтении</label>
   <label class="check-control"><input type="checkbox" checked={useGlobalSettings} disabled={scopeBusy} onchange={event=>changeScope(event.currentTarget.checked)}/>Общие настройки для книг</label>
   <p class="muted small">{useGlobalSettings?'Изменения применяются ко всем книгам без собственных настроек.':'Оформление сохраняется только для этой книги.'}</p>
   <div class="control-label">Расположение</div><div class="segmented layout-options">{#each [{id:'single',name:'Страница'},{id:'spread',name:'Разворот'},{id:'scroll',name:'Прокрутка'}] as layout}<button class:active={mode===layout.id} onclick={()=>changeMode(layout.id as PageMode)}>{layout.name}</button>{/each}</div>
   <p class="muted small">{mode==='scroll'?'Непрерывная лента. Колесо прокручивает страницы, следующие изображения готовятся заранее.':'Страницы видны целиком. Колесо и стрелки перелистывают; следующие четыре страницы готовятся заранее.'}</p>
   {#if mode!=='scroll'}<label class="check-control"><input type="checkbox" checked={fitWindow} onchange={event=>changeFit(event.currentTarget.checked)}/>Подогнать под окно</label>{/if}
   <label class="setting-label" for="document-width">{mode==='spread'?'Ширина разворота':'Ширина страницы'} <span>{fitWindow&&mode!=='scroll'?'Автоматически':`${width} px`}</span></label><input id="document-width" type="range" min="480" max="2400" step="20" value={width} disabled={fitWindow&&mode!=='scroll'} oninput={event=>changeWidth(+event.currentTarget.value)}/>
   <p class="muted small">{mode==='scroll'?'Ширина ограничена размером окна.':'Страница также подстраивается под высоту окна. Для увеличения деталей выберите прокрутку.'}</p>
   {#if mode==='spread'}<label class="check-control"><input type="checkbox" checked={coverFirst} onchange={event=>{coverFirst=event.currentTarget.checked;saveAppearance();loadPage(page)}}/>Первая страница — отдельная обложка</label><label class="check-control"><input type="checkbox" checked={pageGap} onchange={event=>{pageGap=event.currentTarget.checked;saveAppearance()}}/>Промежуток между страницами</label><label class="check-control"><input type="checkbox" checked={equalHeight} onchange={event=>{equalHeight=event.currentTarget.checked;saveAppearance()}}/>Выровнять высоту страниц</label>{/if}
   <span class="setting-label">Окружение</span><div class="theme-chips">{#each themes as theme}<button class:active={settings.theme===theme.id} onclick={()=>saveAppearance({theme:theme.id})}>{theme.name}</button>{/each}</div>
  {:else}
   {#if !bookmarks.length}<p class="muted small">Пока нет закладок. Нажмите B или значок закладки в верхней панели.</p>{/if}
   {#each bookmarks as bookmark}<button class="paged-bookmark" onclick={()=>{panel='';loadPage(bookmark.chapter,bookmark.locator?.ratio||0)}}><BookmarkSimple size={16}/>{bookmark.title||`Страница ${bookmark.chapter+1}`}</button>{/each}
  {/if}
 </aside>{/if}
</div>
