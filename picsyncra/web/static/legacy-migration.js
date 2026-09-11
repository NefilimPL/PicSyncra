(() => {
  const legacyPrefix = "picorg";
  const currentPrefix = "picsyncra";
  const localStorageRenames = [
    [`${legacyPrefix}-theme`, `${currentPrefix}-theme`],
    [`${legacyPrefix}-web-image-scan-mode`, `${currentPrefix}-web-image-scan-mode`],
    [`${legacyPrefix}-log-autoscroll`, `${currentPrefix}-log-autoscroll`],
    [`${legacyPrefix}-last-login-username`, `${currentPrefix}-last-login-username`],
  ];
  const sessionStorageRenames = [
    [`${legacyPrefix}-active-presence-client-id`, `${currentPrefix}-active-presence-client-id`],
  ];

  function copyIfMissing(storage, sourceKey, targetKey) {
    try {
      if (storage.getItem(targetKey) !== null) return;
      const value = storage.getItem(sourceKey);
      if (value !== null) storage.setItem(targetKey, value);
    } catch (_error) {
      // Local browser storage can be disabled; the panel works without it.
    }
  }

  function migrateStorage(storage, renames) {
    renames.forEach(([sourceKey, targetKey]) => copyIfMissing(storage, sourceKey, targetKey));
    try {
      const legacyKeys = Array.from(
        { length: storage.length },
        (_unused, index) => storage.key(index)
      ).filter((key) => key?.startsWith(`${legacyPrefix}-show-timing-`));
      legacyKeys.forEach((sourceKey) => {
        const targetKey = `${currentPrefix}${sourceKey.slice(legacyPrefix.length)}`;
        copyIfMissing(storage, sourceKey, targetKey);
      });
    } catch (_error) {
      // Reading browser storage is optional for the web panel.
    }
  }

  function migrateLegacyBrowserStorage() {
    migrateStorage(window.localStorage, localStorageRenames);
    migrateStorage(window.sessionStorage, sessionStorageRenames);
  }

  window.PicSyncra = window.PicSyncra || {};
  window.PicSyncra.migrateLegacyBrowserStorage = migrateLegacyBrowserStorage;
  migrateLegacyBrowserStorage();
})();
