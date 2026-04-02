/* critique.js - Knowledge Critique (Faza G) dashboard */
(function () {
  'use strict';

  // Tab switching
  document.querySelectorAll('.mo-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      document.querySelectorAll('.mo-tab').forEach(function (t) { t.classList.remove('mo-tab--active'); });
      document.querySelectorAll('.mo-tab-content').forEach(function (c) { c.classList.remove('mo-tab-content--active'); });
      tab.classList.add('mo-tab--active');
      var target = M.$(tab.dataset.tab);
      if (target) target.classList.add('mo-tab-content--active');
    });
  });

  var SEV_ICONS = { CRITICAL: '!!', WARNING: '!', INFO: '.' };
  var SEV_CLASS = { CRITICAL: 'mo-tag--red', WARNING: 'mo-tag--yellow', INFO: 'mo-tag--blue' };

  function fmtTs(ts) {
    if (!ts) return '-';
    var d = new Date(ts * 1000);
    return d.toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  // -- Report tab --
  function loadReport() {
    M.apiFetch('/api/critique/report').then(function (data) {
      var el = M.$('report-summary');
      if (!data || data.error) {
        el.innerHTML = '<div class="mo-empty-state">' + (data && data.error || 'Brak danych') + '</div>';
        return;
      }
      if (!data.report) {
        el.innerHTML = '<div class="mo-empty-state">Brak raportow. Kliknij "Run Critique".</div>';
        return;
      }
      var r = data.report;
      var sevHtml = '';
      if (r.findings_by_severity) {
        Object.keys(r.findings_by_severity).sort().forEach(function (k) {
          var cls = SEV_CLASS[k] || '';
          sevHtml += '<span class="mo-tag ' + cls + '">' + k + ': ' + r.findings_by_severity[k] + '</span> ';
        });
      }
      var catHtml = '';
      if (r.findings_by_category) {
        Object.keys(r.findings_by_category).sort().forEach(function (k) {
          catHtml += '<span class="mo-tag">' + k + ': ' + r.findings_by_category[k] + '</span> ';
        });
      }

      el.innerHTML =
        '<div class="mo-card mo-mb-2">' +
        '  <div class="mo-card__header">Ostatni raport</div>' +
        '  <div class="mo-card__body">' +
        '    <div class="mo-grid mo-grid--2">' +
        '      <div><strong>ID:</strong> ' + (r.report_id || '').substring(0, 12) + '</div>' +
        '      <div><strong>Czas:</strong> ' + fmtTs(r.timestamp) + '</div>' +
        '      <div><strong>Trigger:</strong> ' + (r.trigger || '-') + '</div>' +
        '      <div><strong>Duration:</strong> ' + (r.duration_ms || 0).toFixed(0) + 'ms</div>' +
        '      <div><strong>Findings:</strong> ' + (r.findings ? r.findings.length : 0) + ' (total: ' + (r.findings_total || 0) + ')</div>' +
        '      <div><strong>Goals:</strong> ' + (r.goals_created ? r.goals_created.length : 0) + ' created</div>' +
        '    </div>' +
        '    <div class="mo-mt-2">' + sevHtml + '</div>' +
        '    <div class="mo-mt-1">' + catHtml + '</div>' +
        (r.llm_summary ? '<div class="mo-mt-2 mo-text-dim">' + r.llm_summary + '</div>' : '') +
        (r.error ? '<div class="mo-mt-2 mo-tag mo-tag--red">Error: ' + r.error + '</div>' : '') +
        '  </div>' +
        '</div>' +
        '<div class="mo-card">' +
        '  <div class="mo-card__header">Status</div>' +
        '  <div class="mo-card__body">' +
        '    <div><strong>Available:</strong> ' + (data.status && data.status.available ? 'Tak' : 'Nie') + '</div>' +
        '    <div><strong>Cooldown:</strong> ' + ((data.status && data.status.cooldown_sec || 28800) / 3600).toFixed(0) + 'h</div>' +
        '    <div><strong>Ostatnia krytyka:</strong> ' + fmtTs(data.status && data.status.last_critique_ts) + '</div>' +
        '  </div>' +
        '</div>';
    });
  }

  // -- Findings tab --
  function loadFindings() {
    M.apiFetch('/api/critique/findings').then(function (data) {
      var el = M.$('findings-list');
      if (!data || !data.findings || !data.findings.length) {
        el.innerHTML = '<div class="mo-empty-state">Brak findings</div>';
        return;
      }
      el.innerHTML = data.findings.map(function (f, i) {
        var cls = SEV_CLASS[f.severity] || '';
        var beliefHtml = f.belief_ids && f.belief_ids.length
          ? '<div class="mo-mt-1 mo-text-dim">Beliefs: ' + f.belief_ids.slice(0, 3).join(', ') + '</div>'
          : '';
        var sourcesHtml = f.evidence_sources && f.evidence_sources.length
          ? '<div class="mo-text-dim">Sources: ' + f.evidence_sources.slice(0, 3).join(', ') + '</div>'
          : '';
        var goalHtml = f.recommended_goal_title
          ? '<div class="mo-text-dim">Goal: ' + f.recommended_goal_title + '</div>'
          : '';

        return '<div class="mo-card mo-mb-2">' +
          '<div class="mo-card__header">' +
          '  <span class="mo-tag ' + cls + '">' + SEV_ICONS[f.severity] + ' ' + f.severity + '</span> ' +
          '  <span class="mo-tag">' + f.category + '</span> ' +
          '  <strong>' + f.topic + '</strong>' +
          '</div>' +
          '<div class="mo-card__body">' +
          '  <div>' + f.description + '</div>' +
          '  <div class="mo-mt-1"><strong>Akcja:</strong> ' + f.suggested_action + '</div>' +
          (f.confidence_delta ? '<div class="mo-text-dim">Confidence delta: ' + f.confidence_delta.toFixed(2) + '</div>' : '') +
          beliefHtml + sourcesHtml + goalHtml +
          '</div></div>';
      }).join('');
    });
  }

  // -- History tab --
  function loadHistory() {
    M.apiFetch('/api/critique/history').then(function (data) {
      var el = M.$('history-list');
      if (!data || !data.reports || !data.reports.length) {
        el.innerHTML = '<div class="mo-empty-state">Brak historii</div>';
        return;
      }
      el.innerHTML = '<table class="mo-table"><thead><tr>' +
        '<th>Czas</th><th>Trigger</th><th>Findings</th><th>Goals</th><th>Duration</th>' +
        '</tr></thead><tbody>' +
        data.reports.map(function (r) {
          var sevBadges = '';
          if (r.findings_by_severity) {
            Object.keys(r.findings_by_severity).forEach(function (k) {
              var cls = SEV_CLASS[k] || '';
              sevBadges += '<span class="mo-tag ' + cls + '">' + k[0] + ':' + r.findings_by_severity[k] + '</span> ';
            });
          }
          return '<tr>' +
            '<td>' + fmtTs(r.timestamp) + '</td>' +
            '<td>' + r.trigger + '</td>' +
            '<td>' + (r.findings_count || 0) + '/' + (r.findings_total || 0) + ' ' + sevBadges + '</td>' +
            '<td>' + (r.goals_count || 0) + '</td>' +
            '<td>' + (r.duration_ms || 0).toFixed(0) + 'ms</td>' +
            '</tr>';
        }).join('') +
        '</tbody></table>';
    });
  }

  // -- Run critique action --
  window.runCritique = function () {
    M.apiFetch('/api/critique/run', { method: 'POST' }).then(function (data) {
      if (data && data.success) {
        M.showToast('ok', 'Krytyka', data.findings + ' findings, ' + data.goals + ' goals');
        loadReport();
        loadFindings();
        loadHistory();
      } else {
        M.showToast('error', 'Blad', (data && data.error) || 'Nie udalo sie');
      }
    });
  };

  // Initial load
  loadReport();
  loadFindings();
  loadHistory();

  // Auto-refresh every 60s
  setInterval(function () { loadReport(); loadFindings(); }, 60000);
  setInterval(loadHistory, 120000);
})();
