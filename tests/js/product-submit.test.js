const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("a rejected product submission preserves fields and cached slot photos", async () => {
  const source = fs.readFileSync(path.resolve(__dirname, "../../picsyncra/web/static/app.js"), "utf8");
  const submit = source.slice(
    source.indexOf("function handleProductSubmitError("),
    source.indexOf('productForm.addEventListener("submit",'),
  );
  const fields = { name: "TEST", type_name: "TEST", model: "test", color1: "", ean: "" };
  const photo = { token: "cached-photo-token" };
  const files = new Map([["01", photo]]);
  let resets = 0;
  let errorMessage = "";
  let busy = false;
  let requests = 0;
  const context = {
    state: { slots: [{ prefix: "01" }], files, loadedPhotos: new Map(), deletedSlots: new Map() },
    productForm: { elements: fields },
    FormData: class { delete() {} set() {} },
    clearResult() {}, recordOcrActivity() {}, ensureSlotUploadsReady() {},
    setBusy(value) { busy = value; },
    ensureProductListValues: async () => {},
    pendingSimilarCandidatePrefixes: () => [],
    productFieldsChangedSinceLoad: () => false,
    hasPendingUserChanges: () => false,
    pendingChangedSlotPrefixes: () => new Set(),
    slotFileToken: (item) => item.token, slotFileName: () => "photo.jpg", isSlotFit: () => true,
    startProcessStatusTicker() {}, stopProcessStatusTicker() {},
    requestJson: async () => { requests += 1; throw new Error("Kolor 1 jest wymagany"); },
    showError(error) { errorMessage = error.message; },
    resetCurrentDraft() { resets += 1; }, trackProcessJob() {}, showQueuedProcess() {},
  };
  vm.createContext(context);
  vm.runInContext(submit, context);
  await context.submitProductForm();
  assert.equal(requests, 1);
  assert.equal(resets, 0);
  assert.equal(errorMessage, "Kolor 1 jest wymagany");
  assert.equal(busy, false);
  assert.deepEqual(fields, { name: "TEST", type_name: "TEST", model: "test", color1: "", ean: "" });
  assert.equal(files.get("01"), photo);
});
