(() => {
  const root = window.PicSyncra = window.PicSyncra || {};

  function finiteNumber(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function nonNegativeInt(value) {
    return Math.max(0, Math.round(finiteNumber(value, 0)));
  }

  function normalizeBbox(value) {
    if (!Array.isArray(value) || value.length !== 4) return null;
    const bbox = value.map((item) => finiteNumber(item, NaN));
    return bbox.every(Number.isFinite) ? bbox : null;
  }

  function normalizeBox(value) {
    if (!value || typeof value !== "object") return null;
    const bbox = normalizeBbox(value.bbox);
    if (!bbox) return null;
    return {
      text: String(value.text || ""),
      value: String(value.value || ""),
      confidence: Math.max(0, Math.min(1, finiteNumber(value.confidence))),
      bbox,
    };
  }

  function normalizeTimings(value) {
    const timings = value && typeof value === "object" ? value : {};
    return {
      fast: nonNegativeInt(timings.fast),
      crop: nonNegativeInt(timings.crop),
      accurate: nonNegativeInt(timings.accurate),
    };
  }

  function normalizeRegion(value, index) {
    if (!value || typeof value !== "object") return null;
    const fast = normalizeBox(value.fast);
    if (!fast) return null;
    const accurate = Array.isArray(value.accurate)
      ? value.accurate.map(normalizeBox).filter(Boolean)
      : [];
    return {
      region_id: String(value.region_id || `region-${index + 1}`),
      fast,
      source_bbox: normalizeBbox(value.source_bbox) || [...fast.bbox],
      crop_bbox: normalizeBbox(value.crop_bbox),
      accurate,
      status: String(value.status || "pending"),
      reason: String(value.reason || ""),
      timings_ms: normalizeTimings(value.timings_ms),
    };
  }

  function normalizeReport(value) {
    const report = value && typeof value === "object" ? value : {};
    const candidates = Array.isArray(report.candidates) ? report.candidates : [];
    const regions = Array.isArray(report.regions) ? report.regions : [];
    const rawTimings = report.timings_ms && typeof report.timings_ms === "object"
      ? report.timings_ms
      : {};
    return {
      available: Boolean(report.available),
      dimensions: report.dimensions && typeof report.dimensions === "object" ? { ...report.dimensions } : {},
      message: String(report.message || ""),
      candidates: candidates.filter((candidate) => candidate && typeof candidate === "object").map((candidate) => ({ ...candidate })),
      regions: regions.map(normalizeRegion).filter(Boolean),
      timings_ms: { total: nonNegativeInt(rawTimings.total) },
    };
  }

  function applyProgressEvent(report, event) {
    const next = normalizeReport(report);
    const kind = String(event?.kind || "");
    const payload = event?.payload && typeof event.payload === "object" ? event.payload : {};
    if (kind === "candidate_regions") {
      const candidates = Array.isArray(payload.regions) ? payload.regions : [];
      for (const candidate of candidates) {
        const fast = normalizeBox(candidate);
        if (!fast) continue;
        const regionId = String(candidate.region_id || `region-${next.regions.length + 1}`);
        const replacement = normalizeRegion({
          region_id: regionId,
          fast,
          source_bbox: candidate.source_bbox || fast.bbox,
          status: "detected",
        }, next.regions.length);
        const index = next.regions.findIndex((region) => region.region_id === regionId);
        if (index >= 0) next.regions[index] = replacement;
        else next.regions.push(replacement);
      }
      return next;
    }

    const regionId = String(payload.region_id || "");
    const region = next.regions.find((item) => item.region_id === regionId);
    if (!region) return next;
    if (kind === "crop_started") {
      region.source_bbox = normalizeBbox(payload.source_bbox) || region.source_bbox;
      region.crop_bbox = normalizeBbox(payload.bbox) || region.crop_bbox;
      region.status = "scanning";
      region.reason = "";
    } else if (kind === "crop_finished") {
      region.source_bbox = normalizeBbox(payload.source_bbox) || region.source_bbox;
      region.crop_bbox = normalizeBbox(payload.bbox) || region.crop_bbox;
      region.accurate = (Array.isArray(payload.accurate) ? payload.accurate : []).map(normalizeBox).filter(Boolean);
      region.status = String(payload.status || (region.accurate.length ? "completed" : "empty"));
      region.reason = String(payload.reason || "");
      region.timings_ms = {
        ...region.timings_ms,
        crop: nonNegativeInt(payload.crop_elapsed_ms),
        accurate: nonNegativeInt(payload.accurate_elapsed_ms),
      };
    } else if (kind === "crop_skipped") {
      region.source_bbox = normalizeBbox(payload.bbox) || region.source_bbox;
      region.status = payload.threshold === undefined ? "skipped" : "skipped_threshold";
      region.reason = String(payload.reason || "Wycinek nie zostal przeskanowany przez dokladny model.");
    }
    return next;
  }

  function collides(first, second) {
    return first.left < second.left + second.width
      && first.left + first.width > second.left
      && first.top < second.top + second.height
      && first.top + first.height > second.top;
  }

  function placeLabels(labels, stageBounds) {
    const width = Math.max(1, finiteNumber(stageBounds?.width, 1));
    const height = Math.max(1, finiteNumber(stageBounds?.height, 1));
    const placed = [];
    for (const rawLabel of Array.isArray(labels) ? labels : []) {
      const bbox = normalizeBbox(rawLabel?.bbox);
      if (!bbox) continue;
      const [left, top, right, bottom] = bbox;
      const labelWidth = Math.min(width, Math.max(1, finiteNumber(rawLabel.width, 48)));
      const labelHeight = Math.min(height, Math.max(1, finiteNumber(rawLabel.height, 18)));
      const centerX = (left + right) / 2;
      const centerY = (top + bottom) / 2;
      const options = [
        ["above", centerX - labelWidth / 2, top - labelHeight - 4],
        ["below", centerX - labelWidth / 2, bottom + 4],
        ["right", right + 4, centerY - labelHeight / 2],
        ["left", left - labelWidth - 4, centerY - labelHeight / 2],
      ];
      let selected = null;
      for (const [position, x, y] of options) {
        const candidate = {
          id: String(rawLabel.id || placed.length + 1),
          position,
          left: Math.max(0, Math.min(width - labelWidth, x)),
          top: Math.max(0, Math.min(height - labelHeight, y)),
          width: labelWidth,
          height: labelHeight,
        };
        if (!placed.some((item) => collides(candidate, item))) {
          selected = candidate;
          break;
        }
      }
      if (!selected) {
        const railTop = Math.min(
          height - labelHeight,
          Math.max(0, placed.length * (labelHeight + 3)),
        );
        selected = {
          id: String(rawLabel.id || placed.length + 1),
          position: "rail",
          left: Math.max(0, width - labelWidth - 4),
          top: railTop,
          width: labelWidth,
          height: labelHeight,
        };
      }
      placed.push(selected);
    }
    return placed;
  }

  function placeLabelsForRenderedImage(labels, imageBounds) {
    const naturalWidth = Math.max(1, finiteNumber(imageBounds?.naturalWidth, 1));
    const naturalHeight = Math.max(1, finiteNumber(imageBounds?.naturalHeight, 1));
    const renderedWidth = Math.max(1, finiteNumber(imageBounds?.renderedWidth, naturalWidth));
    const renderedHeight = Math.max(1, finiteNumber(imageBounds?.renderedHeight, naturalHeight));
    const scaleX = renderedWidth / naturalWidth;
    const scaleY = renderedHeight / naturalHeight;
    const renderedLabels = (Array.isArray(labels) ? labels : []).map((label) => {
      const bbox = normalizeBbox(label?.bbox);
      if (!bbox) return label;
      return {
        ...label,
        bbox: [
          bbox[0] * scaleX,
          bbox[1] * scaleY,
          bbox[2] * scaleX,
          bbox[3] * scaleY,
        ],
      };
    });
    return placeLabels(renderedLabels, { width: renderedWidth, height: renderedHeight });
  }

  function formatDuration(value) {
    const milliseconds = nonNegativeInt(value);
    return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(2)} s` : `${milliseconds} ms`;
  }

  root.OcrDiagnostics = {
    normalizeReport,
    applyProgressEvent,
    placeLabels,
    placeLabelsForRenderedImage,
    formatDuration,
  };
})();
