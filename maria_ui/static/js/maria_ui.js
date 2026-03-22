/**
 * M.A.R.I.A. Metaoperator Panel - Shared Utilities v2
 */

const MariaUI = {

  // --- DOM helpers ---

  $(id) { return document.getElementById(id); },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },


  // --- API helper ---

  async apiFetch(url, opts = {}) {
    try {
      const res = await fetch(url, opts);
      if (res.status === 401 || (res.redirected && res.url.includes('/login'))) {
        window.location.href = '/login';
        return null;
      }
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      console.error('[MariaUI] apiFetch error:', url, e);
      return null;
    }
  },


  // --- Formatting (raw -> display, never in API) ---

  fmtUptime(seconds) {
    if (seconds == null) return '--';
    if (seconds < 60) return Math.floor(seconds) + 's';
    if (seconds < 3600) return (seconds / 60).toFixed(1) + 'm';
    if (seconds < 86400) return (seconds / 3600).toFixed(1) + 'h';
    return (seconds / 86400).toFixed(1) + 'd';
  },

  fmtTimestamp(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  },

  fmtAge(ts) {
    if (!ts) return '--';
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  },

  fmtPercent(value) {
    if (value == null) return '--';
    return Math.round(value) + '%';
  },

  fmtGB(value) {
    if (value == null) return '--';
    return value.toFixed(1) + ' GB';
  },

  fmtNumber(value) {
    if (value == null) return '--';
    return value.toLocaleString('pl-PL');
  },

  fmtDate(dateStr) {
    if (!dateStr) return '--';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('pl-PL');
    } catch(e) { return dateStr; }
  },

  fmtDaysSince(dateStr) {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      const diff = Math.floor((Date.now() - d.getTime()) / 86400000);
      return diff + ' days';
    } catch(e) { return ''; }
  },


  // --- Color helpers ---

  colorClass(value, warnThreshold, errorThreshold) {
    if (value == null) return '';
    if (value >= errorThreshold) return '--error';
    if (value >= warnThreshold) return '--warn';
    return '';
  },

  colorClassInverse(value, warnThreshold, errorThreshold) {
    if (value == null) return '';
    if (value <= errorThreshold) return '--error';
    if (value <= warnThreshold) return '--warn';
    return '--ok';
  },

  progressColor(value, warnThreshold, errorThreshold) {
    if (value >= errorThreshold) return 'mo-progress__fill--error';
    if (value >= warnThreshold) return 'mo-progress__fill--warn';
    return 'mo-progress__fill--ok';
  },


  // --- Op-State helper ---

  opStateClass(state) {
    const map = {
      'idle': 'mo-opstate--idle',
      'active': 'mo-opstate--active',
      'processing': 'mo-opstate--processing',
      'learning': 'mo-opstate--learning',
      'blocked': 'mo-opstate--blocked',
      'error': 'mo-opstate--error',
      'waiting': 'mo-opstate--waiting',
    };
    return map[(state || 'idle').toLowerCase()] || 'mo-opstate--idle';
  },


  // --- Badge helpers ---

  modeBadgeClass(mode) {
    const m = (mode || 'active').toLowerCase();
    return 'mo-badge--' + m;
  },

  modelStatusBadge(warmState, isLoaded) {
    if (warmState === 'EXTERNAL') return { cls: 'mo-badge--external', text: 'EXTERNAL' };
    if (warmState === 'RULE_BASED' || warmState === 'rule_based') return { cls: 'mo-badge--rule', text: 'RULE-BASED' };
    if (isLoaded) return { cls: 'mo-badge--loaded', text: 'LOADED' };
    return { cls: 'mo-badge--cold', text: 'COLD' };
  },

  integrityBadge(flags) {
    if (!flags) return { cls: 'mo-badge--off', text: 'N/A' };
    const checks = [
      flags.has_graph_nodes,
      flags.has_longterm,
      flags.has_knowledge,
      flags.last_memory_update_ts && (Date.now() / 1000 - flags.last_memory_update_ts) < 86400,
    ];
    const passed = checks.filter(Boolean).length;
    if (passed >= 4) return { cls: 'mo-badge--ok', text: 'OK' };
    if (passed >= 2) return { cls: 'mo-badge--warn', text: 'PARTIAL' };
    return { cls: 'mo-badge--error', text: 'DEGRADED' };
  },


  // --- Toast Notification System ---

  _toastDedup: {},  // title -> timestamp

  showToast(type, title, message) {
    // Dedup: skip if same title within 5s
    const now = Date.now();
    const key = title;
    if (this._toastDedup[key] && now - this._toastDedup[key] < 5000) return;
    this._toastDedup[key] = now;

    const container = this.$('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'mo-toast mo-toast--' + (type || 'info');
    toast.innerHTML =
      '<div class="mo-toast__title">' + this.escapeHtml(title) + '</div>' +
      '<div class="mo-toast__message">' + this.escapeHtml(message) + '</div>';

    toast.addEventListener('click', () => {
      toast.classList.add('mo-toast--dismiss');
      setTimeout(() => toast.remove(), 300);
    });

    container.appendChild(toast);

    // Auto-dismiss based on severity
    const timeouts = { info: 5000, ok: 5000, warn: 7000, error: 10000, critical: 0 };
    const timeout = timeouts[type] || 5000;
    if (timeout > 0) {
      setTimeout(() => {
        if (toast.parentNode) {
          toast.classList.add('mo-toast--dismiss');
          setTimeout(() => toast.remove(), 300);
        }
      }, timeout);
    }

    // Keep max 5 toasts
    while (container.children.length > 5) {
      container.firstChild.remove();
    }
  },


  // --- Socket.IO (lazy init) ---

  _socket: null,

  getSocket() {
    if (!this._socket && typeof io !== 'undefined') {
      this._socket = io();

      this._socket.on('proactive_notification', (data) => {
        const typeMap = {
          'mode_change': 'info',
          'warning': 'warn',
          'alert': 'error',
          'system_info': 'info',
          'learning_complete': 'ok',
          'planner_decision': 'info',
        };
        this.showToast(
          typeMap[data.type] || 'info',
          data.title || 'Notification',
          data.message || ''
        );
      });
    }
    return this._socket;
  },


  // --- Auto-refresh ---

  _refreshInterval: null,
  _refreshCounter: 0,
  _refreshMax: 3,

  startAutoRefresh(callback, intervalMs = 3000) {
    this._refreshMax = Math.round(intervalMs / 1000);
    this._refreshCounter = this._refreshMax;

    // Initial call
    callback();

    this._refreshInterval = setInterval(() => {
      this._refreshCounter--;
      const timer = this.$('refreshTimer');
      if (timer) timer.textContent = this._refreshCounter;

      if (this._refreshCounter <= 0) {
        this._refreshCounter = this._refreshMax;
        callback();
      }
    }, 1000);
  },

  stopAutoRefresh() {
    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
      this._refreshInterval = null;
    }
  },


  // --- Topbar status updater ---

  updateTopbarStatus(mode, healthScore) {
    const el = this.$('topbarStatus');
    if (!el) return;
    const pulseClass = mode === 'ACTIVE' ? 'mo-pulse--ok' :
                       mode === 'REDUCED' ? 'mo-pulse--warn' : 'mo-pulse--error';
    el.innerHTML = '<span class="mo-pulse ' + pulseClass + '"></span> ' +
                   '<span>' + this.escapeHtml(mode || '--') + '</span>';
  },
};
