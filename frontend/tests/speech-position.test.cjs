const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/speech-position.ts'), 'utf8');
const code = ts.transpileModule(source, {
 compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
}).outputText;
const helpers = {};
vm.runInNewContext(code, {exports: helpers});
const {speechOffsetInCanonical, sliceSpeechFromPosition, wordHitAtPoint} = helpers;
const plain = value => JSON.parse(JSON.stringify(value));

test('DOM whitespace, NBSP and Cyrillic map to canonical paragraph offsets', () => {
 const rendered = '\n  Ёж,\tёлка \n и\u00a0ещё  одна строка.\t';
 const canonical = 'Ёж, ёлка и ещё одна строка.';
 for (const word of ['Ёж', 'ёлка', 'ещё', 'строка']) {
  assert.equal(speechOffsetInCanonical(rendered, canonical, rendered.indexOf(word)), canonical.indexOf(word));
 }
});

test('repeated words, combining stress and non-BMP text retain exact UTF-16 offsets', () => {
 const rendered = '\n🕮  за́мок,  ёж — за́мок.';
 const canonical = '🕮 за́мок, ёж — за́мок.';
 assert.equal(speechOffsetInCanonical(rendered, canonical, rendered.lastIndexOf('за́мок')), canonical.lastIndexOf('за́мок'));
 assert.equal(speechOffsetInCanonical(rendered, canonical, rendered.indexOf('ёж')), canonical.indexOf('ёж'));
 assert.equal(speechOffsetInCanonical(rendered, 'Другой текст', 3), null);
 assert.equal(speechOffsetInCanonical(rendered, canonical, -1), null);
});

test('word queue preserves the remainder, punctuation and original objects', () => {
 const original = Object.freeze([
  Object.freeze({id: 'before', text: 'Уже прочитано.'}),
  Object.freeze({id: 'p', text: 'Вот ёлка — зелёная. «Конец!»'}),
  Object.freeze({id: 'after', text: 'Следующий абзац.  ' }),
 ]);
 const result = sliceSpeechFromPosition(original, 'p', 4);
 assert.deepEqual(plain(result), [
  {id: 'p', text: 'ёлка — зелёная. «Конец!»'},
  {id: 'after', text: 'Следующий абзац.  '},
 ]);
 result[1].text = 'Changed';
 assert.equal(original[1].text, 'Вот ёлка — зелёная. «Конец!»');
 assert.equal(original[2].text, 'Следующий абзац.  ');
 assert.deepEqual(plain(sliceSpeechFromPosition(original, 'missing', 0)), []);
 assert.deepEqual(plain(sliceSpeechFromPosition(original, 'p', -1)), []);
 assert.deepEqual(plain(sliceSpeechFromPosition(original, 'p', 1000)), []);
});

// A small layout fixture exercises the DOM API boundary without adding a DOM dependency.
// The parent browser smoke test covers real caret APIs and font/layout geometry.
function text(data) { return {nodeType: 3, data}; }
function element(tag, id, ...children) {
 const node = {
  nodeType: 1, tag, id, children,
  contains(other) { return this === other || this.children.some(child => child === other || child.contains?.(other)); },
  closest() {
   let current = this;
   while (current) {
    if (['a','img','svg','button','input','textarea','select','script','style'].includes(current.tag)) return current;
    current = current.parentElement;
   }
   return null;
  },
 };
 for (const child of children) child.parentElement = node;
 return node;
}
function layout(paragraph, caretNode, caretOffset, fallback = false) {
 const root = element('div', 'reader', paragraph);
 const texts = [];
 let raw = '';
 function visit(node) {
  node.start = raw.length;
  if (node.nodeType === 3) { texts.push(node); raw += node.data; }
  else node.children.forEach(visit);
  node.end = raw.length;
 }
 visit(root);
 function boundary(node, offset) {
  return node.nodeType === 3 ? node.start + offset : (node.children[offset]?.start ?? node.end);
 }
 const document = {
  target: caretNode.nodeType === 3 ? caretNode.parentElement : caretNode,
  elementFromPoint() { return this.target; },
  caretPositionFromPoint: fallback ? undefined : () => ({offsetNode: caretNode, offset: caretOffset}),
  caretRangeFromPoint: () => ({startContainer: caretNode, startOffset: caretOffset}),
  createTreeWalker(scope) {
   const nodes = texts.filter(node => scope.contains(node));
   let index = 0;
   return {nextNode: () => nodes[index++] || null};
  },
  createRange() {
   let start = 0, end = 0;
   return {
    selectNodeContents(node) { start = node.start; end = node.end; },
    setStart(node, offset) { start = boundary(node, offset); },
    setEnd(node, offset) { end = boundary(node, offset); },
    toString: () => raw.slice(start, end),
    getClientRects: () => texts.filter(node => node.start < end && node.end > start).map(node => {
     const left = Math.max(node.start, start) * 8, right = Math.min(node.end, end) * 8;
     return {left, right, top: 10, bottom: 30, width: right - left, height: 20};
    }),
   };
  },
 };
 root.ownerDocument = document;
 return {root, document, raw};
}

test('a word split across inline nodes maps past an unrelated inline ID', () => {
 const middle = text('л');
 const paragraph = element('p', 'p', text('\n  Ё'), element('em', 'inline-id', middle), text('ка,\tещё ёлка.'));
 const {root} = layout(paragraph, middle, 1);
 const result = wordHitAtPoint(root, [{id: 'p', text: 'Ёлка, ещё ёлка.'}], 4 * 8 + 4, 20);
 assert.deepEqual(plain(result), {id: 'p', offset: 0, word: 'Ёлка'});
});

test('WebKit caret fallback returns the exact second word and keeps hyphenated words intact', () => {
 const content = text('  Ёж по-прежнему спит.');
 const paragraph = element('p', 'p', content);
 const {root, raw} = layout(paragraph, content, 9, true);
 const result = wordHitAtPoint(root, [{id: 'p', text: 'Ёж по-прежнему спит.'}], raw.indexOf('прежнему') * 8 + 4, 20);
 assert.deepEqual(plain(result), {id: 'p', offset: 3, word: 'по-прежнему'});
});

test('nearest caret on whitespace, punctuation, or empty margins does not start speech', () => {
 const content = text('Ёж, ёлка.');
 const paragraph = element('p', 'p', content);
 const {root} = layout(paragraph, content, 2);
 const paragraphs = [{id: 'p', text: content.data}];
 assert.equal(wordHitAtPoint(root, paragraphs, 2 * 8 + 4, 20), null); // comma
 assert.equal(wordHitAtPoint(root, paragraphs, 3 * 8 + 4, 20), null); // space
 assert.equal(wordHitAtPoint(root, paragraphs, 400, 20), null);
 assert.equal(wordHitAtPoint(root, paragraphs, 8, 50), null);
});

test('anchors and images remain navigation, and a footnote does not join the adjacent word', () => {
 const content = text('Ёлка');
 const link = element('a', 'footnote', text('1'));
 const image = element('img', 'picture');
 const paragraph = element('p', 'p', content, link, text('.'), image);
 const {root, document} = layout(paragraph, content, 2);
 const paragraphs = [{id: 'p', text: 'Ёлка1.'}];
 assert.deepEqual(plain(wordHitAtPoint(root, paragraphs, 12, 20)), {id: 'p', offset: 0, word: 'Ёлка'});
 document.target = link;
 assert.equal(wordHitAtPoint(root, paragraphs, 36, 20), null);
 document.target = image;
 assert.equal(wordHitAtPoint(root, paragraphs, 44, 20), null);
});

test('unknown paragraphs, outside targets and mismatched canonical text fail closed', () => {
 const content = text('Ёлка');
 const paragraph = element('p', 'p', content);
 const {root, document} = layout(paragraph, content, 2);
 assert.equal(wordHitAtPoint(root, [{id: 'other', text: 'Ёлка'}], 12, 20), null);
 assert.equal(wordHitAtPoint(root, [{id: 'p', text: 'Сосна'}], 12, 20), null);
 document.target = element('div', 'outside');
 assert.equal(wordHitAtPoint(root, [{id: 'p', text: 'Ёлка'}], 12, 20), null);
});
