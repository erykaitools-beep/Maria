/**
 * Task Pipeline - Web UI page
 * Submit, track, and review Claude/Codex tasks.
 */

let _currentFilter = '';
let _refreshTimer = null;

// Tab switching
document.querySelectorAll('.mo-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.mo-tab').forEach(t => t.classList.remove('mo-tab--active'));
    document.querySelectorAll('.mo-tab-content').forEach(c => c.classList.remove('mo-tab-content--active'));
    tab.classList.add('mo-tab--active');
    const target = document.getElementById(tab.dataset.tab);
    if (target) target.classList.add('mo-tab-content--active');
  });
});

// -- Submit --

function submitTask(backend) {
  const input = document.getElementById('task-input');
  const text = (input.value || '').trim();
  if (text.length < 5) {
    showToast('Zadanie za krotkie (min 5 znakow)', 'warn');
    return;
  }

  const btnClaude = document.getElementById('btn-claude');
  const btnCodex = document.getElementById('btn-codex');
  const status = document.getElementById('submit-status');

  btnClaude.disabled = true;
  btnCodex.disabled = true;
  status.textContent = 'Wysylanie...';

  fetch('/api/tasks', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({task_text: text, backend: backend}),
  })
    .then(r => r.json().then(data => ({ok: r.ok, data})))
    .then(({ok, data}) => {
      btnClaude.disabled = false;
      btnCodex.disabled = false;
      if (ok && data.task_id) {
        status.textContent = 'Przyjeto: ' + data.task_id;
        input.value = '';
        showToast('Task zlecony (' + backend + '): ' + data.task_id, 'ok');
        startAutoRefresh();
        loadTasks();
      } else {
        status.textContent = data.error || 'Blad';
        showToast(data.error || 'Blad wysylania', 'error');
      }
    })
    .catch(() => {
      btnClaude.disabled = false;
      btnCodex.disabled = false;
      status.textContent = 'Blad sieci';
      showToast('Blad polaczenia', 'error');
    });
}

// -- Task list --

function loadTasks() {
  const url = _currentFilter
    ? '/api/tasks?limit=30&status=' + _currentFilter
    : '/api/tasks?limit=30';

  fetch(url)
    .then(r => r.json())
    .then(data => {
      renderTaskList(data.tasks || []);
      renderRunning(data.tasks || []);
      const badge = document.getElementById('task-count');
      badge.textContent = data.count + ' tasks';
      badge.className = 'mo-badge mo-badge--on';
    })
    .catch(() => {
      document.getElementById('tasks-list').innerHTML =
        '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function renderTaskList(tasks) {
  const el = document.getElementById('tasks-list');
  if (!tasks.length) {
    el.innerHTML = '<div class="mo-empty-state">Brak taskow</div>';
    return;
  }

  let html = '<div class="mo-tasks-table">';
  html += '<div class="mo-tasks-row mo-tasks-row--header">';
  html += '<span class="mo-tasks-col mo-tasks-col--id">ID</span>';
  html += '<span class="mo-tasks-col mo-tasks-col--backend">Backend</span>';
  html += '<span class="mo-tasks-col mo-tasks-col--status">Status</span>';
  html += '<span class="mo-tasks-col mo-tasks-col--dur">Czas</span>';
  html += '<span class="mo-tasks-col mo-tasks-col--source">Zrodlo</span>';
  html += '<span class="mo-tasks-col mo-tasks-col--text">Zadanie</span>';
  html += '</div>';

  tasks.forEach(t => {
    const tid = t.task_id || '?';
    const backend = (t.backend || '?').toUpperCase();
    const status = t.status || '?';
    const statusClass = _statusClass(status);
    const dur = t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + 's' : '-';
    const source = _sourceLabel(t.source || '');
    const text = (t.task_text || '').substring(0, 50);
    const hasPdf = status === 'COMPLETED';

    html += '<div class="mo-tasks-row" onclick="showTaskDetail(\'' + tid + '\')" style="cursor:pointer">';
    html += '<span class="mo-tasks-col mo-tasks-col--id mo-text-mono">' + tid.slice(0, 8) + '</span>';
    html += '<span class="mo-tasks-col mo-tasks-col--backend"><b>' + backend + '</b></span>';
    html += '<span class="mo-tasks-col mo-tasks-col--status ' + statusClass + '">' + status + '</span>';
    html += '<span class="mo-tasks-col mo-tasks-col--dur">' + dur + '</span>';
    html += '<span class="mo-tasks-col mo-tasks-col--source">' + source + '</span>';
    html += '<span class="mo-tasks-col mo-tasks-col--text">' + _esc(text) + '</span>';
    html += '</div>';
  });

  html += '</div>';
  el.innerHTML = html;
}

function renderRunning(allTasks) {
  const running = allTasks.filter(t =>
    t.status === 'RUNNING' || t.status === 'PENDING'
  );
  const container = document.getElementById('running-tasks');
  const list = document.getElementById('running-list');

  if (!running.length) {
    container.style.display = 'none';
    stopAutoRefresh();
    return;
  }

  container.style.display = 'block';
  startAutoRefresh();

  let html = '';
  running.forEach(t => {
    const tid = t.task_id || '?';
    const backend = (t.backend || '?').toUpperCase();
    const text = (t.task_text || '').substring(0, 60);
    const elapsed = t.started_at
      ? Math.round((Date.now() / 1000 - t.started_at)) + 's'
      : 'czeka...';

    html += '<div class="mo-card mo-card--compact mo-mb-1">';
    html += '<span class="mo-text-mono">' + tid.slice(0, 8) + '</span> ';
    html += '<b>' + backend + '</b> ';
    html += '<span class="mo-text-yellow">' + t.status + '</span> ';
    html += elapsed + ' - ' + _esc(text);
    html += '</div>';
  });
  list.innerHTML = html;
}

function filterTasks(status) {
  _currentFilter = status;
  document.querySelectorAll('[data-filter]').forEach(btn => {
    btn.classList.toggle('mo-btn--active', btn.dataset.filter === status);
  });
  loadTasks();
}

// -- Detail --

function showTaskDetail(taskId) {
  // Switch to detail tab
  document.querySelectorAll('.mo-tab').forEach(t => t.classList.remove('mo-tab--active'));
  document.querySelectorAll('.mo-tab-content').forEach(c => c.classList.remove('mo-tab-content--active'));
  const detailTab = document.querySelector('[data-tab="tab-detail"]');
  if (detailTab) detailTab.classList.add('mo-tab--active');
  document.getElementById('tab-detail').classList.add('mo-tab-content--active');

  const el = document.getElementById('task-detail');
  el.innerHTML = '<div class="mo-empty-state">Ladowanie...</div>';

  fetch('/api/tasks/' + taskId)
    .then(r => {
      if (!r.ok) throw new Error('not found');
      return r.json();
    })
    .then(t => {
      const status = t.status || '?';
      const statusClass = _statusClass(status);
      const ts = t.created_at ? new Date(t.created_at * 1000).toLocaleString('pl-PL') : '-';
      const dur = t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + 's' : '-';
      const backend = (t.backend || '?').toUpperCase();

      let html = '<div class="mo-card">';
      html += '<div class="mo-flex mo-flex-between mo-flex-center mo-mb-2">';
      html += '<h3 class="mo-text-lg">' + backend + ' <span class="mo-text-mono">' + t.task_id + '</span></h3>';
      html += '<span class="' + statusClass + ' mo-text-lg"><b>' + status + '</b></span>';
      html += '</div>';

      html += '<div class="mo-text-sm mo-text-muted mo-mb-2">';
      html += 'Utworzono: ' + ts + ' | Czas: ' + dur + ' | Zrodlo: ' + _sourceLabel(t.source || '');
      html += '</div>';

      // Task text
      html += '<div class="mo-mb-2">';
      html += '<b>Zadanie:</b>';
      html += '<div class="mo-code-block mo-mt-1">' + _esc(t.task_text || '') + '</div>';
      html += '</div>';

      // Result or error
      if (t.result_summary) {
        html += '<div class="mo-mb-2">';
        html += '<b>Wynik:</b>';
        html += '<div class="mo-code-block mo-mt-1">' + _esc(t.result_summary) + '</div>';
        html += '</div>';
      }
      if (t.error) {
        html += '<div class="mo-mb-2">';
        html += '<b class="mo-text-red">Blad:</b>';
        html += '<div class="mo-code-block mo-mt-1 mo-text-red">' + _esc(t.error) + '</div>';
        html += '</div>';
      }

      // PDF button
      if (status === 'COMPLETED') {
        html += '<a href="/api/tasks/' + t.task_id + '/pdf" class="mo-btn mo-btn--sm mo-mt-2" download>Pobierz PDF</a>';
      }

      // Metadata
      if (t.metadata && Object.keys(t.metadata).length > 0) {
        html += '<div class="mo-mt-2 mo-text-sm mo-text-muted">';
        html += '<b>Metadata:</b> ' + _esc(JSON.stringify(t.metadata));
        html += '</div>';
      }

      html += '</div>';

      // Back button
      html += '<button class="mo-btn mo-btn--sm mo-mt-2" onclick="switchToTab(\'tab-list\')">Wstecz do listy</button>';

      el.innerHTML = html;
    })
    .catch(() => {
      el.innerHTML = '<div class="mo-empty-state">Nie znaleziono taska</div>';
    });
}

function switchToTab(tabId) {
  document.querySelectorAll('.mo-tab').forEach(t => t.classList.remove('mo-tab--active'));
  document.querySelectorAll('.mo-tab-content').forEach(c => c.classList.remove('mo-tab-content--active'));
  const tab = document.querySelector('[data-tab="' + tabId + '"]');
  if (tab) tab.classList.add('mo-tab--active');
  document.getElementById(tabId).classList.add('mo-tab-content--active');
}

// -- Auto-refresh for running tasks --

function startAutoRefresh() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(loadTasks, 5000);
}

function stopAutoRefresh() {
  if (_refreshTimer) {
    clearInterval(_refreshTimer);
    _refreshTimer = null;
  }
}

// -- Helpers --

function _statusClass(status) {
  switch (status) {
    case 'COMPLETED': return 'mo-text-green';
    case 'FAILED':
    case 'TIMEOUT':
    case 'INTERRUPTED': return 'mo-text-red';
    case 'RUNNING': return 'mo-text-yellow';
    case 'PENDING': return 'mo-text-muted';
    default: return '';
  }
}

function _sourceLabel(source) {
  if (source.startsWith('telegram')) return 'Telegram';
  if (source.startsWith('webui')) return 'Web UI';
  return source || '-';
}

function _esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function showToast(msg, type) {
  // Use maria_ui.js toast if available
  if (window.MoUI && window.MoUI.toast) {
    window.MoUI.toast(msg, type);
  } else if (window.moToast) {
    window.moToast(msg, type);
  }
}

// -- Init --
loadTasks();
