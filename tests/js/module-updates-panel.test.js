const test = require('node:test');
const assert = require('node:assert/strict');
const {loadBrowserScript, resetBrowserGlobals} = require('./helpers');
const {deferred} = require('./helpers');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.value = ''; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); }
  addEventListener(name, callback) { this.events[name] = callback; }
  replaceChildren(...items) { this.children = items; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
}

test('offline rows do not claim the published signed release is missing', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async () => ({
    offline:true, modules:[{module_id:'core',label:'Aplikacja i dane',current:'1.old',current_id:'old',versions:[]}],
  })});
  await panel.refresh();
  const row = panel.element.children.find(child => child.className === 'module-updates-rows').children[0];
  assert.match(row.children[1].textContent, /nie sprawdzono.*katalog niedostępny/);
  assert.doesNotMatch(row.children[1].textContent, /brak podpisanego wydania/);
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
  const bar = panel.element.children.find(child => child.tagName === 'progress');
  const status = panel.element.children.find(child => child.role === 'status');
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
  const status = panel.element.children.find(child => child.role === 'status');
  assert.match(status.textContent, /nie powiodła.*Nie udało się pobrać pliku OCR/);
  assert.equal(panel.element.children.find(child => child.tagName === 'progress').hidden, true);
  panel.dispose();
});

test('offline empty catalog displays GitHub failure cause', async () => {
  resetBrowserGlobals();
  global.document = {createElement: tag => new Element(tag)};
  loadBrowserScript('picsyncra/web/static/module-updates-panel.js');
  const panel = window.PicSyncra.ModuleUpdatesPanel.create({requestJson:async () => ({
    modules:[], offline:true, catalog_error:{code:'rate_limit',message:'GitHub: przekroczono limit zapytań.'}})});
  await panel.refresh();
  const status = panel.element.children.find(child => child.role === 'status');
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
  const bar = panel.element.children.find(child => child.tagName === 'progress');
  const status = panel.element.children.find(child => child.role === 'status');
  assert.ok(bar);
  assert.equal(bar.max,2097152);
  assert.equal(bar.value,1048576);
  assert.match(status.textContent,/OCR.*50%/);
  const controls = panel.element.children.find(child => child.className === 'module-updates-controls');
  assert.ok(controls.children.every(button => button.disabled));
  panel.dispose();
});
