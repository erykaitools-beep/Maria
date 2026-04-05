/* Vision page - visual perception pipeline */

document.addEventListener('DOMContentLoaded', function() {
  // Tab switching
  document.querySelectorAll('.mo-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('.mo-tab').forEach(function(t) { t.classList.remove('mo-tab--active'); });
      document.querySelectorAll('.mo-tab-content').forEach(function(c) { c.classList.remove('mo-tab-content--active'); });
      tab.classList.add('mo-tab--active');
      var target = document.getElementById(tab.dataset.tab);
      if (target) target.classList.add('mo-tab-content--active');
    });
  });

  loadFrame();
  loadStatus();
  loadPercept();
  loadHealth();

  // Live preview: refresh frame every 1s
  setInterval(loadFrame, 1000);
  // Status/analysis refresh every 10s
  setInterval(loadStatus, 10000);
});


function loadFrame() {
  var img = document.getElementById('camera-img');
  var noFrame = document.getElementById('no-frame');
  var summary = document.getElementById('vision-summary');
  if (!img) return;

  // Reload image (cache bust)
  var newImg = new Image();
  newImg.onload = function() {
    img.src = newImg.src;
    img.style.display = 'block';
    noFrame.style.display = 'none';
  };
  newImg.onerror = function() {
    img.style.display = 'none';
    noFrame.style.display = 'block';
  };
  newImg.src = '/api/vision/frame?t=' + Date.now();

  // Load summary text under image
  fetch('/api/vision/last')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data && data.percept && data.percept.summary) {
        summary.textContent = data.percept.summary + ' [' + formatTs(data.percept.timestamp) + ']';
      } else {
        summary.textContent = '';
      }
    })
    .catch(function() { summary.textContent = ''; });
}


function loadStatus() {
  fetch('/api/vision/status')
    .then(function(r) { return r.json(); })
    .then(function(data) {
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
    })
    .catch(function(e) {
      document.getElementById('vision-status').innerHTML =
        '<div class="mo-empty-state">Blad ladowania: ' + e.message + '</div>';
    });
}


function loadPercept() {
  fetch('/api/vision/last')
    .then(function(r) { return r.json(); })
    .then(function(data) {
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
    })
    .catch(function(e) {
      document.getElementById('vision-percept').innerHTML =
        '<div class="mo-empty-state">Blad: ' + e.message + '</div>';
    });
}


function loadHealth() {
  fetch('/api/vision/health')
    .then(function(r) { return r.json(); })
    .then(function(data) {
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
    })
    .catch(function(e) {
      document.getElementById('vision-health').innerHTML =
        '<div class="mo-empty-state">Blad: ' + e.message + '</div>';
    });
}


function takeSnap() {
  var btn = document.querySelector('.mo-btn--sm');
  if (btn) { btn.disabled = true; btn.textContent = 'Robie...'; }

  fetch('/api/vision/snap', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (btn) { btn.disabled = false; btn.textContent = 'Snap'; }
      if (data.success) {
        loadFrame();
        loadPercept();
        loadHealth();
        loadStatus();
      } else {
        alert('Blad: ' + (data.error || 'nieznany'));
      }
    })
    .catch(function(e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Snap'; }
      alert('Blad: ' + e.message);
    });
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
