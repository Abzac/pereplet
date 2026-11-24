<script lang="ts">
 import {onMount} from 'svelte';import {X,Plus,Minus} from 'phosphor-svelte';
 import {fitImage,zoomImage} from './image-viewer';
 export let src:string;export let onclose:()=>void;
 let canvas:HTMLElement,dialog:HTMLElement,closeButton:HTMLButtonElement;
 let natural={width:0,height:0},available={width:0,height:0},view={scale:1,x:0,y:0},fitting=true,failed=false;
 let drag:{id:number;x:number;y:number;startX:number;startY:number;moved:boolean}=null,suppressClick=false;
 $: fitScale=fitImage(natural,available);
 $: if(fitting)view={scale:fitScale,x:0,y:0};
 function fit(){fitting=true;view={scale:fitScale,x:0,y:0}}
 function zoom(scale:number,x=0,y=0){fitting=false;view=zoomImage(view,scale,{x,y},fitScale)}
 function wheel(event:WheelEvent){event.preventDefault();event.stopPropagation();if(!natural.width)return;const bounds=canvas.getBoundingClientRect();const delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?available.height:1);zoom(view.scale*Math.exp(-Math.max(-300,Math.min(300,delta))*.002),event.clientX-bounds.left-bounds.width/2,event.clientY-bounds.top-bounds.height/2)}
 function down(event:PointerEvent){if(event.button!==0)return;event.stopPropagation();suppressClick=false;drag={id:event.pointerId,x:event.clientX,y:event.clientY,startX:view.x,startY:view.y,moved:false};canvas.setPointerCapture(event.pointerId)}
 function move(event:PointerEvent){if(!drag||drag.id!==event.pointerId)return;const x=event.clientX-drag.x,y=event.clientY-drag.y;if(Math.hypot(x,y)>5)drag.moved=true;if(drag.moved){fitting=false;view={...view,x:drag.startX+x,y:drag.startY+y}}}
 function up(event:PointerEvent){if(!drag||drag.id!==event.pointerId)return;suppressClick=drag.moved||event.type==='pointercancel';drag=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId)}
 function click(event:MouseEvent){event.stopPropagation();if(suppressClick){suppressClick=false;return}onclose()}
 function keys(event:KeyboardEvent){
  event.stopPropagation();
  if(event.key==='Escape'){event.preventDefault();onclose();return}
  if(event.key==='Tab'){const buttons=Array.from(dialog.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));const first=buttons[0],last=buttons.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}
 }
 onMount(()=>{const previous=document.activeElement as HTMLElement;const resize=new ResizeObserver(()=>{available={width:canvas.clientWidth,height:canvas.clientHeight}});resize.observe(canvas);canvas.addEventListener('wheel',wheel,{passive:false});dialog.addEventListener('keydown',keys);closeButton.focus({preventScroll:true});return()=>{resize.disconnect();canvas.removeEventListener('wheel',wheel);dialog.removeEventListener('keydown',keys);if(previous?.isConnected)previous.focus({preventScroll:true})}});
</script>

<div class="image-viewer illustration-viewer" bind:this={dialog} role="dialog" aria-modal="true" aria-label="Просмотр изображения">
 <div class="image-toolbar"><span>Иллюстрация</span><button class="icon-button" aria-label="Уменьшить" disabled={!natural.width} onclick={()=>zoom(view.scale/1.25)}><Minus size={23}/></button><span class="image-scale" aria-live="polite">{Math.round(view.scale*100)}%</span><button class="icon-button" aria-label="Увеличить" disabled={!natural.width} onclick={()=>zoom(view.scale*1.25)}><Plus size={23}/></button><button class:active={fitting} aria-pressed={fitting} disabled={!natural.width} onclick={fit}>Вписать</button><button title="Исходный размер: один пиксель изображения на пиксель экрана" disabled={!natural.width} onclick={()=>{fitting=false;view={scale:1,x:0,y:0}}}>100%</button><button class="icon-button" bind:this={closeButton} aria-label="Закрыть изображение" onclick={onclose}><X size={25}/></button></div>
 <div class="image-canvas" bind:this={canvas} role="button" tabindex="-1" aria-label="Изображение: нажмите, чтобы закрыть; колесо меняет масштаб, перетаскивание перемещает" class:dragging={!!drag?.moved} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onclick={click} onkeydown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onclose()}}}>
  {#if failed}<p role="status">Не удалось открыть изображение</p>{:else}<img src={src} alt="Иллюстрация из книги" draggable="false" onload={event=>{const image=event.currentTarget as HTMLImageElement;natural={width:image.naturalWidth,height:image.naturalHeight}}} onerror={()=>failed=true} style:width={`${natural.width*view.scale}px`} style:height={`${natural.height*view.scale}px`} style:transform={`translate(${view.x}px,${view.y}px)`} style:visibility={natural.width?'visible':'hidden'}/>{/if}
 </div>
 <p class="image-help">Колесо — масштаб · Перетаскивание — перемещение · Нажмите на изображение или Esc, чтобы закрыть</p>
</div>

<style>
 .illustration-viewer .image-toolbar{flex:none;min-height:64px;height:auto;gap:12px}.illustration-viewer .image-toolbar .active{border-color:#c7b98d;background:#ffffff12}.image-scale{min-width:44px;text-align:center}
 .illustration-viewer .image-canvas{position:relative;padding:0;cursor:zoom-out;outline:none}.illustration-viewer .image-canvas.dragging{cursor:grabbing}.illustration-viewer .image-canvas img{flex:none;max-width:none;max-height:none;margin:0;object-fit:contain;background:white;pointer-events:auto}
 .image-help{flex:none;margin:0;padding:8px 20px 12px;text-align:center;color:#b6bdc2;font-size:11px;line-height:1.5;pointer-events:none}
 @media(max-width:600px){.illustration-viewer .image-toolbar{gap:5px;padding:8px 10px}.illustration-viewer .image-toolbar>span:first-child{display:none}.illustration-viewer .image-toolbar .icon-button:last-child{margin-left:auto}.image-help{font-size:10px}}
</style>
