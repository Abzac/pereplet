export interface PaginationState {
 signature:string;counts:(number|null)[];measured:number;total:number|null;complete:boolean;error:string|null;
}
export interface GlobalPageRange {first:number;last:number;total:number}
export interface GlobalPageTarget {chapter:number;localView:number;column:number;pageNumber:number}

export function paginationState(signature:string,counts:(number|null)[],error:string|null=null):PaginationState {
 const measured=counts.filter(value=>value!==null).length,complete=measured===counts.length;
 return{signature,counts:[...counts],measured,total:complete?counts.reduce<number>((sum,value)=>sum+(value||0),0):null,complete,error};
}
/** Numbers are physical columns. A short final right-hand column is not invented. */
export function globalPageRange(counts:(number|null)[],chapter:number,localView:number,columns=1):GlobalPageRange|null {
 if(!counts.length||counts.some(value=>value===null)||chapter<0||chapter>=counts.length)return null;
 const cols=Math.max(1,Math.floor(columns)),before=counts.slice(0,chapter).reduce<number>((sum,value)=>sum+(value||0),0);
 const chapterCount=counts[chapter]||1,local=Math.min(chapterCount-1,Math.max(0,Math.floor(localView))*cols);
 return{first:before+local+1,last:before+Math.min(chapterCount,local+cols),total:counts.reduce<number>((sum,value)=>sum+(value||0),0)};
}
export function locateGlobalPage(counts:(number|null)[],pageNumber:number,columns=1):GlobalPageTarget|null {
 if(!counts.length||counts.some(value=>value===null)||!Number.isFinite(pageNumber))return null;
 const total=counts.reduce<number>((sum,value)=>sum+(value||0),0),target=Math.max(1,Math.min(total,Math.round(pageNumber))),cols=Math.max(1,Math.floor(columns));
 let remaining=target-1;
 for(let chapter=0;chapter<counts.length;chapter++){const size=counts[chapter]||1;if(remaining<size)return{chapter,localView:Math.floor(remaining/cols),column:remaining%cols,pageNumber:target};remaining-=size}
 return null;
}
export function physicalCountFromRightEdge(right:number,viewportWidth:number,columns:number,gap:number){
 const cols=Math.max(1,Math.floor(columns)),columnWidth=(viewportWidth-gap*(cols-1))/cols;
 return Math.max(1,Math.ceil((Math.max(0,right)+gap-2)/Math.max(1,columnWidth+gap)));
}
/** Read actual text/image rectangles: scrollWidth is at least two columns in a spread. */
export function physicalPageCount(flow:HTMLElement,viewportWidth:number,columns:number,gap:number):number {
 const origin=flow.getBoundingClientRect().left,range=flow.ownerDocument.createRange();let right=0;
 const walker=flow.ownerDocument.createTreeWalker(flow,NodeFilter.SHOW_TEXT);
 while(walker.nextNode()){
  const text=walker.currentNode as Text,length=text.data.trimEnd().length;if(!length)continue;
  // One real character is enough to identify this text node's final column.
  range.setStart(text,length-1);range.setEnd(text,length);
  for(const rect of Array.from(range.getClientRects()))if(rect.width>.1&&rect.height>.1)right=Math.max(right,rect.right-origin);
 }
 for(const image of Array.from(flow.querySelectorAll('img'))){for(const rect of Array.from(image.getClientRects()))if(rect.width>.1&&rect.height>.1)right=Math.max(right,rect.right-origin)}
 return physicalCountFromRightEdge(right,viewportWidth,columns,gap);
}
export function paginationSignature(bookId:string,count:number,settings:any,width:number,height:number,columns:number,gap:number,coverUrl=''){
 return JSON.stringify([2,bookId,count,settings.layout,settings.font,settings.fontSize,settings.lineHeight,settings.margin,settings.width,settings.cover,width,height,columns,gap,coverUrl]);
}
const aborted=()=>new DOMException('Пересчёт страниц отменён','AbortError');
export function abortable<T>(promise:Promise<T>,signal:AbortSignal):Promise<T>{
 if(signal.aborted)return Promise.reject(aborted());
 return new Promise((resolve,reject)=>{const cancel=()=>reject(aborted());signal.addEventListener('abort',cancel,{once:true});promise.then(value=>{signal.removeEventListener('abort',cancel);if(signal.aborted)reject(aborted());else resolve(value)},error=>{signal.removeEventListener('abort',cancel);reject(error)})});
}
export function idleBetweenChapters(signal:AbortSignal):Promise<void>{
 return new Promise((resolve,reject)=>{
  if(signal.aborted){reject(aborted());return}
  let timer:number;const finish=()=>{signal.removeEventListener('abort',cancel);signal.aborted?reject(aborted()):resolve()};
  const cancel=()=>{if(typeof cancelIdleCallback==='function')cancelIdleCallback(timer);else clearTimeout(timer);reject(aborted())};
  signal.addEventListener('abort',cancel,{once:true});timer=typeof requestIdleCallback==='function'?requestIdleCallback(finish,{timeout:350}):setTimeout(finish,16) as unknown as number;
 });
}

/** Retains only counts for four settings signatures, never chapter HTML or DOM. */
export class WholeBookPaginator<T> {
 private cache=new Map<string,(number|null)[]>();private controller:AbortController=null;private generation=0;
 constructor(private maxSignatures=4,private idle:(signal:AbortSignal)=>Promise<void>=idleBetweenChapters){}
 cancel(){this.generation++;this.controller?.abort();this.controller=null}
 dispose(){this.cancel();this.cache.clear()}
 get cacheSize(){return this.cache.size}
 async start(options:{signature:string;count:number;load:(index:number,signal:AbortSignal)=>Promise<T>;measure:(index:number,chapter:T,signal:AbortSignal)=>Promise<number>;update:(state:PaginationState)=>void}){
  this.cancel();const generation=this.generation,controller=new AbortController();this.controller=controller;
  const signal=controller.signal,count=Math.max(1,options.count),previous=this.cache.get(options.signature);
  const counts=previous?.length===count?previous:[...Array(count)].map(()=>null);
  this.cache.delete(options.signature);this.cache.set(options.signature,counts);
  while(this.cache.size>Math.max(1,this.maxSignatures))this.cache.delete(this.cache.keys().next().value!);
  const publish=(error:string|null=null)=>{if(generation===this.generation&&!signal.aborted)options.update(paginationState(options.signature,counts,error))};publish();
  try{
   for(let index=0;index<count;index++){
    if(counts[index]!==null)continue;
    await this.idle(signal);signal.throwIfAborted();
    const chapter=await options.load(index,signal);signal.throwIfAborted();
    const measured=await options.measure(index,chapter,signal);signal.throwIfAborted();
    if(!Number.isFinite(measured)||measured<1)throw new Error('Не удалось измерить страницы главы');
    counts[index]=Math.ceil(measured);publish();
   }
  }catch(error){if(!signal.aborted&&generation===this.generation){publish(error instanceof Error?error.message:String(error));controller.abort()}}
 }
}
