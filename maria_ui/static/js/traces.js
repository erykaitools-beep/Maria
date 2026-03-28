/**
 * Decision Traces - Web UI page
 * Phase 1 traceability visualization
 */

// Tab switching (reuse pattern from analysis.js)
document.querySelectorAll('.mo-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.mo-tab').forEach(t => t.classList.remove('mo-tab--active'));
    document.querySelectorAll('.mo-tab-content').forEach(c => c.classList.remove('mo-tab-content--active'));
    tab.classList.add('mo-tab--active');
    const target = document.getElementById(tab.dataset.tab);
    if (target) target.classList.add('mo-tab-content--active');
  });
});

// -- Data loading --

function loadTraces() {
  loadRecent();
  loadStats();
  loadFailed();
}

function loadRecent() {
  fetch('/api/traces?limit=30')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('traces-list');
      const count = document.getElementById('trace-count');
      count.textContent = data.count + ' traces';
      count.className = 'mo-badge mo-badge--on';

      if (!data.traces || data.traces.length === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak traces</div>';
        return;
      }

      let html = '<div class="mo-traces-table">';
      html += '<div class="mo-traces-row mo-traces-row--header">';
      html += '<span class="mo-traces-col mo-traces-col--id">ID</span>';
      html += '<span class="mo-traces-col mo-traces-col--action">Akcja</span>';
      html += '<span class="mo-traces-col mo-traces-col--status">Status</span>';
      html += '<span class="mo-traces-col mo-traces-col--dur">Czas</span>';
      html += '<span class="mo-traces-col mo-traces-col--llm">LLM</span>';
      html += '<span class="mo-traces-col mo-traces-col--k7">K7</span>';
      html += '<span class="mo-traces-col mo-traces-col--goal">Cel</span>';
      html += '</div>';

      data.traces.forEach(t => {
        const eid = (t.episode_id || '?').slice(-8);
        const action = t.action_type || 'guard';
        const ok = t.success === true ? 'OK' : (t.success === false ? 'FAIL' : '?');
        const okClass = t.success === true ? 'mo-text-green' : (t.success === false ? 'mo-text-red' : '');
        const dur = (t.duration_ms || 0).toFixed(0);
        const llm = t.total_llm_calls || 0;
        const k7 = t.k7_decision || '-';
        const k7Class = k7 === 'block' || k7 === 'rate_limited' ? 'mo-text-red' : '';
        const goal = (t.goal_description || '-').substring(0, 25);
        const models = (t.models_used || []).join(', ') || '-';

        html += `<div class="mo-traces-row" onclick="showDetail('${t.episode_id}')" style="cursor:pointer">`;
        html += `<span class="mo-traces-col mo-traces-col--id mo-text-mono">${eid}</span>`;
        html += `<span class="mo-traces-col mo-traces-col--action"><b>${action}</b></span>`;
        html += `<span class="mo-traces-col mo-traces-col--status ${okClass}">${ok}</span>`;
        html += `<span class="mo-traces-col mo-traces-col--dur">${dur}ms</span>`;
        html += `<span class="mo-traces-col mo-traces-col--llm">${llm > 0 ? llm + ' (' + models + ')' : '-'}</span>`;
        html += `<span class="mo-traces-col mo-traces-col--k7 ${k7Class}">${k7}</span>`;
        html += `<span class="mo-traces-col mo-traces-col--goal">${goal}</span>`;
        html += '</div>';
      });

      html += '</div>';
      el.innerHTML = html;
    })
    .catch(() => {
      document.getElementById('traces-list').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadStats() {
  fetch('/api/traces/stats')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('traces-stats');
      if (data.total === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak danych</div>';
        return;
      }

      const successRate = data.total > 0 ? ((data.success / data.total) * 100).toFixed(0) : 0;
      const actionHtml = Object.entries(data.action_types || {})
        .sort((a, b) => b[1] - a[1])
        .map(([action, count]) => `<div class="mo-flex mo-flex-between mo-mb-1"><span>${action}</span><span class="mo-text-mono">${count}</span></div>`)
        .join('');

      el.innerHTML = `
        <div class="mo-grid mo-grid--3 mo-mb-3">
          <div class="mo-card">
            <div class="mo-card__label">Traces</div>
            <div class="mo-card__value">${data.total}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Sukces</div>
            <div class="mo-card__value ${data.failed > 5 ? 'mo-text-red' : 'mo-text-green'}">${successRate}%</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Avg czas</div>
            <div class="mo-card__value">${(data.avg_duration_ms || 0).toFixed(0)}ms</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">LLM calls</div>
            <div class="mo-card__value">${data.total_llm_calls || 0}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">K7 blokad</div>
            <div class="mo-card__value ${data.k7_blocks > 0 ? 'mo-text-yellow' : ''}">${data.k7_blocks || 0}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Bledy</div>
            <div class="mo-card__value ${data.failed > 0 ? 'mo-text-red' : ''}">${data.failed || 0}</div>
          </div>
        </div>
        <h3 class="mo-text-md mo-mb-2">Akcje</h3>
        <div class="mo-card">${actionHtml || '<span class="mo-text-muted">Brak</span>'}</div>
      `;
    })
    .catch(() => {
      document.getElementById('traces-stats').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadFailed() {
  fetch('/api/traces/failed?limit=10')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('traces-failed');
      if (!data.traces || data.traces.length === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak bledow - super!</div>';
        return;
      }

      let html = '';
      data.traces.forEach(t => {
        const eid = (t.episode_id || '?').slice(-8);
        const action = t.action_type || 'guard';
        const k7 = t.k7_decision || '-';
        const summary = t.result_summary || '-';
        const dur = (t.duration_ms || 0).toFixed(0);

        html += `<div class="mo-card mo-mb-2" onclick="showDetail('${t.episode_id}')" style="cursor:pointer">`;
        html += `<div class="mo-flex mo-flex-between"><span class="mo-text-mono">[${eid}]</span><span class="mo-text-red">FAIL</span></div>`;
        html += `<div><b>${action}</b> K7:${k7} - ${dur}ms</div>`;
        html += `<div class="mo-text-muted">${summary.substring(0, 80)}</div>`;
        html += '</div>';
      });

      el.innerHTML = html;
    })
    .catch(() => {
      document.getElementById('traces-failed').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

// -- Detail overlay --

function showDetail(episodeId) {
  fetch(`/api/traces/${episodeId}`)
    .then(r => r.json())
    .then(t => {
      if (t.error) {
        return;
      }

      const overlay = document.getElementById('trace-detail-overlay');
      const title = document.getElementById('detail-title');
      const body = document.getElementById('trace-detail-body');

      title.textContent = `Trace ${(t.episode_id || '?').slice(-8)}`;

      const ok = t.success === true ? 'OK' : 'FAIL';
      const okClass = t.success === true ? 'mo-text-green' : 'mo-text-red';
      const models = (t.models_used || []).join(', ') || '-';
      const dur = (t.duration_ms || 0).toFixed(0);
      const started = new Date((t.started_at || 0) * 1000).toLocaleString('pl-PL');

      let stepsHtml = '';
      (t.steps || []).forEach((s, i) => {
        const resultClass = s.result === 'blocked' ? 'mo-text-red' : (s.result === 'allowed' || s.result === 'ok' ? 'mo-text-green' : '');
        const detail = s.detail && Object.keys(s.detail).length > 0 ? JSON.stringify(s.detail) : '';
        stepsHtml += `<div class="mo-traces-step">`;
        stepsHtml += `<span class="mo-text-mono">${i + 1}.</span> `;
        stepsHtml += `<b>${s.subsystem}</b>: ${s.action} -> <span class="${resultClass}">${s.result}</span>`;
        if (detail) stepsHtml += ` <span class="mo-text-muted mo-text-sm">${detail}</span>`;
        stepsHtml += '</div>';
      });

      body.innerHTML = `
        <div class="mo-grid mo-grid--2 mo-mb-2">
          <div>
            <div class="mo-text-muted">Status</div>
            <div class="${okClass}"><b>${ok}</b></div>
          </div>
          <div>
            <div class="mo-text-muted">Czas</div>
            <div>${dur}ms</div>
          </div>
          <div>
            <div class="mo-text-muted">Akcja</div>
            <div><b>${t.action_type || '-'}</b></div>
          </div>
          <div>
            <div class="mo-text-muted">Start</div>
            <div>${started}</div>
          </div>
          <div>
            <div class="mo-text-muted">Cel</div>
            <div>${t.goal_description || '-'}</div>
          </div>
          <div>
            <div class="mo-text-muted">K7</div>
            <div>${t.k7_decision || '-'} ${(t.k7_reasons || []).join(', ')}</div>
          </div>
          <div>
            <div class="mo-text-muted">K10</div>
            <div>${t.k10_safety_mode || '-'} -> ${t.k10_validation || '-'}</div>
          </div>
          <div>
            <div class="mo-text-muted">LLM</div>
            <div>${t.total_llm_calls || 0} calls (${models}) ${(t.total_llm_latency_ms || 0).toFixed(0)}ms</div>
          </div>
        </div>
        <div>
          <div class="mo-text-muted">Mode / Health</div>
          <div>${t.mode || '-'} / ${((t.health_score || 0) * 100).toFixed(0)}%</div>
        </div>
        <div class="mo-mb-2">
          <div class="mo-text-muted">Plan ID</div>
          <div class="mo-text-mono mo-text-sm">${t.plan_id || '-'}</div>
        </div>
        <h4 class="mo-text-md mo-mb-1">Steps (${(t.steps || []).length})</h4>
        <div class="mo-traces-steps">${stepsHtml || '<span class="mo-text-muted">Brak</span>'}</div>
        <div class="mo-mt-2">
          <div class="mo-text-muted">Summary</div>
          <div>${t.result_summary || '-'}</div>
        </div>
      `;

      overlay.style.display = 'flex';
    })
    .catch(() => {});
}

function closeDetail() {
  document.getElementById('trace-detail-overlay').style.display = 'none';
}

// Close overlay on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeDetail();
});

// Close overlay on click outside
document.getElementById('trace-detail-overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeDetail();
});

// Initial load
loadTraces();
// Auto-refresh every 30s
setInterval(loadTraces, 30000);
