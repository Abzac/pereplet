<script lang="ts">
 import {onMount} from 'svelte';
 import {desktop,native,flushDesktopState} from './desktop';
 import {readWindowState,restoreOrMaximize,setWindowFullscreen,windowStateEvent} from './window-state';
 import {BookOpen,Minus,Square,CornersIn,X} from 'phosphor-svelte';
 const demoLibrary=location.port==='18771';
 let maximized=false,fullscreen=false,closing=false,error='';
 const directions=['North','South','West','East','NorthWest','NorthEast','SouthWest','SouthEast'];
 function windowApi(){return native().window.getCurrentWindow()}
 async function updateState(){const state=await readWindowState();maximized=state.maximized;fullscreen=state.fullscreen}
 async function requestClose(){await windowApi().close()}
 async function closeSafely(){
  if(closing)return;closing=true;error='';
  try{await flushDesktopState();await native().core.invoke('finish_close')}
  catch(e){error=e instanceof Error?e.message:String(e);closing=false}
 }
 function drag(event:MouseEvent){if(event.button===0&&!(event.target as HTMLElement).closest('button')){if(event.detail===2)void restoreOrMaximize().then(updateState);else if(!fullscreen)void windowApi().startDragging()}}
 onMount(()=>{
  if(!desktop)return;
  document.documentElement.classList.add('desktop-app');
  const stateChanged=(e:Event)=>{const state=(e as CustomEvent).detail;fullscreen=state.fullscreen;maximized=state.maximized};
  const keys=(e:KeyboardEvent)=>{if(document.querySelector('.reader-shell'))return;if(e.key==='F11'){e.preventDefault();void setWindowFullscreen(!fullscreen)}else if(e.key==='Escape'&&fullscreen){e.preventDefault();void setWindowFullscreen(false)}};
  window.addEventListener(windowStateEvent,stateChanged);window.addEventListener('keydown',keys);

  let removed=false,offClose=()=>{},offResize=()=>{};
  void (async()=>{
   offClose=await native().event.listen('desktop-close-requested',closeSafely);
   offResize=await windowApi().onResized(updateState);
   if(removed){offClose();offResize();return}
   await updateState();await native().core.invoke('desktop_ready');
  })();
  return()=>{window.removeEventListener(windowStateEvent,stateChanged);window.removeEventListener('keydown',keys);removed=true;offClose();offResize();document.documentElement.classList.remove('desktop-app')};
 });
</script>

{#if desktop}
 <div class="desktop-titlebar" onmousedown={drag} role="presentation">
  <div class="desktop-brand"><BookOpen size={17}/><span>переплёт</span><small>{closing?'Сохраняем…':demoLibrary?'Демонстрационная библиотека':'Личная библиотека'}</small></div>
  <div class="desktop-window-buttons">
   <button title="Свернуть" aria-label="Свернуть окно" onclick={()=>native().core.invoke('minimize_window')}><Minus size={16}/></button>
   <button title={maximized||fullscreen?'Восстановить размер':'Развернуть'} aria-label={maximized||fullscreen?'Восстановить размер окна':'Развернуть окно'} onclick={()=>restoreOrMaximize().then(updateState)}>{#if maximized||fullscreen}<CornersIn size={16}/>{:else}<Square size={14}/>{/if}</button>
   <button class="desktop-close" title="Закрыть" aria-label="Закрыть приложение" disabled={closing} onclick={requestClose}><X size={18}/></button>
  </div>
 </div>
 {#if error}<div class="desktop-close-error" role="alert">{error}<button onclick={()=>error=''} aria-label="Скрыть сообщение"><X size={16}/></button></div>{/if}
 {#if !maximized&&!fullscreen}{#each directions as direction}<div class={`desktop-resize desktop-resize-${direction}`} role="presentation" onpointerdown={event=>{if(event.button===0){event.preventDefault();void windowApi().startResizeDragging(direction)}}}></div>{/each}{/if}
{/if}

<style>
 :global(html.desktop-app){--desktop-chrome:36px}
 :global(html.desktop-app .app-shell),:global(html.desktop-app .reader-shell){height:calc(100dvh - var(--desktop-chrome))}
 :global(html.desktop-app .reader-shell:fullscreen){height:100dvh}
 .desktop-titlebar{height:36px;display:flex;align-items:center;justify-content:space-between;background:var(--side);color:var(--side-ink);border-bottom:1px solid color-mix(in srgb,var(--side-ink) 12%,transparent);user-select:none;position:relative;z-index:10000;padding-left:16px;flex-shrink:0}
 .desktop-brand{display:flex;align-items:center;gap:9px;pointer-events:none;font-family:Literata,Georgia,serif;font-size:14px;letter-spacing:.03em}
 .desktop-brand small{font-family:Inter,system-ui,sans-serif;font-size:10px;letter-spacing:0;color:var(--side-muted);margin-left:8px}
 .desktop-window-buttons{display:flex;height:36px;padding-right:4px}
 .desktop-window-buttons button{display:grid;place-items:center;width:46px;min-height:36px;padding:0;background:transparent;color:inherit;border:0;border-radius:0;box-shadow:none}
 .desktop-window-buttons button:hover{background:color-mix(in srgb,var(--side-ink) 14%,transparent)}
 .desktop-window-buttons button:focus-visible{outline:2px solid var(--gold);outline-offset:-5px}
 .desktop-window-buttons .desktop-close:hover{background:#c42b35;color:#fff}
 .desktop-close-error{position:fixed;top:43px;right:12px;z-index:12000;max-width:460px;display:flex;align-items:center;gap:12px;padding:12px 16px;color:var(--text);background:var(--surface);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow);font-size:13px}
 .desktop-resize{position:fixed;z-index:11000}
 .desktop-resize-North,.desktop-resize-South{left:8px;right:8px;height:4px;cursor:ns-resize}
 .desktop-resize-North{top:0}.desktop-resize-South{bottom:0}
 .desktop-resize-West,.desktop-resize-East{top:8px;bottom:8px;width:4px;cursor:ew-resize}
 .desktop-resize-West{left:0}.desktop-resize-East{right:0}
 .desktop-resize-NorthWest,.desktop-resize-NorthEast,.desktop-resize-SouthWest,.desktop-resize-SouthEast{width:9px;height:9px}
 .desktop-resize-NorthWest{left:0;top:0;cursor:nwse-resize}.desktop-resize-NorthEast{right:0;top:0;cursor:nesw-resize}
 .desktop-resize-SouthWest{left:0;bottom:0;cursor:nesw-resize}.desktop-resize-SouthEast{right:0;bottom:0;cursor:nwse-resize}
</style>
