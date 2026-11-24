const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const exportsObject={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/continue-reading.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsObject,Date});
const {continueReading,continueCapacity}=exportsObject;
test('recent openings sort by actual time, never metadata/import order, with no fixed cap',()=>{
 const books=Array.from({length:7},(_,i)=>({id:i,status:'reading',progress:20,last_opened:`2026-01-0${i+1}T00:00:00Z`,added_at:`2030-01-0${7-i}`}));
 const result=continueReading(books);assert.equal(result.length,7);assert.equal(result[0].id,6);assert.equal(books[0].id,0);
 books[1]={...books[1],last_opened:'2026-02-01T00:00:00+03:00'};assert.equal(continueReading(books)[0].id,1);
});
test('newly opened reading books are shown, while planned, unread and completed statuses are excluded',()=>{
 const items=[{id:'new',status:'reading',progress:0,last_opened:'2026-01-01'},{id:'unopened',status:'unread',progress:0},{id:'unread-after-open',status:'unread',progress:40,last_opened:'2027-01-01'},{id:'planned',status:'planned',progress:40,last_opened:'2027-01-01'},{id:'want',status:'want',progress:40,last_opened:'2027-01-01'},{id:'finished',status:'finished',progress:80,last_opened:'2027-01-01'},{id:'read',status:'read',progress:10,last_opened:'2027-01-01'},{id:'legacy',status:'reading',progress:20}];
 assert.deepEqual(Array.from(continueReading(items),b=>b.id),['new','legacy']);
});

test('a jump to position 100 remains in Continue reading until explicitly completed',()=>{
 const jumped={id:'end',status:'reading',progress:100,last_opened:'2026-01-01'};
 assert.equal(continueReading([jumped])[0],jumped);
 assert.equal(continueReading([{...jumped,status:'read',progress:82}]).length,0);
});
test('row capacity follows available width, including four and five cards',()=>{
 assert.equal(continueCapacity(752),2);assert.equal(continueCapacity(902),3);assert.equal(continueCapacity(1304),4);assert.equal(continueCapacity(1576),5);assert.equal(continueCapacity(1832),6);assert.equal(continueCapacity(0),1);
});
