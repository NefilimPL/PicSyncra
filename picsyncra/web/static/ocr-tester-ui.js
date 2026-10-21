// Classic script: definitions only; shared application state is initialized by app.js.

function ocrDiagnosticsHelper() {
  if (!window.PicSyncra.OcrDiagnostics) {
    throw new Error("Nie zaladowano modulu diagnostyki OCR.");
  }
  return window.PicSyncra.OcrDiagnostics;
}

function ocrBboxLabel(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4) return "brak";
  return `[${bbox.map((value) => Math.round(Number(value) || 0)).join(", ")}]`;
}

function ocrDiagnosticStatusLabel(status) {
  const labels = {
    detected: "wykryto szybkim modelem",
    pending: "oczekuje na decyzje",
    scanning: "trwa skanowanie dokladne",
    completed: "zeskanowano dokladnie",
    empty: "dokladny model nie wykryl tekstu",
    skipped_threshold: "pominieto przez prog pewnosci",
    skipped: "pominieto",
    not_requested: "dokladny model jest wylaczony",
    invalid_region: "niepoprawny obszar",
    full_image: "pelny obraz",
  };
  return labels[String(status || "")] || String(status || "brak statusu");
}

function safeOcrDiagnosticImageUrl(value) {
  try {
    const url = new URL(String(value || ""), window.location.origin);
    if (url.protocol !== "blob:" && url.protocol !== "http:" && url.protocol !== "https:") return "";
    return decodeURI(url.href);
  } catch (_error) {
    return "";
  }
}

function renderOcrDiagnosticView(result, options = {}) {
  const helpers = ocrDiagnosticsHelper();
  const output = document.createElement("div");
  output.className = "ocr-diagnostic-result wide-field";
  const layout = document.createElement("div");
  layout.className = "ocr-diagnostic-layout";
  const stage = document.createElement("div");
  stage.className = `ocr-diagnostic-stage${options.live ? " ocr-diagnostic-live-preview" : ""}`;
  const image = document.createElement("img");
  image.className = "ocr-diagnostic-image";
  image.alt = options.live ? "Obraz analizowany na zywo przez OCR" : "Obraz analizowany przez OCR";
  const imageUrl = safeOcrDiagnosticImageUrl(options.imageUrl || result.image_url);
  if (imageUrl) image.src = encodeURI(imageUrl);
  const overlay = document.createElement("div");
  overlay.className = "ocr-diagnostic-overlay";
  const status = document.createElement("p");
  status.className = "ocr-diagnostic-live-status";
  status.hidden = !options.live;
  status.textContent = "Ladowanie modelu OCR...";
  const details = document.createElement("div");
  details.className = "ocr-diagnostic-details";
  const heading = document.createElement("h3");
  const modelHeadings = document.createElement("div");
  modelHeadings.className = "ocr-diagnostic-model-columns ocr-diagnostic-model-headings";
  const fastHeading = document.createElement("strong");
  fastHeading.textContent = "Szybki model";
  const accurateHeading = document.createElement("strong");
  accurateHeading.textContent = "Dokladny model OCR";
  modelHeadings.append(fastHeading, accurateHeading);
  const pairList = document.createElement("div");
  pairList.className = "ocr-diagnostic-pairs";
  const detailPanel = document.createElement("div");
  detailPanel.className = "ocr-diagnostic-detail-panel";
  let report = helpers.normalizeReport(result);
  let activeRegionId = "";

  const setOcrRegionFocus = (regionId = "") => {
    activeRegionId = String(regionId || "");
    stage.classList.toggle("ocr-diagnostic-focus-active", Boolean(activeRegionId));
    output.querySelectorAll("[data-ocr-region-id]").forEach((element) => {
      const focused = Boolean(activeRegionId) && element.dataset.ocrRegionId === activeRegionId;
      element.classList.toggle("ocr-focused", focused);
      element.classList.toggle("ocr-muted", Boolean(activeRegionId) && !focused);
    });
  };

  const renderDetailPanel = (region = null) => {
    detailPanel.textContent = "";
    if (!region) {
      detailPanel.textContent = "Najedz kursorem lub ustaw fokus na wierszu, aby zobaczyc surowe odczyty, pola i czasy skanowania.";
      return;
    }
    const title = document.createElement("strong");
    title.textContent = `Diagnostyka ${region.region_id}`;
    const statusLine = document.createElement("p");
    statusLine.textContent = `Status: ${ocrDiagnosticStatusLabel(region.status)}.`;
    const fastLine = document.createElement("p");
    fastLine.textContent = region.fast
      ? `Szybki: surowo "${region.fast.text || "-"}", porownanie "${region.fast.value || "-"}", pewnosc ${ocrConfidenceLabel(region.fast.confidence)}, pole ${ocrBboxLabel(region.fast.bbox)}.`
      : "Szybki: brak odczytu regionu (skanowanie pelnego obrazu).";
    const cropLine = document.createElement("p");
    cropLine.textContent = `Zrodlo ${ocrBboxLabel(region.source_bbox)}; wycinek ${ocrBboxLabel(region.crop_bbox)}.`;
    const accurateLine = document.createElement("p");
    accurateLine.textContent = region.accurate.length
      ? `Dokladny: ${region.accurate.map((box) => `"${box.text || "-"}" -> "${box.value || "-"}" (${ocrConfidenceLabel(box.confidence)}, ${ocrBboxLabel(box.bbox)})`).join("; ")}.`
      : "Dokladny: brak odczytu dla tego wycinka.";
    const timings = region.timings_ms || {};
    const timingsLine = document.createElement("p");
    timingsLine.textContent = `Czasy: szybki ${helpers.formatDuration(timings.fast)}, przygotowanie wycinka ${helpers.formatDuration(timings.crop)}, dokladny ${helpers.formatDuration(timings.accurate)}, caly przebieg ${helpers.formatDuration(report.timings_ms.total)}.`;
    detailPanel.append(title, statusLine, fastLine, cropLine, accurateLine, timingsLine);
    if (region.reason) {
      const reason = document.createElement("p");
      reason.textContent = `Powod: ${region.reason}`;
      detailPanel.appendChild(reason);
    }
  };

  const drawOverlay = () => {
    overlay.textContent = "";
    const width = Number(image.naturalWidth || 0);
    const height = Number(image.naturalHeight || 0);
    if (!width || !height) return;
    const labels = [];
    const addBox = (region, box, model, index = 0) => {
      if (!box || !Array.isArray(box.bbox) || box.bbox.length !== 4) return;
      const [left, top, right, bottom] = box.bbox.map(Number);
      if (![left, top, right, bottom].every(Number.isFinite)) return;
      const rectangle = document.createElement("div");
      rectangle.className = `ocr-diagnostic-box ${model}`;
      rectangle.setAttribute("data-ocr-overlay", "true");
      rectangle.setAttribute("data-ocr-region-id", region.region_id);
      rectangle.setAttribute("data-ocr-model", model);
      rectangle.style.left = `${Math.max(0, Math.min(100, (left / width) * 100))}%`;
      rectangle.style.top = `${Math.max(0, Math.min(100, (top / height) * 100))}%`;
      rectangle.style.width = `${Math.max(0.3, Math.min(100, ((right - left) / width) * 100))}%`;
      rectangle.style.height = `${Math.max(0.3, Math.min(100, ((bottom - top) / height) * 100))}%`;
      overlay.appendChild(rectangle);
      const labelText = `${model === "fast" ? "Szybki" : "Dokladny"} ${ocrConfidenceLabel(box.confidence)}`;
      labels.push({
        id: `${region.region_id}-${model}-${index}`,
        region,
        model,
        text: labelText,
        bbox: box.bbox,
        width: Math.max(58, labelText.length * 7 + 12),
        height: 21,
      });
    };
    for (const region of ocrDisplayRegions(report)) {
      addBox(region, region.fast, "fast");
      region.accurate.forEach((box, index) => addBox(region, box, "accurate", index));
    }
    const renderedWidth = Math.max(1, Number(image.clientWidth || stage.clientWidth || width));
    const renderedHeight = Math.max(1, Number(image.clientHeight || stage.clientHeight || height));
    const placements = helpers.placeLabelsForRenderedImage(labels, {
      naturalWidth: width,
      naturalHeight: height,
      renderedWidth,
      renderedHeight,
    });
    placements.forEach((placement) => {
      const labelData = labels.find((label) => label.id === placement.id);
      if (!labelData) return;
      const label = document.createElement("span");
      label.className = `ocr-diagnostic-confidence ${labelData.model}`;
      label.setAttribute("data-ocr-region-id", labelData.region.region_id);
      label.setAttribute("data-ocr-label-position", placement.position);
      label.textContent = labelData.text;
      label.style.left = `${(placement.left / renderedWidth) * 100}%`;
      label.style.top = `${(placement.top / renderedHeight) * 100}%`;
      overlay.appendChild(label);
    });
  };

  const renderPairs = () => {
    pairList.textContent = "";
    const regions = ocrDisplayRegions(report);
    heading.textContent = report.available ? `Wykryte wartosci (${regions.length})` : "OCR niedostepny";
    if (!regions.length) {
      const empty = document.createElement("p");
      empty.className = "settings-note";
      empty.textContent = report.message || "Nie znaleziono tekstu na obrazie.";
      pairList.appendChild(empty);
      renderDetailPanel();
      return;
    }
    for (const region of regions) {
      const row = document.createElement("article");
      row.className = "ocr-diagnostic-pair-row";
      row.tabIndex = 0;
      row.setAttribute("data-ocr-region-id", region.region_id);
      row.title = "Najedz, aby zobaczyc szczegoly diagnostyczne.";
      const columns = document.createElement("div");
      columns.className = "ocr-diagnostic-model-columns";
      const appendModel = (model, title, boxes) => {
        const cell = document.createElement("div");
        cell.className = `ocr-diagnostic-model-cell ${model}`;
        cell.setAttribute("data-ocr-region-id", region.region_id);
        const modelTitle = document.createElement("strong");
        modelTitle.textContent = title;
        cell.appendChild(modelTitle);
        if (!boxes.length) {
          const empty = document.createElement("span");
          empty.className = "ocr-diagnostic-empty-value";
          empty.textContent = model === "fast" ? "Brak regionu" : "Brak odczytu";
          cell.appendChild(empty);
        } else {
          for (const box of boxes) {
            const value = document.createElement("span");
            value.className = "ocr-diagnostic-value";
            value.textContent = `${box.text || "-"} -> ${box.value || "-"} (${ocrConfidenceLabel(box.confidence)})`;
            cell.appendChild(value);
          }
        }
        return cell;
      };
      columns.append(
        appendModel("fast", "Szybki", region.fast ? [region.fast] : []),
        appendModel("accurate", "Dokladny", region.accurate),
      );
      const stateLine = document.createElement("small");
      stateLine.className = "ocr-diagnostic-pair-status";
      stateLine.textContent = ocrDiagnosticStatusLabel(region.status);
      row.append(columns, stateLine);
      const activate = () => {
        setOcrRegionFocus(region.region_id);
        renderDetailPanel(region);
      };
      row.addEventListener("mouseenter", activate);
      row.addEventListener("focus", activate);
      row.addEventListener("mouseleave", () => {
        if (activeRegionId === region.region_id) setOcrRegionFocus();
      });
      row.addEventListener("blur", () => {
        if (activeRegionId === region.region_id) setOcrRegionFocus();
      });
      pairList.appendChild(row);
    }
    const active = regions.find((region) => region.region_id === activeRegionId);
    renderDetailPanel(active || null);
  };

  const update = (nextResult) => {
    report = helpers.normalizeReport(nextResult);
    renderPairs();
    drawOverlay();
  };

  image.addEventListener("load", drawOverlay);
  stage.append(image, overlay, status);
  details.append(heading, modelHeadings, pairList, detailPanel);
  layout.append(stage, details);
  output.appendChild(layout);
  update(result);
  if (image.complete) drawOverlay();
  return { element: output, update, setStatus: (message) => { status.textContent = message; } };
}

async function renderOcrLivePreview(file) {
  const helpers = ocrDiagnosticsHelper();
  const imageUrl = URL.createObjectURL(file);
  const view = renderOcrDiagnosticView({ available: true, image_url: imageUrl }, { imageUrl, live: true });
  let report = helpers.normalizeReport({ available: true });
  return {
    element: view.element,
    setStatus(message) { view.setStatus(message); },
    showEvent(event) {
      report = helpers.applyProgressEvent(report, event);
      view.update(report);
      const kind = String(event?.kind || "");
      const payload = event?.payload || {};
      if (kind === "queued") {
        view.setStatus("Zadanie przekazane do procesu OCR; oczekiwanie na rozpoczecie etapu.");
      } else if (kind === "candidate_regions") {
        view.setStatus(`Szybki model wykryl ${(payload.regions || []).length} sektorow.`);
      } else if (kind === "crop_started") {
        view.setStatus(`Dokladny model skanuje wycinek ${payload.crop_index || 1}/${payload.crop_total || 1}.`);
      } else if (kind === "crop_finished") {
        view.setStatus("Zaktualizowano wynik dokladnego modelu OCR.");
      } else if (kind === "throttled" || kind === "paused") {
        view.setStatus(`OCR wstrzymany: ${payload.reason || payload.resource || "limit zasobow"}.`);
      } else if (kind === "stage_started") {
        const workerPid = Number(payload.worker_pid || 0);
        const worker = workerPid > 0 ? `Proces OCR (PID ${workerPid})` : "Proces OCR";
        view.setStatus(`${worker} rozpoczal etap: ${payload.stage || "przetwarzanie"}.`);
      }
    },
    dispose() { URL.revokeObjectURL(imageUrl); },
  };
}

function renderOcrDiagnostics(result) {
  return renderOcrDiagnosticView(result).element;
}

function renderOcrBackgroundQueue(payload = {}) {
  if (!ocrBackgroundQueuePanel || !ocrBackgroundQueueSummary || !ocrBackgroundQueueList) {
    return;
  }
  const items = Array.isArray(payload.jobs) ? payload.jobs : [];
  const remaining = Math.max(0, Number(payload.remaining_count) || 0);
  ocrBackgroundQueuePanel.hidden = false;
  ocrBackgroundQueueSummary.textContent = remaining ? `+${remaining} kolejnych` : "";
  ocrBackgroundQueueList.replaceChildren();
  if (!items.length) {
    ocrBackgroundQueueList.className = "ocr-background-queue-list empty-state";
    ocrBackgroundQueueList.textContent = "Brak oczekujacych lub aktualnie skanowanych zdjec OCR.";
    return;
  }
  ocrBackgroundQueueList.className = "ocr-background-queue-list";
  for (const job of items) {
    const card = document.createElement("article");
    card.className = `ocr-background-queue-item status-${String(job.status || "pending")}`;
    if (job.thumbnail_url) {
      const image = document.createElement("img");
      image.src = String(job.thumbnail_url);
      image.alt = "Wycinek OCR";
      card.appendChild(image);
    }
    const details = document.createElement("div");
    const modelLabel = job.kind === "fast" ? "Szybki model" : "Dokladny model OCR";
    const state = String(job.status || "pending");
    const stateLabel = state === "processing"
      ? "Skanowanie w tle"
      : state === "pending"
        ? "Oczekuje na bezczynnosc uzytkownikow"
        : state === "completed"
          ? "Zakonczono"
          : state;
    const result = Array.isArray(job.result)
      ? job.result.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    details.textContent = result.length
      ? `${modelLabel} - ${stateLabel}: ${result.join(", ")}`
      : `${modelLabel} - ${stateLabel}`;
    card.appendChild(details);
    ocrBackgroundQueueList.appendChild(card);
  }
}

async function refreshOcrBackgroundQueue() {
  if (!ocrBackgroundQueuePanel) {
    return;
  }
  try {
    renderOcrBackgroundQueue(await requestJson("/api/ocr/jobs"));
  } catch (error) {
    if (error?.status === 403) {
      ocrBackgroundQueuePanel.hidden = true;
      return;
    }
    ocrBackgroundQueuePanel.hidden = true;
  }
}
