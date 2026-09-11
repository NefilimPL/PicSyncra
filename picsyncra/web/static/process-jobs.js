(function registerProcessJobs(global) {
  "use strict";

  global.PicSyncra = global.PicSyncra || {};

  function activeJobFrom(payload) {
    if (payload?.current && typeof payload.current === "object") {
      return payload.current;
    }
    return (payload?.jobs || []).find((job) =>
      ["queued", "running"].includes(job?.status)
    ) || null;
  }

  class ProcessJobsController {
    constructor(options = {}) {
      this.fetchJobs = options.fetchJobs || (() => Promise.resolve({ jobs: [] }));
      this.render = options.render || (() => {});
      this.timerApi = options.timerApi || global;
      this.inFlight = null;
      this.runtimeVersion = null;
      this.activeJob = null;
    }

    refresh(runtimeVersion) {
      if (runtimeVersion !== undefined) this.runtimeVersion = runtimeVersion;
      if (this.inFlight) return this.inFlight;

      const requestState = {
        runtimeVersion: this.runtimeVersion,
        activeJob: this.activeJob,
      };
      let request;
      try {
        request = Promise.resolve(this.fetchJobs(requestState));
      } catch (error) {
        request = Promise.reject(error);
      }
      this.inFlight = request
        .then((payload) => {
          const previousActiveJob = this.activeJob;
          this.activeJob = activeJobFrom(payload);
          this.render(payload, {
            runtimeVersion: this.runtimeVersion,
            activeJob: this.activeJob,
            previousActiveJob,
          });
          return payload;
        })
        .finally(() => {
          this.inFlight = null;
        });
      return this.inFlight;
    }
  }

  global.PicSyncra.ProcessJobsController = ProcessJobsController;
})(window);
