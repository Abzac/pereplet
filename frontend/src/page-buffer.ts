type Job<T>={index:number;controller:AbortController;started:boolean;promise:Promise<T>;resolve:(value:T)=>void;reject:(reason:any)=>void};
const cancelled=()=>new DOMException('Загрузка страницы отменена','AbortError');

/** A small decoded-page cache. Foreground pages precede speculative requests. */
export class PageBuffer<T> {
 private ready=new Map<number,T>();private jobs=new Map<number,Job<T>>();private queue:Job<T>[]=[];
 private protected=new Set<number>();private wanted=new Set<number>();private active=0;private disposed=false;
 constructor(private load:(index:number,signal:AbortSignal)=>Promise<T>,private release:(value:T)=>void,
  private options:{maxItems?:number;maxPending?:number;changed?:()=>void}={}){}
 get size(){return this.ready.size}get pendingCount(){return this.jobs.size}
 entries(){return [...this.ready.entries()]}
 peek(index:number){return this.ready.get(index)}
 /** Transfer decoded display pages to the caller before replacing the cache. */
 take(indices:number[]){const entries:Array<[number,T]>=[];for(const index of new Set(indices)){if(!this.ready.has(index))continue;entries.push([index,this.ready.get(index)!]);this.ready.delete(index)}return entries}
 plan(visible:number[],ahead:number[]=[]){
  if(this.disposed)return;
  this.protected=new Set(visible);this.wanted=new Set([...visible,...ahead]);
  for(const job of this.jobs.values())if(!this.wanted.has(job.index))this.cancel(job);
  this.prune();
  // Start visible pages first. A rejected prefetch is deliberately consumed.
  for(const index of [...visible,...ahead])void this.get(index,visible.includes(index)).catch(()=>{});
 }
 get(index:number,foreground=true):Promise<T>{
  if(this.disposed)return Promise.reject(cancelled());
  if(this.ready.has(index)){const value=this.ready.get(index)!;this.ready.delete(index);this.ready.set(index,value);return Promise.resolve(value)}
  let job=this.jobs.get(index);
  if(job?.controller.signal.aborted)job=undefined;
  if(job){if(foreground&&!job.started){this.queue=this.queue.filter(item=>item!==job);this.queue.unshift(job);this.pump()}return job.promise}
  let resolve:(value:T)=>void,reject:(reason:any)=>void;
  const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no});void promise.catch(()=>{});
  job={index,controller:new AbortController(),started:false,promise,resolve:resolve!,reject:reject!};this.jobs.set(index,job);
  if(foreground)this.queue.unshift(job);else this.queue.push(job);this.pump();return promise;
 }
 private cancel(job:Job<T>){job.controller.abort();job.reject(cancelled());if(!job.started){this.queue=this.queue.filter(item=>item!==job);if(this.jobs.get(job.index)===job)this.jobs.delete(job.index)}}
 private pump(){
  while(!this.disposed&&this.active<(this.options.maxPending||2)&&this.queue.length){
   const job=this.queue.shift()!;if(job.controller.signal.aborted)continue;job.started=true;this.active++;
   void Promise.resolve().then(()=>this.load(job.index,job.controller.signal)).then(value=>{
    if(this.disposed||job.controller.signal.aborted){this.release(value);job.reject(cancelled());return}
    this.ready.set(job.index,value);this.prune();job.resolve(value);this.options.changed?.();
   },reason=>job.reject(reason)).finally(()=>{this.active--;if(this.jobs.get(job.index)===job)this.jobs.delete(job.index);this.pump()});
  }
 }
 private prune(){
  while(this.ready.size>(this.options.maxItems||8)){
   const index=[...this.ready.keys()].find(value=>!this.protected.has(value));if(index===undefined)break;
   const value=this.ready.get(index)!;this.ready.delete(index);this.release(value);
  }
 }
 dispose(){if(this.disposed)return;this.disposed=true;for(const job of this.jobs.values())this.cancel(job);this.jobs.clear();this.queue=[];for(const value of this.ready.values())this.release(value);this.ready.clear()}
}
