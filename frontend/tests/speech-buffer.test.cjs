const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function helpers() {
  const source = fs.readFileSync(path.join(__dirname, '../src/speech-buffer.ts'), 'utf8');
  const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const exports = {};
  vm.runInNewContext(code, {exports});
  return exports;
}

const tick = () => new Promise(resolve => setImmediate(resolve));

function controlled(maxItems = 6) {
  const {SpeechBuffer} = helpers();
  const requests = [];
  const released = [];
  let active = 0;
  let peak = 0;
  const buffer = new SpeechBuffer(index => new Promise((resolve, reject) => {
    active++;
    peak = Math.max(peak, active);
    requests.push({index,
      resolve(value = {index}) { active--; resolve(value); },
      reject(error) { active--; reject(error); },
    });
  }), value => released.push(value), {maxItems});
  return {buffer, requests, released, get peak() { return peak; }};
}

test('current resolves immediately and three future paragraphs prepare during playback', async () => {
  const c = controlled();
  const current = c.buffer.ensure(0);
  c.buffer.prefetch(1, 4);
  assert.deepEqual(c.requests.map(request => request.index), [0]);
  assert.equal(c.buffer.pendingCount, 4);
  c.requests[0].resolve();
  assert.equal((await current).index, 0);
  assert.deepEqual(c.requests.map(request => request.index), [0, 1]);
  for (let index = 1; index <= 3; index++) {
    c.requests[index].resolve();
    await tick();
  }
  assert.equal(c.buffer.pendingCount, 0);
  assert.equal(c.peak, 1);
  assert.equal((await c.buffer.ensure(3)).index, 3);
  assert.equal(c.requests.length, 4);
  c.buffer.dispose();
  assert.equal(c.released.length, 4);
});

test('ensure shares pending and cached promises, including a promoted prefetch', async () => {
  const c = controlled();
  c.buffer.prefetch(2, 4);
  const first = c.buffer.ensure(2);
  assert.equal(c.buffer.ensure(2), first);
  c.requests[0].resolve();
  const value = await first;
  assert.equal(c.buffer.ensure(2), first);
  assert.equal(await c.buffer.ensure(2), value);
  assert.deepEqual(c.requests.map(request => request.index), [2, 3]);
  c.buffer.dispose();
  c.requests[1].resolve();
  await tick();
  assert.equal(c.released.length, 2);
});

test('foreground jumps ahead of queued prefetch without overlapping active synthesis', async () => {
  const c = controlled();
  c.buffer.prefetch(0, 5);
  const foreground = c.buffer.ensure(4);
  c.requests[0].resolve();
  await tick();
  assert.deepEqual(c.requests.map(request => request.index), [0, 4]);
  c.requests[1].resolve();
  assert.equal((await foreground).index, 4);
  assert.deepEqual(c.requests.map(request => request.index), [0, 4, 1]);
  c.buffer.dispose();
  c.requests[2].resolve();
  await tick();
  assert.equal(c.peak, 1);
});

test('buffer is bounded, releases old audio, and refills its moving horizon', async () => {
  const c = controlled();
  const current = c.buffer.ensure(0);
  c.buffer.prefetch(1, 10000);
  assert.equal(c.buffer.size, 6);
  for (let index = 0; index < 6; index++) {
    c.requests[index].resolve();
    await tick();
  }
  await current;
  assert.equal(c.requests.length, 6);
  c.buffer.retainFrom(3);
  assert.deepEqual(c.released.map(value => value.index), [0, 1, 2]);
  c.buffer.ensure(3);
  c.buffer.prefetch(4, 7);
  assert.equal(c.buffer.size, 4);
  assert.equal(c.requests[6].index, 6);
  c.requests[6].resolve();
  await tick();
  c.buffer.dispose();
  assert.equal(c.buffer.size, 0);
  assert.deepEqual(c.released.map(value => value.index), [0, 1, 2, 3, 4, 5, 6]);
});

test('full buffer replaces farthest background item for a foreground jump', async () => {
  const c = controlled(3);
  c.buffer.prefetch(0, 3);
  const jump = c.buffer.ensure(8);
  assert.equal(c.buffer.size, 3);
  c.requests[0].resolve();
  await tick();
  assert.equal(c.requests[1].index, 8);
  c.requests[1].resolve();
  await jump;
  assert.equal(c.requests[2].index, 1);
  c.requests[2].resolve();
  await tick();
  assert.equal(c.requests.length, 3);
  c.buffer.dispose();
});

test('clear rejects old waiters and releases late answers without mixing generations', async () => {
  const c = controlled();
  const old = c.buffer.ensure(0);
  c.buffer.prefetch(1, 4);
  c.buffer.clear();
  await assert.rejects(old, {name:'AbortError'});
  const fresh = c.buffer.ensure(0);
  assert.notEqual(old, fresh);
  assert.equal(c.requests.length, 1);
  c.requests[0].resolve({index:0, generation:'old'});
  await tick();
  assert.deepEqual(c.released, [{index:0, generation:'old'}]);
  assert.equal(c.requests.length, 2);
  c.requests[1].resolve({index:0, generation:'new'});
  assert.equal((await fresh).generation, 'new');
  assert.equal(c.buffer.size, 1);
  c.buffer.dispose();
  assert.equal(c.peak, 1);
  assert.equal(c.released.length, 2);
});

test('retaining past an in-flight paragraph releases its late answer exactly once', async () => {
  const c = controlled();
  c.buffer.prefetch(0, 3);
  c.buffer.retainFrom(2);
  const current = c.buffer.ensure(2);
  c.requests[0].resolve();
  await tick();
  assert.deepEqual(c.released.map(value => value.index), [0]);
  assert.deepEqual(c.requests.map(request => request.index), [0, 2]);
  c.requests[1].resolve();
  await current;
  c.buffer.dispose();
  c.buffer.dispose();
  assert.deepEqual(c.released.map(value => value.index), [0, 2]);
});

test('background errors stay handled and surface only when their paragraph is requested', async () => {
  const c = controlled();
  c.buffer.prefetch(0, 3);
  const failed = new Error('voice worker failed');
  c.requests[0].reject(failed);
  await tick();
  assert.equal(c.requests[1].index, 1);
  await assert.rejects(c.buffer.ensure(0), error => error === failed);
  const next = c.buffer.ensure(1);
  c.requests[1].resolve();
  assert.equal((await next).index, 1);
  c.buffer.dispose();
  c.requests[2].reject(new Error('obsolete failure'));
  await tick();
  await assert.rejects(c.buffer.ensure(4), {name:'AbortError'});
  assert.equal(c.requests.length, 3);
});

test('synchronous loader failures do not stall remaining prefetch', async () => {
  const {SpeechBuffer} = helpers();
  const requested = [];
  const buffer = new SpeechBuffer(index => {
    requested.push(index);
    if (index === 0) throw new Error('sync failure');
    return Promise.resolve({index});
  }, () => {});
  buffer.prefetch(0, 2);
  await tick();
  assert.deepEqual(requested, [0, 1]);
  await assert.rejects(buffer.ensure(0), /sync failure/);
  assert.equal((await buffer.ensure(1)).index, 1);
  buffer.dispose();
});

test('visible window retains previous spread and reuses cached audio on a backward seek', async () => {
  const c = controlled(12);
  const first = c.buffer.ensure(2);
  c.buffer.setWindow(2, [3, 4, 5, 0, 1]);
  for (let count = 0; count < 6; count++) { c.requests[count].resolve(); await tick(); }
  await first;
  assert.deepEqual(c.requests.map(request => request.index), [2, 3, 4, 5, 0, 1]);
  c.buffer.setWindow(4, [5, 6, 7], [0, 1, 2, 3]);
  const cached = await c.buffer.ensure(1);
  assert.equal(cached.index, 1);
  assert.equal(c.requests.filter(request => request.index === 1).length, 1);
  assert.equal(c.released.length, 0);
  c.buffer.dispose();c.requests[6].resolve();await tick();
  assert.equal(c.peak, 1);
});

test('window change drops obsolete audio, but late loads cannot leak back into cache', async () => {
  const c = controlled(8);
  c.buffer.setWindow(0, [1, 2]);
  c.requests[0].resolve();await tick();
  c.buffer.setWindow(8, [9, 10]);
  c.requests[1].resolve();await tick();
  assert.deepEqual(c.released.map(value => value.index), [0, 1]);
  assert.deepEqual(c.requests.map(request => request.index), [0, 1, 8]);
  c.buffer.dispose();c.requests[2].resolve();await tick();
});

test('weighted cache keeps current audio, evicts lower priority audio and pauses background filling', async () => {
  const {SpeechBuffer} = helpers();const requested=[],released=[];
  const buffer = new SpeechBuffer(async index => { requested.push(index);return {index, bytes:6}; }, value => released.push(value.index), {maxItems:12,maxWeight:15,weight:value=>value.bytes});
  buffer.setWindow(0, [1, 2, 3, 4]);await tick();
  assert.deepEqual(requested, [0, 1, 2]);
  assert.equal(buffer.retainedWeight, 12);assert.deepEqual(released, [2]);
  buffer.setWindow(0, [1, 2, 3, 4]);await tick();
  assert.deepEqual(requested, [0, 1, 2], 'same window does not retry over-budget prefetch');
  const selected=buffer.ensure(2);buffer.setWindow(2, [3, 4], [0, 1]);await selected;await tick();
  assert.equal(requested.filter(index=>index===2).length, 2);
  assert.ok(buffer.retainedWeight <= 15);assert.equal((await buffer.ensure(2)).index, 2);
  buffer.dispose();assert.equal(buffer.retainedWeight, 0);
});

test('prepared chapter lead transfers without reloading or double releasing', async () => {
  const {SpeechBuffer} = helpers();const released=[];let loads=0;
  const first=new SpeechBuffer(async index=>({index,bytes:10}),value=>released.push(value));
  const lead=await first.ensure(2);assert.equal(first.take(9),undefined);
  const transfer=first.take(2);assert.equal(transfer,lead);first.dispose();assert.equal(released.length,0);
  const next=new SpeechBuffer(async index=>{loads++;return {index};},value=>released.push(value));
  next.seed(0,transfer);assert.equal(await next.ensure(0),lead);assert.equal(loads,0);next.dispose();assert.deepEqual(released,[lead]);
  const late={index:3};next.seed(0,late);assert.deepEqual(released,[lead,late]);
});
