const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const exportsMap={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/reader-search.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:exportsMap});
const {canonicalOffsets,textRange,literalMatches}=exportsMap;
const plain=value=>JSON.parse(JSON.stringify(value));
test('normalization maps the second repeated match after emoji and NBSP without widening the highlight',()=>{
 const raw='\n 🕮  Кот\u00a0и\n   Кот. ', canonical='🕮 Кот и Кот.';
 const spans=literalMatches(canonical,'кот');
 assert.equal(spans.length,2);
 for(const span of spans){const mapped=canonicalOffsets(raw,canonical,span.start,span.end);assert.equal(raw.slice(...mapped),'Кот');}
 assert.equal(canonicalOffsets(raw,'unrelated',0,2),null);
});
test('literal punctuation is not a regex and UTF16 positions retain surrogate pairs',()=>{
 assert.deepEqual(plain(literalMatches('a+b 🕮 a+b','a+b')),[{start:0,end:3},{start:7,end:10}]);
 assert.deepEqual(plain(literalMatches('🕮🕮','🕮')),[{start:0,end:2},{start:2,end:4}]);
 assert.equal(literalMatches('aaaa','a',2).length,2);
 assert.equal(literalMatches('text','').length,0);
});
test('a range crosses inline text nodes while selecting only the matching phrase',()=>{
 const nodes=['\n Вот Бене','дикт\u00a0и ','ещё.'].map(data=>({data,textContent:data}));
 let i=0;
 const element={ownerDocument:{createTreeWalker:()=>({nextNode:()=>nodes[i++]}),createRange:()=>({setStart(node,offset){this.start=[nodes.indexOf(node),offset]},setEnd(node,offset){this.end=[nodes.indexOf(node),offset]}})}};
 const range=textRange(element,'Вот Бенедикт и ещё.',4,14);
 assert.deepEqual(plain(range.start),[0,6]);assert.deepEqual(plain(range.end),[1,6]);
});
test('invalid or mismatched canonical ranges cannot mark unrelated text',()=>{
 for(const [start,end] of [[-1,1],[1,1],[2,1],[0,20]])assert.equal(canonicalOffsets('text','text',start,end),null);
 assert.equal(canonicalOffsets('other','text',0,2),null);
});
