"""Static integrity tests for the browser UI."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "picsyncra" / "web" / "static" / "index.html"
LOGIN_HTML = ROOT / "picsyncra" / "web" / "static" / "login.html"
APP_JS = ROOT / "picsyncra" / "web" / "static" / "app.js"
APP_CSS = ROOT / "picsyncra" / "web" / "static" / "app.css"


class _HtmlCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, str] = {}
        self.duplicate_ids: set[str] = set()
        self.input_names: set[str] = set()
        self.button_ids: set[str] = set()
        self.data_modals: set[str] = set()
        self.classes: set[str] = set()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        self.tags.append((tag, attr_map))
        element_id = attr_map.get("id", "")
        if element_id:
            if element_id in self.ids:
                self.duplicate_ids.add(element_id)
            self.ids[element_id] = tag
        if tag == "input" and attr_map.get("name"):
            self.input_names.add(attr_map["name"])
        if tag == "button" and element_id:
            self.button_ids.add(element_id)
        if attr_map.get("data-modal"):
            self.data_modals.add(attr_map["data-modal"])
        for class_name in attr_map.get("class", "").split():
            self.classes.add(class_name)

    def has_tag(self, tag: str, **attrs: str) -> bool:
        for found_tag, found_attrs in self.tags:
            if found_tag != tag:
                continue
            if all(found_attrs.get(key) == value for key, value in attrs.items()):
                return True
        return False


def _parse(path: Path) -> _HtmlCollector:
    parser = _HtmlCollector()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


class WebUiIntegrityTests(unittest.TestCase):
    def test_photo_loading_overlay_does_not_interpret_status_as_html(self) -> None:
        js_source = APP_JS.read_text(encoding="utf-8")
        renderer_start = js_source.index("function createSlotNode")
        renderer_end = js_source.index("function renderSlot(prefix)", renderer_start)
        renderer = js_source[renderer_start:renderer_end]

        self.assertNotIn("overlay.innerHTML", renderer)
        self.assertIn("textContent = photoLoadingText()", renderer)

    def test_pimcore_editor_exposes_a_compact_live_ocr_sidebar(self) -> None:
        html = _parse(INDEX_HTML)
        source = APP_JS.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertEqual(html.ids.get("pimcoreCreateOcrPanel"), "aside")
        self.assertEqual(html.ids.get("pimcoreEditOcrPanel"), "aside")
        self.assertIn("function renderPimcoreOcrPanel", source)
        self.assertIn("function refreshOpenPimcoreOcrPanels", source)
        self.assertIn("pimcore-runtime-layout", css)
        self.assertIn("pimcore-ocr-sidebar", css)

    def test_cached_or_moved_slot_image_is_activated_for_ocr_in_its_destination(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        web_item = source[
            source.index("function webImageCacheItem") : source.index(
                "async function cacheWebImageForSlot",
                source.index("function webImageCacheItem"),
            )
        ]
        activation = source[
            source.index("async function ensureSlotOcrCollection") : source.index(
                "function acceptSimilarCandidate",
                source.index("async function ensureSlotOcrCollection"),
            )
        ]
        similar = source[
            source.index("function acceptSimilarCandidate") : source.index(
                "function pendingSimilarCandidatePrefixes",
                source.index("function acceptSimilarCandidate"),
            )
        ]
        assignment = source[
            source.index("function setSlotAssignment") : source.index(
                "function moveSlotContent",
                source.index("function setSlotAssignment"),
            )
        ]
        web_assignment = source[
            source.index("async function addSelectedWebImagesToSlots") : source.index(
                "function imageFromBrowserExtensionItem",
                source.index("async function addSelectedWebImagesToSlots"),
            )
        ]

        self.assertIn("ocr_state: payload.ocr_state", web_item)
        self.assertIn('requestJson("/api/ocr/slot-assignment"', activation)
        self.assertIn("ensureSlotOcrCollection(prefix", similar)
        self.assertIn("ensureSlotOcrCollection(prefix", assignment)
        self.assertIn("ensureSlotOcrCollection(prefix", web_assignment)

    def test_settings_ui_contains_module_status_tab_and_refresh_contract(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('data-settings-tab="module-status"', html)
        self.assertIn('src="/static/module-build-status.js', html)
        self.assertIn('"/api/settings/module-status"', source)
        self.assertIn("Odswiez porownanie", source)
        self.assertIn("function renderSettingsModuleStatus()", source)
        self.assertIn("utilities.commitUrl", source)
        self.assertIn('link.target = "_blank"', source)

    def test_ocr_background_queue_renders_safe_rows_in_workspace_position(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        source = APP_JS.read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderOcrBackgroundQueue") : source.index(
                "function renderSettingsOcr", source.index("function renderOcrBackgroundQueue")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the OCR queue rendering contract")
        script = f"""
const makeNode = (tag) => ({{
  tag, className: "", textContent: "", hidden: false, src: "", alt: "",
  children: [],
  append(...items) {{ this.children.push(...items); }},
  appendChild(item) {{ this.children.push(item); return item; }},
  replaceChildren(...items) {{ this.children = items; this.textContent = ""; }},
  classList: {{ toggle() {{}}, add() {{}}, remove() {{}} }},
}});
const document = {{ createElement: makeNode }};
const ocrBackgroundQueuePanel = makeNode("section");
const ocrBackgroundQueueSummary = makeNode("span");
const ocrBackgroundQueueList = makeNode("div");
{renderer}
renderOcrBackgroundQueue({{
  jobs: [
    {{ kind: "fast", thumbnail_url: "/api/file?token=crop-1", status: "processing", result: [] }},
    {{ kind: "accurate", thumbnail_url: "/api/file?token=crop-2", status: "completed", result: ["20kg \\u2192 20"] }},
  ],
  remaining_count: 7,
}});
console.log(JSON.stringify({{
  hidden: ocrBackgroundQueuePanel.hidden,
  summary: ocrBackgroundQueueSummary.textContent,
  firstImage: ocrBackgroundQueueList.children[0]?.children[0]?.src || "",
  secondImage: ocrBackgroundQueueList.children[1]?.children[0]?.src || "",
  firstText: ocrBackgroundQueueList.children[0]?.children[1]?.textContent || "",
  secondText: ocrBackgroundQueueList.children[1]?.children[1]?.textContent || "",
}}));
renderOcrBackgroundQueue({{ jobs: [], remaining_count: 0 }});
console.log(JSON.stringify({{ emptyText: ocrBackgroundQueueList.textContent }}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result, empty = [json.loads(line) for line in completed.stdout.splitlines()]

        self.assertFalse(result["hidden"])
        self.assertEqual(result["summary"], "+7 kolejnych")
        self.assertEqual(result["firstImage"], "/api/file?token=crop-1")
        self.assertEqual(result["secondImage"], "/api/file?token=crop-2")
        self.assertIn("Szybki model", result["firstText"])
        self.assertIn("zdjec", empty["emptyText"])
        self.assertIn("20kg → 20", result["secondText"])
        self.assertIn('id="ocrBackgroundQueuePanel"', html)
        self.assertGreater(html.index('id="ocrBackgroundQueuePanel"'), html.index('id="processQueuePanel"'))
        self.assertLess(html.index('id="ocrBackgroundQueuePanel"'), html.index('id="slotsTitle"'))

    def test_clearing_slot_reports_its_removed_file_token_to_ocr(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        clear_assignment = source[
            source.index("function clearSlotAssignment") : source.index(
                "function setSlotFile", source.index("function clearSlotAssignment")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the OCR slot activity contract")
        script = f"""
const state = {{
  files: new Map(), loadedPhotos: new Map([["01", {{ token: "old-slot-token" }}]]),
  slotFits: new Map(), slotSources: new Map(), userSelectedSlotSources: new Map(),
}};
const calls = [];
const bumpSlotRevision = () => {{}};
const markSlotDeletion = () => {{}};
const revokeFilePreviewUrl = () => {{}};
const dismissSimilarCandidate = () => {{}};
const slotAssignmentToken = (prefix) => state.loadedPhotos.get(prefix)?.token || "";
const recordOcrActivity = (payload) => calls.push(payload);
{clear_assignment}
clearSlotAssignment("01");
console.log(JSON.stringify(calls));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(
            json.loads(completed.stdout),
            [{"removedSlotToken": "old-slot-token"}],
        )

    def test_ocr_slot_polling_keeps_queue_and_refinement_states_live(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        state_helpers = source[
            source.index("function isOcrSlotStateInProgress") : source.index(
                "function updateSlotPreview", source.index("function isOcrSlotStateInProgress")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the OCR slot state contract")
        completed = subprocess.run(
            [
                str(node),
                "-e",
                f"{state_helpers}\nconsole.log(JSON.stringify([\"queued\", \"scanning\", \"refining\", \"completed\"].map(isOcrSlotStateInProgress)));",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(json.loads(completed.stdout), [True, True, True, False])
        self.assertIn("isOcrSlotStateInProgress(item?.ocr_state)", source)
        self.assertIn("isOcrSlotStateInProgress(photo?.ocr_state)", source)

    def test_settings_ocr_tab_has_diagnostic_controls_and_overlay_contract(self) -> None:
        html = _parse(INDEX_HTML)
        source = APP_JS.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertTrue(html.has_tag("button", **{"data-settings-tab": "ocr"}))
        self.assertIn("function renderSettingsOcr()", source)
        self.assertIn("function renderOcrDiagnostics", source)
        self.assertIn("function renderOcrLivePreview", source)
        self.assertIn("showEvent(event)", source)
        self.assertIn("candidate_regions", source)
        self.assertIn("crop_started", source)
        self.assertIn("PicSyncra.OcrDiagnostics", source)
        self.assertIn("applyProgressEvent", source)
        self.assertNotIn("createImageBitmap", source)
        self.assertNotIn("data-ocr-candidate-index", source)
        self.assertIn("await renderOcrLivePreview(selected)", source)
        self.assertIn("data-ocr-region-id", source)
        self.assertIn("setOcrRegionFocus", source)
        self.assertIn("ocr-diagnostic-focus-active", css)
        self.assertIn("ocr-focused", css)
        self.assertNotIn("0 0 0 9999px", css)
        self.assertIn("/api/settings/ocr/status", source)
        self.assertIn("/api/settings/ocr/runs", source)
        self.assertIn("ocr_max_memory_mode", source)
        self.assertIn("ocr_max_memory_percent", source)
        self.assertIn("ocr_max_memory_gb", source)
        self.assertIn("ocr_max_disk_busy_percent", source)
        self.assertIn("ocr_accurate_confidence_threshold", source)
        self.assertIn(
            'selectField("ocr_max_memory_mode", "Miekki prog RAM systemu", ocrSettings.max_memory_mode || "percent", [\n'
            '    ["percent", "Procent calego RAM"],\n'
            '    ["gigabytes", "GB aktualnego uzycia"],',
            source,
        )
        self.assertIn("Aktualne uzycie RAM", source)
        self.assertIn('"Miekki prog RAM systemu"', source)
        self.assertIn(
            '"OCR sprawdza uzycie przed kazdym etapem i czeka przed rozpoczeciem kolejnego; nie przerywa etapu, ktory juz trwa."',
            source,
        )
        self.assertIn("Aktualna aktywnosc dysku", source)
        self.assertIn('"Proces OCR"', source)
        self.assertIn('"Zadanie przekazane do procesu OCR; oczekiwanie na rozpoczecie etapu."', source)
        self.assertIn("data-ocr-overlay", source)
        self.assertIn("model.version", source)
        self.assertIn("%", source)
        self.assertIn("ocr-diagnostic-overlay", css)
        self.assertIn("ocr-diagnostic-live-status", css)
        self.assertIn("ocr-diagnostic-model-columns", css)
        self.assertIn("ocr-diagnostic-detail-panel", css)
        self.assertIn('data-ocr-label-position="rail"', css)
        self.assertIn('requestJson("/api/ocr/jobs")', source)
        self.assertIn("ocr-background-queue", css)
        self.assertIn("slot-ocr-state", source)
        self.assertIn("ocr-collecting", css)
        self.assertIn('requestJson("/api/ocr/validate"', source)
        self.assertIn('requestJson("/api/ocr/approval"', source)
        self.assertIn("pimcore-runtime-ocr-mismatch", css)
        self.assertIn("function openOcrAnnotatedImage", source)
        self.assertIn('requestJson(`/api/ocr/scan?token=${encodeURIComponent(token)}`)', source)
        self.assertIn("ocr-slot-open-overlay", css)
        self.assertIn('overlay.className = "ocr-slot-open-overlay";', source)
        self.assertIn("function refreshOcrSlotStates", source)
        self.assertIn('requestJson(`/api/ocr/scan?token=${encodeURIComponent(token)}`)', source)
        self.assertIn('createPoller("ocr-slot-state", 1500, refreshOcrSlotStates)', source)

    def test_pimcore_export_selection_has_a_legacy_chrome_border_fallback(self) -> None:
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            css,
            r"\.pimcore-export-layout-row\.pimcore-export-layout-selected\s*\{[^}]*"
            r"border-color:\s*var\(--accent\);\s*"
            r"border-color:\s*color-mix\(in srgb, var\(--accent\) 55%, transparent\);",
        )

    def test_pimcore_export_drag_grip_uses_safari_safe_selection_and_has_no_empty_rules(self) -> None:
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            css,
            r"\.pimcore-export-layout-grip\s*\{[^}]*"
            r"-webkit-user-select:\s*none;[^}]*user-select:\s*none;",
        )
        self.assertNotRegex(css, r"\.history-summary-row\s*\{\s*\}")
        self.assertNotRegex(css, r"\.slots-section\s*\{\s*\}")

    def test_thumbnail_filter_has_a_label_and_safari_safe_selection_rule(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertRegex(
            html,
            r'<label class="check-row compact-check web-image-thumbnail-filter">\s*'
            r'<input id="webImageHideThumbnails" type="checkbox">',
        )
        self.assertIn("-webkit-user-select: none;", css)
        self.assertNotIn("-webkit-user-drag:", css)
        self.assertNotIn("min-height: auto;", css)

    def test_slot_settings_collect_similar_file_detection_configuration(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('"similar_file_detection"', source)
        self.assertIn('"Wykrywaj pliki z podobnych produktow"', source)
        self.assertIn("similar_file_slot_prefixes", source)

    def test_similar_candidate_requires_explicit_acceptance_and_has_source_button(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function acceptSimilarCandidate(prefix)", source)
        self.assertIn('acceptButton.textContent = "✓";', source)
        self.assertIn('rejectButton.textContent = "×";', source)
        self.assertIn('["similar", "POD"', source)
        self.assertIn('source === "similar"', source)

    def test_sql_badge_selects_text_copy_preview_and_only_opens_http_urls(self) -> None:
        """SQL must be a visible copyable source state, never a blind file opener."""

        source = APP_JS.read_text(encoding="utf-8")
        badge_start = source.index("function renderSlotBadges")
        badge_end = source.index("function isPhotoSourceLoading", badge_start)
        badges = source[badge_start:badge_end]
        opener_start = source.index("function loadedFileUrl")
        opener_end = source.index("function markSlotDeletion", opener_start)
        opener = source[opener_start:opener_end]

        self.assertIn("function isHttpUrl(value)", source)
        self.assertIn("function renderSqlPreview", source)
        self.assertIn('state.slotSources.set(prefix, key);', badges)
        self.assertIn("updateSlotPreview(prefix);", badges)
        self.assertNotIn("copyTextToClipboard(sqlValue", badges)
        self.assertIn('source === "sql"', opener)
        self.assertIn("isHttpUrl", opener)

        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the SQL URL contract test")
        start = source.index("function isHttpUrl(value)")
        end = source.index("function selectedPhotoToken", start)
        is_http_url = source[start:end]
        script = f"""
{is_http_url}
console.log(JSON.stringify({{
  http: isHttpUrl('http://example.test/file.pdf'),
  https: isHttpUrl('https://example.test/file.pdf'),
  plainSql: isHttpUrl('Assembly_instruction'),
  ftp: isHttpUrl('ftp://example.test/file.pdf'),
}}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"http": True, "https": True, "plainSql": False, "ftp": False},
        )

    def test_slot_open_state_tracks_ready_local_ftp_and_sql_sources(self) -> None:
        """A source change must update opening readiness without reloading the EAN."""

        source = APP_JS.read_text(encoding="utf-8")
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the slot opening readiness contract test")
        is_http_start = source.index("function isHttpUrl(value)")
        is_http_end = source.index("function selectedPhotoToken", is_http_start)
        default_source_start = source.index("function defaultSlotSource")
        default_source_end = source.index("function similarCandidateForSlot", default_source_start)
        state_start = source.index("function slotOpenState")
        state_end = source.index("function selectedSlotSourceCanOpen", state_start)
        script = f"""
const state = {{ slotSources: new Map() }};
const similarCandidateForSlot = () => null;
{source[is_http_start:is_http_end]}
{source[default_source_start:default_source_end]}
{source[state_start:state_end]}
const ftpLoading = {{ ftp: true, ftp_filename: '590776365477_14.png' }};
const ftpReady = {{ ...ftpLoading, ftp_url: '/api/file?token=abc' }};
const sqlUrl = {{ sql: true, sql_value: 'https://example.test/file.jpg' }};
const sqlText = {{ sql: true, sql_value: 'nie-jest-linkiem' }};
state.slotSources.set('14', 'ftp');
const results = {{ ftp_loading: slotOpenState('14', ftpLoading, null), ftp_ready: slotOpenState('14', ftpReady, null) }};
state.slotSources.set('14', 'sql');
results.sql_url = slotOpenState('14', sqlUrl, null);
results.sql_text = slotOpenState('14', sqlText, null);
console.log(JSON.stringify(results));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "ftp_loading": {"enabled": False, "title": "Pobieranie pliku FTP..."},
                "ftp_ready": {"enabled": True, "title": "Otwórz aktywne źródło FTP"},
                "sql_url": {"enabled": True, "title": "Otwórz aktywne źródło SQL"},
                "sql_text": {"enabled": False, "title": "Wartość SQL nie jest linkiem HTTP/HTTPS"},
            },
        )

    def test_slot_open_button_keeps_the_original_preview_overlay(self) -> None:
        """All slot actions keep their established preview overlay positions."""

        source = APP_JS.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")
        renderer_start = source.index("function createSlotNode")
        renderer_end = source.index("function renderSlot(", renderer_start)
        renderer = source[renderer_start:renderer_end]

        self.assertIn('controls.className = "slot-preview-actions";', renderer)
        self.assertIn("preview.appendChild(controls);", renderer)
        self.assertNotIn("meta.appendChild(controls);", renderer)
        self.assertIn("function updateSlotOpenButton", source)
        self.assertIn('openButton.textContent = "Otwórz";', renderer)
        self.assertIn(".slot-preview-actions .slot-fit-button {\n  top: 3px;\n  left: 3px;", css)
        self.assertIn(".slot-preview-actions .slot-clear-button {\n  top: 3px;\n  right: 3px;", css)
        self.assertIn(".slot-preview-actions .slot-open-button {\n  bottom: 3px;\n  left: 3px;", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertNotIn(".slot-controls", css)
        self.assertNotRegex(css, r"\.slot-meta \{\s*min-width: 0;\s*overflow: visible;")

    def test_active_ftp_source_refreshes_stale_preview_before_opening(self) -> None:
        """A stale FTP cache token must never be opened without a refresh request."""

        source = APP_JS.read_text(encoding="utf-8")
        loader_start = source.index("async function loadFtpPreview")
        loader_end = source.index("function nextBackgroundFtpPreviewCandidate", loader_start)
        loader = source[loader_start:loader_end]
        opener_start = source.index("async function openSlotFile")
        opener_end = source.index("function markSlotDeletion", opener_start)
        opener = source[opener_start:opener_end]
        badge_start = source.index("function renderSlotBadges")
        badge_end = source.index("function isPhotoSourceLoading", badge_start)
        badges = source[badge_start:badge_end]

        self.assertIn("const forceRefresh = Boolean(options.forceRefresh);", loader)
        self.assertIn("const cached = forceRefresh ? null", loader)
        self.assertIn(
            "await loadFtpPreview(photo, prefix, openingRequestId, { forceRefresh: true });",
            opener,
        )
        self.assertIn("loadFtpPreview(photo, prefix, state.photoLoadRequestId, { forceRefresh: true })", badges)
        self.assertIn("ftpPreviewRequests: new Map(),", source)
        self.assertIn("const pending = state.ftpPreviewRequests.get(prefix);", loader)
        self.assertIn("await pending;", loader)
        self.assertIn("return loadFtpPreview(refreshedPhoto, prefix, requestId, options);", loader)

    def test_ftp_refresh_does_not_change_newer_slot_state_or_open_it(self) -> None:
        """A completed old FTP request must not override another entry or source selection."""

        source = APP_JS.read_text(encoding="utf-8")
        loader_start = source.index("async function loadFtpPreview")
        loader_end = source.index("function nextBackgroundFtpPreviewCandidate", loader_start)
        loader = source[loader_start:loader_end]
        opener_start = source.index("async function openSlotFile")
        opener_end = source.index("function markSlotDeletion", opener_start)
        opener = source[opener_start:opener_end]

        self.assertIn("const openingRequestId = state.photoLoadRequestId;", opener)
        self.assertIn("const openingRevision = slotRevision(prefix);", opener)
        self.assertIn("openingRequestId !== state.photoLoadRequestId", opener)
        self.assertIn("openingRevision !== slotRevision(prefix)", opener)
        self.assertIn('selectedSlotSource(prefix, photo) !== "ftp"', opener)
        self.assertIn("if (state.ftpPreviewRequests.get(prefix) !== requestComplete) return;", loader)
        self.assertNotIn('state.slotSources.set(prefix, "ftp");', loader)

    def test_unaccepted_similar_candidate_is_the_current_preview_source(self) -> None:
        """The candidate shown by default must be openable as the active POD source."""

        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function selectedSlotSource")
        end = source.index("function similarCandidateForSlot", start)
        selected_source = source[start:end]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar source contract test")
        script = f"""
const state = {{ slotSources: new Map() }};
const similarCandidateForSlot = (prefix) => prefix === '07' ? {{ url: '/api/cache/file' }} : null;
const defaultSlotSource = () => '';
{selected_source}
console.log(selectedSlotSource('07', null));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(completed.stdout.strip(), "similar")

    def test_filling_an_existing_product_replaces_old_similar_lookup_with_a_fresh_one(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function fillForm")
        end = source.index("async function refreshData", start)
        body = source[start:end]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the fill-form lookup contract test")
        script = f"""
const state = {{
  suppressAutoSearch: false, loadedEntryOriginal: null,
  slotFits: new Map(), deletedSlots: new Map(), slotSources: new Map(),
  similarCandidates: new Map(), dismissedSimilarSlots: new Set(),
  userSelectedSlotSources: new Map(), ftpPreviewLoading: new Map(),
  ftpPreviewBackgroundLoading: new Map(), photoSourcesLoaded: new Set(),
  loadedPhotos: new Map(), backgroundFtpLookupKey: "",
  backgroundFtpLookupRequestId: 0, backgroundFtpLookupTimer: 0,
  photoLoadRequestId: 0,
}};
const fields = Object.fromEntries(
  ["product_id", "name", "type_name", "model", "color1", "color2", "color3", "extra", "ean"]
    .map((name) => [name, {{ value: "" }}])
);
const productForm = {{ elements: fields }};
const formStatus = {{ textContent: "" }};
const window = {{ clearTimeout() {{}} }};
const setTimeout = () => 0;
const handlePimcoreEanInput = () => {{}};
const applyProductFieldSettings = () => {{}};
const updateFieldWarnings = () => {{}};
const formPayload = () => ({{ name: fields.name.value, type_name: fields.type_name.value, model: fields.model.value }});
let cancelled = 0;
const cancelSimilarFileLookup = () => {{ cancelled += 1; }};
const pendingLoads = [];
function loadPhotosForEntry() {{
  const requestId = ++state.photoLoadRequestId;
  state.loadedPhotos.clear();
  let resolve;
  const promise = new Promise((done) => {{
    resolve = () => {{
      if (state.photoLoadRequestId === requestId) state.loadedPhotos.set("02", {{ token: "loaded" }});
      done();
    }};
  }});
  pendingLoads.push({{ requestId, resolve }});
  return promise;
}}
const scans = [];
const startSimilarFileLookup = (options) => scans.push({{
  immediate: options?.immediate === true,
  occupied: Array.from(state.loadedPhotos.keys()),
}});
{body}
(async () => {{
  fillForm({{ name: "Old", type_name: "Desk", model: "A" }}, {{ loadPhotos: true }});
  fillForm({{ name: "New", type_name: "Desk", model: "B" }}, {{ loadPhotos: true }});
  const scansBeforePhotos = scans.length;
  pendingLoads[0].resolve();
  await Promise.resolve();
  await Promise.resolve();
  const scansAfterStalePhotos = scans.length;
  pendingLoads[1].resolve();
  await Promise.resolve();
  await Promise.resolve();
  console.log(JSON.stringify({{ cancelled, scansBeforePhotos, scansAfterStalePhotos, scans }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["cancelled"], 2)
        self.assertEqual(result["scansBeforePhotos"], 0)
        self.assertEqual(result["scansAfterStalePhotos"], 0)
        self.assertEqual(
            result["scans"], [{"immediate": True, "occupied": ["02"]}]
        )

    def test_filling_without_photos_invalidates_an_old_photo_lookup(self) -> None:
        """A completed old photo load must not search for a newly filled entry."""

        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function fillForm")
        end = source.index("async function refreshData", start)
        body = source[start:end]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the fill-form lookup contract test")
        script = f"""
const state = {{
  suppressAutoSearch: false, loadedEntryOriginal: null,
  slotFits: new Map(), deletedSlots: new Map(), slotSources: new Map(),
  similarCandidates: new Map(), dismissedSimilarSlots: new Set(),
  userSelectedSlotSources: new Map(), ftpPreviewLoading: new Map(),
  ftpPreviewBackgroundLoading: new Map(), photoSourcesLoaded: new Set(),
  loadedPhotos: new Map(), backgroundFtpLookupKey: "",
  backgroundFtpLookupRequestId: 0, backgroundFtpLookupTimer: 0,
  photoLoadRequestId: 0,
}};
const fields = Object.fromEntries(
  ["product_id", "name", "type_name", "model", "color1", "color2", "color3", "extra", "ean"]
    .map((name) => [name, {{ value: "" }}])
);
const productForm = {{ elements: fields }};
const formStatus = {{ textContent: "" }};
const window = {{ clearTimeout() {{}} }};
const setTimeout = () => 0;
const handlePimcoreEanInput = () => {{}};
const applyProductFieldSettings = () => {{}};
const updateFieldWarnings = () => {{}};
const formPayload = () => ({{ name: fields.name.value, type_name: fields.type_name.value, model: fields.model.value }});
const cancelSimilarFileLookup = () => {{}};
let resolveOldPhotoLoad;
function loadPhotosForEntry() {{
  const requestId = ++state.photoLoadRequestId;
  return new Promise((resolve) => {{
    resolveOldPhotoLoad = () => {{
      if (state.photoLoadRequestId === requestId) state.loadedPhotos.set("02", {{ token: "old" }});
      resolve();
    }};
  }});
}}
const scans = [];
const startSimilarFileLookup = (options) => scans.push({{
  immediate: options?.immediate === true,
  product: fields.name.value,
  occupied: Array.from(state.loadedPhotos.keys()),
}});
{body}
(async () => {{
  fillForm({{ name: "Old", type_name: "Desk", model: "A" }}, {{ loadPhotos: true }});
  fillForm({{ name: "New", type_name: "Desk", model: "B" }}, {{ loadPhotos: false }});
  const scansBeforeOldPhotoCompletes = scans.length;
  resolveOldPhotoLoad();
  await Promise.resolve();
  await Promise.resolve();
  console.log(JSON.stringify({{ scansBeforeOldPhotoCompletes, scans }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["scansBeforeOldPhotoCompletes"], 1)
        self.assertEqual(
            result["scans"], [{"immediate": True, "product": "New", "occupied": []}]
        )

    def test_request_json_composes_external_abort_with_timeout(self) -> None:
        """An external cancellation signal must not disable the transport deadline."""

        source = APP_JS.read_text(encoding="utf-8")
        request_json = source[
            source.index("async function requestJson") : source.index(
                "function clientFailureFingerprint"
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the request timeout contract test")
        script = f"""
const state = {{ csrfToken: "" }};
const window = {{ setTimeout, clearTimeout, location: {{ href: "" }} }};
const applyClientIdentityHeader = () => {{}};
const applyPanelRequestHeaders = () => {{}};
const signals = [];
function abortError() {{ return Object.assign(new Error("aborted"), {{ name: "AbortError" }}); }}
function fetch(_path, options) {{
  signals.push(options.signal);
  return new Promise((_resolve, reject) => {{
    const fallback = setTimeout(() => reject(new Error("transport still pending")), 40);
    const abort = () => {{ clearTimeout(fallback); reject(abortError()); }};
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener("abort", abort, {{ once: true }});
  }});
}}
{request_json}
(async () => {{
  const timeoutExternal = new AbortController();
  let timeoutMessage = "";
  try {{
    await requestJson("/api/similar-files", {{ signal: timeoutExternal.signal, timeoutMs: 5 }});
  }} catch (error) {{
    timeoutMessage = error.message;
  }}
  const timeoutSignalAborted = signals[0]?.aborted === true;
  const timeoutSignalComposed = signals[0] !== timeoutExternal.signal;

  const cancelledExternal = new AbortController();
  const cancelledRequest = requestJson("/api/similar-files", {{
    signal: cancelledExternal.signal,
    timeoutMs: 100,
  }}).catch((error) => error.name);
  cancelledExternal.abort();
  const externalErrorName = await cancelledRequest;
  console.log(JSON.stringify({{
    timeoutMessage, timeoutSignalAborted, timeoutSignalComposed,
    externalErrorName, externalSignalComposed: signals[1] !== cancelledExternal.signal,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertIn("Backend nie odpowiedzial", result["timeoutMessage"])
        self.assertTrue(result["timeoutSignalAborted"])
        self.assertTrue(result["timeoutSignalComposed"])
        self.assertEqual(result["externalErrorName"], "AbortError")
        self.assertTrue(result["externalSignalComposed"])

    def test_manual_product_search_starts_similar_scan_before_entries_finish(self) -> None:
        """A slow or failed entries lookup must not hold back the forced similar scan."""

        source = APP_JS.read_text(encoding="utf-8")
        search = source[
            source.index("async function searchByProduct") : source.index(
                "let autoSearchTimer", source.index("async function searchByProduct")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the manual product search contract test")
        script = f"""
const formPayload = () => ({{ name: "Desk", type_name: "Table", model: "T1" }});
const formStatus = {{ textContent: "" }};
const renderEntrySelect = () => {{}};
const renderEntryModal = () => {{}};
let rejectEntries;
const requestJson = () => new Promise((_resolve, reject) => {{ rejectEntries = reject; }});
let scans = 0;
const startSimilarFileLookup = (options) => {{ if (options?.immediate) scans += 1; }};
{search}
(async () => {{
  const pendingSearch = searchByProduct();
  const scansWhileEntriesPending = scans;
  rejectEntries(new Error("entries unavailable"));
  let error = "";
  try {{ await pendingSearch; }} catch (caught) {{ error = caught.message; }}
  console.log(JSON.stringify({{ scansWhileEntriesPending, scans, error }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["scansWhileEntriesPending"], 1)
        self.assertEqual(result["scans"], 1)
        self.assertEqual(result["error"], "entries unavailable")

    def test_accepted_similar_image_keeps_the_similar_preview_marker(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function createSlotNode")
        end = source.index("function renderSlot(", start)
        renderer = source[start:end]
        selected_file_start = renderer.index("if (selectedFile) {")
        selected_file_end = renderer.index("} else if (candidate) {", selected_file_start)
        selected_file_branch = renderer[selected_file_start:selected_file_end]

        self.assertIn(
            'selectedSlotSource(slot.prefix, loadedPhoto) === "similar"',
            selected_file_branch,
        )
        self.assertIn(
            'preview.classList.add("has-similar-candidate");',
            selected_file_branch,
        )

    def test_updating_an_accepted_similar_image_restores_the_preview_marker(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function updateSlotPreview")
        end = source.index("function renderSlot(", start)
        updater = source[start:end]
        selected_file_start = updater.index("if (selectedFile) {")
        selected_file_end = updater.index(
            "if (selectedSlotSource(prefix, loadedPhoto) === \"similar\" && candidate?.is_pdf)",
            selected_file_start,
        )
        selected_file_branch = updater[selected_file_start:selected_file_end]

        self.assertIn(
            'selectedSlotSource(prefix, loadedPhoto) === "similar"',
            selected_file_branch,
        )
        self.assertIn(
            'preview.classList.add("has-similar-candidate");',
            selected_file_branch,
        )

    def test_accepting_and_dismissing_a_similar_candidate_preserves_source_semantics(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        accept_start = source.index("function acceptSimilarCandidate")
        accept_end = source.index("function selectedPhotoToken", accept_start)
        accept_body = source[accept_start:accept_end]
        dismiss_start = source.index("function dismissSimilarCandidate")
        dismiss_end = source.index("function acceptSimilarCandidate", dismiss_start)
        dismiss_body = source[dismiss_start:dismiss_end]

        self.assertIn("similar_candidate_id: candidate.id", accept_body)
        self.assertIn('state.slotSources.set(prefix, "similar");', accept_body)
        self.assertIn("state.dismissedSimilarSlots.add(prefix);", dismiss_body)
        self.assertIn("state.similarCandidates.delete(prefix);", dismiss_body)
        self.assertIn('state.slotSources.delete(prefix);', dismiss_body)

    def test_similar_lookup_requires_acceptance_before_its_token_is_serialized(self) -> None:
        """Catches lookup candidates being submitted without explicit acceptance."""

        source = APP_JS.read_text(encoding="utf-8")
        helpers = source[
            source.index("function slotFileItem") : source.index(
                "function slotUploadProgress"
            )
        ]
        accept_start = source.index("function acceptSimilarCandidate")
        accept = source[accept_start : source.index("function pendingSimilarCandidatePrefixes", accept_start)]
        submit_start = source.index("function handleProductSubmitError")
        handler_start = source.index('productForm.addEventListener("submit"')
        submit_support = source[submit_start:handler_start]
        submit_handler = source[handler_start : source.index("function resetCurrentDraft", handler_start)]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar-file submission contract test")
        script = f"""
const submittedForms = [];
let submitHandler = null;
const productForm = {{
  elements: {{}},
  addEventListener(name, handler) {{ if (name === "submit") submitHandler = handler; }},
}};
class FormData {{
  constructor() {{ this.values = new Map(); }}
  delete(key) {{ this.values.delete(key); }}
  set(key, value) {{ this.values.set(key, value); }}
  entries() {{ return this.values.entries(); }}
}}
const state = {{
  slots: [{{ prefix: "01" }}],
  files: new Map(),
  similarCandidates: new Map(),
  dismissedSimilarSlots: new Set(),
  loadedPhotos: new Map(),
  deletedSlots: new Map(),
  slotSources: new Map(),
}};
const clearResult = () => {{}};
const ensureSlotUploadsReady = () => {{}};
const setBusy = () => {{}};
const ensureProductListValues = async () => {{}};
const productFieldsChangedSinceLoad = () => false;
const hasPendingUserChanges = () => false;
const pendingChangedSlotPrefixes = () => new Set();
const isSlotFit = () => true;
const startProcessStatusTicker = () => {{}};
const stopProcessStatusTicker = () => {{}};
const trackProcessJob = () => {{}};
const showQueuedProcess = () => {{}};
const resetCurrentDraft = () => {{}};
const showError = (error) => {{ throw error; }};
const markSlotDeletion = () => {{}};
const renderSlot = () => {{}};
const pendingSimilarCandidatePrefixes = () => state.files.has("01") ? [] : ["01"];
const openSimilarDecisionModal = () => {{}};
const ensureSlotOcrCollection = () => Promise.resolve();
const formStatus = {{ textContent: "" }};
async function requestJson(_url, options) {{
  submittedForms.push(Object.fromEntries(options.body.entries()));
  return {{ job: {{}} }};
}}
{helpers}
{accept}
{submit_support}
{submit_handler}
(async () => {{
  state.similarCandidates.set("01", {{
    id: "candidate-1",
    filename: "5901234567890_01.pdf",
    size_bytes: 12,
    is_pdf: true,
    token: "signed-similar-token",
    url: "/api/file?token=signed-similar-token",
    thumb_url: "/api/thumbnail?token=signed-similar-token",
  }});
  await submitHandler({{ preventDefault() {{}} }});
  const requestsBeforeAcceptance = submittedForms.length;
  const filesBeforeAcceptance = state.files.size;
  acceptSimilarCandidate("01");
  await submitHandler({{ preventDefault() {{}} }});
  const accepted = submittedForms.at(-1);
  console.log(JSON.stringify({{
    filesBeforeAcceptance,
    requestsBeforeAcceptance,
    acceptedToken: accepted.existing_slot_01 || null,
    acceptedName: accepted.existing_slot_name_01 || null,
    browserSlot: accepted.slot_01 || null,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["filesBeforeAcceptance"], 0)
        self.assertEqual(result["requestsBeforeAcceptance"], 0)
        self.assertEqual(result["acceptedToken"], "signed-similar-token")
        self.assertEqual(result["acceptedName"], "5901234567890_01.pdf")
        self.assertIsNone(result["browserSlot"])

    def test_similar_lookup_reserves_occupied_slots_and_reports_current_errors(self) -> None:
        """Catches a lookup that overwrites occupied slots or hides its current error."""

        source = APP_JS.read_text(encoding="utf-8")
        lookup_helpers = source[
            source.index("function similarFileIdentityKey") : source.index(
                "function scheduleSimilarFileLookup", source.index("function similarFileIdentityKey")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar-file lookup contract test")
        script = f"""
const state = {{
  files: new Map([["01", {{ token: "manual" }}]]),
  loadedPhotos: new Map([["02", {{ token: "loaded" }}]]),
  deletedSlots: new Map(),
  slotSources: new Map(),
  similarCandidates: new Map(),
  similarDecisionResults: new Map(),
  dismissedSimilarSlots: new Set(),
  similarFileLookupRequestId: 0,
}};
const formStatus = {{ textContent: "" }};
const formPayload = () => ({{
  name: "Simple Sideboard 100 8S", type_name: "Sideboard", model: "100",
  color1: "WHITE", color2: "", color3: "", extra: "NO-LED",
}});
const normalizedIdentityValue = (value) => String(value || "").trim().toUpperCase();
const renderSlots = () => {{}};
let sentPayload = null;
async function requestJson(_url, options) {{
  sentPayload = JSON.parse(options.body);
  throw new Error("offline");
}}
{lookup_helpers}
(async () => {{
  let thrown = null;
  try {{
    await lookupSimilarFiles();
  }} catch (error) {{
    thrown = error.message;
  }}
  console.log(JSON.stringify({{
    occupied: sentPayload.occupied_prefixes,
    status: formStatus.textContent,
    thrown,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["occupied"], ["01", "02"])
        self.assertIsNone(result["thrown"])
        self.assertIn("Nie udalo sie sprawdzic plikow z podobnych produktow", result["status"])

    def test_similar_lookup_uses_abort_signal_and_ignores_abort_error(self) -> None:
        """A superseded transport must be cancellable without surfacing a user error."""

        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("async function lookupSimilarFiles")
        end = source.index("function scheduleSimilarFileLookup", start)
        lookup = source[start:end]

        self.assertIn("new AbortController()", lookup)
        self.assertIn("signal: controller.signal", lookup)
        self.assertIn('error.name === "AbortError"', lookup)

    def test_photo_load_does_not_schedule_similar_lookup(self) -> None:
        """Photo-source completion must not launch a second similar-file request."""

        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("async function loadPhotosForEntry")
        end = source.index("function fillForm", start)

        self.assertNotIn("scheduleSimilarFileLookup", source[start:end])

    def test_empty_slot_has_search_feedback_and_reduced_motion_css(self) -> None:
        """Only a free slot exposes accessible lookup progress with safe motion fallback."""

        source = APP_JS.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertIn("Automatyczne wyszukiwanie podobnych plikow...", source)
        self.assertIn("similar-searching", source)
        self.assertIn('empty.setAttribute("role", "status")', source)
        self.assertIn('empty.setAttribute("aria-live", "polite")', source)
        self.assertRegex(
            css,
            re.compile(
                r"\.slot-card\.similar-searching \.slot-preview\s*\{[^}]*border:\s*2px dashed",
                re.DOTALL,
            ),
        )
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertRegex(
            css,
            re.compile(
                r"@media \(prefers-reduced-motion: reduce\)\s*\{.*?"
                r"\.slot-card\.similar-searching \.slot-preview\s*\{[^}]*animation:\s*none",
                re.DOTALL,
            ),
        )

    def test_late_similar_response_cannot_replace_new_lookup_results(self) -> None:
        """An aborted predecessor resolving late cannot render over the current lookup."""

        source = APP_JS.read_text(encoding="utf-8")
        lookup_helpers = source[
            source.index("function similarFileIdentityKey") : source.index(
                "function scheduleSimilarFileLookup", source.index("function similarFileIdentityKey")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the stale similar-file lookup contract test")
        script = f"""
const requests = [];
let fields = {{
  name: "Old Product", type_name: "Sideboard", model: "100",
  color1: "WHITE", color2: "", color3: "", extra: "NO-LED",
}};
const state = {{
  files: new Map(), loadedPhotos: new Map(), deletedSlots: new Map(),
  slotSources: new Map(), similarCandidates: new Map(),
  similarDecisionResults: new Map(), dismissedSimilarSlots: new Set(),
  similarFileLookupRequestId: 0, similarFileLookupController: null,
  similarFileLookupInFlight: false, similarFileLookupStartedAt: 0,
  similarFileLookupKey: "",
}};
const formStatus = {{ textContent: "" }};
const formPayload = () => ({{ ...fields }});
const normalizedIdentityValue = (value) => String(value || "").trim().toUpperCase();
let renders = 0;
const renderSlots = () => {{ renders += 1; }};
function requestJson(_url, options) {{
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {{
    resolve = resolvePromise;
    reject = rejectPromise;
  }});
  requests.push({{ options, resolve, reject }});
  return promise;
}}
{lookup_helpers}
(async () => {{
  const oldLookup = lookupSimilarFiles();
  fields = {{ ...fields, name: "New Product", color1: "BLACK" }};
  const newLookup = lookupSimilarFiles();
  requests[1].resolve({{ candidates: [{{ target_prefix: "02", id: "new" }}] }});
  await newLookup;
  requests[0].resolve({{ candidates: [{{ target_prefix: "01", id: "old" }}] }});
  await oldLookup;
  console.log(JSON.stringify({{
    aborted: requests[0].options.signal?.aborted === true,
    candidates: Array.from(state.similarCandidates.values()).map((candidate) => candidate.id),
    status: formStatus.textContent,
    renders,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertTrue(result["aborted"])
        self.assertEqual(result["candidates"], ["new"])
        self.assertEqual(result["status"], "")
        self.assertGreater(result["renders"], 0)

    def test_invalid_similar_identity_retains_accepted_pdf_preview_metadata(self) -> None:
        """Clearing an ineligible lookup must remove pending candidates, not an accepted PDF."""

        source = APP_JS.read_text(encoding="utf-8")
        lookup_helpers = source[
            source.index("function similarFileIdentityKey") : source.index(
                "function scheduleSimilarFileLookup", source.index("function similarFileIdentityKey")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the accepted PDF identity contract test")
        script = f"""
const acceptedPdf = {{
  id: "accepted-pdf", filename: "instruction.pdf", is_pdf: true,
  token: "signed-pdf", url: "/api/file?token=signed-pdf",
  thumb_url: "/api/thumbnail?token=signed-pdf",
}};
const state = {{
  files: new Map([["01", {{ similar_candidate_id: "accepted-pdf", token: "signed-pdf" }}]]),
  loadedPhotos: new Map(), deletedSlots: new Map(),
  slotSources: new Map([["01", "similar"]]),
  similarCandidates: new Map([
    ["01", acceptedPdf],
    ["02", {{ id: "pending", filename: "pending.jpg", is_pdf: false }}],
  ]),
  dismissedSimilarSlots: new Set(), similarFileLookupTimer: 0,
  similarFileLookupRequestId: 0, similarFileLookupController: null,
  similarFileLookupInFlight: false, similarFileLookupStartedAt: 0,
  similarFileLookupKey: "",
}};
const formStatus = {{ textContent: "" }};
const formPayload = () => ({{
  name: "Product", type_name: "Sideboard", model: "",
  color1: "WHITE", color2: "", color3: "", extra: "",
}});
const normalizedIdentityValue = (value) => String(value || "").trim().toUpperCase();
const window = {{ clearTimeout: () => {{}} }};
let renders = 0;
let requests = 0;
const renderSlots = () => {{ renders += 1; }};
const requestJson = () => {{ requests += 1; throw new Error("request must not start"); }};
{lookup_helpers}
(async () => {{
  await lookupSimilarFiles();
  const retained = state.similarCandidates.get("01");
  console.log(JSON.stringify({{
    retainedId: retained?.id || null,
    retainedPdf: retained?.is_pdf === true,
    retainedUrl: retained?.url || null,
    pendingRetained: state.similarCandidates.has("02"),
    requests,
    renders,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["retainedId"], "accepted-pdf")
        self.assertTrue(result["retainedPdf"])
        self.assertEqual(result["retainedUrl"], "/api/file?token=signed-pdf")
        self.assertFalse(result["pendingRetained"])
        self.assertEqual(result["requests"], 0)
        self.assertGreater(result["renders"], 0)

    def test_similar_candidate_image_preview_uses_its_signed_thumbnail(self) -> None:
        """Catches a pending candidate deriving its thumbnail from an inactive slot source."""

        source = APP_JS.read_text(encoding="utf-8")
        renderer = source[
            source.index("function renderSimilarCandidatePreview") : source.index(
                "function clearSlotAssignment", source.index("function renderSimilarCandidatePreview")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar candidate preview contract")
        script = f"""
const candidate = {{
  filename: "candidate.jpg", is_pdf: false,
  thumb_url: "/api/thumbnail?token=signed-thumbnail",
  url: "/api/file?token=signed-file",
}};
const preview = {{ classList: {{ add() {{}} }} }};
const previewImage = {{ src: "", addEventListener() {{}} }};
const empty = {{ textContent: "" }};
const similarCandidateForSlot = () => candidate;
const thumbnailUrl = () => "";
{renderer}
renderSimilarCandidatePreview("01", preview, previewImage, empty);
console.log(JSON.stringify({{ src: previewImage.src }}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(completed.stdout)["src"], "/api/thumbnail?token=signed-thumbnail")

    def test_manual_slot_file_starts_immediate_similar_lookup_with_new_occupied_slot(self) -> None:
        """Manual assignment must reallocate candidates immediately using the new occupancy."""

        source = APP_JS.read_text(encoding="utf-8")
        set_slot_file = source[
            source.index("function setSlotFile") : source.index("function getSlotAssignment", source.index("function setSlotFile"))
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar candidate reallocation contract")
        script = f"""
const state = {{
  files: new Map(), loadedPhotos: new Map(), slotSources: new Map(),
  userSelectedSlotSources: new Map(), similarCandidates: new Map(),
}};
const formStatus = {{ textContent: "" }};
const uploadFileValidationError = () => "";
const bumpSlotRevision = () => {{}};
const markSlotDeletion = () => {{}};
const revokeFilePreviewUrl = () => {{}};
const isProvisionalSlotPlacement = () => false;
const createSlotFileUpload = (_prefix, file) => ({{ file }});
const dismissSimilarCandidate = () => {{}};
const updateSubmitButtonState = () => {{}};
const uploadSlotFile = () => {{}};
const slotAssignmentToken = () => "";
const recordOcrActivity = () => {{}};
let immediateRefreshes = 0;
let debouncedRefreshes = 0;
let occupiedAtRefresh = [];
const scheduleSimilarFileLookup = () => {{ debouncedRefreshes += 1; }};
const startSimilarFileLookup = (options) => {{
  if (options?.immediate) immediateRefreshes += 1;
  occupiedAtRefresh = Array.from(state.files.keys()).sort();
}};
{set_slot_file}
setSlotFile("01", {{ name: "manual.jpg" }});
console.log(JSON.stringify({{ immediateRefreshes, debouncedRefreshes, occupiedAtRefresh }}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["immediateRefreshes"], 1)
        self.assertEqual(result["debouncedRefreshes"], 0)
        self.assertEqual(result["occupiedAtRefresh"], ["01"])

    def test_similar_controls_are_compact_and_slot_local(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        settings_start = source.index("function renderSettingsSlots")
        settings_end = source.index("function renderSettingsUsers", settings_start)
        settings = source[settings_start:settings_end]
        slot_start = source.index("function createSlotNode")
        slot_end = source.index("function renderSlot(", slot_start)
        slots = source[slot_start:slot_end]

        self.assertIn('similarInput.name = "similar_file_slot_prefixes";', settings)
        self.assertNotIn('settingsFieldGroup("Podobne produkty"', settings)
        self.assertIn('["similar", "POD"', source)
        self.assertIn('acceptButton.textContent = "✓";', slots)
        self.assertIn('rejectButton.textContent = "×";', slots)

    def test_similar_decision_modal_exposes_preview_list_and_blocking_actions(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")

        for identifier in (
            'id="similarDecisionModal"',
            'id="similarDecisionList"',
            'id="similarDecisionRejectAllButton"',
            'id="similarDecisionContinueButton"',
        ):
            self.assertIn(identifier, html)
        self.assertIn('role="dialog"', html)
        self.assertIn('aria-modal="true"', html)
        self.assertIn(".slot-card.slot-similar-pending", css)
        self.assertIn("@keyframes slot-similar-pending-pulse", css)

    def test_pending_similar_candidate_renders_its_thumbnail_without_selecting_pod(self) -> None:
        """Catches an empty slot hiding a suggestion until the POD badge is clicked."""

        source = APP_JS.read_text(encoding="utf-8")
        update_start = source.index("function updateSlotPreview")
        update_end = source.index("function createSlotNode", update_start)
        update_slot_preview = source[update_start:update_end]
        helpers = source[
            source.index("function defaultSlotSource") : source.index(
                "function selectedPhotoToken", source.index("function defaultSlotSource")
            )
        ]
        candidate_preview = source[
            source.index("function renderSimilarCandidatePreview") : source.index(
                "function clearSlotAssignment", source.index("function renderSimilarCandidatePreview")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar preview contract test")
        script = f"""
const state = {{
  files: new Map(),
      loadedPhotos: new Map(),
      slotSources: new Map(),
      similarCandidates: new Map(),
      similarDecisionResults: new Map(),
      dismissedSimilarSlots: new Set(),
  deletedSlots: new Map(),
  ftpPreviewLoading: new Set(),
  ftpPreviewBackgroundLoading: new Set(),
  slotFits: new Map(),
}};
const classList = () => {{
  const values = new Set();
  return {{
    add: (...names) => names.forEach((name) => values.add(name)),
    remove: (...names) => names.forEach((name) => values.delete(name)),
    contains: (name) => values.has(name),
  }};
}};
const previewImage = {{
  src: "",
  addEventListener: () => {{}},
  removeAttribute: () => {{}},
}};
const empty = {{
  textContent: "",
  setAttribute: () => {{}},
  removeAttribute: () => {{}},
}};
const preview = {{
  classList: classList(),
  querySelector: (selector) => {{
    if (selector === "img") return previewImage;
    if (selector === ".slot-empty") return empty;
    return null;
  }},
  appendChild: () => {{}},
}};
const card = {{
  dataset: {{}},
  classList: {{ toggle: () => {{}} }},
  querySelector: (selector) => {{
    if (selector === ".slot-meta span") return {{ textContent: "" }};
    if (selector === ".slot-preview") return preview;
    if (selector === ".slot-fit-button") return null;
    return null;
  }},
  querySelectorAll: () => [],
}};
const slotGrid = {{ querySelector: () => card }};
const isSlotFit = () => false;
const slotStatusText = () => "Brak pliku";
const isPhotoSourceLoading = () => false;
const sourceLoadingTitle = () => "";
const renderSlots = () => {{ throw new Error("slot should already be rendered"); }};
const renderSlotUploadOverlay = () => {{}};
const renderSelectedFilePreview = () => {{}};
const isFileImageLike = () => false;
const document = {{ createElement: () => ({{}}) }};
{helpers}
{candidate_preview}
{update_slot_preview}
state.similarCandidates.set("01", {{
  filename: "candidate.jpg",
  thumb_url: "/api/thumbnail/candidate.jpg",
  url: "/api/file/candidate.jpg",
  is_pdf: false,
}});
updateSlotPreview("01");
console.log(JSON.stringify({{
  source: previewImage.src,
  marked: preview.classList.contains("has-similar-candidate"),
}}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["source"], "/api/thumbnail/candidate.jpg")
        self.assertTrue(result["marked"])

    def test_decision_modal_accept_and_reject_resolve_only_chosen_slots(self) -> None:
        """Catches modal controls that do not apply the existing per-slot decision paths."""

        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("function pendingSimilarCandidatePrefixes()", source)
        self.assertIn("function renderSimilarDecisionModal()", source)
        helpers = source[
            source.index("function defaultSlotSource") : source.index(
                "async function ensureSlotOcrCollection", source.index("function defaultSlotSource")
            )
        ]
        accept = source[
            source.index("function acceptSimilarCandidate") : source.index(
                "function pendingSimilarCandidatePrefixes",
                source.index("function acceptSimilarCandidate"),
            )
        ]
        decision_helpers = source[
            source.index("function pendingSimilarCandidatePrefixes") : source.index(
                "function selectedPhotoToken", source.index("function pendingSimilarCandidatePrefixes")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar decision modal contract test")
        script = f"""
class Element {{
  constructor() {{
    this.children = [];
    this.className = "";
    this.textContent = "";
    this.dataset = {{}};
    this.listeners = {{}};
    this.classList = {{ add: () => {{}}, remove: () => {{}} }};
  }}
  append(...items) {{ this.children.push(...items); }}
  appendChild(item) {{ this.children.push(item); return item; }}
  replaceChildren(...items) {{ this.children = items; }}
  addEventListener(name, listener) {{ this.listeners[name] = listener; }}
  setAttribute() {{}}
}}
const state = {{
  slots: [{{ prefix: "01", label: "Instrukcja 1" }}, {{ prefix: "02", label: "Instrukcja 2" }}],
  files: new Map(),
  loadedPhotos: new Map(),
  slotSources: new Map(),
  similarCandidates: new Map(),
  similarDecisionResults: new Map(),
  dismissedSimilarSlots: new Set(),
  deletedSlots: new Map(),
  userSelectedSlotSources: new Set(),
}};
const similarDecisionList = new Element();
const similarDecisionContinueButton = new Element();
const similarDecisionRejectAllButton = new Element();
const similarDecisionModal = new Element();
const document = {{ createElement: () => new Element() }};
const markSlotDeletion = () => {{}};
const renderSlot = () => {{}};
const ensureSlotOcrCollection = () => Promise.resolve();
const formStatus = {{ textContent: "" }};
{helpers}
{accept}
{decision_helpers}
state.similarCandidates.set("01", {{ id: "one", filename: "one.jpg", thumb_url: "/thumb/one", source_color: "Czarny" }});
state.similarCandidates.set("02", {{ id: "two", filename: "two.pdf", url: "/file/two", is_pdf: true, source_color: "Biały" }});
renderSimilarDecisionModal();
similarDecisionList.children[0].children.at(-1).children[0].listeners.click({{ preventDefault() {{}} }});
similarDecisionList.children[1].children.at(-1).children[1].listeners.click({{ preventDefault() {{}} }});
console.log(JSON.stringify({{
  accepted: state.files.get("01")?.similar_candidate_id || null,
  rejected: state.dismissedSimilarSlots.has("02"),
  pending: pendingSimilarCandidatePrefixes(),
  continueDisabled: similarDecisionContinueButton.disabled,
  acceptedState: similarDecisionList.children[0].children.at(-1).children[0].textContent,
  rejectedState: similarDecisionList.children[1].children.at(-1).children[0].textContent,
}}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["accepted"], "one")
        self.assertTrue(result["rejected"])
        self.assertEqual(result["pending"], [])
        self.assertFalse(result["continueDisabled"])
        self.assertEqual(result["acceptedState"], "Zachowany")
        self.assertEqual(result["rejectedState"], "Odrzucony")

    def test_pending_similar_candidates_block_submit_until_all_are_decided(self) -> None:
        """A pending suggestion must open the decision modal before any submit work starts."""

        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("async function submitProductForm()", source)
        handler_start = source.index('productForm.addEventListener("submit",')
        handler_end = source.index("function resetCurrentDraft", handler_start)
        submit_handler = source[handler_start:handler_end]
        self.assertIn("pendingSimilarCandidatePrefixes()", submit_handler)
        self.assertIn("openSimilarDecisionModal()", submit_handler)
        self.assertIn("submitProductForm()", submit_handler)
        self.assertNotIn('requestJson("/api/process/background"', submit_handler)

        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar submit gate contract test")
        script = f"""
let submitHandler;
let pending = ["01"];
let opened = 0;
let submitted = 0;
const productForm = {{ addEventListener: (_name, handler) => {{ submitHandler = handler; }} }};
const pendingSimilarCandidatePrefixes = () => pending;
const openSimilarDecisionModal = () => {{ opened += 1; }};
const submitProductForm = () => {{ submitted += 1; return Promise.resolve(); }};
const handleProductSubmitError = () => {{ throw new Error("unexpected submit failure"); }};
{submit_handler}
(async () => {{
  await submitHandler({{ preventDefault() {{}} }});
  pending = [];
  await submitHandler({{ preventDefault() {{}} }});
  console.log(JSON.stringify({{ opened, submitted }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(completed.stdout), {"opened": 1, "submitted": 1})

    def test_reject_all_enables_continue_without_submitting_similar_token(self) -> None:
        """Bulk rejection leaves candidates out of files, then continues through the normal submit path."""

        source = APP_JS.read_text(encoding="utf-8")
        wiring_start = source.index("similarDecisionRejectAllButton?.addEventListener")
        wiring_end = source.index(
            'document.querySelectorAll("[data-close-similar-decision]")', wiring_start
        )
        wiring = source[wiring_start:wiring_end]
        self.assertIn("dismissSimilarCandidate(prefix)", wiring)
        self.assertIn("similarDecisionContinueButton?.addEventListener", wiring)
        self.assertIn("closeSimilarDecisionModal()", wiring)
        self.assertIn("submitProductForm()", wiring)
        self.assertIn('document.querySelectorAll("[data-close-similar-decision]")', source)
        self.assertIn('button.addEventListener("click", closeSimilarDecisionModal)', source)

        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the similar decision action contract test")
        script = f"""
const listeners = {{}};
const similarDecisionRejectAllButton = {{ addEventListener: (name, listener) => {{ listeners.rejectAll = listener; }} }};
const similarDecisionContinueButton = {{ addEventListener: (name, listener) => {{ listeners.continue = listener; }} }};
const pending = new Set(["01", "02"]);
const state = {{ files: new Map() }};
let closed = 0;
let submitted = 0;
let rendered = 0;
const pendingSimilarCandidatePrefixes = () => [...pending];
const dismissSimilarCandidate = (prefix) => pending.delete(prefix);
const renderSlot = () => {{ rendered += 1; }};
const renderSimilarDecisionModal = () => {{ rendered += 1; }};
const closeSimilarDecisionModal = () => {{ closed += 1; }};
const submitProductForm = () => {{ submitted += 1; return Promise.resolve(); }};
const handleProductSubmitError = () => {{ throw new Error("unexpected submit failure"); }};
{wiring}
(async () => {{
  listeners.rejectAll();
  listeners.continue();
  await Promise.resolve();
  console.log(JSON.stringify({{
    pending: pendingSimilarCandidatePrefixes(),
    serializedSimilar: [...state.files.values()].some((item) => item.similar_candidate_id),
    closed,
    submitted,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["pending"], [])
        self.assertFalse(result["serializedSimilar"])
        self.assertEqual(result["closed"], 1)
        self.assertEqual(result["submitted"], 1)

    def test_submit_rechecks_candidates_added_while_lists_are_prepared(self) -> None:
        """Catches a late lookup candidate being serialized without a decision."""

        source = APP_JS.read_text(encoding="utf-8")
        submit_start = source.index("async function submitProductForm()")
        submit_end = source.index('productForm.addEventListener("submit",', submit_start)
        submit_product = source[submit_start:submit_end]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the late similar candidate contract test")
        script = f"""
let modalOpens = 0;
let requests = 0;
const state = {{ similarCandidates: new Map([['01', {{ token: 'late-token' }}]]) }};
const clearResult = () => {{}};
const ensureSlotUploadsReady = () => {{}};
const setBusy = () => {{}};
const ensureProductListValues = async () => {{}};
const pendingSimilarCandidatePrefixes = () => [...state.similarCandidates.keys()];
const openSimilarDecisionModal = () => {{ modalOpens += 1; }};
const handleProductSubmitError = () => {{}};
const productFieldsChangedSinceLoad = () => false;
const hasPendingUserChanges = () => true;
const pendingChangedSlotPrefixes = () => new Set();
const FormData = class {{}};
const requestJson = () => {{ requests += 1; return Promise.resolve({{}}); }};
const recordOcrActivity = () => {{}};
{submit_product}
(async () => {{
  await submitProductForm();
  console.log(JSON.stringify({{ modalOpens, requests }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script], check=True, capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(json.loads(completed.stdout), {"modalOpens": 1, "requests": 0})

    def test_similar_decision_modal_inerts_background_and_focuses_close_control(self) -> None:
        """Catches an aria-modal dialog that still permits background slot actions."""

        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("function setSimilarDecisionBackgroundInert()", source)
        self.assertIn("function restoreSimilarDecisionBackground()", source)
        self.assertIn("similarDecisionCloseButton?.focus()", source)

    def test_selected_similar_slot_uses_its_edited_id_when_settings_are_saved(self) -> None:
        """Catches an enabled per-slot checkbox retaining the ID it had at render time."""

        source = APP_JS.read_text(encoding="utf-8")
        start = source.find("function selectedSimilarSlotPrefixes")
        self.assertNotEqual(start, -1, "settings need a row-aware selected-prefix helper")
        end = source.find("function renderSettingsSlots", start)
        helper = source[start:end]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the slot settings contract test")
        script = f"""
const rows = [
  {{ querySelector(selector) {{
    if (selector === '[name="similar_file_slot_prefixes"]') return {{ checked: true }};
    if (selector === '[name="prefix"]') return {{ value: "15" }};
    return null;
  }} }},
];
{helper}
console.log(JSON.stringify(selectedSimilarSlotPrefixes(rows)));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(completed.stdout), ["15"])

    def test_list_usage_modal_opens_the_selected_blocking_product(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function renderListUsageModal")
        end = source.index("const trackedProductFields", start)
        renderer = source[start:end]

        self.assertIn('button.textContent = "Wczytaj"', renderer)
        self.assertIn("fillForm(item, { loadPhotos: true });", renderer)
        self.assertIn("closeModals();", renderer)
        self.assertIn("row.append(text, button);", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_header_stacks_latency_above_compact_system_status(self) -> None:
        markup = INDEX_HTML.read_text(encoding="utf-8")
        css = (ROOT / "picsyncra" / "web" / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        source = APP_JS.read_text(encoding="utf-8")

        stack_start = markup.index('class="header-status-stack"')
        location_start = markup.index('class="header-location"')
        stack_source = markup[stack_start:location_start]

        self.assertLess(markup.index("PicSyncra Web"), stack_start)
        self.assertLess(stack_start, location_start)
        self.assertLess(
            stack_source.index('id="backendHealthStatus"'),
            stack_source.index('id="resourceStatus"'),
        )
        self.assertIn(".header-status-stack", css)
        self.assertIn(".header-location #serverInfo", css)
        self.assertIn("grid-template-columns: minmax(150px, max-content) auto", css)
        self.assertIn(
            "`System: ${formatPercent(host.cpu_percent)}/${formatPercent(host.memory_percent)}/${formatPercent(host.disk_busy_percent)}`",
            source,
        )

    def test_web_ui_uses_the_central_panel_timestamp_formatter(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function selectedPanelTimeZone", source)
        self.assertIn("function coercePanelDate", source)
        self.assertIn("function formatPanelTimestamp", source)
        self.assertIn("timeZone: selectedPanelTimeZone()", source)
        self.assertIn('timeZone: "UTC"', source)
        self.assertNotIn("new Date(eventTime).toLocaleTimeString()", source)
        self.assertNotIn("new Date(Number(item.started_at) * 1000).toLocaleString()", source)

    def test_panel_timestamp_formatter_runtime_contract(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        formatter = source[
            source.index("function selectedPanelTimeZone") : source.index(
                "const SQLITE_BACKUP_DAYS"
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the browser formatter contract test")
        script = f"""
const state = {{ settings: {{ web_display: {{ time_zone: "Europe/Warsaw" }} }} }};
{formatter}
const winter = formatPanelTimestamp("2026-01-15T12:00:00Z");
const summer = formatPanelTimestamp("2026-07-15T12:00:00Z");
state.settings.web_display.time_zone = "Invalid/Time_Zone";
const fallback = formatPanelTimestamp("2026-01-15T12:00:00Z");
const impossible = formatPanelTimestamp("2026-02-31T12:00:00Z");
const ambiguousNumber = coercePanelDate(946684800);
const seconds = coercePanelDate(946684800, {{ epochUnit: "seconds" }})?.toISOString();
const historicalMilliseconds = coercePanelDate(946684800000, {{ epochUnit: "milliseconds" }})?.toISOString();
state.settings.web_display.time_zone = "UTC";
const historySeconds = formatPanelTimestamp(1773576000, {{ epochUnit: "seconds" }});
console.log(JSON.stringify({{
  winter,
  summer,
  fallback,
  impossible,
  ambiguousNumber,
  seconds,
  historicalMilliseconds,
  historySeconds,
}}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertRegex(result["winter"], r"13:00:00.*CET")
        self.assertRegex(result["summer"], r"14:00:00.*CEST")
        self.assertRegex(result["fallback"], r"12:00:00.*UTC")
        self.assertEqual(result["impossible"], "Brak danych")
        self.assertIsNone(result["ambiguousNumber"])
        self.assertEqual(result["seconds"], "2000-01-01T00:00:00.000Z")
        self.assertEqual(
            result["historicalMilliseconds"], "2000-01-01T00:00:00.000Z"
        )
        self.assertNotEqual(result["historySeconds"], "Brak danych")
        self.assertRegex(result["historySeconds"], r"12:00:00.*UTC")

    def test_time_zone_rerender_preserves_offline_health_status_and_reformats_details(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        formatter = source[
            source.index("function selectedPanelTimeZone") : source.index(
                "const SQLITE_BACKUP_DAYS"
            )
        ]
        normalized_health = source[
            source.index("const HEALTH_COMPONENT_LABELS") : source.index(
                "function canonicalHealthTimestamp"
            )
        ]
        health_rendering = source[
            source.index("function canonicalHealthTimestamp") : source.index(
                "function resourceUnavailableText"
            )
        ]
        health_level = source[
            source.index("function healthLevel") : source.index(
                "async function pollBackendHealth"
            )
        ]
        health_poll = source[
            source.index("async function pollBackendHealth") : source.index(
                "function setBackendHealthDetailsExpanded"
            )
        ]
        self.assertIn("async function fetchRuntimeStatus()", source)
        self.assertIn('requestJson("/api/runtime-status")', source)
        self.assertIn("new PicSyncra.RuntimeStatusPoller", source)
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the browser health rerender contract test")
        script = f"""
const state = {{ settings: {{ web_display: {{ time_zone: "UTC" }} }}, lastHealthPayload: null }};
const backendHealthStatus = {{ dataset: {{}}, textContent: "" }};
const backendHealthText = {{ textContent: "" }};
function makeNode() {{
  return {{
    dataset: {{}},
    textContent: "",
    children: [],
    append(...items) {{ this.children.push(...items); }},
  }};
}}
const backendHealthDetailsList = {{
  children: [],
  replaceChildren(...items) {{ this.children = items; }},
}};
const document = {{ hidden: false, createElement: () => makeNode() }};
const window = {{ clearTimeout: () => {{}}, setTimeout: () => 0 }};
let healthNow = 0;
const performance = {{ now: () => (healthNow += 25) }};
const HEALTH_OFFLINE_FAILURES = 3;
const HEALTH_CRITICAL_MS = 1000;
const HEALTH_SLOW_MS = 300;
let healthFailures = 0;
let healthPollTimer = 0;
let healthPollGeneration = 0;
let healthPollController = null;
let lastSuccessfulHealthComponents = {{}};
const healthSamples = [];
const renderResourceStatus = () => {{}};
const scheduleBackendHealthPoll = () => {{}};
{formatter}
{normalized_health}
{health_rendering}
{health_level}
{health_poll}
const successfulComponents = {{
  backend: {{ status: "online", observed_at: "2026-01-15T12:00:00Z" }},
  sqlite: {{ status: "online", observed_at: "2026-01-15T12:00:00Z" }},
}};
const healthResponses = [
  {{ ok: true, components: successfulComponents, resources: {{}}, time: "2026-01-15T12:00:00Z" }},
  new Error("offline"),
  new Error("offline"),
  new Error("offline"),
];
async function requestJson() {{
  const next = healthResponses.shift();
  if (next instanceof Error) throw next;
  return next;
}}
(async () => {{
  await pollBackendHealth();
  await pollBackendHealth();
  await pollBackendHealth();
  await pollBackendHealth();
  state.settings.web_display.time_zone = "Europe/Warsaw";
  rerenderCachedHealthDetails();
  const detailText = backendHealthDetailsList.children
    .map((item) => item.children.map((child) => child.textContent).join(":"))
    .join("|");
  console.log(JSON.stringify({{
    level: backendHealthStatus.dataset.level,
    label: backendHealthText.textContent,
    detailText,
  }}));
}})();
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["level"], "offline")
        self.assertEqual(result["label"], "Offline")
        self.assertRegex(result["detailText"], r"13:00:00.*CET")

    def test_all_visible_panel_timestamps_use_the_central_formatter(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        compact_source = re.sub(r"\s+", " ", source)

        iso_calls = [
            "formatPanelTimestamp(payload.checked_at)",
            "formatPanelTimestamp(release.published_at)",
            "formatPanelTimestamp(state.fileIndex?.generated_at)",
            "formatPanelTimestamp(event.created_at)",
            "formatPanelTimestamp(delivery.updated_at || delivery.created_at)",
            "formatPanelTimestamp(incident.last_seen_at || incident.first_seen_at)",
            "formatPanelTimestamp(job.started_at)",
            "formatPanelTimestamp(job.finished_at)",
            "formatPanelTimestamp(observedAt)",
            "formatPanelTimestamp(serverTime)",
            "formatPanelTimestamp(detector.last_trigger_at)",
            "formatPanelTimestamp(resources.observed_at)",
            "formatPanelTimestamp(item.created_at)",
            "formatPanelTimestamp(status.expires_at)",
            "formatPanelTimestamp(status.last_checked_at)",
            "formatPanelTimestamp(status.last_success_at)",
        ]
        for call in iso_calls:
            self.assertIn(call, source)

        epoch_second_calls = [
            "formatPanelTimestamp(user.last_seen_epoch, { epochUnit: \"seconds\" })",
            "formatPanelTimestamp(item.started_at, { epochUnit: \"seconds\" })",
            'formatPanelTimestamp(event.timestamp, { date: false, epochUnit: "seconds", })',
            "formatPanelTimestamp(user.lock_expires_ts, { epochUnit: \"seconds\" })",
            'formatPanelTimestamp(user.last_failed_login_ts, { epochUnit: "seconds", })',
            'formatPanelTimestamp(user.extension_token_last_used_ts, { epochUnit: "seconds", })',
        ]
        for call in epoch_second_calls:
            self.assertIn(call, compact_source)
        self.assertGreaterEqual(
            compact_source.count(
                'formatPanelTimestamp(item.ts || item.created_at, { epochUnit: "seconds", })'
            ),
            3,
        )
        self.assertIn(
            'formatPanelTimestamp( group.latest_ts, { epochUnit: "seconds" } )',
            compact_source,
        )

        self.assertIn("formatDuration(payload.total_ms || 0)", source)
        self.assertIn("formatHistoryDuration(file.elapsed_ms)", source)
        self.assertNotRegex(source, r"\buser\.last_seen(?!_epoch)\b")
        self.assertNotRegex(source, r"\.toLocale(?:Date|Time)?String\(")
        for legacy_field in (
            "user.lock_expires_at",
            "user.last_failed_login_at",
            "user.extension_token_last_used_at",
        ):
            self.assertNotIn(legacy_field, source)

        visible_renderers = (
            "activeUserLastSeenLabel",
            "renderGithubStatus",
            "renderHistoryTiming",
            "renderHistoryChanges",
            "renderHistoryDetails",
            "renderHistory",
            "renderLogEvent",
            "renderResourceDetails",
            "renderPimcoreLiveEvents",
            "renderPimcoreHistory",
            "renderEntraExpiryStatus",
            "renderSettingsUsers",
        )
        for name in visible_renderers:
            start = source.index(f"function {name}(")
            match = re.search(r"\n(?:async )?function ", source[start + 1 :])
            end = len(source) if match is None else start + 1 + match.start()
            renderer = source[start:end]
            self.assertIn(
                "formatPanelTimestamp(",
                renderer,
                f"{name} must route visible instants through the central formatter",
            )

    def test_global_time_zone_field_uses_the_server_catalog_and_rerenders(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('requestJson("/api/settings/time-zones")', source)
        self.assertIn('input.type = "search"', source)
        self.assertIn('datalist.id = "panelTimeZoneCatalog"', source)
        self.assertIn("state.panelTimeZones.includes(input.value)", source)
        self.assertIn("web_display: {", source)
        self.assertIn('time_zone: data.get("web_display_time_zone")', source)
        self.assertIn("rerenderPanelTimestampViews()", source)

        rerender_start = source.index("function rerenderPanelTimestampViews")
        rerender_end = source.index("function settingsSaveButton", rerender_start)
        rerender = source[rerender_start:rerender_end]
        for call in (
            "renderActiveUsersPresence(",
            "renderHistoryTiming(state.historyTimingItem, { open: false })",
            "renderHistoryChanges(state.historyChangesItem, { open: false })",
            "rerenderHistoryDetailTimestamps()",
            "renderPimcoreLiveEvents()",
        ):
            self.assertIn(call, rerender)
        self.assertNotIn("renderHistoryDetails(", rerender)
        detail_refresh_start = source.index("function rerenderHistoryDetailTimestamps")
        detail_refresh_end = source.index("function renderHistoryDetails", detail_refresh_start)
        detail_refresh = source[detail_refresh_start:detail_refresh_end]
        self.assertIn('querySelectorAll("[data-history-item-index]")', detail_refresh)
        self.assertIn("meta.textContent =", detail_refresh)
        self.assertNotIn("historyDetailOutput.textContent", detail_refresh)
        self.assertNotIn("replaceChildren", detail_refresh)

    def test_mail_settings_tab_has_safe_secrets_and_responsive_channel_cards(self) -> None:
        html = _parse(INDEX_HTML)
        source = APP_JS.read_text(encoding="utf-8")
        css = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertTrue(html.has_tag("button", **{"data-settings-tab": "mail"}))
        mail_start = source.index("function renderSettingsMail()")
        mail_end = source.index("function renderSettingsSlots", mail_start)
        mail_source = source[mail_start:mail_end]
        self.assertIn('type: "password"', mail_source)
        self.assertIn("email.entra?.client_secret_set", mail_source)
        self.assertIn("email.smtp?.password_set", mail_source)
        self.assertNotIn("email.entra?.client_secret ||", mail_source)
        self.assertNotIn("email.smtp?.password ||", mail_source)
        self.assertIn("client_secret: data.get(\"email_entra_client_secret\")", mail_source)
        self.assertIn("password: data.get(\"email_smtp_password\")", mail_source)
        self.assertIn('security !== "none"', mail_source)
        self.assertIn("Nie szyfruje polaczenia", mail_source)
        self.assertIn("testButton.disabled = true", mail_source)
        self.assertIn("testButton.disabled = false", mail_source)
        self.assertIn("result.used_channel", source)
        self.assertIn("result.attempts", source)
        self.assertIn("error.payload = payload", source)
        recipients_start = source.index("function splitEmailRecipients")
        recipients_end = source.index("const MAIL_SEVERITY_RULES", recipients_start)
        recipients_source = source[recipients_start:recipients_end]
        self.assertIn("new Set()", recipients_source)
        self.assertIn("toLowerCase()", recipients_source)
        self.assertIn("seen.has", recipients_source)
        self.assertIn(".mail-channel-grid", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        responsive_start = css.index("@media (max-width: 920px)")
        self.assertIn("grid-template-columns: 1fr", css[responsive_start:])
        self.assertNotIn("animation", css[css.index(".mail-test-status"):responsive_start])

    def test_user_settings_forms_send_optional_email_fields(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")
        users_source = source[
            source.index("function renderSettingsUsers") : source.index(
                "function renderSettings()", source.index("function renderSettingsUsers")
            )
        ]

        self.assertIn('emailInput.name = "email"', users_source)
        self.assertIn('emailInput.type = "email"', users_source)
        self.assertIn('emailInput.autocomplete = "email"', users_source)
        self.assertIn('userEmailInput.type = "email"', users_source)
        self.assertIn('userEmailInput.autocomplete = "email"', users_source)
        self.assertIn("email: emailInput.value", users_source)
        self.assertIn("email: userEmailInput.value", users_source)
        self.assertIn(".user-add-form", css)
        self.assertIn(".user-row", css)

    def test_backend_health_indicator_is_accessible_safe_and_visibility_aware(self) -> None:
        html_source = INDEX_HTML.read_text(encoding="utf-8")
        js_source = APP_JS.read_text(encoding="utf-8")
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        brand_start = html_source.index('<div class="topbar-brand">')
        brand_end = html_source.index("</header>", brand_start)
        brand_source = html_source[brand_start:brand_end]
        self.assertIn('id="backendHealthStatus"', brand_source)
        self.assertIn('aria-live="polite"', brand_source)
        self.assertIn('aria-controls="backendHealthDetails"', brand_source)
        self.assertIn('aria-expanded="false"', brand_source)
        self.assertIn('class="backend-health-dot"', brand_source)
        self.assertIn('id="backendHealthText"', brand_source)
        self.assertIn('id="backendHealthDetails"', brand_source)
        self.assertIn('id="backendHealthDetails" class="backend-health-details" role="tooltip" hidden', brand_source)
        for label in ("Backend", "SQLite", "Proces zadan", "Powiadomienia", "FTP", "SQL", "Profile SQL", "Pimcore"):
            self.assertIn(label, brand_source)

        health_start = js_source.index("function healthLevel")
        health_end = js_source.index("async function pollBackendHealth", health_start)
        health_source = js_source[health_start:health_end]
        self.assertIn('components.backend?.status !== "online"', health_source)
        self.assertIn('components.sqlite?.status === "critical"', health_source)
        self.assertIn('components.job_processor?.status === "critical"', health_source)
        self.assertIn('components.notification_worker?.status === "critical"', health_source)
        self.assertIn("payloadOk === false", health_source)
        self.assertIn("ms > HEALTH_CRITICAL_MS", health_source)
        self.assertIn("ms >= HEALTH_SLOW_MS", health_source)
        self.assertIn('item.status === "degraded"', health_source)
        self.assertIn("performance.now()", js_source)
        self.assertIn('requestJson("/api/health", { signal: controller.signal })', js_source)
        self.assertIn("healthFailures = 0", js_source)
        self.assertIn("healthFailures >= HEALTH_OFFLINE_FAILURES", js_source)
        self.assertIn("document.hidden", js_source)
        self.assertIn("pollBackendHealth().catch(() => {})", js_source)
        self.assertIn("async function fetchRuntimeStatus()", js_source)
        self.assertIn('requestJson("/api/runtime-status")', js_source)
        self.assertIn("new PicSyncra.RuntimeStatusPoller", js_source)
        self.assertNotIn("backendHealthDetailsList.innerHTML", js_source)
        self.assertIn("backendHealthDetailsList.replaceChildren", js_source)
        self.assertIn("observed_at", js_source)
        self.assertIn("components[key]?.observed_at", js_source)
        self.assertIn("status.textContent = observedAt", js_source)
        self.assertIn("serverTime", js_source)
        self.assertIn("currentLatencyMs", js_source)
        self.assertIn("medianLatencyMs", js_source)

        disclosure_start = js_source.index("function setBackendHealthDetailsExpanded")
        disclosure_end = js_source.index("function showLogsError", disclosure_start)
        disclosure_source = js_source[disclosure_start:disclosure_end]
        self.assertIn("backendHealthDetails.hidden = !expanded", disclosure_source)
        self.assertIn('setAttribute("aria-expanded", expanded ? "true" : "false")', disclosure_source)
        self.assertIn("healthDetailsPinned", disclosure_source)
        self.assertIn("healthDetailsPointerInside = true", disclosure_source)
        self.assertIn("healthDetailsPointerInside = false", disclosure_source)
        self.assertNotIn('matches(":hover")', disclosure_source)
        for event_name in ("pointerenter", "pointerleave", "focusin", "focusout", "click"):
            self.assertIn(f'addEventListener("{event_name}"', disclosure_source)

        self.assertIn(".backend-health-dot", css_source)
        self.assertIn('[data-level="offline"]', css_source)
        self.assertNotIn(".backend-health-indicator:hover .backend-health-details", css_source)
        self.assertNotIn(".backend-health-indicator:focus-within .backend-health-details", css_source)

    def test_resource_indicator_has_compact_and_accessible_detail_contract(self) -> None:
        html_source = INDEX_HTML.read_text(encoding="utf-8")
        js_source = APP_JS.read_text(encoding="utf-8")
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn('id="resourceStatus"', html_source)
        self.assertIn('id="resourceStatusText"', html_source)
        self.assertIn('id="resourceDetails"', html_source)
        self.assertIn('id="resourceDetailsList"', html_source)
        self.assertIn('data-settings-tab="monitor"', html_source)
        self.assertIn('aria-controls="resourceDetails"', html_source)
        self.assertIn('aria-expanded="false"', html_source)

        self.assertIn("function renderResourceStatus", js_source)
        self.assertIn("function renderSettingsResourceMonitor", js_source)
        self.assertIn("function runResourceMonitorTest", js_source)
        self.assertIn('requestJson("/api/resource-monitor/simulate-safe"', js_source)
        self.assertIn('requestJson("/api/resource-monitor/real-test"', js_source)
        self.assertIn("resourceDetailsList.replaceChildren", js_source)
        self.assertIn('setAttribute("aria-expanded", expanded ? "true" : "false")', js_source)
        self.assertIn("renderResourceStatus(payload.resources || {})", js_source)
        self.assertIn("formatPercent", js_source)
        self.assertIn("formatMib", js_source)
        self.assertIn('"brak danych"', js_source)
        self.assertIn(".resource-status", css_source)

    def test_resource_visibility_settings_tests_and_ftp_cache_use_safe_state_paths(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        resource_start = source.index("function renderResourceStatus")
        resource_end = source.index("function healthLevel", resource_start)
        resource_source = source[resource_start:resource_end]
        monitor_start = source.index("function renderSettingsResourceMonitor")
        monitor_end = source.index("function renderSettings()", monitor_start)
        monitor_source = source[monitor_start:monitor_end]

        self.assertIn("state.settings?.resource_monitor?.show_status === false", resource_source)
        self.assertIn("resourceStatus.hidden", resource_source)
        self.assertNotIn("backendHealthIndicator.hidden", resource_source)
        for setting in (
            "show_status",
            "cpu_percent_threshold",
            "memory_percent_threshold",
            "io_mib_per_second_threshold",
        ):
            self.assertIn(setting, monitor_source)
        for kind in ("cpu", "memory", "disk"):
            self.assertIn(f'runResourceMonitorTest("{kind}")', monitor_source)
        self.assertIn('runResourceMonitorTest("safe")', monitor_source)
        self.assertIn("function updateResourceMonitorTestUi", monitor_source)
        self.assertIn("resourceMonitorTestState.pending", monitor_source)
        self.assertIn("resourceMonitorTestState.message", monitor_source)
        self.assertIn("await pollBackendHealth()", monitor_source)
        self.assertIn("async function fetchRuntimeStatus()", source)
        self.assertIn("new PicSyncra.RuntimeStatusPoller", source)

        self.assertIn("const FTP_PREVIEW_CACHE_LIMIT = 120;", source)
        helper_start = source.index("function setFtpPreviewCache")
        helper_end = source.index("function clearFtpPreviewCacheForPrefixes", helper_start)
        helper_source = source[helper_start:helper_end]
        self.assertIn("state.ftpPreviewCache.delete(key);", helper_source)
        self.assertIn("state.ftpPreviewCache.set(key, value);", helper_source)
        self.assertIn("state.ftpPreviewCache.size > FTP_PREVIEW_CACHE_LIMIT", helper_source)
        self.assertIn(
            "state.ftpPreviewCache.delete(state.ftpPreviewCache.keys().next().value);",
            helper_source,
        )
        self.assertLess(
            helper_source.index("state.ftpPreviewCache.delete(key);"),
            helper_source.index("state.ftpPreviewCache.set(key, value);"),
        )
        self.assertEqual(source.count("state.ftpPreviewCache.set("), 1)
        self.assertGreaterEqual(source.count("setFtpPreviewCache("), 4)
        preview_loader = source[
            source.index("async function loadFtpPreview") : source.index(
                "function nextBackgroundFtpPreviewCandidate"
            )
        ]
        merge_photo = source[
            source.index("function mergePhotoRecord") : source.index(
                "function photoLoadingText"
            )
        ]
        self.assertGreaterEqual(preview_loader.count("setFtpPreviewCache("), 2)
        self.assertIn("setFtpPreviewCache(cachedFtpKey, cachedFtp);", merge_photo)

    def test_logs_use_tabs_live_stream_and_cursor_loading(self) -> None:
        html_source = INDEX_HTML.read_text(encoding="utf-8")
        js_source = APP_JS.read_text(encoding="utf-8")
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        for tab in ("live", "critical", "error", "warning", "jobs"):
            self.assertIn(f'data-log-tab="{tab}"', html_source)
            self.assertIn(f'data-log-badge="{tab}"', html_source)
        for control_id in (
            "logsTextFilter",
            "logsSeverityFilter",
            "logsModuleFilter",
            "logsUserFilter",
            "logsEanFilter",
            "logsJobFilter",
            "logsPauseButton",
            "logsAutoscrollToggle",
            "logsLoadMoreButton",
            "logsResetFiltersButton",
        ):
            self.assertIn(f'id="{control_id}"', html_source)
        self.assertIn("observability:", js_source)
        self.assertIn("nextCursor", js_source)
        self.assertIn("unread", js_source)
        self.assertIn("MAX_LIVE_LOG_EVENTS = 2000", js_source)
        self.assertIn("localStorage.getItem(LOG_AUTOSCROLL_KEY)", js_source)
        self.assertIn('classList.toggle("log-alert-error"', js_source)
        self.assertIn(".nav-button.log-alert-error", css_source)
        self.assertIn(".log-card-highlight", css_source)
        self.assertIn("data-observability-id", js_source)
        self.assertIn("live_seed", js_source)
        self.assertIn("stream_after_id", js_source)
        logs_renderer = js_source[
            js_source.index("function renderLogEvent") : js_source.index("function createPoller")
        ]
        self.assertNotIn("innerHTML", logs_renderer)
        self.assertIn("textContent", logs_renderer)

    def test_incident_cards_render_safe_delivery_status_details(self) -> None:
        js_source = APP_JS.read_text(encoding="utf-8")
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        for status, label in (
            ("pending", "Oczekuje"),
            ("sending", "Oczekuje"),
            ("sent", "Wysłano"),
            ("fallback", "Fallback"),
            ("skipped", "Pominięto"),
            ("error", "Błąd"),
        ):
            self.assertIn(f'{status}: "{label}"', js_source)
        incident_renderer = js_source[
            js_source.index("function renderIncidentCard") : js_source.index(
                "function renderJobCard"
            )
        ]
        self.assertIn("renderIncidentDeliveries", incident_renderer)
        self.assertNotIn("innerHTML", incident_renderer)
        self.assertIn(".log-delivery-badge", css_source)
        self.assertIn(".log-delivery-details", css_source)
        delivery_styles = css_source[
            css_source.index(".log-delivery-summary") : css_source.index(
                ".log-card-highlight"
            )
        ]
        self.assertIn("var(--local)", delivery_styles)
        self.assertNotIn("var(--success)", delivery_styles)

    def test_incident_context_is_loaded_lazily_and_problem_is_cursor_paginated(self) -> None:
        js_source = APP_JS.read_text(encoding="utf-8")
        incident_renderer = js_source[
            js_source.index("function renderIncidentCard") : js_source.index(
                "function renderJobCard"
            )
        ]

        self.assertNotIn('renderIncidentContext(incident, "before"', incident_renderer)
        self.assertIn("renderLazyIncidentContext", incident_renderer)
        self.assertIn("/context?", js_source)
        self.assertIn("problem_next_cursor", js_source)
        self.assertIn("Wczytaj wiecej", js_source)
        self.assertIn('addEventListener("toggle"', js_source)

    def test_live_archive_load_more_keeps_fixed_seed_boundary_and_deduplicates(self) -> None:
        js_source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("archiveSince", js_source)
        self.assertIn("payload.archive_since", js_source)
        self.assertIn("liveArchiveEndpoint", js_source)
        self.assertIn('params.set("since", live.archiveSince)', js_source)
        self.assertIn("mergeLiveItems", js_source)
        self.assertIn("live.nextCursor", js_source)
        self.assertNotIn('tabName === "live" || !tab.nextCursor', js_source)
        append_live = js_source[
            js_source.index("function appendLiveEvent") : js_source.index(
                "function handleObservabilityEvent"
            )
        ]
        self.assertIn("live.archiveSince", append_live)
        self.assertIn("live.items.sort", append_live)

    def test_app_js_static_id_selectors_exist_in_index_html(self) -> None:
        html = _parse(INDEX_HTML)
        source = APP_JS.read_text(encoding="utf-8")
        selector_ids = set(
            re.findall(
                r"document\.querySelector(?:All)?\([\"']#([A-Za-z][A-Za-z0-9_-]*)[\"']\)",
                source,
            )
        )
        created_ids = set(
            re.findall(r"\.id\s*=\s*[\"']([A-Za-z][A-Za-z0-9_-]*)[\"']", source)
        )

        missing = sorted(selector_ids - set(html.ids) - created_ids)

        self.assertEqual(missing, [])
        self.assertEqual(html.duplicate_ids, set())

    def test_product_form_keeps_required_fields_and_actions(self) -> None:
        html = _parse(INDEX_HTML)

        required_inputs = {
            "product_id",
            "name",
            "type_name",
            "model",
            "color1",
            "color2",
            "color3",
            "extra",
            "ean",
        }
        required_buttons = {
            "webImagesButton",
            "findByEanButton",
            "findProductButton",
            "submitButton",
            "clearButton",
            "logoutButton",
            "themeToggleButton",
        }

        self.assertIn("productForm", html.ids)
        self.assertEqual(required_inputs - html.input_names, set())
        self.assertEqual(required_buttons - html.button_ids, set())
        self.assertIn("entrySelect", html.ids)
        self.assertIn("formStatus", html.ids)

    def test_all_product_fields_have_dynamic_containers_and_labels(self) -> None:
        html = _parse(INDEX_HTML)
        canonical = {
            "name",
            "type",
            "model",
            "color1",
            "color2",
            "color3",
            "extra",
            "ean",
        }
        containers = {
            attrs.get("data-product-field")
            for _tag, attrs in html.tags
            if attrs.get("data-product-field")
        }
        labels = {
            attrs.get("data-product-field-label")
            for _tag, attrs in html.tags
            if attrs.get("data-product-field-label")
        }

        self.assertEqual(canonical - containers, set())
        self.assertEqual(canonical - labels, set())

    def test_web_settings_builds_vertical_product_field_rows(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn("function productFieldSettingsList", source)
        self.assertIn('className = "product-field-settings-list wide-field"', source)
        self.assertIn('className = "product-field-settings-row"', source)
        self.assertIn("function collectProductFieldSettings", source)
        self.assertNotIn("function productFieldSettingsOrder", source)
        self.assertNotIn("function renderProductFieldLayout", source)
        self.assertNotIn("function moveProductFieldSettingsRow", source)
        self.assertNotIn("product_field_${key}_group", source)
        self.assertNotIn("product_field_${key}_order", source)
        self.assertNotIn("product-field-order-actions", source)
        self.assertIn(".product-field-settings-list", css)
        self.assertIn(".product-field-settings-row", css)
        self.assertNotIn(".product-field-group-heading", css)
        self.assertNotIn(".product-field-order-actions", css)

    def test_topbar_contains_non_button_presence_before_web_images(self) -> None:
        source = INDEX_HTML.read_text(encoding="utf-8")
        html = _parse(INDEX_HTML)

        self.assertIn("activeUsersPresence", html.ids)
        self.assertIn("activeUsersList", html.ids)
        self.assertLess(
            source.index('id="activeUsersPresence"'),
            source.index('id="webImagesButton"'),
        )
        self.assertNotIn('activeUsersPresence" type="button', source)

    def test_github_status_button_and_modal_exist(self) -> None:
        source = INDEX_HTML.read_text(encoding="utf-8")
        html = _parse(INDEX_HTML)
        css = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn("githubStatusButton", html.button_ids)
        self.assertIn("githubStatusModal", html.ids)
        self.assertIn("githubStatusOutput", html.ids)
        self.assertIn("githubStatusCheckedAt", html.ids)
        self.assertTrue(html.has_tag("button", id="githubStatusButton", type="button"))
        self.assertLess(
            source.index('id="githubStatusButton"'),
            source.index("<strong>PicSyncra Web</strong>"),
        )
        self.assertIn('viewBox="0 0 16 16" width="24" height="24"', source)
        self.assertIn(".github-status-button", css)
        self.assertRegex(css, r"\.github-status-button\s*\{[^}]*width:\s*42px;")
        self.assertRegex(css, r"\.github-status-button\s*\{[^}]*height:\s*42px;")
        self.assertIn(".github-status-button.update-available", css)
        self.assertIn("@keyframes github-status-pulse", css)

    def test_app_js_renders_active_user_presence(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn("function renderActiveUsersPresence", source)
        self.assertIn("function refreshActiveUsersPresence", source)
        self.assertIn("/api/server/presence", source)
        self.assertIn("show_active_web_users", source)
        self.assertIn("Pokaz aktywnych uzytkownikow", source)
        self.assertIn(".active-users-presence", css)
        self.assertIn(".presence-user-label", css)
        self.assertIn(".presence-more-button", css)

    def test_app_js_loads_and_renders_github_status(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('const githubStatusButton = document.querySelector("#githubStatusButton")', source)
        self.assertIn('const githubStatusModal = document.querySelector("#githubStatusModal")', source)
        self.assertIn('const githubStatusOutput = document.querySelector("#githubStatusOutput")', source)
        self.assertIn("function renderGithubStatus", source)
        self.assertIn("async function refreshGithubStatus", source)
        self.assertIn('requestJson("/api/github/repository"', source)
        self.assertIn('githubStatusButton.classList.toggle("update-available"', source)
        self.assertIn('document.querySelectorAll("[data-close-github-status]")', source)

    def test_app_js_marks_presence_client_and_leaves_on_pagehide(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn('CLIENT_ID_HEADER = "X-PicSyncra-Client-Id"', source)
        self.assertIn("function activePresenceClientId", source)
        self.assertIn("function notifyActiveUsersPresenceLeave", source)
        self.assertIn("/api/server/presence/leave", source)
        self.assertIn('window.addEventListener("pagehide"', source)
        self.assertIn("keepalive: true", source)

    def test_web_images_modal_contains_url_input_filters_and_actions(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("webImagesModal", html.ids)
        self.assertIn("webImageUrl", html.ids)
        self.assertIn("webImageScanMode", html.ids)
        self.assertIn("scanWebImagesButton", html.button_ids)
        self.assertIn("webImageMinWidth", html.ids)
        self.assertIn("webImageMinHeight", html.ids)
        self.assertIn("webImageMinKb", html.ids)
        self.assertIn("webImageUrlFilter", html.ids)
        self.assertIn("webImageHideThumbnails", html.ids)
        self.assertIn("browserExtensionDownload", html.ids)
        self.assertIn("browserExtensionDownload", html.button_ids)
        self.assertIn("browserExtensionHelpButton", html.button_ids)
        self.assertIn("browserExtensionReceiveButton", html.button_ids)
        self.assertIn("browserExtensionHelp", html.ids)
        self.assertIn("webImagesClearDataButton", html.button_ids)
        self.assertIn("webImagesOutput", html.ids)
        self.assertTrue(html.has_tag("button", id="webImagesButton", type="button"))

    def test_modal_navigation_targets_have_matching_panels(self) -> None:
        html = _parse(INDEX_HTML)

        missing_targets = {
            name
            for name in html.data_modals
            if f"{name}View" not in html.ids and f"{name}Modal" not in html.ids
        }

        self.assertEqual(missing_targets, set())
        self.assertIn("modal-view", html.classes)
        self.assertIn("manager-panel", html.classes)

    def test_settings_tabs_include_security_section(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("settingsView", html.ids)
        self.assertTrue(
            html.has_tag(
                "button",
                type="button",
                **{"data-settings-tab": "security"},
            )
        )

    def test_settings_include_pimcore_tab(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertTrue(html.has_tag("button", **{"data-settings-tab": "pimcore"}))

    def test_pimcore_test_and_history_modals_exist(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("pimcoreTestModal", html.ids)
        self.assertIn("pimcoreHistoryModal", html.ids)
        self.assertIn("pimcoreTestForm", html.ids)
        self.assertIn("pimcoreLiveLog", html.ids)
        self.assertIn("pimcoreTestRegenerateButton", html.button_ids)

    def test_pimcore_setup_wizard_has_four_steps_and_admin_controls(self) -> None:
        html = _parse(INDEX_HTML)
        for element_id in (
            "pimcoreSetupModal",
            "pimcoreSetupForm",
            "pimcoreSetupStepTitle",
            "pimcoreSetupBody",
            "pimcoreSetupBackButton",
            "pimcoreSetupNextButton",
            "pimcoreSetupCancelButton",
            "pimcoreSetupStatus",
        ):
            self.assertIn(element_id, html.ids)

    def test_runtime_pimcore_prompt_and_create_modals_exist(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("pimcoreMissingModal", html.ids)
        self.assertIn("pimcoreCreateModal", html.ids)
        self.assertIn("pimcoreCreateForm", html.ids)
        self.assertIn("pimcoreMissingCreateButton", html.ids)
        self.assertIn("pimcoreCreateRecalculateAllButton", html.ids)
        self.assertIn("pimcoreEditButton", html.ids)

    def test_runtime_pimcore_edit_modal_exists(self) -> None:
        html = _parse(INDEX_HTML)
        for element_id in (
            "pimcoreEditButton",
            "pimcoreEditModal",
            "pimcoreEditForm",
            "pimcoreEditSubmitButton",
            "pimcoreEditRecalculateAllButton",
            "pimcoreEditCancelButton",
            "pimcoreEditStatus",
        ):
            self.assertIn(element_id, html.ids)

    def test_pimcore_template_builder_modal_has_preview_and_translation_controls(self) -> None:
        html = _parse(INDEX_HTML)

        for element_id in (
            "pimcoreTemplateModal",
            "pimcoreTemplateText",
            "pimcoreTemplateSources",
            "pimcoreTemplatePreview",
            "pimcoreTemplateTranslate",
            "pimcoreTemplateLanguage",
            "pimcoreTemplatePreviewButton",
            "pimcoreTemplateSaveButton",
            "pimcoreTemplateHelpButton",
            "pimcoreTemplateHelpModal",
            "pimcoreTemplateHelpCloseButton",
            "pimcoreTemplateHelpList",
            "pimcoreTemplateHelpDetail",
        ):
            self.assertIn(element_id, html.ids)

    def test_pimcore_template_builder_has_ocr_validation_control(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("pimcoreTemplateOcrValidation", html.ids)

    def test_app_js_persists_and_previews_pimcore_mapping_templates(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function openPimcoreTemplateBuilder", source)
        self.assertIn("function previewPimcoreTemplate", source)
        self.assertIn("function insertPimcoreTemplateFunction", source)
        self.assertIn("function openPimcoreTemplateHelp", source)
        self.assertIn("function closePimcoreTemplateHelp", source)
        self.assertIn("function selectPimcoreTemplateHelp", source)
        self.assertIn("TEMPLATE_FUNCTION_HELP", source)
        self.assertIn("/api/settings/pimcore/template-preview", source)
        self.assertIn("row.dataset.valueTemplate", source)
        self.assertIn("row.dataset.translate", source)
        self.assertIn("row.dataset.targetLanguage", source)
        self.assertIn('["Nazwa", "PRODUCT:name"]', source)
        self.assertIn('insertPimcoreTemplateText(`{${source}|keep}`)', source)
        self.assertIn('["Wypelnione (1/0)", "|filled"]', source)
        self.assertIn("|any_filled", source)
        self.assertIn("|count_filled", source)
        self.assertIn("|if_filled", source)
        self.assertIn("PIMCORE_TEMPLATE_MATH_TOKENS", source)
        self.assertIn('["Mnoz", "*"]', source)
        self.assertIn('["Oblicz", "oblicz()"]', source)
        self.assertIn("insertPimcoreTemplateText(token)", source)
        self.assertIn("function pimcoreOcrValidationFromRow", source)
        self.assertIn("ocr_validation", source)
        self.assertIn("function pimcoreSlotTokens", source)
        self.assertIn("slot_tokens: pimcoreSlotTokens()", source)

    def test_runtime_pimcore_forms_load_samples_and_recalculate_saved_templates(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function populatePimcoreRuntimeForm", source)
        self.assertIn("async function loadPimcoreTestSample", source)
        self.assertIn("/api/settings/pimcore/test-sample", source)
        self.assertIn("/api/pimcore/render-templates", source)
        self.assertIn("Przelicz pole", source)
        self.assertIn("pimcore-recalculate-field", source)
        self.assertIn("async function recalculateAllPimcoreEditFields", source)
        self.assertIn("pimcoreEditRecalculateAllButton", source)

    def test_typing_in_an_ocr_validated_runtime_field_requests_validation(self) -> None:
        """Catches manual fields that wait for blur instead of checking OCR."""

        source = APP_JS.read_text(encoding="utf-8")
        populate = source[
            source.index("function populatePimcoreRuntimeForm") : source.index(
                "function pimcoreRuntimeWarnings",
                source.index("function populatePimcoreRuntimeForm"),
            )
        ]
        validation = source[
            source.index("async function validatePimcoreOcrFields") : source.index(
                "function pimcoreRuntimeRecalculateStatus",
                source.index("async function validatePimcoreOcrFields"),
            )
        ]
        ocr_slot_tokens = source[
            source.index("function pimcoreOcrSlotTokens") : source.index(
                "function renderPimcoreTemplateTokens",
                source.index("function pimcoreOcrSlotTokens"),
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the Pimcore OCR interaction contract")
        script = f"""
let runtimeInput;
const calls = [];
const makeNode = (tag) => {{
  const node = {{
    tag, className: "", textContent: "", dataset: {{}}, value: "", id: "",
    required: false, readOnly: false, autocomplete: "", children: [], listeners: {{}},
    append(...items) {{ this.children.push(...items); }},
    appendChild(item) {{ this.children.push(item); return item; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
  }};
  if (tag === "input") runtimeInput = node;
  return node;
}};
const document = {{ createElement: makeNode }};
const window = {{ setTimeout, clearTimeout }};
const state = {{ settings: {{ ocr_available: true }} }};
const pimcoreSlotTokens = () => ({{ "20": "signed-slot" }});
class FormData {{
  constructor(source) {{ this.source = source; }}
  entries() {{ return Object.entries(this.source.elements).map(([name, input]) => [name, input.value]); }}
}}
const formPayload = () => ({{}});
const requestJson = async (url, options) => {{
  calls.push({{ url, body: JSON.parse(options.body) }});
  return {{ mismatch: false, images: [] }};
}};
const renderPimcoreOcrMismatch = () => {{}};
const clearPimcoreOcrMismatch = () => {{}};
const updatePimcoreCreateSubmitState = () => {{}};
const updatePimcoreEditSubmitState = () => {{}};
const updatePimcoreRuntimeFieldChangeState = () => {{}};
const pimcoreRuntimeLayoutGroups = (schema) => [{{ name: "", rows: [{{ fields: schema }}] }}];
const pimcoreRuntimeSection = () => makeNode("section");
const pimcoreRuntimeRow = () => makeNode("div");
{ocr_slot_tokens}
{validation}
{populate}
const form = {{ textContent: "", elements: {{}}, append() {{}} }};
const schema = [{{ source: "HEIGHT", label: "Wysokosc", ocr_validation: true, value_template: "" }}];
populatePimcoreRuntimeForm(form, schema, {{ HEIGHT: "22078978" }});
form.elements.HEIGHT = runtimeInput;
runtimeInput.listeners.input();
runtimeInput.value = "22078979";
runtimeInput.listeners.input();
await new Promise((resolve) => setTimeout(resolve, 450));
console.log(JSON.stringify(calls));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        calls = json.loads(completed.stdout)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], "/api/ocr/validate")
        self.assertEqual(calls[0]["body"]["field_id"], "HEIGHT")

    def test_global_runtime_recalculation_validates_manual_ocr_fields(self) -> None:
        """Catches global recalculation that validates only template-backed fields."""

        source = APP_JS.read_text(encoding="utf-8")
        validation = source[
            source.index("async function validatePimcoreOcrFields") : source.index(
                "function pimcoreRuntimeRecalculateStatus",
                source.index("async function validatePimcoreOcrFields"),
            )
        ]
        ocr_slot_tokens = source[
            source.index("function pimcoreOcrSlotTokens") : source.index(
                "function renderPimcoreTemplateTokens",
                source.index("function pimcoreOcrSlotTokens"),
            )
        ]
        renderer = source[
            source.index("async function renderPimcoreRuntimeTemplates") : source.index(
                "function pimcoreEditHasRuntimeTemplates",
                source.index("async function renderPimcoreRuntimeTemplates"),
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the Pimcore OCR interaction contract")
        script = f"""
const calls = [];
const form = {{
  dataset: {{ pimcoreMode: "create" }},
  elements: {{
    WIDTH: {{ value: "120", dataset: {{}} }},
    HEIGHT: {{ value: "22078978", dataset: {{}} }},
  }},
}};
const pimcoreCreateForm = form;
const pimcoreEditForm = {{}};
const state = {{ settings: {{ ocr_available: true }} }};
const pimcoreSlotTokens = () => ({{ "20": "signed-slot" }});
class FormData {{
  constructor(source) {{ this.source = source; }}
  entries() {{ return Object.entries(this.source.elements).map(([name, input]) => [name, input.value]); }}
}}
const formPayload = () => ({{}});
const requestJson = async (url, options) => {{
  calls.push({{ url, body: JSON.parse(options.body) }});
  if (url === "/api/pimcore/render-templates") return {{ values: {{}}, integrations: {{}} }};
  return {{ mismatch: false, images: [] }};
}};
const updatePimcoreRuntimeFieldChangeState = () => {{}};
const updatePimcoreRuntimeCalculatedState = () => {{}};
const renderPimcoreOcrMismatch = () => {{}};
const updatePimcoreCreateSubmitState = () => {{}};
const updatePimcoreEditSubmitState = () => {{}};
{ocr_slot_tokens}
{validation}
{renderer}
const schema = [
  {{ source: "WIDTH", value_template: "{{WIDTH}}", ocr_validation: false }},
  {{ source: "HEIGHT", pimcore_field: "height", value_template: "{{PRODUCT:height}}", ocr_validation: true }},
];
await renderPimcoreRuntimeTemplates(form, schema);
console.log(JSON.stringify(calls.filter((call) => call.url === "/api/ocr/validate")));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        calls = json.loads(completed.stdout)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["body"]["field_id"], "height")
        self.assertEqual(calls[0]["body"]["value"], "22078978")

    def test_ocr_validation_activates_template_ui_and_field_recalculation(self) -> None:
        """An OCR-only mapping remains manually editable but gets its runtime controls."""

        source = APP_JS.read_text(encoding="utf-8")
        template_controls = source[
            source.index("function pimcoreTemplateBuilderButton") : source.index(
                "function pimcoreSlotTokens", source.index("function pimcoreTemplateBuilderButton")
            )
        ]
        runtime_form = source[
            source.index("function populatePimcoreRuntimeForm") : source.index(
                "const pimcoreOcrValidationTimers",
                source.index("function populatePimcoreRuntimeForm"),
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the Pimcore OCR runtime contract")
        script = f"""
const buttons = [];
const makeNode = (tag) => {{
  const node = {{
    tag, className: "", textContent: "", title: "", dataset: {{}}, value: "", id: "",
    children: [], listeners: {{}}, required: false, readOnly: false, autocomplete: "",
    append(...items) {{ this.children.push(...items); }},
    appendChild(item) {{ this.children.push(item); return item; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
    setAttribute() {{}},
  }};
  if (tag === "button") buttons.push(node);
  return node;
}};
const document = {{ createElement: makeNode }};
const rowButton = makeNode("button");
const configuredRow = {{
  dataset: {{ valueTemplate: "", ocrValidation: "true" }},
  classList: {{ contains: () => false }},
  querySelector(selector) {{
    if (selector === ".pimcore-template-button") return rowButton;
    if (selector === '[name="mapping_type"]') return {{ value: "input" }};
    return null;
  }},
}};
const updatePimcoreRuntimeFieldChangeState = () => {{}};
const schedulePimcoreOcrFieldValidation = () => {{}};
const pimcoreRuntimeLayoutGroups = (schema) => [{{ name: "", rows: [{{ fields: schema }}] }}];
const pimcoreRuntimeSection = () => makeNode("section");
const pimcoreRuntimeRow = () => makeNode("div");
{template_controls}
{runtime_form}
updatePimcoreTemplateButton(configuredRow);
const form = {{ textContent: "", elements: {{}}, children: [], append(...items) {{ this.children.push(...items); }} }};
populatePimcoreRuntimeForm(
  form,
  [{{ source: "HEIGHT", label: "Wysokosc", value_template: "", ocr_validation: true }}],
  {{ HEIGHT: "220" }},
  {{ allowRecalculate: true }},
);
console.log(JSON.stringify({{
  templateLabel: rowButton.textContent,
  hasFieldRecalculate: buttons.some((button) => button.className.includes("pimcore-recalculate-field")),
}}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        controls = json.loads(completed.stdout)
        self.assertEqual(controls["templateLabel"], "Zmien szablon")
        self.assertTrue(controls["hasFieldRecalculate"])

    def test_ocr_completion_revalidates_open_pimcore_forms(self) -> None:
        """A completed scan must compare the current form values without editing them."""

        source = APP_JS.read_text(encoding="utf-8")
        state_helpers = source[
            source.index("function isOcrSlotStateInProgress") : source.index(
                "function updateSlotPreview", source.index("function isOcrSlotStateInProgress")
            )
        ]
        refresh_slots = source[
            source.index("async function refreshOcrSlotStates") : source.index(
                "function renderSettingsOcr", source.index("async function refreshOcrSlotStates")
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the OCR completion contract")
        script = f"""
let revalidations = 0;
const state = {{
  files: new Map([["20", {{ token: "signed-slot", ocr_state: "refining" }}]]),
  loadedPhotos: new Map(),
}};
const slotFileToken = (item) => item.token;
const requestJson = async () => ({{ state: "completed" }});
const updateSlotPreview = () => {{}};
const revalidateOpenPimcoreOcrFields = async () => {{ revalidations += 1; }};
{state_helpers}
{refresh_slots}
await refreshOcrSlotStates();
console.log(JSON.stringify({{ state: state.files.get("20").ocr_state, revalidations }}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        result = json.loads(completed.stdout)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["revalidations"], 1)

    def test_applying_a_calculated_value_revalidates_it_against_ocr(self) -> None:
        """Manual input wins until the user explicitly accepts the calculated value."""

        source = APP_JS.read_text(encoding="utf-8")
        calculated_state = source[
            source.index("function updatePimcoreRuntimeCalculatedState") : source.index(
                "function clearPimcoreOcrMismatch",
                source.index("function updatePimcoreRuntimeCalculatedState"),
            )
        ]
        node = Path(r"C:\Program Files\nodejs\node.exe")
        if not node.exists():
            self.skipTest("Node.js is required for the Pimcore calculated-value contract")
        script = f"""
const created = [];
const makeNode = (tag) => {{
  const node = {{
    tag, className: "", textContent: "", title: "", hidden: false, children: [], listeners: {{}},
    append(...items) {{ this.children.push(...items); }},
    appendChild(item) {{ this.children.push(item); return item; }},
    addEventListener(name, handler) {{ this.listeners[name] = handler; }},
    setAttribute() {{}},
    querySelector(selector) {{
      if (selector === "span") return this.children.find((item) => item.tag === "span") || null;
      return null;
    }},
  }};
  created.push(node);
  return node;
}};
const document = {{ createElement: makeNode }};
let calculatedInfo = null;
const field = {{
  classList: {{ toggle() {{}} }},
  querySelector(selector) {{
    if (selector === ".pimcore-runtime-calculated") return calculatedInfo;
    if (selector === "input") return input;
    return null;
  }},
  appendChild(item) {{ calculatedInfo = item; }},
}};
const input = {{ value: "manual", dataset: {{}}, closest: () => field }};
const form = {{ elements: {{ HEIGHT: input }} }};
let validationSource = "";
const clearPimcoreRuntimeConflict = () => {{}};
const updatePimcoreRuntimeFieldChangeState = () => {{}};
const updatePimcoreRuntimeOriginalState = () => {{}};
const updatePimcoreCreateSubmitState = () => {{}};
const updatePimcoreEditSubmitState = () => {{}};
const pimcoreRuntimeActions = (...items) => {{ const actions = makeNode("actions"); actions.append(...items); return actions; }};
const schedulePimcoreOcrFieldValidation = (_form, _schema, source) => {{ validationSource = source; }};
{calculated_state}
updatePimcoreRuntimeCalculatedState(
  form,
  {{ calculated_values: {{ HEIGHT: "calculated" }}, changed: {{ HEIGHT: true }} }},
  [{{ source: "HEIGHT", ocr_validation: true }}],
);
created.find((node) => node.className.includes("pimcore-runtime-apply-action")).listeners.click();
console.log(JSON.stringify({{ value: input.value, validationSource }}));
"""
        completed = subprocess.run(
            [str(node), "-e", script],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        result = json.loads(completed.stdout)
        self.assertEqual(result["value"], "calculated")
        self.assertEqual(result["validationSource"], "HEIGHT")

    def test_runtime_pimcore_create_modal_recalculates_and_reopens_for_missing_product(
        self,
    ) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        status_start = source.index("async function checkPimcoreProductStatus")
        status_end = source.index("function openPimcoreCreateModal", status_start)
        status_body = source[status_start:status_end]
        edit_start = source.index("async function openPimcoreEditModal")
        edit_end = source.index("function closePimcoreEditModal", edit_start)
        edit_body = source[edit_start:edit_end]

        self.assertIn("const pimcoreCreateRecalculateAllButton", source)
        self.assertIn("async function recalculateAllPimcoreCreateFields", source)
        self.assertIn(
            "pimcoreCreateRecalculateAllButton?.addEventListener("
            '"click", recalculateAllPimcoreCreateFields);',
            source,
        )
        self.assertIn(
            "pimcoreEditButton.disabled = state.pimcoreCreateSchema.length === 0;",
            status_body,
        )
        self.assertIn(
            "openPimcoreCreateModal(state.pimcoreMissingEan || currentEan);",
            edit_body,
        )

    def test_sql_profile_ui_and_pimcore_sql_mapping_controls_exist(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "picsyncra" / "web" / "static" / "app.css").read_text(
            encoding="utf-8"
        )
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("function additionalSqlProfiles", source)
        self.assertIn('profile.usage === "pimcore_sql"', source)
        self.assertIn("Profile dodatkowe SQL", source)
        self.assertIn("Domyslne polaczenie dla zdjec i slotow", source)
        self.assertNotIn('settingsFieldGroup("MS SQL"', source)
        self.assertNotIn('settingsFieldGroup("MySQL"', source)
        self.assertNotIn("Profil domyslny jest zawsze uzywany przez Sloty", source)
        self.assertIn("function sqlProfileRow", source)
        self.assertIn("/api/settings/sql-profiles/", source)
        self.assertIn("mapping_sql_query", source)
        self.assertIn("mapping_sql_profile_id", source)
        self.assertIn("pimcore-runtime-calculated", source)
        self.assertIn("pimcore-runtime-different", css)
        self.assertIn("pimcore-template-sql-controls", source)
        self.assertIn("insertPimcoreTemplateSqlToken", source)
        self.assertNotIn("row.append(use, label, target, required, template, remove, pimcoreSqlMappingControls", source)
        self.assertNotIn("row.appendChild(pimcoreSqlMappingControls", source)
        self.assertIn(".sql-profile-card", css)
        self.assertIn(".sql-profile-card + .sql-profile-card", css)

    def test_pimcore_mapping_layout_controls_and_runtime_sections_exist(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "picsyncra" / "web" / "static" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("mapping_layout_group", source)
        self.assertIn("mapping_layout_order", source)
        self.assertNotIn("mapping_layout_width", source)
        self.assertIn("layout_group:", source)
        self.assertIn("layout_order:", source)
        self.assertNotIn("layout_width:", source)
        self.assertNotIn("pimcoreRuntimeFieldWidth", source)
        self.assertIn("function pimcoreRuntimeLayoutGroups", source)
        self.assertIn("pimcore-runtime-section", source)
        self.assertIn("pimcore-runtime-row", source)
        self.assertIn("--pimcore-runtime-columns", source)
        self.assertIn(".pimcore-runtime-section", css)
        self.assertIn(".pimcore-runtime-row", css)
        self.assertIn("border-left: 4px solid var(--accent)", css)

    def test_pimcore_runtime_difference_ui_preserves_manual_values(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function updatePimcoreRuntimeCalculatedState", source)
        self.assertIn("function updatePimcoreRuntimeFieldChangeState", source)
        self.assertIn("dataset.originalValue", source)
        self.assertIn("dataset.calculatedValue", source)
        self.assertIn("pimcore-runtime-different", source)
        self.assertIn("Zastosuj wyliczone", source)
        self.assertIn('mode: form.dataset.pimcoreMode || "create"', source)
        self.assertIn("if (!input.value)", source)

    def test_pimcore_runtime_difference_actions_are_compact_icon_buttons(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "picsyncra" / "web" / "static" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('className = "pimcore-runtime-actions"', source)
        self.assertIn('className = "ghost-button pimcore-runtime-action-button', source)
        self.assertIn('textContent = "\\u2713"', source)
        self.assertIn('textContent = "\\u00d7"', source)
        self.assertIn('title = "Zastosuj wyliczone"', source)
        self.assertIn('title = "Cofnij zmiany"', source)
        self.assertIn("setAttribute(\"aria-label\"", source)
        self.assertIn(".pimcore-runtime-actions", css)
        self.assertIn(".pimcore-runtime-action-button", css)
        runtime_state_start = css.index(".pimcore-runtime-calculated,")
        runtime_state_end = css.index(".pimcore-runtime-calculated {", runtime_state_start)
        runtime_state_block = css[runtime_state_start:runtime_state_end]

        self.assertIn("display: flex;", runtime_state_block)
        self.assertIn("flex-wrap: wrap;", runtime_state_block)
        self.assertNotIn(
            "grid-template-columns: minmax(0, 1fr) auto auto;",
            runtime_state_block,
        )
        actions_block = css[
            css.index(".pimcore-runtime-actions {") : css.index(
                ".pimcore-runtime-action-button {"
            )
        ]
        self.assertIn("display: flex;", actions_block)
        self.assertIn("flex-wrap: nowrap;", actions_block)
        action_button_block = css[
            css.index(".pimcore-runtime-action-button {") : css.index(
                ".pimcore-runtime-apply-action {"
            )
        ]
        self.assertIn("width: 28px;", action_button_block)
        self.assertIn("min-width: 28px;", action_button_block)
        self.assertIn("padding: 0;", action_button_block)

    def test_pimcore_edit_recalculation_blocks_submit_until_resolved(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "picsyncra" / "web" / "static" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("function hasBlockingPimcoreRuntimeDifferences", source)
        self.assertIn("function focusFirstPimcoreRuntimeDifference", source)
        self.assertIn("function updatePimcoreEditSubmitState", source)
        self.assertIn("pimcore-runtime-conflict", source)
        self.assertIn("pimcore-runtime-pulse", source)
        self.assertIn("Cofnij zmiany", source)
        self.assertIn("Oryginalnie:", source)
        self.assertIn("pimcore-runtime-original", source)
        self.assertIn("pimcore-runtime-conflict", css)
        self.assertIn("body[data-theme=\"dark\"] .pimcore-runtime-conflict input", css)
        self.assertIn("@keyframes pimcore-runtime-pulse", css)

    def test_pimcore_runtime_forwards_latest_render_integration_context(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("pimcoreCreateIntegrations", source)
        self.assertIn("pimcoreEditIntegrations", source)
        self.assertIn("result.integrations || { sql_profiles: [] }", source)
        self.assertNotIn("integration_results: state.pimcoreCreateIntegrations", source)
        self.assertNotIn("integration_results: state.pimcoreEditIntegrations", source)
        self.assertIn(
            "integration_context_id: state.pimcoreCreateIntegrationContextId",
            source,
        )
        self.assertIn(
            "integration_context_id: state.pimcoreEditIntegrationContextId",
            source,
        )
        self.assertIn("result.integration_context_id", source)
        self.assertIn("object_id:", source)

    def test_pimcore_history_has_submission_export_actions(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("exportPimcoreSubmissions", source)
        self.assertIn("/api/settings/pimcore/submissions/export", source)
        self.assertIn("Eksport CSV", html)
        self.assertIn("pimcoreHistoryExportCsvButton", html)
        self.assertIn("Eksport XLSX", html)
        self.assertIn("pimcoreHistoryExportXlsxButton", html)

    def test_pimcore_settings_has_modal_submission_export_action(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("function pimcoreSettingsExportButton", source)
        self.assertIn("function openPimcoreExportModal", source)
        self.assertIn("function closePimcoreExportModal", source)
        self.assertIn("Eksport danych Pimcore", source)
        self.assertIn("pimcoreExportModal", html)
        self.assertIn("pimcoreExportCsvButton", html)
        self.assertIn("pimcoreExportXlsxButton", html)
        self.assertIn('exportPimcoreSubmissions("csv", { includeFilters: false })', source)
        self.assertIn('exportPimcoreSubmissions("xlsx", { includeFilters: false })', source)
        self.assertNotIn("promptPimcoreSubmissionExportFormat", source)
        self.assertNotIn("Format eksportu danych Pimcore: CSV lub XLSX", source)
        self.assertIn("pimcoreSettingsExportButton()", source)

    def test_pimcore_settings_has_saved_import_export_layout_editor(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("pimcoreExportLayoutModal", html)
        self.assertIn("pimcoreExportLayoutOpenButton", source)
        self.assertIn("function savePimcoreExportColumns", source)
        self.assertIn("pimcoreExportLayoutAddFieldButton", source)
        self.assertIn("pimcoreExportLayoutAddBlankButton", source)
        self.assertIn("export_columns", source)

    def test_pimcore_export_layout_supports_between_slots_insert_and_selection(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css = APP_CSS.read_text(encoding="utf-8")

        self.assertIn("insertPimcoreExportBlankColumn", source)
        self.assertIn("pimcoreExportLayoutSelection", source)
        self.assertIn("pimcore-export-layout-insert", source)
        self.assertIn("pimcore-export-layout-selected", source)
        self.assertIn("function movePimcoreExportColumns", source)
        self.assertIn('addEventListener("dragstart"', source)
        self.assertIn('addEventListener("dragover"', source)
        self.assertIn('addEventListener("drop"', source)
        self.assertIn("else if (!pimcoreExportLayoutSelection.has(index))", source)
        self.assertIn("const isContiguous = selectedIndexes.every", source)
        self.assertIn(".pimcore-export-layout-insert:hover", css)
        self.assertIn(".pimcore-export-layout-drop-target", css)
        self.assertNotIn('moveUp.textContent = "↑"', source)

    def test_pimcore_edit_modal_opens_before_remote_object_load(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("async function openPimcoreEditModal")
        end = source.index("function closePimcoreEditModal", start)
        body = source[start:end]

        self.assertIn("++state.pimcoreEditRequestId", body)
        self.assertIn("Number(state.pimcoreExistingObject?.id || 0)", body)
        self.assertIn("Nie mozna edytowac produktu Pimcore bez poprawnego ID.", body)
        self.assertLess(
            body.index('pimcoreEditModal.classList.add("active")'),
            body.index("await requestJson"),
        )

    def test_pimcore_edit_click_resolves_current_ean_before_giving_up(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("async function openPimcoreEditModal")
        end = source.index("function closePimcoreEditModal", start)
        body = source[start:end]

        self.assertIn("let objectId = Number(state.pimcoreExistingObject?.id || 0);", body)
        self.assertIn("const currentEan = productForm.elements.ean.value.trim();", body)
        self.assertIn("await checkPimcoreProductStatus(currentEan);", body)
        self.assertIn("objectId = Number(state.pimcoreExistingObject?.id || 0);", body)

    def test_pimcore_status_enables_edit_only_for_positive_object_id(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("async function checkPimcoreProductStatus")
        end = source.index("function openPimcoreCreateModal", start)
        body = source[start:end]

        self.assertIn("Number(payload.object?.id || 0)", body)
        self.assertIn("Pimcore zwrocil produkt bez poprawnego ID", body)
        self.assertIn("pimcoreEditButton.disabled = false", body)

    def test_pimcore_ean_input_clears_cached_lookup_before_rechecking(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function handlePimcoreEanInput")
        end = source.index("function schedulePimcoreStatusLookup", start)
        body = source[start:end]

        self.assertIn('state.pimcoreLastCheckedEan = "";', body)
        self.assertIn("schedulePimcoreStatusLookup();", body)

    def test_pimcore_metadata_refresh_replaces_current_settings_form(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("async function refreshCompactPimcoreMetadata")
        end = source.index("function pimcoreCsvImportButton", start)
        body = source[start:end]

        self.assertIn("renderSettings();", body)
        self.assertNotIn("renderSettingsPimcore();", body)

    def test_loading_existing_entry_triggers_pimcore_status_lookup(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index("function fillForm")
        end = source.index("async function refreshData", start)
        body = source[start:end]

        self.assertIn("productForm.elements.ean.value = entry.ean || \"\";", body)
        self.assertIn("handlePimcoreEanInput();", body)

    def test_pimcore_ui_uses_example_placeholder_without_private_default(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        html_source = INDEX_HTML.read_text(encoding="utf-8")
        css = (ROOT / "picsyncra" / "web" / "static" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("http://twoj-adres-pimcore.example", source)
        self.assertIn("flex-wrap: wrap", css[css.index(".lookup-actions"):])
        self.assertNotIn(".lookup-actions #pimcoreEditButton {\n  min-width", css)

    def test_slot_template_keeps_preview_and_file_input_controls(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("slotTemplate", html.ids)
        self.assertIn("slot-card", html.classes)
        self.assertIn("slot-preview", html.classes)
        self.assertIn("slot-empty", html.classes)
        self.assertTrue(
            html.has_tag(
                "input",
                type="file",
                accept="image/*,.pdf,.eps,.psd,.ai,.tif,.tiff",
            )
        )

    def test_app_js_treats_additional_image_formats_as_uploads(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        for extension in (
            ".jfif",
            ".jpe",
            ".peg",
            ".apng",
            ".dib",
            ".avifs",
            ".heic",
            ".heif",
            ".hif",
            ".jp2",
            ".j2k",
            ".jpc",
            ".jpx",
            ".ico",
            ".cur",
            ".tga",
            ".ppm",
            ".pgm",
            ".pbm",
            ".pnm",
            ".pcx",
        ):
            self.assertIn(f'"{extension}"', source)
        for extension in ("jpe", "peg", "jfif"):
            self.assertIn(f'sourceExt === "{extension}"', source)
        self.assertIn('sourceExt === "apng"', source)

    def test_app_js_swaps_two_occupied_slots_on_slot_drop(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("const target = getSlotAssignment(targetPrefix);", source)
        self.assertIn("Zamieniono slot", source)
        self.assertLess(
            source.index("Zamieniono slot"),
            source.index("Przeniesiono slot"),
        )

    def test_app_js_displays_web_image_scan_errors_inside_modal(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("renderWebImagesError", source)
        self.assertIn("Cloudflare/challenge 403", source)
        self.assertIn("Importer nie dostaje wtedy HTML-a produktu", source)

    def test_app_js_receives_browser_extension_imports(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("/api/browser-extension/imports", source)
        self.assertIn("/api/browser-extension/download", source)
        self.assertIn("receiveBrowserExtensionImages", source)
        self.assertIn("downloadBrowserExtension", source)
        self.assertIn("clearLoadedWebImages", source)
        self.assertIn("parseWebImageUrlFilter", source)
        self.assertIn("!?<[^>]+>", source)
        self.assertIn("existingByUrl", source)
        self.assertIn("state.webImages.push(image)", source)
        self.assertIn("Odbierz z rozszerzenia", source)

    def test_app_js_uses_cached_preview_for_browser_extension_imports(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("preview_url: cache.thumb_url || cache.url || item?.source_url || \"\"", source)
        self.assertIn("img.src = image.preview_url || image.thumb_url || image.url;", source)

    def test_login_page_keeps_accessible_login_form(self) -> None:
        html = _parse(LOGIN_HTML)

        self.assertIn("loginForm", html.ids)
        self.assertIn("loginMessage", html.ids)
        self.assertIn("username", html.input_names)
        self.assertIn("password", html.input_names)
        self.assertTrue(html.has_tag("button", type="submit"))
        self.assertEqual(html.duplicate_ids, set())
        login_source = LOGIN_HTML.read_text(encoding="utf-8")
        self.assertNotIn('value="admin"', login_source)

    def test_login_js_remembers_last_successful_username(self) -> None:
        source = (ROOT / "picsyncra" / "web" / "static" / "login.js").read_text(encoding="utf-8")

        self.assertIn('LAST_LOGIN_USERNAME_KEY = "picsyncra-last-login-username"', source)
        self.assertIn("localStorage.getItem(LAST_LOGIN_USERNAME_KEY)", source)
        self.assertIn("localStorage.setItem(LAST_LOGIN_USERNAME_KEY, username)", source)
        self.assertLess(
            source.index("localStorage.setItem(LAST_LOGIN_USERNAME_KEY, username)"),
            source.index('window.location.href = "/"'),
        )

    def test_backup_history_and_diff_modals_exist(self) -> None:
        html = _parse(INDEX_HTML)

        self.assertIn("backupHistoryModal", html.ids)
        self.assertIn("backupHistoryOutput", html.ids)
        self.assertIn("backupDiffModal", html.ids)
        self.assertIn("backupDiffOutput", html.ids)

    def test_backup_modals_render_above_settings_modal(self) -> None:
        html = _parse(INDEX_HTML)
        modal_classes = {
            attrs.get("id"): set(attrs.get("class", "").split())
            for tag, attrs in html.tags
            if tag == "div" and attrs.get("id") in {"backupHistoryModal", "backupDiffModal"}
        }

        self.assertIn("nested-modal", modal_classes["backupHistoryModal"])
        self.assertIn("nested-modal", modal_classes["backupDiffModal"])

    def test_history_ui_uses_abortable_summary_and_lazy_detail_requests(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        history_start = source.index("async function loadHistory")
        history_end = source.index("function showHistoryLoadError", history_start)
        history_source = source[history_start:history_end]

        self.assertIn("historyLoadController?.abort()", history_source)
        self.assertIn("new AbortController()", history_source)
        self.assertIn("signal: controller.signal", history_source)
        self.assertNotIn('limit: "1000"', history_source)
        self.assertIn("async function loadHistoryDetails", source)
        self.assertIn("/api/history/details?", source)
        self.assertIn("group.change_count", source)
        self.assertIn("group.entry", source)
        detail_error_start = source.index("function showHistoryDetailLoadError")
        detail_error_end = source.index("function showHistoryLoadError", detail_error_start)
        detail_error_handler = source[detail_error_start:detail_error_end]
        self.assertIn('if (error?.name === "AbortError") return;', detail_error_handler)
        detail_close_start = source.index("function closeHistoryDetail")
        detail_close_end = source.index("async function loadHistoryDetails", detail_close_start)
        detail_close_handler = source[detail_close_start:detail_close_end]
        self.assertIn("historyDetailsController?.abort()", detail_close_handler)
        self.assertIn("historyDetailsController = null", detail_close_handler)
        self.assertIn('classList.remove("active")', detail_close_handler)
        self.assertIn('button.addEventListener("click", closeHistoryDetail)', source)
        close_modals_start = source.index("function closeModals()")
        close_modals_end = source.index("function activeUserLastSeenLabel", close_modals_start)
        self.assertIn("closeHistoryDetail();", source[close_modals_start:close_modals_end])

    def test_history_detail_ui_pages_and_aborts_stale_requests(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('id="historyDetailPrevButton"', html)
        self.assertIn('id="historyDetailNextButton"', html)
        self.assertIn('page: String(page)', source)
        self.assertIn('page_size: String(state.historyDetailPageSize)', source)
        self.assertIn('historyDetailPrevButton.disabled = page <= 1', source)
        self.assertIn('historyDetailNextButton.disabled = page >= totalPages', source)
        self.assertIn('const fragment = document.createDocumentFragment();', source)
        self.assertIn('historyDetailOutput.appendChild(fragment);', source)
        render_start = source.index("function renderHistoryDetails")
        render_end = source.index("function updateHistoryDetailPagination", render_start)
        self.assertIn(
            'historyDetailOutput.className = "history-detail-output";',
            source[render_start:render_end],
        )

    def test_history_detail_loading_replaces_stale_pagination_context(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        load_start = source.index("async function loadHistoryDetails")
        load_end = source.index("async function loadHistory(", load_start)
        load_source = source[load_start:load_end]
        request_index = load_source.index("await requestJson")

        self.assertIn("state.historyDetailGroup = group;", load_source[:request_index])
        self.assertIn("historyDetailPrevButton.disabled = true;", load_source[:request_index])
        self.assertIn("historyDetailNextButton.disabled = true;", load_source[:request_index])

        close_start = source.index("function closeHistoryDetail")
        close_end = source.index("async function loadHistoryDetails", close_start)
        close_source = source[close_start:close_end]
        self.assertIn("state.historyDetailGroup = null;", close_source)
        self.assertIn("state.historyDetailPage = 1;", close_source)

    def test_history_changes_modal_is_safe_detailed_and_responsive(self) -> None:
        html = _parse(INDEX_HTML)
        html_source = INDEX_HTML.read_text(encoding="utf-8")
        js_source = APP_JS.read_text(encoding="utf-8")
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        for element_id in (
            "historyChangesModal",
            "historyChangesTitle",
            "historyChangesOutput",
        ):
            self.assertIn(element_id, html.ids)
        self.assertIn('class="modal-view nested-modal"', html_source)
        self.assertIn('role="dialog"', html_source)
        self.assertIn('aria-modal="true"', html_source)
        self.assertIn('aria-labelledby="historyChangesTitle"', html_source)
        self.assertIn('tabindex="-1"', html_source)
        self.assertIn("data-close-history-changes", html_source)

        renderer_start = js_source.index("function renderHistoryChanges")
        renderer_end = js_source.index("function renderHistoryDetails", renderer_start)
        renderer = js_source[renderer_start:renderer_end]
        self.assertNotIn("innerHTML", renderer)
        self.assertNotIn("history-file-change-${operation}", renderer)
        for value in (
            "field.before",
            "field.after",
            "historyChangeJobId(details, changeSet)",
        ):
            self.assertIn(value, renderer)
        self.assertIn("textContent", renderer)
        self.assertIn("historyCompactFileRow(file)", renderer)
        self.assertIn('historyTechnicalDetails("Dane techniczne"', renderer)
        compact_start = js_source.index("function historyCompactFileRow")
        compact_end = js_source.index("let historyChangesReturnFocus", compact_start)
        compact_helper = js_source[compact_start:compact_end]
        self.assertIn("historyEvidenceBadges(evidence)", compact_helper)
        self.assertIn("historyEvidenceDetails(evidence)", compact_helper)
        for raw_evidence_row in (
            'historyChangeRow("Lokalnie"',
            'historyChangeRow("FTP"',
            'historyChangeRow("SQL"',
        ):
            self.assertNotIn(raw_evidence_row, renderer)
        self.assertIn("historyChangesCloseButton?.focus()", js_source)
        self.assertIn(
            "changesButton.disabled = !hasChangeSet && !hasLegacyDetails",
            js_source,
        )
        self.assertIn("historyChangesReturnFocus.focus()", js_source)
        self.assertIn("history-change-before-after", css_source)
        self.assertIn("history-file-change-added", css_source)
        self.assertIn("history-file-change-deleted", css_source)
        self.assertIn("history-file-change-replaced", css_source)
        self.assertIn("history-file-summary-row", css_source)
        self.assertIn("history-evidence-badges", css_source)
        self.assertIn("@media (max-width: 700px)", css_source)

    def test_live_log_renderer_uses_compact_summary_and_expandable_details(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        renderer_start = source.index("function renderLogEvent")
        renderer_end = source.index("function incidentValue", renderer_start)
        renderer = source[renderer_start:renderer_end]
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")

        self.assertIn("log-event-compact", renderer)
        self.assertIn("log-event-summary-row", renderer)
        self.assertIn('document.createElement("details")', renderer)
        self.assertIn('document.createElement("summary")', renderer)
        self.assertIn("event.recommended_action", renderer)
        self.assertIn("event.traceback_text", renderer)
        self.assertIn("JSON.stringify(event.details, null, 2)", renderer)
        self.assertIn("title.title = title.textContent", renderer)
        self.assertIn("Podsumowanie: ${event.summary", renderer)
        self.assertIn(".log-event-compact", css_source)
        self.assertIn(".log-event-summary-row", css_source)
        self.assertIn(".logs-output-live {\n  max-height: min(65vh, 760px);\n  overflow: auto;\n  gap: 0;", css_source)
        self.assertIn("text-overflow: ellipsis", css_source)

    def test_history_changes_formats_structured_values_and_unknown_durations(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        css_source = (
            ROOT / "picsyncra" / "web" / "static" / "app.css"
        ).read_text(encoding="utf-8")
        self.assertIn("function formatHistoryDuration", source)
        value_start = source.index("function historyChangeValue")
        value_end = source.index("function historyTechnicalValue", value_start)
        value_formatter = source[value_start:value_end]
        duration_start = source.index("function formatHistoryDuration")
        duration_end = source.index("function historyChangeRow", duration_start)
        duration_formatter = source[duration_start:duration_end]

        self.assertIn('typeof value === "object"', value_formatter)
        self.assertNotIn("JSON.stringify", value_formatter)
        self.assertIn("Dane zlozone", value_formatter)
        self.assertIn("function historyTechnicalValue", source)
        self.assertIn('return "Brak danych"', duration_formatter)
        self.assertIn('return `${Math.max(0, Number(value))} ms`', duration_formatter)
        self.assertIn("formatHistoryDuration(file.elapsed_ms)", source)
        self.assertNotIn('`${historyChangeValue(file.elapsed_ms)} ms`', source)
        style_start = css_source.index(".history-change-row span,")
        style_end = css_source.index("}", style_start)
        self.assertIn("white-space: pre-wrap", css_source[style_start:style_end])

    def test_history_changes_resolves_pimcore_operation_identifier(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("function historyChangeJobId", source)
        resolver_start = source.index("function historyChangeJobId")
        resolver_end = source.index("function historyFileOperationLabel", resolver_start)
        resolver = source[resolver_start:resolver_end]

        self.assertIn("details.job_id", resolver)
        self.assertIn("changeSet.job_id", resolver)
        self.assertIn("details.pimcore_operation?.operation_id", resolver)
        self.assertIn("changeSet.pimcore?.operation_id", resolver)
        self.assertIn("historyChangeJobId(details, changeSet)", source)

    def test_history_changes_modal_isolates_background_and_traps_focus(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")

        self.assertIn("historyChangesBackgroundState", source)
        self.assertIn('"#historyView.active, #historyDetailModal.active, #historyTimingModal.active"', source)
        self.assertIn('modal.getAttribute("inert")', source)
        self.assertIn('modal.setAttribute("inert", "")', source)
        self.assertIn('modal.setAttribute("aria-hidden", "true")', source)
        self.assertIn('modal.removeAttribute("inert")', source)
        self.assertIn('modal.removeAttribute("aria-hidden")', source)
        self.assertIn('event.key !== "Tab"', source)
        self.assertIn("event.shiftKey", source)
        self.assertIn('event.key === "Escape"', source)
        self.assertIn("closeHistoryChangesModal()", source)
        self.assertIn('historyChangesModal.classList.contains("active")', source)
        self.assertIn("if (historyChangesBackgroundState.length) return", source)
        self.assertIn("historyChangesReturnFocus.focus()", source)


if __name__ == "__main__":
    unittest.main()
