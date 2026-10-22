import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const voiceSource = fs.readFileSync(new URL('../../maria_ui/static/js/chat_voice.js', import.meta.url), 'utf8');
const chatSource = fs.readFileSync(new URL('../../maria_ui/static/js/chat.js', import.meta.url), 'utf8');
const localSource = fs.readFileSync(new URL('../../maria_ui/static/js/chat_local_stt.js', import.meta.url), 'utf8');
function fixture({secure = true, direct = false, handler = true, accept = true, media = null, local = false, requireLocal = false, segmenter = true, storage = new Map(), apiFetch = null, correlate = true, gestureSpeech = false, onSend = null} = {}) {
  const elements = new Map();
  let gesture = false, speechUnlocked = false;
  if (media) media.gesture = () => gesture;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', innerHTML: '', disabled: false, style: {}, children: [], attrs: {}, listeners: {},
      addEventListener(n, cb) { this.listeners[n] = cb; },
      setAttribute(n, v) { this.attrs[n] = v; },
      appendChild(v) { this.children.push(v); }, focus() {}, remove() {},
      click() { if (!this.disabled) { gesture = true; try { this.listeners.click?.(); } finally { gesture = false; } } }
    });
    return elements.get(id);
  }
  const events = {}, docEvents = {}, winEvents = {}, spoken = [], emitted = [], timers = new Map();
  let cancelCalls = 0;
  let serial = 0, now = 0;
  const due = new Map();
  class Recognition {
    constructor() { Recognition.latest = this; Recognition.instances.push(this); }
    start() { this.started = true; this.onstart?.(); }
    abort() { this.aborted = true; this.onend?.(); }
    stop() { this.stopCalls = (this.stopCalls || 0) + 1; }
  }
  Recognition.instances = [];
  const socket = { connected: true, on(n, f) { events[n] = n === 'chat_response' && correlate ? data => f({...data,request_id:data.request_id || emitted.filter(([name])=>name==='chat_message').at(-1)?.[1].request_id}) : f; }, emit(n, p) { emitted.push([n, p]); } };
  const documentListeners = {};
  const document = { hidden: false, getElementById: element, createElement: () => element('generated' + serial++),
    addEventListener(n, f) { (documentListeners[n] ||= []).push(f); docEvents[n] = () => documentListeners[n].slice().forEach(cb=>cb()); }, removeEventListener(n,f) { documentListeners[n] = (documentListeners[n] || []).filter(cb=>cb!==f); } };
  const window = { isSecureContext: secure, SpeechRecognition: Recognition,
    crypto:{randomUUID(){ return '00000000-0000-4000-8000-' + String(++serial).padStart(12,'0'); }},
    sessionStorage:{getItem:key=>storage.get(key) || null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    navigator: {mediaDevices:media && media.devices}, AudioContext: media && media.AudioContext,
    fetch: media && media.fetch, AbortController,
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
    speechSynthesis: { speak(u) { if (gestureSpeech && !gesture && !speechUnlocked) throw new Error('gesture-required'); if (gesture) speechUnlocked=true; spoken.push(u); }, cancel() { cancelCalls++; }, getVoices() { return [{lang:'pl-PL'}]; } },
    setTimeout(f, ms = 0) { const id = ++serial; timers.set(id, f); due.set(id, now + ms); return id; }, clearTimeout(id) { timers.delete(id); due.delete(id); },
    addEventListener(n, f) { winEvents[n] = f; }, matchMedia() { return { matches: true }; } };
  const MariaUI = { $: element, getSocket: () => socket, apiFetch: apiFetch || (async () => ({ messages: [{role:'maria', content:'history'}] })),
    createPoller() {}, updateTopbarStatus() {} };
  class ClockDate extends Date { static now() { return now; } }
  const context = vm.createContext({ Date: ClockDate, window, document, MariaUI, ...(segmenter ? {} : {Intl:{}}), console: { log() {} },
    setInterval() { return 1; }, clearInterval() {} });
  if (local || requireLocal) element('chatInput').dataset = {voiceBackend:'local'};
  if (local) vm.runInContext(localSource, context);
  vm.runInContext(voiceSource, context);
  let voice;
  if (direct) {
    voice = window.MariaChatVoice(element('chatInput'), handler ? {sendText(text) {
      if (accept === 'throw') throw new Error('send failed');
      if (!accept) return false;
      emitted.push(['chat_message', {message:text}]); if(onSend)onSend(voice); voice.setBusy(true); return true;
    }} : {});
  } else vm.runInContext(chatSource, context);
  function advance(ms) {
    const until = now + ms;
    let steps = 0;
    while (true) {
      const next = [...due].filter(([id,t]) => timers.has(id) && t <= until).sort((a,b) => a[1]-b[1])[0];
      if (!next) break;
      assert.ok(++steps < 100, 'timer loop must be bounded');
      const [id,t] = next; now = t;
      const fn = timers.get(id); timers.delete(id); due.delete(id); fn();
    }
    now = until;
  }
  return { voice, advance, window, get cancelCalls() { return cancelCalls; }, element, events, docEvents, winEvents, spoken, emitted, timers, document, socket, Recognition };
}
const f = fixture();
f.events.connected({ chat_backend: {provider:'codex', model:'gpt-6.1-sol', configured:true}, ollama_available:false });
assert.equal(f.element('chatModelBadge').textContent, 'Codex · gpt-6.1-sol');
f.events.connect();
await Promise.resolve(); await Promise.resolve();
assert.equal(f.spoken.length, 0, 'history must never be spoken');
f.element('voiceToggle').click();
assert.equal(f.spoken.length, 1);
assert.match(f.element('voiceStatus').textContent, /Czekam/, 'calling speak does not prove playback');
assert.equal(f.element('voiceToggle').attrs['aria-pressed'], 'false');
f.spoken[0].onstart(); f.spoken[0].onend();
assert.equal(f.element('voiceToggle').attrs['aria-pressed'], 'true');
f.events.chat_response({success:true, message:'fresh'});
assert.equal(f.spoken.at(-1).text, 'fresh');
const count = f.spoken.length;
f.events.chat_response({success:false, error:'error'});
assert.equal(f.spoken.length, count, 'errors must not be narrated');
f.element('voiceMic').click();
const rec = f.Recognition.latest;
rec.onstart();
rec.onresult({resultIndex:0, results:[Object.assign([{transcript:'Cześć Mario'}], {isFinal:true})]});
assert.equal(f.element('chatInput').value, 'Cześć Mario');
assert.equal(f.emitted.length, 0, 'recognition never sends automatically');
rec.onend();
f.element('sendBtn').click(); f.element('sendBtn').click();
assert.equal(f.emitted.length, 1, 'double click must not send twice');
f.events.chat_response({rate_limited:true, wait_seconds:3});
f.element('chatInput').value = 'blocked';
f.element('chatInput').listeners.keypress({key:'Enter', preventDefault(){}});
assert.equal(f.emitted.length, 1, 'keyboard cannot bypass rate limit');
const g = fixture();
g.socket.connected = false; g.events.disconnect();
g.element('chatInput').value = 'offline';
g.element('chatInput').listeners.keypress({key:'Enter', preventDefault(){}});
assert.equal(g.emitted.length, 0, 'offline input must not enter SocketIO buffer');
const h = fixture();
h.element('voiceToggle').click(); h.spoken[0].onstart(); h.spoken[0].onend();
h.element('voiceMic').click(); const old = h.Recognition.latest;
h.document.hidden = true; h.docEvents.visibilitychange();
assert.equal(old.aborted, true);
h.document.hidden = false;
h.events.chat_response({success:true, message:'after hiding'});
assert.equal(h.spoken.length, 1, 'returning to page must not resume speech');
old.onresult({resultIndex:0, results:[Object.assign([{transcript:'stale'}],{isFinal:true})]});
assert.equal(h.element('chatInput').value, '', 'late recognition after cleanup must be ignored');
h.element('voicePlay').click();
assert.equal(h.spoken.at(-1).text, 'after hiding', 'manual playback remains available');
const pending = h.spoken.at(-1);
for (const callback of [...h.timers.values()]) callback();
assert.match(h.element('voiceStatus').textContent, /nie rozpoczęło/);
pending.onstart();
assert.equal(h.element('voiceToggle').attrs['aria-pressed'], 'false', 'late start must not re-enable voice');
console.log('chat voice behavior: PASS');

function final(rec, text, index = 0, isFinal = true) {
  const results = [];
  results[index] = Object.assign([{transcript:text}], {isFinal});
  rec.onresult({resultIndex:index, results});
}
function beginHandsfree(f) {
  f.element('voiceHandsfree').click();
  finishConversationCue(f);f.advance(1200);
  assert.equal(f.Recognition.latest.started, true, 'microphone starts after the acknowledged cue and cooldown');
  return f.Recognition.latest;
}
function finishConversationCue(f) {
  const cue=f.spoken.at(-1);assert.equal(cue.text,'Rozmowa włączona.');
  cue.onstart();cue.onend();
}
async function beginLocalConversation(f) {
  f.element('voiceHandsfree').click();finishConversationCue(f);await settle();f.advance(1200);
}
for (const cfg of [{secure:false}, {handler:false}]) {
  const f = fixture({direct:true, ...cfg});
  assert.equal(f.element('voiceHandsfree').disabled, true);
  f.element('voiceHandsfree').click(); f.advance(60000);
  assert.equal(f.Recognition.instances.length, 0, 'no insecure or old-client microphone');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria'); rec.onend(); f.advance(2000);
  assert.equal(f.emitted.length, 0, 'wake word alone is never sent');
  const next = f.Recognition.latest;
  final(next, 'Jaka jest pogoda wyślij'); final(next, 'Jaka jest pogoda wyślij');
  f.advance(899); assert.equal(f.emitted.length, 0);
  f.advance(1); assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'Jaka jest pogoda');
  next.onend(); final(next, 'stale'); f.advance(10000);
  assert.equal(f.emitted.length, 1, 'late callbacks cannot duplicate sends');
  const instances = f.Recognition.instances.length;
  f.voice.response('Dobrze', {success:true});
  f.voice.setBusy(false); f.advance(3000);
  assert.equal(f.Recognition.instances.length, instances, 'no listening before TTS starts');
  const reply = f.spoken.at(-1); reply.onstart(); f.advance(3000);
  assert.equal(f.Recognition.instances.length, instances, 'no self-hearing during speech');
  reply.onend(); f.advance(1199);
  assert.equal(f.Recognition.instances.length, instances);
  f.advance(1); final(f.Recognition.latest, 'otwórz stronę'); f.advance(1000);
  assert.equal(f.emitted.length, 1, 'a new command needs a new wake word');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Mario, powiedz dzień dobry wyślij', 0, false); f.advance(1000);
  assert.equal(f.emitted.length, 0, 'interim speech is never submitted');
  final(rec, 'Mario, powiedz dzień dobry wyślij'); f.advance(900);
  assert.equal(f.emitted[0][1].message, 'powiedz dzień dobry');
  assert.equal(f.element('chatInput').value, '', 'automatic command does not alter draft');
}
for (const action of ['stop', 'hidden', 'disconnect', 'permission', 'failure']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria zrób coś wyślij');
  if (action === 'stop') f.element('voiceStop').click();
  if (action === 'hidden') { f.document.hidden = true; f.docEvents.visibilitychange(); }
  if (action === 'disconnect') f.voice.disconnect();
  if (action === 'permission') rec.onerror({error:'not-allowed'});
  if (action === 'failure') f.voice.failure('timeout');
  f.advance(60000); assert.equal(f.emitted.length, 0, action + ' invalidates final timer');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria wyślij'); f.element('chatInput').value = 'mój szkic'; f.advance(900);
  assert.equal(f.emitted.length, 0, 'draft typed during final silence is preserved');
  assert.equal(f.element('chatInput').value, 'mój szkic');
}
for (const accept of [false, 'throw']) {
  const f = fixture({direct:true, accept}); const rec = beginHandsfree(f);
  final(rec, 'Maria test wyślij'); f.advance(900); f.advance(60000);
  assert.equal(f.emitted.length, 0); assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
{
  const f = fixture({direct:true}); beginHandsfree(f);
  for (let i = 0; i < 8; i++) { f.Recognition.latest.onend(); f.advance(3000); }
  assert.equal(f.Recognition.instances.length, 8, 'rapid microphone failures bounded');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
console.log('foreground handsfree lifecycle: PASS');
// Complete path: wake word -> guarded real chat.js sendMessage -> SocketIO.
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria opowiedz mi o pamięci wyślij'); final(rec, 'Maria opowiedz mi o pamięci wyślij');
  f.advance(900);
  assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][0], 'chat_message');
  assert.equal(f.emitted[0][1].message, 'opowiedz mi o pamięci');
  assert.equal(f.element('sendBtn').disabled, true, 'real send synchronously sets thinking');
  const before = f.Recognition.instances.length;
  f.events.chat_response({success:true, message:'Pamiętam naszą rozmowę.'});
  f.advance(3000);
  assert.equal(f.Recognition.instances.length, before, 'real terminal response waits for TTS playback');
  const answer = f.spoken.at(-1); answer.onstart(); answer.onend();
  f.advance(1200);
  assert.equal(f.Recognition.instances.length, before + 1);
  final(f.Recognition.latest, 'Maria następne pytanie wyślij'); f.advance(900);
  assert.equal(f.emitted.length, 2, 'next explicit wake word starts one new turn');
}
for (const response of [
  {success:false, error:'backend failure'},
  {success:true, fallback:true, message:'busy fallback'},
  {rate_limited:true, wait_seconds:3},
]) {
  const f = fixture(); final(beginHandsfree(f), 'Maria test odpowiedzi wyślij'); f.advance(900);
  const before = f.Recognition.instances.length;
  f.events.chat_response(response); f.advance(60000);
  assert.equal(f.emitted.length, 1, 'terminal failure must not resend');
  assert.equal(f.Recognition.instances.length, before, 'terminal failure needs manual re-enable');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria ' + 'x'.repeat(2001) + ' wyślij'); f.advance(900); f.advance(5000);
  assert.equal(f.emitted.length, 0, 'real send guard rejects oversized automatic command');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
  rec.onend(); f.advance(1200);
  assert.notEqual(f.Recognition.latest, rec, 'invalid oversized capture is discarded at session end');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria nie nadpisuj wyślij'); f.element('chatInput').value = 'ręczny szkic';
  f.advance(900); assert.equal(f.emitted.length, 0);
  assert.equal(f.element('chatInput').value, 'ręczny szkic');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria jeszcze nie wysyłaj wyślij'); f.socket.connected = false; f.events.disconnect();
  f.advance(60000); assert.equal(f.emitted.length, 0, 'disconnect invalidates pending automatic command');
}
{
  const f = fixture(); final(beginHandsfree(f), 'Maria długie pytanie wyślij'); f.advance(900);
  const before = f.Recognition.instances.length;
  f.advance(130000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
  assert.equal(f.element('sendBtn').disabled, true, 'unknown outcome keeps the real send path closed');
  assert.equal(f.emitted.length, 1);
  assert.equal(f.Recognition.instances.length, before);
  f.events.chat_response({success:true, message:'spóźniona odpowiedź'}); f.advance(10000);
  assert.equal(f.emitted.length, 1, 'late answer cannot resume automatic resends');
  assert.equal(f.element('sendBtn').disabled, false);
}
console.log('handsfree -> real chat send/result guards: PASS');

{
  const f = fixture(); final(beginHandsfree(f), 'Maria pytanie wyślij'); f.advance(900);
  f.events.chat_response({success:true, message:'odpowiedź'});
  const answer = f.spoken.at(-1); answer.onstart();
  const before = f.Recognition.instances.length;
  f.element('voiceToggle').click(); f.advance(10000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false', 'voice OFF also ends handsfree while speaking');
  assert.equal(f.Recognition.instances.length, before);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria'); rec.onend(); f.advance(1500);
  f.voice.setBusy(true); f.voice.setBusy(false); f.advance(1200);
  final(f.Recognition.latest, 'tekst bez ponownego hasła'); f.advance(900);
  assert.equal(f.emitted.length, 0, 'manual generation invalidates a previous wake word');
}
{
  const f = fixture({direct:true}); beginHandsfree(f);
  f.voice.setBusy(false); f.voice.setBusy(false); f.advance(5000);
  assert.equal(f.Recognition.instances.length, 1, 'repeated ready notifications never start a second active recognizer');
}
console.log('handsfree toggle/armed/recognizer isolation: PASS');
{
  const f = fixture({direct:true});
  f.voice.response('Poprzednia odpowiedź', {success:true});
  final(beginHandsfree(f), 'Maria');
  f.element('voicePlay').click(); const playback = f.spoken.at(-1);
  playback.onstart(); playback.onend(); f.advance(1200);
  final(f.Recognition.latest, 'rozmowa bez ponownego hasła'); f.advance(900);
  assert.equal(f.emitted.length, 0, 'manual TTS must invalidate a previously armed wake word');
}
console.log('manual TTS requires fresh wake word: PASS');
{
  const f = fixture(); final(beginHandsfree(f), 'Maria czekaj na wynik wyślij'); f.advance(900);
  assert.equal(f.element('clearBtn').disabled, true);
  f.element('clearBtn').listeners.click(); // forced handler bypasses disabled DOM control
  assert.equal(f.emitted.length, 1, 'pending reply cannot be confused with a clear response');
  f.advance(130000);
  assert.equal(f.element('clearBtn').disabled, true, 'unknown result keeps history clear locked');
  f.element('clearBtn').click(); f.element('clearBtn').listeners.click();
  assert.equal(f.emitted.length, 1, 'timeout never permits competing clear_history');
  f.events.chat_response({success:true, message:'prawdziwa spóźniona odpowiedź'});
  assert.equal(f.element('clearBtn').disabled, false);
  assert.equal(f.element('sendBtn').disabled, false);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
  f.element('clearBtn').click();
  assert.equal(f.emitted.at(-1)[0], 'clear_history', 'actual terminal response unlocks normal controls');
}
{
  const f = fixture(); f.socket.connected = false; f.events.disconnect();
  assert.equal(f.element('clearBtn').disabled, true);
  f.element('clearBtn').listeners.click();
  assert.equal(f.emitted.length, 0, 'forced offline clear never enters SocketIO buffering');
  const g = fixture(); g.socket.connected = false; // before the disconnect event arrives
  g.element('clearBtn').listeners.click();
  assert.equal(g.emitted.length, 0, 'clear guard also checks live socket state');
}
console.log('pending/unknown/offline clear isolation: PASS');

for (const event of ['end', 'no-speech']) {
  const f = fixture({direct:true}); beginHandsfree(f);
  for (let i = 0; i < 12; i++) {
    f.advance(10000);
    const rec = f.Recognition.latest;
    if (event === 'end') rec.onend(); else rec.onerror({error:'no-speech'});
    f.advance(1000);
    assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
  }
  assert.equal(f.Recognition.instances.length, 13, 'ordinary idle ends keep foreground readiness');
  assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true}); beginHandsfree(f);
  for (let i = 0; i < 7; i++) { f.Recognition.latest.onend(); f.advance(3000); }
  f.advance(10000); f.Recognition.latest.onend(); f.advance(1000);
  f.Recognition.latest.onend(); f.advance(3000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true', 'stable idle session resets rapid failure count');
  assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true}); beginHandsfree(f);
  for (let i = 0; i < 3; i++) { f.Recognition.latest.onerror({error:'network'}); f.advance(5000); }
  assert.equal(f.Recognition.instances.length, 3, 'network failures allow only two retries');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
for (const action of ['stop', 'hidden']) {
  const f = fixture({direct:true}); beginHandsfree(f); f.advance(10000);
  f.Recognition.latest.onend();
  if (action === 'stop') f.element('voiceStop').click();
  else { f.document.hidden = true; f.docEvents.visibilitychange(); }
  f.advance(60000);
  assert.equal(f.Recognition.instances.length, 1, action + ' cancels ordinary idle restart');
}
{
  const f = fixture({direct:true}); beginHandsfree(f);
  f.advance(46 * 1000 * 10);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true', '45s renewal is normal idle, not a fault');
  assert.ok(f.Recognition.instances.length > 8);
  assert.equal(f.emitted.length, 0);
}
console.log('normal idle renewal vs bounded rapid/network failures: PASS');

{
  const f = fixture({direct:true}); f.element('chatInput').value = 'Szkic'; f.element('voiceMic').click();
  const rec = f.Recognition.latest;
  assert.equal(rec.interimResults, true);
  assert.equal(f.cancelCalls, 0, 'idle synth is not unnecessarily cancelled before microphone');
  rec.onaudiostart(); assert.match(f.element('voiceDiagnostic').textContent, /zgłosiło otwarcie mikrofonu/);
  rec.onspeechstart(); assert.match(f.element('voiceDiagnostic').textContent, /zgłasza mowę/);
  final(rec, '<img src=x onerror=alert(1)>', 0, false);
  assert.equal(f.element('voiceTranscript').textContent, 'Wstępnie (niewysłane): <img src=x onerror=alert(1)>');
  assert.equal(f.element('voiceTranscript').innerHTML, '', 'diagnostic never uses HTML');
  assert.equal(f.element('chatInput').value, 'Szkic');
  assert.equal(f.emitted.length, 0);
  f.advance(15000); assert.match(f.element('voiceStatus').textContent, /wstępne.*bez końcowego/);
  rec.onend(); assert.match(f.element('voiceStatus').textContent, /wstępne.*bez końcowego/);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  assert.equal(rec.interimResults, true);
  final(rec, 'Maria', 0, false);
  final(rec, 'nie powinno się wysłać', 0, true); f.advance(900);
  assert.equal(f.emitted.length, 0, 'interim wake word never arms a later final command');
  assert.match(f.element('voiceTranscript').textContent, /^Końcowo:/);
}
for (const mode of ['manual', 'handsfree']) {
  const f = fixture({direct:true});
  if (mode === 'manual') f.element('voiceMic').click(); else beginHandsfree(f);
  const old = f.Recognition.latest;
  old.onaudiostart(); f.advance(15000);
  assert.match(f.element('voiceStatus').textContent, mode === 'manual' ? /nie zwróciło żadnego tekstu/ : /Czekam na „Maria”/);
  assert.equal(f.emitted.length, 0);
  f.element('voiceStop').click(); f.element('voiceMic').click();
  const status = f.element('voiceStatus').textContent;
  const preview = f.element('voiceTranscript').textContent;
  old.onaudiostart(); old.onsoundstart(); old.onspeechstart(); old.onaudioend();
  final(old, 'spóźnione słowa'); old.onend();
  assert.equal(f.element('voiceStatus').textContent, status, 'stale events cannot overwrite new session status');
  assert.equal(f.element('voiceTranscript').textContent, preview);
  f.advance(15000); assert.match(f.element('voiceStatus').textContent, /nie zwróciło żadnego tekstu/);
}
{
  const f = fixture({direct:true}); f.element('voiceMic').click();
  const rec = f.Recognition.latest;
  final(rec, 'tekst końcowy'); final(rec, 'tekst końcowy');
  assert.equal(f.element('chatInput').value, 'tekst końcowy', 'manual finals are deduplicated too');
  f.element('chatInput').value = 'ręczna edycja'; final(rec, 'inne słowa', 1);
  assert.equal(f.element('chatInput').value, 'ręczna edycja', 'manual STT never overwrites typed edits');
  rec.onerror({error:'network'});
  assert.match(f.element('voiceStatus').textContent, /połączenia usługi/);
}
{
  const f = fixture({direct:true}); f.element('voiceMic').click(); f.Recognition.latest.onend();
  assert.match(f.element('voiceStatus').textContent, /nie zwróciło żadnego tekstu/);
  f.element('voiceMic').click(); f.advance(30000);
  assert.match(f.element('voiceStatus').textContent, /nie zwróciło żadnego tekstu/);
}
console.log('safe interim/final preview and no-result STT diagnostics: PASS');

function snapshot(rec, chunks) {
  rec.onresult({resultIndex:0, results:chunks.map(([transcript,isFinal]) =>
    Object.assign([{transcript}], {isFinal}))});
}
{
  const f = fixture({direct:true}); f.element('voiceMic').click(); const rec = f.Recognition.latest;
  rec.stop = () => { rec.stopCalls = (rec.stopCalls || 0) + 1;
    f.window.setTimeout(() => { final(rec, 'Maria czy mnie słyszysz'); rec.onend(); }, 200);
  };
  final(rec, 'Maria czy mnie słyszysz', 0, false);
  f.advance(1000); final(rec, 'Maria czy mnie słyszysz', 0, false);
  f.advance(799); assert.equal(rec.stopCalls || 0, 0);
  f.advance(1); assert.equal(rec.stopCalls, 1, 'unchanged duplicate interim cannot postpone stop');
  assert.equal(rec.aborted, undefined, 'request finalization with stop, not abort');
  assert.equal(f.element('chatInput').value, '');
  f.advance(200); assert.equal(f.element('chatInput').value, 'Maria czy mnie słyszysz');
  assert.equal(f.emitted.length, 0, 'manual finalization still needs Send');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  rec.stop = () => { rec.stopCalls = (rec.stopCalls || 0) + 1;
    final(rec, 'Maria powiedz dzień dobry wyślij'); rec.onend();
  };
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(1800);
  assert.equal(rec.aborted, undefined);
  f.advance(900); assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'powiedz dzień dobry');
  final(rec, 'Maria powiedz dzień dobry wyślij'); rec.onend(); f.advance(10000);
  assert.equal(f.emitted.length, 1, 'sync and duplicate callbacks cannot resend');
}
for (const behavior of ['no-end', 'throws', 'end-without-final']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  rec.stop = () => { rec.stopCalls = (rec.stopCalls || 0) + 1;
    if (behavior === 'throws') throw new Error('stop unavailable');
    if (behavior === 'end-without-final') rec.onend();
  };
  final(rec, 'Maria niedokończone nie wyślij', 0, false);
  if (behavior === 'throws') { final(rec, 'Maria niedokończone wyślij',0,false); f.advance(1800); }
  else { rec.onend(); f.advance(2000); }
  assert.equal(rec.stopCalls || 0, behavior === 'throws' ? 1 : 0);
  assert.equal(f.emitted.length, 0);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], behavior === 'throws' ? 'false' : 'true');
  assert.match(f.element('voiceTranscript').textContent, /Wstępnie.*Maria niedokończone/);
  assert.match(f.element('voiceStatus').textContent, behavior === 'throws' ? /wstępne.*bez końcowego/ : /Nie zatwierdzono.*nic nie wysłano/);
}
for (const action of ['stop', 'hidden', 'disconnect', 'busy', 'new-manual', 'tts']) {
  const f = fixture({direct:true});
  f.voice.response('Poprzednia odpowiedź', {success:true});
  const rec = beginHandsfree(f); final(rec, 'Maria niedokończone', 0, false);
  if (action === 'stop') f.element('voiceStop').click();
  if (action === 'hidden') { f.document.hidden = true; f.docEvents.visibilitychange(); }
  if (action === 'disconnect') f.voice.disconnect();
  if (action === 'busy') f.voice.setBusy(true);
  if (action === 'new-manual') f.element('voiceMic').click();
  if (action === 'tts') f.element('voicePlay').click();
  const text = f.element('voiceStatus').textContent;
  f.advance(1800); assert.equal(rec.stopCalls || 0, 0, action + ' invalidates stop timer');
  final(rec, 'Maria spóźnione polecenie');
  assert.equal(f.element('voiceStatus').textContent, text);
  assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria', 0, false); snapshot(rec, []); f.advance(2000);
  assert.equal(rec.stopCalls || 0, 0, 'retracted interim no longer requests finalization');
  final(rec, 'polecenie bez hasła'); f.advance(900);
  assert.equal(f.emitted.length, 0, 'withdrawn interim wake never arms command');
  assert.match(f.element('voiceStatus').textContent, /Zacznij polecenie od/);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria pokaż'); f.advance(500);
  snapshot(rec, [['Maria pokaż',true], ['projekt',false]]);
  f.advance(1000); assert.equal(f.emitted.length, 0, 'unresolved tail cancels prefix commit');
  snapshot(rec, [['Maria pokaż',true], ['projekt X wyślij',true]]); f.advance(900);
  assert.equal(f.emitted.length, 1); assert.equal(f.emitted[0][1].message, 'pokaż projekt X');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  snapshot(rec, [['Maria pokaż',true], ['projekt',false]]); f.advance(1800);
  rec.onend(); f.advance(5000);
  assert.equal(f.emitted.length, 0, 'unfinalized tail cannot silently become a truncated command');
}
for (const late of ['Maria', 'zwykłe słowa', 'retracted']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria', 0, false); rec.onend();
  if (late === 'retracted') snapshot(rec, []); else final(rec, late);
  f.advance(1500);
  assert.equal(f.Recognition.instances.length, 2, 'ended session recovers after late final or retraction');
  if (late === 'Maria') { final(f.Recognition.latest, 'następne polecenie wyślij'); f.advance(900); assert.equal(f.emitted.length, 1); }
  else assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria', 0, false); rec.onend(); f.advance(1800); final(rec, 'Maria');
  f.advance(1300);
  assert.equal(f.Recognition.instances.length, 2, 'stop without native end closes after final-result grace');
  final(f.Recognition.latest, 'teraz polecenie wyślij'); f.advance(900);
  assert.equal(f.emitted.length, 1);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  snapshot(rec, [['Maria zrób',true], ['fragment0',false]]);
  for (let i = 1; i <= 14; i++) { f.advance(1000); snapshot(rec, [['Maria zrób',true], ['fragment'+i,false]]); }
  snapshot(rec, [['Maria zrób',true], ['pełne polecenie wyślij',true]]); f.advance(900);
  assert.equal(f.emitted[0][1].message, 'zrób pełne polecenie', 'started command retains its wake while tail finalizes');
}
console.log('bounded interim stop/final grace and complete-command guards: PASS');

{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria, powiedz mi dzień dobry, wyślij', 0, false);
  f.advance(1800); assert.equal(rec.stopCalls, 1); assert.equal(f.emitted.length, 0);
  f.advance(1999); assert.equal(f.emitted.length, 0);
  f.advance(1); assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'powiedz mi dzień dobry');
  assert.match(f.element('voiceTranscript').textContent, /Wysłano po słowie.*Safari nie zatwierdziło/);
  assert.equal(f.element('chatInput').value, '');
  final(rec, 'Maria, powiedz mi dzień dobry, wyślij'); rec.onend(); f.advance(2000);
  assert.equal(f.emitted.length, 1, 'late true final never duplicates compatibility send');
}
for (const phrase of ['Maria powiedz dzień dobry', 'powiedz dzień dobry wyślij',
  'Maria wyślij', 'Maria nie wyślij', 'Maria powiedz nie wyslij',
  'Hej Maria powiedz dzień dobry wyślij', 'Maria pokaż niewyślij']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, phrase, 0, false); f.advance(6800);
  assert.equal(f.emitted.length, 0, 'reject unconfirmed/negated phrase: ' + phrase);
}
for (const revised of ['powiedz mi dzień dobry wyślij', 'Maria powiedz mi dzień dobry', 'Maria powiedz mi dzień dobry nie wyślij']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria powiedz mi dzień dobry wyślij', 0, false); f.advance(2000);
  final(rec, revised, 0, false); f.advance(4800);
  assert.equal(f.emitted.length, 0, 'latest revised snapshot controls confirmation');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria pierwsza wersja wyślij', 0, false); f.advance(3000);
  final(rec, 'Maria nagła zmiana wyślij', 0, false); f.advance(800);
  assert.equal(f.emitted.length, 0, 'late unstable replacement is never accepted');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  snapshot(rec, [['Maria powiedz',true], ['mi dzień dobry wyślij',false]]); f.advance(6800);
  assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'powiedz mi dzień dobry', 'full snapshot combines final prefix and interim tail once');
}
{
  const f = fixture({direct:true}); f.element('voiceMic').click(); const rec = f.Recognition.latest;
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(6800);
  assert.equal(f.emitted.length, 0, 'manual dictation never uses spoken-confirmation autosend');
  assert.equal(f.element('chatInput').value, '');
}
for (const error of ['no-speech', 'network', 'not-allowed', 'aborted']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false);
  rec.onerror({error}); f.advance(15000);
  assert.equal(f.emitted.length, 0, 'no compatibility fallback after recognition error: ' + error);
}
for (const action of ['stop', 'hidden', 'disconnect', 'busy', 'draft']) {
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(1800);
  if (action === 'stop') f.element('voiceStop').click();
  if (action === 'hidden') { f.document.hidden = true; f.docEvents.visibilitychange(); }
  if (action === 'disconnect') { f.socket.connected = false; f.events.disconnect(); }
  if (action === 'busy') { f.element('chatInput').value = 'ręcznie'; f.element('sendBtn').click(); }
  if (action === 'draft') f.element('chatInput').value = 'ręczny szkic';
  f.advance(5000);
  assert.equal(f.emitted.length, action === 'busy' ? 1 : 0, action + ' prevents compatibility auto send');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  rec.stop = () => { throw new Error('stop failed'); };
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(6800);
  assert.equal(f.emitted.length, 0, 'stop failure is not a no-final timeout');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(3000);
  final(rec, 'Maria powiedz dzień dobry wyślij'); f.advance(900);
  assert.equal(f.emitted.length, 1); assert.equal(f.emitted[0][1].message, 'powiedz dzień dobry');
  assert.match(f.element('voiceTranscript').textContent, /^Końcowo:/, 'real final remains a real final');
}
for (const body of ['powiedz dzień dobry wyślij', 'powiedz nie wyślij']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria'); rec.onend(); f.advance(1000);
  final(f.Recognition.latest, body); f.advance(900);
  assert.equal(f.emitted.length, body.includes('nie ') ? 0 : 1);
  if (f.emitted.length) assert.equal(f.emitted[0][1].message, 'powiedz dzień dobry');
}
console.log('explicit spoken confirmation on stable no-final timeout: PASS');
for (const accept of [false, 'throw']) {
  const f = fixture({direct:true, accept}); const rec = beginHandsfree(f);
  final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(6800);
  assert.equal(f.emitted.length, 0);
  assert.doesNotMatch(f.element('voiceTranscript').textContent, /^Wysłano/);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria ' + 'x'.repeat(2001) + ' wyślij', 0, false); f.advance(6800);
  assert.equal(f.emitted.length, 0, 'compatibility body also obeys the real chat length bound');
}
{
  const f = fixture(); f.events.chat_response({success:true, message:'Poprzednia odpowiedź'});
  const rec = beginHandsfree(f); final(rec, 'Maria powiedz dzień dobry wyślij', 0, false); f.advance(1800);
  f.element('voicePlay').click(); f.advance(5000);
  assert.equal(f.emitted.length, 0, 'TTS invalidates spoken-confirmation grace');
}

function receiveAndFinishSpeech(f) {
  f.events.chat_response({success:true, message:'Odpowiedź Marii'});
  const u = f.spoken.at(-1); u.onstart(); u.onend(); f.advance(1200);
  return f.Recognition.latest;
}
{
  const f = fixture(); let rec = beginHandsfree(f);
  final(rec, 'Maria pierwsze polecenie wyślij', 0, false); f.advance(6800);
  assert.equal(f.emitted.length, 1);
  rec = receiveAndFinishSpeech(f);
  final(rec, 'niepowiązana rozmowa w pokoju', 0, false); rec.onend(); f.advance(2000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
  assert.match(f.element('voiceStatus').textContent, /nic nie wysłano/);
  const old = rec; f.advance(1200); rec = f.Recognition.latest;
  assert.notEqual(rec, old);
  const status = f.element('voiceStatus').textContent;
  final(old, 'Maria stare polecenie wyślij'); old.onerror({error:'aborted'}); old.onend();
  assert.equal(f.element('voiceStatus').textContent, status);
  final(rec, 'bez nowego hasła'); f.advance(900);
  assert.equal(f.emitted.length, 1, 'discarded background cannot arm a later command');
  snapshot(rec, [['Maria drugie polecenie wyślij',false]]); f.advance(6800);
  assert.equal(f.emitted.length, 2); assert.equal(f.emitted[1][1].message, 'drugie polecenie');
  receiveAndFinishSpeech(f);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true', 'two whole actual-chat turns retain explicit handsfree intent');
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  snapshot(rec, [['Maria urwany początek',true], ['niezatwierdzony koniec',false]]); rec.onend(); f.advance(6200);
  assert.equal(f.emitted.length, 0);
  final(f.Recognition.latest, 'ciąg dalszy bez hasła'); f.advance(900);
  assert.equal(f.emitted.length, 0, 'dropping incomplete turn also drops its previously final wake/prefix');
}
for (const gap of [2000, 4000]) {
  const f = fixture(); const rec = beginHandsfree(f);
  for (const text of ['Maria', 'Maria powiedz', 'Maria powiedz mi', 'Maria powiedz mi dzień', 'Maria powiedz mi dzień dobry']) {
    final(rec, text, 0, false); rec.onspeechend(); f.advance(gap);
    assert.equal(rec.stopCalls || 0, 0, 'slow words without spoken terminator must not request stop');
    assert.equal(f.emitted.length, 0);
    assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
    assert.doesNotMatch(f.element('voiceStatus').textContent, /Odśwież|sprawdź „Mów”/, 'long active capture is not presented as a failed service');
  }
  final(rec, 'Maria powiedz mi dzień dobry wyślij',0,false);
  f.advance(1799); assert.equal(rec.stopCalls || 0, 0);
  f.advance(1); assert.equal(rec.stopCalls, 1);
  f.advance(5000); assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'powiedz mi dzień dobry');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  snapshot(rec, [['Maria powiedz',true]]); f.advance(4000);
  assert.equal(f.emitted.length, 0, 'true final prefix alone is not a complete command');
  snapshot(rec, [['Maria powiedz',true], ['mi dzień',true]]); f.advance(4000);
  assert.equal(f.emitted.length, 0);
  snapshot(rec, [['Maria powiedz',true], ['mi dzień',true], ['dobry wyślij',true]]); f.advance(900);
  assert.equal(f.emitted.length, 1); assert.equal(f.emitted[0][1].message, 'powiedz mi dzień dobry');
}
for (const late of [false, true]) {
  const f = fixture({direct:true}); const old = beginHandsfree(f);
  final(old, 'Maria urwany tekst',0,!late); old.onend();
  if (late) final(old, 'Maria urwany tekst');
  f.advance(1200);
  assert.notEqual(f.Recognition.latest, old, 'ended unconfirmed final command must recover, including late final ordering');
  final(f.Recognition.latest, 'dalszy ciąg wyślij'); f.advance(900);
  assert.equal(f.emitted.length, 0, 'command body never carries across sessions');
  final(old, 'Maria stary tekst wyślij'); f.advance(900); assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'Maria niedokończone',0,false); f.advance(45000);
  assert.equal(rec.stopCalls || 0, 0, 'hard capture bound does not invent a spoken terminator');
  f.advance(6200); assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
  assert.notEqual(f.Recognition.latest, rec); assert.equal(f.emitted.length, 0);
}
for (const action of ['stop', 'hidden', 'disconnect', 'busy', 'draft']) {
  const f = fixture({direct:true}); const rec = beginHandsfree(f);
  final(rec, 'tło pokoju',0,false); rec.onend(); f.advance(2000);
  if (action === 'stop') f.element('voiceStop').click();
  if (action === 'hidden') { f.document.hidden = true; f.docEvents.visibilitychange(); }
  if (action === 'disconnect') f.voice.disconnect();
  if (action === 'busy') f.voice.setBusy(true);
  if (action === 'draft') f.element('chatInput').value = 'mój szkic';
  f.advance(1200); assert.equal(f.Recognition.instances.length, 1, action + ' prevents discarded-capture restart');
  final(rec, 'Maria spóźnione wyślij'); assert.equal(f.emitted.length, 0);
  if (action === 'draft') assert.equal(f.element('chatInput').value, 'mój szkic');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria wyślij',0,false); f.advance(4000);
  assert.equal(rec.stopCalls || 0, 0, 'initial verb is not an empty confirmation');
  assert.equal(f.emitted.length, 0);
  final(rec, 'Maria wyślij wiadomość test wyślij',0,false); f.advance(6800);
  assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'wyślij wiadomość test');
}
{
  const f = fixture(); const rec = beginHandsfree(f);
  final(rec, 'Maria wyślij'); f.advance(4000);
  assert.equal(f.emitted.length, 0);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
  assert.doesNotMatch(f.element('voiceStatus').textContent, /Polecenie potwierdzone/);
  snapshot(rec, [['Maria wyślij',true], ['wiadomość test wyślij',true]]); f.advance(900);
  assert.equal(f.emitted.length, 1);
  assert.equal(f.emitted[0][1].message, 'wyślij wiadomość test');
}
for (const phrase of ['Maria wyślij', 'Maria nie wyślij', 'Maria '+ 'x'.repeat(2001) +' wyślij']) {
  for (const late of [false, true]) {
    const f = fixture({direct:true}); const old = beginHandsfree(f);
    final(old, phrase,0,!late); f.advance(1000); old.onend();
    if (late) final(old, phrase);
    f.advance(1200);
    assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true');
    assert.notEqual(f.Recognition.latest, old, 'invalid final confirmation recovers in either native-end ordering');
    final(f.Recognition.latest, 'wiadomość test wyślij'); f.advance(900);
    assert.equal(f.emitted.length, 0, 'fresh session does not inherit invalid wake or command');
  }
}
console.log('explicit terminator for slow speech and fresh-wake recovery across whole chat turns: PASS');
{
  const f = fixture(); let rec = beginHandsfree(f);
  final(rec, 'Maria pierwsze wyślij'); f.advance(900);
  rec = receiveAndFinishSpeech(f);
  for (let i = 1; i <= 2; i++) {
    const old = rec;
    final(old, 'Maria niedokończone',0,false); old.onerror({error:'aborted'});
    f.advance(i * 1000 - 1); assert.equal(f.Recognition.latest, old);
    f.advance(1); rec = f.Recognition.latest; assert.notEqual(rec, old);
    const status = f.element('voiceStatus').textContent;
    final(old, 'Maria stare polecenie wyślij'); old.onerror({error:'aborted'}); old.onend();
    assert.equal(f.element('voiceStatus').textContent, status);
    final(rec, 'dopisek wyślij'); f.advance(900);
    assert.equal(f.emitted.length, 1, 'fresh capture cannot inherit aborted wake or body');
  }
  rec.onerror({error:'aborted'}); f.advance(5000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
  assert.match(f.element('voiceStatus').textContent, /trzykrotnie/);
  assert.equal(f.emitted.length, 1, 'aborted recovery never resends the preceding network message');
  rec = beginHandsfree(f); rec.onerror({error:'aborted'}); f.advance(1000);
  assert.notEqual(f.Recognition.latest, rec, 'explicit opt-in resets abort allowance');
  final(f.Recognition.latest, 'Maria drugie wyślij'); f.advance(900); assert.equal(f.emitted.length, 2);
  rec = receiveAndFinishSpeech(f);
  for (let i = 1; i <= 2; i++) { rec.onerror({error:'aborted'}); f.advance(i * 1000); rec = f.Recognition.latest; }
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'true', 'accepted command resets allowance for another two retries');
}
{
  const f = fixture({direct:true}); let rec = beginHandsfree(f);
  rec.onerror({error:'aborted'}); f.advance(1000); rec = f.Recognition.latest;
  f.advance(3000); rec.onend(); f.advance(1000); rec = f.Recognition.latest;
  final(rec, 'niezatwierdzone tło',0,false); rec.onerror({error:'aborted'}); f.advance(2000);
  f.Recognition.latest.onerror({error:'aborted'}); f.advance(5000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false', 'onstart, normal idle and interim do not reset abort budget');
}
for (const action of ['stop', 'hidden', 'pagehide', 'disconnect', 'busy', 'tts', 'draft', 'new-manual']) {
  const f = fixture({direct:true}); f.voice.response('Poprzednia odpowiedź');
  const rec = beginHandsfree(f); rec.onerror({error:'aborted'});
  if (action === 'stop') f.element('voiceStop').click();
  if (action === 'hidden') { f.document.hidden = true; f.docEvents.visibilitychange(); }
  if (action === 'pagehide') f.winEvents.pagehide();
  if (action === 'disconnect') f.voice.disconnect();
  if (action === 'busy') f.voice.setBusy(true);
  if (action === 'tts') f.element('voicePlay').click();
  if (action === 'draft') f.element('chatInput').value = 'ręczny szkic';
  if (action === 'new-manual') f.element('voiceMic').click();
  const count = f.Recognition.instances.length;
  f.advance(2500); assert.equal(f.Recognition.instances.length, count, action + ' invalidates aborted resume');
  final(rec, 'Maria stare wyślij'); assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true}); f.element('voiceMic').click();
  const rec = f.Recognition.latest; rec.onerror({error:'aborted'}); f.advance(5000);
  assert.equal(f.Recognition.instances.length, 1, 'manual aborted has no automatic retry');
}
{
  const f = fixture({direct:true}); f.element('voiceMic').click(); const rec = f.Recognition.latest;
  final(rec, 'tylko podgląd',0,false); f.advance(1800); assert.equal(rec.stopCalls, 1);
  f.advance(4999); assert.equal(f.element('voiceMic').attrs['aria-pressed'], 'true');
  f.advance(1); assert.equal(f.element('voiceMic').attrs['aria-pressed'], 'false', 'manual final grace remains five seconds');
  assert.equal(f.emitted.length, 0);
}
console.log('bounded current-session aborted recovery and separate manual final grace: PASS');

function fakeMicMedia({state = 'running', missingContext = false, constructorThrows = false, constructorBlockAfterFirst = false, resumeRejects = false, sourceThrows = false, requireGesture = false, resumePending = false} = {}) {
  const requests = [], contexts = [];
  const media = {byte:128, requests, contexts, resumeRequests:[]};
  media.devices = {getUserMedia(constraints) { return new Promise((resolve, reject) => requests.push({constraints, resolve, reject})); }};
  media.stream = () => {
    const tracks = [0,1].map(() => ({stops:0, stop() { this.stops++; this.onended?.(); }}));
    return {tracks, getTracks:() => tracks, getAudioTracks:() => [tracks[0]]};
  };
  if (!missingContext) media.AudioContext = class {
    constructor() { if (constructorThrows || (constructorBlockAfterFirst && contexts.length) || (requireGesture && !media.gesture?.())) throw new Error('no context'); this.state = state; this.sampleRate = 48000; this.destination = {}; this.closes = 0; contexts.push(this); }
    resume() { if(requireGesture && !media.gesture?.())throw new Error('resume outside gesture'); this.resumed = true; this.resumes = (this.resumes || 0) + 1; if(resumePending)return new Promise((resolve,reject)=>media.resumeRequests.push({resolve,reject})); return resumeRejects ? Promise.reject(new Error('blocked')) : Promise.resolve(); }
    close() { this.closes++; this.state = 'closed'; return Promise.resolve(); }
    createMediaStreamSource(stream) {
      if (sourceThrows) throw new Error('source unavailable');
      this.stream = stream;
      return this.source = {disconnects:0, connections:[], connect(node) { this.connections.push(node); }, disconnect() { this.disconnects++; }};
    }
    createAnalyser() { return this.analyser = {disconnects:0, getByteTimeDomainData(values) { values.fill(media.byte); }, disconnect() { this.disconnects++; }}; }
    createScriptProcessor() { return this.processor = {disconnects:0, connections:[], connect(node) { this.connections.push(node); }, disconnect() { this.disconnects++; }}; }
    createGain() { return this.gain = {gain:{value:1}, disconnects:0, connections:[], connect(node) { this.connections.push(node); }, disconnect() { this.disconnects++; }}; }
  };
  return media;
}
for (const byte of [128, 150]) {
  const media = fakeMicMedia(), f = fixture({direct:true, media});
  const old = beginHandsfree(f), task = f.element('voiceMicTest').listeners.click();
  assert.equal(old.aborted, true); assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
  assert.equal(f.element('voiceToggle').attrs['aria-pressed'], 'false');
  assert.equal(media.contexts[0].resumed, true, 'AudioContext starts in the same gesture before permission resolves');
  assert.equal(media.requests[0].constraints.audio, true); assert.equal(media.requests[0].constraints.video, false);
  const stream = media.stream(); media.requests[0].resolve(stream); await task;
  assert.match(f.element('voiceStatus').textContent, /Mikrofon otwarty/);
  assert.doesNotMatch(f.element('voiceStatus').textContent, /odbiera dźwięk/);
  media.byte = byte; f.advance(7999);
  assert.match(f.element('voiceMicLevel').textContent, byte === 128 ? /Poziom dźwięku: 0\/100 · najwyższy: 0\/100/ : /Poziom dźwięku: 100\/100 · najwyższy: 100\/100/);
  assert.equal(stream.tracks[0].stops, 0); f.advance(1);
  assert.match(f.element('voiceStatus').textContent, byte === 128 ? /nie wykryłem dźwięku/ : /odbiera dźwięk.*nie działanie rozpoznawania/);
  assert.ok(stream.tracks.every(t => t.stops === 1), 'all tracks are stopped after measurement');
  const ctx = media.contexts[0];
  assert.equal(ctx.closes, 1); assert.equal(ctx.source.disconnects, 1); assert.equal(ctx.analyser.disconnects, 1);
  assert.equal(ctx.source.connections.length, 1); assert.equal(ctx.source.connections[0], ctx.analyser, 'microphone is connected only to analyser, never output');
  assert.equal(f.Recognition.instances.length, 1); assert.equal(f.emitted.length, 0);
  assert.equal(f.element('voiceMicTest').attrs['aria-pressed'], 'false');
  f.element('voiceMic').click(); assert.equal(f.Recognition.instances.length, 2, 'manual dictation remains available after probe cleanup');
}
for (const phase of ['pending', 'measuring']) {
  for (const action of ['stop', 'hidden', 'pagehide', 'disconnect', 'busy', 'dispose', 'manual', 'hf', 'tts', 'probe-toggle']) {
    const media = fakeMicMedia(), f = fixture({direct:true, media});
    f.voice.response('Poprzednia odpowiedź');
    const task = f.element('voiceMicTest').listeners.click(), stream = media.stream();
    if (phase === 'measuring') { media.requests[0].resolve(stream); await task; }
    if (action === 'stop') f.element('voiceStop').click();
    if (action === 'hidden') { f.document.hidden = true; f.docEvents.visibilitychange(); }
    if (action === 'pagehide') f.winEvents.pagehide();
    if (action === 'disconnect') f.voice.disconnect();
    if (action === 'busy') f.voice.setBusy(true);
    if (action === 'dispose') f.voice.dispose();
    if (action === 'manual') f.element('voiceMic').click();
    if (action === 'hf') f.element('voiceHandsfree').click();
    if (action === 'tts') f.element('voicePlay').click();
    if (action === 'probe-toggle') f.element('voiceMicTest').click();
    const status = f.element('voiceStatus').textContent;
    if (phase === 'pending') { media.requests[0].resolve(stream); await task; }
    assert.ok(stream.tracks.every(t => t.stops === 1), phase + '/' + action + ' closes even a late permission stream');
    assert.equal(media.contexts[0].closes, 1);
    assert.equal(f.element('voiceStatus').textContent, status, 'late fulfilment cannot overwrite newer state');
    assert.equal(f.emitted.length, 0);
  }
}
for (const config of [{missingContext:true}, {constructorThrows:true}, {sourceThrows:true}, {resumeRejects:true}]) {
  const media = fakeMicMedia(config), f = fixture({direct:true, media});
  const task = f.element('voiceMicTest').listeners.click(), stream = media.stream();
  media.requests[0].resolve(stream); await task; await Promise.resolve();
  assert.ok(stream.tracks.every(t => t.stops === 1));
  assert.match(f.element('voiceStatus').textContent, /nie został ukończony/i);
  assert.doesNotMatch(f.element('voiceStatus').textContent, /nie wykryłem dźwięku/);
  assert.ok(media.contexts.every(c => c.closes === 1));
}
{
  const media = fakeMicMedia(), f = fixture({direct:true, media});
  const task = f.element('voiceMicTest').listeners.click();
  f.advance(19999); assert.equal(f.element('voiceMicTest').attrs['aria-pressed'], 'true');
  f.advance(1); assert.equal(f.element('voiceMicTest').attrs['aria-pressed'], 'false');
  const status = f.element('voiceStatus').textContent, stream = media.stream();
  media.requests[0].resolve(stream); await task;
  assert.ok(stream.tracks.every(t => t.stops === 1)); assert.equal(f.element('voiceStatus').textContent, status);
}
{
  const media = fakeMicMedia({state:'suspended'}), f = fixture({direct:true, media});
  const task = f.element('voiceMicTest').listeners.click(), stream = media.stream();
  media.requests[0].resolve(stream); await task;
  f.advance(5000); assert.equal(stream.tracks[0].stops, 0);
  assert.match(f.element('voiceStatus').textContent, /czekam na uruchomienie pomiaru/);
  media.contexts[0].state = 'running'; f.advance(100);
  f.advance(7999); assert.equal(stream.tracks[0].stops, 0); f.advance(1);
  assert.equal(stream.tracks[0].stops, 1, 'eight seconds are measured after context readiness');
}
{
  const media = fakeMicMedia({state:'suspended'}), f = fixture({direct:true, media});
  const task = f.element('voiceMicTest').listeners.click(), stream = media.stream();
  media.requests[0].resolve(stream); await task;
  f.advance(9000); f.advance(9000); f.advance(2000);
  assert.equal(stream.tracks[0].stops, 1); assert.match(f.element('voiceStatus').textContent, /nie został ukończony/);
}
{
  const media = fakeMicMedia(), f = fixture({direct:true, media});
  const task = f.element('voiceMicTest').listeners.click();
  media.requests[0].reject({name:'NotAllowedError'}); await task;
  assert.match(f.element('voiceStatus').textContent, /Brak zgody/); assert.equal(media.contexts[0].closes, 1);
  assert.equal(f.Recognition.instances.length, 0);
}
for (const config of [{secure:false,media:fakeMicMedia()}, {}]) {
  const f = fixture({direct:true,...config});
  assert.equal(f.element('voiceMicTest').disabled, true);
  f.element('voiceMicTest').click(); assert.equal(f.Recognition.instances.length, 0);
}
console.log('local microphone probe signal, permission, readiness and complete async disposal: PASS');

function fakeLocalMedia({available = true, ...config} = {}) {
  const media = fakeMicMedia(config); media.posts = []; media.fetches = [];
  media.fetch = (url, options) => {
    media.fetches.push({url, options});
    if (url === '/api/voice/status') return Promise.resolve({ok:true, json:async () => ({available, sample_rate:16000, max_seconds:30, provider:'whisper.cpp', language:'pl'})});
    assert.equal(url, '/api/voice/transcribe');
    return new Promise((resolve, reject) => media.posts.push({options, resolve, reject}));
  };
  return media;
}
async function settle() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
async function localCapture(f, media) {
  const request = media.requests.at(-1), stream = media.stream(); request.resolve(stream); await settle();
  return {context:media.contexts.at(-1), stream};
}
function feedPCM(f, context, amplitude, blocks) {
  for (let i = 0; i < blocks; i++) {
    const callback = context.processor.onaudioprocess;
    if (!callback) break;
    const data = new Float32Array(4096); data.fill(amplitude);
    callback({inputBuffer:{getChannelData:() => data}}); f.advance(4096 / context.sampleRate * 1000);
  }
}
async function sayLocal(f, media) {
  const capture = await localCapture(f, media);
  feedPCM(f, capture.context, 0.05, 4); feedPCM(f, capture.context, 0, 48);
  return capture;
}
{
  const media = fakeLocalMedia(), f = fixture({media, local:true});
  assert.equal(f.element('voiceMic').disabled, true, 'status check completes before microphone can start');
  await settle(); assert.equal(f.element('voiceMic').disabled, false);
  const wav = f.window.MariaLocalSTT.encodeWav([new Float32Array([1,1,1,-1,-1,-1,0,0,0])], 48000);
  const view = new DataView(wav);
  assert.equal(view.getUint32(24,true),16000); assert.equal(view.getUint16(22,true),1); assert.equal(view.getUint16(34,true),16);
  assert.equal(view.getUint32(40,true),6); assert.equal(view.getInt16(44,true),32767); assert.equal(view.getInt16(46,true),-32768); assert.equal(view.getInt16(48,true),0);
  assert.throws(() => f.window.MariaLocalSTT.encodeWav([new Float32Array(48000*31)],48000), /audio-limit/, 'encoder cannot silently truncate an utterance');
  const capped = f.window.MariaLocalSTT.encodeWav([new Float32Array(48000*30)],48000);
  assert.equal(capped.byteLength,960044); assert.ok(capped.byteLength < 1048576);
  f.element('voiceMic').click();
  const capture = await sayLocal(f,media);
  assert.equal(media.posts.length,1); assert.ok(capture.stream.tracks.every(t => t.stops === 1));
  assert.equal(capture.context.closes,1); assert.equal(capture.context.gain.gain.value,0);
  assert.equal(media.posts[0].options.credentials,'same-origin'); assert.equal(media.posts[0].options.headers['Content-Type'],'audio/wav');
  media.posts[0].resolve({ok:true,json:async () => ({success:true,text:'To lokalna wiadomość'})}); await settle();
  assert.equal(f.element('chatInput').value,'To lokalna wiadomość'); assert.equal(f.emitted.length,0,'local manual result remains a draft');
  assert.equal(f.Recognition.instances.length,0,'Apple recognizer is never constructed in local mode');
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  for (const text of ['Maria pierwsze polecenie wyślij','Maria drugie polecenie wyślij']) {
    const capture=await sayLocal(f,media), post=media.posts.at(-1);
    assert.ok(capture.stream.tracks.every(t=>t.stops===1));
    post.resolve({ok:true,json:async()=>({success:true,text})});await settle();f.advance(900);
    assert.equal(f.emitted.at(-1)[1].message,text.includes('pierwsze')?'pierwsze polecenie':'drugie polecenie');
    f.events.chat_response({success:true,message:'Odpowiedź na polecenie'});
    const u=f.spoken.at(-1);u.onstart();const requests=media.requests.length;f.advance(2000);
    assert.equal(media.requests.length,requests,'no local recording during TTS');
    u.onend();f.advance(1200);
  }
  assert.equal(f.emitted.length,2);assert.equal(media.posts.length,2);assert.equal(f.Recognition.instances.length,0);
  f.element('voiceStop').click();
  const stream=media.stream();media.requests.at(-1).resolve(stream);await settle();assert.ok(stream.tracks.every(t=>t.stops===1));
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true,direct:true});await settle();await beginLocalConversation(f);
  const {context}=await localCapture(f,media);feedPCM(f,context,0,20);feedPCM(f,context,0.05,2);feedPCM(f,context,0,20);
  f.advance(30000);
  assert.equal(media.posts.length,0,'idle and short noise do not invoke STT');
  f.advance(1000);assert.equal(media.requests.length,2,'idle renews once after normal capture duration, without rapid loop');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'true');f.element('voiceStop').click();
  media.requests.at(-1).resolve(media.stream());await settle();
}
for (const phase of ['permission','upload']) {
  for (const action of ['stop','hidden','disconnect','busy','probe','tts']) {
    const media=fakeLocalMedia(),f=fixture({media,local:true,direct:true});await settle();f.voice.response('Odpowiedź');await beginLocalConversation(f);
    let stream;
    if(phase==='upload') ({stream}=await sayLocal(f,media));
    if(action==='stop')f.element('voiceStop').click();
    if(action==='hidden'){f.document.hidden=true;f.docEvents.visibilitychange();}
    if(action==='disconnect')f.voice.disconnect();
    if(action==='busy')f.voice.setBusy(true);
    if(action==='probe')f.element('voiceMicTest').click();
    if(action==='tts')f.element('voicePlay').click();
    const status=f.element('voiceStatus').textContent;
    if(phase==='permission'){stream=media.stream();media.requests[0].resolve(stream);}
    else {assert.equal(media.posts[0].options.signal.aborted,true);media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria stare polecenie wyślij'})});}
    await settle();f.advance(900);
    assert.ok(stream.tracks.every(t=>t.stops===1));assert.equal(f.emitted.length,0);assert.equal(f.element('voiceStatus').textContent,status);
    if(action==='probe'){media.requests.at(-1).resolve(media.stream());await settle();f.element('voiceStop').click();}
  }
}
{
  const media=fakeLocalMedia({available:false}),f=fixture({media,local:true});await settle();
  assert.equal(f.element('voiceMic').disabled,true);assert.equal(f.element('voiceHandsfree').disabled,true);
  assert.equal(f.element('voiceMicTest').disabled,false);assert.match(f.element('voiceConfirmation').textContent,/Nie przełączam na usługę Apple/);
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  media.posts[0].resolve({ok:false,json:async()=>({success:false,code:'busy'})});await settle();
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false');assert.equal(f.Recognition.instances.length,0);assert.equal(f.emitted.length,0);
}
console.log('local PCM/WAV capture, VAD, cancellation and two actual chat/TTS turns: PASS');
{
  const media=fakeLocalMedia(), f=fixture({media,requireLocal:true}); await settle();
  assert.equal(f.element('voiceMic').disabled,true);assert.equal(f.Recognition.instances.length,0,'missing local script never silently uses Apple');
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();
  const wav=f.window.MariaLocalSTT.encodeWav([new Float32Array(44100).fill(0.5)],44100),view=new DataView(wav);
  assert.equal(wav.byteLength,32044);assert.equal(view.getInt16(44,true),16384,'44.1kHz is converted using actual sample rate');
  f.element('voiceMic').click();await sayLocal(f,media);
  f.advance(46000);assert.equal(media.posts[0].options.signal.aborted,false,'legacy 30/45s UI timers do not abort local transcription');
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Wynik po transkrypcji'})});await settle();
  assert.equal(f.element('chatInput').value,'Wynik po transkrypcji');
}
for(const config of [{constructorThrows:true},{resumeRejects:true},{state:'suspended'}]){
  const media=fakeLocalMedia(config),f=fixture({media,local:true});await settle();f.element('voiceHandsfree').click();await settle();
  assert.equal(media.requests.length,0,'failed context preparation never opens a microphone');assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false');
  assert.equal(media.posts.length,0);assert.equal(f.Recognition.instances.length,0);
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();f.element('voiceMic').click();await sayLocal(f,media);
  f.advance(120000);await settle();assert.equal(media.posts[0].options.signal.aborted,true);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'spóźnione'})});await settle();assert.equal(f.element('chatInput').value,'');
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  f.element('chatInput').value='Mój szkic';media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria test wyślij'})});await settle();f.advance(900);
  assert.equal(f.emitted.length,0);assert.equal(f.element('chatInput').value,'Mój szkic');
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});
  const task=f.element('voiceMicTest').listeners.click(),status=f.element('voiceStatus').textContent;
  await settle();assert.equal(f.element('voiceStatus').textContent,status,'late status preload cannot overwrite active microphone probe');
  media.requests[0].resolve(media.stream());await task;f.element('voiceStop').click();
}
console.log('local-only startup failures, actual rates, transcription timeout and draft guards: PASS');
{
  const media=fakeLocalMedia({constructorBlockAfterFirst:true}),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  for(const text of ['Maria pierwsze wyślij','Maria drugie wyślij']){
    const {context,stream}=await sayLocal(f,media);
    assert.equal(context.closes,0,'HF retains only the unlocked context, with microphone tracks already closed');
    assert.ok(stream.tracks.every(t=>t.stops===1));assert.equal(context.processor.onaudioprocess,null);
    media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text})});await settle();f.advance(900);
    f.events.chat_response({success:true,message:'Odpowiedź'});const u=f.spoken.at(-1);u.onstart();u.onend();f.advance(1200);
  }
  assert.equal(f.emitted.length,2);assert.equal(media.contexts.length,1);assert.equal(media.contexts[0].resumes,1,'second automatic HF turn does not call constructor/resume again');
  f.element('voiceStop').click();assert.equal(media.contexts[0].closes,1);
  media.requests.at(-1).resolve(media.stream());await settle();
}
for(const interruption of ['track','context']){
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  const {context,stream}=await localCapture(f,media);feedPCM(f,context,0.05,4);
  if(interruption==='track')stream.tracks[0].onended();
  else {context.state='interrupted';context.onstatechange();}
  assert.equal(media.posts.length,0,'interrupted capture cannot upload a truncated phrase');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false');assert.equal(context.closes,1);
  assert.ok(stream.tracks.every(t=>t.stops===1));assert.equal(context.onstatechange,null);
}
for(const action of ['stop','hidden','disconnect','dispose','manual','probe']){
  const media=fakeLocalMedia(),f=fixture({media,local:true,direct:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  const context=media.contexts[0];
  if(action==='stop')f.element('voiceStop').click();
  if(action==='hidden'){f.document.hidden=true;f.docEvents.visibilitychange();}
  if(action==='disconnect')f.voice.disconnect();
  if(action==='dispose')f.voice.dispose();
  if(action==='manual')f.element('voiceMic').click();
  if(action==='probe')f.element('voiceMicTest').click();
  assert.equal(context.closes,1,action+' releases retained HF context');
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria stare wyślij'})});await settle();assert.equal(f.emitted.length,0);
  if(action==='manual'||action==='probe'){media.requests.at(-1).resolve(media.stream());await settle();f.element('voiceStop').click();}
}
console.log('HF retains one unlocked context and rejects interrupted audio captures: PASS');
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  const {context}=await localCapture(f,media);
  feedPCM(f,context,0,293);feedPCM(f,context,0.05,118);
  assert.equal(media.posts.length,0,'25 seconds waiting do not consume the spoken utterance budget');
  feedPCM(f,context,0,48);assert.equal(media.posts.length,1);
  const seconds=new DataView(media.posts[0].options.body).getUint32(40,true)/32000;
  assert.ok(seconds>14&&seconds<16,'upload contains only bounded pre-roll, ten-second speech and ending silence');
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria całe polecenie wyślij'})});await settle();f.advance(900);
  assert.equal(f.emitted.length,1);f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();f.element('voiceMic').click();
  const {context}=await localCapture(f,media);feedPCM(f,context,0.05,4);feedPCM(f,context,0.007,60);
  assert.equal(media.posts.length,0,'quiet continuation above0.005 is not silence after speech starts');
  for(let i=0;i<3;i++){feedPCM(f,context,0,35);assert.equal(media.posts.length,0,'three-second word spacing does not cut a sentence');feedPCM(f,context,0.02,4);}
  feedPCM(f,context,0,46);assert.equal(media.posts.length,0,'less than four seconds silence is not terminal');
  feedPCM(f,context,0,2);assert.equal(media.posts.length,1);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Cała spokojna wypowiedź'})});await settle();
  assert.equal(f.element('chatInput').value,'Cała spokojna wypowiedź');assert.equal(f.emitted.length,0);
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  const {context,stream}=await localCapture(f,media);feedPCM(f,context,0.05,400);
  assert.equal(media.posts.length,0,'30-second speech limit never uploads a truncated utterance');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false');assert.match(f.element('voiceStatus').textContent,/limit 30 sekund.*Nic nie wysłano/);
  assert.ok(stream.tracks.every(t=>t.stops===1));assert.equal(context.closes,1);assert.equal(f.emitted.length,0);
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();f.element('voiceMic').click();
  const {context}=await localCapture(f,media);feedPCM(f,context,0,12);feedPCM(f,context,0.05,300);feedPCM(f,context,0,48);
  assert.equal(media.posts.length,1);const wav=media.posts[0].options.body,view=new DataView(wav);assert.ok(wav.byteLength<=960044);
  let voicedSamples=0;for(let i=44;i<wav.byteLength;i+=2)if(view.getInt16(i,true)>100)voicedSamples++;
  assert.ok(Math.abs(voicedSamples-409600)<=2,'cap adjustment removes only leading silence, preserves all25.6seconds of speech');
  f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();const rec=new f.window.MariaLocalSTT.Recognition();rec.start();
  const {context}=await localCapture(f,media);feedPCM(f,context,0,280);feedPCM(f,context,0.05,2);feedPCM(f,context,0,2);
  assert.equal(rec.voiced,false);assert.equal(rec.chunks.length,0);assert.ok(rec.preRollSamples<=context.sampleRate*0.75);
  assert.ok(rec.preRoll.reduce((n,c)=>n+c.length,0)<=context.sampleRate*0.75,'waiting memory is bounded to0.75second even near30s');
  f.advance(6000);assert.equal(media.posts.length,0);assert.equal(context.closes,1);
}
for(const action of ['stop','hidden','disconnect','busy']){
  const media=fakeLocalMedia(),f=fixture({media,local:true,direct:true});await settle();await beginLocalConversation(f);const {context,stream}=await localCapture(f,media);feedPCM(f,context,0.05,4);
  if(action==='stop')f.element('voiceStop').click();if(action==='hidden'){f.document.hidden=true;f.docEvents.visibilitychange();}if(action==='disconnect')f.voice.disconnect();if(action==='busy')f.voice.setBusy(true);
  const status=f.element('voiceStatus').textContent;f.advance(31000);assert.equal(f.element('voiceStatus').textContent,status,'cancel invalidates speech-limit timer');
  assert.equal(media.posts.length,0);assert.ok(stream.tracks.every(t=>t.stops===1));if(action==='busy')f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();f.element('voiceMic').click();const {context}=await localCapture(f,media);
  feedPCM(f,context,0,350);feedPCM(f,context,0.05,4);assert.equal(context.closes,0,'onset straddling idle30s can finish250ms admission');
  feedPCM(f,context,0,48);assert.equal(media.posts.length,1);f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();f.element('voiceMic').click();const {context}=await localCapture(f,media);
  feedPCM(f,context,0,350);feedPCM(f,context,0.05,2);f.advance(500);
  assert.equal(context.closes,1,'stalled candidate onset cannot defer idle renewal indefinitely');assert.equal(media.posts.length,0);
}
console.log('speech-relative cap, bounded pre-roll, quiet continuation and four-second endpoint: PASS');

const restoredVoiceStatus = 'Połączenie przywrócone. Włącz „Rozmowa: Maria”, aby znów rozmawiać.';
for (const [reason, expected] of [
  ['transport close', 'Brak połączenia — kanał rozmowy został przerwany. Rozmowa została zatrzymana.'],
  ['transport error', 'Brak połączenia — kanał rozmowy został przerwany. Rozmowa została zatrzymana.'],
  ['untrusted server supplied detail', 'Brak połączenia. Rozmowa została zatrzymana.']
]) {
  const f = fixture({direct:true});
  f.voice.disconnect(reason);
  assert.equal(f.element('voiceStatus').textContent, expected, 'disconnect uses fixed local reason descriptions');
}
{
  const media = fakeLocalMedia(), f = fixture({direct:true, media, local:true});
  const initial = f.element('voiceStatus').textContent;
  f.voice.connected();
  assert.equal(f.element('voiceStatus').textContent, initial, 'initial connect preserves local STT startup status');
  await settle();
  const ready = f.element('voiceStatus').textContent;
  f.voice.connected();
  assert.equal(f.element('voiceStatus').textContent, ready, 'initial connect preserves ready status');
  await beginLocalConversation(f);
  const {stream} = await localCapture(f, media);
  const listening = f.element('voiceStatus').textContent;
  f.voice.connected(); f.voice.connected();
  assert.equal(f.element('voiceStatus').textContent, listening, 'repeated connect preserves active capture status');
  assert.ok(stream.tracks.every(t => t.stops === 0), 'repeated connect does not interrupt active capture');
  f.voice.disconnect('ping timeout');
  assert.ok(stream.tracks.every(t => t.stops === 1), 'disconnect closes every microphone track');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
  assert.equal(f.element('voiceStatus').textContent, 'Brak połączenia — upłynął czas oczekiwania na serwer. Rozmowa została zatrzymana.');
  assert.doesNotMatch(f.element('voiceStatus').textContent, /ping timeout/, 'reason is translated, not displayed raw');
  f.voice.connected();
  assert.equal(f.element('voiceStatus').textContent, restoredVoiceStatus);
  const requests = media.requests.length;
  f.advance(10000);
  assert.equal(media.requests.length, requests, 'reconnect requires a fresh microphone gesture');
  assert.equal(f.emitted.length, 0);
}
{
  const f = fixture({direct:true});
  beginHandsfree(f);
  f.voice.response('Pierwsza odpowiedź', {success:true});
  const oldSpeech = f.spoken.at(-1); oldSpeech.onstart();
  f.voice.disconnect('ping timeout');
  assert.ok(f.cancelCalls > 0, 'disconnect cancels active speech');
  assert.equal(f.element('voiceToggle').attrs['aria-pressed'], 'false');
  const disconnected = f.element('voiceStatus').textContent;
  oldSpeech.onend(); oldSpeech.onerror();
  assert.equal(f.element('voiceStatus').textContent, disconnected, 'late TTS callbacks cannot erase disconnect status');
  f.voice.connected();
  const count = f.Recognition.instances.length;
  oldSpeech.onend(); f.advance(10000);
  assert.equal(f.element('voiceStatus').textContent, restoredVoiceStatus);
  assert.equal(f.Recognition.instances.length, count, 'stale TTS end cannot restart microphone after reconnect');
  assert.equal(f.emitted.length, 0);
}
{
  const f = fixture();
  const rec = beginHandsfree(f);
  f.socket.connected = false; f.events.disconnect('ping timeout');
  assert.equal(rec.aborted, true);
  assert.equal(f.element('sendBtn').disabled, true);
  f.socket.connected = true; f.events.connect(); await settle();
  assert.equal(f.element('sendBtn').disabled, false, 'idle reconnect releases connection busy state');
  assert.equal(f.element('voiceStatus').textContent, restoredVoiceStatus);
  const count = f.Recognition.instances.length;
  rec.onend(); final(rec, 'Maria stare polecenie wyślij'); f.advance(10000);
  assert.equal(f.Recognition.instances.length, count);
  assert.equal(f.emitted.length, 0, 'reconnect never repeats or sends stale speech');
  f.events.connect(); await settle();
  assert.equal(f.element('voiceStatus').textContent, restoredVoiceStatus);
}
{
  const f = fixture();
  const rec = beginHandsfree(f);
  final(rec, 'Maria sprawdź Kritaqo wyślij'); f.advance(900);
  assert.equal(f.emitted.length, 1);
  f.socket.connected = false; f.events.disconnect('ping timeout');
  f.socket.connected = true; f.events.connect(); await settle();
  assert.equal(f.element('sendBtn').disabled, true, 'unknown reply remains busy after reconnect');
  assert.match(f.element('voiceStatus').textContent, /Sprawdź historię/);
  assert.match(f.element('voiceStatus').textContent, /odśwież/);
  const count = f.Recognition.instances.length;
  f.element('chatInput').value = 'nie ponawiaj';
  f.element('sendBtn').click(); f.element('voiceHandsfree').click();
  rec.onend(); f.advance(140000);
  assert.equal(f.emitted.length, 1, 'unknown reply cannot be retried by reconnect, button or timer');
  assert.equal(f.Recognition.instances.length, count);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'], 'false');
}
console.log('disconnect cleanup, honest reconnect status and unknown-outcome send guard: PASS');

// Local HF uses the audio endpoint, not a word that STT must spell correctly.
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();
  await beginLocalConversation(f);
  for (const text of ['Maria powiedz dzień dobry', 'Mario drugie polecenie']) {
    const {context}=await localCapture(f,media);
    const before=f.emitted.length;
    feedPCM(f,context,0.05,4);feedPCM(f,context,0,44);
    assert.equal(media.posts.length,before,'no transcription before four seconds of measured silence');
    assert.equal(f.emitted.length,before,'no early send while capturing');
    feedPCM(f,context,0,4);
    media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text})});await settle();
    assert.equal(f.emitted.length,before+1,'one completed utterance sends exactly once without a terminator');
    assert.equal(f.emitted.at(-1)[1].message,before?'drugie polecenie':'powiedz dzień dobry');
    f.advance(900);assert.equal(f.emitted.length,before+1,'legacy final timer cannot duplicate local send');
    f.events.chat_response({success:true,message:'Odpowiedź'});
    const u=f.spoken.at(-1);u.onstart();const requests=media.requests.length;f.advance(2000);
    assert.equal(media.requests.length,requests,'no microphone during TTS');
    u.onend();f.advance(1200);
  }
  assert.equal(media.contexts.length,1,'two pause-send turns retain the unlocked HF context');
  f.element('voiceStop').click();
}
for(const text of ['polecenie bez hasła','Hej Maria polecenie',
  'Maria '+ 'x'.repeat(2001),'Maria wyślij','Maria nie wyślij']) {
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  await sayLocal(f,media);media.posts[0].resolve({ok:true,json:async()=>({success:true,text})});await settle();
  assert.equal(f.emitted.length,0,'missing leading wake, empty and invalid commands never send');
  f.advance(1200);assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'true');
  // A fresh capture must not inherit a discarded wake word.
  await sayLocal(f,media);media.posts[1].resolve({ok:true,json:async()=>({success:true,text:'dopisek bez hasła'})});await settle();
  assert.equal(f.emitted.length,0);f.element('voiceStop').click();
}
for(const reason of [undefined,'stopped']) {
  const media=fakeLocalMedia(),f=fixture({media,local:true});
  const Original=f.window.MariaLocalSTT.Recognition;
  f.window.MariaLocalSTT.Recognition=class extends Original {
    emit(name,event) {if(name==='onresult'||name==='onend')event={...event,completionReason:reason};super.emit(name,event);}
  };
  await settle();await beginLocalConversation(f);await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria nie wysyłaj uciętego'})});await settle();f.advance(900);
  assert.equal(f.emitted.length,0,'final text alone is not proof of the silence endpoint');f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();
  const rec=new f.window.MariaLocalSTT.Recognition(),results=[],ends=[];
  rec.onresult=e=>results.push(e);rec.onend=e=>ends.push(e);rec.start();
  const {context}=await localCapture(f,media);feedPCM(f,context,0.05,4);rec.stop();
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria ręczne zakończenie'})});await settle();
  assert.equal(results[0].completionReason,'stopped');assert.equal(ends[0].completionReason,'stopped');
}
for(const action of ['stop','hidden','disconnect','busy','draft','tts']) {
  const media=fakeLocalMedia(),f=fixture({media,local:true,direct:true});await settle();
  await beginLocalConversation(f);await sayLocal(f,media);
  if(action==='stop')f.element('voiceStop').click();
  if(action==='hidden'){f.document.hidden=true;f.docEvents.visibilitychange();}
  if(action==='disconnect')f.voice.disconnect('transport close');
  if(action==='busy')f.voice.setBusy(true);
  if(action==='draft')f.element('chatInput').value='zachowaj szkic';
  if(action==='tts'){f.voice.response('Odpowiedź');f.element('voicePlay').click();}
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria spóźnione polecenie'})});await settle();f.advance(1000);
  assert.equal(f.emitted.length,0,'cancelled or blocked markerless result never sends: '+action);
  if(action==='draft')assert.equal(f.element('chatInput').value,'zachowaj szkic');
  f.voice.dispose();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();f.element('voiceMic').click();await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Maria ręczny szkic'})});await settle();
  assert.equal(f.element('chatInput').value,'Maria ręczny szkic');assert.equal(f.emitted.length,0,'manual Mów remains draft-only');
}
console.log('local HF leading wake + measured silence sends once, fresh turns and completion/cancel guards: PASS');

// Auto speech reads a supplied bounded introduction or an honestly labelled
// prefix. It never invents a semantic summary or truncates manual full playback.
function enableAuto(f) {
  f.element('voiceToggle').click();
  f.spoken.at(-1).onstart(); f.spoken.at(-1).onend();
}
const longReport = 'Szczegółowy raport zawiera dane, ograniczenia i kolejne kroki. '.repeat(18);
{
  const f = fixture(); enableAuto(f);
  const brief = 'Kontrola danych jest zakończona. Pozostało zapisać instrukcję; nie sprawdzono historii uruchomienia.';
  const reply = '## W skrócie\n' + brief + '\n\n## Pełny raport\n' + longReport;
  f.events.chat_response({success:true,message:reply});
  assert.equal(f.spoken.at(-1).text,brief,'only the valid supplied introduction is auto-read');
  assert.equal(f.element('chatMessages').children.at(-1).textContent,reply,'full original Markdown stays on screen');
  assert.equal(f.element('voicePlay').textContent,'Odsłuchaj całość');
  f.spoken.at(-1).onstart();f.spoken.at(-1).onend();f.element('voicePlay').click();
  assert.ok(f.spoken.at(-1).text.includes(longReport.trim()),'manual playback retains the complete report');
  assert.ok(f.spoken.at(-1).text.includes(brief),'manual full playback also retains supplied brief');
  assert.ok(!f.spoken.at(-1).text.includes('##'),'headings are formatting, not spoken Markdown markers');
}
{
  const f = fixture({direct:true});enableAuto(f);
  f.voice.response('**Wynik:** gotowe. [Raport](https://example.invalid/report) i `kolumna_id` są w czacie.');
  assert.equal(f.spoken.at(-1).text,'Wynik: gotowe. Raport (https://example.invalid/report) i kolumna_id są w czacie.');
  f.voice.response('```python\nprint("wartość")\n```\n```x = 2```');
  assert.equal(f.spoken.at(-1).text,'print("wartość") x = 2','code content is preserved when removing fence formatting');
  f.voice.dispose();
}
{
  const f=fixture({direct:true});enableAuto(f);
  f.voice.response('Pierwszy fakt. Drugi fakt. Trzeci fakt. '+longReport);
  assert.equal(f.spoken.at(-1).text,'Czytam początek odpowiedzi. Całość jest w czacie. Pierwszy fakt. Drugi fakt. Trzeci fakt.');
  f.spoken.at(-1).onstart();assert.match(f.element('voiceStatus').textContent,/tylko początek/);
  assert.ok(f.spoken.at(-1).text.split(/\s+/).length<=70);
  f.voice.dispose();
}
for(const reply of [
  '## W skrócie\nPierwszy fakt. Drugi fakt. Trzeci fakt. Czwarty fakt.\n## Pełny raport\n'+longReport,
  '## W skrócie\nTreść bez końcowej interpunkcji\n## Pełny raport\n'+longReport,
  '## Pełny raport\nPełny początek.\n## W skrócie\n'+longReport,
  'Wprowadzenie.\n## W skrócie\nKrótki opis.\n## Pełny raport\n'+longReport,
  '## W skrócie\nKrótki opis.\n## Pełny raport\n'+longReport+'\n## W skrócie\nInny opis.',
  '## W skrócie\nKrótki opis.\n```\n## Pełny raport\n'+longReport+'\n```',
]) {
  const f=fixture({direct:true});enableAuto(f);f.voice.response(reply);
  assert.match(f.spoken.at(-1).text,/^(Czytam początek odpowiedzi|Pełna odpowiedź jest w czacie)/,'invalid marked structures never claim to be a supplied summary');
  assert.ok(f.spoken.at(-1).text.split(/\s+/).length<=70);f.voice.dispose();
}
{
  const f=fixture({direct:true});enableAuto(f);
  const hugeFirst='słowo '.repeat(75)+'koniec. '+longReport;
  f.voice.response(hugeFirst);
  assert.equal(f.spoken.at(-1).text,'Pełna odpowiedź jest w czacie. Wybierz „Odsłuchaj całość”, aby ją przeczytać.','never speak a cut-off oversized first sentence');
  f.element('voiceStop').click();const count=f.spoken.length;
  f.voice.response('Późna odpowiedź. '+longReport);f.advance(10000);
  assert.equal(f.spoken.length,count,'Stop keeps later automatic speech disabled');
  f.element('voicePlay').click();assert.ok(f.spoken.at(-1).text.includes(longReport.trim()));
  f.voice.dispose();
}
{
  const f=fixture();beginHandsfree(f);
  final(f.Recognition.latest,'Maria sprawdź stan wyślij');f.advance(900);
  const before=f.Recognition.instances.length;
  f.events.chat_response({success:true,message:'## W skrócie\nWszystkie projekty mają zapisane wyniki. Jedna kontrola pozostaje niepewna.\n## Pełny raport\n'+longReport});
  const spoken=f.spoken.at(-1);assert.equal(spoken.text,'Wszystkie projekty mają zapisane wyniki. Jedna kontrola pozostaje niepewna.');
  f.advance(2500);assert.equal(f.Recognition.instances.length,before,'no microphone while brief waits to start');
  spoken.onstart();f.advance(2000);assert.equal(f.Recognition.instances.length,before);
  spoken.onend();f.advance(1199);assert.equal(f.Recognition.instances.length,before);
  f.advance(1);assert.equal(f.Recognition.instances.length,before+1,'same existing handsfree cooldown resumes after brief');
  f.element('voiceStop').click();const stopped=f.Recognition.instances.length;
  spoken.onend();f.advance(10000);assert.equal(f.Recognition.instances.length,stopped,'late speech callback cannot undo Stop');
}
console.log('bounded supplied speech brief vs honest prefix, full manual playback and lifecycle: PASS');
for(const segmenter of [true,false]) {
  for(const words of [70,71]) {
    const f=fixture({direct:true,segmenter});enableAuto(f);
    const brief='słowo '.repeat(words-1)+'Koniec.';
    f.voice.response('## W skrócie\n'+brief+'\n## Pełny raport\n'+longReport);
    if(words===70)assert.equal(f.spoken.at(-1).text,brief,'valid brief includes the exact word-budget boundary');
    else assert.match(f.spoken.at(-1).text,/^Pełna odpowiedź jest w czacie/,'oversize brief cannot be mistaken for a bounded supplied introduction');
    f.voice.dispose();
  }
  const f=fixture({direct:true,segmenter});enableAuto(f);
  f.voice.response('Pierwszy fakt. Drugi fakt! Trzeci fakt? '+longReport);
  assert.equal(f.spoken.at(-1).text,'Czytam początek odpowiedzi. Całość jest w czacie. Pierwszy fakt. Drugi fakt! Trzeci fakt?');
  f.voice.dispose();
}
console.log('speech word-budget boundary and no-Segmenter compatibility: PASS');

{
  const f = fixture({direct:true});
  f.voice.hydrate('Zapisana pełna odpowiedź.');
  assert.equal(f.spoken.length,0,'hydration never speaks');
  assert.equal(f.element('voicePlay').disabled,false);
  f.element('voicePlay').click();
  assert.equal(f.spoken.at(-1).text,'Zapisana pełna odpowiedź.');
  f.voice.dispose();
  const history = fixture(); history.events.connect();
  await settle();
  assert.equal(history.spoken.length,0);
  assert.equal(history.element('voicePlay').disabled,false,'saved history enables manual replay');
  history.element('voicePlay').click(); assert.equal(history.spoken.at(-1).text,'history');
}
{
  const f = fixture({direct:true}); beginHandsfree(f);
  f.voice.response('Odpowiedź do przerwania.');
  const item=f.spoken.at(-1); item.onstart();
  const before=f.Recognition.instances.length;
  f.window.speechSynthesis.speaking=true;
  f.element('voiceInterrupt').click();
  item.onend(); f.advance(1600);
  assert.equal(f.Recognition.instances.length,before,'cancel is not proof that native audio is quiet');
  f.window.speechSynthesis.speaking=false;f.advance(200);
  assert.equal(f.Recognition.instances.length,before+1,'interrupt resumes previously opted-in conversation');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'true');
  f.voice.response('Drugi odczyt.'); f.spoken.at(-1).onstart();
  f.element('voiceInterrupt').click(); f.element('voiceStop').click();
  const stopped=f.Recognition.instances.length;f.advance(10000);
  assert.equal(f.Recognition.instances.length,stopped,'Stop revokes interrupt resume');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false');
  f.voice.dispose();
}
console.log('saved history manual replay and bounded interrupt-to-listen: PASS');

{
  const store=new Map(), f=fixture({storage:store,correlate:false});
  f.element('chatInput').value='Pierwsze polecenie'; f.element('sendBtn').click();
  const first=f.emitted.at(-1)[1];
  assert.match(first.request_id,/^[a-f0-9-]{36}$/i);
  assert.deepEqual(JSON.parse(store.get('maria.chat.pending.v1')),{request_id:first.request_id});
  assert.ok(!store.get('maria.chat.pending.v1').includes('polecenie'),'pending storage has no transcript');
  f.events.chat_response({request_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',success:true,message:'Stara odpowiedź'});
  assert.equal(f.element('sendBtn').disabled,true,'uncorrelated reply cannot release current turn');
  f.events.chat_response({request_id:first.request_id,success:true,message:'Potwierdzona odpowiedź'});
  assert.equal(store.size,0);assert.equal(f.element('sendBtn').disabled,false);
  const count=f.element('chatMessages').children.length;
  f.events.chat_response({request_id:first.request_id,success:true,message:'Duplikat'});
  assert.equal(f.element('chatMessages').children.length,count);
  f.element('chatInput').value='Drugie polecenie';f.element('sendBtn').click();
  const second=f.emitted.at(-1)[1];assert.notEqual(first.request_id,second.request_id);
  f.events.chat_response({request_id:first.request_id,success:true,message:'Późny duplikat'});
  assert.equal(f.element('sendBtn').disabled,true);
}
{
  const id='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const storage=new Map([['maria.chat.pending.v1',JSON.stringify({request_id:id})]]);
  const paths=[];
  const f=fixture({storage,correlate:false,apiFetch:async path=>{
    paths.push(path);
    return path.includes('/turn/') ? {request_id:id,state:'completed',response:{success:true,message:'Odzyskana pełna odpowiedź'}} : {messages:[{role:'maria',content:'Odzyskana pełna odpowiedź'}]};
  }});
  await settle();
  assert.equal(f.emitted.length,0,'reload never resubmits');
  assert.equal(f.spoken.length,0,'recovered response is never automatically spoken');
  assert.equal(storage.size,0);assert.equal(f.element('sendBtn').disabled,false);
  assert.ok(paths.some(path=>path.endsWith(id)));
  f.element('voicePlay').click();assert.equal(f.spoken.at(-1).text,'Odzyskana pełna odpowiedź');
}
{
  const id='cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  const storage=new Map([['maria.chat.pending.v1',JSON.stringify({request_id:id})]]);
  const f=fixture({storage,correlate:false,apiFetch:async()=>({request_id:id,state:'unknown'})});
  await settle();f.events.disconnect('transport close');f.events.connect();await settle();
  f.element('chatInput').value='Nie wolno ponowić';f.element('sendBtn').click();
  assert.equal(f.emitted.length,0);assert.equal(f.element('sendBtn').disabled,true);assert.equal(storage.size,1);
  f.document.hidden=true;f.docEvents.visibilitychange();f.advance(150000);await settle();
  assert.equal(f.emitted.length,0);
  f.document.hidden=false;f.element('chatContinue').click();
  assert.equal(storage.size,0);assert.equal(f.element('sendBtn').disabled,false);
  assert.equal(f.emitted.length,0,'explicit continuation does not resend the unknown request');
  f.element('chatInput').value='Sprawdź zapisane wyniki';f.element('sendBtn').click();
  assert.equal(f.emitted.length,1);assert.notEqual(f.emitted[0][1].request_id,id);
}
{
  const f=fixture({correlate:false});
  f.element('voiceToggle').click();f.spoken.at(-1).onstart();f.spoken.at(-1).onend();
  f.element('chatInput').value='Wysłana wiadomość';f.element('sendBtn').click();
  const id=f.emitted.at(-1)[1].request_id,spoken=f.spoken.length;
  f.events.chat_response({request_id:id,replayed:true,success:true,message:'Odzyskany wynik'});
  assert.equal(f.spoken.length,spoken,'server replay flag never causes automatic speech');
  f.element('voicePlay').click();assert.equal(f.spoken.at(-1).text,'Odzyskany wynik');
}
{
  const f=fixture({correlate:false});
  f.window.sessionStorage.setItem=()=>{throw new Error('disabled storage');};
  f.element('chatInput').value='Polecenie';f.element('sendBtn').click();
  assert.equal(f.emitted.length,0,'no durable ID means no dispatch');
  assert.equal(f.element('chatInput').value,'Polecenie');
}
console.log('durable turn IDs, reply correlation, reload reconciliation and no unknown retry: PASS');
{
  let id;
  const f=fixture({apiFetch:async path=>path.includes('/turn/')?{request_id:id,state:'completed'}:{messages:[{role:'maria',content:'Zapisany wynik'}]}});
  beginHandsfree(f);final(f.Recognition.latest,'Maria sprawdź zapisane wyniki wyślij');f.advance(900);
  id=f.emitted.at(-1)[1].request_id;
  f.events.chat_ack({request_id:id,state:'completed'});await settle();
  assert.equal(f.element('sendBtn').disabled,false);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false','completion without response body clears waiting-for-reply honestly');
  const before=f.spoken.length;f.advance(5000);assert.equal(f.spoken.length,before,'history-only recovery never speaks automatically');
}
console.log('history-only terminal reconciliation clears pending voice intent: PASS');

// Unlike the ordinary lifecycle fixture, this synthetic browser rejects a first
// TTS start and AudioContext constructor/resume outside the actual click callback.
{
  const media=fakeLocalMedia({requireGesture:true,constructorBlockAfterFirst:true});
  const f=fixture({media,local:true,gestureSpeech:true});await settle();
  assert.throws(()=>f.window.speechSynthesis.speak(new f.window.SpeechSynthesisUtterance('Bez gestu')),/gesture-required/);
  f.element('voiceHandsfree').click();
  assert.equal(f.spoken.length,1,'one click synchronously starts an audible cue');
  const cue=f.spoken[0];assert.equal(cue.text,'Rozmowa włączona.');
  assert.equal(media.contexts.length,1);assert.equal(media.contexts[0].resumes,1,'capture context unlocked in the same gesture');
  assert.equal(media.requests.length,0,'context preparation does not request microphone permission');
  await settle();f.advance(1500);assert.equal(media.requests.length,0,'prepared context alone cannot start capture');
  cue.onstart();f.advance(2000);assert.equal(media.requests.length,0,'no microphone while cue speaks');
  cue.onend();f.advance(1199);assert.equal(media.requests.length,0);
  f.advance(1);assert.equal(media.requests.length,1,'mic opens only after cue and normal cooldown');
  for(const command of ['Maria pierwsze polecenie','Maria drugie polecenie']) {
    const {stream}=await sayLocal(f,media);
    assert.ok(stream.tracks.every(track=>track.stops===1),'capture closed before ASR/model reply');
    media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text:command})});await settle();
    f.events.chat_response({success:true,message:'## W skrócie\nOdpowiedź głosowa działa.\n## Pełny raport\n'+longReport});
    const reply=f.spoken.at(-1);assert.equal(reply.text,'Odpowiedź głosowa działa.','first and second replies speak without voice-toggle clicks');
    const count=media.requests.length;f.advance(1200);reply.onstart();f.advance(1200);
    assert.equal(media.requests.length,count,'no mic while actual reply is pending or speaking');
    reply.onend();f.advance(1200);
  }
  assert.equal(f.emitted.length,2);assert.equal(media.contexts.length,1);assert.equal(media.contexts[0].resumes,1);
  f.element('voiceStop').click();assert.equal(media.contexts[0].closes,1);
  const late=media.stream();media.requests.at(-1).resolve(late);await settle();assert.ok(late.tracks.every(t=>t.stops===1));
}
for(const started of [false,true]) {
  for(const action of ['stop','hidden','pagehide','disconnect','busy','dispose','manual','replay','toggle','hf','interrupt']) {
    const media=fakeLocalMedia({requireGesture:true}),f=fixture({direct:true,media,local:true,gestureSpeech:true});await settle();
    f.voice.hydrate('Poprzedni zapisany wynik');f.element('voiceHandsfree').click();const cue=f.spoken.at(-1);
    if(started)cue.onstart();
    if(action==='stop')f.element('voiceStop').click();
    if(action==='hidden'){f.document.hidden=true;f.docEvents.visibilitychange();}
    if(action==='pagehide')f.winEvents.pagehide();
    if(action==='disconnect')f.voice.disconnect('transport close');
    if(action==='busy')f.voice.setBusy(true);
    if(action==='dispose')f.voice.dispose();
    if(action==='manual')f.element('voiceMic').click();
    if(action==='replay')f.element('voicePlay').click();
    if(action==='toggle')f.element('voiceToggle').click();
    if(action==='hf')f.element('voiceHandsfree').click();
    if(action==='interrupt')f.element('voiceInterrupt').click();
    const requests=media.requests.length,status=f.element('voiceStatus').textContent;
    cue.onstart();cue.onend();await settle();f.advance(20000);
    assert.equal(media.requests.length,requests,action+' invalidates pending cue microphone start');
    assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false',action+' revokes startup intent');
    // A fresh explicit manual operation may produce its own status/error, but
    // the old cue must not report success or restore automatic conversation.
    if(!['manual','replay','interrupt'].includes(action))assert.equal(f.element('voiceStatus').textContent,status);
    if(action==='interrupt')assert.match(f.element('voiceStatus').textContent,/Odczyt przerwany/);
    assert.equal(media.contexts[0].closes,1,'prepared context released on '+action);
    f.voice.dispose();
    for(const request of media.requests)request.resolve(media.stream());await settle();
  }
}
for(const failure of ['no-start','no-end','error','end-without-start','context-timeout','context-reject']) {
  const pending=failure.startsWith('context-');
  const media=fakeLocalMedia({requireGesture:true,resumePending:pending}),f=fixture({direct:true,media,local:true,gestureSpeech:true});await settle();
  f.element('voiceHandsfree').click();const cue=f.spoken.at(-1);
  if(failure==='no-start')f.advance(8000);
  if(failure==='no-end'){cue.onstart();f.advance(12000);}
  if(failure==='error')cue.onerror();
  if(failure==='end-without-start')cue.onend();
  if(pending){cue.onstart();cue.onend();if(failure==='context-reject')media.resumeRequests[0].reject(new Error('blocked'));else f.advance(8000);}
  await settle();assert.equal(media.requests.length,0,failure+' never opens a microphone');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false');assert.equal(media.contexts[0].closes,1);
  const status=f.element('voiceStatus').textContent;cue.onstart();cue.onend();
  if(pending)media.resumeRequests[0].resolve();await settle();f.advance(20000);
  assert.equal(media.requests.length,0);assert.equal(f.element('voiceStatus').textContent,status);
  f.voice.dispose();
}
console.log('one-click gesture-gated speech + context unlock, two spoken turns, cue cancellation and bounded failures: PASS');
{
  const media=fakeLocalMedia({requireGesture:true,resumePending:true}),f=fixture({direct:true,media,local:true,gestureSpeech:true});await settle();
  f.element('voiceHandsfree').click();const cue=f.spoken.at(-1);cue.onstart();cue.onend();
  assert.equal(media.requests.length,0,'ended cue still waits for capture context');
  f.voice.setBusy(true);f.voice.setBusy(false);
  media.resumeRequests[0].resolve();await settle();f.advance(20000);
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false','busy cancels a pending preparation even after cue ended');
  assert.equal(media.requests.length,0);assert.equal(media.contexts[0].closes,1);
  f.voice.dispose();
}
console.log('busy after ended cue revokes pending context preparation without stuck handsfree intent: PASS');
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'"Maria"? Tak, twoje imię to "Maria".'})});await settle();
  assert.equal(f.emitted.length,1,'quoted initial wake in the observed photo sends via real local STT/chat');
  assert.equal(f.emitted[0][1].message,'Tak, twoje imię to "Maria".','only wake decoration is removed, full body remains');
  f.element('voiceStop').click();
}
console.log('observed quoted wake photo routes complete command once: PASS');
for(const [text,body] of [
  ['„Maria”? Tak, twoje imię to „Maria”.','Tak, twoje imię to „Maria”.'],
  ['  “Mario” — „Zacytuj słowo Maria.”  ','„Zacytuj słowo Maria.”'],
  ["'Maria': 'Powiedz Maria i Mario.'","'Powiedz Maria i Mario.'"],
  ['«Maria» – „Pokaż wynik”.','„Pokaż wynik”.'],
  ['‘Mario’?! „Tak”.','„Tak”.'],
  ['Maria „Powiedz: \'Maria\'.”','„Powiedz: \'Maria\'.”'],
  ['Maria? Tak, twoje imię to "Maria".','Tak, twoje imię to "Maria".'],
  [' \n " Maria " ?   "Pokaż wynik." \n ','"Pokaż wynik."'],
  ['„Maria”, powiedz test wyślij','powiedz test']
]) {
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text})});await settle();
  assert.equal(f.emitted.length,1,'accepted bounded leading quote decoration: '+text);
  assert.equal(f.emitted[0][1].message,body,'body punctuation/quotes and repeated wake names preserved');
  f.advance(5000);assert.equal(f.emitted.length,1,'no duplicate after old finalizer deadlines');f.element('voiceStop').click();
}
for(const [text,reason] of [
  ['Marian, zrób test','zaczynać'],['Marianna zrób test','zaczynać'],['Maria2 zrób test','zaczynać'],
  ['Maria_test zrób test','zaczynać'],['xMaria zrób test','zaczynać'],['Hej "Maria", zrób test','zaczynać'],
  ['powiedz Maria zrób test','zaczynać'],['"Maria powiedz test"','zaczynać'],['""Maria"" test','zaczynać'],
  ['„Maria" test','zaczynać'],
  ['"Maria" '+ 'x'.repeat(2001),'2000'],['„Maria” nie wyślij','Nieprawidłowe'],['"Maria" wyślij','Nieprawidłowe']
]) {
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text})});await settle();
  assert.equal(f.emitted.length,0,text);
  assert.ok(f.element('voiceTranscript').textContent.includes('Nie wysłano —'));
  assert.ok(f.element('voiceTranscript').textContent.includes(reason));
  assert.ok(f.element('voiceTranscript').textContent.includes(text.trim().slice(0,1000)),'reason identifies the exact rejected capture');
  f.advance(1200);assert.ok(f.element('voiceStatus').textContent.includes('Nie wysłano poprzedniej wypowiedzi:'));
  assert.ok(f.element('voiceStatus').textContent.includes(reason),'new mic status retains prior rejection reason');
  f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'Hej Maria, powiedz coś.'})});await settle();
  const rejected=f.element('voiceTranscript').textContent;
  f.advance(1200);await localCapture(f,media);
  f.advance(30000);f.advance(1200);await settle();
  assert.equal(f.emitted.length,0);assert.equal(f.element('voiceTranscript').textContent,rejected,'30s idle/restart cannot erase an actual rejection');
  assert.match(f.element('voiceStatus').textContent,/Nie wysłano poprzedniej wypowiedzi/);
  await sayLocal(f,media);media.posts[1].resolve({ok:true,json:async()=>({success:true,text:'„Maria”, nowa poprawna wypowiedź.'})});await settle();
  assert.equal(f.emitted.length,1);assert.equal(f.emitted[0][1].message,'nowa poprawna wypowiedź.');
  assert.match(f.element('voiceTranscript').textContent,/nowa poprawna/);
  assert.doesNotMatch(f.element('voiceTranscript').textContent,/Nie wysłano|Hej Maria/,'new transcript replaces prior capture-specific outcome');
  f.element('voiceStop').click();
}
for(const action of ['stop','hidden']) {
  const media=fakeLocalMedia(),f=fixture({media,local:true,direct:true});await settle();await beginLocalConversation(f);await sayLocal(f,media);
  if(action==='stop')f.element('voiceStop').click();else{f.document.hidden=true;f.docEvents.visibilitychange();}
  const preview=f.element('voiceTranscript').textContent;
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'"Maria"? Tak, twoje imię to "Maria".'})});await settle();f.advance(35000);
  assert.equal(f.emitted.length,0);assert.equal(f.element('voiceTranscript').textContent,preview,'late quoted transcript cannot resurrect a cancelled capture');
  f.voice.dispose();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});
  const Original=f.window.MariaLocalSTT.Recognition;
  f.window.MariaLocalSTT.Recognition=class extends Original {emit(name,event){super.emit(name,name==='onend'||name==='onresult'?{...event,completionReason:'stopped'}:event);}};
  await settle();await beginLocalConversation(f);await sayLocal(f,media);
  media.posts[0].resolve({ok:true,json:async()=>({success:true,text:'„Maria”, zrób test.'})});await settle();
  assert.equal(f.emitted.length,0);assert.match(f.element('voiceTranscript').textContent,/Brak potwierdzonego zakończenia ciszą/);
  f.element('voiceStop').click();
}
{
  const f=fixture({direct:true});const rec=beginHandsfree(f);
  final(rec,'"Maria"? Powiedz test wyślij');f.advance(1000);
  assert.equal(f.emitted.length,0,'quoted wake expansion is local-only, not a legacy Safari confirmation change');f.voice.dispose();
}
console.log('local quote boundaries, intact bodies, persistent visible rejections, silence and stale-event guards: PASS');

async function localUtterance(f,media,text) {
  await sayLocal(f,media);
  media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text})});await settle();
}
function finishSpoken(f) {const u=f.spoken.at(-1);u.onstart();u.onend();f.advance(1200);}
function answerLocal(f,text='Odpowiedź na bieżące polecenie.') {f.events.chat_response({success:true,message:text});finishSpoken(f);}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  for(const [text,body] of [
    ['„Maria”, opisz słowo „Maria”.','opisz słowo „Maria”.'],
    ['A teraz powiedz Maria na końcu.','A teraz powiedz Maria na końcu.'],
    ['„Mario”? Podsumuj słowo „Maria”.','Podsumuj słowo „Maria”.'],
    ['Powiedz „koniec rozmowy” w zdaniu.','Powiedz „koniec rozmowy” w zdaniu.'],
    ['„koniec rozmowy”','„koniec rozmowy”']
  ]) {
    const count=f.emitted.length;await localUtterance(f,media,text);
    assert.equal(f.emitted.length,count+1);assert.equal(f.emitted.at(-1)[1].message,body);
    answerLocal(f);assert.match(f.element('voiceStatus').textContent,/Głos włączony|Czekam/);
  }
  const count=f.emitted.length;await localUtterance(f,media,'koniec rozmowy');
  assert.equal(f.emitted.length,count,'exact close is a local control, never a model message');
  assert.match(f.element('voiceStatus').textContent,/Czuwanie/);assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'true');
  f.advance(1200);await localUtterance(f,media,'kolejna wypowiedź bez imienia');
  assert.equal(f.emitted.length,count,'close revokes bare followups');
  f.advance(1200);await localUtterance(f,media,'Maria nowe polecenie');assert.equal(f.emitted.length,count+1);
  answerLocal(f);await localUtterance(f,media,'nowa kontynuacja');assert.equal(f.emitted.length,count+2);
  f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({direct:true,media,local:true});await settle();f.voice.hydrate('Zapisany pełny raport.');await beginLocalConversation(f);
  await localUtterance(f,media,'„Maria”');
  assert.equal(f.emitted.length,0);assert.equal(f.spoken.at(-1).text,'Tak, słucham.');
  const count=media.requests.length;f.advance(2000);assert.equal(media.requests.length,count,'standalone wake cue keeps microphone closed');
  finishSpoken(f);f.element('voicePlay').click();assert.equal(f.spoken.at(-1).text,'Zapisany pełny raport.','wake acknowledgment never replaces last reply');
  finishSpoken(f);await localUtterance(f,media,'pokaż wynik');assert.equal(f.emitted.length,1);assert.equal(f.emitted[0][1].message,'pokaż wynik');
  f.voice.dispose();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  await localUtterance(f,media,'Maria');finishSpoken(f);await localCapture(f,media);
  f.advance(10000);await sayLocal(f,media);media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text:'Maria nie wyślij'})});await settle();
  assert.equal(f.emitted.length,0);f.advance(1200);await localCapture(f,media);
  for(let cycle=0;cycle<5;cycle++) {
    f.advance(30000);f.advance(1200);await localCapture(f,media);
    assert.match(f.element('voiceStatus').textContent,/Rozmowa aktywna/,'conversation remains active beyond the old one-minute timeout');
  }
  f.advance(19000);assert.match(f.element('voiceStatus').textContent,/Rozmowa aktywna/);
  f.advance(1000);assert.match(f.element('voiceStatus').textContent,/Czuwanie/,'quiet across capture renewal exhausts the original budget; rejected sound does not reset it');
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'true');
  await sayLocal(f,media);media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text:'czy teraz odpowiesz'})});await settle();
  assert.equal(f.emitted.length,0);f.element('voiceStop').click();
}
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  await localUtterance(f,media,'Mario');finishSpoken(f);await localCapture(f,media);
  for(let cycle=0;cycle<5;cycle++) {f.advance(30000);f.advance(1200);await localCapture(f,media);}
  const {context}=await localCapture(f,media);
  f.advance(29500);feedPCM(f,context,0.05,4);f.advance(200);feedPCM(f,context,0,48);
  f.advance(90000);media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text:'spóźniony wynik rozpoczętej kontynuacji'})});await settle();
  assert.equal(f.emitted.length,1,'eligibility latched at qualified speech onset survives deadline and ASR delay');
  f.advance(90000);f.events.chat_response({success:true,message:'Długo oczekiwana odpowiedź.'});
  const reply=f.spoken.at(-1);reply.onstart();const count=media.requests.length;f.advance(90000);assert.equal(media.requests.length,count);
  reply.onend();f.advance(1200);await localCapture(f,media);
  for(let cycle=0;cycle<5;cycle++) {
    f.advance(30000);f.advance(1200);await localCapture(f,media);
    assert.match(f.element('voiceStatus').textContent,/Rozmowa aktywna/,'conversation remains active beyond the old one-minute timeout');
  }
  f.advance(29500);await sayLocal(f,media);media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text:'kontynuacja po długim modelu i odczycie'})});await settle();
  assert.equal(f.emitted.length,2,'model, TTS and cooldown do not spend a renewed listening budget');f.element('voiceStop').click();
}
for(const action of ['stop','hidden','disconnect','dispose','manual']) {
  const media=fakeLocalMedia(),f=fixture({direct:true,media,local:true});await settle();await beginLocalConversation(f);
  await localUtterance(f,media,'Maria');finishSpoken(f);await sayLocal(f,media);
  if(action==='stop')f.element('voiceStop').click();
  if(action==='hidden'){f.document.hidden=true;f.docEvents.visibilitychange();}
  if(action==='disconnect')f.voice.disconnect('transport close');
  if(action==='dispose')f.voice.dispose();
  if(action==='manual')f.element('voiceMic').click();
  media.posts.at(-1).resolve({ok:true,json:async()=>({success:true,text:'stara kontynuacja'})});await settle();f.advance(185000);
  assert.equal(f.emitted.length,0);assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false',action+' revokes active lease and late capture');
  f.voice.dispose();for(const request of media.requests)request.resolve(media.stream());await settle();
}
{
  const media=fakeLocalMedia(),f=fixture({direct:true,media,local:true,onSend:voice=>voice.disconnect('transport close')});await settle();await beginLocalConversation(f);
  await localUtterance(f,media,'Maria zrób test');f.voice.setBusy(false);f.voice.connected();
  assert.equal(f.element('voiceHandsfree').attrs['aria-pressed'],'false','synchronous callback stop is not undone by accepted return');
  await beginLocalConversation(f);await localUtterance(f,media,'polecenie bez nowego imienia');
  assert.equal(f.emitted.length,1,'old accepted callback cannot restore a lease across explicit stop/new session');f.voice.dispose();
}
console.log('local foreground followups, standalone wake, exact close, listening-only lease, onset latch and cancellation: PASS');
{
  const media=fakeLocalMedia(),f=fixture({media,local:true});await settle();await beginLocalConversation(f);
  for(const closing of ['koniec   rozmowy?!','  koniec\trozmowy…  ','koniec rozmowy, wyślij']) {
    await localUtterance(f,media,'Maria');finishSpoken(f);
    await localUtterance(f,media,closing);
    assert.equal(f.emitted.length,0,'whole local close tolerates ASR spacing/punctuation and old terminator');
    assert.match(f.element('voiceStatus').textContent,/Czuwanie/);f.advance(1200);
  }
  await localUtterance(f,media,'Maria');finishSpoken(f);
  await localUtterance(f,media,'nie koniec rozmowy?!');
  assert.equal(f.emitted.length,1);assert.equal(f.emitted[0][1].message,'nie koniec rozmowy?!','negated close stays a normal message');
  assert.equal(f.element('voiceStatus').textContent,'Polecenie wysłane. Czekam na odpowiedź Marii…');
  f.element('voiceStop').click();
}
console.log('local close comparison whitespace/punctuation/legacy terminator without negation broadening: PASS');
