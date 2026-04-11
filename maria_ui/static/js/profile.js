/**
 * Profile page - operator profile + proactive contact management.
 */

// ========= Tab switching (reuse pattern from tasks.js) =========
document.querySelectorAll('.mo-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.mo-tab').forEach(t => t.classList.remove('mo-tab--active'));
    document.querySelectorAll('.mo-tab-content').forEach(c => c.classList.remove('mo-tab-content--active'));
    tab.classList.add('mo-tab--active');
    const target = document.getElementById(tab.dataset.tab);
    if (target) target.classList.add('mo-tab-content--active');

    // Load data for activated tab
    if (tab.dataset.tab === 'tab-proactive') loadProactive();
    if (tab.dataset.tab === 'tab-history') loadHistory();
  });
});

// ========= Profile =========

function loadProfile() {
  moFetch('/api/user/profile')
    .then(data => renderProfile(data))
    .catch(() => {
      document.getElementById('profile-identity').innerHTML =
        '<div class="mo-empty-state">UserProfile niedostepny</div>';
    });
}

function renderProfile(data) {
  // Identity
  const id = data.identity || {};
  document.getElementById('profile-identity').innerHTML = `
    <div class="mo-kv"><span class="mo-kv__key">Imie</span><span class="mo-kv__val">${id.name || '?'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Jezyk</span><span class="mo-kv__val">${id.language || '?'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Strefa czasowa</span><span class="mo-kv__val">${id.timezone || '?'}</span></div>
  `;

  // Preferences
  const pref = data.preferences || {};
  document.getElementById('profile-preferences').innerHTML = `
    <div class="mo-kv"><span class="mo-kv__key">Styl odpowiedzi</span><span class="mo-kv__val">${pref.response_style || '?'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Poziom autonomii</span><span class="mo-kv__val">${pref.autonomy_level || '?'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Kanal powiadomien</span><span class="mo-kv__val">${pref.notify_channel || '?'}</span></div>
  `;

  // Interests
  const interests = data.interests || [];
  if (interests.length === 0) {
    document.getElementById('profile-interests').innerHTML = '<div class="mo-text-muted">Brak zainteresowani</div>';
  } else {
    document.getElementById('profile-interests').innerHTML = interests.map(i =>
      `<span class="mo-tag">${i} <button class="mo-tag__remove" onclick="removeInterest('${i}')">&times;</button></span>`
    ).join(' ');
  }

  // Schedule
  const schedule = (data.schedule || {}).notes || [];
  if (schedule.length === 0) {
    document.getElementById('profile-schedule').innerHTML = '<div class="mo-text-muted">Brak notatek</div>';
  } else {
    document.getElementById('profile-schedule').innerHTML = '<ul class="mo-list">' +
      schedule.map(s => `<li>${s}</li>`).join('') + '</ul>';
  }

  // Facts
  const facts = data.facts || [];
  if (facts.length === 0) {
    document.getElementById('profile-facts').innerHTML = '<div class="mo-text-muted">Brak faktow</div>';
  } else {
    document.getElementById('profile-facts').innerHTML = '<ul class="mo-list">' +
      facts.map(f => `<li>${f}</li>`).join('') + '</ul>';
  }

  // Stats
  const stats = data.stats || {};
  document.getElementById('profile-stats').innerHTML = `
    <div class="mo-kv"><span class="mo-kv__key">Pierwszy kontakt</span><span class="mo-kv__val">${stats.first_seen ? new Date(stats.first_seen).toLocaleDateString('pl') : '?'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Ostatni kontakt</span><span class="mo-kv__val">${stats.last_seen ? new Date(stats.last_seen).toLocaleDateString('pl') : '?'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Wiadomosci</span><span class="mo-kv__val">${stats.total_messages || 0}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Sesje</span><span class="mo-kv__val">${stats.sessions_count || 0}</span></div>
  `;
}

function addInterest() {
  const input = document.getElementById('new-interest');
  const val = input.value.trim();
  if (!val) return;

  moFetch('/api/user/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({add_interest: val})
  }).then(() => {
    input.value = '';
    loadProfile();
    moToast('Dodano: ' + val, 'success');
  });
}

function removeInterest(name) {
  moFetch('/api/user/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({remove_interest: name})
  }).then(() => {
    loadProfile();
    moToast('Usunieto: ' + name, 'info');
  });
}

function addSchedule() {
  const input = document.getElementById('new-schedule');
  const val = input.value.trim();
  if (!val) return;

  moFetch('/api/user/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({add_schedule: val})
  }).then(() => {
    input.value = '';
    loadProfile();
    moToast('Dodano notatke', 'success');
  });
}

function addFact() {
  const input = document.getElementById('new-fact');
  const val = input.value.trim();
  if (!val) return;

  moFetch('/api/user/profile', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({add_fact: val})
  }).then(() => {
    input.value = '';
    loadProfile();
    moToast('Dodano fakt', 'success');
  });
}

// ========= Proactive Contact =========

function loadProactive() {
  moFetch('/api/proactive/status')
    .then(data => renderProactive(data))
    .catch(() => {
      document.getElementById('proactive-info').innerHTML =
        '<div class="mo-empty-state">ProactiveScheduler niedostepny</div>';
    });
}

function renderProactive(data) {
  const enabled = data.enabled;
  const statusBadge = document.getElementById('proactive-status');
  statusBadge.textContent = enabled ? 'WLACZONY' : 'WYLACZONY';
  statusBadge.className = 'mo-badge ' + (enabled ? 'mo-badge--on' : 'mo-badge--off');

  const toggleBtn = document.getElementById('proactive-toggle');
  toggleBtn.textContent = enabled ? 'Wylacz' : 'Wlacz';

  const quietStr = data.quiet_hours ? 'Tak (cisza nocna)' : 'Nie';

  document.getElementById('proactive-info').innerHTML = `
    <div class="mo-kv"><span class="mo-kv__key">Kontakty dzisiaj</span><span class="mo-kv__val">${data.contacts_today} / ${data.max_per_day}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Cisza nocna</span><span class="mo-kv__val">${quietStr}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Idle operatora</span><span class="mo-kv__val">${data.operator_idle_human || 'n/a'}</span></div>
    <div class="mo-kv"><span class="mo-kv__key">Godzina</span><span class="mo-kv__val">${data.current_hour}:00</span></div>
  `;

  // Cooldowns
  const cooldowns = data.cooldowns || {};
  const reasonNames = {
    morning_summary: 'Poranny brief',
    evening_recap: 'Wieczorne podsumowanie',
    weekly_review: 'Przeglad tygodnia',
    goal_achieved: 'Cel osiagniety',
    learning_milestone: 'Kamien milowy nauki',
    interest_match: 'Dopasowanie zainteresowan',
    idle_checkin: 'Check-in po przerwie',
  };

  let cdHtml = '<table class="mo-table"><thead><tr><th>Typ</th><th>Cooldown</th><th>Pozostalo</th></tr></thead><tbody>';
  for (const [key, info] of Object.entries(cooldowns)) {
    const name = reasonNames[key] || key;
    const cooldownH = (info.cooldown_sec / 3600).toFixed(1) + 'h';
    const remaining = info.remaining_sec > 0
      ? formatDuration(info.remaining_sec)
      : '<span class="mo-text-success">Gotowe</span>';
    cdHtml += `<tr><td>${name}</td><td>${cooldownH}</td><td>${remaining}</td></tr>`;
  }
  cdHtml += '</tbody></table>';
  document.getElementById('proactive-cooldowns').innerHTML = cdHtml;
}

function toggleProactive() {
  moFetch('/api/proactive/toggle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  }).then(data => {
    moToast(data.enabled ? 'Proaktywnosc WLACZONA' : 'Proaktywnosc WYLACZONA',
            data.enabled ? 'success' : 'info');
    loadProactive();
  });
}

// ========= Contact History =========

function loadHistory() {
  moFetch('/api/proactive/history?limit=30')
    .then(data => renderHistory(data.contacts || []))
    .catch(() => {
      document.getElementById('proactive-history').innerHTML =
        '<div class="mo-empty-state">Historia niedostepna</div>';
    });
}

function renderHistory(contacts) {
  if (contacts.length === 0) {
    document.getElementById('proactive-history').innerHTML =
      '<div class="mo-empty-state">Brak historii kontaktow</div>';
    return;
  }

  const reasonNames = {
    morning_summary: 'Poranny brief',
    evening_recap: 'Wieczorne podsumowanie',
    weekly_review: 'Przeglad tygodnia',
    goal_achieved: 'Cel osiagniety',
    learning_milestone: 'Kamien milowy',
    interest_match: 'Dopasowanie zainteresowan',
    idle_checkin: 'Check-in',
  };

  // Reverse to show newest first
  const reversed = [...contacts].reverse();

  let html = '<div class="mo-timeline">';
  for (const c of reversed) {
    const dt = c.timestamp ? new Date(c.timestamp * 1000) : null;
    const dateStr = dt ? dt.toLocaleDateString('pl') + ' ' + dt.toLocaleTimeString('pl', {hour: '2-digit', minute: '2-digit'}) : '?';
    const reason = reasonNames[c.reason] || c.reason;
    // Truncate message for preview
    const preview = (c.message || '').replace(/\*/g, '').substring(0, 120);

    html += `
      <div class="mo-timeline__item">
        <div class="mo-flex mo-flex-between">
          <span class="mo-badge mo-badge--outline">${reason}</span>
          <span class="mo-text-sm mo-text-muted">${dateStr}</span>
        </div>
        <div class="mo-text-sm mo-mt-1">${preview}${(c.message || '').length > 120 ? '...' : ''}</div>
      </div>
    `;
  }
  html += '</div>';
  document.getElementById('proactive-history').innerHTML = html;
}

// ========= Helpers =========

function formatDuration(sec) {
  if (sec < 60) return sec + 's';
  if (sec < 3600) return Math.round(sec / 60) + 'min';
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return m > 0 ? h + 'h ' + m + 'min' : h + 'h';
}

// ========= Init =========

loadProfile();
