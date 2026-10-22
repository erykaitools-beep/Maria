/* Vision page: visibility-aware live preview and an isolated manual photo. */
var visionPoller = null;
var snapshotPoller = null;
var snapshotPending = false;
var displayedFrameVersion = null;

document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.mo-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('.mo-tab').forEach(function(t) { t.classList.remove('mo-tab--active'); });
      document.querySelectorAll('.mo-tab-content').forEach(function(c) { c.classList.remove('mo-tab-content--active'); });
      tab.classList.add('mo-tab--active');
      var target = document.getElementById(tab.dataset.tab);
      if (target) target.classList.add('mo-tab-content--active');
      if (visionPoller) visionPoller.refresh();
    });
  });
  visionPoller = MariaUI.createPoller(refreshVision, 1000);
});

function cameraVisible() {
  return document.getElementById('tab-camera').classList.contains('mo-tab-content--active');
}

async function refreshVision() {
  var data = await MariaUI.apiFetch('/api/vision/state');
  if (!data || !data.available) {
    renderStatus({ available: false });
    document.getElementById('camera-img').style.display = 'none';
    document.getElementById('no-frame').style.display = 'block';
    return;
  }
  var state = data.state;
  renderStatus({ available: true, status: state.status || {} });
  renderPercept({ percept: state.last_percept });
  renderHealth(state.health || {});
  var percept = state.last_percept || {};
  var framePercept = state.frame_percept || percept;
  document.getElementById('vision-summary').textContent =
    (framePercept.summary || '') + (framePercept.timestamp ? ' [' + formatTs(framePercept.timestamp) + ']' : '');
  if (!cameraVisible()) return;
  if (state.frame_available === false) {
    displayedFrameVersion = null;
    document.getElementById('camera-img').style.display = 'none';
    document.getElementById('no-frame').style.display = 'block';
    return;
  }
  await loadFrame(state.frame_version || String(percept.timestamp || 'saved'));
}

function loadFrame(version) {
  if (version === displayedFrameVersion) return Promise.resolve();
  return new Promise(function(resolve) {
    var img = document.getElementById('camera-img');
    var noFrame = document.getElementById('no-frame');
    var fresh = new Image();
    fresh.id = img.id;
    fresh.alt = img.alt;
    fresh.className = img.className;
    fresh.style.cssText = img.style.cssText;
    fresh.onload = function() {
      displayedFrameVersion = version;
      fresh.style.display = 'block';
      img.replaceWith(fresh);
      noFrame.style.display = 'none';
      fresh.onload = fresh.onerror = null;
      resolve();
    };
    fresh.onerror = function() {
      img.style.display = 'none';
      noFrame.style.display = 'block';
      fresh.onload = fresh.onerror = null;
      resolve();
    };
    fresh.src = '/api/vision/frame?v=' + encodeURIComponent(version);
  });
}

function renderStatus(data) {
      var el = document.getElementById('vision-status');
      if (!data || !data.available) {
        el.innerHTML = '<div class="mo-empty-state">VisionCortex nie zainicjalizowany</div>';
        return;
      }
      var s = data.status;
      var html = '<div class="mo-card mo-mb-2">';
      html += '<div class="mo-card__title">Status wzroku</div>';
      html += '<table class="mo-table">';
      html += '<tr><td>Sensory</td><td>' + (s.sensor_count || 0) + '</td></tr>';
      html += '<tr><td>Aktywny sensor</td><td>' + (s.active_sensor || 'brak') + '</td></tr>';
      html += '<tr><td>Moduly</td><td>' + (s.active_modules ? s.active_modules.join(', ') : 'brak') + '</td></tr>';
      html += '<tr><td>Zdrowie</td><td>' + formatPct(s.sensor_health) + '</td></tr>';
      html += '<tr><td>Ostatnia jakosc</td><td>' + formatPct(s.last_quality) + '</td></tr>';
      html += '</table></div>';
      el.innerHTML = html;
}

function renderPercept(data) {
      var el = document.getElementById('vision-percept');
      if (!data || !data.percept) {
        el.innerHTML = '<div class="mo-empty-state">Brak danych. Czekam na pierwszy obraz z kamery.</div>';
        return;
      }
      var p = data.percept;
      var html = '<div class="mo-card mo-mb-2">';
      html += '<div class="mo-card__title">Analiza [' + formatTs(p.timestamp) + ']</div>';
      html += '<table class="mo-table">';
      html += '<tr><td>Podsumowanie</td><td>' + esc(p.summary || '') + '</td></tr>';
      html += '<tr><td>Jakosc</td><td>' + formatPct(p.quality) + '</td></tr>';
      html += '<tr><td>Zdrowie</td><td>' + formatPct(p.health) + '</td></tr>';
      html += '<tr><td>Moduly</td><td>' + (p.modules_run ? p.modules_run.join(', ') : '') + '</td></tr>';
      html += '<tr><td>Czas przetwarzania</td><td>' + (p.processing_time_ms || 0).toFixed(0) + 'ms</td></tr>';
      html += '</table>';

      if (p.motion) {
        html += '<div class="mo-card__title mo-mt-2">Ruch</div>';
        html += '<table class="mo-table">';
        html += '<tr><td>Wykryto</td><td>' + (p.motion.motion_detected ? 'TAK' : 'NIE') + '</td></tr>';
        if (p.motion.motion_detected) {
          html += '<tr><td>Poziom</td><td>' + formatPct(p.motion.motion_level) + '</td></tr>';
          html += '<tr><td>Klasyfikacja</td><td>' + esc(p.motion.classification || '') + '</td></tr>';
          html += '<tr><td>Alert</td><td>' + esc(p.motion.alert_level || '') + '</td></tr>';
        }
        html += '</table>';
      }

      if (p.scene) {
        html += '<div class="mo-card__title mo-mt-2">Scena</div>';
        html += '<table class="mo-table">';
        html += '<tr><td>Opis</td><td>' + esc(p.scene.description || '') + '</td></tr>';
        html += '<tr><td>Oswietlenie</td><td>' + esc(p.scene.lighting || '') + '</td></tr>';
        html += '<tr><td>Kolory</td><td>' + (p.scene.dominant_colors ? p.scene.dominant_colors.join(', ') : '') + '</td></tr>';
        html += '<tr><td>Zlozonosc</td><td>' + formatPct(p.scene.complexity) + '</td></tr>';
        html += '<tr><td>Backend</td><td>' + esc(p.scene.backend_used || '') + '</td></tr>';
        html += '</table>';
      }

      html += '</div>';
      el.innerHTML = html;
}

function renderHealth(data) {
      var el = document.getElementById('vision-health');
      if (!data || !data.health) {
        el.innerHTML = '<div class="mo-empty-state">Brak danych o zdrowiu sensora</div>';
        return;
      }
      var h = data.health;
      var html = '<div class="mo-card mo-mb-2">';
      html += '<div class="mo-card__title">Zdrowie sensora</div>';
      html += '<table class="mo-table">';
      html += '<tr><td>Sensor</td><td>' + esc(data.sensor_id || '') + '</td></tr>';
      html += '<tr><td>Ogolne</td><td>' + formatPct(h.overall) + ' (' + esc(h.degradation_level || '') + ')</td></tr>';
      html += '<tr><td>Polaczenie</td><td>' + formatPct(h.connection) + '</td></tr>';
      html += '<tr><td>Stream</td><td>' + formatPct(h.stream) + '</td></tr>';
      html += '<tr><td>Rozdzielczosc</td><td>' + formatPct(h.resolution) + '</td></tr>';
      html += '<tr><td>Kolor</td><td>' + formatPct(h.color) + '</td></tr>';
      html += '<tr><td>Ostrosc</td><td>' + formatPct(h.focus) + '</td></tr>';
      html += '<tr><td>Ekspozycja</td><td>' + formatPct(h.exposure) + '</td></tr>';
      html += '<tr><td>Szum</td><td>' + formatPct(h.noise) + '</td></tr>';
      html += '<tr><td>Latencja</td><td>' + (h.latency_ms || 0).toFixed(0) + 'ms</td></tr>';
      if (h.issues && h.issues.length) {
        html += '<tr><td>Problemy</td><td>' + h.issues.join(', ') + '</td></tr>';
      }
      if (data.description) {
        html += '<tr><td>Opis</td><td>' + esc(data.description) + '</td></tr>';
      }
      html += '</table></div>';
      el.innerHTML = html;
}

function finishSnapshot(message) {
  if (snapshotPoller) snapshotPoller.stop();
  snapshotPoller = null;
  snapshotPending = false;
  var button = document.getElementById('vision-snap-button');
  button.disabled = false;
  button.textContent = 'Zrob zdjecie';
  document.getElementById('snapshot-status').textContent = message;
}

async function takeSnap() {
  if (snapshotPending) return;
  snapshotPending = true;
  var button = document.getElementById('vision-snap-button');
  button.disabled = true;
  button.textContent = 'Robie zdjecie...';
  document.getElementById('snapshot-status').textContent = 'Przygotowuje nowe zdjecie i opis...';
  document.getElementById('snapshot-result').style.display = 'none';
  var accepted = await MariaUI.apiFetch('/api/vision/snap', { method: 'POST', errorBody: true });
  if (!accepted || !accepted.accepted) {
    finishSnapshot(accepted && accepted.error || 'Nie mozna zrobic zdjecia. Sprawdz stan kamery.');
    return;
  }
  var started = Date.now();
  snapshotPoller = MariaUI.createPoller(async function() {
    if (Date.now() - started > 610000) {
      finishSnapshot('Opis trwa zbyt dlugo. Sprawdz stan kamery i sprobuj pozniej.');
      return;
    }
    var result = await MariaUI.apiFetch('/api/vision/snap/' + encodeURIComponent(accepted.job_id));
    if (!result) {
      finishSnapshot('Zdjecie jest niedostepne lub wygaslo.');
      return;
    }
    if (result.status === 'running') return;
    if (!result.success) {
      finishSnapshot(result.error || 'Nie udalo sie zrobic zdjecia.');
      return;
    }
    document.getElementById('snapshot-img').src = result.frame_url;
    document.getElementById('snapshot-description').textContent = result.summary || '';
    document.getElementById('snapshot-result').style.display = 'block';
    finishSnapshot('Zdjecie z ' + formatTs(result.percept.timestamp) + '.');
  }, 1000);
}

function formatPct(val) {
  if (val === null || val === undefined) return '--';
  return (val * 100).toFixed(1) + '%';
}

function formatTs(ts) {
  if (!ts) return '--';
  var d = new Date(ts * 1000);
  return d.toLocaleTimeString('pl-PL');
}

function esc(s) {
  var div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
