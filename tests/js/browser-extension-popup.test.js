const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

function loadImageCollector(document) {
  const popupPath = path.resolve(__dirname, "../..", "picsyncra/browser_extension/popup.js");
  const popupSource = fs.readFileSync(popupPath, "utf8");
  const start = popupSource.indexOf("  function collectImagesFromPage() {");
  const end = popupSource.indexOf("\n  async function currentTab()", start);

  assert.notEqual(start, -1, "popup must define collectImagesFromPage");
  assert.notEqual(end, -1, "collectImagesFromPage must end before currentTab");

  const collectorSource = popupSource.slice(start, end).replace(/^  /gm, "");
  return vm.runInNewContext(`(${collectorSource})`, {
    URL,
    RegExp,
    Set,
    String,
    Number,
    parseInt,
    document,
    location: { href: "https://shop.example.test/product" },
  });
}

function loadSafeImagePreviewUrl() {
  const popupPath = path.resolve(__dirname, "../..", "picsyncra/browser_extension/popup.js");
  const popupSource = fs.readFileSync(popupPath, "utf8");
  const start = popupSource.indexOf("  function safeImagePreviewUrl(value) {");
  const end = popupSource.indexOf("\n  function formatMs", start);

  assert.notEqual(start, -1, "popup must define safeImagePreviewUrl");
  assert.notEqual(end, -1, "safeImagePreviewUrl must end before formatMs");

  const helperSource = popupSource.slice(start, end).replace(/^  /gm, "");
  return vm.runInNewContext(`(${helperSource})`, { URL, String, encodeURI });
}

function textNode(tagName, textContent) {
  return {
    tagName,
    naturalWidth: 0,
    naturalHeight: 0,
    textContent,
    getAttribute: () => null,
  };
}

test("collectImagesFromPage scans script text without serializing the DOM as HTML", () => {
  const document = {
    baseURI: "https://shop.example.test/product",
    title: "Product",
    documentElement: new Proxy({}, {
      get: () => {
        throw new Error("DOM root must not be inspected while scanning");
      },
    }),
    querySelectorAll(selector) {
      if (selector === "script, style") {
        return [textNode("SCRIPT", 'const hero = "https:\\/\\/cdn.example.test/assets/hero.png?version=1";')];
      }
      return [];
    },
  };

  const result = loadImageCollector(document)();

  assert.deepEqual(JSON.parse(JSON.stringify(result.images)), [
    {
      url: "https://cdn.example.test/assets/hero.png?version=1",
      filename: "hero.png?version=1",
      width: 0,
      height: 0,
      size_bytes: 0,
      mime_type: "",
      source: "script.text",
      kind: "image",
    },
  ]);
});

test("safeImagePreviewUrl percent-encodes HTTP(S) image URLs", () => {
  const safeImagePreviewUrl = loadSafeImagePreviewUrl();

  assert.equal(
    safeImagePreviewUrl("https://cdn.example.test/assets/hero image.png?alt=front view"),
    "https://cdn.example.test/assets/hero%20image.png?alt=front%20view"
  );
  assert.equal(
    safeImagePreviewUrl("https://cdn.example.test/assets/hero%20image.png?alt=front%20view"),
    "https://cdn.example.test/assets/hero%20image.png?alt=front%20view"
  );
});

test("safeImagePreviewUrl rejects non-HTTP(S) schemes", () => {
  const safeImagePreviewUrl = loadSafeImagePreviewUrl();

  assert.equal(safeImagePreviewUrl("javascript:alert(1)"), "");
  assert.equal(safeImagePreviewUrl("data:text/html,<script>alert(1)</script>"), "");
});
