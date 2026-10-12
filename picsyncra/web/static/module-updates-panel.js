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
        await refresh(); onChanged();
      } catch (error) { channel.value = currentChannel; status.textContent = error.message; }
      finally { busy = false; synchronize(); }
    });
    channelLabel.append(channel);
    const conflicts = node('div', undefined, 'module-updates-conflicts');
    const selected = new Map(), rows = new Map(), selectedVersions = new Map();
    let busy = false, timer = null, operationId = null, restoreBackupId = null, terminalMessage = null;
    let lastOperation = null, retryAction = null;
    let authorizationId = null;
    function button(label, action) {
      const item = node('button', label); item.type = 'button';
      item.addEventListener('click', () => action()); return item;
    }
    const update = button('Aktualizuj', () => prepare('apply'));
    const ocr = button('Pobierz OCR', () => prepare('install_ocr'));
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
    operationBox.append(status, progressbar, errorDetails, retry, authorizationLink, authorizationCancel);
    const ocrSection = node('div', undefined, 'module-ocr-install');
    ocrSection.append(node('strong', 'Silnik i modele OCR'), ocr);
    const refreshButton = button('Sprawdź wersje', () => refresh());
    controls.append(update, refreshButton);
    const backupLabel = node('label', 'Awaryjne odtworzenie bazy: ');
    const backups = node('select'); backups.setAttribute('aria-label', 'Kopia bazy do odtworzenia');
    backups.addEventListener('change', () => { restoreBackupId = backups.value || null; });
    backupLabel.append(backups);
    element.append(title, controls, note, channelLabel, operationBox, table, ocrSection, backupLabel, conflicts);
    function placeProgress(action, moduleId) {
      const row = rows.get(action === 'install_ocr' ? 'ocr' : moduleId);
      const target = row?.element || (action === 'install_ocr' ? ocrSection : element);
      if (operationBox.parentNode !== target) target.append(operationBox);
    }
    function showProgress(operation) {
      lastOperation = operation;
      placeProgress(operation.action, operation.progress?.module_id);
      const labels = {accepted:'Operacja przyjęta — oczekiwanie na rozpoczęcie.', downloading:'Pobieranie',
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
      const details = operation.error_details;
      errorDetails.hidden = !details;
      errorText.textContent = details ? JSON.stringify(details, null, 2) : '';
      if (details?.http_status) status.textContent += ` (HTTP ${details.http_status})`;
      const canRetry = operation.error && ['failed', 'rolled_back'].includes(operation.state) &&
        (operation.action === 'install_ocr' || details?.retryable === true);
      retry.hidden = !canRetry;
      retryAction = canRetry ? operation.action : null;
    }
    function synchronize() {
      update.disabled = ocr.disabled = refreshButton.disabled = busy;
      for (const row of rows.values()) row.select.disabled = busy;
      backups.disabled = busy;
      channel.disabled = busy;
      retry.disabled = busy;
    }
    function select(moduleId, versionId) {
      const row = rows.get(moduleId);
      if (!row) throw new Error('Nieznany moduł.');
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
        if (authorizationId === identifier) endAuthorization(error.message);
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
        ocr.hidden = snapshot.ocr_installed === true;
        if (lastOperation) placeProgress(lastOperation.action, lastOperation.progress?.module_id);
        if (!operationId) status.textContent = terminalMessage || (snapshot.offline ?
          `${snapshot.catalog_error?.message || 'Nie udało się pobrać katalogu GitHuba.'} Pokazywany jest katalog lokalny; brakujące pliki wymagają połączenia.` :
          snapshot.blocked_releases?.length && !snapshot.modules.some(m => m.latest) ? 'Brak kompletnego podpisanego wydania modułów w Release.' : '');
        synchronize();
      } catch (error) { status.textContent = error.message; }
    }
    function conflictDialog(plan) {
      conflicts.replaceChildren(node('h4', 'Konflikty zgodności'));
      for (const item of plan.conflicts) conflicts.append(node('p', `${item.module_id} ${item.selected_version || ''}${item.dependency_id ? ` ↔ ${item.dependency_id} ${item.dependency_version || 'brak'}` : ''}: ${item.requirement}`));
      conflicts.append(node('p', 'Zmień wybory wersji wskazanych modułów i ponów aktualizację. Blokady pozostają zachowane.'));
      const cancel = button('Nie aktualizuj', () => conflicts.replaceChildren());
      conflicts.append(cancel);
    }
    async function prepare(action) {
      if (busy) return;
      busy = true; synchronize(); conflicts.replaceChildren();
      placeProgress(action, null);
      retry.hidden = true; errorDetails.hidden = true;
      progressbar.hidden = false; progressbar.removeAttribute('value');
      status.textContent = action === 'install_ocr' ? 'Sprawdzanie zgodności i przygotowanie instalacji OCR…' : 'Sprawdzanie zgodności i przygotowanie planu…';
      try {
        const plan = await post('/api/installation/module-plans', {action,
          selected: ['apply','rollback_modules'].includes(action) ? Object.fromEntries(selected) : {},
          excluded: action === 'update' ? [...selected.keys()] : [], restore_backup_id:restoreBackupId});
        if (plan.conflicts.length) { status.textContent = 'Plan zawiera konflikty zgodności.'; conflictDialog(plan); return plan; }
        if (plan.has_changes === false) { status.textContent = 'Wszystkie wybrane moduły są aktualne. Blokady zostały zachowane.'; return plan; }
        let changes = (plan.changes || []).map(item => `${item.module_id}: ${item.current || 'brak'} → ${item.target}`).join('\n');
        if (action === 'update_all') {
          const overridden = new Set([...selected.keys(), ...[...rows.values()].filter(row => row.module.pinned).map(row => row.module.module_id)]);
          if (overridden.size) changes += `\nAktualizacje zostaną włączone, a wybory cofnięcia pominięte dla: ${[...overridden].sort().join(', ')}.`;
        }
        if (!await confirm(`${changes || 'Zgodny zestaw modułów.'}\nDo pobrania: ${plan.download_bytes.toLocaleString('pl-PL')} bajtów.\nZatwierdzić operację?`)) { status.textContent = 'Operacja anulowana przed rozpoczęciem.'; return plan; }
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
          catch (authorizationError) { status.textContent = authorizationError.message; }
        }
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
          await refresh(); onChanged(); return;
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
    return {element, refresh, select, prepare, selected, rows, dispose:() => clearTimeout(timer)};
  }
  root.ModuleUpdatesPanel = {create};
})();
