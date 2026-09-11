(() => {
  const root = window.PicSyncra = window.PicSyncra || {};

  function text(value) {
    return value === undefined || value === null ? "" : String(value);
  }

  function normalizeModule(value) {
    const source = value && typeof value === "object" ? value : {};
    return {
      id: text(source.id),
      label: text(source.label),
      build_commit: text(source.build_commit),
      build_committed_at: text(source.build_committed_at),
      local_commit: text(source.local_commit),
      local_committed_at: text(source.local_committed_at),
      status: text(source.status || "repository_unavailable"),
    };
  }

  function normalizeBuild(value) {
    if (!value || typeof value !== "object") return null;
    return {
      build_variant: text(value.build_variant),
      generated_at: text(value.generated_at),
      repository_commit: text(value.repository_commit),
    };
  }

  function normalizeSnapshot(value) {
    const source = value && typeof value === "object" ? value : {};
    return {
      build: normalizeBuild(source.build),
      repository_status: text(source.repository_status || "unavailable"),
      modules: Array.isArray(source.modules) ? source.modules.map(normalizeModule) : [],
      status: text(source.status),
    };
  }

  function statusLabel(status) {
    return {
      matching: "Zgodny",
      rebuild_required: "Wymaga ponownego builda",
      uncommitted_changes: "Niezacommitowane zmiany",
      repository_unavailable: "Repozytorium niedostepne",
      build_metadata_missing: "Brak danych buildu",
    }[status] || "Nieznany status";
  }

  function commitUrl(value) {
    const commit = text(value).trim();
    return /^[0-9a-f]{40}$/i.test(commit)
      ? `https://github.com/NefilimPL/PicSyncra/commit/${commit}`
      : "";
  }

  root.ModuleBuildStatus = { normalizeSnapshot, statusLabel, commitUrl };
})();
