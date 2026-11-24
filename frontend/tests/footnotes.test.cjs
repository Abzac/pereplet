const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const out={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/footnotes.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:out});
const link=(text,attrs={})=>({textContent:text,getAttribute:name=>({href:'#a-note',...attrs}[name]??null),hasAttribute:name=>name in attrs});

test('FB2/EPUB semantics and conventional legacy markers identify footnotes',()=>{
 for(const text of ['[1]','(12)','345','[ 23 ]','12а','*','†','‡‡'])assert.equal(out.isFootnoteReference(link(text)),true,text);
 assert.equal(out.isFootnoteReference(link('См. примечание',{role:'doc-noteref'})),true);
 assert.equal(out.isFootnoteReference(link('Note',{'epub:type':'noteref'})),true);
});
test('ordinary contents links and external numeric links stay normal navigation',()=>{
 for(const text of ['Глава 1','Начало','Вернуться к тексту','2026 год','123456',''])assert.equal(out.isFootnoteReference(link(text)),false,text);
 assert.equal(out.isFootnoteReference(link('[1]',{href:'https://example.org/'})),false);
 assert.equal(out.isFootnoteReference(link('Note',{href:'https://example.org/',role:'doc-noteref'})),false);
});
