<script lang="ts">
 import {onDesktopClose} from './desktop';
 import {onMount,tick} from 'svelte';
 import {ArrowLeft,ArrowRight,BookOpen,BookmarkSimple,List,TextAa,Headphones,Play,Pause,Stop,SpeakerHigh,CornersOut,CornersIn,X,MagnifyingGlass,ArrowsClockwise,CaretLeft,CaretRight,Check,ArrowUUpLeft,SkipBack,SkipForward} from 'phosphor-svelte';
 import {api} from './api';import Cover from './Cover.svelte';import ImageViewer from './ImageViewer.svelte';import './reader-cover.css'; import {themes,fonts,layoutSettings} from './types'; import type {Book,Chapter} from './types';
 import {cancelLocalSpeech,waitForSpeechCancellation,splitSpeech} from './speech'; import type {SpeechPart} from './speech';
 import {SpeechBuffer} from './speech-buffer';
 import {prepareSpeechAudio,releaseSpeechAudio} from './speech-audio'; import type {PreparedSpeech} from './speech-audio';
 import {speechFragmentSpan,speechCharacterAt} from './speech-follow';
 import {speechWindow,speechCacheLimit} from './speech-window';
 import {nextSpeechChapter,SpeechBookEnd} from './speech-chapters';import type {SpeechChapter} from './speech-chapters';
 import {positionInBook,locateInBook} from './reading-position';
 import {textRange,literalMatches} from './reader-search'; import type {SearchHit,SearchResponse} from './reader-search';
 import './reader-search.css';import './reader-speech.css';
 import {nativeFullscreenBridge} from './window-state';
 import {createReaderImmersion} from './reader-immersion';import './reader-immersion.css';
 import ReadingCompletion from './ReadingCompletion.svelte';import {completionOffer,serialReadingWriter} from './reading-completion';import type {CompletionReason,CompletionSource} from './reading-completion';import {normalizeReadStatus} from './reading-status';
 import WholeBookPagination from './WholeBookPagination.svelte';
 import {globalPageRange,locateGlobalPage,paginationState} from './whole-book-pagination';
 import {isFootnoteReference} from './footnotes'; import type {Footnote} from './footnotes';
 export let book:Book; export let settings:any; export let onclose:()=>void; export let onsettings:(s:any)=>void; export let onupdate:(b:Book)=>void; export let notify:(s:string)=>void;
 export let useGlobalSettings=true; export let onsettingsscope:(global:boolean)=>Promise<any>;
 let scopeChanging=false;
 let chapter:Chapter=null, chapterIndex=Number(book.chapter||0), page=0,pageCount=1,loading=false,panel='',autoHide=false,frame:HTMLElement,flow:HTMLElement;
 let viewW=900,viewH=600,cols=2,gap=64; let ready=false,chapterRequest=0,fullscreen=false;let stableLoc:any=null; let search='',submittedQuery='',searchScope:'book'|'chapter'='book',searchChapter=chapterIndex;
 let shell:HTMLElement,controlsVisible=true;
 const immersion=createReaderImmersion({fullscreenBridge:nativeFullscreenBridge(),changed:state=>{autoHide=state.autoHide;fullscreen=state.fullscreen;controlsVisible=state.controlsVisible},notify});
 $: immersion.setAutoHide(settings.autoHideTools===true);
 let completionReason:CompletionReason=null,completionDismissed=false,completionBusy=false,completionDone=false,completionPrevious='reading',completionScrollUntil=0;
 const writeReading=serialReadingWriter<Book>(()=>book,values=>api<Book>(`/api/books/${book.id}`,'PATCH',values),updated=>{book={...book,...updated};onupdate(book)});
 let searchResults:SearchHit[]=[],searchTotal=0,nextSearchOffset:number=null,activeIndex=-1,searchBusy=false,searchError='',searchAttempted=false;
 let searchAbort:AbortController=null,searchRequest=0,searchOrigin:any=null;
 let dockOrigin:any=null,dockBaseline:any=null,panelChanging=false,panelRequest=0;
 let selectedSpeechId='',speechClickTimer:any=null,voiceDownload='',voiceDownloadError='';
 $: selectedVoiceName=ttsStatus?.voices?.find(v=>v.id===voice)?.name?.split(' · ')[0]||'Голос не выбран';
 $: activeHit=searchResults[activeIndex];
 $: if(ready){panel;chapter;submittedQuery;searchResults;activeIndex;void tick().then(paintSearch);}
 let imageUrl='';
 let ttsStatus:any=null,voice='',speaking=false,paused=false,ttsBusy=false,spokenId='',spokenIndex=-1,session=0,audio:HTMLAudioElement=null;
 let disposed=false,speechStarting=false,speechParts:SpeechPart[]=[];
 let speechBuffer:SpeechBuffer<PreparedSpeech>=null,speechAbort:AbortController=null,preserveSpeechPage=false;
 let speechCacheKey='',speechVisible:string[]=[],speechPrevious:string[]=[];
 let speechAhead:SpeechChapter<Chapter>=null;
 let textPointer:{x:number,y:number}=null,chapterSearch:HTMLInputElement;
 let footnote:Footnote=null,noteLoading=false,noteVisible=false,noteLeft=20,noteTop=100,noteElement:HTMLElement,noteAnchor:HTMLAnchorElement,noteOrigin:any=null,noteRequest=0,noteAbort:AbortController=null;
 let pagination=paginationState('',[]),paginator:WholeBookPagination;
 $: globalPages=globalPageRange(pagination.counts,chapterIndex,page,cols);
 let scrollRatio=0,scrubbing=false,scrubValue=0,jumpValue=1,jumpEditing=false;
 $: bookPosition=settings.layout!=='scroll'&&globalPages?(globalPages.last===globalPages.total?1:(globalPages.first-1)/Math.max(1,globalPages.total-1)):positionInBook(book.chapters||[],book.chapter_count||1,chapterIndex,settings.layout==='scroll'?scrollRatio:page/Math.max(1,pageCount-1));
 $: if(!jumpEditing)jumpValue=settings.layout==='scroll'?Math.round(bookPosition*100):globalPages?.first||1;
 let saveTimer:any=null,resizeTimer:any=null,resizeObs:ResizeObserver,wheelTime=0; let localBookmarks:any[]=book.bookmarks||[]; let returnPlaces:any[]=[];let anchors:Record<string,number>={...book.anchors};
 $: cols=settings.layout==='spread'&&viewW>660?2:1;
 $: showCover=!!book.cover_url&&chapterIndex===0&&page===0&&settings.cover==='separate'&&!chapter;
 $: effectiveWidth=settings.layout==='spread'&&settings.adaptiveWidth!==false?Math.min(1600,settings.fontSize*62+settings.margin*2+gap):settings.width;
 $: paperStyle=`--book-font:'${settings.font}';--book-size:${settings.fontSize}px;--book-line:${settings.lineHeight};--book-padding:${settings.margin}px;--book-width:${effectiveWidth}px;--columns:${cols};--column-gap:${gap}px;`;

 async function loadChapter(index:number,locator:any=null,end=false,continuation?:{chapter:Chapter}){
  completionScrollUntil=0;closeFootnote(false);if(!continuation)stopSpeech();selectedSpeechId='';paintSpeechSelection();loading=true;clearSearchHighlights();stableLoc=null;const request=++chapterRequest;
  try {const target=Math.max(0,Math.min(index,(book.chapters?.length||book.chapter_count||1)-1));const response=continuation?.chapter||await api<Chapter>(`/api/books/${book.id}/chapters/${target}`);if(disposed||request!==chapterRequest)return false;chapterIndex=target;chapter=response;page=0;await tick();await document.fonts.ready;await Promise.all(Array.from(flow?.querySelectorAll('img')||[]).map(img=>img.decode().catch(()=>{})));if(disposed||request!==chapterRequest)return false;flow?.querySelectorAll('img').forEach(img=>{img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label',img.alt||'Открыть иллюстрацию')});await new Promise(r=>requestAnimationFrame(r));measure();await tick();measure();if(end){page=pageCount-1;if(settings.layout==='scroll')frame.scrollTop=frame.scrollHeight;}else if(locator)restore(locator);else if(settings.layout==='scroll')frame.scrollTop=0;queueSave();paintSearch();if(searchScope==='chapter'&&submittedQuery&&searchChapter!==chapterIndex)void doSearch();return true;}
  catch(e){if(!disposed)notify(e.message)}finally{if(request===chapterRequest)loading=false}
 }
 function measure(){if(!frame||!flow)return;if(settings.layout!=='scroll'){frame.scrollLeft=0;frame.scrollTop=0;}viewW=frame.clientWidth;viewH=frame.clientHeight;const w=frame.clientWidth;pageCount=settings.layout==='scroll'?1:Math.max(1,Math.ceil((flow.scrollWidth+gap-2)/(w+gap)));page=Math.max(0,Math.min(page,pageCount-1));}
 function layoutGeometry(){return JSON.stringify([settings.layout,settings.font,settings.fontSize,settings.lineHeight,settings.margin,settings.width,settings.cover,frame?.clientWidth,frame?.clientHeight,pageCount])}
 function locator(){if(!flow||!frame)return{id:'',page,ratio:0};const f=frame.getBoundingClientRect();const els=flow.querySelectorAll<HTMLElement>('p[id],h1[id],h2[id],h3[id],h4[id],li[id],img[id],blockquote[id]');let found:HTMLElement=null;for(const e of els){const rects=e.getClientRects();if(Array.from(rects).some(r=>r.bottom>f.top+8&&r.top<f.bottom-8&&r.right>f.left+8&&r.left<f.right-8)){found=e;break;}}return{id:found?.id||'',page,geometry:layoutGeometry(),ratio:settings.layout==='scroll'?frame.scrollTop/Math.max(1,frame.scrollHeight-frame.clientHeight):page/Math.max(1,pageCount)};}
 function restore(loc:any){if(!flow||!frame)return;frame.scrollLeft=0;if(typeof loc==='string'&&loc.startsWith('{')){try{loc=JSON.parse(loc)}catch{}}if(loc?.geometry===layoutGeometry()){if(settings.layout==='scroll')frame.scrollTop=(loc.ratio||0)*Math.max(0,frame.scrollHeight-frame.clientHeight);else page=Math.max(0,Math.min(pageCount-1,Number(loc.page)||0));return;}if(Number.isInteger(loc?.viewPage)&&settings.layout!=='scroll'){page=Math.max(0,Math.min(pageCount-1,loc.viewPage));return;}const id=typeof loc==='string'?loc:loc.id;const el=id?flow.querySelector<HTMLElement>(`[id="${CSS.escape(id)}"]`):null;if(el){if(settings.layout==='scroll')frame.scrollTop=el.getBoundingClientRect().top-frame.getBoundingClientRect().top+frame.scrollTop;else{const x=el.getBoundingClientRect().left-flow.getBoundingClientRect().left;page=Math.min(pageCount-1,Math.max(0,Math.floor((x+3)/(viewW+gap))));}}else if(settings.layout==='scroll')frame.scrollTop=(loc.ratio||0)*(frame.scrollHeight-frame.clientHeight);else page=Math.min(pageCount-1,Math.max(0,Math.floor((loc.ratio||0)*pageCount)));}
 async function queueSave(){if(!chapter||disposed)return;await tick();if(disposed)return;stableLoc=locator();scrollRatio=stableLoc.ratio;updateSpeechWindow();clearTimeout(saveTimer);saveTimer=setTimeout(save,450)}
 async function save(){if(!chapter||!frame)return false;const loc=locator(),index=chapterIndex,count=book.chapters?.length||book.chapter_count||1;const frac=settings.layout==='scroll'?loc.ratio:page/Math.max(1,pageCount-1);const progress=Math.min(100,100*positionInBook(book.chapters||[],count,index,frac));try{await writeReading(current=>({chapter:index,locator:loc,progress,status:normalizeReadStatus(current.status)==='read'?'read':'reading'}));return true}catch(e){notify(e.message);return false}}
 function offerCompletion(source:CompletionSource,ended=false){
  if(!chapter||!frame||disposed)return;
  const count=book.chapters?.length||book.chapter_count||1,frac=settings.layout==='scroll'?frame.scrollTop/Math.max(1,frame.scrollHeight-frame.clientHeight):page/Math.max(1,pageCount-1);
  const atEnd=ended||chapterIndex===count-1&&(settings.layout==='scroll'?frame.scrollTop+frame.clientHeight>=frame.scrollHeight-5:page===pageCount-1);
  const offered=completionOffer(positionInBook(book.chapters||[],count,chapterIndex,frac),source,atEnd,completionDismissed,normalizeReadStatus(book.status)==='read');
  if(offered){completionReason=offered;immersion.activity()}
 }
 function dismissCompletion(){completionReason=null;completionDone=false;completionDismissed=true}
 async function completeReading(){
  if(completionBusy)return;completionBusy=true;clearTimeout(saveTimer);
  try{if(!await save())return;completionPrevious=normalizeReadStatus(book.status);await writeReading(()=>({status:'read'}));completionDone=true;completionReason=null;completionDismissed=true;stopSpeech();immersion.activity()}
  catch(e){notify(e.message)}finally{completionBusy=false}
 }
 async function undoCompletion(){if(completionBusy)return;completionBusy=true;try{await writeReading(()=>({status:completionPrevious==='read'?'reading':completionPrevious}));completionDone=false;completionReason=null;notify('Отметка о прочтении отменена. Позиция сохранена.')}catch(e){notify(e.message)}finally{completionBusy=false}}
 async function change(key:string,value:any){const loc=locator();settings=key==='layout'?layoutSettings(settings,value):{...settings,[key]:value,...(key==='width'?{[`${settings.layout}Width`]:value,adaptiveWidth:false}:{})};onsettings(settings);if(['rate','speechCache'].includes(key)&&speaking)startSpeech(speechParts,spokenIndex,paused,true);await tick();await document.fonts.ready;await new Promise(r=>requestAnimationFrame(r));measure();await tick();measure();restore(loc);queueSave();}
 async function changeSettingsScope(global:boolean){
  if(scopeChanging||!onsettingsscope)return;const loc=locator();scopeChanging=true;
  try{const resolved=await onsettingsscope(global);if(disposed)return;settings=resolved;useGlobalSettings=global;await tick();await document.fonts.ready;await new Promise(r=>requestAnimationFrame(r));measure();await tick();measure();restore(loc);queueSave();}
  catch(e){notify(e.message)}finally{scopeChanging=false}
 }
 async function next(dir:number){if(loading)return;if(frame)frame.scrollLeft=0;if(settings.layout==='scroll'){completionScrollUntil=dir>0?performance.now()+700:0;if(dir>0&&frame.scrollTop+frame.clientHeight>=frame.scrollHeight-5&&chapterIndex<(book.chapter_count||1)-1)await loadChapter(chapterIndex+1);else if(dir<0&&frame.scrollTop<=2&&chapterIndex>0)await loadChapter(chapterIndex-1,null,true);else frame.scrollBy({top:dir*frame.clientHeight*.87,behavior:'smooth'});if(dir>0)offerCompletion('forward');return;}if(page+dir<0){if(chapterIndex>0)await loadChapter(chapterIndex-1,null,true);}else if(page+dir>=pageCount){if(chapterIndex<(book.chapters?.length||book.chapter_count||1)-1)await loadChapter(chapterIndex+1);else offerCompletion('forward',true);}else{page+=dir;queueSave();}if(dir>0)offerCompletion('forward');}
 async function jumpBook(fraction:number){
  if(disposed||loading)return;completionScrollUntil=0;stopSpeech();
  if(settings.layout!=='scroll'&&globalPages){await jumpGlobal(1+fraction*(globalPages.total-1));return;}
  const target=locateInBook(book.chapters||[],book.chapter_count||1,fraction);
  if(target.chapter!==chapterIndex)await loadChapter(target.chapter,{ratio:target.ratio},target.end);
  else{if(settings.layout==='scroll')frame.scrollTop=target.ratio*Math.max(0,frame.scrollHeight-frame.clientHeight);else page=Math.round(target.ratio*Math.max(0,pageCount-1));queueSave()}
 }
 async function commitScrub(){try{await jumpBook(scrubValue/1000)}finally{scrubbing=false}}
 async function jumpGlobal(number:number){
  const target=locateGlobalPage(pagination.counts,number,cols);if(!target||loading)return;completionScrollUntil=0;stopSpeech();
  if(target.chapter!==chapterIndex)await loadChapter(target.chapter,{viewPage:target.localView});
  else{page=Math.max(0,Math.min(pageCount-1,target.localView));queueSave();}
 }
 function jumpNumber(){if(loading)return;const number=Number(jumpValue);if(!Number.isFinite(number))return;if(settings.layout==='scroll')void jumpBook(number/100);else void jumpGlobal(number);jumpEditing=false}
 function wheel(e:WheelEvent){if(e.ctrlKey||e.metaKey||imageUrl)return;const now=Date.now();if(settings.layout==='scroll'){completionScrollUntil=e.deltaY>0?performance.now()+700:0;const atEnd=e.deltaY>0&&frame.scrollTop+frame.clientHeight>=frame.scrollHeight-3;const atStart=e.deltaY<0&&frame.scrollTop<=1;if((atEnd&&chapterIndex<(book.chapter_count||1)-1)||(atStart&&chapterIndex>0)){e.preventDefault();if(!loading&&now-wheelTime>350){wheelTime=now;void loadChapter(chapterIndex+(atEnd?1:-1),null,atStart).then(()=>{if(atEnd)offerCompletion('scroll')})}}else if(atEnd)offerCompletion('scroll',true);return;}e.preventDefault();if(now-wheelTime<230)return;if(Math.abs(e.deltaY)<8)return;wheelTime=now;next(e.deltaY>0?1:-1);}
 function wheelEvents(node:HTMLElement){node.addEventListener('wheel',wheel,{passive:false});return{destroy(){node.removeEventListener('wheel',wheel)}}}
 async function leave(){stopSpeech();disposed=true;await save();onclose()}
 function keydown(e:KeyboardEvent){
  if(e.key==='Escape'){
   if(noteVisible){e.preventDefault();closeFootnote();return;}
   if(imageUrl){e.preventDefault();imageUrl='';return;}
   if(panel){e.preventDefault();void setPanel('');return;}
   if(immersion.handleEscape())e.preventDefault();return;
  }
  if((e.ctrlKey||e.metaKey)&&(e.code==='KeyF'||e.key.toLowerCase()==='f')){e.preventDefault();void focusSearch();return;}
  if(e.key==='F11'){e.preventDefault();void immersion.toggleFullscreen();return;}
  const target=e.target as HTMLElement;if(target?.closest('input,textarea,select,[contenteditable="true"]'))return;
  if(!e.ctrlKey&&!e.metaKey&&target?.closest('button,a,[role="button"]')&&[' ','Enter'].includes(e.key))return;
  if(noteVisible&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','PageUp','PageDown',' '].includes(e.key)||imageUrl)return;
  if(e.ctrlKey&&e.code==='Space'){e.preventDefault();toggleSpeech();return;}
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  if(['ArrowRight','ArrowDown','PageDown',' '].includes(e.key)){e.preventDefault();next(e.shiftKey?-1:1)}
  else if(['ArrowLeft','ArrowUp','PageUp'].includes(e.key)){e.preventDefault();next(-1)}
  else if(e.code==='KeyT')void setPanel(panel==='contents'?'':'contents');else if(e.code==='KeyB')addBookmark();
 }
 function closeFootnote(restoreFocus=true){
  const wasVisible=noteVisible;noteRequest++;noteAbort?.abort();noteAbort=null;noteVisible=false;noteLoading=false;footnote=null;
  if(wasVisible&&restoreFocus&&noteAnchor?.isConnected)noteAnchor.focus({preventScroll:true});
 }
 async function showFootnote(anchor:HTMLAnchorElement,id:string):Promise<boolean>{
  closeFootnote(false);const request=noteRequest,controller=new AbortController();noteAbort=controller;noteAnchor=anchor;
  noteOrigin={chapter:chapterIndex,loc:locator()};const rect=anchor.getBoundingClientRect();noteVisible=true;noteLoading=true;
  noteLeft=Math.max(16,Math.min(rect.left,window.innerWidth-500));noteTop=Math.max(16,Math.min(rect.bottom+12,window.innerHeight-220));
  try{
   const result=await api<Footnote>(`/api/books/${book.id}/notes/${encodeURIComponent(id)}`,'GET',undefined,controller.signal);
   if(disposed||request!==noteRequest)return true;footnote=result;noteLoading=false;await tick();
   if(noteElement){const height=noteElement.getBoundingClientRect().height;noteTop=Math.max(16,Math.min(rect.bottom+12,window.innerHeight-height-20));noteElement.querySelector<HTMLButtonElement>('.note-close')?.focus({preventScroll:true});}
   return true;
  }catch(e){if(disposed||request!==noteRequest||e.name==='AbortError')return true;closeFootnote(false);return false;}
 }
 async function openNoteSection(){if(!footnote)return;const target=footnote,origin=noteOrigin;closeFootnote(false);returnPlaces=[...returnPlaces,origin];if(target.chapter!==chapterIndex)await loadChapter(target.chapter,{id:target.anchor});else{restore({id:target.anchor});queueSave()}}
 function noteEvents(node:HTMLElement){node.addEventListener('click',clickContent);return{destroy(){node.removeEventListener('click',clickContent)}}}
 function outsideNote(e:PointerEvent){const target=e.target as Node;if(noteVisible&&!noteElement?.contains(target)&&!noteAnchor?.contains(target))closeFootnote(false)}
 async function clickContent(e:MouseEvent){const target=e.target as HTMLElement;const img=target.closest('img') as HTMLImageElement;if(img){imageUrl=img.src;return;}const a=target.closest('a');if(!a){selectSpeechParagraph(e);return;}const href=a.getAttribute('href')||'';if(href.startsWith('#')){e.preventDefault();if(loading||disposed)return;let id:string;try{id=decodeURIComponent(href.slice(1))}catch{id=href.slice(1)};if(!id)return;if(isFootnoteReference(a)&&await showFootnote(a,id))return;closeFootnote(false);const previous={chapter:chapterIndex,loc:locator()};let targetChapter=anchors[id];if(targetChapter===undefined&&flow?.querySelector(`[id="${CSS.escape(id)}"]`))targetChapter=chapterIndex;if(targetChapter===undefined){try{const detail=await api<Book>(`/api/books/${book.id}`);if(disposed)return;anchors={...anchors,...detail.anchors};book={...book,...detail};targetChapter=anchors[id]}catch(err){notify(err.message);return}}if(targetChapter===undefined){notify('Не удалось найти раздел, на который ссылается книга');return;}returnPlaces=[...returnPlaces,previous];if(Number(targetChapter)!==chapterIndex)await loadChapter(Number(targetChapter),{id});else{restore({id});queueSave();}}else if(/^https?:/i.test(href)){e.preventDefault();window.open(href,'_blank','noopener,noreferrer')}}
 function viewportScroll(){if(settings.layout!=='scroll'&&(frame.scrollLeft||frame.scrollTop)){frame.scrollLeft=0;frame.scrollTop=0;return;}if(!loading){queueSave();if(settings.layout==='scroll'&&performance.now()<completionScrollUntil)offerCompletion('scroll')}}
 function contentEvents(node:HTMLElement){const key=(e:KeyboardEvent)=>{if(e.key==='Enter'&&(e.target as HTMLElement).tagName==='IMG'){e.preventDefault();clickContent(e as any)}};const focus=(e:FocusEvent)=>{if(settings.layout==='scroll'||!frame||!flow)return;const target=e.target as HTMLElement;if(!target.closest('a,img'))return;const x=target.getBoundingClientRect().left-flow.getBoundingClientRect().left;page=Math.max(0,Math.min(pageCount-1,Math.floor((x+3)/(viewW+gap))));frame.scrollLeft=0;queueSave()};const pointer=(e:PointerEvent)=>{textPointer={x:e.clientX,y:e.clientY}};node.addEventListener('pointerdown',pointer);node.addEventListener('click',clickContent);node.addEventListener('keydown',key);node.addEventListener('focusin',focus);return{destroy(){node.removeEventListener('pointerdown',pointer);node.removeEventListener('click',clickContent);node.removeEventListener('keydown',key);node.removeEventListener('focusin',focus)}}}
 async function backToText(){const p=returnPlaces[returnPlaces.length-1];if(!p||loading)return;returnPlaces=returnPlaces.slice(0,-1);if(p.chapter!==chapterIndex)await loadChapter(p.chapter,p.loc);else{restore(p.loc);queueSave();}}
 async function addBookmark(){const loc=locator();const item={chapter:chapterIndex,locator:loc,title:chapter?.title||`Глава ${chapterIndex+1}`,created_at:new Date().toISOString()};localBookmarks=[...localBookmarks,item];try{await api(`/api/books/${book.id}`,'PATCH',{bookmarks:localBookmarks});notify('Закладка сохранена')}catch(e){notify(e.message)}}
 function clearSearchHighlights(){const registry=(CSS as any).highlights;registry?.delete('book-search');registry?.delete('book-search-active')}
 function hitRange(hit:SearchHit){
  if(!hit||hit.chapter!==chapterIndex||!flow||!chapter)return null;
  const paragraph=chapter.paragraphs?.find(p=>p.id===hit.id),element=flow.querySelector<HTMLElement>(`[id="${CSS.escape(hit.id)}"]`);
  return paragraph&&element?textRange(element,paragraph.text,hit.start,hit.end):null;
 }
 function paintSearch(){
  clearSearchHighlights();if(disposed||panel!=='search'||!submittedQuery||!flow||!chapter)return;
  const registry=(CSS as any).highlights,HighlightClass=(window as any).Highlight;if(!registry||!HighlightClass)return;
  const ranges:Range[]=[];
  for(const paragraph of chapter.paragraphs||[]){
   const element=flow.querySelector<HTMLElement>(`[id="${CSS.escape(paragraph.id)}"]`);if(!element)continue;
   for(const hit of literalMatches(paragraph.text,submittedQuery,2000-ranges.length)){const range=textRange(element,paragraph.text,hit.start,hit.end);if(range)ranges.push(range)}
   if(ranges.length>=2000)break;
  }
  registry.set('book-search',new HighlightClass(...ranges));
  const active=hitRange(activeHit);if(active){const highlight=new HighlightClass(active);highlight.priority=1;registry.set('book-search-active',highlight)}
 }
 async function fetchSearch(offset=0,append=false){
  searchAbort?.abort();const controller=new AbortController();searchAbort=controller;const request=++searchRequest;
  searchBusy=true;searchError='';
  try{
   const params=new URLSearchParams({q:submittedQuery,scope:searchScope,chapter:String(searchChapter),offset:String(offset),limit:'100'});
   const response=await api<SearchResponse>(`/api/books/${book.id}/search?${params}`,'GET',undefined,controller.signal);
   if(disposed||request!==searchRequest)return false;
   searchResults=append?[...searchResults,...response.results]:response.results;searchTotal=response.total;nextSearchOffset=response.next_offset;
   return true;
  }catch(e){if(!disposed&&request===searchRequest&&e.name!=='AbortError')searchError=e.message;return false;}
  finally{if(request===searchRequest)searchBusy=false}
 }
 async function doSearch(){
  searchAbort?.abort();searchRequest++;submittedQuery=search.trim().replace(/\s+/gu,' ');searchChapter=chapterIndex;
  searchResults=[];searchTotal=0;nextSearchOffset=null;activeIndex=-1;searchError='';searchBusy=false;searchAttempted=!!submittedQuery;
  if(!submittedQuery){clearSearchHighlights();return;}
  await fetchSearch();
 }
 function changeSearchScope(scope:'book'|'chapter'){if(searchScope===scope)return;searchScope=scope;void doSearch()}
 async function selectSearchHit(index:number){
  const hit=searchResults[index];if(!hit||loading)return;
  if(!searchOrigin)searchOrigin=dockOrigin&&samePlace(locator(),dockBaseline)&&dockOrigin.chapter===chapterIndex?dockOrigin:{chapter:chapterIndex,loc:locator()};
  stopSpeech();activeIndex=index;
  if(hit.chapter!==chapterIndex)await loadChapter(hit.chapter,{id:hit.id});
  if(disposed||hit.chapter!==chapterIndex)return;
  await tick();const range=hitRange(hit),rect=range?.getClientRects()[0];
  if(rect){if(settings.layout==='scroll')frame.scrollTop+=rect.top-frame.getBoundingClientRect().top-Math.min(90,frame.clientHeight*.2);
   else page=Math.max(0,Math.min(pageCount-1,Math.floor((rect.left-flow.getBoundingClientRect().left+3)/(viewW+gap))));
  }else restore({id:hit.id});
  await tick();if(window.innerWidth<1000)await setPanel('');paintSearch();queueSave();
 }
 async function goMatch(delta:number){
  if(searchBusy||loading||!searchTotal)return;
  const target=Math.max(0,Math.min(searchTotal-1,activeIndex+delta));
  if(target>=searchResults.length&&nextSearchOffset!==null){if(!await fetchSearch(nextSearchOffset,true))return;}
  await selectSearchHit(target);
 }
 async function returnFromSearch(){
  if(!searchOrigin||loading)return;const origin=searchOrigin;stopSpeech();
  if(origin.chapter!==chapterIndex)await loadChapter(origin.chapter,origin.loc);else{restore(origin.loc);queueSave();}
  if(panel==='search'){dockOrigin=origin;dockBaseline=locator();}searchOrigin=null;activeIndex=-1;
 }
 async function loadTts(){try{const result=await api('/api/tts/status');if(disposed)return;ttsStatus=result;const preferred=voice||settings.voice;voice=ttsStatus.voices?.some(v=>v.id===preferred)?preferred:ttsStatus.voices?.[0]?.id||'';}catch(e){if(!disposed)ttsStatus={ready:false,message:e.message}}}
 function samePlace(a:any,b:any){return !!a&&!!b&&a.id===b.id&&a.page===b.page&&Math.abs((a.ratio||0)-(b.ratio||0))<.00001}
 async function setPanel(value:string){
  if(value===panel)return;
  const previous=panel,place=locator(),change=++panelRequest;
  const hitRect=previous==='search'?hitRange(activeHit)?.getClientRects()[0]:null,view=frame?.getBoundingClientRect();
  const preserveHit=hitRect&&view&&hitRect.right>view.left&&hitRect.left<view.right&&hitRect.bottom>view.top&&hitRect.top<view.bottom?activeHit:null;
  const restoring=previous==='search'&&dockOrigin?.chapter===chapterIndex&&samePlace(place,dockBaseline)?dockOrigin.loc:place;
  if(value==='search'){dockOrigin={chapter:chapterIndex,loc:place};dockBaseline=null;}
  stableLoc=restoring;panelChanging=true;clearTimeout(resizeTimer);panel=value;
  await tick();await new Promise(resolve=>requestAnimationFrame(resolve));
  if(disposed||change!==panelRequest)return;measure();await tick();measure();restore(restoring);
  if(value!=='search'&&preserveHit){const rect=hitRange(preserveHit)?.getClientRects()[0];if(rect){if(settings.layout==='scroll')frame.scrollTop+=rect.top-frame.getBoundingClientRect().top-60;else page=Math.max(0,Math.min(pageCount-1,Math.floor((rect.left-flow.getBoundingClientRect().left+3)/(viewW+gap))));}}
  await tick();stableLoc=locator();
  if(value==='search')dockBaseline=stableLoc;else if(previous==='search'){dockOrigin=null;dockBaseline=null;}
  panelChanging=false;queueSave();
 }
 async function focusSearch(){imageUrl='';await setPanel('search');await tick();chapterSearch?.focus();chapterSearch?.select()}
 function paintSpeechSelection(){flow?.querySelectorAll('.tts-selected').forEach(e=>e.classList.remove('tts-selected'));if(selectedSpeechId&&!speaking)flow?.querySelector(`[id="${CSS.escape(selectedSpeechId)}"]`)?.classList.add('tts-selected')}
 async function downloadVoice(id:string){if(voiceDownload)return;voiceDownload=id;voiceDownloadError='';try{const result=await api(`/api/tts/voices/${encodeURIComponent(id)}/download`,'POST');if(disposed)return;await loadTts();if(disposed)return;if(!result.ready||!ttsStatus?.voices?.some(v=>v.id===id))throw new Error('Голос пока не готов. Проверьте загрузку ещё раз.');stopSpeech();voice=id;change('voice',id);notify('Голос загружен и выбран')}catch(e){if(!disposed)voiceDownloadError=e.message}finally{voiceDownload=''}}
 function releaseAudio(){if(audio){audio.onended=null;audio.onerror=null;audio.ontimeupdate=null;audio.pause();audio=null;}}
 function stopSpeech(){
  const wasActive=speaking||ttsBusy||!!speechBuffer;session++;
  releaseAudio();speechAbort?.abort();speechAbort=null;speechBuffer?.dispose();speechBuffer=null;
  speechCacheKey='';speechVisible=[];speechPrevious=[];speechAhead=null;
  speaking=false;paused=false;ttsBusy=false;spokenId='';preserveSpeechPage=false;
  flow?.querySelectorAll('.tts-current').forEach(e=>e.classList.remove('tts-current'));
  paintSpeechSelection();if(wasActive)cancelLocalSpeech();
 }
 function startSpeech(parts:SpeechPart[],index=0,startPaused=false,keepPage=false,seed?:PreparedSpeech){
  if(disposed||loading||!parts.length){if(seed)releaseSpeechAudio(seed);return;}
  const key=JSON.stringify([chapterIndex,voice,Number(settings.rate),!!settings.russianYo,settings.speechCache||'normal']);
  const reuse=speechBuffer&&speechCacheKey===key;
  if(reuse){session++;releaseAudio();}else stopSpeech();
  speechParts=parts;spokenIndex=Math.max(0,Math.min(index,parts.length-1));speaking=true;paused=startPaused;preserveSpeechPage=keepPage;paintSpeechSelection();
  if(reuse){void playParagraph(session);return;}
  const current=session,controller=new AbortController(),selectedVoice=voice,rate=Number(settings.rate),fromChapter=chapterIndex;
  speechAbort=controller;speechCacheKey=key;
  speechBuffer=new SpeechBuffer<PreparedSpeech>(async index=>{
   await waitForSpeechCancellation();controller.signal.throwIfAborted();
   let part=parts[index];
   if(index===parts.length){
    if(!speechAhead){const next=await nextSpeechChapter(fromChapter,book.chapters?.length||book.chapter_count||1,i=>api<Chapter>(`/api/books/${book.id}/chapters/${i}`,'GET',undefined,controller.signal),controller.signal);controller.signal.throwIfAborted();speechAhead=next;}
    controller.signal.throwIfAborted();if(!speechAhead)throw new SpeechBookEnd();part=speechAhead.parts[0];
   }
   const response=await api('/api/tts/synthesize','POST',{text:part.text,voice:selectedVoice,rate,russian_yo:!!settings.russianYo},controller.signal);
   controller.signal.throwIfAborted();
   return prepareSpeechAudio(response.url,controller.signal);
  },releaseSpeechAudio,{maxItems:64,maxWeight:speechCacheLimit(settings.speechCache),weight:item=>item.bytes});
  if(seed)speechBuffer.seed(0,seed);
  void playParagraph(current);
 }
 async function toggleSpeech(){
  if(disposed||loading||!chapter||speechStarting)return;
  speechStarting=true;const before=session;
  try{
   if(!ttsStatus)await loadTts();
   if(disposed||loading||!chapter||before!==session)return;
   if(!ttsStatus?.ready){await setPanel('speech');notify(ttsStatus?.message||'Модель озвучки пока не установлена');return;}
   if(speaking){if(paused){paused=false;if(audio)await audio.play();}else{paused=true;audio?.pause();}return;}
   const id=selectedSpeechId||locator().id,parts=splitSpeech(chapter.paragraphs||[]);await setPanel('speech');
   if(!parts.length){notify('В этой главе нет текста для озвучки');return;}
   startSpeech(parts,Math.max(0,parts.findIndex(p=>p.id===id)));
  }catch(e){if(!disposed&&before===session){stopSpeech();notify(e.message)}}finally{speechStarting=false}
 }
 function updateSpeechWindow(){
  if(!speechBuffer||!speaking||loading||!frame||!flow||!speechParts.length)return;
  const view=frame.getBoundingClientRect(),ids=new Set(speechParts.map(part=>part.id));
  const visible=Array.from(flow.querySelectorAll<HTMLElement>('[id]')).filter(element=>ids.has(element.id)&&Array.from(element.getClientRects()).some(rect=>rect.bottom>view.top+2&&rect.top<view.bottom-2&&rect.right>view.left+2&&rect.left<view.right-2)).map(element=>element.id);
  if(visible.length&&visible.join('\0')!==speechVisible.join('\0')){speechPrevious=speechVisible;speechVisible=visible;}
  const previousIds=new Set(speechPrevious),previous=speechParts.flatMap((part,index)=>previousIds.has(part.id)?[index]:[]);
  const upcoming=speechWindow(speechParts,speechVisible,spokenIndex);
  if(!settings.speechStopAtChapter&&chapterIndex<(book.chapters?.length||book.chapter_count||1)-1&&(spokenIndex>=speechParts.length-3||upcoming.includes(speechParts.length-1)))upcoming.push(speechParts.length);
  speechBuffer.setWindow(spokenIndex,upcoming,previous);
 }
 async function continueSpeechChapter(current:number){
  if(settings.speechStopAtChapter){stopSpeech();notify('Глава озвучена. Остановка в конце главы включена.');return;}
  if(chapterIndex>=(book.chapters?.length||book.chapter_count||1)-1){stopSpeech();offerCompletion('speech',true);notify('Книга озвучена.');return;}
  const buffer=speechBuffer;ttsBusy=true;let transferred:PreparedSpeech;
  try{
   await buffer.ensure(speechParts.length);
   if(disposed||current!==session||!speaking||buffer!==speechBuffer)return;
   if(settings.speechStopAtChapter){stopSpeech();notify('Глава озвучена. Остановка в конце главы включена.');return;}
   const ahead=speechAhead;if(!ahead)throw new SpeechBookEnd();
   transferred=buffer.take(speechParts.length);
   const loaded=await loadChapter(ahead.index,null,false,{chapter:ahead.chapter});
   if(disposed||current!==session||!speaking){if(transferred)releaseSpeechAudio(transferred);return;}
   if(!loaded){if(transferred)releaseSpeechAudio(transferred);stopSpeech();return;}
   const first=transferred;transferred=undefined;startSpeech(ahead.parts,0,paused,false,first);
  }catch(e){if(transferred)releaseSpeechAudio(transferred);if(disposed||current!==session)return;stopSpeech();if(e instanceof SpeechBookEnd)offerCompletion('speech',true);if(e.name!=='AbortError')notify(e instanceof SpeechBookEnd?'Книга озвучена.':e.message);}
 }
 async function playParagraph(current:number){
  if(disposed||current!==session||!speaking||!speechBuffer)return;
  if(spokenIndex>=speechParts.length){await continueSpeechChapter(current);return;}
  const p=speechParts[spokenIndex],buffer=speechBuffer;ttsBusy=true;
  try{
   const prepared=buffer.ensure(spokenIndex);
   updateSpeechWindow();
   const item=await prepared;
   if(disposed||current!==session||!speaking||buffer!==speechBuffer)return;
   const changedParagraph=spokenId!==p.id;spokenId=p.id;selectedSpeechId=p.id;paintSpeechSelection();
   flow?.querySelectorAll('.tts-current').forEach(e=>e.classList.remove('tts-current'));
   flow?.querySelector(`[id="${CSS.escape(p.id)}"]`)?.classList.add('tts-current');
   if(changedParagraph&&settings.followSpeech!==false&&!preserveSpeechPage)restore({id:p.id});preserveSpeechPage=false;queueSave();
   releaseAudio();const fragment=item.audio;audio=fragment;fragment.currentTime=0;fragment.volume=Number(settings.volume);
   const canonical=chapter.paragraphs?.find(item=>item.id===p.id)?.text||'',span=speechFragmentSpan(speechParts,spokenIndex,canonical);
   fragment.ontimeupdate=()=>{if(!disposed&&current===session&&audio===fragment&&!paused&&settings.followSpeech!==false&&span)followSpeech(p.id,canonical,span,fragment.currentTime,fragment.duration)};
   fragment.onended=()=>{if(disposed||current!==session||audio!==fragment)return;releaseAudio();spokenIndex++;void playParagraph(current)};
   fragment.onerror=()=>{if(disposed||current!==session||audio!==fragment)return;stopSpeech();notify('Не удалось воспроизвести звук')};
   ttsBusy=false;if(!paused){try{await fragment.play()}catch(e){if(!(e.name==='AbortError'&&paused&&audio===fragment&&current===session))throw e}}
  }catch(e){if(disposed||current!==session)return;stopSpeech();if(e.name!=='AbortError')notify(e.message)}
 }
 function seekSpeech(delta:number){if(disposed||loading||!speechParts.length)return;startSpeech(speechParts,Math.max(0,Math.min(speechParts.length-1,spokenIndex+delta)),paused)}
 function followSpeech(id:string,canonical:string,span:{start:number;end:number},elapsed:number,duration:number){
  const offset=speechCharacterAt(canonical,span,elapsed,duration);if(offset===null)return;
  const element=flow?.querySelector<HTMLElement>(`[id="${CSS.escape(id)}"]`);if(!element)return;
  const end=offset+(/[\uD800-\uDBFF]/.test(canonical[offset])?2:1),range=textRange(element,canonical,offset,Math.min(end,canonical.length)),rect=range?.getClientRects()[0];if(!rect)return;
  if(settings.layout==='scroll'){const view=frame.getBoundingClientRect();if(rect.bottom>view.bottom-25||rect.top<view.top)frame.scrollTop+=rect.top-view.top-frame.clientHeight*.25;}
  else{const target=Math.max(0,Math.min(pageCount-1,Math.floor((rect.left-flow.getBoundingClientRect().left+3)/(viewW+gap))));if(target!==page){page=target;queueSave();}}
 }
 function selectSpeechParagraph(e:MouseEvent){
  clearTimeout(speechClickTimer);
  if(disposed||loading||!chapter||e.button!==0||e.detail>1||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey)return;
  if(textPointer&&Math.hypot(e.clientX-textPointer.x,e.clientY-textPointer.y)>5)return;
  if(window.getSelection()?.isCollapsed===false)return;
  const ids=new Set(chapter.paragraphs.map(p=>p.id));let element=e.target as HTMLElement;
  while(element&&element!==flow&&!ids.has(element.id))element=element.parentElement;
  if(!element||element===flow)return;
  selectedSpeechId=element.id;paintSpeechSelection();
  if(speaking){const id=selectedSpeechId,wasPaused=paused,current=session;speechClickTimer=setTimeout(()=>{
   if(disposed||current!==session||window.getSelection()?.isCollapsed===false)return;
   const parts=splitSpeech(chapter.paragraphs||[]),index=parts.findIndex(p=>p.id===id);if(index>=0)startSpeech(parts,index,wasPaused);
  },220);}
 }
 function volume(v:number){change('volume',v);if(audio)audio.volume=v}
 onMount(()=>{const offDesktop=onDesktopClose(async()=>{clearTimeout(saveTimer);return await save();});const stopImmersion=immersion.mount(shell);document.addEventListener('pointerdown',outsideNote);loadChapter(chapterIndex,book.locator).then(()=>{ready=true;if(!disposed){resizeObs=new ResizeObserver(()=>{if(panelChanging)return;const loc=stableLoc||locator();clearTimeout(resizeTimer);resizeTimer=setTimeout(async()=>{if(disposed||panelChanging)return;await tick();measure();await tick();measure();restore(loc)},150)});if(frame)resizeObs.observe(frame)}});loadTts();window.addEventListener('keydown',keydown);return()=>{offDesktop();disposed=true;stopImmersion();clearTimeout(speechClickTimer);searchAbort?.abort();searchRequest++;clearSearchHighlights();closeFootnote(false);document.removeEventListener('pointerdown',outsideNote);resizeObs?.disconnect();clearTimeout(saveTimer);clearTimeout(resizeTimer);stopSpeech();window.removeEventListener('keydown',keydown)}});
</script>

<div bind:this={shell} class:reader-autohide={autoHide} class:reader-controls-visible={controlsVisible} class:search-docked={panel==='search'} class="reader-shell" style={paperStyle} data-anchor-count={Object.keys(anchors).length} data-current-chapter={chapterIndex} data-reader-disposed={disposed}>
 <ReadingCompletion reason={completionReason} busy={completionBusy} done={completionDone} oncomplete={completeReading} onundo={undoCompletion} ondismiss={dismissCompletion}/>
 <header class="reader-toolbar">
  <button class="text-button back-library" data-reader-controls inert={autoHide&&!controlsVisible} onclick={leave}><ArrowLeft size={21}/><span>Библиотека</span></button>
  <div class="reading-title"><strong>{book.title}</strong><span>{book.author||book.authors?.join(', ')}</span></div>
  <div class="toolbar-actions" data-reader-controls inert={autoHide&&!controlsVisible}>
   <button class:active={panel==='search'} class="icon-button" title="Поиск в книге (Ctrl+F)" aria-label="Поиск в книге" onclick={focusSearch}><MagnifyingGlass size={22}/></button>
   <button class:active={panel==='contents'} class="icon-button" title="Оглавление (T)" aria-label="Оглавление" onclick={()=>setPanel(panel==='contents'?'':'contents')}><List size={23}/></button>
   <button class:active={panel==='settings'} class="icon-button" title="Оформление текста" aria-label="Настройки чтения" onclick={()=>setPanel(panel==='settings'?'':'settings')}><TextAa size={26}/></button>
   <button class:active={panel==='speech'} class="icon-button" title="Озвучка" aria-label="Озвучка" onclick={()=>setPanel(panel==='speech'?'':'speech')}><Headphones size={23}/></button>
   <button class="icon-button" title="Добавить закладку (B)" aria-label="Добавить закладку" onclick={addBookmark}><BookmarkSimple size={21}/></button>
   <button class="icon-button fullscreen-button" class:active={fullscreen} title={fullscreen?'Выйти из полного экрана (F11)':'Полный экран (F11)'} aria-label={fullscreen?'Выйти из полного экрана':'Полный экран'} aria-pressed={fullscreen} onclick={()=>immersion.toggleFullscreen()}>{#if fullscreen}<CornersIn size={22}/>{:else}<CornersOut size={22}/>{/if}</button>
  </div>
 </header>
 <main class:textured={settings.texture} class="reader-stage">
  <button class="page-edge prev" data-reader-controls inert={autoHide&&!controlsVisible} title="Предыдущая страница" aria-label="Предыдущая страница" onclick={()=>next(-1)}><CaretLeft size={26}/></button>
  <div class:two-pages={settings.layout==='spread'&&cols===2} class:scrolling={settings.layout==='scroll'} class:textured={settings.texture} class="paper-book">
   {#if loading}<div class="chapter-loading">Открываем главу…</div>{/if}
   <!-- The reading document is focusable so keyboard users can page through it. -->
   <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
   <div class="page-viewport" bind:this={frame} use:wheelEvents onscroll={viewportScroll} role="document" tabindex="0" aria-label="Текст книги">
    <div class="chapter-flow" bind:this={flow} use:contentEvents role="article" style:transform={settings.layout==='scroll'?'none':`translateX(${-page*(viewW+gap)}px)`}>
     {#if chapter}{#if chapterIndex===0&&settings.cover!=='skip'}<div class:separate-cover={settings.cover==='separate'} class="book-cover-page"><Cover {book} lazy={false}/></div>{/if}{@html chapter.html}{/if}
    </div>
   </div>
  </div>
  <button class="page-edge next" data-reader-controls inert={autoHide&&!controlsVisible} title="Следующая страница" aria-label="Следующая страница" onclick={()=>next(1)}><CaretRight size={26}/></button>
 </main>
 <footer class="reader-footer" data-reader-controls inert={autoHide&&!controlsVisible}>
  <div class="book-scrubber" title="Нажмите или потяните, чтобы перейти в любую часть книги">
   <input aria-label="Положение в книге" aria-valuetext={`${Math.round((scrubbing?scrubValue/1000:bookPosition)*100)}% книги`} type="range" min="0" max="1000" step="1" disabled={loading} value={scrubbing?scrubValue:Math.round(bookPosition*1000)} oninput={e=>{scrubbing=true;scrubValue=+e.currentTarget.value}} onchange={commitScrub}/>
  </div>
  <button class="chapter-label text-button" onclick={()=>setPanel(panel==='contents'?'':'contents')}><span>Глава {chapterIndex+1} из {book.chapters?.length||book.chapter_count||1}</span><span class="subtle">{chapter?.title||''}</span></button>
  <div class="reader-navigation" aria-label="Переход по книге">
   <button class="icon-button" title="В начало книги" aria-label="В начало книги" disabled={loading} onclick={()=>jumpBook(0)}><SkipBack size={17}/></button>
   <button class="icon-button" title="Предыдущая страница" aria-label="Назад на страницу" disabled={loading} onclick={()=>next(-1)}><CaretLeft size={18}/></button>
   <form class="page-jump" onsubmit={e=>{e.preventDefault();jumpNumber()}} title={settings.layout==='scroll'?'Положение в книге в процентах':'Номер страницы во всей книге'}>
    {#if settings.layout==='scroll'||globalPages}<input aria-label={settings.layout==='scroll'?'Процент книги':'Номер страницы книги'} type="number" min={settings.layout==='scroll'?0:1} max={settings.layout==='scroll'?100:globalPages?.total||1} step="1" disabled={loading} bind:value={jumpValue} onfocus={()=>jumpEditing=true} onblur={e=>{if(!e.currentTarget.form?.contains(e.relatedTarget as Node))jumpEditing=false}}/>
    <span>{settings.layout==='scroll'?'%':`${globalPages.last>globalPages.first?`– ${globalPages.last} `:''}/ ${globalPages.total}`}</span><button type="submit" class="icon-button" aria-label="Перейти к указанному месту" title="Перейти"><ArrowRight size={14}/></button>
    {:else}<span class="pagination-status" role="status" title={pagination.error||'Страницы пересчитываются в фоне для текущего шрифта и размера окна'}>{pagination.error?'Счёт страниц недоступен':`Считаем страницы · ${pagination.measured}/${book.chapter_count||1}`}</span>{#if pagination.error}<button type="button" class="icon-button" aria-label="Повторить подсчёт страниц" onclick={()=>paginator?.retry()}><ArrowsClockwise size={14}/></button>{/if}{/if}
   </form>
   <button class="icon-button" title="Следующая страница" aria-label="Вперёд на страницу" disabled={loading} onclick={()=>next(1)}><CaretRight size={18}/></button>
   <button class="icon-button" title="В конец книги" aria-label="В конец книги" disabled={loading} onclick={()=>jumpBook(1)}><SkipForward size={17}/></button>
  </div>
  <span class="book-position-label">{Math.round((scrubbing?scrubValue/1000:bookPosition)*100)}%</span>
  {#if returnPlaces.length}<button class="text-button return-to-text" aria-label="Назад к месту чтения" onclick={backToText}><ArrowUUpLeft size={18}/>К тексту</button>{:else if searchOrigin}<button class="text-button return-to-text" aria-label="Вернуться к месту до поиска" onclick={returnFromSearch}><ArrowUUpLeft size={18}/>До поиска</button>{/if}
  <div class="reader-shortcuts" aria-label="Горячие клавиши"><span title="Стрелки влево/вправо или пробел — листать">← → <kbd>Пробел</kbd></span><span title="Найти текст в книге"><kbd>Ctrl F</kbd> поиск</span><span title="Озвучка и пауза"><kbd>Ctrl Пробел</kbd> голос</span><span><kbd>F11</kbd> полный экран · <kbd>Esc</kbd> выход</span></div>
  <button class="listen-button" onclick={toggleSpeech}>{#if speaking&&!paused}<Pause size={19} weight="fill"/>{:else}<Play size={19} weight="fill"/>{/if}<span>{ttsBusy?'Готовим голос…':speaking?(paused?'Продолжить':'Пауза'):'Слушать'}</span></button>
 </footer>
 <WholeBookPagination bind:this={paginator} {book} {settings} {frame} {flow} columns={cols} {gap} onupdate={value=>pagination=value}/>
 {#if panel}
 <aside class:search-panel={panel==='search'} class="reader-panel" aria-label={panel==='settings'?'Настройки чтения':panel==='contents'?'Оглавление':panel==='search'?'Поиск в книге':'Озвучка'}>
  <div class="panel-heading"><h2>{panel==='settings'?'Как вам удобно':panel==='contents'?'Содержание':panel==='search'?'Поиск в книге':'Читать вслух'}</h2><button class="icon-button" aria-label="Закрыть панель" onclick={()=>setPanel('')}><X size={21}/></button></div>
  {#if panel==='settings'}
   <label class="check-control"><input type="checkbox" checked={useGlobalSettings} disabled={scopeChanging} onchange={e=>changeSettingsScope(e.currentTarget.checked)}/>Общие настройки для книг</label>
   <p class="muted small">{useGlobalSettings?'Изменения применяются ко всем книгам без собственных настроек.':'Оформление сохраняется только для этой книги.'}</p>
   <div class="control-label">Оформление</div><div class="theme-options">{#each themes as t}<button class:selected={settings.theme===t.id} class="theme-chip" data-swatch={t.id} onclick={()=>change('theme',t.id)} title={t.description}><span class="swatch"></span>{t.name}{#if settings.theme===t.id}<Check size={16}/>{/if}</button>{/each}</div>
   <label class="control-label" for="book-font">Шрифт</label><select id="book-font" value={settings.font} onchange={e=>change('font',e.currentTarget.value)}>{#each fonts as f}<option value={f}>{f} — Тихий вечер</option>{/each}</select>
   <div class="range-label"><label for="font-size">Размер текста</label><span>{settings.fontSize} px</span></div><input id="font-size" type="range" min="15" max="38" step="1" value={settings.fontSize} oninput={e=>change('fontSize',+e.currentTarget.value)}/>
   <div class="range-label"><label for="line-height">Между строками</label><span>{Number(settings.lineHeight).toFixed(2)}</span></div><input id="line-height" type="range" min="1.2" max="2.2" step=".05" value={settings.lineHeight} oninput={e=>change('lineHeight',+e.currentTarget.value)}/>
   <div class="control-label">Расположение</div><div class="segmented layout-options">{#each [{id:'single',name:'Страница'},{id:'spread',name:'Разворот'},{id:'scroll',name:'Прокрутка'}] as l}<button class:active={settings.layout===l.id} onclick={()=>change('layout',l.id)}>{l.name}</button>{/each}</div>
   {#if settings.layout==='spread'}<label class="setting-check"><input type="checkbox" checked={settings.adaptiveWidth!==false} onchange={e=>change('adaptiveWidth',e.currentTarget.checked)}/> Подбирать ширину разворота под экран</label>{/if}
   <div class="range-label"><label for="page-width">Ширина книги</label><span>{Math.round(effectiveWidth)} px</span></div><input id="page-width" type="range" min="600" max="1600" step="40" value={effectiveWidth} oninput={e=>change('width',+e.currentTarget.value)}/>
   <div class="range-label"><label for="page-margin">Поля страницы</label><span>{settings.margin} px</span></div><input id="page-margin" type="range" min="20" max="90" step="2" value={settings.margin} oninput={e=>change('margin',+e.currentTarget.value)}/>
   <label class="control-label" for="cover-mode">Первая обложка</label><select id="cover-mode" value={settings.cover} onchange={e=>change('cover',e.currentTarget.value)}><option value="separate">Отдельной страницей</option><option value="normal">В начале текста</option><option value="skip">Пропускать</option></select>
   <label class="check-control"><input type="checkbox" checked={settings.texture} onchange={e=>change('texture',e.currentTarget.checked)}/>Текстура бумаги и окружения</label>
   <label class="setting-check"><input type="checkbox" checked={settings.autoHideTools===true} onchange={e=>change('autoHideTools',e.currentTarget.checked)}/> Скрывать инструменты при чтении</label>
  {:else if panel==='contents'}
   <div class="contents-list">{#each book.chapters||[] as c}<button class:current={c.index===chapterIndex} onclick={async()=>{await setPanel('');loadChapter(c.index)}}><span>{String(c.index+1).padStart(2,'0')}</span>{c.title||`Глава ${c.index+1}`}</button>{/each}</div>
   {#if localBookmarks.length}<h3>Закладки</h3><div class="contents-list">{#each localBookmarks as b,i}<button onclick={async()=>{await setPanel('');loadChapter(b.chapter,b.locator)}}><BookmarkSimple size={15}/>{b.title||`Закладка ${i+1}`}</button>{/each}</div>{/if}
  {:else if panel==='search'}
   <div class="segmented search-scope" role="group" aria-label="Область поиска"><button class:active={searchScope==='book'} aria-pressed={searchScope==='book'} onclick={()=>changeSearchScope('book')}>Вся книга</button><button class:active={searchScope==='chapter'} aria-pressed={searchScope==='chapter'} onclick={()=>changeSearchScope('chapter')}>В этой главе</button></div>
   <form class="search-form" onsubmit={e=>{e.preventDefault();doSearch()}}><input bind:this={chapterSearch} aria-label="Слово или фраза" placeholder="Слово или фраза" maxlength="160" bind:value={search}/><button type="submit" class="icon-button" aria-label="Найти" title="Найти (Enter)"><MagnifyingGlass size={20}/></button></form>
   <div class="search-summary" role="status">{#if searchBusy}Ищем…{:else if searchError}{searchError}{:else if searchAttempted}{activeIndex>=0?`Совпадение ${activeIndex+1} из ${searchTotal}`:`Найдено: ${searchTotal}`}{:else}Введите текст и нажмите Enter{/if}</div>
   {#if searchOrigin}<div class="search-return"><button class="text-button" disabled={loading} onclick={returnFromSearch}><ArrowUUpLeft size={16}/>Вернуться к месту до поиска</button><button class="text-button" title="Продолжить чтение отсюда и забыть прежнюю позицию" onclick={()=>searchOrigin=null}>Остаться здесь</button></div>{/if}
   {#if searchTotal}<div class="search-navigation"><button disabled={searchBusy||loading||activeIndex<=0} onclick={()=>goMatch(-1)}><CaretLeft size={16}/>Предыдущее</button><button disabled={searchBusy||loading||activeIndex>=searchTotal-1} onclick={()=>goMatch(1)}>Следующее<CaretRight size={16}/></button></div>{/if}
   <div class="search-results" aria-label="Результаты поиска" aria-busy={searchBusy}>
    {#each searchResults as hit,i}<button class:current={activeIndex===i} class="search-result" aria-current={activeIndex===i?'true':undefined} disabled={loading} onclick={()=>selectSearchHit(i)}><span class="search-result-heading">{i+1}. {hit.chapter_title}</span><span class="search-result-quote">{#if hit.start>hit.before.length}…{/if}{hit.before}<mark>{hit.match}</mark>{hit.after}…</span></button>{/each}
    {#if nextSearchOffset!==null}<button class="search-more" disabled={searchBusy} onclick={()=>fetchSearch(nextSearchOffset,true)}>{searchBusy?'Загружаем…':`Показать ещё · ${searchResults.length} из ${searchTotal}`}</button>{/if}
    {#if searchError}<button class="search-more" onclick={()=>fetchSearch(nextSearchOffset||0,!!searchResults.length)}>Повторить поиск</button>{/if}
    {#if searchAttempted&&!searchBusy&&!searchError&&!searchTotal}<p class="muted small">Совпадений нет. Попробуйте более короткую фразу{searchScope==='chapter'?' или поиск по всей книге':''}.</p>{/if}
   </div>
  {:else if panel==='speech'}
   <div class="speech-panel">
    <button class="primary speech-start" disabled={!ttsStatus?.ready} onclick={toggleSpeech}>{#if speaking&&!paused}<Pause size={26}/>{:else}<Play size={26} weight="fill"/>{/if}{ttsBusy?'Готовим голос…':speaking?(paused?'Продолжить чтение':'Пауза'):'Начать читать вслух'}</button>
    <div class="speech-secondary"><button disabled={!speaking} onclick={()=>seekSpeech(-1)}><CaretLeft size={18}/>Назад</button><button disabled={!speaking} onclick={stopSpeech}><Stop size={18} weight="fill"/>Остановить</button></div>
    <p class="speech-hint">Нажмите на абзац в книге, чтобы начать с него. Во время озвучки клик переносит чтение на выбранный абзац.</p>
    {#if !ttsStatus?.ready}<p class="speech-notice" role="status">{ttsStatus?.message||'Проверяем голос…'}</p>{/if}
    <label class="control-label" for="tts-voice">Голос для чтения</label>
    {#if ttsStatus?.voices?.length}<select id="tts-voice" bind:value={voice} onchange={()=>{stopSpeech();change('voice',voice)}}>{#each ttsStatus.voices as v}<option value={v.id}>{v.name}</option>{/each}</select>{:else}<p>Скачайте голос ниже, чтобы начать чтение.</p>{/if}
    {#if ttsStatus?.downloadable_voices?.length}<details class="speech-downloads"><summary>Скачать ещё голоса</summary><p>Скачиваются один раз. Затем работают без интернета.</p>{#each ttsStatus.downloadable_voices as v}<button disabled={!!voiceDownload} onclick={()=>downloadVoice(v.id)}>{voiceDownload===v.id?'Загружаем…':`Скачать · ${v.label||v.name} · ${v.size_mb||63} МБ`}</button>{/each}</details>{/if}
    {#if voiceDownloadError}<p role="alert" class="speech-notice">{voiceDownloadError}</p>{/if}
    <div class="range-label"><label for="tts-rate">Скорость чтения</label><span>{Number(settings.rate).toFixed(1)}×</span></div><input id="tts-rate" type="range" min=".6" max="1.8" step=".1" value={settings.rate} oninput={e=>change('rate',+e.currentTarget.value)}/>
    <div class="range-label"><label for="tts-volume">Громкость</label><span>{Math.round(settings.volume*100)}%</span></div><input id="tts-volume" type="range" min="0" max="1" step=".05" value={settings.volume} oninput={e=>volume(+e.currentTarget.value)}/>
    <div class="speech-options">
     {#if ttsStatus?.capabilities?.russian_yo}<label class="check-control"><input type="checkbox" checked={!!settings.russianYo} onchange={e=>{stopSpeech();change('russianYo',e.currentTarget.checked)}}/>Восстанавливать «ё» по словарю</label>{/if}
     <label class="check-control"><input type="checkbox" checked={settings.followSpeech!==false} onchange={e=>change('followSpeech',e.currentTarget.checked)}/>Перелистывать вслед за голосом</label>
     <label class="check-control"><input type="checkbox" checked={!!settings.speechStopAtChapter} onchange={e=>change('speechStopAtChapter',e.currentTarget.checked)}/>Останавливаться в конце главы</label>
    </div>
    <label class="control-label" for="tts-cache">Буфер озвучки</label><select id="tts-cache" value={settings.speechCache||'normal'} onchange={e=>change('speechCache',e.currentTarget.value)}><option value="small">Небольшой · 16 МБ</option><option value="normal">Обычный · 32 МБ</option></select>
    <p class="speech-hint">Чтение начинается сразу. Дальше готовим текущий разворот и три абзаца вперёд; предыдущий разворот сохраняем в пределах буфера.</p>
    <button class="speech-refresh" onclick={loadTts}><ArrowsClockwise size={17}/>Проверить готовность голоса</button>
   </div>
  {/if}
 </aside>
 {/if}
 {#if noteVisible}
 <div class="footnote-popup" role="dialog" aria-label="Сноска" tabindex="-1" bind:this={noteElement} style:left={`${noteLeft}px`} style:top={`${noteTop}px`}>
  <div class="footnote-heading"><strong>{footnote?.title||'Сноска'}</strong><button class="icon-button note-close" aria-label="Закрыть сноску" onclick={()=>closeFootnote()}><X size={19}/></button></div>
  {#if noteLoading}<p class="muted small" role="status">Открываем сноску…</p>{:else if footnote}<div class="footnote-content" use:noteEvents>{@html footnote.html}</div><button class="text-button footnote-open" onclick={openNoteSection}><ArrowRight size={15}/>Перейти в раздел сносок</button>{/if}
 </div>
 {/if}
 {#if imageUrl}<ImageViewer src={imageUrl} onclose={()=>imageUrl=''}/>{/if}
</div>








