const test = require('node:test');
const assert = require('node:assert/strict');
const {loadBrowserScript, resetBrowserGlobals} = require('./helpers');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.value = ''; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); }
  addEventListener(name, callback) { this.events[name] = callback; }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
}
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
