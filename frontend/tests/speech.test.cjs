const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function helpers(api = async () => ({})) {
 const source = fs.readFileSync(path.join(__dirname, '../src/speech.ts'), 'utf8');
 const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const exports = {};
 vm.runInNewContext(code, {exports, require:() => ({api})});
 return exports;
}

test('long Russian paragraphs retain every word within request bounds', () => {
 const {splitSpeech} = helpers();
 const text = 'Тихий вечер. За окном шелестят деревья, а мы продолжаем читать книгу. '.repeat(250);
 const parts = splitSpeech([{id:'paragraph-1',text}]);
 assert.ok(parts.length > 1);
 assert.ok(parts.every(part => part.id === 'paragraph-1' && part.text.length <= 1200));
 assert.equal(parts.map(part => part.text).join('').replace(/\s/g,''), text.replace(/\s/g,''));
});

test('long tokens do not lose text or split Unicode surrogate pairs', () => {
 const {splitSpeech} = helpers();
 const text = 'аб🕮'.repeat(1500);
 const parts = splitSpeech([{id:'p',text}], 1199);
 assert.equal(parts.map(part => part.text).join(''), text);
 assert.ok(parts.every(part => part.text.length <= 1199 && !/[\uD800-\uDBFF]$/.test(part.text)));
});

test('new reader waits for all queued cancellation requests', async () => {
 const requests=[];
 const {cancelLocalSpeech,waitForSpeechCancellation} = helpers(() => new Promise(resolve => requests.push(resolve)));
 cancelLocalSpeech();cancelLocalSpeech();
 let settled=false;
 const wait=waitForSpeechCancellation().then(()=>{settled=true});
 await new Promise(resolve => setImmediate(resolve));
 assert.equal(requests.length,1);assert.equal(settled,false);
 requests[0]({});
 await new Promise(resolve => setImmediate(resolve));
 assert.equal(requests.length,2);assert.equal(settled,false);
 requests[1]({});await wait;
 assert.equal(settled,true);
});
