(function attachRuntimeStatusPoller(global) {
  "use strict";

  global.PicSyncra = global.PicSyncra || {};

  class RuntimeStatusPoller {
    constructor(options = {}) {
      this.fetchStatus = options.fetchStatus;
      this.activeIntervalMs = Number(options.activeIntervalMs || 5000);
      this.hiddenIntervalMs = Number(options.hiddenIntervalMs || 30000);
      this.maxBackoffMs = Number(options.maxBackoffMs || 60000);
      this.isHidden = options.isHidden || (() => Boolean(global.document?.hidden));
      this.onVersionChanged = options.onVersionChanged || (() => {});
      this.timerApi = options.timerApi || global;
      this.visibilityTarget = options.visibilityTarget || global.document;
      this.failures = 0;
      this.inFlight = null;
      this.previousVersions = null;
      this.timer = null;
      this.started = false;
      this.pollImmediatelyAfterFlight = false;
      this.handleVisibilityChange = () => {
        this.clearScheduledPoll();
        if (this.isHidden()) {
          this.pollImmediatelyAfterFlight = false;
          if (this.started) this.schedule(this.hiddenIntervalMs);
          return;
        }
        if (this.inFlight) {
          this.pollImmediatelyAfterFlight = true;
          return;
        }
        this.pollNow().catch(() => {});
      };
    }

    pollNow() {
      if (this.inFlight) return this.inFlight;
      let request;
      try {
        request = Promise.resolve(this.fetchStatus());
      } catch (error) {
        request = Promise.reject(error);
      }
      this.inFlight = request
        .then(async (payload) => {
          const versions =
            payload?.versions && typeof payload.versions === "object"
              ? payload.versions
              : {};
          if (this.previousVersions) {
            for (const [name, current] of Object.entries(versions)) {
              const previous = this.previousVersions[name];
              if (!Object.is(current, previous)) {
                await this.onVersionChanged(
                  name,
                  current,
                  previous,
                  payload
                );
              }
            }
          }
          this.previousVersions = { ...versions };
          return payload;
        })
        .then(
          (payload) => {
            this.failures = 0;
            return payload;
          },
          (error) => {
            this.failures += 1;
            throw error;
          }
        )
        .finally(() => {
          this.inFlight = null;
          if (!this.started) return;
          if (this.pollImmediatelyAfterFlight && !this.isHidden()) {
            this.pollImmediatelyAfterFlight = false;
            this.schedule(0);
            return;
          }
          this.schedule(this.nextDelayMs());
        });
      return this.inFlight;
    }

    start() {
      if (!this.started) {
        this.started = true;
        this.visibilityTarget?.addEventListener(
          "visibilitychange",
          this.handleVisibilityChange
        );
      }
      this.clearScheduledPoll();
      return this.pollNow();
    }

    clearScheduledPoll() {
      if (this.timer === null) return;
      this.timerApi.clearTimeout(this.timer);
      this.timer = null;
    }

    schedule(delayMs) {
      this.clearScheduledPoll();
      this.timer = this.timerApi.setTimeout(() => {
        this.timer = null;
        this.pollNow().catch(() => {});
      }, Math.max(0, delayMs));
    }

    nextDelayMs() {
      if (this.isHidden()) return this.hiddenIntervalMs;
      if (!this.failures) return this.activeIntervalMs;
      return Math.min(
        this.maxBackoffMs,
        this.activeIntervalMs * 2 ** this.failures
      );
    }
  }

  global.PicSyncra.RuntimeStatusPoller = RuntimeStatusPoller;
})(window);
