const test = require("node:test");
const assert = require("node:assert/strict");
const { deferred, loadBrowserScript, resetBrowserGlobals } = require("./helpers");

function autocompleteInput(values) {
  resetBrowserGlobals();
  window.Event = Event;
  loadBrowserScript("picsyncra/web/static/latest-request.js");
  loadBrowserScript("picsyncra/web/static/autocomplete.js");
  function element() {
    const classes = new Set();
    return {
      dataset: {}, children: [], textContent: "",
      classList: {
        add: (value) => classes.add(value), remove: (value) => classes.delete(value),
        contains: (value) => classes.has(value),
        toggle: (value, active) => active ? classes.add(value) : classes.delete(value),
      },
      setAttribute() {}, addEventListener() {}, scrollIntoView() {},
      appendChild(child) { this.children.push(child); },
      append(...children) { this.children.push(...children); this.textContent += children.map((child) => child.textContent).join(""); },
      querySelectorAll() { return this.children; },
    };
  }
  const handlers = {};
  const host = element();
  const input = {
    value: "NEW COLOR", removeAttribute() {}, setAttribute() {}, dispatchEvent() {},
    closest: () => host,
    addEventListener(name, handler) { (handlers[name] ||= []).push(handler); },
  };
  const document = {
    activeElement: input, createElement: element, addEventListener() {},
    createTextNode: (textContent) => ({ textContent }),
    querySelectorAll: () => host.children,
  };
  window.PicSyncra.setupAutocomplete({
    document, productForm: { elements: { color1: input }, setAttribute() {} },
    fieldNames: ["color1"], localSuggestions: () => values,
    setTimer: () => 1, clearTimer() {},
  });
  for (const handler of handlers.focus) handler();
  return {
    input,
    key(key) {
      const event = { key, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
      for (const handler of handlers.keydown) handler(event);
      return event;
    },
  };
}

test("Enter while typing a new color cannot implicitly submit and clear the draft", () => {
  const field = autocompleteInput([]);
  const event = field.key("Enter");
  assert.equal(event.defaultPrevented, true);
  assert.equal(field.input.value, "NEW COLOR");
});

test("Enter with suggestions but no selected option cannot submit the draft", () => {
  const field = autocompleteInput(["NEW COLOR VARIANT"]);
  assert.equal(field.key("Enter").defaultPrevented, true);
  assert.equal(field.input.value, "NEW COLOR");
});

test("Enter still commits an explicitly selected suggestion", () => {
  const field = autocompleteInput(["NEW COLOR VARIANT"]);
  field.key("ArrowDown");
  assert.equal(field.key("Enter").defaultPrevented, true);
  assert.equal(field.input.value, "NEW COLOR VARIANT");
});

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
