import {desktop,native} from './desktop';
let queue:Promise<unknown>=Promise.resolve();
const api=()=>native().window.getCurrentWindow();
export const windowStateEvent='pereplet-window-state';
export async function readWindowState(){
 const state=desktop?{fullscreen:await api().isFullscreen(),maximized:await api().isMaximized()}:{fullscreen:!!document.fullscreenElement,maximized:false};
 window.dispatchEvent(new CustomEvent(windowStateEvent,{detail:state}));return state;
}
function run(action:()=>Promise<void>){const next=queue.then(action);queue=next.catch(()=>{});return next.finally(()=>readWindowState());}
export function setWindowFullscreen(value:boolean){return run(async()=>{
 if(desktop){if(document.fullscreenElement)await document.exitFullscreen();await api().setFullscreen(value)}
 else if(value){if(!document.fullscreenElement)await document.documentElement.requestFullscreen()}
 else if(document.fullscreenElement)await document.exitFullscreen();
});}
export function restoreOrMaximize(){return run(async()=>{
 if(document.fullscreenElement)await document.exitFullscreen();
 if(await api().isFullscreen()){await api().setFullscreen(false);if(await api().isMaximized())await api().toggleMaximize()}
 else await api().toggleMaximize();
});}
export function nativeFullscreenBridge(){
 if(!desktop)return undefined;
 let active=false;const listeners=new Set<()=>void>();
 return {active:()=>active,enter:()=>setWindowFullscreen(true),exit:()=>setWindowFullscreen(false),subscribe(callback:()=>void){
  listeners.add(callback);const handler=(e:Event)=>{active=(e as CustomEvent).detail.fullscreen;callback()};
  window.addEventListener(windowStateEvent,handler);void readWindowState();
  return()=>{listeners.delete(callback);window.removeEventListener(windowStateEvent,handler)};
 }};
}
