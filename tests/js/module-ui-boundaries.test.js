const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');

function body(name) {
  for (const file of ['slot-ui.js', 'settings-ui.js', 'ocr-tester-ui.js', 'app.js']) {
    const location = path.join(root, 'picsyncra/web/static', file);
    if (!fs.existsSync(location)) continue;
    const source = fs.readFileSync(location, 'utf8');
    const start = source.indexOf(`function ${name}(`);
    if (start < 0) continue;
    const end = source.indexOf('\n}', start);
    return source.slice(start, end + 2);
  }
  throw Error(`Missing ${name}`);
}

test('slot assignment preserves the selected file and fit flag', () => {
  const item = {token: 'file-1'};
  const context = {state: {files: new Map([['A', item]]), loadedPhotos: new Map()},
    isSlotFit: () => true};
  vm.runInNewContext(body('getSlotAssignment') + '; result=getSlotAssignment("A")', context);
  assert.equal(context.result.value, item);
  assert.equal(context.result.type, 'file');
  assert.equal(context.result.fit, true);
});

test('settings dispatch renders only the selected tab', () => {
  const calls = [];
  const context = {state: {settings: {windows_admin: false}, activeSettingsTab: 'ftp'},
    settingsOutput: {textContent: 'old'}, settingsStatus: {},
    document: {querySelectorAll: () => []}, renderSettingsFtp: () => calls.push('ftp')};
  vm.runInNewContext(body('renderSettings') + '; renderSettings()', context);
  assert.deepEqual(calls, ['ftp']);
  assert.equal(context.settingsOutput.textContent, '');
});

test('OCR diagnostics rejects script URLs', () => {
  const context = {URL, window: {location: {origin: 'http://localhost'}}};
  vm.runInNewContext(body('safeOcrDiagnosticImageUrl') + '; result=safeOcrDiagnosticImageUrl("javascript:alert(1)")', context);
  assert.equal(context.result, '');
});

test('independent scripts contain definitions without initializing application state', () => {
  for (const file of ['slot-ui.js', 'settings-ui.js', 'ocr-tester-ui.js']) {
    vm.runInNewContext(fs.readFileSync(path.join(root, 'picsyncra/web/static', file), 'utf8'), {});
  }
});
