(function () {
  const defaults = window.PICSYNCRA_EXTENSION_DEFAULTS || {};
  const state = {
    images: [],
    selected: new Set(),
    filters: {
      minWidth: 0,
      minHeight: 0,
      hideThumbnails: false,
      urlFilter: "",
    },
    uploadStatus: {},
  };

  const panelUrlInput = document.querySelector("#panelUrl");
  const apiTokenInput = document.querySelector("#apiToken");
  const settingsToggle = document.querySelector("#settingsToggle");
  const filtersToggle = document.querySelector("#filtersToggle");
  const settingsPanel = document.querySelector("#settingsPanel");
  const filtersPanel = document.querySelector("#filtersPanel");
  const minWidthInput = document.querySelector("#minWidth");
  const minHeightInput = document.querySelector("#minHeight");
  const hideThumbnailsInput = document.querySelector("#hideThumbnails");
  const urlFilterInput = document.querySelector("#urlFilter");
  const saveSettingsButton = document.querySelector("#saveSettings");
  const testConnectionButton = document.querySelector("#testConnection");
  const scanPageButton = document.querySelector("#scanPage");
  const selectAllButton = document.querySelector("#selectAll");
  const clearSelectionButton = document.querySelector("#clearSelection");
  const retryFailedButton = document.querySelector("#retryFailed");
  const uploadSelectedButton = document.querySelector("#uploadSelected");
  const statusOutput = document.querySelector("#status");
  const summaryOutput = document.querySelector("#summary");
  const imagesOutput = document.querySelector("#images");

  function setStatus(text) {
    statusOutput.textContent = text || "";
  }

  function extensionStorageGet(keys) {
    return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
  }

  function extensionStorageSet(values) {
    return new Promise((resolve) => chrome.storage.local.set(values, resolve));
  }

  function runtimeMessage(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, (response) => {
        const error = chrome.runtime.lastError;
        if (error) {
          reject(new Error(error.message || "Blad komunikacji z dodatkiem."));
          return;
        }
        resolve(response);
      });
    });
  }

  function normalizePanelUrl(value) {
    return String(value || "").trim().replace(/\/+$/, "");
  }

  function imageFilename(url, fallback = "web-image.jpg") {
    try {
      const path = new URL(url).pathname;
      const name = decodeURIComponent(path.split("/").pop() || "").trim();
      return name || fallback;
    } catch (_error) {
      return fallback;
    }
  }

  function safeImagePreviewUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol !== "http:" && url.protocol !== "https:") return "";
      return encodeURI(decodeURI(url.href));
    } catch (_error) {
      return "";
    }
  }

  function formatMs(value) {
    const ms = Math.max(0, Math.round(Number(value || 0)));
    return `${ms} ms`;
  }

  function formatBytes(bytes) {
    const value = Math.max(0, Number(bytes || 0));
    if (!value) return "";
    if (value < 1024) return `${Math.round(value)} B`;
    if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function positiveInt(value) {
    const parsed = parseInt(String(value || "0"), 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

  function readFilters() {
    state.filters = {
      minWidth: positiveInt(minWidthInput?.value),
      minHeight: positiveInt(minHeightInput?.value),
      hideThumbnails: Boolean(hideThumbnailsInput?.checked),
      urlFilter: String(urlFilterInput?.value || "").trim().toLowerCase(),
    };
    return state.filters;
  }

  async function saveFilters() {
    readFilters();
    await extensionStorageSet({ filters: state.filters });
  }

  function applyFiltersToInputs() {
    if (minWidthInput) minWidthInput.value = String(state.filters.minWidth || 0);
    if (minHeightInput) minHeightInput.value = String(state.filters.minHeight || 0);
    if (hideThumbnailsInput) hideThumbnailsInput.checked = Boolean(state.filters.hideThumbnails);
    if (urlFilterInput) urlFilterInput.value = state.filters.urlFilter || "";
  }

  function isThumbnailImage(image) {
    const width = Number(image?.width || 0);
    const height = Number(image?.height || 0);
    const text = `${image?.url || ""} ${image?.source || ""} ${image?.kind || ""}`.toLowerCase();
    return (
      image?.kind === "thumbnail" ||
      /thumb|thumbnail|small|mini|cart_default|home_default|small_default/.test(text) ||
      (width > 0 && height > 0 && Math.max(width, height) <= 320)
    );
  }

  function parseUrlFilterText(text) {
    const parsed = { include: [], exclude: [] };
    const matches = String(text || "").toLowerCase().match(/!?<[^>]+>|[^\s,;]+/g) || [];
    for (let part of matches) {
      part = part.trim();
      if (!part) continue;
      let target = parsed.include;
      if (part.startsWith("!") && part.length > 1) {
        target = parsed.exclude;
        part = part.slice(1);
      }
      const terms =
        part.startsWith("<") && part.endsWith(">")
          ? part
              .slice(1, -1)
              .split("|")
              .map((term) => term.trim())
              .filter(Boolean)
          : [part];
      if (terms.length) target.push(terms);
    }
    return parsed;
  }

  function imageMatchesUrlFilter(image, text) {
    const parsed = parseUrlFilterText(text);
    const haystack = `${image?.url || ""} ${image?.filename || ""} ${image?.source || ""}`.toLowerCase();
    if (parsed.exclude.some((group) => group.some((term) => haystack.includes(term)))) return false;
    if (parsed.include.some((group) => !group.some((term) => haystack.includes(term)))) return false;
    return true;
  }

  function imagePassesFilters(image) {
    const filters = readFilters();
    const width = Number(image?.width || 0);
    const height = Number(image?.height || 0);
    if (!imageMatchesUrlFilter(image, filters.urlFilter)) return false;
    if (filters.hideThumbnails && isThumbnailImage(image)) return false;
    if (filters.minWidth && width && width < filters.minWidth) return false;
    if (filters.minHeight && height && height < filters.minHeight) return false;
    return true;
  }

  function visibleImageEntries() {
    return state.images
      .map((image, index) => ({ image, index }))
      .filter((entry) => imagePassesFilters(entry.image));
  }

  function uploadStatusTasks(status = state.uploadStatus) {
    return [
      ...(Array.isArray(status.active) ? status.active : []),
      ...(Array.isArray(status.queued) ? status.queued : []),
      ...(Array.isArray(status.recent) ? status.recent : []),
    ];
  }

  function uploadTaskForImage(image) {
    const url = String(image?.url || "");
    if (!url) return null;
    return uploadStatusTasks().find((task) => String(task.url || "") === url) || null;
  }

  function collectImagesFromPage() {
    const imageExtensionPattern =
      "jpe?g|jfif|jpe|peg|png|apng|webp|gif|bmp|dib|tiff?|avif|avifs|heic|heif|hif|jp2|j2k|jpc|jpx|ico|cur|tga|ppm|pgm|pbm|pnm|pcx";
    const imageExtensions = new RegExp(`\\.(${imageExtensionPattern})(\\?|#|$)`, "i");
    const ignored = /^(data:|javascript:|mailto:|tel:)/i;
    const seen = new Set();
    const result = [];

    function absoluteUrl(raw) {
      const value = String(raw || "").replace(/&amp;/g, "&").replace(/\\\//g, "/").trim();
      if (!value || ignored.test(value)) return "";
      try {
        return new URL(value, document.baseURI).href.split("#", 1)[0];
      } catch (_error) {
        return "";
      }
    }

    function kindFrom(url, source, width, height) {
      const text = `${url} ${source}`.toLowerCase();
      if (/thumb|thumbnail|small|mini|cart_default|home_default|small_default/.test(text)) {
        return "thumbnail";
      }
      if (width && height && Math.max(width, height) <= 320) {
        return "thumbnail";
      }
      return "image";
    }

    function add(raw, source, width = 0, height = 0) {
      const url = absoluteUrl(raw);
      if (!url || !imageExtensions.test(url) || seen.has(url)) return;
      seen.add(url);
      result.push({
        url,
        filename: url.split("/").pop() || "web-image.jpg",
        width: Number(width || 0),
        height: Number(height || 0),
        size_bytes: 0,
        mime_type: "",
        source,
        kind: kindFrom(url, source, Number(width || 0), Number(height || 0)),
      });
    }

    function parseSrcset(value, source, fallbackWidth = 0, fallbackHeight = 0) {
      String(value || "")
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean)
        .forEach((part) => {
          const bits = part.split(/\s+/);
          let width = fallbackWidth;
          for (const bit of bits.slice(1)) {
            if (/^\d+(\.\d+)?w$/i.test(bit)) {
              width = parseInt(bit, 10) || fallbackWidth;
              break;
            }
          }
          add(bits[0], source, width, fallbackHeight);
        });
    }

    document.querySelectorAll("img, source, a, link, meta").forEach((node) => {
      const width = parseInt(node.getAttribute("width") || node.naturalWidth || "0", 10) || 0;
      const height = parseInt(node.getAttribute("height") || node.naturalHeight || "0", 10) || 0;
      for (const attr of [
        "src",
        "href",
        "content",
        "data-src",
        "data-original",
        "data-lazy",
        "data-lazy-src",
        "data-full",
        "data-full-src",
        "data-image",
        "data-image-src",
        "data-image-large-src",
        "data-large",
        "data-large-src",
        "data-zoom-image",
        "data-zoom-src",
        "poster",
      ]) {
        add(node.getAttribute(attr), `${node.tagName.toLowerCase()}.${attr}`, width, height);
      }
      for (const attr of ["srcset", "data-srcset", "data-lazy-srcset"]) {
        parseSrcset(node.getAttribute(attr), `${node.tagName.toLowerCase()}.${attr}`, width, height);
      }
    });

    document.querySelectorAll("[style]").forEach((node) => {
      const style = node.getAttribute("style") || "";
      for (const match of style.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/gi)) {
        add(match[1], "style.background");
      }
    });

    const absoluteImageUrl = new RegExp(
      `(?:https?:)?//[^"'<>'\\s\\\\)]+?\\.(?:${imageExtensionPattern})(?:\\?[^"'<>'\\s\\\\)]*)?`,
      "gi"
    );
    const relativeImageUrl = new RegExp(
      `["'](/[^"'<>'\\s\\\\]+?\\.(?:${imageExtensionPattern})(?:\\?[^"'<>'\\s\\\\]*)?)["']`,
      "gi"
    );
    document.querySelectorAll("script, style").forEach((node) => {
      const text = (node.textContent || "").replace(/\\\//g, "/");
      const source = `${node.tagName.toLowerCase()}.text`;
      for (const match of text.matchAll(absoluteImageUrl)) {
        add(match[0], source);
      }
      for (const match of text.matchAll(relativeImageUrl)) {
        add(match[1], source);
      }
    });

    return {
      pageUrl: location.href,
      title: document.title,
      images: result.slice(0, 240),
    };
  }

  async function currentTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs.length || !tabs[0].id) {
      throw new Error("Nie znaleziono aktywnej karty.");
    }
    return tabs[0];
  }

  async function scanPage() {
    setStatus("Skanowanie");
    const tab = await currentTab();
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectImagesFromPage,
    });
    const payload = results && results[0] ? results[0].result : { images: [] };
    state.images = payload.images || [];
    state.selected = new Set(state.images.map((_image, index) => index));
    await extensionStorageSet({ lastPageUrl: payload.pageUrl || tab.url || "" });
    renderImages();
    setStatus("Gotowe");
  }

  function renderImages() {
    const scrollTop = imagesOutput.scrollTop || 0;
    imagesOutput.textContent = "";
    const visible = visibleImageEntries();
    const selectedVisible = visible.filter((entry) => state.selected.has(entry.index)).length;
    summaryOutput.textContent = state.images.length
      ? `${selectedVisible}/${visible.length} widocznych zaznaczonych, ${state.images.length} wykrytych.`
      : "Brak zeskanowanych zdjec.";
    visible.forEach(({ image, index }) => {
      const row = document.createElement("label");
      const checkbox = document.createElement("input");
      const preview = document.createElement("img");
      const meta = document.createElement("div");
      const title = document.createElement("strong");
      const dimensions = document.createElement("small");
      const url = document.createElement("span");
      const task = uploadTaskForImage(image);
      row.className = `image-row ${task ? task.status || "running" : ""}`;
      checkbox.type = "checkbox";
      checkbox.checked = state.selected.has(index);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          state.selected.add(index);
        } else {
          state.selected.delete(index);
        }
        renderImages();
      });
      const previewUrl = safeImagePreviewUrl(image.url);
      if (previewUrl) preview.src = previewUrl;
      preview.alt = "";
      title.textContent = image.filename || imageFilename(image.url);
      dimensions.textContent =
        image.width && image.height ? `${image.width} x ${image.height}` : "rozmiar nieznany";
      url.textContent = image.url;
      meta.append(title, dimensions, url);
      if (task) {
        meta.append(uploadProgressNode(task));
      }
      row.append(checkbox, preview, meta);
      imagesOutput.appendChild(row);
    });
    imagesOutput.scrollTop = scrollTop;
  }

  function uploadProgressNode(task) {
    const wrapper = document.createElement("div");
    const header = document.createElement("div");
    const phase = document.createElement("span");
    const time = document.createElement("span");
    const track = document.createElement("div");
    const fill = document.createElement("div");
    const details = document.createElement("small");
    const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
    const size = formatBytes(task.sizeBytes || task.bytesReceived);
    const timingParts = [];
    if (task.downloadMs) timingParts.push(`pobieranie ${formatMs(task.downloadMs)}`);
    if (task.uploadMs) timingParts.push(`backend/cache ${formatMs(task.uploadMs)}`);
    if (size) timingParts.push(`pobrano ${size}`);
    wrapper.className = "image-upload-progress";
    header.className = "image-upload-header";
    track.className = "progress-track";
    fill.className = "progress-fill";
    fill.style.width = `${progress}%`;
    phase.textContent = task.error || task.phase || "W kolejce";
    time.textContent = formatMs(task.totalMs || task.elapsedMs);
    details.textContent = timingParts.join(" · ");
    header.append(phase, time);
    track.append(fill);
    wrapper.append(header, track);
    if (details.textContent) {
      wrapper.append(details);
    }
    return wrapper;
  }

  async function saveSettings() {
    const settings = {
      panelUrl: normalizePanelUrl(panelUrlInput.value),
      apiToken: apiTokenInput.value.trim(),
    };
    await extensionStorageSet(settings);
    setStatus("Zapisano");
  }

  async function loadSettings() {
    const stored = await extensionStorageGet(["panelUrl", "apiToken", "lastPageUrl", "filters"]);
    const panelUrl = normalizePanelUrl(stored.panelUrl || defaults.panelUrl || "http://127.0.0.1:8010");
    const apiToken = stored.apiToken || defaults.apiToken || "";
    panelUrlInput.value = panelUrl;
    apiTokenInput.value = apiToken;
    if (stored.filters && typeof stored.filters === "object") {
      state.filters = {
        ...state.filters,
        ...stored.filters,
        minWidth: positiveInt(stored.filters.minWidth),
        minHeight: positiveInt(stored.filters.minHeight),
        hideThumbnails: Boolean(stored.filters.hideThumbnails),
        urlFilter: String(stored.filters.urlFilter || ""),
      };
    }
    applyFiltersToInputs();
    if (!stored.panelUrl || (!stored.apiToken && apiToken)) {
      await extensionStorageSet({ panelUrl, apiToken });
    }
  }

  async function testConnection() {
    await saveSettings();
    const panelUrl = normalizePanelUrl(panelUrlInput.value);
    const apiToken = apiTokenInput.value.trim();
    setStatus("Test");
    const response = await fetch(`${panelUrl}/api/browser-extension/ping`, {
      headers: { Authorization: `Bearer ${apiToken}` },
    });
    if (!response.ok) {
      throw new Error(`Panel odrzucil polaczenie: ${response.status}`);
    }
    setStatus("Polaczono");
  }

  async function uploadSelected() {
    await saveSettings();
    const stored = await extensionStorageGet(["lastPageUrl"]);
    const selected = visibleImageEntries()
      .filter((entry) => state.selected.has(entry.index))
      .map((entry) => entry.image);
    if (!selected.length) {
      setStatus("Brak wyboru");
      return;
    }
    const response = await runtimeMessage({
      type: "startUpload",
      images: selected,
      pageUrl: stored.lastPageUrl || "",
    });
    if (!response?.ok) {
      throw new Error(response?.error || "Nie udalo sie uruchomic wysylania w tle.");
    }
    setStatus(`Kolejka +${response.total}`);
    summaryOutput.textContent = "Wysylanie dziala w tle. W panelu kliknij Odbierz z rozszerzenia.";
    refreshUploadStatus().catch(() => {});
  }

  async function retryFailedUploads() {
    const response = await runtimeMessage({ type: "retryFailed" });
    if (!response?.ok) {
      throw new Error(response?.error || "Nie udalo sie ponowic bledow.");
    }
    if (!response.total) {
      setStatus("Brak bledow");
      return;
    }
    setStatus(`Ponawianie ${response.total}`);
    summaryOutput.textContent = "Nieudane pozycje wracaja do kolejki.";
    refreshUploadStatus().catch(() => {});
  }

  async function refreshUploadStatus() {
    const response = await runtimeMessage({ type: "getUploadStatus" });
    if (!response?.ok) return;
    const status = response.status || {};
    const total = Number(status.total || 0);
    const uploaded = Number(status.uploaded || 0);
    const failed = Number(status.failed || 0);
    const failedRetryable = Number(status.failedRetryable || 0);
    const remaining = Number(status.remaining || 0);
    retryFailedButton.disabled = failedRetryable <= 0;
    state.uploadStatus = status;
    renderImages();
    if (status.running || remaining > 0) {
      setStatus(`${uploaded}/${total} wyslano`);
      summaryOutput.textContent = failed
        ? `Wysylanie w tle: ${uploaded}/${total}, bledy: ${failed}, do ponowienia: ${failedRetryable}, rownolegle: ${status.concurrency || 1}, czas: ${formatMs(status.elapsedMs)}.`
        : `Wysylanie w tle: ${uploaded}/${total}, rownolegle: ${status.concurrency || 1}, czas: ${formatMs(status.elapsedMs)}.`;
      return;
    }
    if (total > 0) {
      setStatus(failed ? `Bledy ${failed}` : "Wyslano");
      summaryOutput.textContent = failed
        ? `Zakonczono z bledami: ${failed}. Do ponowienia: ${failedRetryable}. Czas: ${formatMs(status.elapsedMs)}. ${status.lastError || ""}`
        : `Wyslano do panelu w ${formatMs(status.elapsedMs)}. Kliknij Odbierz z rozszerzenia.`;
    }
  }

  saveSettingsButton.addEventListener("click", () => {
    saveSettings().catch((error) => setStatus(error.message));
  });
  settingsToggle.addEventListener("click", () => {
    settingsPanel.hidden = !settingsPanel.hidden;
  });
  filtersToggle.addEventListener("click", () => {
    filtersPanel.hidden = !filtersPanel.hidden;
  });
  for (const input of [minWidthInput, minHeightInput, hideThumbnailsInput, urlFilterInput]) {
    input.addEventListener("input", () => {
      saveFilters().catch((error) => setStatus(error.message));
      renderImages();
    });
    input.addEventListener("change", () => {
      saveFilters().catch((error) => setStatus(error.message));
      renderImages();
    });
  }
  testConnectionButton.addEventListener("click", () => {
    testConnection().catch((error) => setStatus(error.message));
  });
  scanPageButton.addEventListener("click", () => {
    scanPage().catch((error) => setStatus(error.message));
  });
  selectAllButton.addEventListener("click", () => {
    for (const entry of visibleImageEntries()) {
      state.selected.add(entry.index);
    }
    renderImages();
  });
  clearSelectionButton.addEventListener("click", () => {
    state.selected.clear();
    renderImages();
  });
  retryFailedButton.addEventListener("click", () => {
    retryFailedUploads().catch((error) => setStatus(error.message));
  });
  uploadSelectedButton.addEventListener("click", () => {
    uploadSelected().catch((error) => setStatus(error.message));
  });

  window.setInterval(() => {
    refreshUploadStatus().catch(() => {});
  }, 500);

  loadSettings()
    .then(() => Promise.all([scanPage(), refreshUploadStatus()]))
    .catch((error) => setStatus(error.message));
})();
