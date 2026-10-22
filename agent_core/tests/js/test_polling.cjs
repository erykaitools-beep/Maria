'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../../..');
const js = path.join(root, 'maria_ui/static/js');

async function flush() { for (let i = 0; i < 30; i++) await Promise.resolve(); }

function environment(hidden = false) {
  let now = 0, serial = 0;
  const timers = new Map(), elements = new Map(), requests = [], images = [], errors = [];
  const events = () => {
    const listeners = new Map();
    return {
      addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
      removeEventListener(name, fn) { if (listeners.has(name)) listeners.get(name).delete(fn); },
      dispatch(name, event = {}) { for (const fn of [...(listeners.get(name) || [])]) fn(event); },
    };
  };
  const doc = events(), win = events();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set(id === 'tab-camera' ? ['mo-tab-content--active'] : []);
      elements.set(id, Object.assign(events(), {
        id, style: {}, textContent: '', innerHTML: '', value: '', disabled: false,
        classList: { contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name) },
        replaceWith(next) { elements.set(id, next); },
        focus() {}, appendChild() {}, querySelector() { return null; },
      }));
    }
    return elements.get(id);
  }
  Object.assign(doc, { hidden, getElementById: element, querySelectorAll: () => [], createElement: () => element('new-element') });
  Object.assign(win, { location: { href: '' }, innerWidth: 1000 });
  let payload = () => null;
  class FakeImage {
    constructor() { this.style = {}; }
    set src(url) { this._src = url; images.push(url); queueMicrotask(() => { if (this.onload) this.onload(); }); }
    get src() { return this._src; }
  }
  class ClockDate extends Date { static now() { return now; } }
  const context = vm.createContext({
    document: doc, window: win, Image: FakeImage, Date: ClockDate, Promise,
    console: { error: (...args) => errors.push(args), log() {} },
    setTimeout(fn, delay) { const id = ++serial; timers.set(id, { fn, at: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() { throw new Error('unmanaged polling timer'); },
    clearInterval() {},
    fetch(url, opts) { requests.push({ url, opts }); return Promise.resolve({ ok: true, status: 200, json: async () => payload(url, opts) }); },
  });
  const read = name => vm.runInContext(fs.readFileSync(path.join(js, name + '.js'), 'utf8'), context, { filename: name + '.js' });
  read('maria_ui');
  return {
    doc, win, timers, requests, images, errors, context, element, read,
    M: win.MariaUI,
    payload(fn) { payload = fn; },
    async advance(ms) {
      const end = now + ms;
      while (true) {
        const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        now = due[1].at;
        timers.delete(due[0]);
        due[1].fn();
        await flush();
      }
      now = end;
      await flush();
    },
  };
}

async function main() {
  // Hidden load, immediate resume, pause, bounded in-flight work and stop.
  {
    const e = environment(true);
    let calls = 0;
    const poller = e.M.createPoller(async () => { calls++; }, 1000);
    await flush();
    assert.equal(calls, 0);
    assert.equal(e.timers.size, 0);
    e.doc.hidden = false; e.doc.dispatch('visibilitychange'); await flush();
    assert.equal(calls, 1);
    e.doc.hidden = true; e.doc.dispatch('visibilitychange'); await e.advance(10000);
    assert.equal(calls, 1);
    e.doc.hidden = false; e.doc.dispatch('visibilitychange'); await flush();
    assert.equal(calls, 2);
    await e.advance(1000); assert.equal(calls, 3);
    poller.stop(); await e.advance(10000); assert.equal(calls, 3);
  }
  {
    const e = environment();
    let calls = 0, release;
    const pending = new Promise(resolve => { release = resolve; });
    const poller = e.M.createPoller(() => { calls++; return pending; }, 1000);
    await e.advance(10000);
    e.doc.hidden = true; e.doc.dispatch('visibilitychange');
    e.doc.hidden = false; e.doc.dispatch('visibilitychange');
    await poller.refresh();
    assert.equal(calls, 1, 'slow response allowed overlapping refreshes');
    poller.stop(); release(); await flush();
    assert.equal(e.timers.size, 0, 'completion revived a stopped poller');
  }
  {
    const e = environment();
    let calls = 0;
    e.M.createPoller(() => { calls++; if (calls === 1) throw new Error('offline'); }, 1000);
    await flush(); await e.advance(1000);
    assert.equal(calls, 2, 'failed refresh stopped future attempts');
    e.win.dispatch('pagehide', { persisted: true }); await e.advance(10000);
    assert.equal(calls, 2);
    e.win.dispatch('pageshow', { persisted: true }); await flush();
    assert.equal(calls, 3, 'browser back-cache failed to resume polling');
    e.win.dispatch('pagehide', { persisted: false }); await e.advance(10000);
    assert.equal(calls, 3);
  }
  // Real page scripts use the common poller, not independent hidden timers.
  for (const page of ['learning', 'traces', 'beliefs', 'validation', 'analysis', 'experiments', 'critique', 'tasks', 'status']) {
    const e = environment(true);
    e.read(page); await flush();
    assert.equal(e.requests.length, 0, page + ' fetched while initially hidden');
    e.doc.hidden = false; e.doc.dispatch('visibilitychange'); await flush();
    assert.ok(e.requests.length > 0, page + ' did not refresh on return');
    const count = e.requests.length;
    e.doc.hidden = true; e.doc.dispatch('visibilitychange'); await e.advance(120000);
    assert.equal(e.requests.length, count, page + ' polled while hidden');
  }
  // Vision: no initial hidden image, one shared state request, stable version,
  // and an accepted manual request displays its own photo rather than LIVE.
  {
    const e = environment(true);
    const percept = { timestamp: 100, summary: 'live room', quality: 1, health: 1, modules_run: [], sensor_id: 'cam', processing_time_ms: 1 };
    let done = false;
    e.payload((url, opts) => {
      if (url === '/api/vision/state') return { available: true, state: { last_percept: percept, status: {}, frame_available: true, frame_version: '100' } };
      if (url === '/api/vision/snap' && opts.method === 'POST') return { accepted: true, job_id: 'manual' };
      if (url === '/api/vision/snap/manual') return done
        ? { success: true, status: 'done', summary: 'manual scene', percept: { timestamp: 90 }, frame_url: '/api/vision/snap/manual/frame' }
        : { status: 'running' };
      throw new Error('unexpected vision request ' + url);
    });
    e.read('vision'); e.doc.dispatch('DOMContentLoaded'); await flush();
    assert.equal(e.requests.length, 0); assert.equal(e.images.length, 0);
    e.doc.hidden = false; e.doc.dispatch('visibilitychange'); await flush();
    assert.equal(e.images.length, 1);
    await e.advance(3000);
    assert.equal(e.images.length, 1, 'unchanged frame version reloaded the JPEG');
    await vm.runInContext('takeSnap()', e.context); await flush();
    await vm.runInContext('takeSnap()', e.context); await flush();
    assert.equal(e.requests.filter(r => r.opts && r.opts.method === 'POST').length, 1);
    assert.equal(e.element('vision-snap-button').disabled, true);
    done = true; await e.advance(1000);
    assert.equal(e.element('snapshot-description').textContent, 'manual scene');
    assert.equal(e.element('snapshot-img').src, '/api/vision/snap/manual/frame');
    assert.equal(e.element('vision-snap-button').disabled, false);
    assert.equal(e.element('camera-img').src, '/api/vision/frame?v=100');
    const count = e.requests.length;
    e.doc.hidden = true; e.doc.dispatch('visibilitychange'); await e.advance(10000);
    assert.equal(e.requests.length, count);
  }
  {
    const e = environment();
    e.read('vision');
    e.context.fetch = async (url, opts) => {
      assert.equal(opts.errorBody, undefined, 'internal option leaked into fetch');
      return { ok: false, status: 409, json: async () => ({ error: 'Odczekaj chwile.' }) };
    };
    await vm.runInContext('takeSnap()', e.context); await flush();
    assert.equal(e.element('snapshot-status').textContent, 'Odczekaj chwile.');
    assert.equal(e.element('vision-snap-button').disabled, false);
    assert.equal(e.timers.size, 0);
  }
  process.stdout.write('Polling, page visibility and manual snapshot contracts passed.\n');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
