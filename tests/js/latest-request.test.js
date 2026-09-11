const test = require("node:test");
const assert = require("node:assert/strict");
global.window = { PicSyncra: {} };
require("../../picsyncra/web/static/latest-request.js");

test("next aborts the previous request and marks only latest current", () => {
  const latest = new window.PicSyncra.LatestRequest();
  const first = latest.next();
  const second = latest.next();
  assert.equal(first.signal.aborted, true);
  assert.equal(first.isCurrent(), false);
  assert.equal(second.signal.aborted, false);
  assert.equal(second.isCurrent(), true);
});

test("request token rejects a changed value and context signature", () => {
  const latest = new window.PicSyncra.LatestRequest();
  const token = latest.next("name\u0000ALFA\u0000STOL");

  assert.equal(token.isCurrent("name\u0000ALFA\u0000STOL"), true);
  assert.equal(token.isCurrent("name\u0000BETA\u0000SZAFA"), false);
});
