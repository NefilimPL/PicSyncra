const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const elements = [], requests = [];
  class Element {
    constructor(tag) { this.tagName = tag; this.events = {}; this.children = []; }
    append(...items) { this.children.push(...items); elements.push(...items); }
    prepend(...items) { this.children.unshift(...items); elements.push(...items); }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, callback) { this.events[name] = callback; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    remove() { this.removed = true; }
  }
  const source = fs.readFileSync('picsyncra/web/static/app.js', 'utf8');
  const context = {
    state:{installationMaintenanceState:'idle'},
    document:{createElement:tag => new Element(tag), body:new Element('body'),
      querySelector:selector => elements.find(element => '#' + element.id === selector && !element.removed)},
    requestJson:async (url, options) => { requests.push([url, JSON.parse(options.body)]); return {}; },
    showError:error => { throw error; },
  };
  vm.runInNewContext(source.slice(source.indexOf('function showReleaseNotice('), source.indexOf('function renderInstallationMaintenanceNotice(')), context);
  vm.runInNewContext(source.slice(source.indexOf('function renderInstallationMaintenanceNotice('), source.indexOf('function moduleBuildStatusValue(')), context);
  return {context, elements, requests};
}

test('release notice displays safe text and records an account receipt on dismissal', async () => {
  const {context, elements, requests} = harness();
  const notice = {tag:'v6', version_id:'new-core', body:'<script>unsafe()</script>', url:'javascript:unsafe()'};
  context.showReleaseNotice(notice);
  context.showReleaseNotice(notice);
  assert.equal(elements.filter(element => element.tagName === 'dialog').length, 1);
  assert.equal(elements.find(element => element.tagName === 'pre').textContent, notice.body);
  assert.equal(elements.find(element => element.tagName === 'a').href, undefined);
  assert.equal(requests.length, 0);
  const dialog = elements.find(element => element.tagName === 'dialog');
  await dialog.events.cancel({preventDefault(){}});
  assert.deepEqual(requests, [['/api/installation/release-notice/read', {version_id:'new-core'}]]);
  assert.equal(dialog.open, false);
  assert.equal(dialog.removed, true);
});

test('maintenance notice explains the pause even after running work has drained', () => {
  const {context, elements} = harness();
  context.renderInstallationMaintenanceNotice({state:'ready'});
  const notice = elements.find(element => element.id === 'installationMaintenanceNotice');
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /aktualizacja.*kontynuować po zakończeniu/);
  context.renderInstallationMaintenanceNotice({state:'draining'});
  assert.match(notice.textContent, /Rozpoczęte zadania zostaną ukończone/);
});
