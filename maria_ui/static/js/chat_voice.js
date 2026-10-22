/** Browser voice controls. No audio is sent to Maria by this module. */
(function () {
  'use strict';
  // Formatting only: never invent or semantically summarize the answer.
  function speechText(value) {
    return value.replace(/```(?:[\w.+-]+)?[ \t]*\r?\n([\s\S]*?)```/g, '$1')
      .replace(/```([\s\S]*?)```/g, '$1')
      .replace(/^\s{0,3}#{1,6}\s+/gm, '')
      .replace(/^\s*[-*+]\s+/gm, '')
      .replace(/^\s*(?:---+|\*\*\*+)\s*$/gm, '')
      .replace(/!?\[([^\]\n]+)\]\(([^)\n]+)\)/g, '$1 ($2)')
      .replace(/(\*\*|__)([\s\S]+?)\1/g, '$2')
      .replace(/(^|\s)[*_]([^*_\n]+)[*_](?=\s|[.,!?:;]|$)/g, '$1$2')
      .replace(/`([^`]+)`/g, '$1').replace(/\s+/g, ' ').trim();
  }
  const wordCount = text => text.trim() ? text.trim().split(/\s+/u).length : 0;
  const completeSentence = text => /[.!?…]["'”’»\)\]]*$/u.test(text);
  function sentences(text) {
    if (typeof Intl !== 'undefined' && typeof Intl.Segmenter === 'function') {
      return Array.from(new Intl.Segmenter('pl', {granularity: 'sentence'}).segment(text), item => item.segment.trim()).filter(Boolean);
    }
    return (text.match(/[\s\S]+?[.!?…]+["'”’»\)\]]*(?=\s|$)|[\s\S]+$/gu) || []).map(s => s.trim()).filter(Boolean);
  }
  function automaticSpeech(reply) {
    const raw = reply.trim();
    const headings = Array.from(raw.matchAll(/^## (W skrócie|Pełny raport)[ \t]*\r?$/gm));
    if (headings.length === 2 && headings[0].index === 0 && headings[0][1] === 'W skrócie' && headings[1][1] === 'Pełny raport') {
      const briefRaw = raw.slice(raw.indexOf('\n') + 1, headings[1].index).trim();
      const full = raw.slice(headings[1].index + headings[1][0].length).trim();
      const brief = speechText(briefRaw), parts = sentences(brief);
      if (full && brief && !/^\s*#{1,6}\s|```/m.test(briefRaw) && parts.length <= 3 && parts.every(completeSentence) && wordCount(brief) <= 70) {
        return {text: brief, fragment: false};
      }
    }
    const whole = speechText(raw);
    if (wordCount(whole) <= 70) return {text: whole, fragment: false};
    const notice = 'Czytam początek odpowiedzi. Całość jest w czacie.';
    const selected = [];
    for (const sentence of sentences(whole)) {
      if (selected.length >= 3 || !completeSentence(sentence) || wordCount(notice + ' ' + selected.concat(sentence).join(' ')) > 70) break;
      selected.push(sentence);
    }
    return selected.length ? {text: notice + ' ' + selected.join(' '), fragment: true} :
      {text: 'Pełna odpowiedź jest w czacie. Wybierz „Odsłuchaj całość”, aby ją przeczytać.', fragment: true};
  }
  window.MariaChatVoice = function (input, options) {
    const requireLocal = !!(input.dataset && input.dataset.voiceBackend === 'local');
    const el = id => document.getElementById(id);
    const mic = el('voiceMic'), toggle = el('voiceToggle');
    const play = el('voicePlay'), stop = el('voiceStop'), status = el('voiceStatus');
    const interrupt = el('voiceInterrupt');
    play.textContent = 'Odsłuchaj całość';
    options = options || {};
    let hfButton = el('voiceHandsfree');
    if (!hfButton && mic.parentNode) {
      hfButton = document.createElement('button');
      hfButton.id = 'voiceHandsfree'; hfButton.type = 'button';
      hfButton.className = 'mo-btn mo-btn--ghost';
      mic.parentNode.appendChild(hfButton);
      const note = document.createElement('p');
      note.className = 'mo-voice-note';
      note.textContent = requireLocal || window.MariaLocalSTT ? 'Rozmowa na otwartej stronie HTTPS. Rozpoznawanie na miniPC: krótkie nagranie jest przesyłane do miniPC, bez usługi Apple. Powiedz „Maria” raz, potem rozmawiaj bez powtarzania imienia. Po 3 minutach bezczynnego nasłuchu wracam do czuwania. Zakończ wypowiedź około 4 sekundami ciszy.' : 'Rozmowa bez przycisków: otwarta strona HTTPS. Powiedz: „Maria, twoje polecenie, wyślij”. Rozpoznawanie może korzystać z usług Apple; to nie lokalny detektor hasła.';
      mic.parentNode.parentNode?.appendChild(note);
    }
    let probeButton = el('voiceMicTest');
    if (!probeButton && mic.parentNode) {
      probeButton = document.createElement('button');
      probeButton.id = 'voiceMicTest'; probeButton.type = 'button';
      probeButton.className = 'mo-btn mo-btn--ghost';
      mic.parentNode.appendChild(probeButton);
    }
    function localField(id, label) {
      let field = el(id);
      if (!field && status.parentNode) {
        field = document.createElement('p'); field.id = id;
        field.className = 'mo-voice-diagnostic';
        field.setAttribute('aria-live', 'polite'); status.parentNode.appendChild(field);
      }
      if (field) field.textContent = label;
      return field;
    }
    const transcriptPreview = localField('voiceTranscript', 'Rozpoznane słowa: jeszcze brak.');
    const diagnostic = localField('voiceDiagnostic', 'Rozpoznawanie: jeszcze nie uruchomiono.');
    const probeLevel = localField('voiceMicLevel', 'Test mikrofonu: bez rozpoznawania, zapisu i wysyłania audio.');
    let localRejectionReason = '';
    function localListeningStatus(next) {
      return localRejectionReason ? 'Nie wysłano poprzedniej wypowiedzi: ' + localRejectionReason + ' ' + next : next;
    }
    function rejectLocal(reason, transcript) {
      localRejectionReason = reason;
      if (transcriptPreview) transcriptPreview.textContent = 'Nie wysłano — ' + reason + ' Rozpoznano: ' + transcript.slice(0,1000);
    }
    let diagnosticTimer = null, diagnosticSince = 0;
    let anyTranscript = false, finalTranscript = false, diagnosticHinted = false;
    const diagnosticText = text => { if (diagnostic) diagnostic.textContent = text; };
    function clearDiagnosticTimer() {
      if (diagnosticTimer !== null) window.clearTimeout(diagnosticTimer);
      diagnosticTimer = null;
    }
    function beginDiagnostics() {
      clearDiagnosticTimer(); diagnosticSince = Date.now();
      anyTranscript = finalTranscript = diagnosticHinted = false;
      localRejectionReason = '';
      if (transcriptPreview) transcriptPreview.textContent = 'Rozpoznane słowa: jeszcze brak.';
      diagnosticText('Rozpoznawanie: uruchamianie…');
    }
    function noTextHint() {
      if (handsfree && localMode) return localListeningStatus(localConversationStatus());
      if (handsfree) return anyTranscript ? 'Słucham. Zakończ polecenie słowem „wyślij”.' : 'Czekam na „Maria”. Powiedz całe polecenie i zakończ słowem „wyślij”.';
      if (localMode) return 'Lokalne rozpoznawanie: jeszcze brak tekstu. Powiedz wiadomość i zakończ około 4 sekundami ciszy.';
      return anyTranscript ? 'Safari zwróciło słowa wstępne, ale bez końcowego tekstu. Nic nie wysłano. Odśwież stronę i sprawdź „Mów” bez włączania głosu.' :
        'Safari nie zwróciło żadnego tekstu. Odśwież stronę i sprawdź „Mów” bez włączania głosu. Możesz też użyć mikrofonu klawiatury.';
    }
    function noTextDiagnostic() {
      return anyTranscript ? 'Rozpoznawanie: są słowa wstępne, brak zatwierdzenia.' : 'Rozpoznawanie: brak słów z Safari.';
    }
    function errorText(code) {
      if (localMode && (code === 'audio-capture' || code === 'start-failed')) return 'Nie udało się uruchomić lokalnego mikrofonu. Spróbuj ponownie przez „Mów”.';
      const labels = {'not-allowed':'Brak zgody na mikrofon lub rozpoznawanie.',
        'service-not-allowed':'Safari nie dopuściło usługi rozpoznawania.',
        'audio-capture':'Safari zgłosiło problem z dostępem do mikrofonu.',
        'network':'Błąd połączenia usługi rozpoznawania.',
        'no-speech':'Safari zgłosiło brak rozpoznanej wypowiedzi.',
        'aborted':'Sesja rozpoznawania została przerwana.',
        'language-not-supported':'Usługa nie obsługuje wybranego języka.',
        'start-failed':'Nie udało się rozpocząć sesji rozpoznawania.',
        'local-stt-error':'Rozpoznawanie na miniPC nie powiodło się. Nie przełączam na usługę Apple.',
        'local-stt-timeout':'Rozpoznawanie na miniPC przekroczyło czas oczekiwania.',
        'local-stt-limit':'Wypowiedź przekroczyła limit 30 sekund. Nic nie wysłano. Włącz mikrofon ponownie i powiedz krótsze polecenie.'};
      return labels[code] || 'Błąd rozpoznawania: ' + String(code || 'nieznany').slice(0, 40);
    }
    function attachDiagnostics(rec, live) {
      clearDiagnosticTimer();
      if (rec.local) {
        rec.onaudiostart = () => { if (live()) diagnosticText('Mikrofon otwarty. Dźwięk zostanie rozpoznany na miniPC.'); };
        rec.onspeechstart = () => { if (live()) diagnosticText('Lokalny pomiar wykrywa dźwięk wypowiedzi.'); };
        rec.onspeechend = () => { if (live()) diagnosticText('Wykryto około 4 sekund ciszy. Kończę nagranie.'); };
        rec.onprocessing = () => { if (live()) { diagnosticText('Rozpoznawanie krótkiego nagrania na miniPC…'); setStatus('Rozpoznawanie na miniPC…'); } };
        return;
      }
      rec.onaudiostart = () => { if (live()) diagnosticText('Safari zgłosiło otwarcie mikrofonu. Czekam na rozpoznane słowa.'); };
      rec.onsoundstart = () => { if (live()) diagnosticText('Safari zgłasza dźwięk. Czekam na rozpoznane słowa.'); };
      rec.onspeechstart = () => { if (live()) diagnosticText('Safari zgłasza mowę. Czekam na rozpoznane słowa.'); };
      rec.onspeechend = () => { if (live()) diagnosticText('Safari zgłasza koniec mowy. Czekam na zatwierdzenie tekstu.'); };
      rec.onaudioend = () => { if (live()) diagnosticText('Safari zakończyło pobieranie dźwięku.'); };
      if (!finalTranscript && !diagnosticHinted) {
        diagnosticTimer = window.setTimeout(() => {
          diagnosticTimer = null;
          if (!live() || finalTranscript) return;
          diagnosticHinted = true; diagnosticText(noTextDiagnostic()); setStatus(noTextHint());
        }, Math.max(0, 15000 - (Date.now() - diagnosticSince)));
      }
    }
    function previewResults(event) {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result && result[0] && String(result[0].transcript || '').trim();
        if (!text) continue;
        if (localMode) localRejectionReason = '';
        anyTranscript = true;
        if (result.isFinal) { finalTranscript = true; clearDiagnosticTimer(); }
        if (transcriptPreview) transcriptPreview.textContent =
          (result.isFinal ? (localMode ? 'Końcowo (miniPC): ' : 'Końcowo: ') : 'Wstępnie (niewysłane): ') + text.slice(0, 1000);
        diagnosticText(result.isFinal ? (localMode ? 'Rozpoznawanie: wynik z miniPC.' : 'Rozpoznawanie: tekst zatwierdzony przez Safari.') : 'Rozpoznawanie: słowa wstępne, jeszcze niewysłane.');
        setStatus(result.isFinal ? 'Odebrano końcowy tekst. Sprawdź podgląd.' : diagnosticHinted ? noTextHint() : 'Safari zwraca słowa wstępne. Czekam na końcowy tekst; nic nie wysyłam.');
      }
    }
    let activeFinalizer = null;
    function clearFinalizer() {
      if (activeFinalizer) activeFinalizer.cancel();
      activeFinalizer = null;
    }
    function finalizerFor(rec, live, onPending, onNoFinal, mayRequest = () => true, graceMs = 5000) {
      let pending = new Map(), stableTimer = null, graceTimer = null, endTimer = null, requestedAt = null;
      let signature = '', requested = false, ended = false;
      let fullSnapshot = [], fullSignature = '', changedAt = Date.now(), compatibilityAllowed = true;
      function clearStable() { if (stableTimer !== null) window.clearTimeout(stableTimer); stableTimer = null; }
      function clearEnd() { if (endTimer !== null) window.clearTimeout(endTimer); endTimer = null; }
      function clearGrace() { if (graceTimer !== null) window.clearTimeout(graceTimer); graceTimer = null; }
      function fail(reason) {
        if (!live()) return;
        clearStable(); clearGrace(); clearEnd();
        onNoFinal({reason, text: fullSnapshot.map(part => part.text).join(' '),
          stableMs: Date.now() - changedAt, compatibilityAllowed});
      }
      function awaitFinal() {
        if (graceTimer !== null) return;
        if (requestedAt === null) requestedAt = Date.now();
        graceTimer = window.setTimeout(() => {
          graceTimer = null;
          if (live() && pending.size) fail('no-final-timeout');
        }, Math.max(0, graceMs - (Date.now() - requestedAt)));
      }
      function requestFinal() {
        if (!live() || !pending.size || requested || !mayRequest(fullSnapshot.map(part => part.text).join(' '))) return;
        requested = true; clearStable(); awaitFinal();
        diagnosticText('Proszę Safari o zatwierdzenie słów. Jeszcze nic nie wysyłam.');
        setStatus('Czekam na końcowy tekst z Safari…');
        // stop asks for final results; abort would discard them. Mark requested
        // before calling: implementations may deliver callbacks synchronously.
        if (!ended) { try { rec.stop(); } catch (_) { fail('stop-error'); } }
      }
      function scheduleStable() {
        if (requested || !pending.size || stableTimer !== null || !mayRequest(fullSnapshot.map(part => part.text).join(' '))) return;
        stableTimer = window.setTimeout(() => { stableTimer = null; requestFinal(); }, 1800);
      }
      const controller = {
        update(event) {
          // Results are a replaceable snapshot, including retracted interim slots.
          const next = new Map(), all = [];
          for (let i = 0; i < event.results.length; i++) {
            const result = event.results[i];
            const text = result && result[0] && String(result[0].transcript || '').trim();
            if (text) all.push({index:i, text, final:!!result.isFinal});
            if (text && !result.isFinal) next.set(i, text);
          }
          const nextFullSignature = JSON.stringify(all);
          if (nextFullSignature !== fullSignature) changedAt = Date.now();
          fullSignature = nextFullSignature; fullSnapshot = all;
          const nextSignature = JSON.stringify([...next]);
          pending = next;
          if (pending.size) {
            clearEnd(); onPending();
            if (nextSignature !== signature) clearStable();
            if (requested) awaitFinal(); else scheduleStable();
          } else {
            clearStable(); clearGrace();
            // Some engines deliver final results without their terminal onend.
            // Give adjacent final chunks a short window, then close that session.
            if (requested && !ended && endTimer === null) endTimer = window.setTimeout(() => {
              endTimer = null;
              if (live() && !pending.size) rec.onend();
            }, 300);
          }
          signature = nextSignature;
        },
        hasPending() { return pending.size > 0; },
        snapshotText() { return fullSnapshot.map(part => part.text).join(' '); },
        disallowCompatibility() { compatibilityAllowed = false; },
        isEnded() { return ended; },
        request: requestFinal,
        speechEnd() { if (live()) scheduleStable(); },
        end() {
          clearEnd(); ended = true;
          if (!pending.size) { clearStable(); clearGrace(); return false; }
          requested = true; clearStable(); awaitFinal();
          diagnosticText('Safari zakończyło nasłuch bez zatwierdzenia słów. Czekam najwyżej ' + (graceMs / 1000) + ' s.');
          return true;
        },
        cancel() { clearStable(); clearGrace(); clearEnd(); pending.clear(); fullSnapshot = []; }
      };
      activeFinalizer = controller;
      return controller;
    }
    function bindSpeechEnd(rec, live, finalizer) {
      const diagnosticSpeechEnd = rec.onspeechend;
      rec.onspeechend = () => {
        if (!live()) return;
        if (diagnosticSpeechEnd) diagnosticSpeechEnd();
        finalizer.speechEnd();
      };
    }
    // Spoken confirmation is an explicit compatibility rule, never isFinal.
    function spokenConfirmation(text) {
      const wake = /^mari[ao](?=$|[\s,.!?:;\-])[\s,.!?:;\-]*/i.exec(text.trim());
      if (!wake) return null;
      const rest = text.trim().slice(wake[0].length);
      return terminatedBody(rest);
    }
    function terminatedBody(rest) {
      const end = /(?:^|[\s,.!?:;\-])(?:wyślij|wyslij)[\s,.!?:;\-]*$/i.exec(rest);
      if (!end) return null;
      const body = rest.slice(0, end.index).replace(/^[\s,.!?:;\-]+|[\s,.!?:;\-]+$/g, '').trim();
      const negative = /(?:^|\s)nie$/i.test(body);
      return {body, valid: !!body && body.length <= 2000 && !negative};
    }
    function localWakeBody(transcript) {
      // One optional pair decorates only the initial wake word. Quotes in the
      // command are never stripped, and a quoted whole sentence is not a wake.
      const quoted = /^\s*(["'„“«‘])\s*mari[ao]\s*(["'”»’])(?=$|[\s,.!?:;\-–—])/i.exec(transcript);
      const pairs = {'"':'"',"'":"'",'„':'”','“':'”','«':'»','‘':'’'};
      let wake = quoted && pairs[quoted[1]] === quoted[2] ? quoted : null;
      if (!wake) wake = /^\s*mari[ao](?=$|[\s,.!?:;\-–—])/i.exec(transcript);
      return wake ? transcript.slice(wake[0].length).replace(/^[\s,.!?:;\-–—]+/,'').trim() : null;
    }
    const confirmationNote = localField('voiceConfirmation', 'Powiedz: „Maria, twoje polecenie, wyślij”.');
    if (confirmationNote) confirmationNote.className = 'mo-voice-note';
    const synth = window.speechSynthesis;
    const localSTT = window.MariaLocalSTT;
    const localMode = requireLocal || !!localSTT;
    let Recognition = localMode ? null : window.SpeechRecognition || window.webkitSpeechRecognition;
    const canSpeak = !!(synth && window.SpeechSynthesisUtterance);
    let canListen = !!Recognition && window.isSecureContext === true;
    let recognition = null, utterance = null, timer = null, interruptTimer = null;
    let auto = false, lastReply = '', busy = false, disposed = false;
    let connectionLost = false;
    let generation = 0;
    let preparingConversation = false, prepareTimer = null;
    let startupUtterance = null;
    let handsfree = false, hfRec = null, hfTimer = null, silenceTimer = null, captureTimer = null;
    let hfGeneration = 0, armed = false, armTimer = null, waitingForReply = false;
    let rapidFailures = 0, networkErrors = 0, abortedRetries = 0;
    let micProbe = null, probeGeneration = 0;
    let conversationActive = false, conversationRemaining = 0, conversationSince = null, conversationTimer = null, conversationEpoch = 0;
    const conversationNow = () => window.performance ? window.performance.now() : Date.now();
    function localConversationStatus() {
      return conversationActive ? 'Rozmowa aktywna. Mów bez powtarzania imienia i zrób około 4 sekund ciszy. „Koniec rozmowy” przywraca czuwanie.' :
        'Czuwanie. Powiedz „Maria” lub „Maria, twoje polecenie” i zrób około 4 sekund ciszy.';
    }
    function pauseConversationBudget() {
      if (conversationTimer !== null) window.clearTimeout(conversationTimer);
      conversationTimer = null;
      if (conversationSince !== null) conversationRemaining = Math.max(0,conversationRemaining - (conversationNow() - conversationSince));
      conversationSince = null;
      if (conversationRemaining <= 0) conversationActive = false;
    }
    function clearConversation() {
      conversationEpoch++;
      pauseConversationBudget(); conversationActive = false; conversationRemaining = 0;
    }
    function activateConversation() {
      pauseConversationBudget(); conversationActive = true; conversationRemaining = 180000;
    }
    function resumeConversationBudget() {
      if (!conversationActive || conversationSince !== null) return;
      conversationSince = conversationNow();
      conversationTimer = window.setTimeout(() => {
        conversationTimer = null; conversationSince = null; conversationRemaining = 0; conversationActive = false;
        if (handsfree && !busy && !utterance && !document.hidden && !disposed) setStatus(localListeningStatus(localConversationStatus()));
      },conversationRemaining);
    }
    const mediaDevices = window.navigator && window.navigator.mediaDevices;
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    const canProbe = window.isSecureContext === true && !!(mediaDevices && mediaDevices.getUserMedia);
    const clearTimer = id => { if (id !== null) window.clearTimeout(id); };
    function pauseHandsfree() {
      pauseConversationBudget();
      hfGeneration++; clearDiagnosticTimer(); clearFinalizer();
      clearTimer(hfTimer); clearTimer(silenceTimer); clearTimer(captureTimer);
      hfTimer = silenceTimer = captureTimer = null;
      const old = hfRec; hfRec = null;
      if (old) { try { old.abort(); } catch (_) { /* inactive */ } }
    }
    function stopHandsfree() {
      clearConversation();
      preparingConversation = false; clearTimer(prepareTimer); prepareTimer = null;
      handsfree = false; waitingForReply = false; armed = false;
      clearTimer(armTimer); armTimer = null; pauseHandsfree(); render();
      if (localSTT) localSTT.release();
    }
    function scheduleHandsfree(delay) {
      clearTimer(hfTimer); hfTimer = null;
      if (!handsfree || preparingConversation || hfRec || busy || waitingForReply || utterance || document.hidden || disposed) return;
      hfTimer = window.setTimeout(() => { hfTimer = null; listenHandsfree(); }, delay);
    }
    function listenHandsfree() {
      if (!handsfree || preparingConversation || hfRec || busy || waitingForReply || utterance || document.hidden || disposed) return;
      if (synth && (synth.speaking || synth.pending)) {
        stopHandsfree(); setStatus('Odtwarzanie nadal trwa. Poczekaj i ponownie włącz rozmowę.'); return;
      }
      if (input.value.trim()) {
        stopHandsfree(); setStatus('Szkic w polu wiadomości. Wyślij go lub usuń, potem włącz rozmowę ponownie.'); return;
      }
      const token = ++hfGeneration;
      let rec;
      try { rec = new Recognition(); } catch (_) {
        stopHandsfree(); setStatus('Rozpoznawanie niedostępne. Włącz rozmowę ponownie po sprawdzeniu przeglądarki.'); return;
      }
      hfRec = rec;
      if (rec.local) rec.keepContext = true;
      const finals = new Map();
      let command = '', consumed = false, heard = false, startedAt = null, localResult = '', localSilenceResult = false, followupEligible = false;
      const live = () => handsfree && hfRec === rec && token === hfGeneration && !disposed && !document.hidden;
      rec.lang = 'pl-PL'; rec.continuous = false; rec.interimResults = true;
      setStatus(rec.local ? localListeningStatus('Czekam na dostęp do mikrofonu…') : 'Czekam na dostęp do mikrofonu…');
      rec.onstart = () => {
        if (!live()) return;
        startedAt = Date.now();
        diagnosticText(localMode ? 'Nagrywanie dla miniPC rozpoczęte. ' + localConversationStatus() : 'Safari rozpoczęło rozpoznawanie. Czekam na słowa.');
        if (rec.local) { resumeConversationBudget(); setStatus(localListeningStatus(localConversationStatus())); return; }
        setStatus(diagnosticHinted ? noTextHint() : armed ? 'Powiedz polecenie po „Maria”…' : 'Powiedz: „Maria, twoje polecenie, wyślij”. Poniżej pojawią się rozpoznane słowa.');
      };
      function sendCommand(text, compatibility) {
        if (!live() || consumed || !text.trim() || busy || waitingForReply || utterance) return false;
        if (input.value.trim()) { stopHandsfree(); setStatus('Szkic zatrzymał wysyłanie polecenia.'); return false; }
        consumed = true;
        waitingForReply = true; armed = false; clearTimer(armTimer); armTimer = null;
        pauseHandsfree();
        setStatus(rec.local ? 'Wysyłam wiadomość…' : compatibility ? 'Wysyłam po słowie „wyślij” (tryb zgodności)…' : 'Wysyłam polecenie po „Maria”…');
        let accepted = false;
        const acceptedEpoch = conversationEpoch;
        try { accepted = options.sendText(text) === true; } catch (_) { /* fail closed */ }
        if (!accepted) {
          stopHandsfree(); setStatus('Polecenie nie zostało wysłane. Sprawdź połączenie, limit lub szkic i włącz rozmowę ponownie.');
        } else if (compatibility) {
          if (transcriptPreview) transcriptPreview.textContent = 'Wysłano po słowie „wyślij” (Safari nie zatwierdziło tekstu): ' + text;
          diagnosticText('Tryb zgodności: polecenie wysłane po jawnym słowie „wyślij”, bez końcowego wyniku Safari.');
        }
        if (accepted) {
          abortedRetries = 0;
          if (rec.local && handsfree && !disposed && !document.hidden && acceptedEpoch === conversationEpoch) activateConversation();
        }
        return accepted;
      }
      function commit() {
        if (!live() || consumed || finalizer.hasPending() || !command.trim()) return;
        const confirmed = spokenConfirmation(finalizer.snapshotText()) || terminatedBody(command.trim());
        if (!confirmed || !confirmed.valid) { setStatus('Czekam na pełne polecenie zakończone słowem „wyślij”. Nic nie wysłano.'); return; }
        sendCommand(confirmed.body, false);
      }
      const finalizer = finalizerFor(rec, live,
        () => { clearTimer(silenceTimer); silenceTimer = null; },
        state => {
          const confirmed = spokenConfirmation(state.text);
          if (state.reason === 'no-final-timeout' && state.compatibilityAllowed &&
              state.stableMs >= 1800 && confirmed && confirmed.valid) {
            sendCommand(confirmed.body, true); return;
          }
          if (state.reason === 'no-final-timeout' && state.compatibilityAllowed) {
            discardCapture('Nie zatwierdzono wypowiedzi; nic nie wysłano. Czekam na nowe: „Maria, twoje polecenie, wyślij”.', 1200);
            return;
          }
          stopHandsfree(); auto = false; cancelAudio();
          diagnosticText('Brak końcowego tekstu. Podgląd jest wstępny; nic nie wysłano.');
          setStatus('Safari zwróciło słowa wstępne, ale bez końcowego tekstu. Nic nie wysłano. Włącz rozmowę i powiedz całe: „Maria, powiedz dzień dobry, wyślij”.');
        }, text => { const confirmed = spokenConfirmation(text); return !!confirmed && confirmed.valid === true; }, 2000);
      function discardCapture(message, delay) {
        command = ''; armed = false; clearTimer(armTimer); armTimer = null;
        pauseHandsfree();
        // Keep the local preview, but a new session must earn a fresh wake word.
        diagnosticSince = Date.now(); anyTranscript = finalTranscript = diagnosticHinted = false;
        diagnosticText('Poprzednia wypowiedź odrzucona. Nic nie wysłano.');
        setStatus(message); scheduleHandsfree(delay);
      }
      rec.onresult = event => {
        if (!live() || consumed) return;
        finalizer.update(event);
        previewResults(event);
        if (input.value.trim()) { stopHandsfree(); setStatus('Szkic zatrzymał rozmowę bez przycisków.'); return; }
        if (rec.local) {
          // Local STT returns one complete capture; wait for its explicit end
          // reason instead of the Safari chunk/confirmation timers.
          localSilenceResult = event.completionReason === 'silence';
          localResult = event.results.length === 1 && event.results[0].isFinal
            ? String(event.results[0][0].transcript || '').trim() : '';
          return;
        }
        let newFinal = false;
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (!event.results[i].isFinal || finals.has(i)) continue;
          const text = event.results[i][0].transcript.trim(); finals.set(i, text);
          if (!text) continue;
          newFinal = true; heard = true; rapidFailures = 0; networkErrors = 0;
          const wake = /(?:^|[\s,.!?])mari[ao](?=$|[\s,.!?:;\-])/i.exec(text);
          if (wake) {
            armed = true;
            clearTimer(armTimer);
            armTimer = window.setTimeout(() => { armed = false; armTimer = null; if (handsfree && !command) setStatus('Czekam ponownie na „Maria”.'); }, 12000);
            const tail = text.slice(wake.index + wake[0].length).replace(/^[\s,.!?:;\-]+/, '').trim();
            if (tail) command = [command, tail].filter(Boolean).join(' ');
          } else if (armed) command = [command, text].filter(Boolean).join(' ');
        }
        if (command) { clearTimer(armTimer); armTimer = null; }
        if (command && !finalizer.hasPending()) {
          if (newFinal || silenceTimer === null) {
            clearTimer(silenceTimer);
            silenceTimer = window.setTimeout(() => { silenceTimer = null; commit(); }, 900);
          }
          const confirmed = terminatedBody(command.trim());
          setStatus(confirmed && confirmed.valid ? 'Polecenie potwierdzone słowem „wyślij”.' : 'Czekam na pełne polecenie zakończone słowem „wyślij”.');
        } else if (armed && !finalizer.hasPending()) setStatus('Tak? Powiedz polecenie.');
        else if (heard && !armed && !finalizer.hasPending()) setStatus('Rozpoznano słowa. Zacznij polecenie od „Maria”, np. „Maria, powiedz dzień dobry”.');
        if (finalizer.isEnded() && !finalizer.hasPending()) {
          const confirmed = terminatedBody(command.trim());
          if (command && (!confirmed || !confirmed.valid)) discardCapture('Safari zakończyło wypowiedź bez pełnego potwierdzenia. Nic nie wysłano; zacznij ponownie od „Maria”.', 1200);
          else if (!command) restartAfterIdle();
        }
      };
      function restartAfterIdle() {
        // Silence after an established session is normal, not a microphone fault.
        const rapid = startedAt === null || Date.now() - startedAt < 2000;
        rapidFailures = rapid && !heard ? rapidFailures + 1 : 0;
        if (!finalTranscript && Date.now() - diagnosticSince >= 15000) { diagnosticHinted = true; diagnosticText(noTextDiagnostic()); setStatus(noTextHint()); }
        pauseHandsfree();
        if (rapidFailures >= 8) {
          stopHandsfree(); setStatus('Przeglądarka wielokrotnie szybko zakończyła nasłuch. Włącz rozmowę ponownie.'); return;
        }
        scheduleHandsfree(Math.min(3000, 1000 + rapidFailures * 250));
      }
      rec.onend = event => {
        if (!live() || consumed) return;
        clearTimer(captureTimer); captureTimer = null;
        if (rec.local) {
          // Idle renewal is neither a new utterance nor a rejection. Its time
          // was charged by pauseHandsfree and survives the next capture.
          if (!localResult) { pauseHandsfree(); setStatus(localListeningStatus(localConversationStatus())); scheduleHandsfree(1200); return; }
          const wakeBody = localWakeBody(localResult);
          let body = wakeBody === null && followupEligible ? localResult.trim() : wakeBody, reason = '';
          const oldConfirmation = body === null ? null : terminatedBody(body);
          if (!localSilenceResult || !event || event.completionReason !== 'silence') reason = 'Brak potwierdzonego zakończenia ciszą.';
          else if (body === null) reason = 'Wypowiedź musi zaczynać się od „Maria” lub „Mario”.';
          else if (body.length > 2000 && !(oldConfirmation && oldConfirmation.valid)) reason = 'Polecenie przekracza limit 2000 znaków.';
          else if (oldConfirmation && !oldConfirmation.valid) reason = 'Nieprawidłowe potwierdzenie słowem „wyślij”.';
          const controlBody = oldConfirmation && oldConfirmation.valid ? oldConfirmation.body : body;
          const closesConversation = typeof controlBody === 'string' && controlBody.replace(/\s+/g,' ').replace(/[.!?…]+$/,'').trim().toLowerCase() === 'koniec rozmowy';
          if (!reason && closesConversation) {
            consumed = true; clearConversation(); pauseHandsfree();
            if (transcriptPreview) transcriptPreview.textContent = 'Rozmowa zakończona — czuwam na „Maria”.';
            setStatus(localConversationStatus()); scheduleHandsfree(1200); return;
          }
          if (!reason && wakeBody === '') {
            consumed = true; activateConversation(); pauseHandsfree();
            if (transcriptPreview) transcriptPreview.textContent = 'Wezwanie przyjęte. Rozmowa aktywna; możesz mówić bez powtarzania imienia.';
            if (canSpeak && auto) speak('Tak, słucham.',false);
            else { setStatus(localConversationStatus()); scheduleHandsfree(1200); }
            return;
          }
          if (!reason) {
            if (oldConfirmation) body = oldConfirmation.body;
            sendCommand(body, false);
          } else {
            if (localResult) rejectLocal(reason,localResult);
            discardCapture(localListeningStatus(localConversationStatus()),1200);
          }
          return;
        }
        if (finalizer.end()) return;
        if (command) {
          const confirmed = terminatedBody(command.trim());
          if (!confirmed || !confirmed.valid) discardCapture('Safari zakończyło wypowiedź bez pełnego potwierdzenia. Nic nie wysłano; zacznij ponownie od „Maria”.', 1200);
          return; // silence timer owns a fully confirmed final commit
        }
        restartAfterIdle();
      };
      rec.onerror = event => {
        if (!live() || consumed) return;
        finalizer.disallowCompatibility();
        diagnosticText(errorText(event.error));
        if (event.error === 'no-speech') {
          if (finalizer.hasPending()) { finalizer.end(); return; }
          if (command) return;
          restartAfterIdle();
          return;
        }
        if (event.error === 'network' && ++networkErrors <= 2) {
          pauseHandsfree(); scheduleHandsfree(2000 * networkErrors); return;
        }
        if (event.error === 'aborted') {
          abortedRetries++;
          if (abortedRetries <= 2) {
            discardCapture('Safari przerwało nasłuch. Wznawiam; zacznij ponownie od „Maria”.', abortedRetries * 1000);
            return;
          }
          stopHandsfree(); auto = false; cancelAudio();
          setStatus('Safari trzykrotnie przerwało nasłuch. Rozmowa zatrzymana; włącz ją ponownie lub użyj „Mów”.'); return;
        }
        stopHandsfree(); auto = false; cancelAudio();
        setStatus(errorText(event.error) + ' Odśwież stronę, sprawdź „Mów” bez odczytu głosu i włącz rozmowę ponownie.');
      };
      attachDiagnostics(rec, live);
      if (rec.local) {
        const diagnosticSpeechStart = rec.onspeechstart;
        rec.onspeechstart = () => {
          if (!live()) return;
          if (diagnosticSpeechStart) diagnosticSpeechStart();
          pauseConversationBudget();
          followupEligible = conversationActive;
        };
      }
      bindSpeechEnd(rec, live, finalizer);
      if (!rec.local) captureTimer = window.setTimeout(() => { if (live()) { rec.onend(); if (live()) commit(); } }, 45000);
      try { rec.start(); } catch (_) { rec.onerror({error:'start-failed'}); }
    }
    const setStatus = text => { status.textContent = text; };
    function render() {
      mic.disabled = !canListen || busy;
      if (hfButton) {
        hfButton.disabled = !canListen || typeof options.sendText !== 'function' || (!handsfree && busy);
        hfButton.textContent = handsfree ? 'Wyłącz rozmowę' : 'Rozmowa: „Maria”';
        hfButton.setAttribute('aria-pressed', String(handsfree));
        hfButton.title = !canListen ? (localMode ? 'Wymaga HTTPS i dostępnego lokalnego rozpoznawania na miniPC.' : 'Wymaga HTTPS i rozpoznawania mowy.') :
          typeof options.sendText !== 'function' ? 'Odśwież stronę: potrzebna zgodna wersja czatu.' : '';
      }
      play.disabled = !canSpeak || !lastReply || busy;
      if (interrupt) interrupt.disabled = !utterance;
      toggle.disabled = !canSpeak;
      toggle.textContent = auto ? 'Wyłącz głos' : 'Włącz głos';
      toggle.setAttribute('aria-pressed', String(auto));
      mic.setAttribute('aria-pressed', String(!!recognition));
      stop.disabled = !recognition && !utterance && !auto && !handsfree;
      if (probeButton) {
        probeButton.disabled = !canProbe || busy;
        probeButton.textContent = micProbe ? 'Zakończ test mikrofonu' : 'Sprawdź mikrofon';
        probeButton.setAttribute('aria-pressed', String(!!micProbe));
        probeButton.title = canProbe ? 'Lokalny pomiar dźwięku przez 8 sekund; bez rozpoznawania.' : 'Test wymaga HTTPS i dostępu przeglądarki do mikrofonu.';
      }
      if (micProbe) stop.disabled = false;
    }
    function stopTracks(stream) {
      if (stream) stream.getTracks().forEach(track => { try { track.stop(); } catch (_) { /* already ended */ } });
    }
    function stopMicProbe() {
      probeGeneration++;
      const old = micProbe; micProbe = null;
      if (!old) return;
      clearTimer(old.timer); clearTimer(old.meterTimer);
      if (old.source) { try { old.source.disconnect(); } catch (_) { /* detached */ } }
      if (old.analyser) { try { old.analyser.disconnect(); } catch (_) { /* detached */ } }
      stopTracks(old.stream);
      if (old.context) { try { Promise.resolve(old.context.close()).catch(() => {}); } catch (_) { /* already closed */ } }
      render();
    }
    if (probeButton) probeButton.addEventListener('click', async () => {
      if (micProbe) { stopMicProbe(); setStatus('Test mikrofonu zatrzymany.'); return; }
      if (!canProbe || busy || disposed || document.hidden) return;
      stopHandsfree(); auto = false; cancelAudio();
      const token = ++probeGeneration;
      const probe = {stream:null, context:null, source:null, analyser:null, timer:null, meterTimer:null};
      micProbe = probe;
      const live = () => micProbe === probe && token === probeGeneration && !disposed && !document.hidden && !busy;
      function finish(message) { if (!live()) return; stopMicProbe(); setStatus(message); }
      setStatus('Test: czekam na zgodę i gotowość mikrofonu (do 20 sekund).');
      if (probeLevel) probeLevel.textContent = 'Jeszcze nie otwarto strumienia mikrofonu.';
      probe.timer = window.setTimeout(() => finish('Nie zakończono otwierania mikrofonu lub pomiaru. Test nie został ukończony; możesz spróbować ponownie.'), 20000);
      render();
      let pending;
      try {
        // Both calls begin within the explicit gesture. No STT or output speaker.
        pending = mediaDevices.getUserMedia({audio:true, video:false});
        if (AudioContext) {
          try {
            probe.context = new AudioContext();
            Promise.resolve(probe.context.resume()).catch(() => finish('Nie udało się uruchomić pomiaru dźwięku. Test nie został ukończony.'));
          } catch (_) { /* Still consume the permission promise and close its stream. */ }
        }
        const stream = await pending;
        if (!live()) { stopTracks(stream); return; }
        probe.stream = stream;
        if (probeLevel) probeLevel.textContent = 'Strumień mikrofonu otwarty; to jeszcze nie potwierdza dźwięku.';
        if (!probe.context) { finish('Mikrofon otwarty, ale pomiar poziomu niedostępny. Test nie został ukończony.'); return; }
        const tracks = stream.getAudioTracks ? stream.getAudioTracks() : stream.getTracks();
        if (!tracks.length) { finish('Nie otrzymano ścieżki mikrofonu. Test nie został ukończony.'); return; }
        tracks.forEach(track => { track.onended = () => finish('Strumień mikrofonu został zakończony. Test przerwany.'); });
        probe.source = probe.context.createMediaStreamSource(stream);
        probe.analyser = probe.context.createAnalyser(); probe.analyser.fftSize = 512;
        probe.source.connect(probe.analyser);
        const samples = new Uint8Array(probe.analyser.fftSize);
        let peak = 0, measured = false;
        function measure() {
          if (!live()) return;
          if (probe.context.state !== 'running') { finish('Pomiar dźwięku został wstrzymany. Test nie został ukończony.'); return; }
          try {
            probe.analyser.getByteTimeDomainData(samples);
            let sum = 0;
            for (let i = 0; i < samples.length; i++) { const v = (samples[i] - 128) / 128; sum += v * v; }
            const rms = Math.sqrt(sum / samples.length); peak = Math.max(peak, rms); measured = true;
            if (probeLevel) probeLevel.textContent = 'Poziom dźwięku: ' + Math.min(100, Math.round(rms * 1000)) + '/100 · najwyższy: ' + Math.min(100, Math.round(peak * 1000)) + '/100. Powiedz kilka słów.';
          } catch (_) { finish('Pomiar dźwięku nie powiódł się. Test nie został ukończony.'); return; }
          probe.meterTimer = window.setTimeout(measure, 100);
        }
        function startMeasurement() {
          if (!live()) return;
          if (probe.context.state !== 'running') {
            setStatus('Mikrofon otwarty; czekam na uruchomienie pomiaru (do 20 sekund od początku testu).');
            probe.meterTimer = window.setTimeout(startMeasurement, 100); return;
          }
          clearTimer(probe.timer);
          setStatus('Mikrofon otwarty. Powiedz kilka słów; pomiar potrwa 8 sekund.');
          probe.timer = window.setTimeout(() => {
            if (!measured) finish('Mikrofon otwarty, ale pomiar nie ruszył. Test nie został ukończony.');
            else finish(peak >= 0.01 ? 'Mikrofon odbiera dźwięk. To potwierdza sygnał w teście, nie działanie rozpoznawania Safari.' : 'Mikrofon otwarty, nie wykryłem dźwięku.');
          }, 8000);
          measure();
        }
        startMeasurement();
      } catch (error) {
        const name = error && error.name;
        finish(name === 'NotAllowedError' || name === 'SecurityError' ? 'Brak zgody na mikrofon. Test nie został ukończony.' :
          name === 'NotFoundError' ? 'Przeglądarka nie znalazła mikrofonu.' : 'Nie udało się otworzyć lub zmierzyć mikrofonu. Test nie został ukończony.');
      }
    });
    function cancelAudio() {
      if (startupUtterance || preparingConversation) { startupUtterance = null; stopHandsfree(); auto = false; }
      stopMicProbe();
      if (interruptTimer !== null) window.clearTimeout(interruptTimer);
      interruptTimer = null;
      generation++; clearDiagnosticTimer(); clearFinalizer();
      if (timer) window.clearTimeout(timer);
      timer = null;
      const old = recognition;
      recognition = null;
      if (old) { try { old.abort(); } catch (_) { /* already stopped */ } }
      const audioWasActive = !!utterance || !!(synth && (synth.speaking || synth.pending));
      utterance = null;
      if (canSpeak && audioWasActive) synth.cancel();
      render();
    }
    if (interrupt) interrupt.addEventListener('click', () => {
      if (!utterance || disposed) return;
      cancelAudio();
      setStatus('Odczyt przerwany. Czekam na zwolnienie dźwięku…');
      const token = generation, started = Date.now();
      function resume() {
        interruptTimer = null;
        if (token !== generation || disposed || document.hidden || busy) return;
        if (synth.speaking || synth.pending) {
          if (Date.now() - started >= 5000) {
            stopHandsfree(); auto = false; render();
            setStatus('Odtwarzanie nie zwolniło dźwięku. Rozmowa zatrzymana; włącz ją ponownie.'); return;
          }
          interruptTimer = window.setTimeout(resume,200); return;
        }
        setStatus(handsfree ? 'Odczyt przerwany. Wracam do nasłuchu.' : 'Odczyt przerwany.');
        scheduleHandsfree(0);
      }
      interruptTimer = window.setTimeout(resume,1200);
    });
    function speak(text, enabling, fragment = false, conversationStart = false) {
      armed = false; clearTimer(armTimer); armTimer = null;
      pauseHandsfree();
      cancelAudio();
      if (!canSpeak || disposed || document.hidden) return;
      const token = generation;
      let began = false;
      const item = new window.SpeechSynthesisUtterance(speechText(text));
      item.lang = 'pl-PL';
      const voices = synth.getVoices();
      const polish = voices.find(v => /^pl(?:-|$)/i.test(v.lang));
      if (polish) item.voice = polish;
      utterance = item;
      if (conversationStart) startupUtterance = item;
      setStatus('Czekam na rozpoczęcie odczytu…');
      timer = window.setTimeout(() => {
        if (token !== generation || utterance !== item) return;
        auto = false;
        stopHandsfree(); cancelAudio();
        setStatus(conversationStart ? 'Nie rozpoczął się głos powitalny. Rozmowa zatrzymana; kliknij „Rozmowa: Maria” ponownie lub napisz wiadomość.' : 'Safari nie rozpoczęło odczytu. Kliknij „Odsłuchaj”.');
      }, 8000);
      item.onstart = () => {
        if (token !== generation || utterance !== item) return;
        window.clearTimeout(timer); timer = null;
        began = true;
        if (enabling) auto = true;
        if (conversationStart) timer = window.setTimeout(() => {
          if (token === generation && utterance === item) item.onerror();
        },12000);
        setStatus(enabling ? 'Głos włączony. Czytam nowe odpowiedzi.' : fragment ? 'Czytam tylko początek. Pełna odpowiedź jest w czacie.' : 'Czytam odpowiedź…');
        render();
      };
      item.onend = () => {
        if (token !== generation || utterance !== item) return;
        if (startupUtterance === item && !began) { item.onerror(); return; }
        if (startupUtterance === item) startupUtterance = null;
        window.clearTimeout(timer); timer = null; utterance = null;
        setStatus(auto ? 'Głos włączony. Gotowa na kolejną wiadomość.' : 'Odczyt zakończony.');
        render();
        scheduleHandsfree(1200);
      };
      item.onerror = () => {
        if (token !== generation || utterance !== item) return;
        auto = false; stopHandsfree(); cancelAudio();
        setStatus(conversationStart ? 'Nie udało się zakończyć włączenia głosu. Rozmowa zatrzymana; kliknij „Rozmowa: Maria” ponownie lub napisz wiadomość.' : 'Odczyt niedostępny. Spróbuj przycisku „Odsłuchaj”.');
      };
      try { synth.speak(item); } catch (_) { item.onerror(); }
      render();
    }
    mic.addEventListener('click', () => {
      if (!canListen || busy || disposed) return;
      stopHandsfree(); cancelAudio();
      const token = generation;
      const initial = input.value;
      let finalText = '', writtenDraft = initial;
      const manualFinals = new Map();
      let rec;
      try { rec = new Recognition(); } catch (_) {
        setStatus('Rozpoznawanie mowy niedostępne. Użyj mikrofonu klawiatury.');
        return;
      }
      recognition = rec;
      beginDiagnostics();
      const live = () => token === generation && recognition === rec && !disposed && !document.hidden;
      attachDiagnostics(rec, live);
      const finalizer = finalizerFor(rec, live, () => {}, () => {
        cancelAudio(); diagnosticText('Brak końcowego tekstu. Podgląd pozostaje lokalny; nic nie wysłano.');
        setStatus(noTextHint());
      });
      bindSpeechEnd(rec, live, finalizer);
      rec.lang = 'pl-PL'; rec.continuous = false; rec.interimResults = true;
      setStatus('Czekam na zgodę na mikrofon…');
      if (!rec.local) timer = window.setTimeout(() => {
        if (token !== generation || recognition !== rec) return;
        timer = null;
        if (finalizer.hasPending()) { finalizer.request(); return; }
        cancelAudio();
        setStatus(finalText.trim() ? 'Nasłuch zakończony po 30 sekundach. Sprawdź tekst.' : noTextHint());
      }, 30000);
      rec.onstart = () => {
        if (live()) { diagnosticText(localMode ? 'Nagrywanie dla miniPC rozpoczęte.' : 'Safari rozpoczęło rozpoznawanie. Czekam na słowa.'); setStatus('Rozpoznawanie uruchomione. Powiedz wiadomość i sprawdź podgląd słów.'); }
      };
      rec.onresult = event => {
        if (token !== generation || recognition !== rec || document.hidden) return;
        finalizer.update(event);
        previewResults(event);
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal && !manualFinals.has(i)) manualFinals.set(i, event.results[i][0].transcript);
        }
        finalText = [...manualFinals.values()].join(' ');
        if (finalText.trim() && input.value === writtenDraft) {
          input.value = [initial.trim(), finalText.trim()].filter(Boolean).join(' '); writtenDraft = input.value;
        }
        if (finalizer.isEnded() && !finalizer.hasPending()) rec.onend();
      };
      rec.onerror = event => {
        if (token !== generation || recognition !== rec) return;
        finalizer.disallowCompatibility();
        if (event.error === 'no-speech' && finalizer.hasPending()) { finalizer.request(); return; }
        window.clearTimeout(timer); timer = null;
        clearFinalizer(); recognition = null; generation++;
        try { rec.abort(); } catch (_) { /* inactive */ }
        clearDiagnosticTimer(); diagnosticText(errorText(event.error));
        setStatus(errorText(event.error) + ' Odśwież stronę lub użyj mikrofonu klawiatury iPhone’a.');
        render();
      };
      rec.onend = () => {
        if (token !== generation || recognition !== rec) return;
        if (finalizer.end()) { window.clearTimeout(timer); timer = null; return; }
        window.clearTimeout(timer); timer = null;
        recognition = null; clearDiagnosticTimer(); clearFinalizer();
        if (!finalText.trim()) diagnosticText(noTextDiagnostic());
        setStatus(finalText.trim() ? 'Sprawdź tekst i kliknij „Wyślij”.' : noTextHint());
        render();
      };
      try { rec.start(); } catch (_) { rec.onerror({ error: 'start-failed' }); }
      render();
    });
    if (hfButton) hfButton.addEventListener('click', () => {
      if (handsfree) { stopHandsfree(); auto = false; cancelAudio(); setStatus('Rozmowa bez przycisków wyłączona.'); return; }
      if (!canListen || typeof options.sendText !== 'function' || busy || disposed || document.hidden) return;
      if (input.value.trim()) { setStatus('Najpierw wyślij lub usuń szkic wiadomości.'); return; }
      cancelAudio(); handsfree = true; armed = false; waitingForReply = false; rapidFailures = networkErrors = abortedRetries = 0;
      auto = false; beginDiagnostics(); render();
      if (!canSpeak) { listenHandsfree(); return; }
      let preparation;
      if (localMode) {
        try {
          if (!localSTT || typeof localSTT.prepareContext !== 'function') throw new Error('old-helper');
          // This call and synth.speak below both run in the original click.
          preparation = localSTT.prepareContext();
        } catch (_) {
          stopHandsfree(); cancelAudio();
          setStatus('Nie udało się przygotować dźwięku. Rozmowa zatrzymana; odśwież stronę i włącz ją ponownie.'); return;
        }
      }
      speak('Rozmowa włączona.', true, false, true);
      if (preparation && handsfree) {
        preparingConversation = true;
        const token = hfGeneration;
        const live = () => handsfree && preparingConversation && token === hfGeneration && !disposed && !document.hidden;
        const failed = () => {
          if (!live()) return;
          stopHandsfree(); auto = false; cancelAudio();
          setStatus('Nie udało się przygotować dźwięku na telefonie. Rozmowa zatrzymana; włącz ją ponownie.');
        };
        prepareTimer = window.setTimeout(failed,8000);
        Promise.resolve(preparation).then(() => {
          if (!live()) return;
          preparingConversation = false; clearTimer(prepareTimer); prepareTimer = null;
          scheduleHandsfree(1200);
        },failed);
      } else if (preparation) { Promise.resolve(preparation).catch(() => {}); }
    });
    toggle.addEventListener('click', () => {
      if (auto || utterance) {
        stopHandsfree(); auto = false; cancelAudio(); setStatus('Automatyczny głos i rozmowa bez przycisków wyłączone.');
      } else speak('Głos Marii włączony.', true);
    });
    play.addEventListener('click', () => { if (lastReply && !busy) speak(lastReply, false); });
    stop.addEventListener('click', () => {
      stopHandsfree(); auto = false; cancelAudio(); setStatus('Głos i mikrofon zatrzymane.');
    });
    function hide() {
      if (document.hidden) {
        stopHandsfree(); auto = false; cancelAudio(); setStatus('Głos zatrzymany po ukryciu strony. Włącz ponownie, gdy wrócisz.');
      }
    }
    document.addEventListener('visibilitychange', hide);
    window.addEventListener('pagehide', () => { stopHandsfree(); auto = false; cancelAudio(); });
    if (!canSpeak && !canListen) setStatus('Głos przeglądarki niedostępny. Napisz lub użyj mikrofonu klawiatury iPhone’a.');
    else if (!canSpeak) setStatus('Odsłuch niedostępny w tej przeglądarce. Możesz podyktować tekst przyciskiem „Mów”.');
    else if (!canListen) setStatus('Użyj mikrofonu klawiatury iPhone’a. Przycisk „Mów” wymaga HTTPS i obsługi Safari.');
    else setStatus('Kliknij „Mów” lub użyj mikrofonu klawiatury. Sprawdź tekst przed wysłaniem.');
    render();
    if (localMode) {
      setStatus('Sprawdzam dostępność rozpoznawania na miniPC…');
      (localSTT ? localSTT.ready : Promise.resolve({available:false})).then(state => {
        if (disposed) return;
        canListen = state.available === true && window.isSecureContext === true;
        Recognition = canListen ? localSTT.Recognition : null;
        if (confirmationNote) confirmationNote.textContent = canListen ? 'Rozpoznawanie na miniPC. Powiedz „Maria” raz; kolejne wypowiedzi wysyłają się po około 4 sekundach ciszy, bez powtarzania imienia. Po 3 minutach bezczynnego nasłuchu wracam do czuwania. „Koniec rozmowy” przywraca czuwanie. Strona musi być widoczna; krótkie audio (do 30 s) jest przesyłane do miniPC.' : 'Lokalne rozpoznawanie niedostępne. Nie przełączam na usługę Apple. Możesz użyć Sprawdź mikrofon lub napisać.';
        if (!busy && !document.hidden && !micProbe && !recognition && !hfRec && !utterance && !handsfree) setStatus(canListen ? 'Rozpoznawanie na miniPC gotowe. Wybierz „Mów” lub „Rozmowa: Maria”.' : 'Rozpoznawanie na miniPC niedostępne. Sprawdź połączenie i konfigurację lokalnego STT.');
        render();
      });
    }
    return {
      hydrate(text) { lastReply = typeof text === 'string' ? text.trim() : ''; render(); },
      pending() { if (!disposed && !document.hidden) setStatus('Polecenie wysłane. Czekam na odpowiedź Marii…'); },
      setBusy(value) { busy = !!value; if (busy) { stopMicProbe(); armed = false; clearTimer(armTimer); armTimer = null; pauseHandsfree(); if (startupUtterance || !utterance) cancelAudio(); } else scheduleHandsfree(1200); render(); },
      response(text, metadata) {
        if (metadata && (metadata.fallback || metadata.rate_limited || metadata.success === false)) { stopHandsfree(); auto = false; }
        waitingForReply = false;
        lastReply = typeof text === 'string' ? text.trim() : '';
        render();
        if (auto && lastReply && !document.hidden) {
          const spoken = automaticSpeech(lastReply);
          speak(spoken.text, false, spoken.fragment);
        }
      },
      failure(reason) { stopHandsfree(); auto = false; cancelAudio(); setStatus(reason || 'Rozmowa zatrzymana po błędzie. Włącz ją ponownie.'); },
      clear() { stopHandsfree(); lastReply = ''; cancelAudio(); render(); },
      disconnect(reason) {
        connectionLost = true;
        stopHandsfree(); auto = false; cancelAudio();
        const detail = reason === 'ping timeout' ? 'Brak połączenia — upłynął czas oczekiwania na serwer.' :
          reason === 'transport close' || reason === 'transport error' ? 'Brak połączenia — kanał rozmowy został przerwany.' : 'Brak połączenia.';
        setStatus(detail + ' Rozmowa została zatrzymana.');
      },
      connected(state) {
        if (!connectionLost || disposed) return;
        connectionLost = false;
        setStatus(state && state.pendingReply ?
          'Połączenie przywrócone, ale wynik poprzedniej wiadomości jest niepewny. Sprawdź historię i odśwież stronę przed kolejną wiadomością.' :
          'Połączenie przywrócone. Włącz „Rozmowa: Maria”, aby znów rozmawiać.');
        render();
      },
      dispose() { disposed = true; stopHandsfree(); auto = false; cancelAudio(); document.removeEventListener('visibilitychange', hide); }
    };
  };
})();
