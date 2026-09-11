const path = require("node:path");

function loadBrowserScript(relativePath) {
  const absolutePath = path.resolve(__dirname, "../..", relativePath);
  delete require.cache[require.resolve(absolutePath)];
  require(absolutePath);
}

function resetBrowserGlobals() {
  global.window = { PicSyncra: {} };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

module.exports = { deferred, loadBrowserScript, resetBrowserGlobals };
