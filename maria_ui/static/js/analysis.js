/**
 * K12 Self-Analysis dashboard - reports, recommendations, history.
 */
(function() {
  var M = window.MariaUI || {};

  function fmtTime(ts) {
    if (!ts) return '';
    var d = new Date(ts * 1000);
    return d.toLocaleDateString('pl') + ' ' + d.toLocaleTimeString('pl', {hour:'2-digit', minute:'2-digit'});
  }

  function fmtDuration(ms) {
    if (!ms) return '?';
    if (ms < 1000) return Math.round(ms) + 'ms';
    return (ms / 1000).toFixed(1) + 's';
  }

  function esc(s) {
    if (!s) return '';
    if (M.escapeHtml) return M.escapeHtml(s);
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function categoryBadge(cat) {
    var map = {
      'knowledge_gap': 'mo-badge--warn',
      'retention_problem': 'mo-badge--error',
      'strategy_change': 'mo-badge--accent',
      'new_topic': 'mo-badge--ok'
    };
    return map[cat] || 'mo-badge--off';
  }

  function actionBadge(action) {
    var map = {
      'learn': 'mo-badge--ok',
      'fetch': 'mo-badge--accent',
      'review': 'mo-badge--warn',
      'experiment': 'mo-badge--off'
    };
    return map[action] || 'mo-badge--off';
  }

  // --- Load latest report ---
  function loadLatest() {
    var el = document.getElementById('latest-report');
    if (!el) return;

    fetch('/api/analysis/latest')
      .then(function(r) { return r.json(); })
      .then(function(report) {
        if (report.error) {
          el.innerHTML = '<div class="mo-empty-state">Brak raportow analizy</div>';
          return;
        }

        var recs = report.recommendations || [];
        var goals = report.goals_created || [];

        el.innerHTML =
          '<div class="mo-card">' +
            '<div class="mo-flex mo-flex-between mo-mb-3">' +
              '<div>' +
                '<div class="mo-text-xs mo-muted">Report ID</div>' +
                '<div class="mo-mono mo-text-sm">' + esc(report.report_id) + '</div>' +
              '</div>' +
              '<div style="text-align:right">' +
                '<div class="mo-text-xs mo-muted">Wygenerowany</div>' +
                '<div class="mo-text-sm">' + fmtTime(report.timestamp) + '</div>' +
              '</div>' +
            '</div>' +

            '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem" class="mo-mb-3">' +
              '<div class="mo-stat"><div class="mo-stat__value">' + recs.length + '</div><div class="mo-stat__label">Rekomendacje</div></div>' +
              '<div class="mo-stat"><div class="mo-stat__value">' + goals.length + '</div><div class="mo-stat__label">Cele utworzone</div></div>' +
              '<div class="mo-stat"><div class="mo-stat__value">' + (report.beliefs_updated || 0) + '</div><div class="mo-stat__label">Beliefs</div></div>' +
              '<div class="mo-stat"><div class="mo-stat__value">' + fmtDuration(report.duration_ms) + '</div><div class="mo-stat__label">Czas</div></div>' +
            '</div>' +

            '<div class="mo-flex mo-gap-2">' +
              '<span class="mo-badge mo-badge--ok">' + esc(report.analyzer) + '</span>' +
              (report.error ? '<span class="mo-badge mo-badge--error">Error</span>' : '') +
            '</div>' +

            (report.error ? '<div class="mo-mt-2 mo-text-sm mo-muted">' + esc(report.error) + '</div>' : '') +
          '</div>';
      })
      .catch(function() {
        el.innerHTML = '<div class="mo-empty-state">Nie mozna zaladowac raportu</div>';
      });
  }

  // --- Load recommendations ---
  function loadRecommendations() {
    var el = document.getElementById('recommendations-list');
    if (!el) return;

    fetch('/api/analysis/recommendations')
      .then(function(r) { return r.json(); })
      .then(function(recs) {
        if (!recs || !recs.length || recs.error) {
          el.innerHTML = '<div class="mo-empty-state">Brak rekomendacji</div>';
          return;
        }

        recs.sort(function(a, b) { return (b.priority || 0) - (a.priority || 0); });

        el.innerHTML = recs.map(function(r) {
          return '<div class="mo-card mo-mb-2">' +
            '<div class="mo-flex mo-flex-between mo-mb-2">' +
              '<span class="mo-badge ' + categoryBadge(r.category) + '">' + esc(r.category) + '</span>' +
              '<div>' +
                '<span class="mo-badge mo-badge--accent">' + Math.round((r.priority || 0) * 100) + '%</span> ' +
                '<span class="mo-badge ' + actionBadge(r.suggested_action) + '">' + esc(r.suggested_action) + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="mo-text-sm mo-mb-2">' + esc(r.description) + '</div>' +
            '<div class="mo-text-xs mo-muted">Temat: <span class="mo-mono">' + esc(r.topic) + '</span></div>' +
          '</div>';
        }).join('');
      })
      .catch(function() {
        el.innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
      });
  }

  // --- Load history ---
  function loadHistory() {
    var el = document.getElementById('history-list');
    if (!el) return;

    fetch('/api/analysis/history')
      .then(function(r) { return r.json(); })
      .then(function(reports) {
        if (!reports || !reports.length) {
          el.innerHTML = '<div class="mo-empty-state">Brak historii raportow</div>';
          return;
        }

        el.innerHTML =
          '<table class="mo-table">' +
            '<thead><tr>' +
              '<th>Data</th><th>Analyzer</th><th>Rekom.</th><th>Cele</th><th>Czas</th><th>Status</th>' +
            '</tr></thead>' +
            '<tbody>' +
            reports.map(function(r) {
              return '<tr>' +
                '<td class="mo-text-xs">' + fmtTime(r.timestamp) + '</td>' +
                '<td class="mo-text-xs">' + esc(r.analyzer) + '</td>' +
                '<td style="text-align:center">' + (r.num_recommendations || 0) + '</td>' +
                '<td style="text-align:center">' + (r.num_goals || 0) + '</td>' +
                '<td class="mo-text-xs">' + fmtDuration(r.duration_ms) + '</td>' +
                '<td>' + (r.error ? '<span class="mo-badge mo-badge--error">Error</span>' : '<span class="mo-badge mo-badge--ok">OK</span>') + '</td>' +
              '</tr>';
            }).join('') +
            '</tbody></table>';
      })
      .catch(function() {
        el.innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
      });
  }

  // --- Load status badge ---
  function loadStatus() {
    var el = document.getElementById('analysis-status');
    if (!el) return;

    fetch('/api/analysis/status')
      .then(function(r) { return r.json(); })
      .then(function(s) {
        if (s.available) {
          el.className = 'mo-badge mo-badge--ok';
          el.textContent = 'NIM + Local';
        } else {
          el.className = 'mo-badge mo-badge--warn';
          el.textContent = 'Local only';
        }
      })
      .catch(function() {
        el.className = 'mo-badge mo-badge--error';
        el.textContent = 'Offline';
      });
  }

  // --- Tab switching ---
  document.querySelectorAll('.mo-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('.mo-tab').forEach(function(t) { t.classList.remove('mo-tab--active'); });
      document.querySelectorAll('.mo-tab-content').forEach(function(c) { c.classList.remove('mo-tab-content--active'); });
      tab.classList.add('mo-tab--active');
      var target = document.getElementById(tab.dataset.tab);
      if (target) target.classList.add('mo-tab-content--active');
    });
  });

  // Init
  loadStatus();
  loadLatest();
  loadRecommendations();
  loadHistory();

  // Auto-refresh every 30s
  setInterval(function() {
    loadStatus();
    loadLatest();
    loadRecommendations();
    loadHistory();
  }, 30000);
})();
