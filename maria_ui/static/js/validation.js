/**
 * Cross-Validation - Web UI page (Faza F)
 * Multi-Source Learning: disputes, stats, history
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

// -- Data loading --

function loadValidation() {
  loadStats();
  loadDisputes();
  loadHistory();
}

function loadStats() {
  fetch('/api/validation/stats')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('validation-stats');
      if (data.error) {
        el.innerHTML = `<div class="mo-empty-state">Blad: ${data.error}</div>`;
        return;
      }

      const confPct = (data.avg_confidence * 100).toFixed(0);
      const confClass = data.avg_confidence >= 0.7 ? 'mo-text-green' :
                        data.avg_confidence >= 0.4 ? 'mo-text-yellow' : 'mo-text-red';

      el.innerHTML = `
        <div class="mo-grid mo-grid--3 mo-mb-3">
          <div class="mo-card">
            <div class="mo-card__label">Walidacje</div>
            <div class="mo-card__value">${data.total_validations}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Udane</div>
            <div class="mo-card__value mo-text-green">${data.successful}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Avg Confidence</div>
            <div class="mo-card__value ${confClass}">${confPct}%</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Spory (total)</div>
            <div class="mo-card__value">${data.total_disputes}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Nierozwiazane</div>
            <div class="mo-card__value ${data.unresolved_disputes > 0 ? 'mo-text-yellow' : ''}">${data.unresolved_disputes}</div>
          </div>
        </div>
        <div class="mo-card">
          <div class="mo-card__label">Jak dziala</div>
          <p class="mo-text-muted">Maria uczy sie z Ollama (primary), potem NIM (secondary) niezaleznie analizuje ten sam material.
          Roznice w odpowiedziach sa logowane jako spory (disputes). Wysoka zgodnosc = wieksza pewnosc wiedzy.</p>
        </div>
      `;
    })
    .catch(() => {
      document.getElementById('validation-stats').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadDisputes() {
  fetch('/api/validation/disputes?limit=30')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('validation-disputes');
      if (!data.disputes || data.disputes.length === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak sporow - wiedza jest spojna</div>';
        return;
      }

      let html = '<div class="mo-traces-table">';
      html += '<div class="mo-traces-row mo-traces-row--header">';
      html += '<span class="mo-traces-col" style="flex:2">Plik</span>';
      html += '<span class="mo-traces-col">Wymiar</span>';
      html += '<span class="mo-traces-col">Waznosc</span>';
      html += '<span class="mo-traces-col">Status</span>';
      html += '<span class="mo-traces-col" style="flex:2">Czas</span>';
      html += '</div>';

      data.disputes.forEach(d => {
        const fid = (d.file_id || '?').substring(0, 25);
        const dim = d.dimension || '?';
        const sev = d.severity || '?';
        const sevClass = sev === 'high' ? 'mo-text-red' : sev === 'medium' ? 'mo-text-yellow' : '';
        const resolved = d.resolution ? 'Resolved' : 'Open';
        const resClass = d.resolution ? 'mo-text-green' : 'mo-text-yellow';
        const ts = d.timestamp ? new Date(d.timestamp * 1000).toLocaleString('pl-PL') : '-';

        html += '<div class="mo-traces-row">';
        html += `<span class="mo-traces-col" style="flex:2" title="${d.file_id || ''}">${fid}</span>`;
        html += `<span class="mo-traces-col">${dim}</span>`;
        html += `<span class="mo-traces-col ${sevClass}">${sev}</span>`;
        html += `<span class="mo-traces-col ${resClass}">${resolved}</span>`;
        html += `<span class="mo-traces-col" style="flex:2">${ts}</span>`;
        html += '</div>';
      });

      html += '</div>';
      el.innerHTML = html;
    })
    .catch(() => {
      document.getElementById('validation-disputes').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadHistory() {
  fetch('/api/validation/history?limit=20')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('validation-history');
      if (!data.validations || data.validations.length === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak historii walidacji - zostanie wypelniona po pierwszym cyklu</div>';
        return;
      }

      let html = '<div class="mo-traces-table">';
      html += '<div class="mo-traces-row mo-traces-row--header">';
      html += '<span class="mo-traces-col mo-traces-col--id">ID</span>';
      html += '<span class="mo-traces-col" style="flex:2">Cel</span>';
      html += '<span class="mo-traces-col">Status</span>';
      html += '<span class="mo-traces-col">Czas</span>';
      html += '<span class="mo-traces-col" style="flex:2">Data</span>';
      html += '</div>';

      data.validations.forEach(v => {
        const eid = (v.episode_id || '?').slice(-8);
        const goal = (v.goal_description || '-').substring(0, 35);
        const ok = v.success === true ? 'OK' : 'FAIL';
        const okClass = v.success === true ? 'mo-text-green' : 'mo-text-red';
        const dur = (v.duration_ms || 0).toFixed(0);
        const ts = v.started_at ? new Date(v.started_at * 1000).toLocaleString('pl-PL') : '-';

        html += '<div class="mo-traces-row">';
        html += `<span class="mo-traces-col mo-traces-col--id mo-text-mono">${eid}</span>`;
        html += `<span class="mo-traces-col" style="flex:2">${goal}</span>`;
        html += `<span class="mo-traces-col ${okClass}">${ok}</span>`;
        html += `<span class="mo-traces-col">${dur}ms</span>`;
        html += `<span class="mo-traces-col" style="flex:2">${ts}</span>`;
        html += '</div>';
      });

      html += '</div>';
      el.innerHTML = html;
    })
    .catch(() => {
      document.getElementById('validation-history').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

// Initial load
loadValidation();
// Auto-refresh every 60s
setInterval(loadValidation, 60000);
