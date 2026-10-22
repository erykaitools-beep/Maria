/**
 * M.A.R.I.A. Chat Page v2
 */

(function() {
  const M = MariaUI;
  const socket = M.getSocket();

  const chatMessages = M.$('chatMessages');
  const chatInput = M.$('chatInput');
  const sendBtn = M.$('sendBtn');
  const clearBtn = M.$('clearBtn');
  const voice = window.MariaChatVoice ? window.MariaChatVoice(chatInput, {
    sendText: text => sendMessage(text)
  }) : null;
  // Voice creates its optional controls synchronously. Relocate the actual nodes
  // afterwards so IDs, listeners, state and microphone lifecycle stay intact.
  enhanceVoiceLayout();
  function enhanceVoiceLayout() {
    const status = M.$('voiceStatus');
    const panel = status && status.parentNode;
    if (!panel || typeof panel.querySelectorAll !== 'function' || M.$('voiceOptions')) return;
    const mic = M.$('voiceMic');
    const primary = mic && mic.parentNode;
    if (!primary) return;
    const details = document.createElement('details');
    details.id = 'voiceOptions'; details.className = 'mo-voice-options';
    const summary = document.createElement('summary');
    summary.textContent = 'Opcje głosu i mikrofonu';
    const body = document.createElement('div'); body.className = 'mo-voice-options__body';
    const secondary = document.createElement('div'); secondary.className = 'mo-voice-options__controls';
    ['voiceToggle', 'voicePlay', 'voiceMicTest', 'voiceInterrupt'].forEach(id => {
      const button = M.$(id); if (button) secondary.appendChild(button);
    });
    body.appendChild(secondary);
    Array.from(panel.querySelectorAll('.mo-voice-note, .mo-voice-diagnostic')).forEach(node => body.appendChild(node));
    details.appendChild(summary); details.appendChild(body); panel.appendChild(details);
    // Primary order is explicit even when a voice capability is unavailable.
    ['voiceMic', 'voiceHandsfree', 'voiceStop'].forEach(id => {
      const button = M.$(id); if (button) primary.appendChild(button);
    });
  }
  let isConnected = !!socket.connected;

  const pendingStorageKey = 'maria.chat.pending.v1';
  let pendingTurn = null;
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(pendingStorageKey) || 'null');
    if (saved && typeof saved.request_id === 'string' && /^[a-f0-9-]{32,36}$/i.test(saved.request_id)) pendingTurn = {request_id:saved.request_id};
  } catch (_) { /* No automatic retry when storage is inaccessible or malformed. */ }
  let isThinking = !!pendingTurn;
  let projectSelectionBusy = false;
  let isRateLimited = false;
  let rateLimitTimer = null;
  let replyTimer = null;
  let reconcileTimer = null, reconcileBusy = false, reconcileAttempts = 0;
  let historyEpoch = 0;
  const finishedIds = new Set();

  function forgetPending() {
    pendingTurn = null; reconcileAttempts = 0;
    if (reconcileTimer !== null) window.clearTimeout(reconcileTimer);
    reconcileTimer = null;
    try { window.sessionStorage.removeItem(pendingStorageKey); } catch (_) { /* no resend */ }
    const notice = M.$('chatPendingNotice'); if (notice) notice.hidden = true;
  }
  function uncertainTurn() {
    const notice = M.$('chatPendingNotice'); if (notice) notice.hidden = false;
    if (voice && voice.failure) voice.failure('Wynik wiadomości jest niepewny. Sprawdź historię i karty zadań; odśwież widok, jeśli wynik nadal się nie pojawia. Nie ponawiam polecenia.');
  }
  async function reconcilePending() {
    if (!pendingTurn || reconcileBusy || document.hidden || !isConnected || reconcileAttempts >= 40) return;
    if (reconcileTimer !== null) window.clearTimeout(reconcileTimer); reconcileTimer = null;
    const id = pendingTurn.request_id; reconcileBusy = true; ++reconcileAttempts;
    try {
      const data = await M.apiFetch('/api/chat/turn/' + encodeURIComponent(id));
      if (!pendingTurn || pendingTurn.request_id !== id || document.hidden) return;
      if (data && data.request_id === id && data.state === 'completed') {
        if (data.response && typeof data.response === 'object') receiveResponse({...data.response,request_id:id},true);
        else {
          forgetPending(); isThinking = false;
          if (voice && voice.failure) voice.failure('Wiadomość zakończona. Sprawdź zapisaną historię; włącz rozmowę, aby kontynuować.');
          updateSendButton(); await loadChatHistory();
        }
      } else if (!data || data.state !== 'pending') uncertainTurn();
    } catch (_) { uncertainTurn(); }
    finally {
      reconcileBusy = false;
      if (pendingTurn && !document.hidden && isConnected && reconcileAttempts < 40) reconcileTimer = window.setTimeout(reconcilePending,3000);
      else if (pendingTurn && reconcileAttempts >= 40) uncertainTurn();
    }
  }

  function clearReplyTimer() {
    if (replyTimer !== null) window.clearTimeout(replyTimer);
    replyTimer = null;
  }

  // --- Socket events ---

  socket.on('connect', () => {
    console.log('[Chat] Connected');
    isConnected = true;
    updateSendButton();
    if (voice && voice.connected) voice.connected({pendingReply:isThinking});
    loadChatHistory();
    reconcileAttempts = 0; reconcilePending();
  });

  socket.on('connected', (data) => {
    updateBackendBadge(data.chat_backend);
    if (!data.chat_backend && !data.ollama_available) {
      addMessage('system', 'Ollama nie jest dostepna. Chat moze nie dzialac.');
    }
  });

  socket.on('disconnect', (reason) => {
    clearReplyTimer();
    if (reconcileTimer !== null) window.clearTimeout(reconcileTimer); reconcileTimer = null;
    isConnected = false;
    updateSendButton();
    if (voice) voice.disconnect(reason);
    addMessage('error', 'Utracono polaczenie z serwerem.');
  });

  socket.on('chat_status', (data) => {
    if (data.status === 'thinking') { showTypingIndicator(); if (voice && voice.pending) voice.pending(); }
    if (data.status === 'learning_detected') {
      if (data.action === 'already_active') {
        addMessage('system', 'Juz sie ucze o: ' + data.topic);
      } else {
        const action = data.action === 'fetch' ? 'Szukam materialow' : 'Zaczynam nauke';
        addMessage('system', action + ': ' + data.topic);
      }
    }
    if (data.status === 'learning_cancelled') {
      addMessage('system', 'Anulowano nauke: ' + (data.topic || ''));
    }
    if (data.status === 'learning_cancel_notfound') {
      addMessage('system', 'Nie znalazlam aktywnego celu nauki: ' + (data.topic || ''));
    }
    if (data.status === 'operational_command') {
      var labels = {
        fetch: 'Pobieram nowe materialy',
        evaluate: 'Uruchamiam ewaluacje',
        critique: 'Uruchamiam krytyke wiedzy',
        self_analyze: 'Uruchamiam autoanalize',
        creative: 'Uruchamiam refleksje kreatywna',
        validate: 'Uruchamiam walidacje krzyzowa',
        exam: 'Uruchamiam egzamin'
      };
      var msg = labels[data.action] || ('Wykonuje: ' + data.action);
      if (data.topic) msg += ': ' + data.topic;
      addMessage('system', msg);
    }
  });

  function receiveResponse(data, recovered = false) {
    if (!data || typeof data !== 'object') return;
    if (data.request_id && finishedIds.has(data.request_id)) return;
    if (pendingTurn && data.request_id !== pendingTurn.request_id) return;
    // A correlated reply from another page/turn must never clear this page's busy state.
    if (!pendingTurn && data.request_id) return;
    recovered = recovered || data.replayed === true;
    ++historyEpoch;
    clearReplyTimer();
    hideTypingIndicator();

    if (data.rate_limited) {
      if (voice && voice.failure) voice.failure('Limit wiadomości. Rozmowa bez klikania zatrzymana.');
      showRateLimitWarning(data.wait_seconds);
    } else if (data.success) {
      addMessage('maria', data.message);
      if (voice) {
        if (data.fallback || data.timeout) {
          if (voice.failure) voice.failure('Odpowiedź modelu jest niedostępna. Sprawdź komunikat w czacie.');
        } else if (recovered) { if (voice.hydrate) voice.hydrate(data.message); }
        else voice.response(data.message, data);
      }
    } else {
      addMessage('error', data.error || 'Nieznany blad');
      if (voice && voice.failure) voice.failure('Wiadomość zakończyła się błędem. Rozmowa bez klikania zatrzymana.');
    }
    // Deliver the terminal result before allowing the microphone to resume.
    if (data.request_id) {
      finishedIds.add(data.request_id);
      while (finishedIds.size > 128) finishedIds.delete(finishedIds.values().next().value);
    }
    forgetPending();
    isThinking = false;
    updateSendButton();
    if (recovered) { if (voice && voice.failure) voice.failure('Odzyskano wynik wiadomości. Pełna odpowiedź jest w czacie. Włącz rozmowę, aby kontynuować.'); loadChatHistory(); }
  }
  socket.on('chat_response', receiveResponse);
  socket.on('chat_ack', data => {
    if (!pendingTurn || !data || data.request_id !== pendingTurn.request_id) return;
    if (data.state === 'unknown') uncertainTurn();
    if (data.state === 'completed') reconcilePending();
  });

  socket.on('history_cleared', (data) => {
    if (data.success) {
      chatMessages.innerHTML = '';
      if (voice) voice.clear();
      addMessage('system', 'Historia rozmowy wyczyszczona.');
    }
  });


  // --- Chat history ---

  async function loadChatHistory() {
    const epoch = ++historyEpoch;
    const data = await M.apiFetch('/api/chat/history');
    if (epoch !== historyEpoch) return;
    if (data && data.messages && data.messages.length > 0) {
      chatMessages.innerHTML = '';
      let lastMessage = null;
      data.messages.forEach(msg => { lastMessage = addMessage(msg.role, msg.content, false); });
      const reply = data.messages.filter(msg => msg.role === 'maria').pop();
      if (voice && voice.hydrate && reply) voice.hydrate(reply.content);
      if (lastMessage) scrollToMessage(lastMessage, data.messages[data.messages.length - 1].role);
    }
  }


  // --- Message rendering ---

  function scrollToMessage(msg, type) {
    if (type === 'maria' && typeof msg.getBoundingClientRect === 'function' && typeof chatMessages.getBoundingClientRect === 'function') {
      // Keep the start of a long answer visible; scrolling the whole page would
      // hide the voice controls or steal position from the outer mobile page.
      const offset = msg.getBoundingClientRect().top - chatMessages.getBoundingClientRect().top;
      chatMessages.scrollTop = Math.max(0, chatMessages.scrollTop + offset);
    } else chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function addMessage(type, text, scroll = true) {
    const classMap = {
      'user': 'mo-msg--user',
      'maria': 'mo-msg--maria',
      'system': 'mo-msg--system',
      'error': 'mo-msg--error',
    };
    const msg = document.createElement('div');
    msg.className = 'mo-msg ' + (classMap[type] || 'mo-msg--system');
    msg.textContent = text;
    chatMessages.appendChild(msg);
    if (scroll) scrollToMessage(msg, type);
    return msg;
  }

  function showTypingIndicator() {
    hideTypingIndicator();
    const indicator = document.createElement('div');
    indicator.className = 'mo-typing';
    indicator.id = 'typingIndicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    chatMessages.appendChild(indicator);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function hideTypingIndicator() {
    const el = M.$('typingIndicator');
    if (el) el.remove();
  }

  function updateSendButton() {
    sendBtn.disabled = isThinking || isRateLimited || !isConnected || projectSelectionBusy;
    clearBtn.disabled = isThinking || !isConnected;
    if (voice) voice.setBusy(isThinking || isRateLimited || !isConnected || projectSelectionBusy);
  }


  // --- Rate limiting ---

  function showRateLimitWarning(seconds) {
    isRateLimited = true;
    updateSendButton();

    const warning = M.$('rateLimitWarning');
    const waitEl = M.$('waitTime');
    warning.style.display = 'block';
    waitEl.textContent = seconds;

    if (rateLimitTimer) clearInterval(rateLimitTimer);
    rateLimitTimer = setInterval(() => {
      seconds--;
      waitEl.textContent = seconds;
      if (seconds <= 0) {
        clearInterval(rateLimitTimer);
        warning.style.display = 'none';
        isRateLimited = false;
        updateSendButton();
      }
    }, 1000);
  }


  // --- Send ---

  function sendMessage(textOverride) {
    const automatic = typeof textOverride === 'string';
    // A voice turn must never replace an unfinished keyboard message.
    if (automatic && (chatInput.value.trim() || document.hidden)) return false;
    const message = (automatic ? textOverride : chatInput.value).trim();
    if (!message || message.length > 2000 || isThinking || isRateLimited || projectSelectionBusy || !isConnected || !socket.connected) return false;
    let request_id;
    try {
      request_id = window.crypto.randomUUID();
      window.sessionStorage.setItem(pendingStorageKey,JSON.stringify({request_id}));
    } catch (_) {
      addMessage('error','Nie mogę zapisać identyfikatora wiadomości w tej karcie. Włącz pamięć sesji przeglądarki przed wysłaniem.'); return false;
    }
    ++historyEpoch;
    pendingTurn = {request_id}; reconcileAttempts = 0;
    addMessage('user', message);
    chatInput.value = '';
    isThinking = true;
    updateSendButton();
    if (voice && voice.pending) voice.pending();
    clearReplyTimer();
    replyTimer = window.setTimeout(() => {
      replyTimer = null;
      if (!isThinking) return;
      uncertainTurn();
      if (voice && voice.failure) voice.failure('Brak potwierdzenia odpowiedzi. Sprawdź czat przed następną wiadomością.');
      addMessage('error', 'Odpowiedź nie dotarła na czas. Wiadomość mogła zostać wykonana. Nie ponawiam jej automatycznie; zaczekaj na odpowiedź lub odśwież stronę i sprawdź historię.');
      // Keep the turn busy: retrying an unknown outcome could duplicate work.
    }, 130000);
    try {
      socket.emit('chat_message', { message: message, request_id });
    } catch (_) {
      clearReplyTimer();
      if (voice && voice.failure) voice.failure('Nie udało się potwierdzić wysłania. Sprawdź połączenie i historię rozmowy.');
      addMessage('error', 'Nie udało się potwierdzić wysłania wiadomości. Sprawdź połączenie i historię przed ponowieniem.');
      return false;
    }
    return true;
  }

  sendBtn.addEventListener('click', sendMessage);
  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); sendMessage(); }
  });
  clearBtn.addEventListener('click', () => {
    if (isThinking || !isConnected || !socket.connected) return;
    socket.emit('clear_history');
  });
  const continueBtn = M.$('chatContinue');
  if (continueBtn) continueBtn.addEventListener('click', () => {
    if (!pendingTurn) return;
    clearReplyTimer(); forgetPending(); isThinking = false; updateSendButton();
    if (voice && voice.failure) voice.failure('Możesz napisać nową wiadomość. Poprzednie zlecenie mogło zostać wykonane — sprawdź karty zadań.');
  });


  // --- Status polling for topbar ---

  function updateBackendBadge(backend) {
    if (!backend || typeof backend !== 'object') return;
    const badge = M.$('chatModelBadge');
    if (!badge) return;
    const provider = backend.provider === 'codex' ? 'Codex' :
      backend.provider === 'ollama' ? 'Ollama' : String(backend.provider || 'Chat');
    badge.textContent = provider + (backend.model ? ' · ' + backend.model : '') +
      (backend.configured === false ? ' · nie skonfigurowano' : '');
    badge.className = 'mo-badge ' + (backend.configured === false ? 'mo-badge--warn' : 'mo-badge--accent');
  }

  async function pollStatus() {
    const data = await M.apiFetch('/api/status');
    if (data) {
      M.updateTopbarStatus(data.mode, data.health_score);
      updateBackendBadge(data.chat_backend);
    }
  }

  // Focus input
  updateSendButton();
  if (pendingTurn) { uncertainTurn(); reconcilePending(); }
  if (window.MariaChatWork) window.MariaChatWork(M,{selectionBusy(value){projectSelectionBusy=!!value;updateSendButton();}});
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { if (reconcileTimer !== null) window.clearTimeout(reconcileTimer); reconcileTimer = null; }
    else if (pendingTurn) { reconcileAttempts = 0; reconcilePending(); }
  });
  if (!window.matchMedia || !window.matchMedia('(pointer: coarse)').matches) chatInput.focus();
  M.createPoller(pollStatus, 5000);

})();
