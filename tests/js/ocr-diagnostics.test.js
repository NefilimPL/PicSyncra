const test = require("node:test");
const assert = require("node:assert/strict");
const { loadBrowserScript, resetBrowserGlobals } = require("./helpers");

function loadDiagnostics() {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/ocr-diagnostics.js");
  return window.PicSyncra.OcrDiagnostics;
}

test("normalizes paired OCR regions without truncating decimal values", () => {
  const diagnostics = loadDiagnostics();

  const report = diagnostics.normalizeReport({
    available: true,
    regions: [{
      region_id: "region-1",
      fast: { text: "23,4", value: "23.4", confidence: 0.93, bbox: [10, 12, 42, 26] },
      source_bbox: [10, 12, 42, 26],
      crop_bbox: [2, 4, 50, 34],
      accurate: [{ text: "23.4", value: "23.4", confidence: 0.98, bbox: [11, 13, 43, 27] }],
      status: "completed",
      timings_ms: { fast: 12, crop: 3, accurate: 25 },
    }],
    timings_ms: { total: 40 },
  });

  assert.equal(report.regions[0].fast.text, "23,4");
  assert.equal(report.regions[0].fast.value, "23.4");
  assert.equal(report.regions[0].accurate[0].value, "23.4");
  assert.deepEqual(report.regions[0].timings_ms, { fast: 12, crop: 3, accurate: 25 });
  assert.deepEqual(report.timings_ms, { total: 40 });
});

test("progress events update the matching fast-model region only", () => {
  const diagnostics = loadDiagnostics();
  let report = diagnostics.normalizeReport({ available: true });

  report = diagnostics.applyProgressEvent(report, {
    kind: "candidate_regions",
    payload: {
      regions: [
        { region_id: "region-1", text: "100", confidence: 0.97, bbox: [20, 30, 55, 48] },
        { region_id: "region-2", text: "31", confidence: 1, bbox: [70, 80, 100, 96] },
      ],
    },
  });
  report = diagnostics.applyProgressEvent(report, {
    kind: "crop_started",
    payload: { region_id: "region-2", source_bbox: [70, 80, 100, 96], bbox: [62, 72, 108, 104] },
  });
  report = diagnostics.applyProgressEvent(report, {
    kind: "crop_finished",
    payload: {
      region_id: "region-2",
      accurate: [{ text: "31", confidence: 0.99, bbox: [71, 81, 101, 97] }],
      status: "completed",
      crop_elapsed_ms: 4,
      accurate_elapsed_ms: 19,
    },
  });

  assert.equal(report.regions[0].status, "detected");
  assert.equal(report.regions[1].status, "completed");
  assert.deepEqual(report.regions[1].crop_bbox, [62, 72, 108, 104]);
  assert.equal(report.regions[1].accurate[0].text, "31");
  assert.deepEqual(report.regions[1].timings_ms, { fast: 0, crop: 4, accurate: 19 });
});

test("places colliding labels in distinct usable positions", () => {
  const diagnostics = loadDiagnostics();
  const placements = diagnostics.placeLabels([
    { id: "fast", bbox: [100, 100, 150, 120], width: 48, height: 18 },
    { id: "accurate", bbox: [104, 102, 154, 122], width: 48, height: 18 },
  ], { width: 320, height: 240 });

  assert.equal(placements.length, 2);
  assert.notDeepEqual(
    [placements[0].left, placements[0].top],
    [placements[1].left, placements[1].top],
  );
  assert.notEqual(placements[0].position, placements[1].position);
  for (const placement of placements) {
    assert.ok(placement.left >= 0);
    assert.ok(placement.top >= 0);
    assert.ok(placement.left + placement.width <= 320);
    assert.ok(placement.top + placement.height <= 240);
  }
});

test("places labels using the rendered image size, not the natural pixel size", () => {
  const diagnostics = loadDiagnostics();
  const placements = diagnostics.placeLabelsForRenderedImage([
    { id: "fast", bbox: [800, 400, 920, 440], width: 78, height: 21 },
    { id: "accurate", bbox: [804, 402, 924, 442], width: 86, height: 21 },
  ], {
    naturalWidth: 1600,
    naturalHeight: 900,
    renderedWidth: 400,
    renderedHeight: 225,
  });

  assert.equal(placements.length, 2);
  assert.notDeepEqual(
    [placements[0].left, placements[0].top],
    [placements[1].left, placements[1].top],
  );
  assert.notEqual(placements[0].position, placements[1].position);
  for (const placement of placements) {
    assert.ok(placement.left >= 0);
    assert.ok(placement.top >= 0);
    assert.ok(placement.left + placement.width <= 400);
    assert.ok(placement.top + placement.height <= 225);
  }
});
