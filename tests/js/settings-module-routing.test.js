const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function render(state) {
  const output = [];
  let installed = 0, legacy = 0;
  const context = vm.createContext({state, settingsOutput:{appendChild: panel => output.push(panel)},
    document:{createElement: () => ({children:[], append(...items){this.children.push(...items);},
      appendChild(item){this.children.push(item);}, addEventListener(){}})},
    renderInstalledUpdateControls: panel => {installed++; panel.children.push('installed');},
    moduleBuildStatusUtilities: () => {legacy++; return null;},
    loadModuleBuildStatus: () => Promise.resolve(), renderSettings: () => {}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../picsyncra/web/static/settings-ui.js'), 'utf8'), context);
  vm.runInContext('renderSettingsModuleStatus()', context);
  return {output, installed, legacy};
}
test('installed modules bypass portable build comparison and its missing-build message', () => {
  const result = render({installationUpdatesChecked:true, installationUpdates:{module_mode:true}});
  assert.equal(result.legacy, 0);
  assert.equal(result.installed, 1);
  assert.deepEqual(result.output[0].children, ['installed']);
});
test('initial installation discovery and controller failures do not fetch portable diagnostics', () => {
  for (const state of [{}, {installationUpdatesChecked:true, installationUpdatesError:'controller unavailable'}]) {
    assert.equal(render(state).legacy, 0);
  }
});
test('portable discovery keeps the existing build comparison', () => {
  const result = render({installationUpdatesChecked:true, installationUpdates:null, moduleBuildStatusError:'offline'});
  assert.equal(result.legacy, 1);
  assert.ok(result.output[0].children.length > 1);
});

test('controller status failure offers retry and renders modules after successful retry', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../../picsyncra/web/static/app.js'), 'utf8');
  const start = source.indexOf('function renderInstalledUpdateControls(panel) {');
  const end = source.indexOf('\nfunction ', start + 1);
  const state = {installationUpdatesChecked:true, installationUpdatesError:'temporary 503', activeSettingsTab:'module-status'};
  const panel = {children:[],appendChild(child){this.children.push(child);}};
  let refreshed = 0;
  const context = vm.createContext({state,
    installationUpdatesUtilities: () => ({}),
    document:{createElement:tag => ({tag,events:{},addEventListener(name,handler){this.events[name]=handler;}})},
    loadInstallationUpdates:async () => {state.installationUpdatesError=''; state.installationUpdates={module_mode:true};},
    renderSettings:() => {refreshed++;},
  });
  vm.runInContext(source.slice(start,end),context);
  context.panel=panel;
  vm.runInContext('renderInstalledUpdateControls(panel)',context);
  const retry=panel.children.find(child => child.tag === 'button');
  assert.ok(retry,'status outage must offer retry');
  await retry.events.click();
  assert.equal(refreshed,1);
  assert.equal(state.installationUpdates.module_mode,true);
  assert.equal(state.installationUpdatesError,'');
});
