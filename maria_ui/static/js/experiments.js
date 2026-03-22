/**
 * M.A.R.I.A. Experiments Page v2
 */

(function() {
  const M = MariaUI;

  // --- Tab switching ---
  document.querySelectorAll('.mo-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.mo-tab').forEach(t => t.classList.remove('mo-tab--active'));
      document.querySelectorAll('.mo-tab-content').forEach(c => c.classList.remove('mo-tab-content--active'));
      tab.classList.add('mo-tab--active');
      const target = M.$(tab.dataset.tab);
      if (target) target.classList.add('mo-tab-content--active');
    });
  });

  // Format timestamp
  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    return d.toLocaleDateString('pl') + ' ' + d.toLocaleTimeString('pl', {hour:'2-digit', minute:'2-digit'});
  }

  // Status badge class
  function statusBadge(status) {
    const map = {
      'draft': 'mo-badge--off', 'proposed': 'mo-badge--warn',
      'approved': 'mo-badge--ok', 'rejected': 'mo-badge--error',
      'expired': 'mo-badge--off', 'running': 'mo-badge--accent',
      'completed': 'mo-badge--ok',
    };
    return map[(status || '').toLowerCase()] || 'mo-badge--off';
  }

  // --- Actions ---
  window.approveProposal = function(id) {
    M.apiFetch('/api/experiments/approve/' + id, {method: 'POST'}).then(data => {
      if (data && data.success) { M.showToast('ok', 'Zatwierdzone', 'Propozycja zatwierdzona'); loadProposals(); }
      else M.showToast('error', 'Blad', (data && data.message) || 'Nie udalo sie');
    });
  };

  window.rejectProposal = function(id) {
    M.apiFetch('/api/experiments/reject/' + id, {method: 'POST'}).then(data => {
      if (data && data.success) { M.showToast('ok', 'Odrzucone', 'Propozycja odrzucona'); loadProposals(); }
      else M.showToast('error', 'Blad', (data && data.message) || 'Nie udalo sie');
    });
  };

  window.toggleComment = function(id) {
    const el = M.$('comment-' + id);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  };

  window.submitComment = function(id) {
    const textarea = document.querySelector('#comment-' + id + ' textarea');
    const text = (textarea && textarea.value || '').trim();
    if (!text) return;
    M.apiFetch('/api/experiments/comment/' + id, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: text})
    }).then(data => {
      if (data && data.success) { M.showToast('ok', 'Dodano', 'Uwaga dodana'); textarea.value = ''; loadProposals(); }
      else M.showToast('error', 'Blad', (data && data.message) || 'Nie udalo sie');
    });
  };

  // --- Load proposals ---
  function loadProposals() {
    M.apiFetch('/api/experiments/proposals').then(proposals => {
      const el = M.$('proposals-list');
      if (!proposals || !proposals.length) {
        el.innerHTML = '<div class="mo-empty-state">Brak propozycji. System automatycznie wygeneruje propozycje na podstawie obserwacji K4/K9.</div>';
        return;
      }

      proposals.reverse();
      el.innerHTML = proposals.map(p => {
        const canAct = p.status === 'draft' || p.status === 'proposed';
        const commentsHtml = (p.comments || []).map(c =>
          '<div class="mo-text-xs mo-mt-2" style="padding-left:var(--mo-sp-3);border-left:2px solid var(--mo-border)">' +
          '<span class="mo-accent">' + M.escapeHtml(c.author || 'user') + '</span> ' +
          '<span class="mo-muted">' + fmtTime(c.timestamp) + '</span><br>' +
          M.escapeHtml(c.text) + '</div>'
        ).join('');

        return '<div class="mo-exp-card">' +
          '<div class="mo-flex mo-flex-between mo-flex-center">' +
          '<div class="mo-flex mo-flex-center mo-gap-2">' +
          '<span class="mo-badge ' + statusBadge(p.status) + '">' + M.escapeHtml(p.status) + '</span>' +
          '<span class="mo-text-xs mo-muted mo-mono">' + M.escapeHtml(p.proposal_id) + '</span></div>' +
          '<span class="mo-text-xs mo-muted">' + fmtTime(p.timestamp) + '</span></div>' +
          '<div class="mo-mt-2 mo-mono mo-text-sm">' + M.escapeHtml(p.parameter_id) + ': ' +
          p.current_value + ' &rarr; ' + p.proposed_value + '</div>' +
          '<div class="mo-mt-2 mo-text-sm mo-secondary">' + M.escapeHtml(p.hypothesis) + '</div>' +
          '<div class="mo-text-xs mo-muted mo-mt-2">Zrodlo: ' + M.escapeHtml(p.source) +
          ' | Ryzyko: ' + M.escapeHtml(p.risk_assessment || '-') + '</div>' +
          (canAct ? '<div class="mo-exp-actions">' +
            '<button class="mo-btn mo-btn--approve" onclick="approveProposal(\'' + p.proposal_id + '\')">Zatwierdz</button>' +
            '<button class="mo-btn mo-btn--reject" onclick="rejectProposal(\'' + p.proposal_id + '\')">Odrzuc</button>' +
            '<button class="mo-btn mo-btn--ghost" onclick="toggleComment(\'' + p.proposal_id + '\')">Dodaj uwage</button>' +
            '</div>' : '') +
          '<div id="comment-' + p.proposal_id + '" class="mo-comment-input">' +
          '<textarea placeholder="Twoja uwaga..."></textarea>' +
          '<button class="mo-btn mo-btn--ghost mo-mt-2" onclick="submitComment(\'' + p.proposal_id + '\')">Wyslij</button></div>' +
          commentsHtml +
          '</div>';
      }).join('');
    });
  }

  // --- Load reports ---
  function loadReports() {
    M.apiFetch('/api/experiments/reports').then(reports => {
      const el = M.$('reports-list');
      if (!reports || !reports.length) {
        el.innerHTML = '<div class="mo-empty-state">Brak raportow z eksperymentow.</div>';
        return;
      }

      reports.reverse();
      el.innerHTML = reports.map(r => {
        const recBadge = r.recommendation === 'ADOPT' ? 'mo-badge--ok' :
                         r.recommendation === 'REJECT' ? 'mo-badge--error' : 'mo-badge--warn';

        const deltasHtml = Object.entries(r.delta_metrics || {}).map(([k,v]) => {
          const cls = v > 0 ? 'mo-metric__value--ok' : v < 0 ? 'mo-metric__value--error' : '';
          const sign = v > 0 ? '+' : '';
          return '<div class="mo-stat"><div class="mo-stat__value mo-text-sm ' + cls + '">' +
            sign + v.toFixed(3) + '</div><div class="mo-stat__label">' + M.escapeHtml(k) + '</div></div>';
        }).join('');

        return '<div class="mo-exp-card">' +
          '<div class="mo-flex mo-flex-between mo-flex-center">' +
          '<div class="mo-flex mo-flex-center mo-gap-2">' +
          '<span class="mo-badge ' + recBadge + '">' + M.escapeHtml(r.recommendation) + '</span>' +
          '<span class="mo-text-xs mo-muted mo-mono">' + M.escapeHtml(r.report_id) + '</span></div>' +
          '<span class="mo-text-xs mo-muted">' + fmtTime(r.timestamp) + '</span></div>' +
          '<div class="mo-mt-2 mo-mono mo-text-sm">' + M.escapeHtml(r.parameter_id) + ': ' +
          r.baseline_value + ' &rarr; ' + r.test_value + '</div>' +
          '<div class="mo-mt-2 mo-text-sm mo-secondary">' + M.escapeHtml(r.hypothesis) + '</div>' +
          '<div class="mo-text-xs mo-muted mo-mt-2">' + M.escapeHtml(r.conclusion) + '</div>' +
          '<div class="mo-text-xs mo-muted">Pewnosc: ' + (r.confidence * 100).toFixed(0) + '% | ' +
          'Cykli: ' + r.test_cycles + ' | Czas: ' + Math.round(r.duration_sec) + 's</div>' +
          (deltasHtml ? '<div class="mo-stats-grid mo-mt-3">' + deltasHtml + '</div>' : '') +
          '<a href="/api/experiments/export/' + r.report_id + '" class="mo-btn mo-btn--ghost mo-mt-3" style="display:inline-flex;text-decoration:none">Export JSON</a>' +
          '</div>';
      }).join('');
    });
  }

  // --- Load params ---
  function loadParams() {
    M.apiFetch('/api/experiments/params').then(params => {
      const el = M.$('params-list');
      if (!params || !params.length) {
        el.innerHTML = '<div class="mo-empty-state">Brak parametrow</div>';
        return;
      }

      const byRisk = {low: [], medium: [], high: []};
      params.forEach(p => { if (byRisk[p.risk_level]) byRisk[p.risk_level].push(p); });

      let html = '';
      ['low', 'medium', 'high'].forEach(risk => {
        const items = byRisk[risk];
        if (!items.length) return;
        const badgeCls = risk === 'low' ? 'mo-badge--ok' : risk === 'medium' ? 'mo-badge--warn' : 'mo-badge--error';
        html += '<div class="mo-flex mo-flex-center mo-gap-2 mo-mt-4 mo-mb-3">' +
          '<span class="mo-badge ' + badgeCls + '">' + risk.toUpperCase() + ' RISK</span>' +
          '<span class="mo-text-xs mo-muted">(' + items.length + ' params)</span></div>';
        html += '<table class="mo-table"><thead><tr>' +
          '<th>Parametr</th><th>Wartosc</th><th>Zakres</th><th>Metryka</th><th>Opis</th></tr></thead><tbody>';
        items.forEach(p => {
          html += '<tr><td class="mo-mono mo-text-xs">' + M.escapeHtml(p.param_id) + '</td>' +
            '<td><strong>' + p.current_value + '</strong></td>' +
            '<td class="mo-text-xs">' + p.min_value + ' - ' + p.max_value + ' (step ' + p.step + ')</td>' +
            '<td class="mo-text-xs">' + M.escapeHtml(p.impact_metric) + '</td>' +
            '<td class="mo-text-xs mo-muted">' + M.escapeHtml(p.description) + '</td></tr>';
        });
        html += '</tbody></table>';
      });

      el.innerHTML = html;
    });
  }

  // Init
  loadProposals();
  loadReports();
  loadParams();
  setInterval(() => { loadProposals(); loadReports(); }, 30000);

})();
