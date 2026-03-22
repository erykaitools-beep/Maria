/**
 * M.A.R.I.A. Architecture Map v2
 * Force-directed graph + Pipeline + Data Flow views
 */

(function() {
  const M = MariaUI;

  // ── State ──────────────────────────────────────────────
  let archData = null;
  let nodes = [];
  let edges = [];
  let selectedNode = null;
  let hoveredNode = null;

  let canvas, ctx;
  let offsetX = 0, offsetY = 0, scale = 1;
  let isDragging = false, dragStartX = 0, dragStartY = 0;
  let dragNode = null;

  const COLORS = {
    homeostasis: '#f0883e', planner: '#58a6ff', perception: '#d2a8ff',
    deliberation: '#7ee787', autonomy: '#f85149', world_model: '#79c0ff',
    meta_cognition: '#e3b341', action_safety: '#f778ba', experiment: '#a5d6ff',
    goals: '#56d364', evaluation: '#ffa657', sandbox: '#ff7b72',
    teacher: '#d2a8ff', consciousness: '#bc8cff', web_source: '#79c0ff',
    introspection: '#8b949e', memory: '#7ee787', llm: '#ffa657',
    registry: '#8b949e', modules: '#58a6ff', adapters: '#8b949e',
    executor: '#8b949e', metacontrol: '#8b949e', awareness: '#bc8cff',
    ui: '#f0883e', storage: '#56d364', effector: '#ffaa00',
    maria_core: '#484f58', maria_ui: '#f0883e', models: '#8b949e',
  };

  function getColor(name) { return COLORS[name] || '#8b949e'; }

  // ── Init ───────────────────────────────────────────────
  async function init() {
    canvas = document.getElementById('graphCanvas');
    ctx = canvas.getContext('2d');
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('wheel', onWheel);
    canvas.addEventListener('dblclick', onDblClick);

    document.getElementById('searchInput').addEventListener('input', onSearch);

    try {
      const resp = await fetch('/api/architecture');
      archData = await resp.json();
      buildGraph();
      buildSidebar();
      buildPipeline();
      buildDataFlow();
      updateStats();
      animate();
    } catch (e) {
      console.error('Failed to load architecture data:', e);
    }
  }

  function resizeCanvas() {
    const area = document.getElementById('graphArea');
    canvas.width = area.clientWidth;
    canvas.height = area.clientHeight;
  }

  // ── Build graph ────────────────────────────────────────
  function buildGraph() {
    if (!archData || !archData.packages) return;
    nodes = [];
    edges = [];

    const pkgs = Object.keys(archData.packages);
    const cx = canvas.width / 2, cy = canvas.height / 2;
    const radius = Math.min(cx, cy) * 0.6;

    pkgs.forEach((name, i) => {
      const angle = (i / pkgs.length) * Math.PI * 2 - Math.PI / 2;
      const pkg = archData.packages[name];
      const size = Math.max(20, Math.min(50, Math.sqrt(pkg.total_lines / 10)));

      nodes.push({
        id: name,
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        vx: 0, vy: 0,
        size: size,
        color: getColor(name),
        label: name,
        files: pkg.files ? pkg.files.length : 0,
        lines: pkg.total_lines || 0,
        functions: pkg.total_functions || 0,
        classes: pkg.total_classes || 0,
      });
    });

    if (archData.edges) {
      archData.edges.forEach(e => {
        const from = nodes.find(n => n.id === e.from);
        const to = nodes.find(n => n.id === e.to);
        if (from && to) edges.push({ from, to, type: e.type });
      });
    }
  }

  // ── Physics ────────────────────────────────────────────
  function simulate() {
    const damping = 0.9, repulsion = 8000, attraction = 0.005, centerPull = 0.001;
    const cx = canvas.width / 2, cy = canvas.height / 2;

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = repulsion / (dist * dist);
        let fx = (dx / dist) * force, fy = (dy / dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }

    edges.forEach(e => {
      let dx = e.to.x - e.from.x, dy = e.to.y - e.from.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      let force = dist * attraction;
      let fx = (dx / dist) * force, fy = (dy / dist) * force;
      e.from.vx += fx; e.from.vy += fy;
      e.to.vx -= fx; e.to.vy -= fy;
    });

    nodes.forEach(n => {
      n.vx += (cx - n.x) * centerPull;
      n.vy += (cy - n.y) * centerPull;
    });

    nodes.forEach(n => {
      if (n === dragNode) return;
      n.vx *= damping; n.vy *= damping;
      n.x += n.vx; n.y += n.vy;
    });
  }

  // ── Render ─────────────────────────────────────────────
  function render() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);

    edges.forEach(e => {
      ctx.beginPath();
      ctx.moveTo(e.from.x, e.from.y);
      ctx.lineTo(e.to.x, e.to.y);
      ctx.strokeStyle = 'rgba(48, 54, 61, 0.6)';
      ctx.lineWidth = 1;
      if (selectedNode && (e.from.id === selectedNode.id || e.to.id === selectedNode.id)) {
        ctx.strokeStyle = 'rgba(0, 212, 255, 0.4)'; ctx.lineWidth = 2;
      }
      if (hoveredNode && (e.from.id === hoveredNode.id || e.to.id === hoveredNode.id)) {
        ctx.strokeStyle = 'rgba(0, 212, 255, 0.6)'; ctx.lineWidth = 2;
      }
      ctx.stroke();
    });

    nodes.forEach(n => {
      const isSelected = selectedNode && selectedNode.id === n.id;
      const isHovered = hoveredNode && hoveredNode.id === n.id;
      const active = selectedNode || hoveredNode;
      const isConnected = active && edges.some(e =>
        (e.from.id === active.id && e.to.id === n.id) ||
        (e.to.id === active.id && e.from.id === n.id)
      );

      let alpha = 1.0;
      if (active && !isSelected && !isHovered && !isConnected) alpha = 0.25;

      ctx.beginPath();
      ctx.arc(n.x, n.y, n.size, 0, Math.PI * 2);
      ctx.fillStyle = n.color + Math.round(alpha * 255).toString(16).padStart(2, '0');
      ctx.fill();

      if (isSelected) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 3; ctx.stroke(); }
      else if (isHovered) { ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 2; ctx.stroke(); }

      ctx.fillStyle = 'rgba(230, 237, 243, ' + alpha + ')';
      ctx.font = Math.max(11, n.size * 0.5) + "px 'Segoe UI', sans-serif";
      ctx.textAlign = 'center';
      ctx.fillText(n.label, n.x, n.y + n.size + 14);
    });

    ctx.restore();
  }

  function animate() { simulate(); render(); requestAnimationFrame(animate); }

  // ── Mouse events ───────────────────────────────────────
  function screenToWorld(sx, sy) {
    return { x: (sx - offsetX) / scale, y: (sy - offsetY) / scale };
  }

  function hitTest(sx, sy) {
    const {x, y} = screenToWorld(sx, sy);
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = n.x - x, dy = n.y - y;
      if (dx * dx + dy * dy < n.size * n.size) return n;
    }
    return null;
  }

  function onMouseDown(e) {
    const node = hitTest(e.offsetX, e.offsetY);
    if (node) {
      dragNode = node; selectedNode = node;
      showDetail(node.id); highlightSidebar(node.id);
    } else {
      isDragging = true; selectedNode = null; closeDetail();
    }
    dragStartX = e.offsetX; dragStartY = e.offsetY;
  }

  function onMouseMove(e) {
    if (dragNode) {
      const {x, y} = screenToWorld(e.offsetX, e.offsetY);
      dragNode.x = x; dragNode.y = y; dragNode.vx = 0; dragNode.vy = 0;
    } else if (isDragging) {
      offsetX += e.offsetX - dragStartX; offsetY += e.offsetY - dragStartY;
      dragStartX = e.offsetX; dragStartY = e.offsetY;
    } else {
      const node = hitTest(e.offsetX, e.offsetY);
      hoveredNode = node;
      canvas.style.cursor = node ? 'pointer' : 'grab';
      const tooltip = document.getElementById('tooltip');
      if (node) {
        tooltip.innerHTML = '<div class="tt-name">' + node.label + '</div>' +
          '<div class="tt-stats">' + node.files + ' files, ' + node.lines + ' lines, ' +
          node.functions + ' functions, ' + node.classes + ' classes</div>';
        tooltip.style.display = 'block';
        tooltip.style.left = (e.offsetX + 280 + 15) + 'px';
        tooltip.style.top = (e.offsetY + 45 + 15) + 'px';
      } else {
        tooltip.style.display = 'none';
      }
    }
  }

  function onMouseUp() { dragNode = null; isDragging = false; }

  function onWheel(e) {
    e.preventDefault();
    scale *= e.deltaY > 0 ? 0.9 : 1.1;
    scale = Math.max(0.3, Math.min(3, scale));
  }

  function onDblClick(e) {
    const node = hitTest(e.offsetX, e.offsetY);
    if (node) { selectedNode = node; showDetail(node.id); }
  }

  // Expose zoom functions for buttons
  window.zoomIn = function() { scale = Math.min(3, scale * 1.2); };
  window.zoomOut = function() { scale = Math.max(0.3, scale * 0.8); };
  window.resetView = function() { scale = 1; offsetX = 0; offsetY = 0; };

  // ── Sidebar ────────────────────────────────────────────
  function buildSidebar() {
    if (!archData || !archData.packages) return;
    const list = document.getElementById('pkgList');
    const sorted = Object.keys(archData.packages).sort();
    list.innerHTML = sorted.map(name => {
      const pkg = archData.packages[name];
      const fc = pkg.files ? pkg.files.length : 0;
      const lc = pkg.total_lines || 0;
      return '<div class="mo-arch-pkg" data-pkg="' + name + '" onclick="selectPackage(\'' + name + '\')">' +
        '<div class="mo-arch-pkg__name" style="color:' + getColor(name) + '">' + name + '</div>' +
        '<div class="mo-arch-pkg__meta">' + fc + ' files, ' + lc + ' lines</div></div>';
    }).join('');
  }

  window.selectPackage = function(name) {
    selectedNode = nodes.find(n => n.id === name) || null;
    showDetail(name); highlightSidebar(name);
  };

  function highlightSidebar(name) {
    document.querySelectorAll('.mo-arch-pkg').forEach(el => {
      el.classList.toggle('mo-arch-pkg--active', el.dataset.pkg === name);
    });
  }

  function onSearch(e) {
    const q = e.target.value.toLowerCase().trim();
    document.querySelectorAll('.mo-arch-pkg').forEach(el => {
      if (!q) { el.classList.remove('mo-hidden'); return; }
      const name = el.dataset.pkg;
      const pkg = archData.packages[name];
      let match = name.toLowerCase().includes(q);
      if (!match && pkg && pkg.files) {
        for (const f of pkg.files) {
          if (f.package.toLowerCase().includes(q)) { match = true; break; }
          if (f.functions && f.functions.some(fn => fn.name.toLowerCase().includes(q))) { match = true; break; }
          if (f.classes && f.classes.some(c => c.name.toLowerCase().includes(q))) { match = true; break; }
        }
      }
      el.classList.toggle('mo-hidden', !match);
    });
  }

  // ── Detail panel ───────────────────────────────────────
  function showDetail(pkgName) {
    const panel = document.getElementById('detailPanel');
    const content = document.getElementById('detailContent');
    const pkg = archData.packages[pkgName];
    if (!pkg) { panel.classList.remove('mo-arch-detail--open'); return; }

    let html = '<h2 style="color:' + getColor(pkgName) + '">' + M.escapeHtml(pkgName) + '</h2>';

    const fc = pkg.files ? pkg.files.length : 0;
    html += '<div class="mo-metric"><span class="mo-metric__label">Files</span><span class="mo-metric__value">' + fc + '</span></div>';
    html += '<div class="mo-metric"><span class="mo-metric__label">Lines</span><span class="mo-metric__value">' + (pkg.total_lines || 0) + '</span></div>';
    html += '<div class="mo-metric"><span class="mo-metric__label">Functions</span><span class="mo-metric__value">' + (pkg.total_functions || 0) + '</span></div>';
    html += '<div class="mo-metric"><span class="mo-metric__label">Classes</span><span class="mo-metric__value">' + (pkg.total_classes || 0) + '</span></div>';

    // Connected packages
    const connected = edges
      .filter(e => e.from.id === pkgName || e.to.id === pkgName)
      .map(e => e.from.id === pkgName ? e.to.id : e.from.id)
      .filter((v, i, a) => a.indexOf(v) === i);
    if (connected.length) {
      html += '<h3 class="mo-mt-3 mo-text-sm mo-accent">Connections (' + connected.length + ')</h3>';
      html += '<div class="mo-flex mo-gap-2" style="flex-wrap:wrap">';
      connected.forEach(c => {
        html += '<span class="mo-badge mo-badge--off" style="color:' + getColor(c) + ';cursor:pointer" onclick="selectPackage(\'' + c + '\')">' + c + '</span>';
      });
      html += '</div>';
    }

    // Data flow
    const relatedFlow = Object.entries(archData.data_flow || {}).filter(([file, flow]) =>
      flow.writers.some(w => w.startsWith('agent_core.' + pkgName)) ||
      flow.readers.some(r => r.startsWith('agent_core.' + pkgName))
    );
    if (relatedFlow.length) {
      html += '<h3 class="mo-mt-3 mo-text-sm mo-accent">Data Files</h3>';
      relatedFlow.forEach(([file, flow]) => {
        const isWriter = flow.writers.some(w => w.startsWith('agent_core.' + pkgName));
        const isReader = flow.readers.some(r => r.startsWith('agent_core.' + pkgName));
        const rw = [];
        if (isWriter) rw.push('<span class="mo-badge mo-badge--warn" style="font-size:0.6rem">W</span>');
        if (isReader) rw.push('<span class="mo-badge mo-badge--info" style="font-size:0.6rem">R</span>');
        html += '<div class="mo-text-xs mo-mt-2">' + rw.join(' ') + ' <span class="mo-mono">' + file + '</span></div>';
      });
    }

    // Files
    if (pkg.files && pkg.files.length) {
      html += '<h3 class="mo-mt-3 mo-text-sm mo-accent">Files (' + pkg.files.length + ')</h3>';
      pkg.files.forEach(f => {
        const shortPath = f.file.split('/').slice(-1)[0];
        html += '<div class="mo-mt-2" style="cursor:pointer" onclick="this.querySelector(\'.fd\').style.display=this.querySelector(\'.fd\').style.display===\'none\'?\'block\':\'none\'">' +
          '<div class="mo-text-sm">' + M.escapeHtml(shortPath) + ' <span class="mo-muted">(' + f.lines + ' lines)</span></div>' +
          '<div class="mo-text-xs mo-muted">' + M.escapeHtml(f.docstring || '') + '</div>' +
          '<div class="fd" style="display:none;padding-left:var(--mo-sp-3);margin-top:var(--mo-sp-1)">';
        if (f.classes && f.classes.length) {
          f.classes.forEach(c => {
            html += '<div class="mo-text-xs mo-accent">' + c.name + '</div>';
            if (c.methods) c.methods.forEach(m => {
              html += '<div class="mo-text-xs mo-muted" style="padding-left:var(--mo-sp-3)">.' + m + '</div>';
            });
          });
        }
        if (f.functions && f.functions.length) {
          f.functions.forEach(fn => {
            html += '<div class="mo-text-xs mo-secondary">' + fn.name + '(' + fn.params.filter(p => p !== 'self').join(', ') + ')</div>';
          });
        }
        html += '</div></div>';
      });
    }

    content.innerHTML = html;
    panel.classList.add('mo-arch-detail--open');
  }

  window.closeDetail = function() {
    document.getElementById('detailPanel').classList.remove('mo-arch-detail--open');
    selectedNode = null;
  };

  // ── Views ──────────────────────────────────────────────
  window.switchView = function(name, el) {
    document.querySelectorAll('.mo-filter__tab[data-view]').forEach(t => t.classList.remove('mo-filter__tab--active'));
    if (el) el.classList.add('mo-filter__tab--active');
    M.$('view-graph').style.display = name === 'graph' ? 'block' : 'none';
    M.$('view-pipeline').style.display = name === 'pipeline' ? 'block' : 'none';
    M.$('view-dataflow').style.display = name === 'dataflow' ? 'block' : 'none';
  };

  function buildPipeline() {
    if (!archData || !archData.pipeline) return;
    const container = M.$('pipelineContainer');
    let html = '<h2 class="mo-text-xl mo-accent mo-mb-3">Decision Pipeline (Homeostasis Tick Loop)</h2>';
    archData.pipeline.forEach((step, i) => {
      const isLast = i === archData.pipeline.length - 1;
      const mod = step.module.split('.')[1] || step.module;
      html += '<div style="display:flex;gap:var(--mo-sp-3);margin-bottom:var(--mo-sp-2)">' +
        '<div style="display:flex;flex-direction:column;align-items:center;width:20px">' +
        '<div style="width:10px;height:10px;border-radius:50%;background:var(--mo-accent);flex-shrink:0"></div>' +
        (!isLast ? '<div style="width:2px;flex:1;background:var(--mo-border)"></div>' : '') +
        '</div>' +
        '<div class="mo-card" style="flex:1;padding:var(--mo-sp-3);cursor:pointer" onclick="selectPackage(\'' + mod + '\')">' +
        '<div class="mo-text-xs mo-muted">Phase ' + step.phase + '</div>' +
        '<div class="mo-text-sm mo-accent" style="font-weight:600">' + step.label + '</div>' +
        '<div class="mo-text-xs mo-mono mo-muted">' + step.module + '</div>' +
        '<div class="mo-text-xs mo-secondary mo-mt-2">' + step.description + '</div>' +
        '</div></div>';
    });
    container.innerHTML = html;
  }

  function buildDataFlow() {
    if (!archData || !archData.data_flow) return;
    const container = M.$('dataflowContainer');
    let html = '<h2 class="mo-text-xl mo-accent mo-mb-3">Data Flow - JSONL Files</h2>';
    Object.entries(archData.data_flow).forEach(([file, flow]) => {
      html += '<div class="mo-card mo-mt-3" style="padding:var(--mo-sp-3)">' +
        '<div class="mo-mono mo-text-sm">' + file + '</div>' +
        '<div class="mo-text-xs mo-muted">' + flow.label + '</div>' +
        '<div class="mo-text-xs mo-mt-2">' +
        '<span class="mo-badge mo-badge--warn" style="font-size:0.6rem">W</span> ' + flow.writers.join(', ') + '<br>' +
        '<span class="mo-badge mo-badge--info" style="font-size:0.6rem">R</span> ' + flow.readers.join(', ') +
        '</div></div>';
    });
    container.innerHTML = html;
  }

  function updateStats() {
    if (!archData || !archData.stats) return;
    const s = archData.stats;
    M.$('statsBar').innerHTML = (s.files || 0) + ' files | ' + (s.lines || 0) + ' lines | ' +
      (s.functions || 0) + ' functions | ' + (s.classes || 0) + ' classes';
  }

  init();
})();
