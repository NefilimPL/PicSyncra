(() => {
  const root = window.PicSyncra = window.PicSyncra || {};

  function text(value) {
    return value === undefined || value === null ? "" : String(value).trim();
  }

  function normalizeRelease(value) {
    const source = value && typeof value === "object" ? value : {};
    const releaseId = Number(source.release_id);
    return {
      release_id: Number.isInteger(releaseId) && releaseId > 0 ? releaseId : null,
      tag: text(source.tag),
      channel: source.channel === "dev" ? "dev" : "stable",
      can_install: source.can_install === true,
      blocked_reason: text(source.blocked_reason),
      components: Array.isArray(source.components) ? source.components : [],
    };
  }

  function normalizeSnapshot(value) {
    const source = value && typeof value === "object" ? value : {};
    const maintenance = source.maintenance && typeof source.maintenance === "object"
      ? source.maintenance : {};
    return {
      channel: source.channel === "dev" ? "dev" : "stable",
      build: text(source.build),
      backend_running: source.backend_running === true,
      autostart: source.autostart === true,
      maintenance: {
        state: text(maintenance.state || "idle"),
        active_tasks: Number.isInteger(maintenance.active_tasks) ? maintenance.active_tasks : 0,
        other_users: Number.isInteger(maintenance.other_users) ? maintenance.other_users : 0,
        deadline_utc: maintenance.deadline_utc === null ? null : text(maintenance.deadline_utc) || null,
        force_allowed: maintenance.force_allowed === true,
      },
    };
  }

  function requestId() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
    return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function operationRequest(action, releaseId = null) {
    if (!["update", "downgrade", "install_ocr", "restart"].includes(action)) {
      throw new Error("Niepoprawna operacja instalacji.");
    }
    const parsedRelease = Number(releaseId);
    const needsRelease = action === "update" || action === "downgrade";
    if (needsRelease && (!Number.isInteger(parsedRelease) || parsedRelease <= 0)) {
      throw new Error("Wybierz poprawne wydanie.");
    }
    return {
      request_id: requestId(),
      action,
      release_id: needsRelease ? parsedRelease : null,
      restore_backup_id: null,
      acknowledge_data_loss: false,
    };
  }

  async function loadReleases(channel, requestJson) {
    if (channel !== "stable" && channel !== "dev") throw new Error("Niepoprawny kanal wydan.");
    const payload = await requestJson(`/api/installation/releases?channel=${encodeURIComponent(channel)}`);
    return Array.isArray(payload?.releases) ? payload.releases.map(normalizeRelease) : [];
  }

  async function submitOperation(request, requestJson) {
    return requestJson("/api/installation/operations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  }

  root.InstallationUpdates = {
    normalizeSnapshot,
    normalizeRelease,
    operationRequest,
    loadReleases,
    submitOperation,
  };
})();
