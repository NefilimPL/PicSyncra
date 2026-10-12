const test = require('node:test');
const assert = require('node:assert/strict');
const {loadBrowserScript, resetBrowserGlobals} = require('./helpers');
const {deferred} = require('./helpers');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.value = ''; }
  append(...items) { for (const item of items) {
    if (item.parent) item.parent.children = item.parent.children.filter(child => child !== item);
    item.parent = this; this.children.push(item);
  } }
  appendChild(item) { this.append(item); }
  addEventListener(name, callback) { this.events[name] = callback; }
  replaceChildren(...items) { this.children = items; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { if (name === 'href') delete this._href; else delete this[name]; }
  get href() { return Object.hasOwn(this, '_href') ? new URL(this._href, 'http://localhost:8010/').href : ''; }
  set href(value) { this._href = value; }
}
function find(item, predicate) { return predicate(item) ? item : item.children?.map(child => find(child, predicate)).find(Boolean); }

test('infrastructure upgrade conflicts offer full Setup rather than module selection changes', async () => {
  resetBrowserGlobals(); global.document = {createElement:tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  let executions = 0;
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async url => {
    if (url.endsWith('/execute')) executions++;
    return {plan_id:'a'.repeat(32), conflicts:[{code:'controller_outdated',module_id:'core',requirement:'Wymagany kontroler 3; obecny 2.'}],
            setup_release_url:'https://github.com/NefilimPL/PicSyncra/releases/tag/v0.5.6-dev.6'};
  }});
  await panel.prepare('apply');
  const link = find(panel.element, child => child.tagName === 'a' && child.textContent.includes('Setup'));
  assert.equal(link.href, 'https://github.com/NefilimPL/PicSyncra/releases/tag/v0.5.6-dev.6');
  assert.equal(executions, 0);
  panel.dispose();
});

test('missing release URLs never become links to the current WEB page', async () => {
  const {panel} = setup(); await panel.refresh();
  assert.equal(Object.hasOwn(panel.rows.get('ftp').currentLink, '_href'), false);
  assert.equal(Object.hasOwn(panel.rows.get('ftp').latestLink, '_href'), false);
});

test('current and available releases have separate clickable tags and publication dates', async () => {
  resetBrowserGlobals(); global.document = {createElement:tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async () => ({modules:[{
    module_id:'core',label:'Aplikacja i dane',current:'1.old',current_id:'old',latest:'1.new',versions:[],
    current_release:{tag:'v0.5.6-dev.2',published_at:'2026-10-12T07:00:00Z',release_url:'https://github.com/NefilimPL/PicSyncra/releases/tag/v0.5.6-dev.2'},
    latest_release:{tag:'v0.5.6-dev.3',published_at:'2026-10-13T07:00:00Z',release_url:'https://github.com/NefilimPL/PicSyncra/releases/tag/v0.5.6-dev.3'},
  }]})});
  await panel.refresh();
  const row = panel.rows.get('core');
  assert.equal(row.currentLink.href, 'https://github.com/NefilimPL/PicSyncra/releases/tag/v0.5.6-dev.2');
  assert.equal(row.latestLink.href, 'https://github.com/NefilimPL/PicSyncra/releases/tag/v0.5.6-dev.3');
  assert.match(row.currentLink.textContent, /v0\.5\.6-dev\.2.*12\.10\.2026/);
  assert.match(row.latestLink.textContent, /v0\.5\.6-dev\.3.*13\.10\.2026/);
});

test('OCR progress is attached to OCR row and shows speed and remaining time', async t => {
  resetBrowserGlobals(); global.document = {createElement:tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const operation = {operation_id:'a'.repeat(32),state:'downloading',action:'install_ocr',
    progress:{module_id:'ocr_models',downloaded_bytes:1048576,total_bytes:2097152,bytes_per_second:524288,eta_seconds:2}};
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async url => url.endsWith('/modules') ? {
    modules:[{module_id:'ocr',label:'Obsługa OCR',current:'1.old',current_id:'old',versions:[]}],operation,
  } : operation});
  t.after(() => panel.dispose());
  await panel.refresh(); await new Promise(resolve => setImmediate(resolve));
  const row = panel.rows.get('ocr');
  assert.ok(find(row.element, child => child.tagName === 'progress'));
  const status = find(row.element, child => child.role === 'status');
  assert.match(status.textContent, /KiB\/s.*2 s/);
  panel.dispose();
});

test('offline rows do not claim the published signed release is missing', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async () => ({
    offline:true, modules:[{module_id:'core',label:'Aplikacja i dane',current:'1.old',current_id:'old',versions:[]}],
  })});
  await panel.refresh();
  assert.match(panel.rows.get('core').latestLink.textContent, /nie sprawdzono.*katalog niedostępny/);
  assert.doesNotMatch(panel.rows.get('core').latestLink.textContent, /brak podpisanego wydania/);
});

test('OCR preparation shows pending progress and then the controller error without executing', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const pending = deferred(), calls = [];
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async url => {
    calls.push(url);
    return pending.promise;
  }});
  const work = panel.prepare('install_ocr');
  const bar = find(panel.element, child => child.tagName === 'progress');
  const status = find(panel.element, child => child.role === 'status');
  const controls = panel.element.children.find(child => child.className === 'module-updates-controls');
  assert.equal(bar.hidden, false);
  assert.match(status.textContent, /przygotowanie instalacji OCR/);
  assert.ok(controls.children.every(button => button.disabled));
  pending.reject(new Error('Nie udało się zweryfikować certyfikatu GitHuba.'));
  await work;
  assert.match(status.textContent, /certyfikatu GitHuba/);
  assert.equal(bar.hidden, true);
  assert.ok(controls.children.filter(button => !/Cofnij/.test(button.textContent)).every(button => !button.disabled));
  assert.deepEqual(calls, ['/api/installation/module-plans']);
});

test('OCR download failure remains visible after the automatic catalog refresh', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const pending = deferred();
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({confirm:() => true, requestJson:async url => {
    if (url.endsWith('/module-plans')) return {plan_id:'a'.repeat(32),conflicts:[],changes:[],download_bytes:100};
    if (url.endsWith('/execute')) return {operation_id:'a'.repeat(32),state:'accepted',action:'install_ocr'};
    if (url.includes('/operations/')) return pending.promise;
    return {modules:[],offline:false};
  }});
  await panel.prepare('install_ocr');
  pending.resolve({operation_id:'a'.repeat(32),state:'failed',action:'install_ocr',error:'Nie udało się pobrać pliku OCR.'});
  await new Promise(resolve => setImmediate(resolve));
  const status = find(panel.element, child => child.role === 'status');
  assert.match(status.textContent, /nie powiodła.*Nie udało się pobrać pliku OCR/);
  assert.equal(find(panel.element, child => child.tagName === 'progress').hidden, true);
  panel.dispose();
});

test('download details and retry create a fresh plan and require new confirmation', async t => {
  resetBrowserGlobals(); global.document = {createElement:tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  let plans = 0, executions = 0, confirmations = 0;
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({confirm:() => { confirmations++; return confirmations === 1; },
    requestJson:async url => {
      if (url.endsWith('/module-plans')) { plans++; return {plan_id:String(plans).repeat(32),conflicts:[],changes:[],download_bytes:10}; }
      if (url.endsWith('/execute')) { executions++; return {operation_id:'1'.repeat(32),state:'accepted',action:'install_ocr'}; }
      if (url.includes('/operations/')) return {operation_id:'1'.repeat(32),state:'rolled_back',action:'install_ocr',error:'GitHub zwrócił HTTP 503.',
        error_details:{code:'http_error',http_status:503,module_id:'ocr_models',file:'models/ocr/model.bin',retryable:true}};
      return {modules:[],offline:false};
    }});
  t.after(() => panel.dispose());
  await panel.prepare('install_ocr'); await new Promise(resolve => setImmediate(resolve));
  const details = find(panel.element, child => child.tagName === 'details');
  assert.equal(details.hidden, false);
  assert.match(find(details, child => child.tagName === 'pre').textContent, /503.*|ocr_models/);
  const retry = find(panel.element, child => child.textContent === 'Ponów pobieranie');
  assert.equal(retry.hidden, false); assert.equal(retry.disabled, false);
  await retry.events.click();
  assert.equal(plans, 2); assert.equal(confirmations, 2); assert.equal(executions, 1);
});

test('offline empty catalog displays GitHub failure cause', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async () => ({
    modules:[], offline:true, catalog_error:{code:'rate_limit',message:'GitHub: przekroczono limit zapytań.'}})});
  await panel.refresh();
  const status = find(panel.element, child => child.role === 'status');
  assert.match(status.textContent,/limit/);
  assert.match(status.textContent,/lokalny/);
});
function setup({differentChannels=false} = {}) {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const calls = [];
  let channel = 'stable';
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({
    confirm: () => false,
    requestJson: async (url, options) => {
      calls.push([url, options?.body ? JSON.parse(options.body) : null]);
      if (url.endsWith('/channel')) { channel=JSON.parse(options.body).channel; return {channel}; }
      if (url.endsWith('/modules')) return {channel, modules: ['ftp', 'sql'].map(id => ({module_id: id, label:id, current:'5', current_id:'new', latest:'5', pinned:id === 'sql', versions:differentChannels && channel === 'dev' ? [] : [{version_id:'old',display_version:'1',available:true,release_url:'https://github.com/NefilimPL/PicSyncra/releases/tag/v1'}]}))};
      return {plan_id:'a'.repeat(32), conflicts:[], download_bytes:3, changes:[]};
    }
  });
  return {panel, calls};
}
test('one update button is at top and submits explicit versions together', async () => {
  const {panel, calls} = setup();
  const controls = panel.element.children[1];
  assert.equal(controls.className, 'module-updates-controls');
  assert.deepEqual(controls.children.map(item => item.textContent), ['Aktualizuj', 'Sprawdź wersje']);
  await panel.refresh(); panel.select('ftp', 'old');
  await controls.children[0].events.click();
  assert.deepEqual(calls[1][1], {action:'apply', selected:{ftp:'old'}, excluded:[], restore_backup_id:null});
});

test('permission failure opens only native host authorization and stops before download', async t => {
  resetBrowserGlobals(); global.document = {createElement:tag => new Element(tag)};
  window.location = {};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const calls = [], id = 'a'.repeat(32);
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async (url, options) => {
    calls.push([url, options?.body ? JSON.parse(options.body) : null]);
    if (url.endsWith('/module-plans')) {
      const error = new Error('Brak dostępu'); error.detail = {code:'permission_required'}; throw error;
    }
    if (url.endsWith('/module-authorization')) return {request_id:id,launch_url:`picsyncra-update://authorize/test/${id}`};
    if (url.endsWith('/cancel')) return {state:'cancelled'};
    return {state:'pending'};
  }});
  t.after(() => panel.dispose());
  await panel.prepare('apply');
  assert.equal(window.location.href, `picsyncra-update://authorize/test/${id}`);
  assert.deepEqual(calls[1][1], {action:'apply',selected:{},excluded:[],restore_backup_id:null});
  assert.equal(calls.some(([url]) => url.endsWith('/execute')), false);
  const cancel = find(panel.element, child => child.textContent === 'Anuluj logowanie');
  assert.equal(cancel.hidden, false);
  await cancel.events.click();
  assert.equal(cancel.hidden, true);
  assert.match(find(panel.element, child => child.role === 'status').textContent, /anulowane/);
});

test('late authorization response cannot replace a newer login request', async t => {
  for (const outcome of ['cancelled', 'executing', 'error']) {
    await t.test(outcome, async t => {
      resetBrowserGlobals(); global.document = {createElement:tag => new Element(tag)};
      window.location = {};
      loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
      const first = deferred(), calls = [], ids = ['a'.repeat(32), 'b'.repeat(32)];
      let requests = 0;
      const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async url => {
        calls.push(url);
        if (url.endsWith('/module-plans')) {
          const error = new Error('Brak dostępu'); error.detail = {code:'permission_required'}; throw error;
        }
        if (url.endsWith('/module-authorization')) {
          const id = ids[requests++];
          return {request_id:id,launch_url:`picsyncra-update://authorize/test/${id}`};
        }
        if (url.endsWith('/cancel')) return {state:'cancelled'};
        if (url.endsWith(ids[0])) return first.promise;
        return {state:'pending'};
      }});
      t.after(() => panel.dispose());
      await panel.prepare('apply');
      const cancel = find(panel.element, child => child.textContent === 'Anuluj logowanie');
      await cancel.events.click();
      await panel.prepare('apply');
      if (outcome === 'error') first.reject(new Error('Wygasło stare logowanie'));
      else first.resolve({state:outcome,operation_id:'c'.repeat(32)});
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(cancel.hidden, false);
      assert.match(find(panel.element, child => child.role === 'status').textContent, /Dokończ logowanie/);
      assert.equal(calls.some(url => url.includes('/operations/')), false);
      assert.equal(panel.element.children[1].children[0].disabled, true);
    });
  }
});
test('selection is draft, shared rollback submits all, update excludes drafts', async () => {
  const {panel,calls} = setup();
  await panel.refresh();
  panel.select('ftp','old'); panel.select('sql','old');
  assert.equal(calls.length,1);
  await panel.prepare('rollback_modules');
  assert.deepEqual(calls[1][1].selected, {ftp:'old',sql:'old'});
  assert.equal(calls.some(([url]) => url.endsWith('/execute')), false);
  await panel.prepare('update');
  assert.deepEqual(calls[2][1].selected, {});
  assert.deepEqual(calls[2][1].excluded, ['ftp','sql']);
});
test('each selected row points to its release and pins survive refresh', async () => {
  const {panel} = setup();
  await panel.refresh(); panel.select('ftp','old');
  assert.equal(panel.rows.get('ftp').link.href, 'https://github.com/NefilimPL/PicSyncra/releases/tag/v1');
  assert.match(panel.rows.get('sql').status.textContent, /wyłączony/i);
  await panel.refresh();
  assert.equal(panel.selected.get('ftp'), 'old');
});

test('channel selector persists channel and refreshes without applying drafts', async () => {
  const {panel, calls} = setup({differentChannels:true});
  await panel.refresh(); panel.select('ftp','old');
  const find = item => item.children.find(child => child.tagName === 'select') || item.children.map(find).find(Boolean);
  const channel = find(panel.element);
  assert.equal(channel.value, 'stable');
  channel.value = 'dev';
  await channel.events.change();
  assert.deepEqual(calls[1], ['/api/installation/channel', {channel:'dev'}]);
  assert.equal(calls[2][0], '/api/installation/modules');
  assert.equal(panel.selected.get('ftp'), 'old');
  assert.equal(panel.rows.get('ftp').select.value, 'old');
  assert.equal(panel.rows.get('ftp').link.href, 'https://github.com/NefilimPL/PicSyncra/releases/tag/v1');
  assert.match(panel.rows.get('ftp').status.textContent, /niedostępna.*kanale/i);
  assert.ok(panel.rows.get('ftp').select.children.some(option => option.value === 'old'));
  assert.equal(calls.some(([url]) => url.endsWith('/execute')), false);
});

test('reopened panel resumes OCR progress with bytes and percent and keeps controls locked', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const operation = {operation_id:'a'.repeat(32),state:'downloading',action:'install_ocr',
    progress:{downloaded_bytes:1048576,total_bytes:2097152}};
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async url =>
    url.endsWith('/modules') ? {modules:[],operation} : operation});
  await panel.refresh();
  await new Promise(resolve => setImmediate(resolve));
  const bar = find(panel.element, child => child.tagName === 'progress');
  const status = find(panel.element, child => child.role === 'status');
  assert.ok(bar);
  assert.equal(bar.max,2097152);
  assert.equal(bar.value,1048576);
  assert.match(status.textContent,/OCR.*50%/);
  const controls = panel.element.children.find(child => child.className === 'module-updates-controls');
  assert.ok(controls.children.every(button => button.disabled));
  panel.dispose();
});
