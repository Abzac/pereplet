/** Keep keyboard navigation inside an open modal, then return to its trigger. */
export function dialogFocus(node:HTMLElement){
 const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
 const controls=()=>Array.from(node.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')).filter(el=>el.getClientRects().length>0);
 let active=true;
 const first=()=>controls()[0]?.focus({preventScroll:true});
 queueMicrotask(()=>{if(active)first()});
 const key=(event:KeyboardEvent)=>{
  if(event.key!=='Tab')return;
  const items=controls(),index=items.indexOf(document.activeElement as HTMLElement);
  if(!items.length){event.preventDefault();return;}
  if(event.shiftKey&&index<=0){event.preventDefault();items.at(-1)!.focus()}
  else if(!event.shiftKey&&(index===items.length-1||index===-1)){event.preventDefault();items[0].focus()}
 };
 node.addEventListener('keydown',key);
 return{destroy(){active=false;node.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus({preventScroll:true})}};
}
