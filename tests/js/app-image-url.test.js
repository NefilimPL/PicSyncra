const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

function loadSafeOcrDiagnosticImageUrl() {
  const appPath = path.resolve(__dirname, "../..", "picsyncra/web/static/app.js");
  const appSource = fs.readFileSync(appPath, "utf8");
  const start = appSource.indexOf("function safeOcrDiagnosticImageUrl(value) {");
  const end = appSource.indexOf("\n\nfunction renderOcrDiagnosticView", start);

  assert.notEqual(start, -1, "app must define safeOcrDiagnosticImageUrl");
  assert.notEqual(end, -1, "safeOcrDiagnosticImageUrl must precede the OCR renderer");

  const helperSource = appSource.slice(start, end);
  return vm.runInNewContext(`(${helperSource})`, {
    URL,
    String,
    encodeURI,
    decodeURI,
    window: { location: { origin: "https://panel.example.test" } },
  });
}

test("safeOcrDiagnosticImageUrl allows supported diagnostic image URLs", () => {
  const safeOcrDiagnosticImageUrl = loadSafeOcrDiagnosticImageUrl();

  assert.equal(
    safeOcrDiagnosticImageUrl("/api/file?token=abc def"),
    "https://panel.example.test/api/file?token=abc def"
  );
  assert.equal(
    safeOcrDiagnosticImageUrl("blob:https://panel.example.test/7e90370a-462f-4111-b334-d889b2372cb3"),
    "blob:https://panel.example.test/7e90370a-462f-4111-b334-d889b2372cb3"
  );
});

test("safeOcrDiagnosticImageUrl rejects executable URL schemes", () => {
  const safeOcrDiagnosticImageUrl = loadSafeOcrDiagnosticImageUrl();

  assert.equal(safeOcrDiagnosticImageUrl("javascript:alert(1)"), "");
  assert.equal(safeOcrDiagnosticImageUrl("data:text/html,<script>alert(1)</script>"), "");
});
