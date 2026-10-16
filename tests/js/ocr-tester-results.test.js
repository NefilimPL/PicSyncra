const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("OCR tester displays the runtime error beside the image instead of claiming no text", () => {
  const source = fs.readFileSync(path.resolve(__dirname, "../../picsyncra/web/static/settings-ui.js"), "utf8");
  const start = source.indexOf("      livePreview.dispose();");
  const finish = source.indexOf("    } catch (error) {", start);
  let displayed;
  const context = {
    livePreview: { dispose() {} }, results: { appendChild() {} },
    finalSnapshot: { state: "error", result: null, error: "PermissionError: OCR cache is read-only" },
    selected: {}, URL: { createObjectURL: () => "blob:test-image" }, status: {},
    renderOcrDiagnostics(result) { displayed = result; },
  };
  vm.runInNewContext(source.slice(start, finish), context);
  assert.equal(displayed.message, "PermissionError: OCR cache is read-only");
  assert.equal(context.status.textContent, displayed.message);
});
