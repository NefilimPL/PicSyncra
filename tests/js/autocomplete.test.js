const test = require("node:test");
const assert = require("node:assert/strict");
const { deferred, loadBrowserScript, resetBrowserGlobals } = require("./helpers");

test("controller merges the latest remote values with local values", async () => {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/latest-request.js");
  loadBrowserScript("picsyncra/web/static/autocomplete.js");

  const rendered = [];
  const remote = deferred();
  const controller = new window.PicSyncra.AutocompleteController({
    fieldName: "name",
    localSuggestions: () => ["LOCAL"],
    remoteSuggestions: () => remote.promise,
    render: (values) => rendered.push(values),
    delayMs: 0,
    setTimer: (callback) => (callback(), 1),
    clearTimer: () => {},
  });

  controller.refresh();
  remote.resolve(["REMOTE"]);
  await controller.pendingForTest();

  assert.deepEqual(rendered.at(-1), ["LOCAL", "REMOTE"]);
});

test("controller ignores remote results after the request context changes", async () => {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/latest-request.js");
  loadBrowserScript("picsyncra/web/static/autocomplete.js");

  const scheduled = [];
  const rendered = [];
  const remote = deferred();
  let requestSnapshot = { signature: "name\u0000AL", payload: { name: "AL" } };
  const controller = new window.PicSyncra.AutocompleteController({
    fieldName: "name",
    localSuggestions: () => ["ALFA"],
    remoteSuggestions: () => remote.promise,
    render: (values) => rendered.push(values),
    captureRequest: () => requestSnapshot,
    getQuery: () => requestSnapshot.payload.name,
    delayMs: 180,
    setTimer: (callback, delay) => {
      scheduled.push({ callback, delay });
      return scheduled.length;
    },
    clearTimer: () => {},
  });

  assert.equal(controller.refresh(), true);
  assert.equal(scheduled[0].delay, 180);
  const pending = scheduled.shift().callback();
  requestSnapshot = { signature: "name\u0000BETA", payload: { name: "BETA" } };
  remote.resolve(["ALFABET"]);
  await pending;

  assert.deepEqual(rendered, [["ALFA"]]);
});

test("controller skips remote work when local visible results fill the panel", () => {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/latest-request.js");
  loadBrowserScript("picsyncra/web/static/autocomplete.js");

  const scheduled = [];
  const rendered = [];
  const local = Array.from({ length: 80 }, (_value, index) => `ALFA-${index}`);
  const controller = new window.PicSyncra.AutocompleteController({
    fieldName: "name",
    localSuggestions: () => local,
    remoteSuggestions: () => Promise.resolve([]),
    render: (values) => rendered.push(values),
    getQuery: () => "ALFA",
    setTimer: (callback, delay) => {
      scheduled.push({ callback, delay });
      return scheduled.length;
    },
    clearTimer: () => {},
    limit: 80,
  });

  assert.equal(controller.refresh(), false);
  assert.deepEqual(scheduled, []);
  assert.deepEqual(rendered, [local]);
});
