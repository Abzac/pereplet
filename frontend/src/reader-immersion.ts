export interface ReaderImmersionState {autoHide:boolean;fullscreen:boolean;controlsVisible:boolean}
interface ImmersionOptions {changed:(state:ReaderImmersionState)=>void;notify?:(message:string)=>void;idleMs?:number;fullscreenBridge?:{active:()=>boolean;enter:()=>Promise<unknown>;exit:()=>Promise<unknown>;subscribe:(callback:()=>void)=>()=>void}}

// Only the reader which requested fullscreen may close it during disposal.
const fullscreenOwners=new WeakMap<Document,symbol>();
const controlSelector='[data-reader-controls]';
const persistentSelector='[data-reader-keep-controls],.reader-panel,.image-viewer,[role="dialog"],[role="menu"],dialog[open]';
const readerUiSelector=`${controlSelector},${persistentSelector}`;
const pageKeys=new Set(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' ','Spacebar','PageUp','PageDown','Home','End']);

/** Independent fullscreen and auto-hiding controls; showing controls never changes reader geometry. */
export function createReaderImmersion(options:ImmersionOptions){
 let state:ReaderImmersionState={autoHide:false,fullscreen:false,controlsVisible:true};
 let root:HTMLElement|null=null,doc:Document|null=null,disposed=false;
 const bridge=options.fullscreenBridge;let offBridge=()=>{};
 const activeFullscreen=()=>bridge?bridge.active():!!doc?.fullscreenElement;
 let desiredFullscreen=false,entering=false,operation=0,keyboardMode=false,pointerHeld=false;
 let pointer:{x:number;y:number}|null=null,movementAnchor:{x:number;y:number}|null=null,timer:ReturnType<typeof setTimeout>|undefined;
 const owner=Symbol('reader-fullscreen'),idleMs=Math.max(100,options.idleMs??2800);

 function publish(change:Partial<ReaderImmersionState>){
  if(disposed)return;
  const next={...state,...change};
  if(next.autoHide===state.autoHide&&next.fullscreen===state.fullscreen&&next.controlsVisible===state.controlsVisible)return;
  state=next;options.changed({...state});
 }
 function clearTimer(){if(timer!==undefined){clearTimeout(timer);timer=undefined}}
 function insideControls(element:Element|null){return !!(root&&element&&root.contains(element)&&element.closest(controlSelector))}
 function insideReaderUi(target:EventTarget|null){
  const element=target as Element|null;
  return !!(root&&element&&root.contains(element)&&typeof element.closest==='function'&&element.closest(readerUiSelector));
 }
 function keepControls(){
  if(!root||!doc)return false;
  if(pointerHeld)return true;
  if([...root.querySelectorAll<HTMLElement>(persistentSelector)].some(element=>!element.hidden&&element.getClientRects().length>0))return true;
  if(keyboardMode&&insideControls(doc.activeElement))return true;
  // Hit-test now: a layout change can move the old hovered button elsewhere.
  return !!(pointer&&insideControls(doc.elementFromPoint(pointer.x,pointer.y)));
 }
 function arm(){
  clearTimer();if(disposed||!root||!state.autoHide)return;
  timer=setTimeout(()=>{
   timer=undefined;if(disposed||!state.autoHide)return;
   if(keepControls())arm();
   else{if(pointer)movementAnchor={...pointer};publish({controlsVisible:false})}
  },idleMs);
 }
 function activity(){if(disposed)return;publish({controlsVisible:true});arm()}
 function setAutoHide(value:boolean){
  if(disposed)return;
  publish({autoHide:value,controlsVisible:true});arm();
 }
 function fullscreenChanged(){
  if(disposed||!doc)return;
  const active=activeFullscreen(),wasFullscreen=state.fullscreen;
  publish({fullscreen:active});
  if(!active&&wasFullscreen){
   desiredFullscreen=false;entering=false;
   if(fullscreenOwners.get(doc)===owner)fullscreenOwners.delete(doc);
  }
  activity();
 }
 async function closeFullscreen(){
  operation++;desiredFullscreen=false;entering=false;
  const currentDoc=doc;
  if(!currentDoc||!activeFullscreen())return;
  try{await (bridge?bridge.exit():currentDoc.exitFullscreen())}catch{if(!disposed)options.notify?.('РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹Р№С‚Рё РёР· РїРѕР»РЅРѕРіРѕ СЌРєСЂР°РЅР°. РќР°Р¶РјРёС‚Рµ Esc.')}
  if(!disposed)fullscreenChanged();
 }
 async function enterFullscreen(){
  const currentDoc=doc;if(disposed||!currentDoc)return;
  desiredFullscreen=true;
  if(activeFullscreen()){fullscreenChanged();return}
  const generation=++operation;entering=true;fullscreenOwners.set(currentDoc,owner);
  try{
   // Call synchronously in the originating click/key event to retain activation.
   await (bridge?bridge.enter():currentDoc.documentElement.requestFullscreen());
   if(disposed||generation!==operation){
    if(!desiredFullscreen&&fullscreenOwners.get(currentDoc)===owner&&(bridge||currentDoc.fullscreenElement)){try{await (bridge?bridge.exit():currentDoc.exitFullscreen())}catch{}}
    return;
   }
   entering=false;fullscreenChanged();
  }catch{
   if(disposed||generation!==operation)return;
   entering=false;desiredFullscreen=false;
   if(fullscreenOwners.get(currentDoc)===owner)fullscreenOwners.delete(currentDoc);
   publish({fullscreen:activeFullscreen()});activity();
   options.notify?.('РќРµ СѓРґР°Р»РѕСЃСЊ РїРµСЂРµРєР»СЋС‡РёС‚СЊ РїРѕР»РЅС‹Р№ СЌРєСЂР°РЅ. РџРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·.');
  }
 }
 async function toggleFullscreen(){
  if(disposed)return;
  if(activeFullscreen()||entering)await closeFullscreen();else await enterFullscreen();
 }
 function handleEscape(){
  if(disposed||!activeFullscreen()&&!entering)return false;
  void closeFullscreen();return true;
 }
 function mount(element:HTMLElement){
  root=element;doc=element.ownerDocument;
  const currentDoc=doc;
  const recordPointer=(event:PointerEvent)=>{pointer={x:event.clientX,y:event.clientY};return pointer};
  const move=(event:PointerEvent)=>{
   const current=recordPointer(event);
   if(!movementAnchor){movementAnchor={...current};return}
   // Measure displacement from one anchor, not travelled distance: small jitter
   // must neither reveal the overlay nor postpone its idle timeout forever.
   const threshold=(currentDoc.defaultView?.innerWidth??1024)<850?48:64;
   if(Math.hypot(current.x-movementAnchor.x,current.y-movementAnchor.y)<threshold)return;
   movementAnchor={...current};activity();
  };
  const down=(event:PointerEvent)=>{keyboardMode=false;pointerHeld=true;movementAnchor={...recordPointer(event)};activity()};
  const release=()=>{if(pointerHeld){pointerHeld=false;activity()}};
  const leave=()=>{pointer=null};
  const key=(event:KeyboardEvent)=>{
   if(['Shift','Control','Alt','Meta'].includes(event.key))return;
   if(pageKeys.has(event.key)&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!insideReaderUi(event.target))return;
   keyboardMode=true;activity();
  };
  const wheel=(event:WheelEvent)=>{if(insideReaderUi(event.target))activity()};
  const focus=(event:FocusEvent)=>{if(insideReaderUi(event.target))activity()};
  // Making a hidden toolbar inert can blur its last mouse-focused button.
  // That programmatic blur must not bring the toolbar straight back again.
  const blur=()=>{if(state.controlsVisible)arm()};
  root.addEventListener('pointermove',move,{passive:true});root.addEventListener('pointerdown',down,{passive:true});
  root.addEventListener('pointerleave',leave,{passive:true});root.addEventListener('wheel',wheel,{passive:true});
  root.addEventListener('focusin',focus);root.addEventListener('focusout',blur);
  currentDoc.addEventListener('keydown',key,true);currentDoc.addEventListener('fullscreenchange',fullscreenChanged);
  currentDoc.addEventListener('pointerup',release,true);currentDoc.addEventListener('pointercancel',release,true);
  if(bridge)offBridge=bridge.subscribe(fullscreenChanged);
  fullscreenChanged();
  return()=>{
   if(disposed)return;
   disposed=true;offBridge();operation++;desiredFullscreen=false;entering=false;clearTimer();
   element.removeEventListener('pointermove',move);element.removeEventListener('pointerdown',down);
   element.removeEventListener('pointerleave',leave);element.removeEventListener('wheel',wheel);
   element.removeEventListener('focusin',focus);element.removeEventListener('focusout',blur);
   currentDoc.removeEventListener('keydown',key,true);currentDoc.removeEventListener('fullscreenchange',fullscreenChanged);
   currentDoc.removeEventListener('pointerup',release,true);currentDoc.removeEventListener('pointercancel',release,true);
   if(fullscreenOwners.get(currentDoc)===owner&&currentDoc.fullscreenElement){void currentDoc.exitFullscreen().catch(()=>{})}
   root=null;doc=null;
  };
 }
 return{mount,setAutoHide,toggleFullscreen,activity,handleEscape};
}

