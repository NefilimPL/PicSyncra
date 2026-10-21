const test = require("node:test");
const assert = require("node:assert/strict");
const { loadBrowserScript, resetBrowserGlobals } = require("./helpers");

function loadUpdates() {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/installation-updates.js");
  return window.PicSyncra.InstallationUpdates;
}

test("normalizes installed status without accepting private implementation fields", () => {
  const updates = loadUpdates();
  const snapshot = updates.normalizeSnapshot({
    channel: "dev", build: 42, backend_running: true,
    maintenance: { state: "draining", active_tasks: 2, force_allowed: true, program_root: "C:\\secret" },
  });

  assert.equal(snapshot.channel, "dev");
  assert.equal(snapshot.maintenance.active_tasks, 2);
  assert.equal("program_root" in snapshot.maintenance, false);
});

test("an update requires a selected signed release while restart does not", () => {
  const updates = loadUpdates();

  assert.throws(() => updates.operationRequest("update"), /Wybierz/);
  assert.equal(updates.operationRequest("restart").release_id, null);
  assert.equal(updates.operationRequest("update", 42).release_id, 42);
});

test("does not submit the currently active release as an update", () => {
  const updates = loadUpdates();

  assert.equal(
    updates.selectUpdateTarget([
      { release_id: 43, can_install: true },
      { release_id: 42, can_install: true },
      { release_id: 41, can_install: true },
    ], 42).release_id,
    43,
  );
  assert.equal(updates.selectUpdateTarget([{ release_id: 42, can_install: true }, { release_id: 41, can_install: true }], 42), null);
});

test("release loading and operation submission use only fixed installed API routes", async () => {
  const updates = loadUpdates();
  const calls = [];
  const requestJson = async (path, options) => {
    calls.push({ path, options });
    return path.includes("releases") ? { releases: [{ release_id: 8, can_install: true }] } : { operation_id: "op-1" };
  };

  const releases = await updates.loadReleases("stable", requestJson);
  await updates.submitOperation(updates.operationRequest("restart"), requestJson);

  assert.equal(releases[0].release_id, 8);
  assert.equal(calls[0].path, "/api/installation/releases?channel=stable");
  assert.equal(calls[1].path, "/api/installation/operations");
  assert.equal(calls[1].options.method, "POST");
});
