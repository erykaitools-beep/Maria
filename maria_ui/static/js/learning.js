/**
 * Learning Goals - Web UI page (CDL Feedback Loop)
 * Shows learning goals created from chat, their progress and outcomes
 */

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

function loadLearning() {
  loadOverview();
  loadGoals();
}

function loadOverview() {
  fetch('/api/learning/stats')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('learning-overview');
      if (data.total === 0) {
        el.innerHTML = `
          <div class="mo-empty-state">
            Brak celow nauki.<br>
            <span class="mo-text-muted">Napisz w chacie "Poczytaj o fizyce" aby Maria zaczela sie uczyc.</span>
          </div>`;
        return;
      }

      const compRate = (data.completion_rate * 100).toFixed(0);
      const avgProg = (data.avg_progress * 100).toFixed(0);
      const compClass = data.completion_rate >= 0.7 ? 'mo-text-green' :
                        data.completion_rate >= 0.3 ? 'mo-text-yellow' : '';

      el.innerHTML = `
        <div class="mo-grid mo-grid--3 mo-mb-3">
          <div class="mo-card">
            <div class="mo-card__label">Cele nauki</div>
            <div class="mo-card__value">${data.total}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Aktywne</div>
            <div class="mo-card__value">${data.active}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Ukonczone</div>
            <div class="mo-card__value mo-text-green">${data.achieved}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Ukonczenie</div>
            <div class="mo-card__value ${compClass}">${compRate}%</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Avg postep</div>
            <div class="mo-card__value">${avgProg}%</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Tematy</div>
            <div class="mo-card__value">${data.topics_count}</div>
          </div>
        </div>
        <div class="mo-card">
          <div class="mo-card__label">Jak dziala CDL</div>
          <p class="mo-text-muted">Conversation-Driven Learning: napisz w chacie "Naucz sie o X"
          lub "Poczytaj o Y" - Maria automatycznie utworzy cel nauki, pobierze materialy,
          nauczy sie i zda egzamin. Postep i wyniki widoczne tutaj.</p>
        </div>
      `;
    })
    .catch(() => {
      document.getElementById('learning-overview').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadGoals() {
  fetch('/api/learning/goals')
    .then(r => r.json())
    .then(data => {
      renderGoalList('learning-active', data.active, 'Brak aktywnych celow nauki');
      renderGoalList('learning-done', data.achieved.concat(data.failed || []), 'Brak ukonczonych celow');
    })
    .catch(() => {
      document.getElementById('learning-active').innerHTML = '<div class="mo-empty-state">Blad</div>';
      document.getElementById('learning-done').innerHTML = '<div class="mo-empty-state">Blad</div>';
    });
}

function renderGoalList(elementId, goals, emptyMsg) {
  const el = document.getElementById(elementId);
  if (!goals || goals.length === 0) {
    el.innerHTML = `<div class="mo-empty-state">${emptyMsg}</div>`;
    return;
  }

  let html = '';
  goals.forEach(g => {
    const topic = (g.metadata || {}).topic || g.description || '?';
    const status = g.status || '?';
    const statusClass = status === 'achieved' ? 'mo-text-green' :
                        status === 'failed' || status === 'abandoned' ? 'mo-text-red' :
                        status === 'active' ? 'mo-text-yellow' : '';
    const progress = ((g.progress || 0) * 100).toFixed(0);
    const priority = (g.priority || 0).toFixed(1);
    const created = g.created_at ? timeAgo(g.created_at) : '-';
    const source = (g.metadata || {}).source || g.created_by || '?';
    const channel = (g.metadata || {}).channel || '';
    const gid = (g.id || '?').substring(0, 12);

    // Outcome details if available
    let outcomeHtml = '';
    if (g.outcome) {
      const score = g.outcome.final_score ? ((g.outcome.final_score) * 100).toFixed(0) + '%' : '-';
      const chunks = g.outcome.chunks_learned || 0;
      const exams = g.outcome.exams_passed || 0;
      outcomeHtml = `
        <div class="mo-mt-1 mo-text-sm">
          <span class="mo-text-muted">Wynik:</span> ${score}
          | <span class="mo-text-muted">Chunki:</span> ${chunks}
          | <span class="mo-text-muted">Egzaminy:</span> ${exams}
        </div>`;
    }

    // Progress bar
    const barWidth = Math.max(3, (g.progress || 0) * 100);
    const barColor = status === 'achieved' ? 'var(--mo-green, #4caf50)' : 'var(--mo-accent)';

    html += `
      <div class="mo-card mo-mb-2">
        <div class="mo-flex mo-flex-between mo-flex-center">
          <div>
            <span class="mo-text-mono mo-text-sm">[${gid}]</span>
            <b>${topic}</b>
          </div>
          <span class="${statusClass}">${status.toUpperCase()}</span>
        </div>
        <div class="mo-mt-1">
          <div style="background:var(--mo-bg-elevated);border-radius:4px;height:8px;width:100%">
            <div style="background:${barColor};border-radius:4px;height:8px;width:${barWidth}%;transition:width 0.3s"></div>
          </div>
          <div class="mo-flex mo-flex-between mo-text-sm mo-mt-1">
            <span>${progress}% complete</span>
            <span class="mo-text-muted">pri=${priority} | ${source}${channel ? '/'+channel : ''} | ${created}</span>
          </div>
        </div>
        ${outcomeHtml}
      </div>`;
  });

  el.innerHTML = html;
}

function timeAgo(ts) {
  const diff = (Date.now() / 1000) - ts;
  if (diff < 3600) return Math.floor(diff / 60) + 'min temu';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h temu';
  return Math.floor(diff / 86400) + 'd temu';
}

// Initial load
loadLearning();
// Auto-refresh every 30s
setInterval(loadLearning, 30000);
