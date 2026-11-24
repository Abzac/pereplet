const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const tick = () => new Promise(resolve => setImmediate(resolve));

function helpers(options = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src/speech-audio.ts'), 'utf8');
  const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const exports = {};
  const state = {audio:[], revoked:[], created:[], timer:null, listeners:new Set(), fetches:0};
  class Audio extends EventTarget {
    constructor() { super(); this.readyState = options.readyState || 0; this.pauseCount = 0; this.loadCount = 0; state.audio.push(this); }
    addEventListener(name, handler, opts) { state.listeners.add(handler); super.addEventListener(name, handler, opts); }
    removeEventListener(name, handler) { state.listeners.delete(handler); super.removeEventListener(name, handler); }
    pause() { this.pauseCount++; }
    removeAttribute(name) { if (name === 'src') this.src = ''; }
    load() { this.loadCount++; if (options.loadThrows) throw new Error('load failed'); }
  }
  vm.runInNewContext(code, {exports, Audio, AbortController, DOMException,
    fetch: async (...args) => { state.fetches++; return options.fetch ? options.fetch(...args) : {ok:true, blob:async () => ({})}; },
    URL: {
      createObjectURL(blob) { state.created.push(blob); return 'blob:test'; },
      revokeObjectURL(url) { state.revoked.push(url); },
    },
    setTimeout(callback) { state.timer = callback; return 1; },
    clearTimeout() { state.timer = null; },
  });
  return {...exports, state};
}

test('prepared audio waits for canplay and releases media and object URL', async () => {
  const h = helpers();
  const controller = new AbortController();
  let prepared = false;
  const pending = h.prepareSpeechAudio('/audio.wav', controller.signal).then(item => { prepared = true; return item; });
  await tick();
  assert.equal(prepared, false);
  assert.equal(h.state.audio[0].preload, 'auto');
  h.state.audio[0].dispatchEvent(new Event('canplay'));
  const item = await pending;
  assert.equal(item.url, 'blob:test');
  assert.equal(h.state.listeners.size, 0);
  assert.equal(h.state.timer, null);
  item.audio.onended = () => {};
  item.audio.onerror = () => {};
  h.releaseSpeechAudio(item);
  assert.equal(item.audio.onended, null);
  assert.equal(item.audio.onerror, null);
  assert.equal(item.audio.pauseCount, 1);
  assert.equal(item.audio.src, '');
  assert.deepEqual(h.state.revoked, ['blob:test']);
});

test('already decoded audio resolves without waiting for another event', async () => {
  const h = helpers({readyState:3});
  const item = await h.prepareSpeechAudio('/audio.wav', new AbortController().signal);
  assert.equal(h.state.listeners.size, 0);
  assert.equal(h.state.timer, null);
  h.releaseSpeechAudio(item);
});

test('cache accounting includes retained WAV data and decoded sample allowance', async () => {
  const h = helpers({readyState:3,fetch:async () => ({ok:true,blob:async () => ({size:1024})})});
  const item = await h.prepareSpeechAudio('/audio.wav', new AbortController().signal);
  assert.equal(item.bytes,3072);
  h.releaseSpeechAudio(item);
});

test('abort while decoding removes listeners, timer, audio and URL', async () => {
  const h = helpers();
  const controller = new AbortController();
  const pending = h.prepareSpeechAudio('/audio.wav', controller.signal);
  const rejected = assert.rejects(pending, {name:'AbortError'});
  await tick();
  controller.abort();
  await rejected;
  assert.equal(h.state.listeners.size, 0);
  assert.equal(h.state.timer, null);
  assert.equal(h.state.audio[0].src, '');
  assert.deepEqual(h.state.revoked, ['blob:test']);
});

test('already aborted signal never starts a download', async () => {
  const h = helpers();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(h.prepareSpeechAudio('/audio.wav', controller.signal), {name:'AbortError'});
  assert.equal(h.state.fetches, 0);
  assert.equal(h.state.timer, null);
});

test('timeout aborts a stalled fetch and keeps its useful timeout error', async () => {
  let fetchSignal;
  const h = helpers({fetch: (_url, {signal}) => new Promise((_resolve, reject) => {
    fetchSignal = signal;
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), {once:true});
  })});
  const pending = h.prepareSpeechAudio('/audio.wav', new AbortController().signal);
  const rejected = assert.rejects(pending, /15 секунд/);
  h.state.timer();
  await rejected;
  assert.equal(fetchSignal.aborted, true);
  assert.equal(h.state.audio.length, 0);
  assert.equal(h.state.timer, null);
});

test('timeout while decoding releases its prepared source', async () => {
  const h = helpers();
  const pending = h.prepareSpeechAudio('/audio.wav', new AbortController().signal);
  const rejected = assert.rejects(pending, /15 секунд/);
  await tick();
  h.state.timer();
  await rejected;
  assert.equal(h.state.listeners.size, 0);
  assert.deepEqual(h.state.revoked, ['blob:test']);
});

test('decode errors and synchronous load failures both clean up', async () => {
  const event = helpers();
  const pending = event.prepareSpeechAudio('/audio.wav', new AbortController().signal);
  const rejected = assert.rejects(pending, /прочитать аудио/);
  await tick();
  event.state.audio[0].dispatchEvent(new Event('error'));
  await rejected;
  assert.equal(event.state.listeners.size, 0);
  assert.deepEqual(event.state.revoked, ['blob:test']);
  const sync = helpers({loadThrows:true});
  await assert.rejects(sync.prepareSpeechAudio('/audio.wav', new AbortController().signal), /load failed/);
  assert.equal(sync.state.listeners.size, 0);
  assert.deepEqual(sync.state.revoked, ['blob:test']);
});

test('HTTP failures do not allocate audio or blob URLs', async () => {
  const h = helpers({fetch:async () => ({ok:false,status:503})});
  await assert.rejects(h.prepareSpeechAudio('/audio.wav', new AbortController().signal), /HTTP 503/);
  assert.equal(h.state.audio.length, 0);
  assert.equal(h.state.created.length, 0);
  assert.equal(h.state.timer, null);
});

test('abort in the canplay continuation cannot return a stale prepared item', async () => {
  const h = helpers();
  const controller = new AbortController();
  const pending = h.prepareSpeechAudio('/audio.wav', controller.signal);
  const rejected = assert.rejects(pending, {name:'AbortError'});
  await tick();
  h.state.audio[0].dispatchEvent(new Event('canplay'));
  controller.abort();
  await rejected;
  assert.deepEqual(h.state.revoked, ['blob:test']);
});
