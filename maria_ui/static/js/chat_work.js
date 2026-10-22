/* Durable work is read independently of chat turns. This panel never submits jobs. */
(function () {
  const labels = {accepted:'Przyjęte',queued:'W kolejce',running:'W toku',completed:'Zakończone — raport wykonawcy',failed:'Błąd',cancelled:'Anulowane',interrupted:'Przerwane',unknown:'Wynik niepewny'};
  function presentation(task) {
    if (task.stale === true) return {label:'Nieaktualne dane — odśwież stan',kind:'uncertain'};
    if (task.available === false) return {label:'Komputer lub wynik niedostępny',kind:'uncertain'};
    if (task.requiresHuman === true) return {label:'Potrzebny krok człowieka',kind:'human'};
    const status = Object.hasOwn(labels, task.status) ? task.status : 'unknown';
    return {label:labels[status],kind:status === 'completed' ? 'completed' : status};
  }
  window.MariaChatWork = function (M, options = {}) {
    const select = M.$('workProject'), list = M.$('workTasks'), status = M.$('workStatus');
    if (!select || !list || !status) return null;
    let epoch = 0, timer = null, disposed = false, reading = false, selecting = false;
    let hydrated = false, tasks = [], projects = [], selected = '';
    let selectionUncertain = false;
    const completions = new Set();
    const text = (value, limit = 20000) => typeof value === 'string' ? value.slice(0,limit) : '';
    function dateLabel(value) {
      const date = new Date(typeof value === 'number' ? value * 1000 : value);
      return value && Number.isFinite(date.getTime()) ? date.toLocaleString('pl-PL') : 'brak daty';
    }
    function node(tag, value, className) {
      const el = document.createElement(tag); if (value) el.textContent = value;
      if (className) el.className = className; return el;
    }
    function renderProjects() {
      select.replaceChildren();
      const empty = node('option','Bez wybranego projektu'); empty.value = ''; empty.disabled = true; select.appendChild(empty);
      projects.slice(0,128).forEach(project => {
        if (!project || typeof project.key !== 'string') return;
        const option = node('option',text(project.name,200) + ' · ' + text(project.computerName,120) + (project.available === false ? ' · offline' : ''));
        option.value = project.key; select.appendChild(option);
      });
      select.value = selected; select.disabled = selecting;
    }
    function renderTasks() {
      const opened = new Set(Array.from(list.children).filter(card => card.open).map(card => card.dataset.taskKey));
      const scroll = list.scrollTop;
      list.replaceChildren();
      if (!tasks.length) list.appendChild(node('p','Brak zapisanych zadań. Sam wybór projektu niczego nie uruchamia.'));
      tasks.slice(0,100).forEach(task => {
        if (!task || typeof task.key !== 'string') return;
        const view = presentation(task), card = node('details',null,'mo-work-card');
        card.dataset.taskKey = task.key; card.dataset.state = view.kind;
        card.open = opened.has(task.key);
        const summary = node('summary');
        summary.appendChild(node('strong',text(task.projectName,200) + ' · ' + text(task.computerName,120)));
        summary.appendChild(node('span',view.label,'mo-work-state')); card.appendChild(summary);
        card.appendChild(node('p','Ostatni odczyt: ' + dateLabel(task.lastSeenAt || task.updatedAt)));
        if (task.requiresHuman) card.appendChild(node('p',text(task.humanStep,2000) || 'Sprawdź raport i wykonaj wskazany krok na urządzeniu.'));
        card.appendChild(node('p',text(task.resultText) || 'Brak zapisanego wyniku. Nie oznacza to zakończenia ani zgody na ponowienie.','mo-work-result'));
        if (task.status === 'completed') card.appendChild(node('p','Zakończenie zadania nie jest niezależną weryfikacją plików.'));
        if (task.snapshot) card.appendChild(node('p','Zapisany raport z podanej daty; nie potwierdza bieżącego połączenia z komputerem.'));
        if (task.resultTruncated) card.appendChild(node('p','Raport skrócony; sprawdź artefakty.'));
        if (Array.isArray(task.artifacts)) task.artifacts.slice(0,30).forEach(artifact => {
          if (!artifact || artifact.available !== true || typeof artifact.path !== 'string') return;
          const button = node('button','Otwórz: ' + (text(artifact.name,200) || text(artifact.path,300)),'mo-btn mo-btn--ghost');
          button.type = 'button'; card.appendChild(button);
          const preview = node('div'); card.appendChild(preview);
          button.addEventListener('click',async () => {
            if (disposed || document.hidden || button.disabled) return;
            const token = epoch; button.disabled = true; preview.textContent = 'Odczytuję artefakt…';
            try {
              const data = await M.apiFetch('/api/work/tasks/' + encodeURIComponent(task.key) + '/artifact?path=' + encodeURIComponent(artifact.path));
              if (disposed || document.hidden || token !== epoch || button.isConnected === false) return;
              if (!data || typeof data.content !== 'string' || data.content.length > 1398104 || !Number.isSafeInteger(data.size) || data.size < 0 || data.size > 1048576) throw new Error('artifact');
              const raw = window.atob(data.content);
              if (raw.length !== data.size || raw.length > 1048576) throw new Error('artifact');
              const bytes = Uint8Array.from(raw,char=>char.charCodeAt(0));
              preview.replaceChildren();
              if (/^(text\/(plain|csv|markdown)|application\/json)(?:;|$)/i.test(data.mime || '')) {
                preview.appendChild(node('pre',new TextDecoder('utf-8').decode(bytes),'mo-work-result'));
              } else {
                const download = node('button','Pobierz plik (bez podglądu)','mo-btn mo-btn--ghost'); download.type = 'button';
                download.addEventListener('click',() => {
                  if (disposed || document.hidden) return;
                  const url = window.URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));
                  const a = node('a'); a.href = url; a.download = text(data.name,200).replace(/[\\/\x00-\x1f]/g,'_') || 'artefakt';
                  a.click(); window.setTimeout(()=>window.URL.revokeObjectURL(url),1000);
                });
                preview.appendChild(download);
              }
            } catch (_) { if (token === epoch && !disposed) preview.textContent = 'Nie udało się odczytać artefaktu. Plik jest niedostępny, zmienił się lub przekracza limit 1 MiB.'; }
            finally { button.disabled = false; }
          });
        });
        list.appendChild(card);
      });
      list.scrollTop = scroll;
    }
    function schedule() {
      if (!disposed && !document.hidden) timer = window.setTimeout(refresh,15000);
    }
    async function refresh() {
      if (disposed || document.hidden || reading || selecting) return;
      if (timer !== null) window.clearTimeout(timer); timer = null;
      reading = true; const token = epoch;
      try {
        const [catalog, ledger] = await Promise.all([M.apiFetch('/api/work/projects'),M.apiFetch('/api/work/tasks')]);
        if (disposed || document.hidden || token !== epoch) return;
        if (!catalog || !Array.isArray(catalog.projects) || !ledger || !Array.isArray(ledger.tasks)) throw new Error('unavailable');
        projects = catalog.projects; selected = typeof catalog.selectedProjectKey === 'string' ? catalog.selectedProjectKey : '';
        if (selectionUncertain) { selectionUncertain = false; if (options.selectionBusy) options.selectionBusy(false); }
        tasks = ledger.tasks;
        const notices = [];
        tasks.slice(0,100).forEach(task => {
          if (!task || !task.completionEventId || task.status !== 'completed') return;
          const event = String(task.completionEventId);
          if (hydrated && !completions.has(event) && !task.historical && !task.stale && task.available !== false) notices.push(text(task.projectName,120));
          completions.add(event);
        });
        // A bounded in-memory notification ledger; reload deliberately establishes a fresh baseline.
        while (completions.size > 512) completions.delete(completions.values().next().value);
        hydrated = true; renderProjects(); renderTasks();
        status.textContent = notices.length ? 'Nowy raport zadania: ' + notices.join(', ') + '. Otwórz kartę.' :
          catalog.partial ? 'Część komputerów jest niedostępna. Sprawdź oznaczenia na kartach.' : 'Stan zadań odczytany. Wybór projektu nie uruchamia pracy.';
      } catch (_) {
        if (token !== epoch || disposed || document.hidden) return;
        tasks = tasks.map(task => ({...task,stale:true})); renderTasks();
        status.textContent = 'Nie udało się odczytać bieżącego stanu. Poprzednie dane są nieaktualne.';
      } finally {
        reading = false;
        // A selection/visibility change invalidates this read. Confirm the new
        // selection immediately instead of leaving sends blocked for a poll period.
        if (token !== epoch && !selecting && !disposed && !document.hidden) refresh();
        else schedule();
      }
    }
    select.addEventListener('change',async () => {
      if (selecting || document.hidden || disposed) return;
      selecting = true; ++epoch; const token = epoch, key = select.value;
      selectionUncertain = true; if (options.selectionBusy) options.selectionBusy(true);
      if (timer !== null) window.clearTimeout(timer); timer = null;
      select.disabled = true; status.textContent = 'Zapisuję wybór projektu…';
      try {
        const response = await M.apiFetch('/api/work/selection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})});
        if (disposed || document.hidden || token !== epoch) return;
        if (!response || response.success === false || response.error) throw new Error('selection');
        status.textContent = 'Wybór zapisany. Odczytuję stan…';
      } catch (_) { if (token === epoch) status.textContent = 'Nie potwierdzono wyboru projektu. Sprawdź wybrany projekt przed poleceniem.'; }
      finally { selecting = false; renderProjects(); if (!reading) refresh(); }
    });
    function visibility() {
      ++epoch;
      if (timer !== null) window.clearTimeout(timer); timer = null;
      if (!document.hidden) refresh();
    }
    document.addEventListener('visibilitychange',visibility);
    window.addEventListener('pagehide',() => { disposed = true; ++epoch; if (timer !== null) window.clearTimeout(timer); });
    refresh();
    return {refresh,dispose(){disposed=true;++epoch;if(timer !== null)window.clearTimeout(timer);document.removeEventListener('visibilitychange',visibility);}};
  };
  window.MariaChatWork.presentation = presentation;
})();
