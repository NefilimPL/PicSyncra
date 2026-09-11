const test = require("node:test");
const assert = require("node:assert/strict");
const { deferred, loadBrowserScript, resetBrowserGlobals } = require("./helpers");

test("refresh shares one in-flight process-job request", async () => {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/process-jobs.js");

  let requests = 0;
  const pending = deferred();
  const rendered = [];
  const controller = new window.PicSyncra.ProcessJobsController({
    fetchJobs: () => {
      requests += 1;
      return pending.promise;
    },
    render: (payload) => rendered.push(payload),
    timerApi: {},
  });

  const first = controller.refresh();
  const second = controller.refresh();

  assert.equal(first, second);
  assert.equal(requests, 1);
  pending.resolve({ jobs: [] });
  await Promise.all([first, second]);
  assert.deepEqual(rendered, [{ jobs: [] }]);
});

test("refresh retains the runtime version and active job for rendering", async () => {
  resetBrowserGlobals();
  loadBrowserScript("picsyncra/web/static/process-jobs.js");

  const rendered = [];
  const runningJob = { job_id: "job-1", status: "running" };
  const controller = new window.PicSyncra.ProcessJobsController({
    fetchJobs: async () => ({ jobs: [runningJob], current: runningJob }),
    render: (payload, state) => rendered.push({ payload, state }),
    timerApi: {},
  });

  await controller.refresh("queue-v2");

  assert.equal(controller.runtimeVersion, "queue-v2");
  assert.equal(controller.activeJob, runningJob);
  assert.equal(rendered[0].state.runtimeVersion, "queue-v2");
  assert.equal(rendered[0].state.activeJob, runningJob);
});
