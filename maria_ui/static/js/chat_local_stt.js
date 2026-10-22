/* Foreground microphone -> bounded PCM/WAV -> authenticated local STT. */
(function () {
  'use strict';
  const Context = window.AudioContext || window.webkitAudioContext;
  const devices = window.navigator && window.navigator.mediaDevices;
  const supported = window.isSecureContext === true && !!Context && !!(devices && devices.getUserMedia);
  let active = null, retainedContext = null;
  function closeContext(context) { if (context) { try { Promise.resolve(context.close()).catch(() => {}); } catch (_) {} } }
  function release() {
    if (active && active.keepContext) active.abort();
    const context = retainedContext; retainedContext = null; closeContext(context);
  }
  // Only an explicit conversation click calls this. Unlock the retained audio
  // context without opening the microphone while the startup cue is spoken.
  function prepareContext() {
    if (!supported || active) throw new Error('local-capture-unavailable');
    if (retainedContext && retainedContext.state === 'closed') retainedContext = null;
    if (!retainedContext) retainedContext = new Context();
    const context = retainedContext;
    return Promise.resolve(context.resume()).then(() => {
      if (retainedContext !== context || context.state !== 'running') throw new Error('context-unavailable');
    });
  }

  function encodeWav(chunks, sampleRate) {
    if (!Number.isFinite(sampleRate) || sampleRate < 16000) throw new Error('sample-rate');
    const length = chunks.reduce((n, chunk) => n + chunk.length, 0);
    if (length > Math.floor(sampleRate * 30)) throw new Error('audio-limit');
    const pcm = new Float32Array(length);
    let offset = 0;
    for (const chunk of chunks) { const part = chunk.subarray(0, length - offset); pcm.set(part, offset); offset += part.length; if (offset === length) break; }
    const count = Math.floor(length * 16000 / sampleRate);
    const buffer = new ArrayBuffer(44 + count * 2), view = new DataView(buffer);
    function text(at, value) { for (let i = 0; i < value.length; i++) view.setUint8(at + i, value.charCodeAt(i)); }
    text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, count * 2, true);
    for (let i = 0; i < count; i++) {
      const start = i * sampleRate / 16000, end = (i + 1) * sampleRate / 16000;
      let sum = 0;
      for (let j = Math.floor(start); j < Math.ceil(end) && j < pcm.length; j++) sum += pcm[j] * (Math.min(j + 1, end) - Math.max(j, start));
      const sample = Math.max(-1, Math.min(1, sum / (end - start)));
      view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
    }
    return buffer;
  }

  function stopTracks(stream) { if (stream) stream.getTracks().forEach(track => { try { track.stop(); } catch (_) { /* ended */ } }); }
  class LocalRecognition {
    constructor() { this.local = true; this.state = 'new'; this.token = 0; this.timers = new Set(); this.chunks = []; }
    emit(name, event) { if (typeof this[name] === 'function') this[name](event || {}); }
    later(fn, ms) { const id = window.setTimeout(() => { this.timers.delete(id); fn(); }, ms); this.timers.add(id); return id; }
    clearTimers() { this.timers.forEach(id => window.clearTimeout(id)); this.timers.clear(); }
    cleanCapture() {
      this.clearTimers();
      this.preRoll = [];
      if (this.processor) { this.processor.onaudioprocess = null; try { this.processor.disconnect(); } catch (_) {} }
      if (this.source) { try { this.source.disconnect(); } catch (_) {} }
      if (this.gain) { try { this.gain.disconnect(); } catch (_) {} }
      stopTracks(this.stream); this.stream = null;
      if (this.context) {
        if (this.context.onstatechange === this.contextStateHandler) this.context.onstatechange = null;
        if (!this.keepContext || this.context !== retainedContext) closeContext(this.context);
        this.context = null;
      }
    }
    fail(code) {
      if (this.state === 'ended' || this.state === 'aborted') return;
      this.state = 'ended'; this.token++; this.cleanCapture(); this.chunks = [];
      if (this.keepContext) release();
      if (this.controller) this.controller.abort();
      if (active === this) active = null;
      this.emit('onerror', {error:code}); this.emit('onend');
    }
    start() {
      if (this.state !== 'new' || !supported) throw new Error('local-capture-unavailable');
      if (active && active !== this) active.abort();
      active = this; this.state = 'starting';
      const token = ++this.token;
      this.later(() => this.fail('audio-capture'), 20000);
      let permission;
      try {
        permission = devices.getUserMedia({audio:true, video:false});
        if (this.keepContext && retainedContext) {
          this.context = retainedContext;
          if (this.context.state !== 'running') throw new Error('context-interrupted');
        } else {
          this.context = new Context();
          if (this.keepContext) retainedContext = this.context;
          Promise.resolve(this.context.resume()).catch(() => { if (token === this.token) this.fail('audio-capture'); });
        }
      } catch (_) {
        if (permission) Promise.resolve(permission).then(stopTracks, () => {});
        this.fail('audio-capture'); return;
      }
      Promise.resolve(permission).then(stream => {
        if (token !== this.token || this.state !== 'starting') { stopTracks(stream); return; }
        this.stream = stream;
        const tracks = stream.getAudioTracks ? stream.getAudioTracks() : stream.getTracks();
        if (!tracks.length || tracks.some(track => track.readyState === 'ended')) { this.fail('audio-capture'); return; }
        tracks.forEach(track => { track.onended = () => {
          if (token === this.token && (this.state === 'starting' || this.state === 'listening')) this.fail('audio-capture');
        }; });
        const ready = () => {
          if (token !== this.token || this.state !== 'starting') return;
          if (this.context.state !== 'running') { this.later(ready, 100); return; }
          try {
            this.sampleRate = this.context.sampleRate;
            if (!Number.isFinite(this.sampleRate) || this.sampleRate < 16000) throw new Error('sample-rate');
            this.source = this.context.createMediaStreamSource(stream);
            this.processor = this.context.createScriptProcessor(4096, 1, 1);
            this.gain = this.context.createGain(); this.gain.gain.value = 0;
            this.source.connect(this.processor); this.processor.connect(this.gain); this.gain.connect(this.context.destination);
            this.clearTimers(); this.state = 'listening'; this.samples = 0; this.voiceRun = 0; this.silence = 0; this.voiced = false;
            this.preRoll = []; this.preRollSamples = 0; this.speechSamples = 0; this.leadingSamples = 0;
            const context = this.context;
            this.contextStateHandler = () => { if (token === this.token && this.state === 'listening' && context.state !== 'running') this.fail('audio-capture'); };
            context.onstatechange = this.contextStateHandler;
            this.processor.onaudioprocess = event => {
              if (token !== this.token || this.state !== 'listening') return;
              try {
                if (this.context.state !== 'running') { this.fail('audio-capture'); return; }
                const input = event.inputBuffer.getChannelData(0);
                const count = input.length;
                if (!count) return;
                const copy = new Float32Array(count); copy.set(input);
                let sum = 0; for (let i = 0; i < copy.length; i++) sum += copy[i] * copy[i];
                const seconds = count / this.sampleRate, loud = Math.sqrt(sum / count) >= (this.voiced ? 0.005 : 0.01);
                this.voiceRun = loud ? this.voiceRun + seconds : 0;
                if (!this.voiced) {
                  this.preRoll.push(copy); this.preRollSamples += count;
                  let excess = this.preRollSamples - Math.floor(this.sampleRate * 0.75);
                  while (excess > 0 && this.preRoll.length) {
                    const first = this.preRoll[0], drop = Math.min(excess, first.length);
                    if (drop === first.length) this.preRoll.shift(); else this.preRoll[0] = first.subarray(drop);
                    excess -= drop; this.preRollSamples -= drop;
                  }
                  if (this.voiceRun < 0.25) return;
                  this.voiced = true; this.chunks = this.preRoll; this.preRoll = [];
                  this.samples = this.preRollSamples; this.speechSamples = Math.round(this.voiceRun * this.sampleRate);
                  this.leadingSamples = Math.max(0, this.samples - this.speechSamples);
                  this.clearTimers();
                  this.later(() => this.fail('local-stt-limit'), Math.max(0, 30000 - this.voiceRun * 1000));
                  this.emit('onspeechstart');
                } else {
                  this.chunks.push(copy); this.samples += count; this.speechSamples += count;
                }
                if (this.speechSamples >= Math.floor(this.sampleRate * 30)) { this.fail('local-stt-limit'); return; }
                if (this.voiced) this.silence = loud ? 0 : this.silence + seconds;
                if (this.voiced && this.silence >= 4) { this.emit('onspeechend'); this.stop(); }
              } catch (_) { this.fail('audio-capture'); }
            };
            this.later(() => {
              // A positive onset near idle renewal gets one bounded decision
              // window; admission clears this timer and starts its own budget.
              if (this.voiceRun > 0 && !this.voiced) this.later(() => this.stop(), 400);
              else this.stop();
            }, 30000);
            this.emit('onstart'); this.emit('onaudiostart');
          } catch (_) { this.fail('audio-capture'); }
        };
        ready();
      }, error => { if (token === this.token) this.fail(error && error.name === 'NotAllowedError' ? 'not-allowed' : 'audio-capture'); });
    }
    stop() {
      if (this.state === 'starting') { this.abort(); return; }
      if (this.state !== 'listening') return;
      const token = this.token;
      // Only the audio VAD can admit a handsfree send. A plain stop is not silence.
      const completionReason = this.voiced && this.silence >= 4 ? 'silence' : 'stopped';
      this.state = 'transcribing'; this.cleanCapture(); this.emit('onaudioend');
      if (!this.voiced) { this.chunks = []; this.state = 'ended'; if (active === this) active = null; this.emit('onend'); return; }
      this.emit('onprocessing');
      let wav;
      // A long utterance may exceed the WAV cap only by its pre-speech tail.
      // Remove leading pre-speech samples, never any part of detected speech.
      let excess = this.samples - Math.floor(this.sampleRate * 30);
      if (excess > this.leadingSamples) { this.fail('local-stt-limit'); return; }
      while (excess > 0 && this.chunks.length) {
        const first = this.chunks[0], drop = Math.min(excess, first.length);
        if (drop === first.length) this.chunks.shift(); else this.chunks[0] = first.subarray(drop);
        excess -= drop;
      }
      try { wav = encodeWav(this.chunks, this.sampleRate); } catch (_) { this.fail('local-stt-limit'); return; }
      this.chunks = [];
      if (wav.byteLength > 1048576) { this.fail('local-stt-error'); return; }
      this.controller = new window.AbortController();
      this.later(() => { if (this.state === 'transcribing') { this.controller.abort(); this.fail('local-stt-timeout'); } }, 120000);
      let request;
      try { request = window.fetch('/api/voice/transcribe', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'audio/wav'}, body:wav, signal:this.controller.signal}); }
      catch (_) { this.fail('local-stt-error'); return; }
      Promise.resolve(request)
        .then(async response => {
          const result = await response.json();
          if (token !== this.token || this.state !== 'transcribing') return;
          if (!response.ok || result.success !== true || typeof result.text !== 'string') { this.fail('local-stt-error'); return; }
          this.clearTimers(); this.state = 'ended'; if (active === this) active = null;
          if (result.text.trim()) this.emit('onresult', {completionReason, resultIndex:0, results:[Object.assign([{transcript:result.text.trim()}], {isFinal:true})]});
          this.emit('onend', {completionReason});
        }).catch(() => { if (token === this.token && this.state === 'transcribing') this.fail('local-stt-error'); });
    }
    abort() {
      if (this.state === 'aborted' || this.state === 'ended') return;
      this.state = 'aborted'; this.token++; this.cleanCapture(); this.chunks = [];
      if (this.controller) this.controller.abort();
      if (active === this) active = null;
      this.emit('onend');
    }
  }
  const ready = (async () => {
    if (!supported || !window.fetch || !window.AbortController) return {available:false};
    const controller = new window.AbortController(), timer = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await window.fetch('/api/voice/status', {credentials:'same-origin', cache:'no-store', signal:controller.signal});
      const status = await response.json();
      return {available:response.ok && status.available === true && status.sample_rate === 16000, provider:'whisper.cpp'};
    } catch (_) { return {available:false}; } finally { window.clearTimeout(timer); }
  })();
  window.MariaLocalSTT = {ready, Recognition:LocalRecognition, encodeWav, release, prepareContext};
})();
