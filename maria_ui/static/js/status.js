/**
 * M.A.R.I.A. Status Page - Metaoperator Panel v2
 */

(function() {
  const M = MariaUI;
  let _activeFilter = 'ALL';
  let _allEvents = [];

  // --- Event filter tabs ---
  document.querySelectorAll('#eventFilter .mo-filter__tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('#eventFilter .mo-filter__tab').forEach(t => t.classList.remove('mo-filter__tab--active'));
      tab.classList.add('mo-filter__tab--active');
      _activeFilter = tab.dataset.filter;
      renderEvents();
    });
  });

  // --- Main fetch ---
  async function fetchStatus() {
    const data = await M.apiFetch('/api/status/full');
    if (!data) return;

    updateSystem(data.system, data.homeostasis);
    updateModels(data.models, data.nim, data.brain);
    updateOpenClaw(data.openclaw);
    updateVision(data.vision);
    updateHomeostasis(data.homeostasis);
    updatePlanner(data.planner, data.goals);
    updateMemory(data.memory);
    updateEvents(data.event_stream);
    updateIdentity(data.identity);

    // Topbar quick status
    M.updateTopbarStatus(
      data.homeostasis ? data.homeostasis.mode : 'ACTIVE',
      data.homeostasis ? data.homeostasis.health_score : 1.0
    );
  }


  // --- A. System ---
  function updateSystem(sys, homeo) {
    if (!sys) return;

    // Health
    const hs = homeo ? homeo.health_score : 1.0;
    const hsPercent = Math.round(hs * 100);
    const hsEl = M.$('sysHealth');
    hsEl.textContent = hsPercent + '%';
    hsEl.className = 'mo-big-value' + (hsPercent >= 90 ? ' mo-big-value--ok' : hsPercent >= 70 ? ' mo-big-value--warn' : ' mo-big-value--error');

    const hsBadge = M.$('sysHealthBadge');
    hsBadge.textContent = hsPercent >= 90 ? 'HEALTHY' : hsPercent >= 70 ? 'DEGRADED' : 'CRITICAL';
    hsBadge.className = 'mo-badge ' + (hsPercent >= 90 ? 'mo-badge--ok' : hsPercent >= 70 ? 'mo-badge--warn' : 'mo-badge--error');

    // RAM
    updateMetricBar('sysRam', 'sysRamBar', sys.ram.percent, '%', 70, 85,
      M.fmtGB(sys.ram.used_gb) + ' / ' + M.fmtGB(sys.ram.total_gb));

    // CPU
    updateMetricBar('sysCpu', 'sysCpuBar', sys.cpu.percent, '%', 70, 90,
      sys.cpu.cores + ' cores');

    // Disk
    updateMetricBar('sysDisk', 'sysDiskBar', sys.disk.percent, '%', 80, 90,
      M.fmtGB(sys.disk.free_gb) + ' free');

    // Uptime
    M.$('sysUptimeUi').textContent = M.fmtUptime(sys.uptime.ui_sec);
    M.$('sysUptimeSys').textContent = M.fmtUptime(sys.uptime.system_sec);

    // Alerts
    // Alert counters removed: homeostasis does not persist alerts to JSONL
  }

  function updateMetricBar(valueId, barId, value, unit, warnT, errorT, subtitle) {
    const valEl = M.$(valueId);
    const barEl = M.$(barId);
    const cc = M.colorClass(value, warnT, errorT);
    valEl.textContent = Math.round(value) + unit;
    valEl.className = 'mo-metric__value' + (cc ? ' mo-metric__value' + cc : '');
    barEl.style.width = Math.min(value, 100) + '%';
    barEl.className = 'mo-progress__fill ' + M.progressColor(value, warnT, errorT);
  }


  // --- B. Models / Routing ---
  function updateModels(models, nim, brain) {
    // Backend mode
    const badge = M.$('modelsBadge');
    const backendEl = M.$('modelsBackend');
    let backendMode = 'LOCAL ONLY';
    if (nim && nim.available && nim.backend === 'nim') backendMode = 'NIM ONLY';
    else if (nim && nim.available) backendMode = 'HYBRID';
    else if (brain && !brain.connected) backendMode = 'OFFLINE';
    backendEl.textContent = backendMode;
    badge.textContent = backendMode;
    badge.className = 'mo-badge ' + (backendMode === 'OFFLINE' ? 'mo-badge--error' : 'mo-badge--accent');

    // Free RAM
    const freeRam = models && models.scheduler ? models.scheduler.free_ram_gb : null;
    const freeRamEl = M.$('modelsFreeRam');
    if (freeRam != null) {
      freeRamEl.textContent = M.fmtGB(freeRam);
      const ramCc = M.colorClassInverse(freeRam, 10, 7);
      freeRamEl.className = 'mo-metric__value mo-text-sm' + (ramCc ? ' mo-metric__value' + ramCc : '');
    }

    // Token budget
    if (nim && nim.budget) {
      M.$('modelsDailyBudget').textContent = M.fmtPercent(nim.budget.daily_percent);
      M.$('modelsDailyBar').style.width = Math.min(nim.budget.daily_percent, 100) + '%';
      M.$('modelsMonthlyBudget').textContent = M.fmtPercent(nim.budget.monthly_percent);
      M.$('modelsMonthlyBar').style.width = Math.min(nim.budget.monthly_percent, 100) + '%';
    }

    // Model list
    const listEl = M.$('modelsList');
    if (models && models.registry) {
      const loaded = (models.scheduler && models.scheduler.loaded_models) || {};
      let html = '';
      for (const spec of models.registry) {
        const role = spec.role;
        const isLoaded = !!loaded[role];
        const badge = M.modelStatusBadge(spec.warm_state, isLoaded);
        const lm = loaded[role] || {};
        const reqs = lm.total_requests || 0;
        const healthDot = lm.healthy === false ? 'mo-pulse--error' : (isLoaded ? 'mo-pulse--ok' : 'mo-pulse--off');

        html += '<div class="mo-model">' +
          '<span class="mo-model__role">' + M.escapeHtml(role) + '</span>' +
          '<span class="mo-model__tag">' + M.escapeHtml(spec.ollama_tag || '--') + '</span>' +
          '<span class="mo-badge ' + badge.cls + '">' + badge.text + '</span>' +
          '<span class="mo-model__ram">' + (spec.ram_estimate_gb > 0 ? spec.ram_estimate_gb + 'G' : '--') + '</span>' +
          '<span class="mo-model__reqs">' + reqs + '</span>' +
          '<span class="mo-model__health"><span class="mo-pulse ' + healthDot + '"></span></span>' +
          '</div>';
      }
      listEl.innerHTML = html;
    }

    // Fallback chain
    const chainEl = M.$('modelsFallback');
    if (models && models.registry) {
      const loaded = (models.scheduler && models.scheduler.loaded_models) || {};
      const chains = [
        { role: 'Planner', chain: ['planner', 'executor', 'triage'] },
        { role: 'Coder', chain: ['coder', 'executor'] },
        { role: 'Memory', chain: ['memory'] },
      ];
      let html = '';
      for (const c of chains) {
        html += '<div class="mo-chain__row"><span class="mo-chain__role">' + c.role + '</span>';
        for (let i = 0; i < c.chain.length; i++) {
          if (i > 0) html += '<span class="mo-chain__arrow">-></span>';
          const r = c.chain[i];
          const isActive = !!loaded[r];
          html += '<span class="mo-chain__node' + (isActive ? ' mo-chain__node--active' : '') + '">' + r + '</span>';
        }
        html += '</div>';
      }
      chainEl.innerHTML = html;
    }

    // Mutex
    const mutexEl = M.$('modelsMutex');
    if (models && models.scheduler) {
      const loadedKeys = Object.keys(models.scheduler.loaded_models || {});
      const heavyLoaded = loadedKeys.filter(k => k === 'planner' || k === 'coder');
      mutexEl.textContent = heavyLoaded.length > 0 ? 'LOCKED (' + heavyLoaded.join(', ') + ')' : 'FREE';
      mutexEl.className = 'mo-metric__value mo-text-sm' + (heavyLoaded.length > 0 ? ' mo-metric__value--warn' : ' mo-metric__value--muted');
    }

    // Executor state (derive from brain)
    const execEl = M.$('modelsExecutorState');
    if (brain && brain.connected) {
      execEl.textContent = 'READY';
      execEl.className = 'mo-opstate mo-opstate--active';
    } else {
      execEl.textContent = 'OFFLINE';
      execEl.className = 'mo-opstate mo-opstate--error';
    }
  }


  // --- C. OpenClaw ---
  function updateOpenClaw(claw) {
    if (!claw) return;

    const badge = M.$('clawBadge');
    badge.textContent = claw.connected ? 'ONLINE' : 'OFFLINE';
    badge.className = 'mo-badge ' + (claw.connected ? 'mo-badge--ok' : 'mo-badge--error');

    const stateEl = M.$('clawState');
    if (claw.connected) {
      stateEl.textContent = 'IDLE';
      stateEl.className = 'mo-opstate mo-opstate--idle';
    } else {
      stateEl.textContent = 'DISCONNECTED';
      stateEl.className = 'mo-opstate mo-opstate--error';
    }

    M.$('clawCalls').textContent = M.fmtNumber(claw.total_calls);
    const successRate = claw.total_calls > 0
      ? Math.round(claw.successful_calls / claw.total_calls * 100) + '%'
      : '--';
    M.$('clawSuccess').textContent = successRate;
    M.$('clawFailed').textContent = M.fmtNumber(claw.failed_calls);
    M.$('clawError').textContent = claw.last_error || 'none';
    M.$('clawError').title = claw.last_error || '';
  }


  // --- I. Vision ---
  function updateVision(v) {
    if (!v || !v.available) {
      const badge = M.$('visionBadge');
      if (badge) { badge.textContent = 'OFFLINE'; badge.className = 'mo-badge mo-badge--error'; }
      return;
    }

    const badge = M.$('visionBadge');
    const healthPct = Math.round((v.health_overall || 0) * 100);
    badge.textContent = v.degradation || 'unknown';
    badge.className = 'mo-badge ' + (healthPct >= 60 ? 'mo-badge--ok' : healthPct >= 30 ? 'mo-badge--warn' : 'mo-badge--error');

    M.$('visionHealth').textContent = healthPct + '%';
    const healthBar = M.$('visionHealthBar');
    healthBar.style.width = healthPct + '%';
    healthBar.className = 'mo-progress__fill ' + (healthPct >= 60 ? 'mo-progress__fill--ok' : healthPct >= 30 ? 'mo-progress__fill--warn' : 'mo-progress__fill--error');

    M.$('visionQuality').textContent = Math.round((v.quality || 0) * 100) + '%';
    M.$('visionDegradation').textContent = v.degradation || '--';
    M.$('visionSensor').textContent = v.active_sensor || 'brak';
    M.$('visionSummary').textContent = v.summary || '--';

    // Refresh thumbnail
    const thumb = M.$('visionThumb');
    if (thumb && v.has_frame) {
      thumb.src = '/api/vision/frame?t=' + Date.now();
      thumb.style.display = 'block';
    }
  }


  // --- D. Homeostasis ---
  function updateHomeostasis(homeo) {
    if (!homeo) return;

    const mode = homeo.mode || 'ACTIVE';
    const modeEl = M.$('homeoMode');
    modeEl.textContent = mode;
    modeEl.className = 'mo-badge ' + M.modeBadgeClass(mode);

    // Pulse
    const pulseEl = M.$('homeoPulse');
    pulseEl.className = 'mo-pulse ' + (mode === 'ACTIVE' ? 'mo-pulse--ok' : mode === 'REDUCED' ? 'mo-pulse--warn' : 'mo-pulse--error');

    // Cause (WHY)
    M.$('homeoCause').textContent = homeo.cause || '--';

    // Health
    const hp = Math.round((homeo.health_score || 1) * 100);
    M.$('homeoHealth').textContent = hp + '%';
    M.$('homeoHealthBar').style.width = hp + '%';
    M.$('homeoHealthBar').className = 'mo-progress__fill ' + (hp >= 90 ? 'mo-progress__fill--ok' : hp >= 70 ? 'mo-progress__fill--warn' : 'mo-progress__fill--error');

    M.$('homeoModeChanges').textContent = homeo.mode_changes_count || 0;
    M.$('homeoConnected').textContent = homeo.connected ? 'YES' : 'NO';
    M.$('homeoConnected').className = 'mo-metric__value' + (homeo.connected ? ' mo-metric__value--ok' : ' mo-metric__value--error');
  }


  // --- E. Planner ---
  function updatePlanner(planner, goals) {
    if (!planner) return;

    // Op-state
    const stateEl = M.$('plannerState');
    let opState = 'idle';
    if (planner.last_decision) {
      const action = (planner.last_decision.action || '').toLowerCase();
      const status = (planner.last_decision.status || '').toLowerCase();
      if (status === 'guard_blocked') opState = 'blocked';
      else if (action === 'learn' || action === 'exam') opState = 'learning';
      else if (action === 'noop' || action === 'skip') opState = 'idle';
      else opState = 'active';
    }
    stateEl.textContent = opState.toUpperCase();
    stateEl.className = 'mo-opstate ' + M.opStateClass(opState);

    // Metrics
    M.$('plannerCycles').textContent = M.fmtNumber(planner.total_cycles);
    M.$('plannerPlans').textContent = M.fmtNumber(planner.total_plans);

    if (planner.last_decision) {
      const ld = planner.last_decision;
      M.$('plannerLastTime').textContent = M.fmtAge(ld.timestamp);
      M.$('plannerAction').textContent = (ld.action || '--').toUpperCase();
      M.$('plannerMessage').textContent = ld.message || '--';
      M.$('plannerMessage').title = ld.message || '';
    }

    // Human Gate
    const proposed = goals ? goals.proposed_count : 0;
    const gateEl = M.$('plannerGate');
    const gateCountEl = M.$('plannerGateCount');
    const gateLabelEl = M.$('plannerGateLabel');
    gateCountEl.textContent = proposed;
    if (proposed > 0) {
      gateEl.className = 'mo-gate mo-gate--pending';
      gateLabelEl.textContent = proposed + ' awaiting approval';
    } else {
      gateEl.className = 'mo-gate mo-gate--clear';
      gateLabelEl.textContent = 'no pending approvals';
    }
  }


  // --- F. Memory ---
  function updateMemory(mem) {
    if (!mem) return;

    // Stats grid
    const sg = mem.semantic_graph || {};
    const ki = mem.knowledge_index || {};
    const lt = mem.longterm_memory || {};
    const cog = mem.cognitive || {};

    M.$('memNodes').textContent = M.fmtNumber(sg.nodes);
    M.$('memEdges').textContent = M.fmtNumber(sg.edges);
    M.$('memKnowledge').textContent = M.fmtNumber(ki.entries);
    M.$('memLongterm').textContent = M.fmtNumber(lt.entries);
    M.$('memBeliefs').textContent = M.fmtNumber(cog.beliefs);
    M.$('memReflections').textContent = M.fmtNumber(cog.reflections);
    M.$('memAudit').textContent = M.fmtNumber(cog.action_audit);
    M.$('memAutonomy').textContent = M.fmtNumber(cog.autonomy_decisions);

    // Integrity badge
    const intBadge = M.integrityBadge(mem.integrity);
    const intEl = M.$('memIntegrity');
    intEl.textContent = intBadge.text;
    intEl.className = 'mo-badge ' + intBadge.cls;
  }


  // --- G. Event Stream ---
  function updateEvents(events) {
    if (!events) return;
    _allEvents = events;
    M.$('eventCount').textContent = events.length;
    renderEvents();
  }

  function renderEvents() {
    const el = M.$('eventStream');
    const filtered = _activeFilter === 'ALL'
      ? _allEvents
      : _allEvents.filter(e => e.source === _activeFilter);

    if (filtered.length === 0) {
      el.innerHTML = '<div class="mo-text-sm mo-muted" style="padding:var(--mo-sp-4);text-align:center">No events</div>';
      return;
    }

    let html = '';
    for (const evt of filtered) {
      const sourceClass = 'mo-event__source--' + (evt.source || 'system');
      const sevClass = 'mo-event__severity--' + (evt.severity || 'info');
      html += '<div class="mo-event">' +
        '<span class="mo-event__time">' + M.fmtTimestamp(evt.timestamp) + '</span>' +
        '<span class="mo-event__source ' + sourceClass + '">' + M.escapeHtml(evt.source || '--') + '</span>' +
        '<span class="mo-event__type">' + M.escapeHtml(evt.type || '--') + '</span>' +
        '<span class="mo-event__detail">' + M.escapeHtml(evt.details || '') + '</span>' +
        '<span class="mo-event__severity ' + sevClass + '"></span>' +
        '</div>';
    }
    el.innerHTML = html;
  }


  // --- H. Identity ---
  function updateIdentity(id) {
    if (!id) return;

    M.$('idName').textContent = id.name || 'M.A.R.I.A.';
    M.$('idBorn').textContent = id.birth_date
      ? M.fmtDate(id.birth_date) + ' (' + M.fmtDaysSince(id.birth_date) + ')'
      : '--';
    M.$('idSessions').textContent = M.fmtNumber(id.session_count);
    M.$('idRestarts').textContent = M.fmtNumber(id.restart_count);
    M.$('idUptime').textContent = id.total_uptime_hours
      ? Math.round(id.total_uptime_hours) + 'h'
      : '--';
    M.$('idOperator').textContent = id.primary_user || '--';
    M.$('idFeeling').textContent = id.feeling || '--';

    // Traits
    const traitsEl = M.$('idTraits');
    if (id.traits && Object.keys(id.traits).length > 0) {
      let html = '';
      for (const [name, score] of Object.entries(id.traits)) {
        const pct = Math.round(score * 100);
        html += '<div class="mo-trait">' +
          '<span class="mo-trait__name">' + M.escapeHtml(name) + '</span>' +
          '<div class="mo-trait__bar"><div class="mo-trait__fill" style="width:' + pct + '%"></div></div>' +
          '<span class="mo-trait__score">' + score.toFixed(2) + '</span>' +
          '</div>';
      }
      traitsEl.innerHTML = html;
    }
  }


  // --- Init ---
  M.getSocket();
  M.startAutoRefresh(fetchStatus, 3000);

})();
