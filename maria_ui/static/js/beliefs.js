/**
 * Belief Store v2 - Web UI page
 * Stats, knowledge gaps, recent beliefs
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

function loadBeliefs() {
  loadStats();
  loadGaps();
  loadRecent();
}

function loadStats() {
  fetch('/api/beliefs/stats')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('beliefs-stats');
      if (data.total === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak beliefs - zostana zbudowane po pierwszym cyklu nauki</div>';
        return;
      }

      const bt = data.by_belief_type || {};
      const et = data.by_entity_type || {};
      const confPct = (data.avg_confidence * 100).toFixed(0);
      const confClass = data.avg_confidence >= 0.7 ? 'mo-text-green' :
                        data.avg_confidence >= 0.4 ? 'mo-text-yellow' : 'mo-text-red';

      const totalFacts = bt.fact || 0;
      const totalObs = bt.observation || 0;
      const totalHypo = bt.hypothesis || 0;
      const factPct = data.total > 0 ? ((totalFacts / data.total) * 100).toFixed(0) : 0;

      el.innerHTML = `
        <div class="mo-grid mo-grid--3 mo-mb-3">
          <div class="mo-card">
            <div class="mo-card__label">Active Beliefs</div>
            <div class="mo-card__value">${data.total}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Avg Confidence</div>
            <div class="mo-card__value ${confClass}">${confPct}%</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Evidence Points</div>
            <div class="mo-card__value">${data.total_evidence || 0}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Facts (verified)</div>
            <div class="mo-card__value mo-text-green">${totalFacts} (${factPct}%)</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Observations</div>
            <div class="mo-card__value">${totalObs}</div>
          </div>
          <div class="mo-card">
            <div class="mo-card__label">Hypotheses</div>
            <div class="mo-card__value mo-text-yellow">${totalHypo}</div>
          </div>
        </div>
        <h3 class="mo-text-md mo-mb-2">Entity Types</h3>
        <div class="mo-card">
          ${Object.entries(et).sort((a,b) => b[1]-a[1]).map(([type, count]) =>
            '<div class="mo-flex mo-flex-between mo-mb-1">' +
            '<span>' + type + '</span>' +
            '<span class="mo-text-mono">' + count + '</span></div>'
          ).join('')}
        </div>
      `;
    })
    .catch(() => {
      document.getElementById('beliefs-stats').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadGaps() {
  fetch('/api/beliefs/gaps')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('beliefs-gaps');
      if (!data.gaps || data.gaps.length === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak luk w wiedzy - wszystkie tematy maja wysoka pewnosc</div>';
        return;
      }

      let html = '<p class="mo-text-muted mo-mb-2">Tematy z najnizsza pewnoscia - kandydaci do powtorki lub nauki.</p>';
      html += '<div class="mo-traces-table">';
      html += '<div class="mo-traces-row mo-traces-row--header">';
      html += '<span class="mo-traces-col" style="flex:3">Temat</span>';
      html += '<span class="mo-traces-col">Pewnosc</span>';
      html += '<span class="mo-traces-col" style="flex:2">Pasek</span>';
      html += '</div>';

      data.gaps.forEach(g => {
        const pct = (g.confidence * 100).toFixed(0);
        const cls = g.confidence >= 0.7 ? 'mo-text-green' :
                    g.confidence >= 0.4 ? 'mo-text-yellow' : 'mo-text-red';
        const barWidth = Math.max(5, g.confidence * 100);

        html += '<div class="mo-traces-row">';
        html += `<span class="mo-traces-col" style="flex:3"><b>${g.topic}</b></span>`;
        html += `<span class="mo-traces-col ${cls}">${pct}%</span>`;
        html += `<span class="mo-traces-col" style="flex:2">`;
        html += `<div style="background:var(--mo-bg-elevated);border-radius:4px;height:8px;width:100%">`;
        html += `<div style="background:var(--mo-accent);border-radius:4px;height:8px;width:${barWidth}%"></div>`;
        html += `</div></span>`;
        html += '</div>';
      });

      html += '</div>';
      el.innerHTML = html;
    })
    .catch(() => {
      document.getElementById('beliefs-gaps').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

function loadRecent() {
  fetch('/api/beliefs/recent?limit=25')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('beliefs-recent');
      if (!data.beliefs || data.beliefs.length === 0) {
        el.innerHTML = '<div class="mo-empty-state">Brak ostatnich beliefs</div>';
        return;
      }

      let html = '<div class="mo-traces-table">';
      html += '<div class="mo-traces-row mo-traces-row--header">';
      html += '<span class="mo-traces-col" style="flex:3">Entity</span>';
      html += '<span class="mo-traces-col">Type</span>';
      html += '<span class="mo-traces-col">Belief</span>';
      html += '<span class="mo-traces-col">Conf</span>';
      html += '<span class="mo-traces-col">Rev</span>';
      html += '<span class="mo-traces-col" style="flex:2">Updated</span>';
      html += '</div>';

      data.beliefs.forEach(b => {
        const entity = (b.entity || '?').substring(0, 30);
        const eType = b.entity_type || '?';
        const bType = b.belief_type || '?';
        const bClass = bType === 'fact' ? 'mo-text-green' :
                       bType === 'hypothesis' ? 'mo-text-yellow' : '';
        const conf = ((b.confidence || 0) * 100).toFixed(0);
        const confClass = b.confidence >= 0.7 ? 'mo-text-green' :
                          b.confidence >= 0.4 ? 'mo-text-yellow' : 'mo-text-red';
        const rev = b.revision || 1;
        const ts = b.updated_at ? new Date(b.updated_at * 1000).toLocaleString('pl-PL') : '-';
        const evCount = (b.evidence || []).length;

        html += '<div class="mo-traces-row">';
        html += `<span class="mo-traces-col" style="flex:3" title="${b.entity || ''}">${entity}</span>`;
        html += `<span class="mo-traces-col">${eType}</span>`;
        html += `<span class="mo-traces-col ${bClass}">${bType}</span>`;
        html += `<span class="mo-traces-col ${confClass}">${conf}%</span>`;
        html += `<span class="mo-traces-col">${rev}${evCount > 0 ? ' ('+evCount+'ev)' : ''}</span>`;
        html += `<span class="mo-traces-col" style="flex:2">${ts}</span>`;
        html += '</div>';
      });

      html += '</div>';
      el.innerHTML = html;
    })
    .catch(() => {
      document.getElementById('beliefs-recent').innerHTML = '<div class="mo-empty-state">Blad ladowania</div>';
    });
}

// Initial load
loadBeliefs();
// Auto-refresh every 60s
setInterval(loadBeliefs, 60000);
