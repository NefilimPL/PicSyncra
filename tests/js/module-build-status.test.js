const test = require("node:test");
const assert = require("node:assert/strict");
const { loadBrowserScript, resetBrowserGlobals } = require("./helpers");

function loadModuleBuildStatus() {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/module-build-status.js");
  return window.PicSyncra.ModuleBuildStatus;
}

test("normalizes a rebuild-required module and translates its status", () => {
  const status = loadModuleBuildStatus();
  const snapshot = status.normalizeSnapshot({
    build: { build_variant: "web-ocr", generated_at: "2026-08-27T10:00:00+00:00" },
    repository_status: "available",
    modules: [{
      id: "ocr",
      label: "OCR",
      build_commit: "old",
      local_commit: "new",
      status: "rebuild_required",
    }],
  });

  assert.equal(snapshot.modules[0].status, "rebuild_required");
  assert.equal(status.statusLabel(snapshot.modules[0].status), "Wymaga ponownego builda");
});

test("keeps embedded build metadata when no local repository is available", () => {
  const status = loadModuleBuildStatus();
  const snapshot = status.normalizeSnapshot({
    build: { build_variant: "local", repository_commit: "abc123" },
    repository_status: "unavailable",
    modules: [],
  });

  assert.equal(snapshot.repository_status, "unavailable");
  assert.equal(snapshot.build.build_variant, "local");
  assert.equal(snapshot.build.repository_commit, "abc123");
});

test("creates a GitHub commit URL only for a complete commit hash", () => {
  const status = loadModuleBuildStatus();
  const commit = "a".repeat(40);

  assert.equal(
    status.commitUrl(commit),
    `https://github.com/NefilimPL/PicSyncra/commit/${commit}`,
  );
  assert.equal(status.commitUrl("abc123"), "");
});
