const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const source=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/reader-immersion.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 let now=0,sequence=0;const timers=new Map(),changes=[],messages=[];
 const clock={setTimeout(fn,ms){const id=++sequence;timers.set(id,{fn,at:now+ms});return id},clearTimeout(id){timers.delete(id)},advance(ms){const end=now+ms;for(;;){const ready=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!ready)break;now=ready[1].at;timers.delete(ready[0]);ready[1].fn()}now=end}};
 class Events{listeners=new Map();addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(fn)}removeEventListener(name,fn){this.listeners.get(name)?.delete(fn)}emit(name,values={}){for(const fn of [...this.listeners.get(name)||[]])fn({type:name,...values})}get listenerCount(){return [...this.listeners.values()].reduce((sum,set)=>sum+set.size,0)}}
 const doc=new Events();doc.fullscreenElement=null;doc.activeElement=null;doc.hit=null;doc.elementFromPoint=()=>doc.hit;doc.defaultView={innerWidth:1280};
 const root=new Events();root.ownerDocument=doc;root.panels=[];root.contains=element=>element?.root===root;root.querySelectorAll=()=>root.panels;
 const content={root,closest:()=>null},control={root,closest:selector=>selector.includes('[data-reader-controls]')?control:null};
 const panel={root,closest:selector=>selector.includes('.reader-panel')?panel:null};
 let requestCount=0,exitCount=0,requestMode='auto',resolveRequest,rejectRequest;
 doc.documentElement={requestFullscreen(){requestCount++;if(requestMode==='reject')return Promise.reject(new Error('blocked'));if(requestMode==='pending')return new Promise((yes,no)=>{resolveRequest=()=>{doc.fullscreenElement=doc.documentElement;doc.emit('fullscreenchange');yes()};rejectRequest=no});doc.fullscreenElement=doc.documentElement;doc.emit('fullscreenchange');return Promise.resolve()}};
 doc.exitFullscreen=()=>{exitCount++;doc.fullscreenElement=null;doc.emit('fullscreenchange');return Promise.resolve()};
 const exports={};vm.runInNewContext(source,{exports,WeakMap,Symbol,setTimeout:clock.setTimeout,clearTimeout:clock.clearTimeout});
 let state={autoHide:false,fullscreen:false,controlsVisible:true};
 const reader=exports.createReaderImmersion({changed:next=>{state={...next};changes.push(state)},notify:message=>messages.push(message),idleMs:100});
 const cleanup=reader.mount(root);
 return{reader,root,doc,content,control,panel,clock,cleanup,changes,messages,timers,get state(){return state},get requestCount(){return requestCount},get exitCount(){return exitCount},pending(){requestMode='pending'},reject(){requestMode='reject'},resolve(){resolveRequest()},rejectPending(){rejectRequest(new Error('cancelled'))}};
}

test('auto-hide controls hide after inactivity and deliberate pointer movement reveals them',()=>{
 const f=fixture();f.doc.hit=f.content;f.root.emit('pointermove',{clientX:400,clientY:300});f.reader.setAutoHide(true);f.clock.advance(99);assert.equal(f.state.controlsVisible,true);f.clock.advance(1);assert.equal(f.state.controlsVisible,false);
 f.root.emit('pointermove',{clientX:464,clientY:300});assert.equal(f.state.controlsVisible,true);f.clock.advance(100);assert.equal(f.state.controlsVisible,false);
 f.reader.setAutoHide(false);f.clock.advance(1000);assert.deepEqual(f.state,{autoHide:false,fullscreen:false,controlsVisible:true});assert.equal(f.timers.size,0);f.cleanup();
});
test('wheel and page keys on the content neither reveal controls nor postpone hiding',()=>{
 const f=fixture();f.reader.setAutoHide(true);f.clock.advance(60);
 f.root.emit('wheel',{target:f.content});f.doc.emit('keydown',{key:'ArrowRight',target:f.content});f.clock.advance(40);assert.equal(f.state.controlsVisible,false);
 for(const key of ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown',' ','Spacebar','PageUp','PageDown','Home','End']){
  f.doc.emit('keydown',{key,target:f.content});assert.equal(f.state.controlsVisible,false,key);
 }
 f.root.emit('wheel',{target:f.content});assert.equal(f.state.controlsVisible,false);assert.equal(f.timers.size,0);
 f.doc.emit('keydown',{key:' ',shiftKey:true,target:f.content});assert.equal(f.state.controlsVisible,false);
 f.doc.emit('keydown',{key:'Control',target:f.content});assert.equal(f.state.controlsVisible,false);f.cleanup();
});
test('pointer jitter is not accumulated and does not keep visible controls alive',()=>{
 const f=fixture();f.doc.hit=f.content;f.root.emit('pointermove',{clientX:400,clientY:300});f.reader.setAutoHide(true);
 for(let step=0;step<5;step++){f.clock.advance(20);f.root.emit('pointermove',{clientX:400+(step%2?6:-6),clientY:300+(step%2?4:-4)})}
 assert.equal(f.state.controlsVisible,false);
 for(let step=0;step<20;step++)f.root.emit('pointermove',{clientX:400+(step%2?8:-8),clientY:300});
 assert.equal(f.state.controlsVisible,false);
 // Hiding resets the movement anchor to the latest pointer, not the old origin.
 f.root.emit('pointermove',{clientX:430,clientY:300});assert.equal(f.state.controlsVisible,false);
 f.root.emit('pointermove',{clientX:470,clientY:300});assert.equal(f.state.controlsVisible,true);f.cleanup();
});
test('small windows need only 48px movement, while click or tap always reveals controls',()=>{
 const f=fixture();f.doc.defaultView.innerWidth=720;f.root.emit('pointermove',{clientX:100,clientY:100});f.reader.setAutoHide(true);f.clock.advance(100);
 f.root.emit('pointermove',{clientX:147,clientY:100});assert.equal(f.state.controlsVisible,false);f.root.emit('pointermove',{clientX:148,clientY:100});assert.equal(f.state.controlsVisible,true);
 f.clock.advance(100);assert.equal(f.state.controlsVisible,false);f.root.emit('pointerdown',{clientX:149,clientY:100,pointerType:'touch'});assert.equal(f.state.controlsVisible,true);f.doc.emit('pointerup');f.cleanup();
});
test('UI interaction, Tab and shortcuts still reveal controls',()=>{
 const f=fixture();f.reader.setAutoHide(true);f.clock.advance(100);
 for(const key of ['Tab','f','F11','Escape']){f.doc.emit('keydown',{key,target:f.content});assert.equal(f.state.controlsVisible,true,key);f.clock.advance(100)}
 f.doc.emit('keydown',{key:'Home',ctrlKey:true,target:f.content});assert.equal(f.state.controlsVisible,true);f.clock.advance(100);
 f.doc.emit('keydown',{key:'ArrowRight',target:f.control});assert.equal(f.state.controlsVisible,true);f.clock.advance(100);
 f.root.emit('wheel',{target:f.panel});assert.equal(f.state.controlsVisible,true);f.clock.advance(100);
 f.root.emit('focusin',{target:f.control});assert.equal(f.state.controlsVisible,true);f.cleanup();
});
test('hover is hit-tested after layout moves controls, and mouse focus alone never pins the overlay',()=>{
 const f=fixture();f.doc.hit=f.control;f.doc.activeElement=f.control;f.root.emit('pointerdown',{clientX:900,clientY:30});f.doc.emit('pointerup');f.reader.setAutoHide(true);
 f.clock.advance(300);assert.equal(f.state.controlsVisible,true);
 f.doc.hit=f.content;f.clock.advance(100);assert.equal(f.state.controlsVisible,false);
 f.root.emit('focusout',{target:f.control});assert.equal(f.state.controlsVisible,false,'blur from inert toolbar must not reopen it');f.cleanup();
});
test('keyboard navigation and visible side panels keep controls available until interaction ends',()=>{
 const f=fixture();f.reader.setAutoHide(true);f.doc.activeElement=f.control;f.doc.emit('keydown',{key:'Tab'});f.root.emit('focusin');f.clock.advance(300);assert.equal(f.state.controlsVisible,true);
 f.doc.hit=f.content;f.root.emit('pointerdown',{clientX:400,clientY:300});f.doc.emit('pointerup');f.clock.advance(100);assert.equal(f.state.controlsVisible,false);
 f.root.panels=[{hidden:false,getClientRects:()=>[{}]}];f.reader.activity();f.clock.advance(300);assert.equal(f.state.controlsVisible,true);
 f.root.panels=[];f.clock.advance(100);assert.equal(f.state.controlsVisible,false);f.cleanup();
});
test('scrubber dragging keeps controls visible outside its bounds until pointer release or cancellation',()=>{
 const f=fixture();f.reader.setAutoHide(true);f.doc.hit=f.content;f.root.emit('pointerdown',{clientX:300,clientY:600});f.root.emit('pointerleave');f.clock.advance(500);assert.equal(f.state.controlsVisible,true);
 f.doc.emit('pointerup');f.clock.advance(100);assert.equal(f.state.controlsVisible,false);
 f.root.emit('pointerdown',{clientX:300,clientY:600});f.doc.emit('pointercancel');f.clock.advance(100);assert.equal(f.state.controlsVisible,false);f.cleanup();
});
test('fullscreen and auto-hide are independent; Escape only exits fullscreen',async()=>{
 const f=fixture();f.reader.setAutoHide(true);assert.equal(f.reader.handleEscape(),false);
 await f.reader.toggleFullscreen();assert.equal(f.state.fullscreen,true);assert.equal(f.state.autoHide,true);
 assert.equal(f.reader.handleEscape(),true);await flush();assert.equal(f.state.fullscreen,false);assert.equal(f.state.autoHide,true);f.cleanup();
});
test('Escape cancels a pending fullscreen request without changing auto-hide',async()=>{
 const f=fixture();f.reader.setAutoHide(true);f.pending();const pending=f.reader.toggleFullscreen();assert.equal(f.reader.handleEscape(),true);f.resolve();await pending;await flush();assert.equal(f.state.fullscreen,false);assert.equal(f.state.autoHide,true);f.cleanup();
});
test('fullscreen rejection reports error and does not affect auto-hide',async()=>{
 const f=fixture();f.reject();await f.reader.toggleFullscreen();assert.equal(f.messages.length,1);assert.equal(f.state.fullscreen,false);assert.equal(f.state.autoHide,false);f.cleanup();
});
test('cleanup releases timers/listeners and owned fullscreen without callbacks; foreign fullscreen is retained',async()=>{
 const f=fixture();await f.reader.toggleFullscreen();const before=f.changes.length;f.cleanup();await flush();f.clock.advance(1000);assert.equal(f.changes.length,before);assert.equal(f.doc.fullscreenElement,null);assert.equal(f.timers.size,0);assert.equal(f.root.listenerCount,0);assert.equal(f.doc.listenerCount,0);
 const g=fixture();g.doc.fullscreenElement={foreign:true};g.doc.emit('fullscreenchange');g.cleanup();assert.equal(g.exitCount,0);assert.ok(g.doc.fullscreenElement);
});
test('unmount during fullscreen request cleans up a late success and does not publish disposed state',async()=>{
 const f=fixture();f.pending();const pending=f.reader.toggleFullscreen();f.cleanup();const before=f.changes.length;f.resolve();await pending;await flush();assert.equal(f.changes.length,before);assert.equal(f.doc.fullscreenElement,null);assert.equal(f.exitCount,1);
});
