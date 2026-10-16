(() => {
  const root = window.PicSyncra = window.PicSyncra || {};
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function releaseUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && url.hostname === 'github.com' && !url.username && !url.password &&
        url.pathname.startsWith('/NefilimPL/PicSyncra/releases/tag/') ? url.href : '';
    } catch (_) { return ''; }
  }
  function releaseCaption(version, release) {
    if (!release?.tag) return version;
    const date = new Date(release.published_at);
    return release.tag + (release.published_at && Number.isFinite(date.getTime()) ? ` · ${date.toLocaleDateString('pl-PL')}` : '');
  }
  function create({requestJson, onChanged = () => {}, confirm = message => window.confirm(message)}) {
    const element = node('section', undefined, 'settings-block module-updates-panel');
    const title = node('h3', 'Wersje zainstalowanych modułów');
    const note = node('p', 'Aktualizuj zatwierdza wybrane wersje i aktualizuje pozostałe niezablokowane moduły. Bez zmiany oznacza najnowszą dostępną wersję, z zachowaniem blokady.', 'settings-note');
    const status = node('p', '', 'settings-note');
    status.setAttribute('role', 'status');
    const progressbar = node('progress');
    progressbar.setAttribute('aria-label', 'Postęp pobierania i instalacji modułów');
    progressbar.hidden = true;
    const operationBox = node('div', undefined, 'module-update-operation');
    const errorDetails = node('details'); errorDetails.hidden = true;
    const errorSummary = node('summary', 'Szczegóły błędu pobierania');
    const errorText = node('pre'); errorDetails.append(errorSummary, errorText);
    const problem = node('div', undefined, 'module-update-alert');
    problem.hidden = true;
    problem.setAttribute('role', 'alert');
    problem.setAttribute('tabindex', '-1');
    const problemTitle = node('h4', 'Nie można wykonać aktualizacji');
    const problemSummary = node('p', '');
    const transientSummary = node('p', ''); transientSummary.hidden = true;
    const focusedProblems = new Set();
    let attempt = 0;
    let visibleProblem = null, visibleConflict = null, problemSource = null;
    let transientSource = null, transientKey = null;
    const table = node('div', undefined, 'module-updates-rows');
    const controls = node('div', undefined, 'module-updates-controls');
    const channelLabel = node('label', 'Kanał aktualizacji: ');
    const channel = node('select'); channel.setAttribute('aria-label', 'Kanał aktualizacji');
    for (const [value, label] of [['stable','Stable'], ['dev','Dev']]) {
      const option = node('option', label); option.value = value; channel.append(option);
    }
    let currentChannel = 'stable'; channel.value = currentChannel;
    channel.addEventListener('change', async () => {
      if (busy) { channel.value = currentChannel; return; }
      busy = true; synchronize();
      try {
        const result = await post('/api/installation/channel', {channel:channel.value});
        currentChannel = result.channel;
        clearTransientProblem('channel');
        await refresh(); onChanged();
      } catch (error) { channel.value = currentChannel; status.textContent = error.message; showProblem(error.message, error.detail, null, 'channel'); }
      finally { busy = false; synchronize(); }
    });
    channelLabel.append(channel);
    const conflicts = node('div', undefined, 'module-updates-conflicts');
    function clearTransientProblem(source) {
      if (transientSource === source) {
        transientSummary.hidden = true;
        transientSummary.textContent = '';
        focusedProblems.delete(transientKey);
        transientSource = transientKey = null;
      }
      if (problemSource === source) clearProblem();
    }
    function clearProblem() {
      if (problemSource !== 'operation') focusedProblems.delete(visibleProblem);
      focusedProblems.delete(transientKey);
      transientSummary.hidden = true;
      transientSummary.textContent = '';
      transientSource = transientKey = null;
      problem.hidden = true;
      visibleProblem = visibleConflict = problemSource = null;
      problemSummary.textContent = '';
      conflicts.replaceChildren();
      errorDetails.hidden = true;
      errorText.textContent = '';
    }
    function presentProblem(message, details, identity) {
      const key = JSON.stringify([identity || `attempt:${attempt}`, message, details || null]);
      if (!problem.hidden && visibleProblem === key) return;
      visibleProblem = key;
      problemSummary.textContent = message;
      errorDetails.hidden = !details;
      errorText.textContent = details ? JSON.stringify(details, null, 2) : '';
      problem.hidden = false;
      focusProblem(key);
    }
    function focusProblem(key) {
      if (!focusedProblems.has(key)) {
        focusedProblems.add(key);
        problem.focus?.({preventScroll:true});
        problem.scrollIntoView?.({block:'center'});
      }
    }
    function showProblem(message, details, identity, source = 'operation') {
      if (source !== 'operation' && !problem.hidden && problemSource === 'operation') {
        transientSource = source;
        transientKey = JSON.stringify([visibleProblem, source, message]);
        transientSummary.textContent = message;
        transientSummary.hidden = false;
        focusProblem(transientKey);
        return;
      }
      visibleConflict = null;
      problemSource = source;
      conflicts.replaceChildren();
      presentProblem(message, details, identity);
    }
    const selected = new Map(), rows = new Map(), selectedVersions = new Map();
    let busy = false, timer = null, catalogTimer = null, disposed = false, operationId = null, restoreBackupId = null, terminalMessage = null;
    let lastOperation = null, retryAction = null;
    let authorizationId = null;
    function button(label, action) {
      const item = node('button', label); item.type = 'button';
      item.addEventListener('click', () => action()); return item;
    }
    const update = button('Aktualizuj', () => prepare('apply'));
    const ocr = button('Pobierz OCR', () => prepare('install_ocr'));
    ocr.hidden = true;
    const retry = button('Ponów pobieranie', () => prepare(retryAction)); retry.hidden = true;
    const authorizationLink = node('a', 'Otwórz jednorazowe logowanie Windows'); authorizationLink.hidden = true;
    const authorizationCancel = button('Anuluj logowanie', async () => {
      const identifier = authorizationId;
      if (!identifier) return;
      try {
        await post(`/api/installation/module-authorization/${identifier}/cancel`, {});
        if (authorizationId !== identifier) return;
        endAuthorization('Logowanie anulowane przed instalacją.');
      } catch (error) { if (authorizationId === identifier) status.textContent = error.message; }
    }); authorizationCancel.hidden = true;
    operationBox.append(status, progressbar, retry, authorizationLink, authorizationCancel);
    problem.append(problemTitle, problemSummary, transientSummary, conflicts, errorDetails);
    const ocrSection = node('div', undefined, 'module-ocr-install');
    const ocrNote = node('p', '', 'settings-note');
    ocrSection.append(node('strong', 'Silnik i modele OCR'), ocrNote, ocr);
    const refreshButton = button('Sprawdź wersje', () => refresh());
    controls.append(update, refreshButton);
    const backupLabel = node('label', 'Awaryjne odtworzenie bazy: ');
    const backups = node('select'); backups.setAttribute('aria-label', 'Kopia bazy do odtworzenia');
    backups.addEventListener('change', () => { restoreBackupId = backups.value || null; });
    backupLabel.append(backups);
    element.append(title, controls, problem, note, channelLabel, operationBox, table, ocrSection, backupLabel);
    function placeProgress(action, moduleId) {
      const row = rows.get(action === 'install_ocr' ? 'ocr' : moduleId);
      const target = row?.element || (action === 'install_ocr' ? ocrSection : element);
      if (operationBox.parentNode !== target) target.append(operationBox);
    }
    function showProgress(operation) {
      lastOperation = operation;
      placeProgress(operation.action, operation.progress?.module_id);
      const labels = {preparing:'Sprawdzanie zgodności i przygotowanie aktualizacji.', accepted:'Operacja przyjęta — oczekiwanie na rozpoczęcie.', downloading:'Pobieranie',
        draining:'Oczekiwanie na zakończenie zadań.', stopping:'Zatrzymywanie backendu.',
        backing_up:'Tworzenie kopii bazy i konfiguracji.', installing:'Instalowanie',
        restoring:'Odtwarzanie bazy i konfiguracji.', migrating:'Migracja bazy.',
        validating:'Sprawdzanie działania modułów.', committed:'Gotowe — instalacja zakończona.',
        rolling_back:'Przywracanie poprzednich wersji.', rolled_back:'Przywrócono poprzednie wersje.',
        failed:'Operacja nie powiodła się.', recovery_required:'Wymagane odzyskiwanie instalacji.'};
      let text = labels[operation.state] || operation.state;
      if (['downloading','installing'].includes(operation.state)) text += operation.action === 'install_ocr' ? ' OCR' : ' modułów';
      const downloaded = operation.progress?.downloaded_bytes || 0;
      const total = operation.progress?.total_bytes || 0;
      progressbar.hidden = ['committed','rolled_back','failed','recovery_required'].includes(operation.state);
      if (operation.state === 'downloading' && total > 0) {
        const mib = value => (value / 1048576).toLocaleString('pl-PL', {minimumFractionDigits:1, maximumFractionDigits:1});
        text += `: ${mib(downloaded)} / ${mib(total)} MiB (${Math.min(100, Math.floor(downloaded * 100 / total))}%)`;
        progressbar.max = total; progressbar.value = downloaded;
        const rate = operation.progress?.bytes_per_second || 0;
        const eta = operation.progress?.eta_seconds;
        if (rate > 0) {
          text += rate >= 1048576 ? ` · ${(rate / 1048576).toFixed(1)} MiB/s` : ` · ${(rate / 1024).toFixed(1)} KiB/s`;
          if (eta !== undefined && eta !== null) text += eta >= 60 ? ` · pozostało ${Math.floor(eta / 60)} min ${eta % 60} s` : ` · pozostało ${eta} s`;
        } else text += ' · obliczanie prędkości i czasu…';
      } else progressbar.removeAttribute('value');
      status.textContent = text + (operation.error ? ` — ${operation.error}` : '');
      if (!['committed','rolled_back','failed','recovery_required'].includes(operation.state)) {
        status.textContent += ' Aktualizacja działa w tle — możesz zamknąć kartę.';
      }
      const details = operation.error_details;
      if (operation.conflicts?.length) conflictDialog(operation);
      else if (operation.error || ['failed','recovery_required'].includes(operation.state)) {
        showProblem(operation.error || labels[operation.state], details, operation.operation_id);
      } else if (operation.state === 'committed') clearProblem();
      if (details?.http_status) status.textContent += ` (HTTP ${details.http_status})`;
      const canRetry = operation.error && ['failed', 'rolled_back'].includes(operation.state) &&
        (operation.action === 'install_ocr' || details?.retryable === true);
      retry.hidden = !canRetry;
      retryAction = canRetry ? operation.action : null;
    }
    function synchronize() {
      update.disabled = ocr.disabled = refreshButton.disabled = busy;
      for (const row of rows.values()) if (row.select) row.select.disabled = busy;
      backups.disabled = busy;
      channel.disabled = busy;
      retry.disabled = busy;
    }
    function select(moduleId, versionId) {
      const row = rows.get(moduleId);
      if (!row) throw new Error('Nieznany moduł.');
      if (row.module.installed === false) throw new Error('Moduł nie zainstalowany. Uruchom Setup, aby go doinstalować.');
      if (versionId) selected.set(moduleId, versionId);
      else { selected.delete(moduleId); selectedVersions.delete(moduleId); }
      row.select.value = versionId || '';
      const version = row.module.versions.find(item => item.version_id === versionId);
      if (version) selectedVersions.set(moduleId, version);
      const draft = version || selectedVersions.get(moduleId);
      const url = releaseUrl(draft?.release_url);
      if (url) row.link.href = url; else row.link.removeAttribute('href');
      row.link.hidden = !versionId || !url;
      row.link.textContent = `Wybrana: ${releaseCaption(draft?.display_version || '', draft)}`;
      row.status.textContent = versionId ? (!version || !version.available ? 'Wybrana wersja jest niedostępna w tym kanale; zmień wybór przed aktualizacją.' : 'Wybrana konkretna wersja; zostanie zatwierdzona razem z aktualizacją.') :
        row.module.pinned ? 'Wyłączony z aktualizacji po cofnięciu.' : 'Aktualizacje włączone.';
      synchronize();
    }
    function post(url, payload) {
      return requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    }
    function endAuthorization(message) {
      clearTimeout(timer);
      authorizationId = null; busy = false;
      authorizationLink.hidden = authorizationCancel.hidden = true;
      progressbar.hidden = true; status.textContent = message;
      try { window.sessionStorage?.removeItem('picsyncra-module-authorization'); } catch (_) {}
      synchronize();
    }
    async function pollAuthorization() {
      const identifier = authorizationId;
      if (!identifier) return;
      try {
        const request = await requestJson(`/api/installation/module-authorization/${identifier}`);
        if (authorizationId !== identifier) return;
        if (request.state === 'executing' && /^[a-f0-9]{32}$/.test(request.operation_id || '')) {
          const nextOperationId = request.operation_id;
          endAuthorization('Logowanie zaakceptowane. Rozpoczynanie instalacji…');
          busy = true; operationId = nextOperationId;
          try { window.sessionStorage?.setItem('picsyncra-module-operation', operationId); } catch (_) {}
          synchronize(); poll(); return;
        }
        if (request.state === 'cancelled') { endAuthorization('Logowanie lub plan instalacji anulowano.'); return; }
      } catch (error) {
        if (authorizationId === identifier) { endAuthorization(error.message); showProblem(error.message, error.detail); }
        return;
      }
      timer = setTimeout(pollAuthorization, 1500);
    }
    async function requestAuthorization(action) {
      const request = await post('/api/installation/module-authorization', {action,
        selected:['apply','rollback_modules'].includes(action) ? Object.fromEntries(selected) : {},
        excluded:action === 'update' ? [...selected.keys()] : [], restore_backup_id:restoreBackupId});
      if (!/^[a-f0-9]{32}$/.test(request.request_id || '') ||
          !/^picsyncra-update:\/\/authorize\/[A-Za-z0-9][A-Za-z0-9._-]{0,63}\/[a-f0-9]{32}$/.test(request.launch_url || '')) {
        throw new Error('Nieprawidłowe żądanie jednorazowego logowania Windows.');
      }
      authorizationId = request.request_id; busy = true;
      authorizationLink.href = request.launch_url;
      authorizationLink.hidden = authorizationCancel.hidden = false;
      status.textContent = 'Dokończ logowanie Windows i zatwierdź plan w launcherze na komputerze hostującym PicSyncra. Konto zostanie użyte tylko do tej instalacji.';
      progressbar.hidden = true;
      try { window.sessionStorage?.setItem('picsyncra-module-authorization', authorizationId); } catch (_) {}
      pollAuthorization();
      window.location.href = request.launch_url;
    }
    async function refresh() {
      if (!operationId) status.textContent = 'Pobieranie katalogu wersji z GitHuba…';
      try {
        const snapshot = await requestJson('/api/installation/modules');
        clearTransientProblem('catalog');
        currentChannel = snapshot.channel || currentChannel;
        channel.value = currentChannel;
        if (!operationId && snapshot.operation && !['committed','rolled_back','failed','recovery_required'].includes(snapshot.operation.state)) {
          operationId = snapshot.operation.operation_id;
          busy = true; terminalMessage = null;
          showProgress(snapshot.operation);
          poll();
        }
        rows.clear(); table.replaceChildren();
        for (const module of snapshot.modules || []) {
          const row = node('div', undefined, 'module-update-row');
          const label = node('strong', module.label);
          if (module.installed === false) {
            const rowStatus = node('span', 'Moduł nie zainstalowany', 'settings-note');
            row.append(label, rowStatus);
            selected.delete(module.module_id); selectedVersions.delete(module.module_id);
            rows.set(module.module_id, {module, element:row, select:null, status:rowStatus});
            table.append(row); continue;
          }
          const available = snapshot.offline ? (module.latest ? `${module.latest} (katalog lokalny)` : 'nie sprawdzono — katalog niedostępny') :
            module.latest || 'brak podpisanego wydania';
          const versions = node('div', undefined, 'module-version-pair');
          const currentLine = node('div', 'Obecna: '), latestLine = node('div', 'Dostępna: ');
          const currentLink = node('a', releaseCaption(module.current, module.current_release));
          const currentUrl = releaseUrl(module.current_release?.release_url);
          if (currentUrl) currentLink.href = currentUrl;
          currentLink.title = module.current;
          const latestLink = node('a', module.latest ? releaseCaption(module.latest, module.latest_release) + (snapshot.offline ? ' (katalog lokalny)' : '') : available);
          const latestUrl = releaseUrl(module.latest_release?.release_url);
          if (latestUrl) latestLink.href = latestUrl;
          latestLink.title = module.latest || '';
          for (const link of [currentLink, latestLink]) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
          currentLine.append(currentLink); latestLine.append(latestLink); versions.append(currentLine, latestLine);
          const dropdown = node('select'); dropdown.setAttribute('aria-label', `Wersja modułu ${module.label}`);
          const unchanged = node('option', 'Bez zmiany'); unchanged.value = ''; dropdown.append(unchanged);
          for (const version of module.versions || []) {
            const option = node('option', `${releaseCaption(version.display_version, version)}${version.version_id === module.current_id ? ' (obecna)' : ''}${version.available ? '' : ' — niedostępna'}`);
            option.value = version.version_id; option.disabled = !version.available; dropdown.append(option);
          }
          const chosen = selected.get(module.module_id);
          if (chosen && !module.versions.some(version => version.version_id === chosen)) {
            const version = selectedVersions.get(module.module_id);
            const option = node('option', `${version?.display_version || chosen.slice(0,8)} — niedostępna w tym kanale`);
            option.value = chosen; option.disabled = true; dropdown.append(option);
          }
          const link = node('a'); link.target = '_blank'; link.rel = 'noopener noreferrer';
          const rowStatus = node('span', '', 'settings-note');
          rows.set(module.module_id, {module, element:row, currentLink, latestLink, select:dropdown, link, status:rowStatus});
          dropdown.addEventListener('change', () => select(module.module_id, dropdown.value));
          row.append(label, versions, dropdown, link, rowStatus); table.append(row);
          select(module.module_id, selected.get(module.module_id) || null);
        }
        backups.replaceChildren();
        const keep = node('option', 'Zachowaj obecną bazę'); keep.value = ''; backups.append(keep);
        for (const backup of snapshot.backups || []) {
          const option = node('option', `${backup.backup_id} · schemat ${backup.schema_version}`);
          option.value = backup.backup_id; backups.append(option);
        }
        backups.value = restoreBackupId || '';
        ocr.hidden = snapshot.ocr_management === 'setup';
        ocr.textContent = snapshot.ocr_installed === true ? 'Zainstaluj ponownie OCR' : 'Pobierz OCR';
        ocrNote.textContent = snapshot.ocr_management === 'setup' ? (snapshot.ocr_installed && snapshot.ocr_available === false ?
          'OCR ma niekompletne pliki. Zakładka OCR jest ukryta; napraw instalację przed użyciem OCR.' : snapshot.ocr_installed ?
          'OCR zainstalowany. Kolejne wersje zainstalujesz przyciskiem Aktualizuj.' :
          'Moduł nie zainstalowany. Uruchom ponownie pełny Setup i zaznacz składnik OCR. Silnik i modele są w instalatorze; instalacja nie wymaga Internetu.') : '';
        clearTimeout(catalogTimer);
        if (snapshot.catalog_refreshing && !operationId && !disposed) {
          catalogTimer = setTimeout(() => { if (!busy && !operationId && !disposed) refresh(); }, 1500);
        }
        if (lastOperation) placeProgress(lastOperation.action, lastOperation.progress?.module_id);
        if (!operationId) status.textContent = terminalMessage || (snapshot.catalog_refreshing ? 'Sprawdzanie wersji w tle…' : snapshot.offline ?
          `${snapshot.catalog_error?.message || 'Nie udało się pobrać katalogu GitHuba.'} Pokazywany jest katalog lokalny; brakujące pliki wymagają połączenia.` :
          snapshot.blocked_releases?.length && !snapshot.modules.some(m => m.latest) ? 'Brak kompletnego podpisanego wydania modułów w Release.' : '');
        synchronize();
      } catch (error) { status.textContent = error.message; showProblem(error.message, error.detail, null, 'catalog'); }
    }
    function conflictDialog(plan) {
      const identity = JSON.stringify([plan.operation_id || plan.plan_id || `attempt:${attempt}`, plan.conflicts,
        plan.error || 'Plan zawiera konflikty zgodności.', plan.error_details || null]);
      if (!problem.hidden && visibleConflict === identity) return;
      visibleConflict = identity;
      problemSource = 'operation';
      conflicts.replaceChildren(node('h4', 'Konflikty zgodności'));
      for (const item of plan.conflicts) conflicts.append(node('p', `${item.module_id} ${item.selected_version || ''}${item.dependency_id ? ` ↔ ${item.dependency_id} ${item.dependency_version || 'brak'}` : ''}: ${item.requirement}`));
      if (plan.conflicts.some(item => ['controller_outdated', 'launcher_outdated'].includes(item.code))) {
        conflicts.append(node('p', 'To wydanie wymaga nowszego launchera i kontrolera. Uruchom pełny instalator Setup na istniejącej instalacji. Baza, konfiguracja i blokady modułów zostaną zachowane. Sama aktualizacja modułów nie wymienia kontrolera.'));
        const setupLink = node('a', 'Pobierz pełny instalator Setup z wydania GitHub');
        setupLink.href = releaseUrl(plan.setup_release_url) || 'https://github.com/NefilimPL/PicSyncra/releases';
        setupLink.target = '_blank'; setupLink.rel = 'noopener noreferrer';
        conflicts.append(setupLink);
      } else {
        conflicts.append(node('p', 'Zmień wybory wersji wskazanych modułów i ponów aktualizację. Blokady pozostają zachowane.'));
      }
      const cancel = button('Zamknij komunikat', clearProblem);
      conflicts.append(cancel);
      presentProblem(plan.error || 'Plan zawiera konflikty zgodności.', plan.error_details,
        identity);
    }
    async function prepare(action) {
      if (busy) return;
      busy = true; attempt++; synchronize(); clearProblem();
      placeProgress(action, null);
      retry.hidden = true; errorDetails.hidden = true;
      progressbar.hidden = false; progressbar.removeAttribute('value');
      status.textContent = action === 'install_ocr' ? 'Sprawdzanie zgodności i przygotowanie instalacji OCR…' : 'Sprawdzanie zgodności i przygotowanie planu…';
      try {
        if (!restoreBackupId) {
          const operation = await post('/api/installation/module-updates', {action,
            selected: ['apply','rollback_modules'].includes(action) ? Object.fromEntries(selected) : {},
            excluded: action === 'update' ? [...selected.keys()] : [], restore_backup_id:null});
          operationId = operation.operation_id;
          terminalMessage = null;
          showProgress(operation);
          try { window.sessionStorage?.setItem('picsyncra-module-operation', operationId); } catch (_) {}
          poll(); return operation;
        }
        const plan = await post('/api/installation/module-plans', {action,
          selected: ['apply','rollback_modules'].includes(action) ? Object.fromEntries(selected) : {},
          excluded: action === 'update' ? [...selected.keys()] : [], restore_backup_id:restoreBackupId});
        if (plan.conflicts.length) { status.textContent = 'Plan zawiera konflikty zgodności.'; conflictDialog(plan); return plan; }
        if (plan.has_changes === false) { status.textContent = 'Wszystkie wybrane moduły są aktualne. Blokady zostały zachowane.'; return plan; }
        let acknowledged = false;
        if (restoreBackupId) {
          acknowledged = await confirm('Odtworzenie starszej bazy usunie dane zapisane po wykonaniu wybranej kopii. Potwierdzasz utratę tych nowszych danych?');
          if (!acknowledged) return plan;
        }
        const operation = await post(`/api/installation/module-plans/${plan.plan_id}/execute`,
          {restore_backup_id:restoreBackupId, acknowledge_data_loss:acknowledged});
        operationId = operation.operation_id;
        terminalMessage = null;
        showProgress(operation);
        try { window.sessionStorage?.setItem('picsyncra-module-operation', operationId); } catch (_) {}
        poll(); return plan;
      } catch (error) {
        status.textContent = error.message;
        if (error.detail?.code === 'permission_required') {
          try { await requestAuthorization(action); }
          catch (authorizationError) { status.textContent = authorizationError.message; showProblem(authorizationError.message, authorizationError.detail); }
        } else showProblem(error.message, error.detail);
        retryAction = action; retry.hidden = action !== 'install_ocr';
      }
      finally { if (!operationId && !authorizationId) { busy = false; progressbar.hidden = true; } synchronize(); }
    }
    async function poll() {
      if (!operationId) return;
      try {
        const operation = await requestJson(`/api/installation/operations/${operationId}`);
        showProgress(operation);
        if (['committed','rolled_back','failed','recovery_required'].includes(operation.state)) {
          terminalMessage = status.textContent;
          if (operation.state === 'committed') { selected.clear(); selectedVersions.clear(); restoreBackupId = null; }
          operationId = null; busy = false;
          try { window.sessionStorage?.removeItem('picsyncra-module-operation'); } catch (_) {}
          await refresh(); onChanged({preservePanel:!problem.hidden}); return;
        }
      } catch (_) { status.textContent = 'Oczekiwanie na panel po restarcie backendu…'; }
      timer = setTimeout(poll, 2000);
    }
    try {
      const stored = window.sessionStorage?.getItem('picsyncra-module-operation');
      if (/^[a-f0-9]{32}$/.test(stored || '')) { operationId = stored; busy = true; poll(); }
      const pending = window.sessionStorage?.getItem('picsyncra-module-authorization');
      if (!operationId && /^[a-f0-9]{32}$/.test(pending || '')) {
        authorizationId = pending; busy = true;
        authorizationCancel.hidden = false;
        status.textContent = 'Oczekiwanie na jednorazowe logowanie i zatwierdzenie planu w launcherze…';
        pollAuthorization();
      }
    } catch (_) {}
    synchronize();
    return {element, refresh, select, prepare, selected, rows, dispose:() => {disposed = true; clearTimeout(timer); clearTimeout(catalogTimer);}};
  }
  root.ModuleUpdatesPanel = {create};
})();
