const test = require("node:test");
const assert = require("node:assert/strict");

function createStorage(values = {}) {
  const entries = new Map(Object.entries(values));
  return {
    getItem(key) {
      return entries.has(key) ? entries.get(key) : null;
    },
    setItem(key, value) {
      entries.set(key, String(value));
    },
    key(index) {
      return [...entries.keys()][index] ?? null;
    },
    get length() {
      return entries.size;
    },
  };
}

test("browser migration copies existing preferences without replacing PicSyncra values", () => {
  const localStorage = createStorage({
    "picorg-theme": "dark",
    "picorg-show-timing-admin": "1",
    "picsyncra-log-autoscroll": "true",
  });
  const sessionStorage = createStorage({
    "picorg-active-presence-client-id": "legacy-client",
  });
  global.window = { PicSyncra: {}, localStorage, sessionStorage };

  require("../../picsyncra/web/static/legacy-migration.js");

  assert.equal(localStorage.getItem("picsyncra-theme"), "dark");
  assert.equal(localStorage.getItem("picsyncra-show-timing-admin"), "1");
  assert.equal(localStorage.getItem("picsyncra-log-autoscroll"), "true");
  assert.equal(sessionStorage.getItem("picsyncra-active-presence-client-id"), "legacy-client");
});
