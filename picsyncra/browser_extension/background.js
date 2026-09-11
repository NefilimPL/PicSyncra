const QUEUE_KEY = "uploadQueue";
const FAILED_KEY = "uploadFailed";
const STATUS_KEY = "uploadStatus";
const ALARM_NAME = "picsyncra-upload-queue";
const UPLOAD_CONCURRENCY = 3;
const RECENT_TASK_LIMIT = 160;
const IMAGE_MIME_BY_EXTENSION = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  jfif: "image/jpeg",
  jpe: "image/jpeg",
  peg: "image/jpeg",
  png: "image/png",
  apng: "image/apng",
  webp: "image/webp",
  gif: "image/gif",
  bmp: "image/bmp",
  dib: "image/bmp",
  tif: "image/tiff",
  tiff: "image/tiff",
  avif: "image/avif",
  avifs: "image/avif-sequence",
  heic: "image/heic",
  heif: "image/heif",
  hif: "image/heif",
  jp2: "image/jp2",
  j2k: "image/j2k",
  jpc: "image/jpc",
  jpx: "image/jpx",
  ico: "image/x-icon",
  cur: "image/x-icon",
  tga: "image/x-tga",
  ppm: "image/x-portable-pixmap",
  pgm: "image/x-portable-graymap",
  pbm: "image/x-portable-bitmap",
  pnm: "image/x-portable-anymap",
  pcx: "image/x-pcx",
};

let processing = false;
let storageMutation = Promise.resolve();

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
}

function withStorageMutation(callback) {
  const next = storageMutation.then(callback, callback);
  storageMutation = next.catch(() => {});
  return next;
}

function normalizePanelUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function makeUploadId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
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

function imageMimeType(url, fallback = "image/jpeg") {
  const lower = String(url || "").toLowerCase().split("?", 1)[0];
  const extension = lower.match(/\.([a-z0-9]+)$/)?.[1] || "";
  return IMAGE_MIME_BY_EXTENSION[extension] || fallback;
}

function queueItemUrl(item) {
  const image = item?.image || item || {};
  return String(image.url || "");
}

function queueItemId(item) {
  return String(item?.uploadId || "");
}

function queueItemsMatch(left, right) {
  if (queueItemId(left) && queueItemId(right)) {
    return queueItemId(left) === queueItemId(right);
  }
  return (
    queueItemUrl(left) === queueItemUrl(right) &&
    String(left?.pageUrl || "") === String(right?.pageUrl || "")
  );
}

function queueWithoutItem(queue, item) {
  const index = queue.findIndex((candidate) => queueItemsMatch(candidate, item));
  if (index < 0) return queue;
  return [...queue.slice(0, index), ...queue.slice(index + 1)];
}

function taskSnapshot(item, patch = {}) {
  const image = item?.image || item || {};
  const startedAt = Number(patch.startedAt ?? item?.startedAt ?? Date.now());
  return {
    id: queueItemId(item) || queueItemUrl(item),
    url: queueItemUrl(item),
    filename: image.filename || imageFilename(queueItemUrl(item)),
    phase: "Oczekuje",
    status: "running",
    progress: 0,
    startedAt,
    elapsedMs: startedAt ? Math.max(0, Date.now() - startedAt) : 0,
    ...patch,
  };
}

async function setActiveTask(item, patch = {}) {
  return withStorageMutation(async () => {
    const stored = await storageGet([STATUS_KEY]);
    const status = stored[STATUS_KEY] || {};
    const id = queueItemId(item) || queueItemUrl(item);
    const active = Array.isArray(status.active) ? [...status.active] : [];
    const index = active.findIndex((task) => String(task.id || "") === id);
    const previous = index >= 0 ? active[index] : {};
    const startedAt = Number(previous.startedAt || patch.startedAt || Date.now());
    const nextTask = taskSnapshot(item, {
      ...previous,
      ...patch,
      startedAt,
      elapsedMs: Math.max(0, Date.now() - startedAt),
      progress: Math.max(0, Math.min(100, Number(patch.progress ?? previous.progress ?? 0))),
    });
    if (index >= 0) {
      active[index] = nextTask;
    } else {
      active.push(nextTask);
    }
    await storageSet({
      [STATUS_KEY]: {
        ...status,
        active,
        updatedAt: Date.now(),
      },
    });
    return nextTask;
  });
}

async function finishTask(item, patch = {}) {
  return withStorageMutation(async () => {
    const stored = await storageGet([STATUS_KEY]);
    const status = stored[STATUS_KEY] || {};
    const id = queueItemId(item) || queueItemUrl(item);
    const active = Array.isArray(status.active) ? [...status.active] : [];
    const index = active.findIndex((task) => String(task.id || "") === id);
    const previous = index >= 0 ? active[index] : {};
    if (index >= 0) {
      active.splice(index, 1);
    }
    const startedAt = Number(previous.startedAt || patch.startedAt || Date.now());
    const task = taskSnapshot(item, {
      ...previous,
      ...patch,
      startedAt,
      elapsedMs: Math.max(0, Date.now() - startedAt),
      completedAt: Date.now(),
    });
    const recent = [task, ...(Array.isArray(status.recent) ? status.recent : [])].slice(
      0,
      RECENT_TASK_LIMIT
    );
    await storageSet({
      [STATUS_KEY]: {
        ...status,
        active,
        recent,
        updatedAt: Date.now(),
      },
    });
    return task;
  });
}

async function setBadge(status) {
  const remaining = Number(status?.remaining || 0);
  if (remaining > 0) {
    await chrome.action.setBadgeBackgroundColor({ color: "#2f6f5e" });
    await chrome.action.setBadgeText({ text: String(Math.min(remaining, 99)) });
  } else if (Number(status?.failed || 0) > 0) {
    await chrome.action.setBadgeBackgroundColor({ color: "#b42318" });
    await chrome.action.setBadgeText({ text: "!" });
  } else {
    await chrome.action.setBadgeText({ text: "" });
  }
}

async function updateStatus(patch) {
  const stored = await storageGet([STATUS_KEY, QUEUE_KEY, FAILED_KEY]);
  const queue = stored[QUEUE_KEY] || [];
  const failedQueue = stored[FAILED_KEY] || [];
  const previous = stored[STATUS_KEY] || {};
  const status = {
    running: false,
    total: 0,
    uploaded: 0,
    failed: 0,
    remaining: queue.length,
    failedRetryable: failedQueue.length,
    active: Array.isArray(previous.active) ? previous.active : [],
    recent: Array.isArray(previous.recent) ? previous.recent : [],
    startedAt: previous.startedAt || 0,
    lastError: "",
    ...previous,
    ...patch,
    failedRetryable: failedQueue.length,
    updatedAt: Date.now(),
  };
  await storageSet({ [STATUS_KEY]: status });
  await setBadge(status);
  return status;
}

async function uploadOne(item, settings) {
  const image = item.image || item;
  const imageUrl = String(image.url || "");
  const pageUrl = String(item.pageUrl || image.pageUrl || "");
  const panelUrl = normalizePanelUrl(settings.panelUrl);
  const apiToken = String(settings.apiToken || "").trim();
  const startedAt = Date.now();
  await setActiveTask(item, {
    phase: "Start",
    progress: 1,
    startedAt,
  });
  if (!panelUrl || !apiToken) {
    throw new Error("Brak adresu panelu albo tokenu.");
  }
  await setActiveTask(item, {
    phase: "Pobieranie z URL",
    progress: 5,
  });
  const imageResponse = await fetch(imageUrl, {
    credentials: "include",
    cache: "no-cache",
  });
  if (!imageResponse.ok) {
    throw new Error(`Nie udalo sie pobrac obrazu ${imageResponse.status}: ${imageUrl}`);
  }
  const downloadStartedAt = Date.now();
  const blob = await responseToProgressBlob(imageResponse, item);
  const downloadMs = Date.now() - downloadStartedAt;
  const filename = imageFilename(imageUrl);
  const form = new FormData();
  form.append("file", blob, filename);
  form.append("prefix", "web");
  form.append("source_url", imageUrl);
  form.append("page_url", pageUrl);

  await setActiveTask(item, {
    phase: "Wysylanie do panelu",
    progress: 82,
    sizeBytes: blob.size,
    downloadMs,
  });
  const uploadStartedAt = Date.now();
  const uploadResponse = await fetch(`${panelUrl}/api/browser-extension/upload-cache`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiToken}` },
    body: form,
  });
  const uploadMs = Date.now() - uploadStartedAt;
  const payload = await uploadResponse.json().catch(() => ({}));
  if (!uploadResponse.ok) {
    throw new Error(payload.detail || `Panel odrzucil upload: ${uploadResponse.status}`);
  }
  const totalMs = Date.now() - startedAt;
  await setActiveTask(item, {
    phase: "Zakonczono",
    progress: 100,
    downloadMs,
    uploadMs,
    totalMs,
    sizeBytes: blob.size,
  });
  return {
    ...payload,
    mime_type: blob.type || imageMimeType(imageUrl),
    taskTiming: {
      downloadMs,
      uploadMs,
      totalMs,
      sizeBytes: blob.size,
    },
  };
}

async function responseToProgressBlob(response, item) {
  const contentLength = Number(response.headers.get("content-length") || 0);
  const contentType = response.headers.get("content-type") || "";
  if (!response.body || !contentLength) {
    const blob = await response.blob();
    await setActiveTask(item, {
      phase: "Pobrano z URL",
      progress: 70,
      bytesReceived: blob.size,
      sizeBytes: blob.size,
    });
    return blob;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  let lastUpdate = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    const now = Date.now();
    if (now - lastUpdate > 250 || received >= contentLength) {
      lastUpdate = now;
      await setActiveTask(item, {
        phase: "Pobieranie z URL",
        progress: Math.max(5, Math.min(70, Math.round((received / contentLength) * 70))),
        bytesReceived: received,
        sizeBytes: contentLength,
      });
    }
  }
  await setActiveTask(item, {
    phase: "Pobrano z URL",
    progress: 70,
    bytesReceived: received,
    sizeBytes: contentLength || received,
  });
  return new Blob(chunks, { type: contentType || imageMimeType(queueItemUrl(item)) });
}

async function processQueueItem(item, settings) {
  try {
    const payload = await uploadOne(item, settings);
    await finishTask(item, {
      phase: "Gotowe",
      status: "done",
      progress: 100,
      ...(payload.taskTiming || {}),
    });
    await withStorageMutation(async () => {
      const latest = await storageGet([QUEUE_KEY, STATUS_KEY]);
      const nextQueue = queueWithoutItem(latest[QUEUE_KEY] || [], item);
      const status = latest[STATUS_KEY] || {};
      await storageSet({ [QUEUE_KEY]: nextQueue });
      await updateStatus({
        running: true,
        uploaded: Number(status.uploaded || 0) + 1,
        remaining: nextQueue.length,
        lastError: "",
      });
    });
  } catch (error) {
    const message = error.message || String(error);
    await finishTask(item, {
      phase: "Blad",
      status: "error",
      progress: 100,
      error: message,
    });
    await withStorageMutation(async () => {
      const latest = await storageGet([QUEUE_KEY, FAILED_KEY, STATUS_KEY]);
      const nextQueue = queueWithoutItem(latest[QUEUE_KEY] || [], item);
      const status = latest[STATUS_KEY] || {};
      await storageSet({
        [QUEUE_KEY]: nextQueue,
        [FAILED_KEY]: [
          ...(latest[FAILED_KEY] || []),
          {
            ...item,
            error: message,
            failedAt: Date.now(),
          },
        ],
      });
      await updateStatus({
        running: true,
        failed: Number(status.failed || 0) + 1,
        remaining: nextQueue.length,
        lastError: message,
      });
    });
  }
}

async function processQueue() {
  if (processing) return;
  processing = true;
  try {
    while (true) {
      const stored = await storageGet([QUEUE_KEY, FAILED_KEY, STATUS_KEY, "panelUrl", "apiToken"]);
      const queue = stored[QUEUE_KEY] || [];
      if (!queue.length) {
        const status = stored[STATUS_KEY] || {};
        const completedAt = Date.now();
        await updateStatus({
          running: false,
          remaining: 0,
          completedAt,
          elapsedMs: status.startedAt ? Math.max(0, completedAt - Number(status.startedAt)) : 0,
        });
        await chrome.alarms.clear(ALARM_NAME);
        return;
      }
      await updateStatus({ running: true, remaining: queue.length });
      const batch = queue.slice(0, UPLOAD_CONCURRENCY);
      await Promise.all(
        batch.map((item) =>
          processQueueItem(item, {
            panelUrl: stored.panelUrl,
            apiToken: stored.apiToken,
          })
        )
      );
    }
  } finally {
    processing = false;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "startUpload") {
    (async () => {
      const images = Array.isArray(message.images) ? message.images : [];
      const incomingQueue = images.map((image) => ({
        uploadId: makeUploadId(),
        image,
        pageUrl: message.pageUrl || "",
      }));
      const result = await withStorageMutation(async () => {
        const stored = await storageGet([QUEUE_KEY, FAILED_KEY, STATUS_KEY]);
        const queue = stored[QUEUE_KEY] || [];
        const status = stored[STATUS_KEY] || {};
        const hasActiveUpload = Boolean(status.running) || queue.length > 0;
        const nextQueue = hasActiveUpload ? [...queue, ...incomingQueue] : incomingQueue;
        const uploaded = hasActiveUpload ? Number(status.uploaded || 0) : 0;
        const failed = hasActiveUpload ? Number(status.failed || 0) : 0;
        const total = hasActiveUpload
          ? Number(status.total || uploaded + failed + queue.length) + incomingQueue.length
          : incomingQueue.length;
        await storageSet({
          [QUEUE_KEY]: nextQueue,
          [FAILED_KEY]: hasActiveUpload ? stored[FAILED_KEY] || [] : [],
          [STATUS_KEY]: {
            running: true,
            total,
            uploaded,
            failed,
            remaining: nextQueue.length,
            failedRetryable: hasActiveUpload ? (stored[FAILED_KEY] || []).length : 0,
            active: hasActiveUpload && Array.isArray(status.active) ? status.active : [],
            recent: hasActiveUpload && Array.isArray(status.recent) ? status.recent : [],
            startedAt: hasActiveUpload && status.startedAt ? status.startedAt : Date.now(),
            completedAt: 0,
            elapsedMs: 0,
            lastError: "",
            updatedAt: Date.now(),
          },
        });
        return { total: incomingQueue.length, queued: nextQueue.length };
      });
      await chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
      processQueue();
      sendResponse({ ok: true, ...result });
    })().catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }
  if (message?.type === "retryFailed") {
    (async () => {
      const result = await withStorageMutation(async () => {
        const stored = await storageGet([QUEUE_KEY, FAILED_KEY, STATUS_KEY]);
        const failedQueue = stored[FAILED_KEY] || [];
        if (!failedQueue.length) {
          return { total: 0, queued: (stored[QUEUE_KEY] || []).length };
        }
        const queue = stored[QUEUE_KEY] || [];
        const nextQueue = [
          ...queue,
          ...failedQueue.map(({ error, failedAt, ...item }) => ({
            ...item,
            uploadId: makeUploadId(),
          })),
        ];
        const status = stored[STATUS_KEY] || {};
        const uploaded = Number(status.uploaded || 0);
        await storageSet({
          [QUEUE_KEY]: nextQueue,
          [FAILED_KEY]: [],
          [STATUS_KEY]: {
            ...status,
            running: true,
            total: uploaded + nextQueue.length,
            uploaded,
            failed: 0,
            remaining: nextQueue.length,
            failedRetryable: 0,
            active: Array.isArray(status.active) ? status.active : [],
            recent: Array.isArray(status.recent) ? status.recent : [],
            startedAt: status.startedAt || Date.now(),
            completedAt: 0,
            elapsedMs: 0,
            lastError: "",
            updatedAt: Date.now(),
          },
        });
        return { total: failedQueue.length, queued: nextQueue.length };
      });
      if (!result.total) {
        sendResponse({ ok: true, ...result });
        return;
      }
      await chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
      processQueue();
      sendResponse({ ok: true, ...result });
    })().catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }
  if (message?.type === "getUploadStatus") {
    storageGet([STATUS_KEY, QUEUE_KEY, FAILED_KEY])
      .then((stored) => {
        const status = stored[STATUS_KEY] || {};
        const failedQueue = stored[FAILED_KEY] || [];
        const queue = stored[QUEUE_KEY] || [];
        const now = Date.now();
        const startedAt = Number(status.startedAt || 0);
        const completedAt = Number(status.completedAt || 0);
        const active = (Array.isArray(status.active) ? status.active : []).map((task) => ({
          ...task,
          elapsedMs: Math.max(0, now - Number(task.startedAt || now)),
        }));
        const activeIds = new Set(active.map((task) => String(task.id || "")));
        const queued = queue
          .filter((item) => !activeIds.has(queueItemId(item) || queueItemUrl(item)))
          .map((item) =>
            taskSnapshot(item, {
              phase: "Oczekuje",
              status: "queued",
              progress: 0,
              startedAt: 0,
              elapsedMs: 0,
            })
          );
        const elapsedMs = startedAt
          ? Math.max(
              0,
              status.running ? now - startedAt : Number(status.elapsedMs || completedAt - startedAt)
            )
          : 0;
        sendResponse({
          ok: true,
          status: {
            running: Boolean(status.running),
            total: Number(status.total || 0),
            uploaded: Number(status.uploaded || 0),
            failed: Number(status.failed || 0),
            remaining: queue.length,
            failedRetryable: failedQueue.length,
            active,
            queued,
            recent: Array.isArray(status.recent) ? status.recent : [],
            elapsedMs,
            concurrency: UPLOAD_CONCURRENCY,
            lastError: status.lastError || "",
          },
        });
      })
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }
  return false;
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    processQueue();
  }
});

chrome.runtime.onStartup.addListener(() => {
  processQueue();
});
