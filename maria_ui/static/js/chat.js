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

  let isThinking = false;
  let isRateLimited = false;
  let rateLimitTimer = null;

  // --- Socket events ---

  socket.on('connect', () => {
    console.log('[Chat] Connected');
    loadChatHistory();
  });

  socket.on('connected', (data) => {
    if (!data.ollama_available) {
      addMessage('system', 'Ollama nie jest dostepna. Chat moze nie dzialac.');
    }
  });

  socket.on('disconnect', () => {
    addMessage('error', 'Utracono polaczenie z serwerem.');
  });

  socket.on('chat_status', (data) => {
    if (data.status === 'thinking') showTypingIndicator();
  });

  socket.on('chat_response', (data) => {
    hideTypingIndicator();
    isThinking = false;
    updateSendButton();

    if (data.rate_limited) {
      showRateLimitWarning(data.wait_seconds);
    } else if (data.success) {
      addMessage('maria', data.message);
    } else {
      addMessage('error', data.error || 'Nieznany blad');
    }
  });

  socket.on('history_cleared', (data) => {
    if (data.success) {
      chatMessages.innerHTML = '';
      addMessage('system', 'Historia rozmowy wyczyszczona.');
    }
  });


  // --- Chat history ---

  async function loadChatHistory() {
    const data = await M.apiFetch('/api/chat/history');
    if (data && data.messages && data.messages.length > 0) {
      chatMessages.innerHTML = '';
      data.messages.forEach(msg => addMessage(msg.role, msg.content));
    }
  }


  // --- Message rendering ---

  function addMessage(type, text) {
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
    chatMessages.scrollTop = chatMessages.scrollHeight;
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
    sendBtn.disabled = isThinking || isRateLimited;
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

  function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || isThinking) return;
    addMessage('user', message);
    chatInput.value = '';
    isThinking = true;
    updateSendButton();
    socket.emit('chat_message', { message: message });
  }

  sendBtn.addEventListener('click', sendMessage);
  chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
  clearBtn.addEventListener('click', () => {
    socket.emit('clear_history');
  });


  // --- Status polling for topbar ---

  async function pollStatus() {
    const data = await M.apiFetch('/api/status');
    if (data) {
      M.updateTopbarStatus(data.mode, data.health_score);
      // Update model badge
      const modelEl = M.$('chatModelBadge');
      if (modelEl) {
        modelEl.textContent = data.ollama_connected ? 'llama3.1:8b' : 'OFFLINE';
        modelEl.className = 'mo-badge ' + (data.ollama_connected ? 'mo-badge--accent' : 'mo-badge--error');
      }
    }
  }

  // Focus input
  chatInput.focus();
  pollStatus();
  setInterval(pollStatus, 5000);

})();
