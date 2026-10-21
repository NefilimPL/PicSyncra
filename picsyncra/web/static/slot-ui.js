// Classic script: definitions only; shared application state is initialized by app.js.

function slotFileItem(value) {
  if (!value) return null;
  if (value.file || value.token || value.uploading || value.error) return value;
  return {
    file: value,
    name: value.name || "",
    size: Number(value.size || 0),
    type: value.type || "",
    token: "",
    url: "",
    thumb_url: "",
    file_version: "",
    preprocessed: false,
    cache_timing: null,
    ocr_state: "",
    client_preprocess_ms: 0,
    progress: 0,
    uploading: false,
    error: "",
  };
}

function slotFileObject(value) {
  return slotFileItem(value)?.file || null;
}

function slotFileName(value) {
  const item = slotFileItem(value);
  return item?.name || item?.file?.name || "plik";
}

function slotFileSize(value) {
  const item = slotFileItem(value);
  return Number(item?.size || item?.file?.size || 0);
}

function slotFileType(value) {
  const item = slotFileItem(value);
  return item?.type || item?.file?.type || "";
}

function slotFileToken(value) {
  return String(slotFileItem(value)?.token || "").trim();
}

function slotAssignmentToken(prefix) {
  return (
    slotFileToken(state.files.get(prefix)) ||
    selectedPhotoToken(state.loadedPhotos.get(prefix), prefix)
  );
}

function slotUploadProgress(value) {
  const progress = Number(slotFileItem(value)?.progress || 0);
  return Math.max(0, Math.min(100, Math.round(progress)));
}

function isSlotUploadActive(value) {
  return Boolean(slotFileItem(value)?.uploading);
}

function slotUploadError(value) {
  return String(slotFileItem(value)?.error || "").trim();
}

function freeSlotPrefixes(limit = Infinity) {
  const prefixes = [];
  for (const slot of state.slots || []) {
    if (isSlotFreeForNewFile(slot.prefix)) {
      prefixes.push(slot.prefix);
      if (prefixes.length >= limit) break;
    }
  }
  return prefixes;
}

async function cacheWebImageForSlot(image, prefix) {
  return requestJson("/api/web-images/cache", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: image.url,
      page_url: state.webImagePageUrl || webImageUrl?.value?.trim() || "",
      prefix,
    }),
    timeoutMs: 60000,
  });
}

async function addSelectedWebImagesToSlots() {
  const selected = [...state.webImageSelected]
    .sort((a, b) => a - b)
    .map((index) => state.webImages[index])
    .filter(Boolean);
  if (!selected.length) {
    formStatus.textContent = "Zaznacz zdjecia do dodania.";
    return;
  }
  const prefixes = freeSlotPrefixes(selected.length);
  if (!prefixes.length) {
    warnNoFreeSlots(selected.map((image) => image.filename || image.url));
    return;
  }
  webImagesAddButton.disabled = true;
  webImagesAddButton.textContent = "Dodawanie...";
  const assigned = [];
  try {
    const limit = Math.min(selected.length, prefixes.length);
    for (let index = 0; index < limit; index += 1) {
      const image = selected[index];
      const prefix = prefixes[index];
      formStatus.textContent = `Pobieranie zdjecia ${index + 1}/${limit} do slotu ${prefix}...`;
      const payload = await cachedWebImagePayload(image, prefix);
      if (!payload.token) {
        throw new Error("Backend nie zwrocil tokenu cache dla zdjecia.");
      }
      state.files.set(prefix, webImageCacheItem(prefix, image, payload));
      await ensureSlotOcrCollection(prefix, state.files.get(prefix));
      state.webImageSelected.delete(state.webImages.indexOf(image));
      assigned.push(prefix);
      renderSlot(prefix);
    }
    if (assigned.length) {
      formStatus.textContent = `Dodano ${assigned.length} zdjec do slotow: ${assigned.join(", ")}.`;
      updateSubmitButtonState();
    }
    if (selected.length > prefixes.length) {
      warnNoFreeSlots(selected.slice(prefixes.length).map((image) => image.filename || image.url));
    }
    renderWebImagesPicker();
  } catch (error) {
    formStatus.textContent = error.message;
  } finally {
    webImagesAddButton.disabled = false;
    webImagesAddButton.textContent = "Dodaj do wolnych slotow";
  }
}

function defaultSlotSource(photo) {
  if (photo?.local && photo?.token) return "local";
  if (photo?.ftp && (photo?.ftp_token || photo?.ftp_filename)) return "ftp";
  return "";
}

function selectedSlotSource(prefix, photo) {
  const selected = state.slotSources.get(prefix);
  if (selected === "similar" && similarCandidateForSlot(prefix)) return "similar";
  if (selected === "local" && photo?.token) return "local";
  if (selected === "ftp" && (photo?.ftp_token || photo?.ftp_filename)) return "ftp";
  if (selected === "sql" && String(photo?.sql_value || "").trim()) return "sql";
  if (!photo && similarCandidateForSlot(prefix)) return "similar";
  return defaultSlotSource(photo);
}

function similarCandidateForSlot(prefix) {
  if (state.dismissedSimilarSlots.has(prefix)) return null;
  if (
    state.slotSources.get(prefix) !== "similar" &&
    (state.files.has(prefix) || (state.loadedPhotos.has(prefix) && !state.deletedSlots.has(prefix)))
  ) {
    return null;
  }
  return state.similarCandidates.get(prefix) || null;
}

function isFreeSimilarSlot(prefix) {
  return (
    !state.files.has(prefix) &&
    !state.loadedPhotos.has(prefix) &&
    !similarCandidateForSlot(prefix)
  );
}

async function ensureSlotOcrCollection(prefix, item = null) {
  if (state.settings?.ocr_available === false) return "disabled";
  const token = slotFileToken(item) || slotAssignmentToken(prefix);
  if (!prefix || !token) return "";
  const payload = await requestJson("/api/ocr/slot-assignment", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prefix, token }),
  });
  if (slotAssignmentToken(prefix) !== token) return "";
  const assigned = state.files.get(prefix) || state.loadedPhotos.get(prefix);
  if (!assigned) return "";
  assigned.ocr_state = String(payload?.state || "");
  updateSlotPreview(prefix);
  try {
    await refreshOpenPimcoreOcrPanels();
    if (assigned.ocr_state === "completed") {
      await revalidateOpenPimcoreOcrFields();
    }
  } catch (_error) {
    // A later OCR refresh retries the optional Pimcore view and comparison update.
  }
  return assigned.ocr_state;
}

function similarDecisionSlotLabel(prefix) {
  const slot = (state.slots || []).find((item) => String(item.prefix) === String(prefix));
  return slot ? `${slot.prefix} - ${slot.label}` : `Slot ${prefix}`;
}

function transferableSlotSource(prefix, photo) {
  const selected = state.slotSources.get(prefix);
  if (selected === "local" && photo?.token) return "local";
  if (selected === "ftp" && (photo?.ftp_token || photo?.ftp_filename)) return "ftp";
  if (photo?.token) return "local";
  if (photo?.ftp_token || photo?.ftp_filename) return "ftp";
  return "";
}

function slotOpenState(prefix, photo, file) {
  const source = selectedSlotSource(prefix, photo);
  if (source === "sql") {
    return isHttpUrl(photo?.sql_value)
      ? { enabled: true, title: "Otwórz aktywne źródło SQL" }
      : { enabled: false, title: "Wartość SQL nie jest linkiem HTTP/HTTPS" };
  }
  if (source === "ftp") {
    if (photo?.ftp_url || photo?.ftp_token) {
      return { enabled: true, title: "Otwórz aktywne źródło FTP" };
    }
    return photo?.ftp_filename
      ? { enabled: false, title: "Pobieranie pliku FTP..." }
      : { enabled: false, title: "Brak pliku FTP" };
  }
  if (source === "local") {
    return photo?.url || photo?.token
      ? { enabled: true, title: "Otwórz aktywne źródło LOCAL" }
      : { enabled: false, title: "Brak lokalnego pliku" };
  }
  if (source === "similar") {
    return filePreviewUrl(prefix, file) || similarCandidateForSlot(prefix)?.url
      ? { enabled: true, title: "Otwórz aktywne źródło POD" }
      : { enabled: false, title: "Brak pliku z podobnego produktu" };
  }
  if (file && filePreviewUrl(prefix, file)) {
    return { enabled: true, title: "Otwórz wybrany plik" };
  }
  return { enabled: false, title: "Brak pliku do otwarcia" };
}

function selectedSlotSourceCanOpen(prefix, photo, file) {
  return slotOpenState(prefix, photo, file).enabled;
}

function updateSlotOpenButton(button, prefix, photo, file) {
  if (!button) return;
  const openState = slotOpenState(prefix, photo, file);
  button.disabled = !openState.enabled;
  button.setAttribute("aria-disabled", openState.enabled ? "false" : "true");
  button.title = openState.title;
}

function selectedSlotSourceCanFit(prefix, photo, file) {
  const source = selectedSlotSource(prefix, photo);
  if (source === "sql") return false;
  if (source === "similar") return Boolean(similarCandidateForSlot(prefix) && !similarCandidateForSlot(prefix).is_pdf);
  if (file) return isFileImageLike(file);
  return Boolean(photo?.is_image && (selectedPhotoToken(photo, prefix) || photo?.ftp_filename));
}

async function openSlotFile(prefix) {
  const selectedFile = state.files.get(prefix);
  let photo = state.loadedPhotos.get(prefix);
  const source = selectedSlotSource(prefix, photo);
  const openingRequestId = state.photoLoadRequestId;
  const openingRevision = slotRevision(prefix);
  if (source === "sql") {
    const sqlUrl = loadedFileUrl(photo, prefix);
    if (sqlUrl) window.open(sqlUrl, "_blank", "noopener");
    return;
  }
  if (selectedFile) {
    window.open(filePreviewUrl(prefix, selectedFile), "_blank", "noopener");
    return;
  }
  const ocrPopup = openOcrImageWindow();
  if (source === "ftp" && photo?.ftp_filename) {
    await loadFtpPreview(photo, prefix, openingRequestId, { forceRefresh: true });
    if (
      openingRequestId !== state.photoLoadRequestId ||
      openingRevision !== slotRevision(prefix)
    ) {
      return;
    }
    photo = state.loadedPhotos.get(prefix);
    if (selectedSlotSource(prefix, photo) !== "ftp") return;
  }
  const url = loadedFileUrl(photo, prefix);
  if (url) await openOcrAnnotatedImage(url, selectedPhotoToken(photo, prefix), ocrPopup);
}

function markSlotDeletion(prefix, photo) {
  if (!photo) return;
  state.deletedSlots.set(prefix, {
    prefix,
    token: photo.token || "",
    ftp_filename: photo.ftp_filename || "",
    sql: Boolean(photo.sql),
    filename: photo.filename || "",
    source: selectedSlotSource(prefix, photo),
  });
}

function slotStatusText(photo, prefix = "") {
  if (!photo) {
    return "Przeciagnij albo wybierz plik";
  }
  if (selectedSlotSource(prefix, photo) === "ftp" && photo.ftp_filename) {
    return `FTP: ${photo.ftp_filename}`;
  }
  if (photo.filename) {
    return photo.filename;
  }
  if (photo.ftp_filename) {
    return `FTP: ${photo.ftp_filename}`;
  }
  const parts = [];
  if (photo.local) parts.push("LOCAL");
  if (photo.ftp) parts.push("FTP");
  if (photo.sql) parts.push("SQL");
  return parts.length ? parts.join(" / ") : "Brak lokalnego pliku";
}

function renderSlotBadges(container, photo, file, prefix) {
  const badges = document.createElement("div");
  badges.className = "slot-badges";
  const statuses = [
    ["local", "LOCAL", "Plik jest w folderze backendu"],
    ["ftp", "FTP", "Wpis dla slotu jest na FTP"],
    ["sql", "SQL", "Wpis dla slotu jest w SQL"],
    ["similar", "POD", "Plik z podobnego produktu"],
  ];
  if (file) {
    const badge = document.createElement("span");
    badge.className = "slot-badge on";
    badge.title = "Nowy plik wybrany w przegladarce";
    badge.textContent = "NOWY";
    badges.appendChild(badge);
  }
  for (const [key, label, title] of statuses) {
    const sqlValue = String(photo?.sql_value || "").trim();
    const similarCandidate = similarCandidateForSlot(prefix);
    const canPreview =
      (key === "local" && photo?.token) ||
      (key === "ftp" && photo?.ftp_filename) ||
      (key === "sql" && Boolean(sqlValue)) ||
      (key === "similar" && Boolean(similarCandidate));
    if (key === "similar" && !similarCandidate) continue;
    const badge = document.createElement(canPreview ? "button" : "span");
    const selected = selectedSlotSource(prefix, photo) === key;
    const loading =
      isPhotoSourceLoading(key) || (key === "ftp" && state.ftpPreviewLoading.has(prefix));
    badge.dataset.source = key;
    badge.className = `slot-badge slot-badge-${key} ${photo && photo[key] || key === "similar" ? "on" : ""} ${
      selected ? "selected" : ""
    } ${loading ? "loading" : ""}`;
    badge.title = loading
      ? sourceLoadingTitle(key)
      : selected
      ? `${title} (aktywny podglad)`
      : title;
    badge.textContent = label;
    if (canPreview) {
      badge.type = "button";
      badge.setAttribute("aria-pressed", selected ? "true" : "false");
      if (loading) {
        badge.setAttribute("aria-busy", "true");
      }
      badge.addEventListener("click", (event) => {
        event.stopPropagation();
        state.slotSources.set(prefix, key);
        state.userSelectedSlotSources.add(prefix);
        if (key === "ftp") {
          if (state.ftpPreviewLoading.has(prefix)) {
            state.ftpPreviewBackgroundLoading.delete(prefix);
            loadFtpPreview(photo, prefix, state.photoLoadRequestId, { forceRefresh: true }).catch((error) => {
              formStatus.textContent = error.message;
            });
          } else {
            loadFtpPreview(photo, prefix, state.photoLoadRequestId, { forceRefresh: true }).catch((error) => {
              formStatus.textContent = error.message;
            });
          }
        } else {
          updateSlotPreview(prefix);
        }
      });
    }
    badges.appendChild(badge);
  }
  container.appendChild(badges);
}

function isProvisionalSlotPlacement(prefix) {
  return Boolean(state.photosLoading && !photoHasUsableContent(state.loadedPhotos.get(prefix)));
}

function createSlotFileUpload(prefix, file, options = {}) {
  return {
    id: ++state.slotUploadRequestId,
    prefix,
    file,
    name: file?.name || "",
    size: Number(file?.size || 0),
    type: file?.type || "",
    token: "",
    url: "",
    thumb_url: "",
    file_version: "",
    preprocessed: false,
    cache_timing: null,
    client_preprocess_ms: 0,
    progress: 0,
    uploading: false,
    error: "",
    xhr: null,
    provisional: Boolean(options.provisional),
    placementBlocked: false,
  };
}

function refreshFileItemSlots(item) {
  for (const prefix of fileItemPrefixes(item)) {
    updateSlotPreview(prefix);
  }
  updateSubmitButtonState();
}

function uploadSlotFile(prefix, item) {
  const file = slotFileObject(item);
  if (!file) return;
  const requestId = item.id;
  item.uploading = true;
  item.progress = 0;
  item.error = "";
  item.token = "";
  item.url = "";
  item.thumb_url = "";
  item.file_version = "";
  item.preprocessed = false;
    item.client_preprocess_ms = 0;
    item.ocr_state = "";
  item.original_size = Number(file.size || item.size || 0);
  refreshFileItemSlots(item);
  const sendUpload = (uploadFile, clientPreprocessed = false) => {
    if (item.id !== requestId) return;
    const data = new FormData();
    data.set("prefix", prefix);
    data.set("file", uploadFile, uploadFile.name || slotFileName(item));
  const xhr = new XMLHttpRequest();
  item.xhr = xhr;
  xhr.upload.addEventListener("progress", (event) => {
    if (!event.lengthComputable) return;
    const nextProgress = Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100)));
    if (nextProgress === item.progress) return;
    item.progress = nextProgress;
    formStatus.textContent = `Wysylanie pliku dla slotu ${prefix}: ${nextProgress}%`;
    refreshFileItemSlots(item);
  });
  xhr.addEventListener("load", () => {
    const payload = xhr.response || {};
    if (xhr.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (xhr.status < 200 || xhr.status >= 300) {
      item.uploading = false;
      item.error = uploadCacheErrorMessage(payload);
      item.xhr = null;
      formStatus.textContent = `Blad uploadu slotu ${prefix}: ${item.error}`;
      refreshFileItemSlots(item);
      return;
    }
    if (!payload.token) {
      item.uploading = false;
      item.error = "Backend nie zwrocil tokenu cache.";
      item.xhr = null;
      formStatus.textContent = `Blad uploadu slotu ${prefix}: ${item.error}`;
      refreshFileItemSlots(item);
      return;
    }
    item.token = payload.token || "";
    item.url = payload.url || "";
    item.thumb_url = payload.thumb_url || "";
    item.file_version = payload.file_version || "";
    item.preprocessed = Boolean(payload.preprocessed || clientPreprocessed);
    item.client_preprocess_ms = item.client_preprocess_ms || 0;
    item.cache_timing = payload.timing || null;
    item.ocr_state = payload.ocr_state || "";
    item.name = payload.name || item.name;
    item.size = Number(payload.size_bytes || item.size || 0);
    item.progress = 100;
    item.uploading = false;
    item.error = "";
    item.xhr = null;
    const timingText =
      showTimingDetails() && payload.timing?.total_ms
        ? ` (${formatDuration(payload.timing.total_ms)})`
        : "";
    formStatus.textContent = `Plik dla slotu ${prefix} jest w cache${timingText}.`;
    refreshFileItemSlots(item);
  });
  xhr.addEventListener("error", () => {
    item.uploading = false;
    item.error = "Nie udalo sie polaczyc z backendem podczas uploadu.";
    item.xhr = null;
    formStatus.textContent = `Blad uploadu slotu ${prefix}: ${item.error}`;
    refreshFileItemSlots(item);
  });
  xhr.addEventListener("abort", () => {
    item.uploading = false;
    item.error = "Upload przerwany.";
    item.xhr = null;
    refreshFileItemSlots(item);
  });
  xhr.open("POST", "/api/upload-cache");
  xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
  if (state.csrfToken) {
    xhr.setRequestHeader(CSRF_HEADER, state.csrfToken);
  }
  xhr.responseType = "json";
  xhr.send(data);
  };
  preprocessFileOnClient(file)
    .then((prepared) => {
      if (item.id !== requestId) return;
      item.client_preprocess_ms = Math.round(prepared.elapsed_ms || 0);
      if (prepared.preprocessed) {
        item.file = prepared.file;
        item.name = prepared.file.name || item.name;
        item.size = Number(prepared.file.size || item.size || 0);
      }
      sendUpload(prepared.file, prepared.preprocessed);
    })
    .catch((error) => {
      item.uploading = false;
      item.error = error.message || "Nie udalo sie przygotowac obrazu po stronie klienta.";
      item.xhr = null;
      formStatus.textContent = `Blad uploadu slotu ${prefix}: ${item.error}`;
      refreshFileItemSlots(item);
    });
  updateSubmitButtonState();
}

function activeSlotUploads() {
  return [...state.files.entries()].filter(([, item]) => isSlotUploadActive(item));
}

function failedSlotUploads() {
  return [...state.files.entries()].filter(([, item]) => Boolean(slotUploadError(item)));
}

function ensureSlotUploadsReady() {
  const pending = activeSlotUploads();
  if (pending.length) {
    throw new Error("Poczekaj na zakonczenie wysylania plikow do cache.");
  }
  const failed = failedSlotUploads();
  if (failed.length) {
    const [prefix, item] = failed[0];
    throw new Error(`Upload slotu ${prefix} nie powiodl sie: ${slotUploadError(item)}`);
  }
}

function renderSlotUploadOverlay(preview, item) {
  preview.querySelector(".slot-upload-overlay")?.remove();
  const error = slotUploadError(item);
  if (!isSlotUploadActive(item) && !error) return;
  const overlay = document.createElement("div");
  const label = document.createElement("span");
  const line = document.createElement("div");
  const bar = document.createElement("i");
  const progress = slotUploadProgress(item);
  overlay.className = `slot-upload-overlay ${error ? "error" : ""}`;
  label.textContent = error ? `Upload nieudany: ${error}` : `Wysylanie ${progress}%`;
  line.className = "progress-line upload-progress-line";
  line.style.setProperty("--upload-progress", `${progress}%`);
  line.appendChild(bar);
  overlay.append(label, line);
  preview.appendChild(overlay);
}

function slotRevision(prefix) {
  return Number(state.slotRevisions.get(prefix) || 0);
}

function bumpSlotRevision(prefix) {
  state.slotRevisions.set(prefix, slotRevision(prefix) + 1);
}

function isSlotFit(prefix) {
  if (state.slotFits.has(prefix)) {
    return Boolean(state.slotFits.get(prefix));
  }
  return Boolean(state.defaultSlotFit);
}

function clearSlotAssignment(prefix, options = {}) {
  bumpSlotRevision(prefix);
  const markDelete = options.markDelete !== false;
  const removedSlotToken = markDelete ? slotAssignmentToken(prefix) : "";
  if (markDelete) {
    markSlotDeletion(prefix, state.loadedPhotos.get(prefix));
    recordOcrActivity({ removedSlotToken });
  }
  revokeFilePreviewUrl(prefix);
  state.files.delete(prefix);
  state.loadedPhotos.delete(prefix);
  state.slotFits.delete(prefix);
  state.slotSources.delete(prefix);
  state.userSelectedSlotSources.delete(prefix);
  dismissSimilarCandidate(prefix);
}

function setSlotFile(prefix, file, options = {}) {
  const validationError = uploadFileValidationError(file);
  const removedSlotToken = slotAssignmentToken(prefix);
  bumpSlotRevision(prefix);
  markSlotDeletion(prefix, state.loadedPhotos.get(prefix));
  revokeFilePreviewUrl(prefix);
  const item = createSlotFileUpload(prefix, file, {
    provisional: options.provisional ?? isProvisionalSlotPlacement(prefix),
  });
  state.files.set(prefix, item);
  state.loadedPhotos.delete(prefix);
  state.slotSources.delete(prefix);
  state.userSelectedSlotSources.delete(prefix);
  dismissSimilarCandidate(prefix);
  if (validationError) {
    item.error = validationError;
    formStatus.textContent = `Blad uploadu slotu ${prefix}: ${item.error}`;
    updateSubmitButtonState();
    return item;
  }
  recordOcrActivity({ removedSlotToken });
  uploadSlotFile(prefix, item);
  startSimilarFileLookup({ immediate: true });
  return item;
}

function getSlotAssignment(prefix) {
  if (state.files.has(prefix)) {
    return { type: "file", prefix, value: state.files.get(prefix), source: "", fit: isSlotFit(prefix) };
  }
  if (state.loadedPhotos.has(prefix)) {
    const photo = state.loadedPhotos.get(prefix);
    return {
      type: "loaded",
      prefix,
      value: photo,
      source: transferableSlotSource(prefix, photo),
      fit: isSlotFit(prefix),
    };
  }
  return null;
}

function setSlotAssignment(prefix, assignment, options = {}) {
  const sourceFit = assignment && "fit" in assignment ? Boolean(assignment.fit) : isSlotFit(assignment?.prefix || prefix);
  const sourceType = assignment?.source || "";
  clearSlotAssignment(prefix, { markDelete: options.markDelete !== false });
  if (!assignment) {
    return;
  }
  if (assignment.type === "file") {
    const item = slotFileItem(assignment.value);
    if (item) {
      item.prefix = prefix;
      item.provisional = false;
      item.placementBlocked = false;
    }
    state.files.set(prefix, item);
    state.slotFits.set(prefix, sourceFit);
    if (sourceType) state.slotSources.set(prefix, sourceType);
    state.userSelectedSlotSources.delete(prefix);
    if (item?.file && !item.token && !item.uploading && !item.error) {
      uploadSlotFile(prefix, item);
    }
    if (slotFileToken(item)) {
      ensureSlotOcrCollection(prefix, item).catch((error) => {
        formStatus.textContent = `Nie zlecono OCR dla slotu ${prefix}: ${error.message}`;
      });
    }
    return;
  }
  if (assignment.type === "loaded") {
    state.loadedPhotos.set(prefix, { ...assignment.value, prefix, dirty: true });
    state.slotFits.set(prefix, sourceFit);
    if (sourceType) state.slotSources.set(prefix, sourceType);
    state.userSelectedSlotSources.delete(prefix);
    ensureSlotOcrCollection(prefix, state.loadedPhotos.get(prefix)).catch((error) => {
      formStatus.textContent = `Nie zlecono OCR dla slotu ${prefix}: ${error.message}`;
    });
  }
}

function moveSlotContent(sourcePrefix, targetPrefix) {
  if (!sourcePrefix || !targetPrefix || sourcePrefix === targetPrefix) {
    return;
  }
  const source = getSlotAssignment(sourcePrefix);
  if (!source) {
    return;
  }
  recordOcrActivity();
  const target = getSlotAssignment(targetPrefix);
  if (target) {
    markSlotDeletion(targetPrefix, state.loadedPhotos.get(targetPrefix));
    markSlotDeletion(sourcePrefix, state.loadedPhotos.get(sourcePrefix));
    clearSlotAssignment(targetPrefix, { markDelete: false });
    clearSlotAssignment(sourcePrefix, { markDelete: false });
    setSlotAssignment(targetPrefix, source, { markDelete: false });
    setSlotAssignment(sourcePrefix, target, { markDelete: false });
    formStatus.textContent = `Zamieniono slot ${sourcePrefix} ze slotem ${targetPrefix}.`;
    renderSlot(targetPrefix);
    renderSlot(sourcePrefix);
    return;
  }
  markSlotDeletion(targetPrefix, state.loadedPhotos.get(targetPrefix));
  markSlotDeletion(sourcePrefix, state.loadedPhotos.get(sourcePrefix));
  setSlotAssignment(targetPrefix, source, { markDelete: false });
  clearSlotAssignment(sourcePrefix, { markDelete: false });
  formStatus.textContent = `Przeniesiono slot ${sourcePrefix} -> ${targetPrefix}.`;
  renderSlot(targetPrefix);
  renderSlot(sourcePrefix);
}

function slotIndex(prefix) {
  return (state.slots || []).findIndex((slot) => String(slot.prefix) === String(prefix));
}

function slotPrefixAt(index) {
  return state.slots?.[index]?.prefix || "";
}

function isSlotFreeForNewFile(prefix) {
  return Boolean(prefix && !state.files.has(prefix) && !photoHasUsableContent(state.loadedPhotos.get(prefix)));
}

function nextFreeSlotPrefix(startPrefix, options = {}) {
  const start = slotIndex(startPrefix);
  if (start < 0) return "";
  const from = start + (options.after ? 1 : 0);
  for (let index = from; index < (state.slots || []).length; index += 1) {
    const prefix = slotPrefixAt(index);
    if (isSlotFreeForNewFile(prefix)) {
      return prefix;
    }
  }
  return "";
}

function warnNoFreeSlots(files, context = "") {
  const names = [...(files || [])]
    .map((file) => (typeof file === "string" ? file : file?.name || slotFileName(file)))
    .filter(Boolean);
  if (!names.length) return;
  const message =
    names.length === 1
      ? `Brak wolnego slotu dla pliku: ${names[0]}.`
      : `Brak wolnych slotow dla plikow: ${names.join(", ")}.`;
  formStatus.textContent = context ? `${message} ${context}` : message;
  window.alert(formStatus.textContent);
}

function assignFilesFromSlot(startPrefix, files, options = {}) {
  const incoming = fileListFromInput(files);
  if (!incoming.length) return;
  const assigned = [];
  const unassigned = [];
  const rejected = [];
  let searchPrefix = startPrefix;
  if (options.replaceStart && incoming.length === 1) {
    const item = setSlotFile(startPrefix, incoming[0], { provisional: isProvisionalSlotPlacement(startPrefix) });
    renderSlot(startPrefix);
    formStatus.textContent = slotUploadError(item)
      ? `Blad uploadu slotu ${startPrefix}: ${slotUploadError(item)}`
      : `Dodano plik do slotu ${startPrefix}.`;
    return;
  }
  for (const file of incoming) {
    const targetPrefix = nextFreeSlotPrefix(searchPrefix, { after: false });
    if (!targetPrefix) {
      unassigned.push(file);
      continue;
    }
    const item = setSlotFile(targetPrefix, file, { provisional: isProvisionalSlotPlacement(targetPrefix) });
    assigned.push({ prefix: targetPrefix, file, item });
    if (slotUploadError(item)) {
      rejected.push({ prefix: targetPrefix, file, item });
    }
    searchPrefix = slotPrefixAt(slotIndex(targetPrefix) + 1) || targetPrefix;
  }
  for (const item of assigned) {
    renderSlot(item.prefix);
  }
  if (rejected.length) {
    const first = rejected[0];
    formStatus.textContent =
      rejected.length === 1
        ? `Blad uploadu slotu ${first.prefix}: ${slotUploadError(first.item)}`
        : `Odrzucono ${rejected.length} plikow przed uploadem. Pierwszy blad: slot ${first.prefix}: ${slotUploadError(first.item)}`;
  } else if (assigned.length) {
    const targetText = assigned.map((item) => item.prefix).join(", ");
    formStatus.textContent =
      assigned.length === 1
        ? `Dodano plik do slotu ${targetText}.`
        : `Dodano ${assigned.length} plikow do slotow: ${targetText}.`;
  }
  if (unassigned.length) {
    warnNoFreeSlots(unassigned);
  }
}

function applyDefaultSlotSource(prefix, photo) {
  const source = defaultSlotSource(photo);
  if (!state.userSelectedSlotSources.has(prefix)) {
    if (source) {
      state.slotSources.set(prefix, source);
    } else {
      state.slotSources.delete(prefix);
    }
  } else if (!selectedSlotSource(prefix, photo)) {
    if (source) {
      state.slotSources.set(prefix, source);
    } else {
      state.slotSources.delete(prefix);
    }
    state.userSelectedSlotSources.delete(prefix);
  }
}

function relocateProvisionalSlotFile(prefix) {
  const item = state.files.get(prefix);
  if (!item?.provisional) {
    return [];
  }
  const targetPrefix = nextFreeSlotPrefix(prefix, { after: true });
  if (!targetPrefix) {
    if (!item.placementBlocked) {
      warnNoFreeSlots([slotFileName(item)], `Slot ${prefix} ma juz dane.`);
    }
    item.placementBlocked = true;
    return [prefix];
  }
  const sourceFit = isSlotFit(prefix);
  state.files.delete(prefix);
  revokeFilePreviewUrl(prefix);
  item.prefix = targetPrefix;
  item.provisional = isProvisionalSlotPlacement(targetPrefix);
  item.placementBlocked = false;
  state.files.set(targetPrefix, item);
  state.slotFits.delete(prefix);
  state.slotFits.set(targetPrefix, sourceFit);
  formStatus.textContent = `Slot ${prefix} ma juz dane. Przeniesiono ${slotFileName(item)} do slotu ${targetPrefix}.`;
  return [prefix, targetPrefix];
}

function isOcrSlotStateInProgress(value) {
  return ["queued", "scanning", "refining"].includes(String(value || ""));
}

function updateOcrSlotIndicator(card, selectedFile, loadedPhoto) {
  const state = String(selectedFile?.ocr_state || loadedPhoto?.ocr_state || "");
  const collecting = isOcrSlotStateInProgress(state);
  card.classList.toggle("ocr-collecting", collecting);
  let indicator = card.querySelector(".slot-ocr-state");
  if (!collecting) {
    indicator?.remove();
    return;
  }
  if (!indicator) {
    indicator = document.createElement("span");
    indicator.className = "slot-ocr-state";
    card.querySelector(".slot-meta")?.appendChild(indicator);
  }
  const details = {
    queued: ["OCR oczekuje na skanowanie", "Obraz oczekuje w kolejce OCR na rozpoczecie szybkiego odczytu."],
    scanning: ["OCR skanuje obraz", "Szybkie wykrywanie wartosci liczbowych trwa w tle."],
    refining: ["OCR dopracowuje wycinki", "Dokladny model OCR analizuje wycinki wskazane przez szybki model."],
  };
  const [text, title] = details[state] || details.scanning;
  indicator.textContent = text;
  indicator.title = title;
}

function updateSlotPreview(prefix) {
  const card = slotGrid.querySelector(`[data-slot-prefix="${prefix}"]`);
  if (!card) {
    renderSlots();
    return;
  }
  const loadedPhoto = state.loadedPhotos.get(prefix);
  const selectedFile = state.files.get(prefix);
  const detail = card.querySelector(".slot-meta span");
  const preview = card.querySelector(".slot-preview");
  const previewImage = preview.querySelector("img");
  const empty = preview.querySelector(".slot-empty");
  const candidate = similarCandidateForSlot(prefix);
  const searching = state.similarFileLookupInFlight && isFreeSimilarSlot(prefix);
  const fitButton = card.querySelector(".slot-fit-button");
  const openButton = card.querySelector(".slot-open-button");
  card.dataset.activeSource = selectedSlotSource(prefix, loadedPhoto) || "";
  if (typeof updateOcrSlotIndicator === "function") {
    updateOcrSlotIndicator(card, selectedFile, loadedPhoto);
  }
  card.classList.toggle("slot-similar-pending", Boolean(candidate && !selectedFile));
  card.classList.toggle("similar-searching", searching);
  detail.textContent = selectedFile ? fileLabel(selectedFile) : slotStatusText(loadedPhoto, prefix);
  card.querySelectorAll(".slot-badge[data-source]").forEach((badge) => {
    const selected = selectedSlotSource(prefix, loadedPhoto) === badge.dataset.source;
    const loading =
      isPhotoSourceLoading(badge.dataset.source) ||
      (badge.dataset.source === "ftp" && state.ftpPreviewLoading.has(prefix));
    const titleBySource = {
      local: "Plik jest w folderze backendu",
      ftp: "Wpis dla slotu jest na FTP",
      sql: "Wpis dla slotu jest w SQL",
      similar: "Plik z podobnego produktu",
    };
    const sqlValue = String(loadedPhoto?.sql_value || "").trim();
    badge.classList.toggle("selected", selected);
    badge.classList.toggle("loading", loading);
    badge.setAttribute("aria-pressed", selected ? "true" : "false");
    if (loading) {
      badge.setAttribute("aria-busy", "true");
      badge.title = sourceLoadingTitle(badge.dataset.source);
    } else {
      badge.removeAttribute("aria-busy");
      const baseTitle = titleBySource[badge.dataset.source] || "";
      badge.title = selected ? `${baseTitle} (aktywny podglad)` : baseTitle;
    }
  });
  if (fitButton) {
    fitButton.classList.toggle("active", isSlotFit(prefix));
    fitButton.hidden = !selectedSlotSourceCanFit(prefix, loadedPhoto, selectedFile);
  }
  if (openButton) {
    updateSlotOpenButton(openButton, prefix, loadedPhoto, selectedFile);
  }
  preview.classList.remove("has-image", "thumb-loading", "loaded-photo", "has-similar-candidate", "has-sql-preview");
  preview.querySelector(".slot-upload-overlay")?.remove();
  preview.querySelector(".slot-similar-preview")?.remove();
  preview.querySelector(".slot-sql-preview")?.remove();
  previewImage.removeAttribute("src");
  empty.textContent = searching
    ? "Automatyczne wyszukiwanie podobnych plikow..."
    : "Brak pliku";
  if (searching && !candidate && !selectedFile && !loadedPhoto) {
    empty.setAttribute("role", "status");
    empty.setAttribute("aria-live", "polite");
  } else {
    empty.removeAttribute("role");
    empty.removeAttribute("aria-live");
  }
  if (selectedSlotSource(prefix, loadedPhoto) === "sql") {
    renderSqlPreview(prefix, loadedPhoto, preview, empty);
    return;
  }
  if (selectedFile) {
    if (selectedSlotSource(prefix, loadedPhoto) === "similar") {
      preview.classList.add("has-similar-candidate");
    }
    if (selectedSlotSource(prefix, loadedPhoto) === "similar" && candidate?.is_pdf) {
      renderSimilarCandidatePreview(prefix, preview, previewImage, empty);
      return;
    }
    if (isFileImageLike(selectedFile)) {
      renderSelectedFilePreview(prefix, selectedFile, preview, previewImage, empty);
    } else {
      empty.textContent = slotFileName(selectedFile);
    }
    renderSlotUploadOverlay(preview, selectedFile);
    return;
  }
  if (candidate) {
    renderSimilarCandidatePreview(prefix, preview, previewImage, empty);
    return;
  }
  if (!loadedPhoto) return;
  preview.classList.add("loaded-photo");
  if (
    state.ftpPreviewLoading.has(prefix) &&
    !state.ftpPreviewBackgroundLoading.has(prefix) &&
    selectedSlotSource(prefix, loadedPhoto) === "ftp"
  ) {
    empty.textContent = "Pobieranie z FTP...";
    preview.classList.add("thumb-loading");
    return;
  }
  const thumb = thumbnailUrl(loadedPhoto, prefix);
  if (thumb && loadedPhoto.is_image) {
    preview.classList.add("thumb-loading");
    previewImage.addEventListener(
      "load",
      () => {
        preview.classList.remove("thumb-loading");
      },
      { once: true }
    );
    previewImage.addEventListener(
      "error",
      () => {
        preview.classList.remove("thumb-loading", "has-image");
        empty.textContent = "Podglad niedostepny";
      },
      { once: true }
    );
    previewImage.src = thumb;
    preview.classList.add("has-image");
    return;
  }
  empty.textContent =
    selectedSlotSource(prefix, loadedPhoto) === "ftp" && loadedPhoto.ftp_filename && !loadedPhoto.ftp_token
      ? "Kliknij FTP, aby pobrac podglad"
      : slotStatusText(loadedPhoto, prefix);
}

function createSlotNode(slot) {
    const node = slotTemplate.content.firstElementChild.cloneNode(true);
    const title = node.querySelector(".slot-meta strong");
    const detail = node.querySelector(".slot-meta span");
    const input = node.querySelector("input");
    const preview = node.querySelector(".slot-preview");
    const previewImage = node.querySelector("img");
    const empty = node.querySelector(".slot-empty");
    const meta = node.querySelector(".slot-meta");
    const loadedPhoto = state.loadedPhotos.get(slot.prefix);
    const selectedFile = state.files.get(slot.prefix);
    const candidate = similarCandidateForSlot(slot.prefix);
    const searching = state.similarFileLookupInFlight && isFreeSimilarSlot(slot.prefix);
    const overlay = document.createElement("div");
    const loadingLabel = document.createElement("span");
    const progressLine = document.createElement("div");
    const progressIndicator = document.createElement("i");
    const controls = document.createElement("div");
    const fitButton = document.createElement("button");
    const openButton = document.createElement("button");
    const clearButton = document.createElement("button");
    node.dataset.slotPrefix = slot.prefix;
    node.dataset.activeSource = selectedSlotSource(slot.prefix, loadedPhoto) || "";
    updateOcrSlotIndicator(node, selectedFile, loadedPhoto);
    node.classList.toggle("slot-similar-pending", Boolean(candidate && !selectedFile));
    node.classList.toggle("similar-searching", searching);

    title.textContent = `${slot.prefix} - ${slot.label}`;
    detail.textContent = selectedFile ? fileLabel(selectedFile) : slotStatusText(loadedPhoto, slot.prefix);
    input.name = `slot_${slot.prefix}`;
    input.multiple = true;
    input.accept = uploadAcceptAttribute();
    previewImage.draggable = false;
    previewImage.loading = "lazy";
    previewImage.decoding = "async";
    if (searching && !candidate && !selectedFile && !loadedPhoto) {
      empty.textContent = "Automatyczne wyszukiwanie podobnych plikow...";
      empty.setAttribute("role", "status");
      empty.setAttribute("aria-live", "polite");
    } else {
      empty.removeAttribute("role");
      empty.removeAttribute("aria-live");
    }
    node.draggable = Boolean(selectedFile || loadedPhoto?.token || loadedPhoto?.ftp_token || loadedPhoto?.ftp_filename);
    renderSlotBadges(meta, loadedPhoto, selectedFile, slot.prefix);
    if (candidate?.source_color) {
      const sourceInfo = document.createElement("span");
      sourceInfo.className = "slot-similar-source";
      sourceInfo.textContent = `Podobne: kolor ${candidate.source_color}`;
      meta.appendChild(sourceInfo);
    }
    overlay.className = "slot-loading-overlay";
    loadingLabel.textContent = photoLoadingText();
    progressLine.className = "progress-line";
    progressLine.appendChild(progressIndicator);
    overlay.append(loadingLabel, progressLine);
    if (state.photosLoading && !selectedFile && !loadedPhoto) {
      preview.appendChild(overlay);
    }
    controls.className = "slot-preview-actions";
    fitButton.type = "button";
    fitButton.className = `slot-fit-button ${isSlotFit(slot.prefix) ? "active" : ""}`;
    fitButton.textContent = "FIT";
    fitButton.title = "Dopasuj zapis tego slotu do zawartosci obrazu";
    fitButton.addEventListener("click", (event) => {
      event.stopPropagation();
      state.slotFits.set(slot.prefix, !isSlotFit(slot.prefix));
      updateSlotPreview(slot.prefix);
      startSimilarFileLookup({ immediate: true });
    });
    openButton.type = "button";
    openButton.className = "slot-open-button";
    openButton.textContent = "Otwórz";
    openButton.addEventListener("click", (event) => {
      event.stopPropagation();
      openSlotFile(slot.prefix).catch((error) => {
        formStatus.textContent = error.message;
      });
    });
    clearButton.type = "button";
    clearButton.className = "slot-clear-button";
    clearButton.textContent = "Usun";
    clearButton.title = "Usun plik z tego slotu w formularzu";
    clearButton.addEventListener("click", (event) => {
      event.stopPropagation();
      const hadSavedPhoto = Boolean(state.loadedPhotos.get(slot.prefix));
      clearSlotAssignment(slot.prefix);
      formStatus.textContent = hadSavedPhoto
        ? `Oznaczono slot ${slot.prefix} do usuniecia przy zapisie.`
        : `Wyczyszczono slot ${slot.prefix}.`;
      renderSlot(slot.prefix);
    });
    if (selectedFile || loadedPhoto || candidate) {
      if (selectedSlotSourceCanFit(slot.prefix, loadedPhoto, selectedFile)) {
        controls.appendChild(fitButton);
      }
      controls.appendChild(clearButton);
    }
    updateSlotOpenButton(openButton, slot.prefix, loadedPhoto, selectedFile);
    controls.appendChild(openButton);
    if (candidate && !selectedFile) {
      const decision = document.createElement("div");
      const acceptButton = document.createElement("button");
      const rejectButton = document.createElement("button");
      const label = document.createElement("span");
      decision.className = "slot-similar-decision";
      label.textContent = "Wymaga decyzji · z podobnego";
      acceptButton.type = "button";
      acceptButton.className = "slot-similar-accept";
      acceptButton.textContent = "✓";
      acceptButton.title = "Wczytaj plik z podobnego produktu";
      acceptButton.setAttribute("aria-label", acceptButton.title);
      acceptButton.addEventListener("click", (event) => {
        event.stopPropagation();
        acceptSimilarCandidate(slot.prefix);
      });
      rejectButton.type = "button";
      rejectButton.className = "slot-similar-reject";
      rejectButton.textContent = "×";
      rejectButton.title = "Odrzuc sugestie z podobnego produktu";
      rejectButton.setAttribute("aria-label", rejectButton.title);
      rejectButton.addEventListener("click", (event) => {
        event.stopPropagation();
        dismissSimilarCandidate(slot.prefix);
        renderSlot(slot.prefix);
      });
      decision.append(label, acceptButton, rejectButton);
      meta.appendChild(decision);
    }

    if (selectedSlotSource(slot.prefix, loadedPhoto) === "sql") {
      renderSqlPreview(slot.prefix, loadedPhoto, preview, empty);
    } else if (selectedFile) {
      if (selectedSlotSource(slot.prefix, loadedPhoto) === "similar") {
        preview.classList.add("has-similar-candidate");
      }
      if (selectedSlotSource(slot.prefix, loadedPhoto) === "similar" && candidate?.is_pdf) {
        renderSimilarCandidatePreview(slot.prefix, preview, previewImage, empty);
      } else if (isFileImageLike(selectedFile)) {
        renderSelectedFilePreview(slot.prefix, selectedFile, preview, previewImage, empty);
      } else {
        empty.textContent = slotFileName(selectedFile);
      }
      renderSlotUploadOverlay(preview, selectedFile);
    } else if (candidate) {
      renderSimilarCandidatePreview(slot.prefix, preview, previewImage, empty);
    } else if (loadedPhoto) {
      preview.classList.add("loaded-photo");
      const thumb = thumbnailUrl(loadedPhoto, slot.prefix);
      if (
        state.ftpPreviewLoading.has(slot.prefix) &&
        !state.ftpPreviewBackgroundLoading.has(slot.prefix) &&
        selectedSlotSource(slot.prefix, loadedPhoto) === "ftp"
      ) {
        preview.classList.add("thumb-loading");
        empty.textContent = "Pobieranie z FTP...";
      } else if (thumb && loadedPhoto.is_image) {
        preview.classList.add("thumb-loading");
        previewImage.addEventListener("load", () => {
          preview.classList.remove("thumb-loading");
        });
        previewImage.addEventListener("error", () => {
          preview.classList.remove("thumb-loading", "has-image");
          empty.textContent = "Podglad niedostepny";
        });
        previewImage.src = thumb;
        preview.classList.add("has-image");
      } else {
        empty.textContent =
          selectedSlotSource(slot.prefix, loadedPhoto) === "ftp" && loadedPhoto.ftp_filename && !loadedPhoto.ftp_token
            ? "Kliknij FTP, aby pobrac podglad"
            : slotStatusText(loadedPhoto, slot.prefix);
      }
    }
    if (controls.childElementCount) {
      preview.appendChild(controls);
    }

    node.addEventListener("dragstart", (event) => {
      const assignment = getSlotAssignment(slot.prefix);
      if (!assignment) {
        event.preventDefault();
        return;
      }
      state.draggedSlotPrefix = slot.prefix;
      event.dataTransfer.setData("application/x-picsyncra-slot", slot.prefix);
      event.dataTransfer.setData("text/plain", slot.prefix);
      event.dataTransfer.effectAllowed = "move";
    });
    node.addEventListener("dragover", (event) => {
      event.preventDefault();
      node.classList.add("drag-over");
      const sourcePrefix =
        event.dataTransfer.getData("application/x-picsyncra-slot") ||
        state.draggedSlotPrefix ||
        event.dataTransfer.getData("text/plain");
      event.dataTransfer.dropEffect = sourcePrefix ? "move" : "copy";
    });
    node.addEventListener("dragleave", () => {
      node.classList.remove("drag-over");
    });
    node.addEventListener("dragend", () => {
      state.draggedSlotPrefix = "";
      node.classList.remove("drag-over");
    });
    node.addEventListener("drop", (event) => {
      event.preventDefault();
      node.classList.remove("drag-over");
      const sourcePrefix =
        event.dataTransfer.getData("application/x-picsyncra-slot") ||
        state.draggedSlotPrefix ||
        event.dataTransfer.getData("text/plain");
      if (sourcePrefix && getSlotAssignment(sourcePrefix)) {
        state.draggedSlotPrefix = "";
        moveSlotContent(sourcePrefix, slot.prefix);
        return;
      }
      const files = fileListFromInput(event.dataTransfer.files);
      if (files.length) {
        state.draggedSlotPrefix = "";
        assignFilesFromSlot(slot.prefix, files);
      }
    });

    input.addEventListener("change", () => {
      const files = fileListFromInput(input.files);
      if (!files.length) {
        bumpSlotRevision(slot.prefix);
        revokeFilePreviewUrl(slot.prefix);
        state.files.delete(slot.prefix);
        renderSlot(slot.prefix);
        return;
      }
      assignFilesFromSlot(slot.prefix, files, { replaceStart: true });
      input.value = "";
    });

    return node;
}

function renderSlot(prefix) {
  const slot = (state.slots || []).find((item) => String(item.prefix) === String(prefix));
  const existing = slotGrid.querySelector(`[data-slot-prefix="${prefix}"]`);
  if (!slot || !existing) {
    renderSlots();
    return;
  }
  existing.replaceWith(createSlotNode(slot));
  updateSubmitButtonState();
}

function renderChangedSlots(prefixes, options = {}) {
  const uniquePrefixes = [...new Set([...(prefixes || [])].map((prefix) => String(prefix || "")).filter(Boolean))];
  for (const prefix of uniquePrefixes) {
    if (options.skipPendingUserEdits && slotHasPendingUserEdit(prefix)) continue;
    renderSlot(prefix);
  }
}

function renderSlotsExceptPendingUserEdits(prefixes = null) {
  const targetPrefixes = prefixes
    ? [...prefixes]
    : (state.slots || []).map((slot) => slot.prefix);
  renderChangedSlots(targetPrefixes, { skipPendingUserEdits: true });
}

function renderSlots(slots = state.slots) {
  slotGrid.textContent = "";
  state.slots = slots;
  slotCount.textContent = `${slots.length} pol`;

  for (const slot of slots) {
    slotGrid.appendChild(createSlotNode(slot));
  }
  updateSubmitButtonState();
}

function hasPendingSlotChanges() {
  if (state.files.size || state.deletedSlots.size) {
    return true;
  }
  for (const [prefix, photo] of state.loadedPhotos.entries()) {
    if (photo?.dirty) {
      return true;
    }
  }
  return false;
}

function slotHasPendingUserEdit(prefix) {
  return Boolean(
    state.files.has(prefix) ||
      state.deletedSlots.has(prefix) ||
      state.loadedPhotos.get(prefix)?.dirty
  );
}

function pendingChangedSlotPrefixes() {
  const prefixes = new Set();
  for (const prefix of state.files.keys()) prefixes.add(prefix);
  for (const prefix of state.deletedSlots.keys()) prefixes.add(prefix);
  for (const [prefix, photo] of state.loadedPhotos.entries()) {
    if (photo?.dirty) {
      prefixes.add(prefix);
    }
  }
  return prefixes;
}

function clearSavedSlotMarkers(prefixes) {
  for (const prefix of prefixes || []) {
    const photo = state.loadedPhotos.get(prefix);
    if (photo?.dirty) {
      const clean = { ...photo };
      delete clean.dirty;
      state.loadedPhotos.set(prefix, clean);
    }
    state.deletedSlots.delete(prefix);
    state.files.delete(prefix);
    state.userSelectedSlotSources.delete(prefix);
  }
}

function similarOccupiedSlotPrefixes() {
  const occupied = new Set(state.files.keys());
  for (const prefix of state.loadedPhotos.keys()) {
    if (!state.deletedSlots.has(prefix)) occupied.add(prefix);
  }
  return Array.from(occupied).sort();
}

function pimcoreSlotTokens() {
  const tokens = {};
  for (const slot of state.slots || []) {
    const prefix = String(slot.prefix || "");
    if (!prefix || state.deletedSlots.has(prefix)) continue;
    const selected = state.files.get(prefix);
    const token = slotFileToken(selected) || selectedPhotoToken(state.loadedPhotos.get(prefix), prefix);
    if (token) tokens[prefix] = token;
  }
  return tokens;
}

function pimcoreOcrSlotTokens() {
  const allSlotTokens = pimcoreSlotTokens();
  const configuredSlots = Array.isArray(state.settings?.ocr?.enabled_slots)
    ? state.settings.ocr.enabled_slots
    : state.ocrEnabledSlots;
  if (!Array.isArray(configuredSlots)) return allSlotTokens;
  const enabledSlots = new Set(configuredSlots.map(String));
  return Object.fromEntries(
    Object.entries(allSlotTokens).filter(([prefix]) => enabledSlots.has(prefix))
  );
}

function selectedSimilarSlotPrefixes(rows) {
  return Array.from(rows)
    .filter((row) => row.querySelector('[name="similar_file_slot_prefixes"]')?.checked)
    .map((row) => String(row.querySelector('[name="prefix"]')?.value || "").trim())
    .filter(Boolean);
}

async function refreshOcrSlotStates() {
  const pending = [];
  for (const [prefix, item] of state.files.entries()) {
    if (isOcrSlotStateInProgress(item?.ocr_state) && slotFileToken(item)) {
      pending.push([prefix, item, slotFileToken(item)]);
    }
  }
  for (const [prefix, photo] of state.loadedPhotos.entries()) {
    if (
      !state.files.has(prefix)
      && isOcrSlotStateInProgress(photo?.ocr_state)
      && String(photo?.token || "")
    ) {
      pending.push([prefix, photo, String(photo.token)]);
    }
  }
  let changed = false;
  const completions = await Promise.all(pending.map(async ([prefix, item, token]) => {
    try {
      const scan = await requestJson(`/api/ocr/scan?token=${encodeURIComponent(token)}`);
      const nextState = String(scan?.state || "");
      if (nextState && nextState !== "missing" && nextState !== item.ocr_state) {
        item.ocr_state = nextState;
        changed = true;
        updateSlotPreview(prefix);
        return nextState === "completed";
      }
    } catch (_error) {
      // A transient scan lookup must not remove the in-progress indication.
    }
    return false;
  }));
  if (changed) {
    try {
      await refreshOpenPimcoreOcrPanels();
    } catch (_error) {
      // A later OCR refresh retries this optional live view.
    }
  }
  if (completions.some(Boolean)) {
    try {
      await revalidateOpenPimcoreOcrFields();
    } catch (_error) {
      // The next input, recalculation, or OCR completion retries validation.
    }
  }
}
