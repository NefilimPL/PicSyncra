const state = {
  slots: [],
  files: new Map(),
  filePreviewUrls: new Map(),
  loadedPhotos: new Map(),
  deletedSlots: new Map(),
  lists: {},
  entries: [],
  selectedList: "names",
  settings: null,
  currentUser: null,
  isAdmin: false,
  fileIndex: null,
  photosLoading: false,
  loadedEntryOriginal: null,
  slotFits: new Map(),
  defaultSlotFit: false,
  slotSources: new Map(),
  similarCandidates: new Map(),
  similarDecisionResults: new Map(),
  dismissedSimilarSlots: new Set(),
  similarFileLookupTimer: 0,
  similarFileLookupRequestId: 0,
  similarFileLookupController: null,
  similarFileLookupInFlight: false,
  similarFileLookupStartedAt: 0,
  similarFileLookupKey: "",
  draggedSlotPrefix: "",
  lastLookupMs: null,
  activeSettingsTab: "app",
  moduleBuildStatus: null,
  moduleBuildStatusLoading: false,
  moduleBuildStatusError: "",
  history: null,
  historyDetailGroup: null,
  historyDetailPage: 1,
  historyDetailPageSize: 25,
  historyTimingItem: null,
  historyChangesItem: null,
  historyPage: 1,
  historyPageSize: 50,
  historySearchTimer: 0,
  pimcoreTestOperation: null,
  pimcoreLiveEvents: [],
  pimcoreLookupTimer: 0,
  pimcoreLookupRequestId: 0,
  pimcoreLastCheckedEan: "",
  pimcoreMissingEan: "",
  pimcoreCreateSchema: [],
  pimcoreCreateIntegrations: { sql_profiles: [] },
  pimcoreCreateIntegrationContextId: "",
  ocrEnabledSlots: [],
  pimcoreRuntimeEnabled: false,
  pimcoreExistingObject: null,
  pimcoreEditObjectId: 0,
  pimcoreEditRequestId: 0,
  pimcoreEditMarker: "",
  pimcoreEditSchema: [],
  pimcoreEditIntegrations: { sql_profiles: [] },
  pimcoreEditIntegrationContextId: "",
  pimcoreTemplateRow: null,
  pimcoreSetup: {
    step: 1,
    settings: null,
    classes: [],
    folders: [],
    fields: [],
    mappings: [],
    manualLocation: false,
    eanTarget: "",
    report: null,
  },
  pimcoreSetupPrompted: false,
  observability: {
    activeTab: "live",
    unread: { critical: 0, error: 0, warning: 0, total: 0, highest: "" },
    stream: null,
    streamConnected: false,
    streamSeeded: false,
    streamAfterId: "",
    seedGeneration: 0,
    seedLoading: false,
    unreadRequestId: 0,
    paused: false,
    buffer: [],
    autoscroll: true,
    committedFilters: {
      query: "",
      severity: "",
      module: "",
      username: "",
      ean: "",
      jobId: "",
    },
    tabs: {
      live: {
        items: [],
        nextCursor: "",
        archiveSince: "",
        unread: 0,
        loading: false,
        requestId: 0,
      },
      critical: { items: [], nextCursor: "", unread: 0, loading: false, requestId: 0 },
      error: { items: [], nextCursor: "", unread: 0, loading: false, requestId: 0 },
      warning: { items: [], nextCursor: "", unread: 0, loading: false, requestId: 0 },
      jobs: { items: [], nextCursor: "", unread: 0, loading: false, requestId: 0 },
    },
  },
  settingsSecrets: null,
  theme: localStorage.getItem("picsyncra-theme") || "light",
  suppressAutoSearch: false,
  lastAutoSearchKey: "",
  photoLoadRequestId: 0,
  photoSourceStatus: new Map(),
  listFilter: "",
  declinedListPrompts: new Set(),
  activeListPromptKeys: new Set(),
  productFields: {},
  ftpPreviewLoading: new Set(),
  ftpPreviewBackgroundLoading: new Set(),
  ftpPreviewRequests: new Map(),
  ftpPreviewCache: new Map(),
  backgroundFtpPreviewTimer: 0,
  backgroundFtpPreviewLimit: 1,
  photoSourcesLoaded: new Set(),
  ftpEnabled: true,
  backgroundFtpLookupTimer: 0,
  backgroundFtpLookupKey: "",
  backgroundFtpLookupRequestId: 0,
  processing: {},
  security: {},
  slotRevisions: new Map(),
  userSelectedSlotSources: new Set(),
  slotUploadRequestId: 0,
  processStatusTimer: 0,
  processStatusStartedAt: 0,
  navigationGuardBypass: false,
  webImages: [],
  webImageSelected: new Set(),
  webImagePageUrl: "",
  webImageScanMode: ["links", "metadata"].includes(
    localStorage.getItem("picsyncra-web-image-scan-mode")
  )
    ? localStorage.getItem("picsyncra-web-image-scan-mode")
    : "links",
  webImageCache: new Map(),
  webImageCacheQueue: [],
  webImageCacheActive: 0,
  processJobs: new Map(),
  processJobsController: null,
  processQueue: { jobs: [], active_count: 0, queued_count: 0, current: null },
  acknowledgedProcessAlerts: new Set(),
  activeUsers: [],
  activeUsersEnabled: false,
  activePresenceClientId: "",
  csrfToken: "",
  pollers: [],
  runtimeStatusPoller: null,
  githubStatus: null,
  githubStatusLoading: false,
  resources: {},
  panelTimeZones: [],
  backupHistoryItems: [],
  pimcoreHistoryItems: [],
  entraExpiryStatus: null,
  lastHealthPayload: null,
};

const WEB_IMAGE_CACHE_LIMIT = 2;
const FTP_PREVIEW_CACHE_LIMIT = 120;
const MAX_AUTOCOMPLETE_OPTIONS = 80;
const ACTIVE_USERS_VISIBLE_LIMIT = 5;
const CSRF_HEADER = "X-PicSyncra-CSRF";
const CLIENT_ID_HEADER = "X-PicSyncra-Client-Id";
const CSRF_SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const SECRET_REVEAL_MS = 60000;
const POLL_HIDDEN_DELAY_MS = 30000;
const CLIENT_FAILURE_DEDUPE_MS = 60000;
const LOG_AUTOSCROLL_KEY = "picsyncra-log-autoscroll";
const MAX_LIVE_LOG_EVENTS = 2000;
const OBSERVABILITY_PAGE_SIZE = 20;
const HEALTH_SLOW_MS = 300;
const HEALTH_CRITICAL_MS = 1000;
const HEALTH_OFFLINE_FAILURES = 3;
state.observability.autoscroll = localStorage.getItem(LOG_AUTOSCROLL_KEY) !== "false";
const clientFailureFingerprints = new Map();
const healthSamples = [];
let healthFailures = 0;
let healthPollGeneration = 0;
let healthPollController = null;
let lastSuccessfulHealthComponents = {};
let healthDetailsPinned = false;
let healthDetailsPointerInside = false;
let resourceDetailsPinned = false;
let resourceDetailsPointerInside = false;
let historyLoadController = null;
let historyDetailsController = null;
let similarDecisionBackgroundState = [];
const resourceMonitorTestState = {
  pending: false,
  message: "Nie uruchomiono testu monitora.",
};

function selectedPanelTimeZone() {
  return String(state.settings?.web_display?.time_zone || "UTC");
}

function coercePanelDate(value, { epochUnit = null } = {}) {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    if (!new Set(["seconds", "milliseconds"]).has(epochUnit)) return null;
    const milliseconds = epochUnit === "seconds" ? value * 1000 : value;
    const date = new Date(milliseconds);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  if (typeof value !== "string") return null;
  const text = value.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/.exec(
    text
  );
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const offsetHour = match[8] === undefined ? 0 : Number(match[8]);
  const offsetMinute = match[9] === undefined ? 0 : Number(match[9]);
  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysInMonth[month - 1] ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59
  ) {
    return null;
  }
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatPanelTimestamp(
  value,
  { date = true, time = true, epochUnit = null } = {}
) {
  const panelDate = coercePanelDate(value, { epochUnit });
  if (!panelDate || (!date && !time)) return "Brak danych";
  const formatterOptions = {
    ...(date ? { year: "numeric", month: "short", day: "2-digit" } : {}),
    ...(time ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : {}),
    timeZone: selectedPanelTimeZone(),
    timeZoneName: "short",
  };
  try {
    return new Intl.DateTimeFormat("pl-PL", formatterOptions).format(panelDate);
  } catch (_error) {
    return new Intl.DateTimeFormat("pl-PL", { ...formatterOptions, timeZone: "UTC" }).format(
      panelDate
    );
  }
}
const SQLITE_BACKUP_DAYS = [
  ["mon", "Pon"],
  ["tue", "Wt"],
  ["wed", "Sr"],
  ["thu", "Czw"],
  ["fri", "Pt"],
  ["sat", "Sob"],
  ["sun", "Nd"],
];
const CLIENT_EXECUTABLE_UPLOAD_EXTENSIONS = new Set([
  "exe",
  "bat",
  "cmd",
  "com",
  "msi",
  "ps1",
  "vbs",
  "js",
  "jar",
  "dll",
  "scr",
  "pif",
  "sh",
]);

const listLabels = {
  names: "Nazwy",
  types: "Typy",
  models: "Modele",
  colors: "Kolory",
  extras: "Dodatki",
};

const photoSourceLabels = {
  local: "lokalne",
  sql: "SQL",
  ftp: "FTP",
  all: "dane",
};

const processStatusLabels = {
  queued: "Oczekuje",
  running: "Trwa",
  completed: "Zakonczone",
  failed: "Blad",
};

const slotGrid = document.querySelector("#slotGrid");
const slotTemplate = document.querySelector("#slotTemplate");
const processQueuePanel = document.querySelector("#processQueuePanel");
const processQueueSummary = document.querySelector("#processQueueSummary");
const processQueueList = document.querySelector("#processQueueList");
const ocrBackgroundQueuePanel = document.querySelector("#ocrBackgroundQueuePanel");
const ocrBackgroundQueueSummary = document.querySelector("#ocrBackgroundQueueSummary");
const ocrBackgroundQueueList = document.querySelector("#ocrBackgroundQueueList");
const productForm = document.querySelector("#productForm");
const formStatus = document.querySelector("#formStatus");
const resultOutput = document.querySelector("#resultOutput");
const resultMeta = document.querySelector("#resultMeta");
const resultSection = document.querySelector(".result-section");
const slotCount = document.querySelector("#slotCount");
const fileIndexInfo = document.querySelector("#fileIndexInfo");
const latencyInfo = document.querySelector("#latencyInfo");
const serverInfo = document.querySelector("#serverInfo");
const versionInfo = document.querySelector("#versionInfo");
const backendHealthIndicator = document.querySelector(".backend-health-indicator");
const backendHealthStatus = document.querySelector("#backendHealthStatus");
const backendHealthText = document.querySelector("#backendHealthText");
const backendHealthDetails = document.querySelector("#backendHealthDetails");
const backendHealthDetailsList = document.querySelector("#backendHealthDetailsList");
const resourceStatusIndicator = document.querySelector(".resource-status-indicator");
const resourceStatus = document.querySelector("#resourceStatus");
const resourceStatusText = document.querySelector("#resourceStatusText");
const resourceDetails = document.querySelector("#resourceDetails");
const resourceDetailsList = document.querySelector("#resourceDetailsList");
const githubStatusButton = document.querySelector("#githubStatusButton");
const githubStatusModal = document.querySelector("#githubStatusModal");
const githubStatusOutput = document.querySelector("#githubStatusOutput");
const githubStatusCheckedAt = document.querySelector("#githubStatusCheckedAt");
const similarDecisionModal = document.querySelector("#similarDecisionModal");
const similarDecisionList = document.querySelector("#similarDecisionList");
const similarDecisionRejectAllButton = document.querySelector("#similarDecisionRejectAllButton");
const similarDecisionContinueButton = document.querySelector("#similarDecisionContinueButton");
const similarDecisionCloseButton = document.querySelector("#similarDecisionCloseButton");
const submitButton = document.querySelector("#submitButton");
const clearButton = document.querySelector("#clearButton");
const logoutButton = document.querySelector("#logoutButton");
const themeToggleButton = document.querySelector("#themeToggleButton");
const entrySelect = document.querySelector("#entrySelect");
const findByEanButton = document.querySelector("#findByEanButton");
const findProductButton = document.querySelector("#findProductButton");
const pimcoreEditButton = document.querySelector("#pimcoreEditButton");
const webImagesButton = document.querySelector("#webImagesButton");
const activeUsersPresence = document.querySelector("#activeUsersPresence");
const activeUsersList = document.querySelector("#activeUsersList");
const activeUsersMoreButton = document.querySelector("#activeUsersMoreButton");
const activeUsersPopover = document.querySelector("#activeUsersPopover");
const webImageUrl = document.querySelector("#webImageUrl");
const scanWebImagesButton = document.querySelector("#scanWebImagesButton");
const webImagesModal = document.querySelector("#webImagesModal");
const webImagesStatus = document.querySelector("#webImagesStatus");
const webImagesOutput = document.querySelector("#webImagesOutput");
const webImageScanMode = document.querySelector("#webImageScanMode");
const webImageMinWidth = document.querySelector("#webImageMinWidth");
const webImageMinHeight = document.querySelector("#webImageMinHeight");
const webImageMinKb = document.querySelector("#webImageMinKb");
const webImageUrlFilter = document.querySelector("#webImageUrlFilter");
const webImageHideThumbnails = document.querySelector("#webImageHideThumbnails");
const browserExtensionDownload = document.querySelector("#browserExtensionDownload");
const browserExtensionHelpButton = document.querySelector("#browserExtensionHelpButton");
const browserExtensionHelp = document.querySelector("#browserExtensionHelp");
const browserExtensionReceiveButton = document.querySelector("#browserExtensionReceiveButton");
const webImagesSelectVisibleButton = document.querySelector("#webImagesSelectVisibleButton");
const webImagesClearSelectionButton = document.querySelector("#webImagesClearSelectionButton");
const webImagesClearDataButton = document.querySelector("#webImagesClearDataButton");
const webImagesAddButton = document.querySelector("#webImagesAddButton");
const listTabs = document.querySelector("#listTabs");
const listValues = document.querySelector("#listValues");
const listAddForm = document.querySelector("#listAddForm");
const listAddInput = document.querySelector("#listAddInput");
const listStatus = document.querySelector("#listStatus");
const listUsageTitle = document.querySelector("#listUsageTitle");
const listUsageOutput = document.querySelector("#listUsageOutput");
const settingsOutput = document.querySelector("#settingsOutput");
const settingsStatus = document.querySelector("#settingsStatus");
const entryMatches = document.querySelector("#entryMatches");
const historyUserFilter = document.querySelector("#historyUserFilter");
const historySearchInput = document.querySelector("#historySearchInput");
const historyRefreshButton = document.querySelector("#historyRefreshButton");
const historyPrevButton = document.querySelector("#historyPrevButton");
const historyNextButton = document.querySelector("#historyNextButton");
const historyPageInfo = document.querySelector("#historyPageInfo");
const historyOutput = document.querySelector("#historyOutput");
const historyDetailTitle = document.querySelector("#historyDetailTitle");
const historyDetailOutput = document.querySelector("#historyDetailOutput");
const historyDetailPrevButton = document.querySelector("#historyDetailPrevButton");
const historyDetailNextButton = document.querySelector("#historyDetailNextButton");
const historyDetailPageInfo = document.querySelector("#historyDetailPageInfo");
const historyTimingTitle = document.querySelector("#historyTimingTitle");
const historyTimingOutput = document.querySelector("#historyTimingOutput");
const historyChangesModal = document.querySelector("#historyChangesModal");
const historyChangesTitle = document.querySelector("#historyChangesTitle");
const historyChangesOutput = document.querySelector("#historyChangesOutput");
const historyChangesCloseButton = document.querySelector("#historyChangesCloseButton");
const pimcoreTestModal = document.querySelector("#pimcoreTestModal");
const pimcoreTestForm = document.querySelector("#pimcoreTestForm");
const pimcoreLiveLog = document.querySelector("#pimcoreLiveLog");
const pimcoreTestElapsed = document.querySelector("#pimcoreTestElapsed");
const pimcoreTestStatus = document.querySelector("#pimcoreTestStatus");
const pimcoreTestSubmitButton = document.querySelector("#pimcoreTestSubmitButton");
const pimcoreTestRegenerateButton = document.querySelector("#pimcoreTestRegenerateButton");
const pimcoreTestClearButton = document.querySelector("#pimcoreTestClearButton");
const pimcoreTestCloseButton = document.querySelector("#pimcoreTestCloseButton");
const pimcoreTemplateModal = document.querySelector("#pimcoreTemplateModal");
const pimcoreTemplateTarget = document.querySelector("#pimcoreTemplateTarget");
const pimcoreTemplateText = document.querySelector("#pimcoreTemplateText");
const pimcoreTemplateSqlControls = document.querySelector("#pimcoreTemplateSqlControls");
const pimcoreTemplateSources = document.querySelector("#pimcoreTemplateSources");
const pimcoreTemplateFunctions = document.querySelector("#pimcoreTemplateFunctions");
const pimcoreTemplateTranslate = document.querySelector("#pimcoreTemplateTranslate");
const pimcoreTemplateLanguage = document.querySelector("#pimcoreTemplateLanguage");
const pimcoreTemplateOcrValidation = document.querySelector("#pimcoreTemplateOcrValidation");
const pimcoreTemplatePreview = document.querySelector("#pimcoreTemplatePreview");
const pimcoreTemplateStatus = document.querySelector("#pimcoreTemplateStatus");
const pimcoreTemplatePreviewButton = document.querySelector("#pimcoreTemplatePreviewButton");
const pimcoreTemplateSaveButton = document.querySelector("#pimcoreTemplateSaveButton");
const pimcoreTemplateClearButton = document.querySelector("#pimcoreTemplateClearButton");
const pimcoreTemplateCancelButton = document.querySelector("#pimcoreTemplateCancelButton");
const pimcoreTemplateHelpButton = document.querySelector("#pimcoreTemplateHelpButton");
const pimcoreTemplateHelpModal = document.querySelector("#pimcoreTemplateHelpModal");
const pimcoreTemplateHelpCloseButton = document.querySelector("#pimcoreTemplateHelpCloseButton");
const pimcoreTemplateHelpList = document.querySelector("#pimcoreTemplateHelpList");
const pimcoreTemplateHelpDetail = document.querySelector("#pimcoreTemplateHelpDetail");
const pimcoreHistoryModal = document.querySelector("#pimcoreHistoryModal");
const pimcoreHistoryFilters = document.querySelector("#pimcoreHistoryFilters");
const pimcoreHistoryOutput = document.querySelector("#pimcoreHistoryOutput");
const pimcoreHistoryCloseButton = document.querySelector("#pimcoreHistoryCloseButton");
const pimcoreHistoryExportCsvButton = document.querySelector("#pimcoreHistoryExportCsvButton");
const pimcoreHistoryExportXlsxButton = document.querySelector("#pimcoreHistoryExportXlsxButton");
const pimcoreExportModal = document.querySelector("#pimcoreExportModal");
const pimcoreExportCloseButton = document.querySelector("#pimcoreExportCloseButton");
const pimcoreExportCsvButton = document.querySelector("#pimcoreExportCsvButton");
const pimcoreExportXlsxButton = document.querySelector("#pimcoreExportXlsxButton");
const pimcoreExportLayoutModal = document.querySelector("#pimcoreExportLayoutModal");
const pimcoreExportLayoutList = document.querySelector("#pimcoreExportLayoutList");
const pimcoreExportLayoutCloseButton = document.querySelector("#pimcoreExportLayoutCloseButton");
const pimcoreExportLayoutCancelButton = document.querySelector("#pimcoreExportLayoutCancelButton");
const pimcoreExportLayoutSaveButton = document.querySelector("#pimcoreExportLayoutSaveButton");
const pimcoreExportLayoutAddFieldButton = document.querySelector("#pimcoreExportLayoutAddFieldButton");
const pimcoreExportLayoutAddBlankButton = document.querySelector("#pimcoreExportLayoutAddBlankButton");
let pimcoreExportLayoutDraft = [];
const pimcoreExportLayoutSelection = new Set();
let pimcoreExportLayoutDragState = null;
let pimcoreExportLayoutMarquee = null;
const pimcoreMissingModal = document.querySelector("#pimcoreMissingModal");
const pimcoreMissingMessage = document.querySelector("#pimcoreMissingMessage");
const pimcoreMissingCreateButton = document.querySelector("#pimcoreMissingCreateButton");
const pimcoreMissingContinueButton = document.querySelector("#pimcoreMissingContinueButton");
const pimcoreMissingCancelButton = document.querySelector("#pimcoreMissingCancelButton");
const pimcoreCreateModal = document.querySelector("#pimcoreCreateModal");
const pimcoreCreateForm = document.querySelector("#pimcoreCreateForm");
const pimcoreCreateOcrPanel = document.querySelector("#pimcoreCreateOcrPanel");
const pimcoreCreateSubmitButton = document.querySelector("#pimcoreCreateSubmitButton");
const pimcoreCreateRecalculateAllButton = document.querySelector("#pimcoreCreateRecalculateAllButton");
const pimcoreCreateCancelButton = document.querySelector("#pimcoreCreateCancelButton");
const pimcoreCreateStatus = document.querySelector("#pimcoreCreateStatus");
const pimcoreEditModal = document.querySelector("#pimcoreEditModal");
const pimcoreEditForm = document.querySelector("#pimcoreEditForm");
const pimcoreEditOcrPanel = document.querySelector("#pimcoreEditOcrPanel");
const pimcoreEditSubmitButton = document.querySelector("#pimcoreEditSubmitButton");
const pimcoreEditRecalculateAllButton = document.querySelector("#pimcoreEditRecalculateAllButton");
const pimcoreEditCancelButton = document.querySelector("#pimcoreEditCancelButton");
const pimcoreEditStatus = document.querySelector("#pimcoreEditStatus");
const pimcoreEditObjectInfo = document.querySelector("#pimcoreEditObjectInfo");
const pimcoreSetupModal = document.querySelector("#pimcoreSetupModal");
const pimcoreSetupForm = document.querySelector("#pimcoreSetupForm");
const pimcoreSetupStepTitle = document.querySelector("#pimcoreSetupStepTitle");
const pimcoreSetupBody = document.querySelector("#pimcoreSetupBody");
const pimcoreSetupProgress = document.querySelector("#pimcoreSetupProgress");
const pimcoreSetupBackButton = document.querySelector("#pimcoreSetupBackButton");
const pimcoreSetupNextButton = document.querySelector("#pimcoreSetupNextButton");
const pimcoreSetupCancelButton = document.querySelector("#pimcoreSetupCancelButton");
const pimcoreSetupStatus = document.querySelector("#pimcoreSetupStatus");
const backupHistoryOutput = document.querySelector("#backupHistoryOutput");
const backupDiffOutput = document.querySelector("#backupDiffOutput");
const logsRefreshButton = document.querySelector("#logsRefreshButton");
const logsClearButton = document.querySelector("#logsClearButton");
const logsClearForm = document.querySelector("#logsClearForm");
const logsClearPassword = document.querySelector("#logsClearPassword");
const logsClearStatus = document.querySelector("#logsClearStatus");
const logsOutput = document.querySelector("#logsOutput");
const logsButton = document.querySelector('[data-modal="logs"]');
const logsView = document.querySelector("#logsView");
const logsFilters = document.querySelector("#logsFilters");
const logsTextFilter = document.querySelector("#logsTextFilter");
const logsSeverityFilter = document.querySelector("#logsSeverityFilter");
const logsModuleFilter = document.querySelector("#logsModuleFilter");
const logsUserFilter = document.querySelector("#logsUserFilter");
const logsEanFilter = document.querySelector("#logsEanFilter");
const logsJobFilter = document.querySelector("#logsJobFilter");
const logsPauseButton = document.querySelector("#logsPauseButton");
const logsAutoscrollToggle = document.querySelector("#logsAutoscrollToggle");
const logsStreamStatus = document.querySelector("#logsStreamStatus");
const logsLoadMoreButton = document.querySelector("#logsLoadMoreButton");
const secretRevealModal = document.querySelector("#secretRevealModal");
const secretRevealForm = document.querySelector("#secretRevealForm");
const secretRevealPassword = document.querySelector("#secretRevealPassword");
const secretRevealStatus = document.querySelector("#secretRevealStatus");
const processAlertModal = document.querySelector("#processAlertModal");
const processAlertTitle = document.querySelector("#processAlertTitle");
const processAlertMessage = document.querySelector("#processAlertMessage");
const processAlertEntry = document.querySelector("#processAlertEntry");
const processAlertLoadButton = document.querySelector("#processAlertLoadButton");

function isSameOriginRequest(path) {
  try {
    return new URL(path, window.location.href).origin === window.location.origin;
  } catch (_error) {
    return true;
  }
}

function isMutatingRequest(options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  return !CSRF_SAFE_METHODS.has(method);
}

function activePresenceClientId() {
  if (state.activePresenceClientId) {
    return state.activePresenceClientId;
  }
  const key = "picsyncra-active-presence-client-id";
  try {
    const stored = sessionStorage.getItem(key);
    if (stored) {
      state.activePresenceClientId = stored;
      return stored;
    }
  } catch (_error) {
    // Session storage can be disabled; keep the generated ID in memory for this page.
  }
  const generated =
    window.crypto?.randomUUID?.() ||
    `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  state.activePresenceClientId = generated;
  try {
    sessionStorage.setItem(key, generated);
  } catch (_error) {
    // In-memory ID is enough when storage is unavailable.
  }
  return generated;
}

function applyClientIdentityHeader(path, fetchOptions) {
  if (!isSameOriginRequest(path)) {
    return;
  }
  const clientId = activePresenceClientId();
  if (!clientId) {
    return;
  }
  const headers = new Headers(fetchOptions.headers || {});
  headers.set(CLIENT_ID_HEADER, clientId);
  fetchOptions.headers = headers;
}

function applyPanelRequestHeaders(path, fetchOptions) {
  if (!isMutatingRequest(fetchOptions) || !isSameOriginRequest(path)) {
    return;
  }
  const headers = new Headers(fetchOptions.headers || {});
  headers.set("X-Requested-With", "XMLHttpRequest");
  if (state.csrfToken) {
    headers.set(CSRF_HEADER, state.csrfToken);
  }
  fetchOptions.headers = headers;
}

async function requestJson(path, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 0);
  const fetchOptions = { ...options };
  delete fetchOptions.timeoutMs;
  const externalSignal = fetchOptions.signal || null;
  applyClientIdentityHeader(path, fetchOptions);
  applyPanelRequestHeaders(path, fetchOptions);
  let timeoutId = 0;
  let externalAbortHandler = null;
  let timedOut = false;
  if (timeoutMs > 0) {
    const controller = new AbortController();
    fetchOptions.signal = controller.signal;
    if (externalSignal) {
      externalAbortHandler = () => controller.abort();
      if (externalSignal.aborted) externalAbortHandler();
      else externalSignal.addEventListener("abort", externalAbortHandler, { once: true });
    }
    timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  let response;
  try {
    response = await fetch(path, fetchOptions);
  } catch (error) {
    if (error?.name === "AbortError" && externalSignal && !timedOut) {
      throw error;
    }
    if (error?.name === "AbortError") {
      throw new Error(
        `Backend nie odpowiedzial w ciagu ${Math.round(timeoutMs / 1000)} s (${path}). ` +
          "Jesli podales folder sieciowy albo dysk mapowany, sprawdz dostep backendu do tej lokalizacji."
      );
    }
    throw new Error(
      `Nie udalo sie polaczyc z backendem (${path}). Sprawdz, czy serwer web dziala. Szczegoly: ${
        error.message || error
      }`
    );
  } finally {
    if (timeoutId) {
      window.clearTimeout(timeoutId);
    }
    if (externalSignal && externalAbortHandler) {
      externalSignal.removeEventListener("abort", externalAbortHandler);
    }
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.location.href = "/login";
    }
    const detail = payload.detail;
    const message =
      typeof detail === "string" ? detail : detail?.message || "Operacja nie powiodla sie.";
    const error = new Error(message);
    error.status = response.status;
    error.detail = detail;
    error.payload = payload;
    throw error;
  }
  if (payload.csrf_token) {
    state.csrfToken = payload.csrf_token;
  }
  return payload;
}

function clientFailureFingerprint(payload) {
  return JSON.stringify([
    payload.kind || "",
    payload.message || "",
    payload.source || "",
    Number(payload.line || 0),
    Number(payload.column || 0),
    payload.stack || "",
  ]);
}

async function reportClientFailure(payload) {
  const now = Date.now();
  const fingerprint = clientFailureFingerprint(payload);
  const lastReportedAt = Number(clientFailureFingerprints.get(fingerprint) || 0);
  if (now - lastReportedAt < CLIENT_FAILURE_DEDUPE_MS) return;
  clientFailureFingerprints.set(fingerprint, now);
  for (const [key, reportedAt] of clientFailureFingerprints.entries()) {
    if (now - reportedAt >= CLIENT_FAILURE_DEDUPE_MS) {
      clientFailureFingerprints.delete(key);
    }
  }
  await requestJson("/api/observability/client-errors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

window.addEventListener("error", (event) => {
  reportClientFailure({
    kind: "error",
    message: event.message || "Frontend error",
    source: event.filename || "",
    line: Number(event.lineno || 0),
    column: Number(event.colno || 0),
    stack: event.error?.stack || "",
  }).catch(() => {});
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  reportClientFailure({
    kind: "unhandledrejection",
    message: reason?.message || String(reason || "Unhandled promise rejection"),
    source: "",
    line: 0,
    column: 0,
    stack: reason?.stack || "",
  }).catch(() => {});
});

function updateAdminUi() {
  state.isAdmin = state.currentUser?.role === "admin";
  document.querySelectorAll(".admin-only").forEach((node) => {
    node.hidden = !state.isAdmin;
  });
  if (!state.isAdmin) {
    stopObservabilityStream();
    updateLogAlert({});
  }
}

function setActiveModalNav(name = "") {
  document.querySelectorAll("[data-modal]").forEach((button) => {
    button.classList.toggle("active", button.dataset.modal === name);
  });
}

function applyTheme() {
  document.body.dataset.theme = state.theme;
  if (themeToggleButton) {
    themeToggleButton.textContent = state.theme === "dark" ? "Jasny" : "Ciemny";
  }
  localStorage.setItem("picsyncra-theme", state.theme);
}

function openModal(name) {
  if (!name) {
    return;
  }
  if ((name === "settings" || name === "logs") && !state.isAdmin) {
    formStatus.textContent = "Ten widok jest dostepny tylko dla administratora.";
    return;
  }
  autocompleteControls.closePanels();
  document.querySelector(`#${name}View`)?.classList.add("active");
  document.querySelector(`#${name}Modal`)?.classList.add("active");
  setActiveModalNav(name);
  if (name === "settings") {
    loadSettings().catch((error) => {
      settingsStatus.textContent = error.message;
    });
  }
  if (name === "history") {
    loadHistory().catch(showHistoryLoadError);
  }
  if (name === "logs") {
    loadLogs().catch((error) => {
      logsOutput.textContent = error.message;
    });
  }
}

function githubRow(label, value, url = "") {
  const row = document.createElement("div");
  row.className = "github-status-row";
  const title = document.createElement("strong");
  title.textContent = label;
  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = value || url;
    row.append(title, link);
  } else {
    const text = document.createElement("span");
    text.textContent = value || "Brak informacji";
    row.append(title, text);
  }
  return row;
}

function renderGithubStatus(payload = {}) {
  state.githubStatus = payload || {};
  if (githubStatusButton) {
    githubStatusButton.classList.toggle("update-available", Boolean(payload.update_available));
    githubStatusButton.title = payload.update_available
      ? "Dostepna jest nowsza wersja na GitHub"
      : "Informacje o repozytorium GitHub";
  }
  if (!githubStatusOutput) return;
  githubStatusOutput.textContent = "";
  if (!payload.available) {
    githubStatusOutput.classList.add("empty-state");
    githubStatusOutput.appendChild(
      githubRow("Status", payload.message || "Repozytorium jest prywatne albo niedostepne.")
    );
  } else {
    githubStatusOutput.classList.remove("empty-state");
    const repo = payload.repository || {};
    const release = payload.latest_release || {};
    const license = payload.license || {};
    const owner = payload.owner || {};
    const contributors = Array.isArray(payload.contributors) ? payload.contributors : [];
    githubStatusOutput.append(
      githubRow("Repozytorium", repo.full_name || "PicSyncra", repo.html_url || ""),
      githubRow("Wersja lokalna", payload.current_version || "dev"),
      githubRow(
        payload.update_available ? "Aktualizacja" : "Najnowszy release",
        release.tag_name
          ? `${release.tag_name}${
              release.published_at ? ` (${formatPanelTimestamp(release.published_at)})` : ""
            }`
          : "Brak publicznego release",
        release.html_url || ""
      ),
      githubRow("Licencja", license.spdx_id || license.name || "Brak informacji"),
      githubRow("Wlasciciel", owner.login || "Brak informacji", owner.html_url || ""),
      githubRow(
        "Contributors",
        contributors.length
          ? contributors.map((item) => `${item.login} (${item.contributions || 0})`).join(", ")
          : "Brak dodatkowych contributors"
      )
    );
  }
  if (githubStatusCheckedAt) {
    githubStatusCheckedAt.textContent = payload.checked_at
      ? `Sprawdzono: ${formatPanelTimestamp(payload.checked_at)}`
      : "";
  }
}

async function refreshGithubStatus(options = {}) {
  if (state.githubStatusLoading) return state.githubStatus;
  state.githubStatusLoading = true;
  try {
    const payload = await requestJson("/api/github/repository", options);
    renderGithubStatus(payload);
    return payload;
  } catch (error) {
    const payload = {
      available: false,
      private: false,
      message: error.message || "Nie udalo sie pobrac danych GitHub.",
      update_available: false,
    };
    renderGithubStatus(payload);
    return payload;
  } finally {
    state.githubStatusLoading = false;
  }
}

function openGithubStatusModal() {
  autocompleteControls.closePanels();
  githubStatusModal?.classList.add("active");
  if (!state.githubStatus) {
    if (githubStatusOutput) githubStatusOutput.textContent = "Pobieranie danych GitHub...";
    refreshGithubStatus().catch(() => {});
  }
}

function closeModals() {
  stopObservabilityStream();
  closeHistoryChangesModal({ restoreFocus: false });
  closeHistoryDetail();
  document.querySelectorAll(".modal-view").forEach((modal) => modal.classList.remove("active"));
  if (logsClearPassword) logsClearPassword.value = "";
  if (logsClearStatus) logsClearStatus.textContent = "";
  closeSecretRevealModal();
  toggleActiveUsersPopover(false);
  setActiveModalNav("");
}

function activeUserLastSeenLabel(user = {}) {
  const text = formatPanelTimestamp(user.last_seen_epoch, { epochUnit: "seconds" });
  return text === "Brak danych" ? "Aktywny" : `Ostatnio: ${text}`;
}

function toggleActiveUsersPopover(force) {
  if (!activeUsersPopover || !activeUsersMoreButton) {
    return;
  }
  const nextOpen = force === undefined ? activeUsersPopover.hidden : Boolean(force);
  activeUsersPopover.hidden = !nextOpen;
  activeUsersMoreButton.setAttribute("aria-expanded", nextOpen ? "true" : "false");
}

function renderActiveUsersPresence(payload = {}) {
  if (!activeUsersPresence || !activeUsersList || !activeUsersMoreButton || !activeUsersPopover) {
    return;
  }
  const users = Array.isArray(payload.users) ? payload.users : [];
  const enabled = Boolean(payload.enabled);
  state.activeUsersEnabled = enabled;
  state.activeUsers = users;
  activeUsersList.textContent = "";
  activeUsersPopover.textContent = "";
  const visibleUsers = users.slice(0, ACTIVE_USERS_VISIBLE_LIMIT);
  activeUsersPresence.hidden = !enabled || !users.length;
  activeUsersMoreButton.hidden = users.length <= ACTIVE_USERS_VISIBLE_LIMIT;
  if (activeUsersMoreButton.hidden) {
    toggleActiveUsersPopover(false);
  }
  if (!enabled || !users.length) {
    toggleActiveUsersPopover(false);
    return;
  }
  for (const user of visibleUsers) {
    const label = document.createElement("span");
    const dot = document.createElement("span");
    const name = document.createElement("span");
    label.className = "presence-user-label";
    dot.className = "presence-user-dot";
    dot.setAttribute("aria-hidden", "true");
    name.textContent = String(user.username || "");
    label.title = activeUserLastSeenLabel(user);
    label.append(dot, name);
    activeUsersList.appendChild(label);
  }
  for (const user of users) {
    const row = document.createElement("div");
    const name = document.createElement("strong");
    const seen = document.createElement("span");
    row.className = "active-users-popover-row";
    name.textContent = String(user.username || "");
    seen.textContent = activeUserLastSeenLabel(user);
    row.append(name, seen);
    activeUsersPopover.appendChild(row);
  }
}

async function refreshActiveUsersPresence() {
  const payload = await requestJson("/api/server/presence");
  renderActiveUsersPresence(payload);
}

function notifyActiveUsersPresenceLeave() {
  const clientId = activePresenceClientId();
  if (!clientId) {
    return;
  }
  const headers = {
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    [CLIENT_ID_HEADER]: clientId,
  };
  if (state.csrfToken) {
    headers[CSRF_HEADER] = state.csrfToken;
  }
  fetch("/api/server/presence/leave", {
    method: "POST",
    headers,
    body: "{}",
    keepalive: true,
  }).catch(() => {});
}

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

function recordOcrActivity({ removedSlotToken = "", kind = "slot-change" } = {}) {
  return requestJson("/api/ocr/activity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind,
      removed_slot_token: String(removedSlotToken || "").trim(),
    }),
  }).catch(() => {});
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

function fileLabel(file) {
  const item = slotFileItem(file);
  if (!item) {
    return "Brak pliku";
  }
  const kb = Math.max(1, Math.round(slotFileSize(item) / 1024));
  const base = `${slotFileName(item)} (${kb} KB)`;
  if (slotUploadError(item)) return `${base} - blad uploadu: ${slotUploadError(item)}`;
  if (isSlotUploadActive(item)) return `${base} - wysylanie ${slotUploadProgress(item)}%`;
  if (slotFileToken(item)) return `${base} - w cache`;
  return base;
}

function formatDuration(ms) {
  const value = Math.max(0, Number(ms || 0));
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 10000) return `${(value / 1000).toFixed(2)} s`;
  return `${(value / 1000).toFixed(1)} s`;
}

function formatFileSize(bytes) {
  const value = Math.max(0, Number(bytes || 0));
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function resourceNumber(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatPercent(value) {
  const number = resourceNumber(value);
  return number === null ? "brak danych" : `${Math.round(number)}%`;
}

function formatMib(bytes) {
  const number = resourceNumber(bytes);
  return number === null ? "brak danych" : `${(number / (1024 * 1024)).toFixed(1)} MB`;
}

function formatResourceBytes(bytes) {
  const number = resourceNumber(bytes);
  return number === null ? "brak danych" : formatFileSize(number);
}

function resourceLevel(detector = {}) {
  return Array.isArray(detector.latched_metrics) && detector.latched_metrics.length
    ? "critical"
    : "normal";
}

function webImageDimensions(image) {
  const width = Number(image?.width || 0);
  const height = Number(image?.height || 0);
  return width && height ? `${width} x ${height}` : "rozmiar nieznany";
}

function webImageFilters() {
  return {
    minWidth: Math.max(0, Number(webImageMinWidth?.value || 0)),
    minHeight: Math.max(0, Number(webImageMinHeight?.value || 0)),
    minKb: Math.max(0, Number(webImageMinKb?.value || 0)),
    urlFilter: String(webImageUrlFilter?.value || "").trim(),
    hideThumbnails: Boolean(webImageHideThumbnails?.checked),
  };
}

function isThumbnailWebImage(image) {
  const width = Number(image?.width || 0);
  const height = Number(image?.height || 0);
  return image?.kind === "thumbnail" || (width > 0 && height > 0 && Math.max(width, height) < 300);
}

function parseWebImageUrlFilter(text) {
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

function webImageMatchesUrlFilter(image, text) {
  const parsed = parseWebImageUrlFilter(text);
  const haystack = `${image?.url || ""} ${image?.filename || ""} ${image?.source || ""}`.toLowerCase();
  if (parsed.exclude.some((group) => group.some((term) => haystack.includes(term)))) return false;
  if (parsed.include.some((group) => !group.some((term) => haystack.includes(term)))) return false;
  return true;
}

function webImagePassesFilters(image, filters = webImageFilters()) {
  const width = Number(image?.width || 0);
  const height = Number(image?.height || 0);
  const kb = Number(image?.size_bytes || 0) / 1024;
  const unknownPasses = state.webImageScanMode === "links";
  if (!webImageMatchesUrlFilter(image, filters.urlFilter)) return false;
  if (filters.minWidth && width && width < filters.minWidth) return false;
  if (filters.minWidth && !width && !unknownPasses) return false;
  if (filters.minHeight && height && height < filters.minHeight) return false;
  if (filters.minHeight && !height && !unknownPasses) return false;
  if (filters.minKb && kb && kb < filters.minKb) return false;
  if (filters.minKb && !kb && !unknownPasses) return false;
  if (filters.hideThumbnails && isThumbnailWebImage(image)) return false;
  return true;
}

function visibleWebImageEntries() {
  const filters = webImageFilters();
  return (state.webImages || [])
    .map((image, index) => ({ image, index }))
    .filter((entry) => webImagePassesFilters(entry.image, filters));
}

function webImageCacheKey(image) {
  return String(image?.url || "").trim();
}

function webImageCacheEntry(image) {
  return state.webImageCache.get(webImageCacheKey(image)) || null;
}

function webImageCacheLabel(image) {
  const entry = webImageCacheEntry(image);
  if (!entry) return "";
  if (entry.status === "queued") return "oczekuje";
  if (entry.status === "loading") return "pobieranie";
  if (entry.status === "ready") return "w cache";
  if (entry.status === "error") return "blad cache";
  return "";
}

function queueWebImageCache(image, prefix = "web", { retry = false, render = true } = {}) {
  const key = webImageCacheKey(image);
  if (!key) return null;
  const existing = state.webImageCache.get(key);
  if (existing && existing.status !== "error") return existing;
  if (existing && existing.status === "error" && !retry) return existing;
  const entry = {
    status: "queued",
    payload: null,
    error: "",
    promise: null,
  };
  state.webImageCache.set(key, entry);
  state.webImageCacheQueue.push({ key, image, prefix });
  pumpWebImageCacheQueue();
  if (render) {
    renderWebImagesPicker();
  }
  return entry;
}

function pumpWebImageCacheQueue() {
  while (state.webImageCacheActive < WEB_IMAGE_CACHE_LIMIT && state.webImageCacheQueue.length) {
    const task = state.webImageCacheQueue.shift();
    const entry = state.webImageCache.get(task.key);
    if (!entry || entry.status !== "queued") continue;
    state.webImageCacheActive += 1;
    entry.status = "loading";
    entry.promise = cacheWebImageForSlot(task.image, task.prefix)
      .then((payload) => {
        entry.status = "ready";
        entry.payload = payload;
        entry.error = "";
        return payload;
      })
      .catch((error) => {
        entry.status = "error";
        entry.error = error.message || String(error);
        throw error;
      })
      .finally(() => {
        state.webImageCacheActive = Math.max(0, state.webImageCacheActive - 1);
        renderWebImagesPicker();
        pumpWebImageCacheQueue();
      });
    entry.promise.catch(() => {});
    renderWebImagesPicker();
  }
}

async function cachedWebImagePayload(image, prefix) {
  let entry = webImageCacheEntry(image);
  if (!entry || entry.status === "error") {
    entry = queueWebImageCache(image, prefix, { retry: true });
  }
  if (!entry) {
    throw new Error("Nie udalo sie przygotowac cache zdjecia.");
  }
  if (entry.payload) {
    return entry.payload;
  }
  if (entry.promise) {
    return entry.promise;
  }
  pumpWebImageCacheQueue();
  if (entry.promise) {
    return entry.promise;
  }
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (entry.payload) {
        window.clearInterval(timer);
        resolve(entry.payload);
      } else if (entry.status === "error") {
        window.clearInterval(timer);
        reject(new Error(entry.error || "Nie udalo sie pobrac zdjecia."));
      } else if (Date.now() - started > 60000) {
        window.clearInterval(timer);
        reject(new Error("Przekroczono czas oczekiwania na pobranie zdjecia."));
      }
    }, 200);
  });
}

function openWebImagesModal() {
  webImagesModal?.classList.add("active");
  webImageUrl?.focus();
}

function closeWebImagesModal() {
  webImagesModal?.classList.remove("active");
}

function clearLoadedWebImages() {
  state.webImages = [];
  state.webImageSelected.clear();
  state.webImagePageUrl = "";
  state.webImageCache.clear();
  state.webImageCacheQueue = [];
  state.webImageCacheActive = 0;
  if (webImagesStatus) {
    webImagesStatus.textContent = "";
  }
  if (webImagesOutput) {
    webImagesOutput.textContent = "Brak pobranych zdjec.";
    webImagesOutput.classList.add("empty-state");
  }
  formStatus.textContent = "Wyczyszczono wczytane zdjecia WWW.";
}

function renderWebImagesPicker() {
  if (!webImagesOutput) return;
  const visible = visibleWebImageEntries();
  const selectedVisible = visible.filter((entry) => state.webImageSelected.has(entry.index)).length;
  if (webImagesStatus) {
    webImagesStatus.textContent = `${selectedVisible}/${visible.length} zaznaczonych, ${state.webImages.length} wykrytych`;
  }
  webImagesOutput.textContent = "";
  webImagesOutput.classList.toggle("empty-state", !visible.length);
  if (!visible.length) {
    webImagesOutput.textContent = state.webImages.length
      ? "Filtry ukryly wszystkie zdjecia."
      : "Brak pobranych zdjec.";
    return;
  }
  for (const { image, index } of visible) {
    const card = document.createElement("article");
    const preview = document.createElement("div");
    const img = document.createElement("img");
    const checkbox = document.createElement("input");
    const meta = document.createElement("div");
    const title = document.createElement("strong");
    const dimensions = document.createElement("span");
    const size = document.createElement("span");
    const format = document.createElement("span");
    const source = document.createElement("span");
    const cache = document.createElement("span");
    checkbox.type = "checkbox";
    checkbox.checked = state.webImageSelected.has(index);
    checkbox.setAttribute("aria-label", `Wybierz obraz ${image.filename || index + 1}`);
    img.loading = "lazy";
    img.decoding = "async";
    img.alt = "";
    img.src = image.preview_url || image.thumb_url || image.url;
    preview.className = "web-image-preview";
    preview.append(checkbox, img);
    title.textContent = image.filename || `Obraz ${index + 1}`;
    dimensions.textContent = webImageDimensions(image);
    size.textContent = formatFileSize(image.size_bytes || 0);
    format.textContent = image.mime_type || "format nieznany";
    source.textContent = isThumbnailWebImage(image) ? "miniatura" : image.source || "obraz";
    cache.textContent = webImageCacheLabel(image);
    meta.className = "web-image-meta";
    meta.append(title, dimensions, format, size, source);
    if (cache.textContent) {
      meta.append(cache);
    }
    card.className = `web-image-card ${checkbox.checked ? "selected" : ""}`;
    card.title = image.url;
    card.append(preview, meta);
    const setSelected = (selected) => {
      if (selected) {
        state.webImageSelected.add(index);
        queueWebImageCache(image, "web");
      } else {
        state.webImageSelected.delete(index);
      }
      checkbox.checked = selected;
      card.classList.toggle("selected", selected);
      renderWebImagesPicker();
    };
    checkbox.addEventListener("change", () => setSelected(checkbox.checked));
    card.addEventListener("click", (event) => {
      if (event.target === checkbox) return;
      setSelected(!state.webImageSelected.has(index));
    });
    webImagesOutput.appendChild(card);
  }
}

function webImagesErrorHelp(message) {
  const text = String(message || "");
  if (/cloudflare|challenge\s*403/i.test(text)) {
    return [
      "Strona pokazuje zabezpieczenie Cloudflare/challenge 403.",
      "Importer nie dostaje wtedy HTML-a produktu, tylko strone blokady, wiec nie ma z czego wyciagnac linkow do zdjec.",
      "To zwykle wymaga sesji prawdziwej przegladarki albo cookies z tej strony.",
    ];
  }
  if (/403|forbidden/i.test(text)) {
    return [
      "Serwer odrzucil pobieranie strony kodem 403 Forbidden.",
      "Najczesciej oznacza to blokade botow, brak wymaganej sesji albo ograniczenie hotlinkowania.",
    ];
  }
  if (/html/i.test(text)) {
    return [
      "Podany adres nie zwrocil strony HTML produktu.",
      "Importer potrzebuje strony z linkami do obrazow albo bezposrednich linkow do plikow graficznych.",
    ];
  }
  return ["Nie udalo sie pobrac listy zdjec z podanego adresu."];
}

function renderWebImagesError(error) {
  const message = error?.message || String(error || "Operacja nie powiodla sie.");
  state.webImages = [];
  state.webImageSelected.clear();
  state.webImageCache.clear();
  state.webImageCacheQueue = [];
  state.webImageCacheActive = 0;
  openWebImagesModal();
  if (webImagesStatus) {
    webImagesStatus.textContent = "Nie mozna pobrac zdjec";
  }
  if (!webImagesOutput) {
    return;
  }
  webImagesOutput.textContent = "";
  webImagesOutput.classList.add("empty-state");
  const wrapper = document.createElement("div");
  const title = document.createElement("strong");
  const details = document.createElement("span");
  wrapper.className = "web-image-error";
  title.textContent = message;
  details.textContent = webImagesErrorHelp(message).join(" ");
  wrapper.append(title, details);
  webImagesOutput.appendChild(wrapper);
}

async function scanWebImages() {
  const url = webImageUrl?.value?.trim() || "";
  if (!url) {
    formStatus.textContent = "Wklej link do strony ze zdjeciami.";
    return;
  }
  state.webImageScanMode = webImageScanMode?.value || "links";
  localStorage.setItem("picsyncra-web-image-scan-mode", state.webImageScanMode);
  scanWebImagesButton.disabled = true;
  scanWebImagesButton.textContent = "Pobieranie...";
  formStatus.textContent =
    state.webImageScanMode === "links"
      ? "Skanowanie linkow do zdjec..."
      : "Skanowanie strony i pobieranie metadanych zdjec...";
  try {
    const payload = await requestJson("/api/web-images/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        mode: state.webImageScanMode,
        filters: webImageFilters(),
      }),
      timeoutMs: 60000,
    });
    state.webImagePageUrl = payload.source_url || url;
    state.webImageScanMode = payload.mode || state.webImageScanMode;
    state.webImages = payload.images || [];
    state.webImageSelected.clear();
    state.webImageCache.clear();
    state.webImageCacheQueue = [];
    state.webImageCacheActive = 0;
    openWebImagesModal();
    renderWebImagesPicker();
    formStatus.textContent =
      state.webImageScanMode === "links"
        ? `Wykryto ${state.webImages.length} linkow do zdjec ze strony.`
        : `Wykryto ${state.webImages.length} zdjec spelniajacych warunki.`;
  } catch (error) {
    formStatus.textContent = error.message;
    renderWebImagesError(error);
  } finally {
    scanWebImagesButton.disabled = false;
    scanWebImagesButton.textContent = "Pobierz zdjecia";
  }
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

function webImageCacheItem(prefix, image, payload) {
  return {
    id: ++state.slotUploadRequestId,
    prefix,
    file: null,
    name: payload.name || image.filename || "web-image.jpg",
    size: Number(payload.size_bytes || image.size_bytes || 0),
    type: image.mime_type || "image/jpeg",
    token: payload.token || "",
    url: payload.url || "",
    thumb_url: payload.thumb_url || "",
    file_version: payload.file_version || "",
    ocr_state: payload.ocr_state || "",
    preprocessed: Boolean(payload.preprocessed),
    cache_timing: payload.timing || null,
    client_preprocess_ms: 0,
    progress: 100,
    uploading: false,
    error: "",
    xhr: null,
    provisional: false,
    placementBlocked: false,
  };
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

function imageFromBrowserExtensionItem(item) {
  const cache = item?.cache || {};
  return {
    url: item?.source_url || cache.url || "",
    preview_url: cache.thumb_url || cache.url || item?.source_url || "",
    thumb_url: cache.thumb_url || "",
    filename: item?.filename || cache.name || "web-image.jpg",
    width: Number(item?.width || cache.width || 0),
    height: Number(item?.height || cache.height || 0),
    size_bytes: Number(item?.size_bytes || cache.size_bytes || 0),
    mime_type: item?.mime_type || "image/jpeg",
    source: item?.source || "browser-extension",
    kind: item?.kind || "image",
    page_url: item?.page_url || "",
  };
}

function loadBrowserExtensionItems(items) {
  const imported = [];
  const existingByUrl = new Map(
    (state.webImages || []).map((image, index) => [webImageCacheKey(image), index])
  );
  for (const item of items || []) {
    const image = imageFromBrowserExtensionItem(item);
    if (!image.url) continue;
    const key = webImageCacheKey(image);
    if (!key) continue;
    state.webImageCache.set(key, {
      status: "ready",
      payload: item.cache || item,
      error: "",
      promise: null,
    });
    const existingIndex = existingByUrl.get(key);
    if (existingIndex !== undefined) {
      state.webImages[existingIndex] = {
        ...state.webImages[existingIndex],
        ...image,
      };
      state.webImageSelected.add(existingIndex);
      imported.push(image);
      continue;
    }
    const newIndex = state.webImages.length;
    state.webImages.push(image);
    state.webImageSelected.add(newIndex);
    existingByUrl.set(key, newIndex);
    imported.push(image);
  }
  if (!imported.length) {
    return 0;
  }
  state.webImagePageUrl = state.webImagePageUrl || imported[0]?.page_url || "";
  openWebImagesModal();
  renderWebImagesPicker();
  return imported.length;
}

async function receiveBrowserExtensionImages() {
  if (!browserExtensionReceiveButton) return;
  browserExtensionReceiveButton.disabled = true;
  browserExtensionReceiveButton.textContent = "Odbieranie...";
  try {
    const payload = await requestJson("/api/browser-extension/imports");
    const count = loadBrowserExtensionItems(payload.items || []);
    formStatus.textContent = count
      ? `Odebrano ${count} zdjec z rozszerzenia.`
      : "Brak nowych zdjec z rozszerzenia.";
  } catch (error) {
    formStatus.textContent = error.message;
  } finally {
    browserExtensionReceiveButton.disabled = false;
    browserExtensionReceiveButton.textContent = "Odbierz z rozszerzenia";
  }
}

async function downloadBrowserExtension() {
  if (!browserExtensionDownload) return;
  browserExtensionDownload.disabled = true;
  browserExtensionDownload.textContent = "Pobieranie...";
  try {
    const response = await fetch("/api/browser-extension/download", {
      cache: "no-store",
    });
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok || !contentType.includes("application/zip")) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(
        payload.detail ||
          "Backend nie zwrocil paczki ZIP rozszerzenia. Sprawdz, czy EXE zawiera folder browser_extension."
      );
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "picsyncra-browser-extension.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    formStatus.textContent = "Pobrano paczke rozszerzenia.";
  } catch (error) {
    formStatus.textContent = error.message;
  } finally {
    browserExtensionDownload.disabled = false;
    browserExtensionDownload.textContent = "Pobierz rozszerzenie";
  }
}

function currentProcessingSettings() {
  return state.settings?.processing || state.processing || {};
}

function currentSecuritySettings() {
  return state.settings?.security || state.security || {};
}

function extensionListText(value) {
  if (Array.isArray(value)) return value.join(", ");
  return String(value || "");
}

function normalizeUploadExtensionList(value) {
  const items = Array.isArray(value) ? value : String(value || "").split(/[\s,;]+/);
  return items
    .map((extension) => String(extension || "").trim().toLowerCase().replace(/^\.+/, ""))
    .filter((extension, index, list) => /^[a-z0-9]+$/.test(extension) && list.indexOf(extension) === index);
}

function uploadAcceptAttribute() {
  const security = currentSecuritySettings();
  const allowed = normalizeUploadExtensionList(security.allowed_upload_extensions);
  if (allowed.length) {
    const blocked = normalizeUploadExtensionList(security.blocked_upload_extensions);
    const pickerAllowed = allowed.filter(
      (extension) =>
        !blocked.includes(extension) &&
        !(security.block_executable_uploads !== false && CLIENT_EXECUTABLE_UPLOAD_EXTENSIONS.has(extension))
    );
    return pickerAllowed.length
      ? pickerAllowed.map((extension) => `.${extension}`).join(",")
      : ".picsyncra-no-allowed-upload";
  }
  return [
    "image/*",
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
    ".pdf",
    ".eps",
    ".psd",
    ".ai",
    ".tif",
    ".tiff",
  ].join(",");
}

function uploadProcessingMode() {
  return currentProcessingSettings().upload_processing_mode || "save";
}

function timingPreferenceStorageKey() {
  const username = state.currentUser?.username || "anonymous";
  return `picsyncra-show-timing-${username}`;
}

function showTimingDetails() {
  const stored = localStorage.getItem(timingPreferenceStorageKey());
  if (stored === "1") return true;
  if (stored === "0") return false;
  return Boolean(currentProcessingSettings().show_timing_details);
}

function setTimingDetailsVisible(value) {
  localStorage.setItem(timingPreferenceStorageKey(), value ? "1" : "0");
  applyTimingDetailsVisibility();
}

function applyTimingDetailsVisibility() {
  if (resultSection) {
    resultSection.hidden = !showTimingDetails();
  }
}

function updateRuntimeMetrics() {
  if (fileIndexInfo) {
    const generatedAt = formatPanelTimestamp(state.fileIndex?.generated_at);
    fileIndexInfo.textContent = state.fileIndex?.generated_at
      ? `${state.fileIndex.label || "Indeks lokalny"}: ${generatedAt}`
      : state.fileIndex?.label || "";
    fileIndexInfo.title = state.fileIndex?.error || "";
  }
  if (latencyInfo) {
    latencyInfo.textContent =
      state.lastLookupMs === null ? "" : `ostatnie wczytanie: ${Math.round(state.lastLookupMs)} ms`;
  }
}

function formValue(name) {
  return productForm.elements[name]?.value?.trim() || "";
}

function currentFormPayload() {
  return {
    name: formValue("name"),
    type_name: formValue("type_name"),
    model: formValue("model"),
    color1: formValue("color1"),
    color2: formValue("color2"),
    color3: formValue("color3"),
    extra: formValue("extra"),
  };
}

function uniqueValues(values, limit = Number.POSITIVE_INFINITY) {
  const seen = new Set();
  const result = [];
  const maxItems = Number.isFinite(limit) ? Math.max(1, Number(limit)) : Number.POSITIVE_INFINITY;
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text) continue;
    const key = text.toUpperCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(text);
    if (result.length >= maxItems) break;
  }
  return result;
}

function setOptions(datalistId, values) {
  const datalist = document.querySelector(datalistId);
  datalist.textContent = "";
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    datalist.appendChild(option);
  }
}

function renderDatalists() {
  setOptions("#namesList", state.lists.names);
  setOptions("#typesList", state.lists.types);
  setOptions("#modelsList", state.lists.models);
  setOptions("#colorsList", state.lists.colors);
  setOptions("#extrasList", state.lists.extras);
}

const fieldListKey = {
  name: "names",
  type_name: "types",
  model: "models",
  color1: "colors",
  color2: "colors",
  color3: "colors",
  extra: "extras",
};

const fieldListLabels = {
  name: "Nazwa",
  type_name: "Typ",
  model: "Model",
  color1: "Kolor 1",
  color2: "Kolor 2",
  color3: "Kolor 3",
  extra: "Dodatek",
};

const productFieldDefinitions = {
  name: { input: "name", label: "Nazwa", required: true },
  type: { input: "type_name", label: "Typ", required: true },
  model: { input: "model", label: "Model", required: true },
  color1: { input: "color1", label: "Kolor 1", required: true },
  color2: { input: "color2", label: "Kolor 2", required: false },
  color3: { input: "color3", label: "Kolor 3", required: false },
  extra: { input: "extra", label: "Dodatek", required: false },
  ean: { input: "ean", label: "EAN", required: false },
};

function cleanDisplayLabel(value) {
  return String(value || "")
    .trim()
    .replace(/[:*]+$/g, "")
    .trim();
}

function productFieldLabel(fieldName) {
  const key =
    Object.entries(productFieldDefinitions).find(([_key, item]) => item.input === fieldName)?.[0] ||
    fieldName;
  const definition = productFieldDefinitions[key];
  if (!definition) return fieldListLabels[fieldName] || fieldName;
  return cleanDisplayLabel(state.productFields?.[key]?.label) || definition.label;
}

function normalizedProductFields(raw = {}) {
  return Object.fromEntries(
    Object.entries(productFieldDefinitions).map(([key, defaults]) => {
      const item = raw?.[key] || {};
      const enabled = item.enabled !== false;
      return [
        key,
        {
          label: cleanDisplayLabel(item.label),
          enabled,
          required: enabled && ("required" in item ? Boolean(item.required) : defaults.required),
        },
      ];
    })
  );
}

function applyProductFieldSettings() {
  state.productFields = normalizedProductFields(state.productFields);
  for (const [key, definition] of Object.entries(productFieldDefinitions)) {
    const item = state.productFields[key];
    const container = document.querySelector(`[data-product-field="${key}"]`);
    const label = document.querySelector(`[data-product-field-label="${key}"]`);
    const input = productForm.elements[definition.input];
    if (!container || !label || !input) continue;
    container.hidden = !item.enabled;
    input.disabled = !item.enabled;
    input.required = item.enabled && item.required;
    if (!item.enabled) input.value = "";
    label.textContent = `${item.label || definition.label}${item.required ? " *" : ""}`;
  }
  findByEanButton.hidden = !state.productFields.ean.enabled;
  updateFieldWarnings();
}

function applyProductFieldLabels() {
  applyProductFieldSettings();
}

function listHasValue(listKey, value) {
  const normalized = normalizeListValue(value);
  if (!normalized) return true;
  return (state.lists[listKey] || []).some((item) => normalizeListValue(item) === normalized);
}

function canonicalListValue(listKey, value) {
  const normalized = normalizeListValue(value);
  return (state.lists[listKey] || []).find((item) => normalizeListValue(item) === normalized) || "";
}

async function addValueToList(listKey, value) {
  const payload = await requestJson(`/api/lists/${listKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  state.lists = payload.lists || {};
  state.entries = payload.entries || state.entries;
  renderDatalists();
  renderListEditor();
  return canonicalListValue(listKey, value);
}

async function promptAddProductFieldToList(fieldName, { force = false } = {}) {
  const listKey = fieldListKey[fieldName];
  const input = productForm.elements[fieldName];
  const value = input?.value?.trim() || "";
  if (!listKey || !value || listHasValue(listKey, value)) {
    return false;
  }
  const promptKey = `${listKey}|${normalizeListValue(value)}`;
  if (state.activeListPromptKeys.has(promptKey)) {
    return false;
  }
  if (!force && state.declinedListPrompts.has(promptKey)) {
    return false;
  }
  state.activeListPromptKeys.add(promptKey);
  try {
    const label = productFieldLabel(fieldName);
    const listLabel = listLabels[listKey] || listKey;
    const shouldAdd = window.confirm(
      `${label}: "${value}" nie istnieje na liscie ${listLabel}. Dodac ten wpis do listy?`
    );
    if (!shouldAdd) {
      state.declinedListPrompts.add(promptKey);
      return false;
    }
    const canonical = await addValueToList(listKey, value);
    if (canonical) {
      input.value = canonical;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    state.declinedListPrompts.delete(promptKey);
    formStatus.textContent = `Dodano "${canonical || value}" do listy ${listLabel}.`;
    return true;
  } finally {
    state.activeListPromptKeys.delete(promptKey);
  }
}

async function ensureProductListValues() {
  for (const fieldName of Object.keys(fieldListKey)) {
    await promptAddProductFieldToList(fieldName);
  }
}

function entryMatchesContext(entry, fieldName) {
  const payload = currentFormPayload();
  if (["type_name", "model", "color1", "color2", "color3", "extra"].includes(fieldName)) {
    if (payload.name && String(entry.name || "").toUpperCase() !== payload.name.toUpperCase()) return false;
  }
  if (["model", "color1", "color2", "color3", "extra"].includes(fieldName)) {
    if (payload.type_name && String(entry.type_name || "").toUpperCase() !== payload.type_name.toUpperCase()) return false;
  }
  if (["color1", "color2", "color3", "extra"].includes(fieldName)) {
    if (payload.model && String(entry.model || "").toUpperCase() !== payload.model.toUpperCase()) return false;
  }
  return true;
}

function localSuggestions(fieldName) {
  const existing = [];
  for (const entry of state.entries || []) {
    if (!entryMatchesContext(entry, fieldName)) continue;
    if (fieldName === "name") existing.push(entry.name);
    if (fieldName === "type_name") existing.push(entry.type_name);
    if (fieldName === "model") existing.push(entry.model);
    if (["color1", "color2", "color3"].includes(fieldName)) {
      existing.push(entry.color1, entry.color2, entry.color3);
    }
    if (fieldName === "extra") existing.push(entry.extra);
  }
  const listValues = state.lists[fieldListKey[fieldName]] || [];
  return uniqueValues([...existing, ...listValues]);
}

async function remoteSuggestions(fieldName, requestPayload, signal) {
  const params = new URLSearchParams({ field: fieldName, ...requestPayload });
  const response = await requestJson(`/api/suggestions?${params.toString()}`, { signal });
  state.fileIndex = response.file_index || state.fileIndex;
  updateRuntimeMetrics();
  return response.values || [];
}

function autocompleteRequestSnapshot(fieldName) {
  const payload = currentFormPayload();
  return {
    payload,
    signature: JSON.stringify([
      fieldName,
      payload.name,
      payload.type_name,
      payload.model,
      payload.color1,
      payload.color2,
      payload.color3,
      payload.extra,
    ]),
  };
}

function renderEntrySelect(entries = state.entries) {
  entrySelect.textContent = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = entries.length ? "Wybierz wpis" : "Brak dopasowan";
  entrySelect.appendChild(empty);
  for (const entry of entries) {
    const option = document.createElement("option");
    option.value = entry.product_id || entry.ean;
    option.textContent = entry.label;
    option.dataset.entry = JSON.stringify(entry);
    entrySelect.appendChild(option);
  }
}

function renderEntryModal(entries) {
  entryMatches.textContent = "";
  if (!entries.length) {
    entryMatches.textContent = "Brak dopasowanych wpisow.";
    document.querySelector("#entryModal").classList.add("active");
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("article");
    row.className = "entry-match";
    const text = document.createElement("div");
    const title = document.createElement("strong");
    const details = document.createElement("span");
    const button = document.createElement("button");
    title.textContent = entry.label;
    details.textContent = `${entry.product_id || "BRAK-ID"} | ${entry.ean || "BRAK-EAN"}`;
    button.type = "button";
    button.textContent = "Wczytaj";
    button.addEventListener("click", () => {
      fillForm(entry, { loadPhotos: true });
      closeModals();
    });
    text.append(title, details);
    row.append(text, button);
    entryMatches.appendChild(row);
  }
  document.querySelector("#entryModal").classList.add("active");
}

function renderListUsageModal(value, usedBy = []) {
  if (!listUsageTitle || !listUsageOutput) {
    return;
  }
  listUsageTitle.textContent = `Nie usunieto: ${value}`;
  listUsageOutput.textContent = "";
  if (!usedBy.length) {
    listUsageOutput.textContent = "Backend nie zwrocil listy produktow.";
    document.querySelector("#listUsageModal")?.classList.add("active");
    return;
  }
  for (const item of usedBy) {
    const row = document.createElement("article");
    const text = document.createElement("div");
    const title = document.createElement("strong");
    const details = document.createElement("span");
    const button = document.createElement("button");
    row.className = "entry-match";
    title.textContent = item.label || `${item.name || ""} ${item.type_name || ""} ${item.model || ""}`.trim();
    details.textContent = `${item.product_id || "BRAK-ID"} | EAN ${item.ean || "BRAK-EAN"} | ${
      item.fields || "pole"
    }`;
    button.type = "button";
    button.textContent = "Wczytaj";
    button.addEventListener("click", () => {
      fillForm(item, { loadPhotos: true });
      closeModals();
    });
    text.append(title, details);
    row.append(text, button);
    listUsageOutput.appendChild(row);
  }
  document.querySelector("#listUsageModal")?.classList.add("active");
}

const trackedProductFields = [
  "name",
  "type_name",
  "model",
  "color1",
  "color2",
  "color3",
  "extra",
  "ean",
];

function updateFieldWarnings() {
  for (const fieldName of trackedProductFields) {
    const input = productForm.elements[fieldName];
    if (!input) continue;
    const label = input.closest("label");
    if (!label) continue;
    let warning = label.querySelector(".field-warning");
    if (!warning) {
      warning = document.createElement("span");
      warning.className = "field-warning";
      label.appendChild(warning);
    }
    const original = state.loadedEntryOriginal ? String(state.loadedEntryOriginal[fieldName] || "") : "";
    const current = String(input.value || "");
    const changed = Boolean(state.loadedEntryOriginal) && current !== original;
    label.classList.toggle("field-changed", changed);
    warning.textContent = "";
    warning.classList.toggle("active", changed);
    if (changed) {
      const text = document.createElement("span");
      const undo = document.createElement("button");
      text.textContent = `Bylo: ${original || "(puste)"}`;
      undo.type = "button";
      undo.textContent = "Cofnij";
      undo.addEventListener("click", () => {
        input.value = original;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        updateFieldWarnings();
      });
      warning.append(text, undo);
    }
  }
  updateSubmitButtonState();
}

function setupFieldChangeTracking() {
  for (const fieldName of trackedProductFields) {
    productForm.elements[fieldName]?.addEventListener("input", updateFieldWarnings);
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

function dismissSimilarCandidate(prefix) {
  state.dismissedSimilarSlots.add(prefix);
  state.similarCandidates.delete(prefix);
  if (state.slotSources.get(prefix) === "similar") {
    state.slotSources.delete(prefix);
    state.userSelectedSlotSources.delete(prefix);
  }
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

function acceptSimilarCandidate(prefix) {
  const candidate = state.similarCandidates.get(prefix);
  if (!candidate || state.dismissedSimilarSlots.has(prefix)) return;
  markSlotDeletion(prefix, state.loadedPhotos.get(prefix));
  state.files.set(prefix, {
    file: null,
    name: candidate.filename,
    size: candidate.size_bytes,
    type: candidate.is_pdf ? "application/pdf" : "",
    token: candidate.token,
    url: candidate.url,
    thumb_url: candidate.thumb_url,
    preprocessed: true,
    uploading: false,
    error: "",
    similar_candidate_id: candidate.id,
  });
  state.slotSources.set(prefix, "similar");
  renderSlot(prefix);
  ensureSlotOcrCollection(prefix, state.files.get(prefix)).catch((error) => {
    formStatus.textContent = `Nie zlecono OCR dla slotu ${prefix}: ${error.message}`;
  });
}

function pendingSimilarCandidatePrefixes() {
  return (state.slots || [])
    .map((slot) => String(slot.prefix || ""))
    .filter((prefix) => Boolean(prefix) && !state.files.has(prefix) && Boolean(similarCandidateForSlot(prefix)));
}

function similarDecisionSlotLabel(prefix) {
  const slot = (state.slots || []).find((item) => String(item.prefix) === String(prefix));
  return slot ? `${slot.prefix} - ${slot.label}` : `Slot ${prefix}`;
}

function similarDecisionPreview(candidate) {
  const preview = document.createElement("div");
  preview.className = "similar-decision-preview";
  if (candidate.is_pdf) {
    const object = document.createElement("object");
    object.className = "similar-decision-pdf";
    object.type = "application/pdf";
    object.data = candidate.url || "";
    const fallback = document.createElement("span");
    fallback.textContent = "Podglad PDF niedostepny";
    object.appendChild(fallback);
    preview.appendChild(object);
    return preview;
  }
  const image = document.createElement("img");
  const fallback = document.createElement("span");
  image.src = candidate.thumb_url || candidate.url || "";
  image.alt = candidate.filename ? `Podglad ${candidate.filename}` : "Podglad pliku z podobnego produktu";
  image.loading = "lazy";
  image.addEventListener("error", () => {
    image.remove();
    fallback.textContent = "Podglad niedostepny";
    preview.appendChild(fallback);
  });
  preview.appendChild(image);
  return preview;
}

function renderSimilarDecisionModal() {
  if (!similarDecisionList) return;
  const prefixes = pendingSimilarCandidatePrefixes();
  for (const prefix of prefixes) {
    if (state.similarDecisionResults.has(prefix)) continue;
    const candidate = similarCandidateForSlot(prefix);
    if (candidate) state.similarDecisionResults.set(prefix, { candidate, decision: "pending" });
  }
  similarDecisionList.replaceChildren();
  for (const [prefix, result] of state.similarDecisionResults) {
    const candidate = result.candidate;
    const row = document.createElement("article");
    const details = document.createElement("div");
    const title = document.createElement("strong");
    const filename = document.createElement("span");
    const source = document.createElement("span");
    const actions = document.createElement("div");
    const acceptButton = document.createElement("button");
    const rejectButton = document.createElement("button");
    row.className = "similar-decision-row";
    row.dataset.slotPrefix = prefix;
    details.className = "similar-decision-details";
    title.textContent = similarDecisionSlotLabel(prefix);
    filename.textContent = candidate.filename || "Bez nazwy pliku";
    source.className = "similar-decision-source";
    source.textContent = candidate.source_color
      ? `Źródło: podobny produkt, kolor ${candidate.source_color}`
      : "Źródło: podobny produkt";
    actions.className = "similar-decision-row-actions";
    if (result.decision === "pending") {
      acceptButton.type = "button";
      acceptButton.className = "slot-similar-accept";
      acceptButton.textContent = "Zachowaj";
      acceptButton.title = "Zachowaj plik z podobnego produktu";
      acceptButton.addEventListener("click", () => {
        acceptSimilarCandidate(prefix);
        result.decision = "accepted";
        renderSimilarDecisionModal();
      });
      rejectButton.type = "button";
      rejectButton.className = "slot-similar-reject";
      rejectButton.textContent = "Odrzuć";
      rejectButton.title = "Odrzuć plik z podobnego produktu";
      rejectButton.addEventListener("click", () => {
        dismissSimilarCandidate(prefix);
        result.decision = "rejected";
        renderSlot(prefix);
        renderSimilarDecisionModal();
      });
      actions.append(acceptButton, rejectButton);
    } else {
      const status = document.createElement("strong");
      status.className = `similar-decision-result ${result.decision}`;
      status.textContent = result.decision === "accepted" ? "Zachowany" : "Odrzucony";
      actions.appendChild(status);
    }
    details.append(title, filename, source);
    row.append(similarDecisionPreview(candidate), details, actions);
    similarDecisionList.appendChild(row);
  }
  if (similarDecisionRejectAllButton) similarDecisionRejectAllButton.disabled = prefixes.length === 0;
  if (similarDecisionContinueButton) similarDecisionContinueButton.disabled = prefixes.length > 0;
}

function focusFirstPendingSimilarCandidate() {
  const prefix = pendingSimilarCandidatePrefixes()[0];
  if (!prefix) return;
  const card = slotGrid.querySelector(`[data-slot-prefix="${prefix}"]`);
  card?.scrollIntoView({
    behavior: "smooth",
    block: "center",
  });
  card?.setAttribute("tabindex", "-1");
  card?.focus({ preventScroll: true });
}

function setSimilarDecisionBackgroundInert() {
  if (!similarDecisionModal || similarDecisionBackgroundState.length) return;
  similarDecisionBackgroundState = Array.from(document.body.children)
    .filter((node) => node !== similarDecisionModal)
    .map((node) => ({
      node,
      inert: node.getAttribute("inert"),
      ariaHidden: node.getAttribute("aria-hidden"),
    }));
  for (const entry of similarDecisionBackgroundState) {
    entry.node.setAttribute("inert", "");
    entry.node.setAttribute("aria-hidden", "true");
  }
}

function restoreSimilarDecisionBackground() {
  for (const entry of similarDecisionBackgroundState) {
    if (entry.inert === null) entry.node.removeAttribute("inert");
    else entry.node.setAttribute("inert", entry.inert);
    if (entry.ariaHidden === null) entry.node.removeAttribute("aria-hidden");
    else entry.node.setAttribute("aria-hidden", entry.ariaHidden);
  }
  similarDecisionBackgroundState = [];
}

function openSimilarDecisionModal() {
  state.similarDecisionResults.clear();
  renderSimilarDecisionModal();
  setSimilarDecisionBackgroundInert();
  similarDecisionModal?.classList.add("active");
  window.setTimeout(() => similarDecisionCloseButton?.focus(), 0);
}

function closeSimilarDecisionModal() {
  similarDecisionModal?.classList.remove("active");
  restoreSimilarDecisionBackground();
  focusFirstPendingSimilarCandidate();
}

function isHttpUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    return ["http:", "https:"].includes(url.protocol);
  } catch (_error) {
    return false;
  }
}

function selectedPhotoToken(photo, prefix) {
  const source = selectedSlotSource(prefix, photo);
  if (source === "ftp") return photo?.ftp_token || "";
  if (source === "sql" || source === "similar") return "";
  return photo?.token || "";
}

function transferableSlotSource(prefix, photo) {
  const selected = state.slotSources.get(prefix);
  if (selected === "local" && photo?.token) return "local";
  if (selected === "ftp" && (photo?.ftp_token || photo?.ftp_filename)) return "ftp";
  if (photo?.token) return "local";
  if (photo?.ftp_token || photo?.ftp_filename) return "ftp";
  return "";
}

function transferablePhotoToken(photo, prefix) {
  const source = transferableSlotSource(prefix, photo);
  if (source === "ftp") return photo?.ftp_token || "";
  if (source === "local") return photo?.token || "";
  return "";
}

function revokeFilePreviewUrl(prefix) {
  const url = state.filePreviewUrls.get(prefix);
  if (url) URL.revokeObjectURL(url);
  state.filePreviewUrls.delete(prefix);
}

function filePreviewUrl(prefix, file) {
  const item = slotFileItem(file);
  const rawFile = slotFileObject(item);
  if (!rawFile) {
    return item?.url || item?.thumb_url || "";
  }
  const current = state.filePreviewUrls.get(prefix);
  if (current) return current;
  const url = URL.createObjectURL(rawFile);
  state.filePreviewUrls.set(prefix, url);
  return url;
}

function isFileImageLike(file) {
  const name = String(slotFileName(file) || "").toLowerCase();
  return (
    String(slotFileType(file) || "").startsWith("image/") ||
    [
      ".jpg",
      ".jpeg",
      ".jfif",
      ".jpe",
      ".peg",
      ".png",
      ".apng",
      ".gif",
      ".bmp",
      ".dib",
      ".webp",
      ".tif",
      ".tiff",
      ".avif",
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
      ".psd",
      ".eps",
      ".ai",
    ].some((ext) => name.endsWith(ext))
  );
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
}

function fittedImageDataUrl(image) {
  const sourceWidth = image.naturalWidth || image.width;
  const sourceHeight = image.naturalHeight || image.height;
  if (!sourceWidth || !sourceHeight) return "";
  const detectScale = Math.min(1, 512 / Math.max(sourceWidth, sourceHeight));
  const detectWidth = Math.max(1, Math.round(sourceWidth * detectScale));
  const detectHeight = Math.max(1, Math.round(sourceHeight * detectScale));
  const detect = document.createElement("canvas");
  detect.width = detectWidth;
  detect.height = detectHeight;
  const detectCtx = detect.getContext("2d", { willReadFrequently: true });
  detectCtx.drawImage(image, 0, 0, detectWidth, detectHeight);
  const pixels = detectCtx.getImageData(0, 0, detectWidth, detectHeight).data;
  const cornerSize = Math.max(1, Math.min(detectWidth, detectHeight, Math.floor(Math.min(detectWidth, detectHeight) / 20) || 1));
  const corners = [
    [0, 0],
    [detectWidth - cornerSize, 0],
    [0, detectHeight - cornerSize],
    [detectWidth - cornerSize, detectHeight - cornerSize],
  ];
  const bg = [0, 0, 0, 0];
  let bgCount = 0;
  for (const [startX, startY] of corners) {
    for (let y = startY; y < startY + cornerSize; y += 1) {
      for (let x = startX; x < startX + cornerSize; x += 1) {
        const idx = (y * detectWidth + x) * 4;
        bg[0] += pixels[idx];
        bg[1] += pixels[idx + 1];
        bg[2] += pixels[idx + 2];
        bg[3] += pixels[idx + 3];
        bgCount += 1;
      }
    }
  }
  bg[0] = bg[0] / Math.max(1, bgCount);
  bg[1] = bg[1] / Math.max(1, bgCount);
  bg[2] = bg[2] / Math.max(1, bgCount);
  bg[3] = bg[3] / Math.max(1, bgCount);
  let left = detectWidth;
  let top = detectHeight;
  let right = -1;
  let bottom = -1;
  for (let y = 0; y < detectHeight; y += 1) {
    for (let x = 0; x < detectWidth; x += 1) {
      const idx = (y * detectWidth + x) * 4;
      const alpha = pixels[idx + 3];
      const diff =
        Math.abs(pixels[idx] - bg[0]) +
        Math.abs(pixels[idx + 1] - bg[1]) +
        Math.abs(pixels[idx + 2] - bg[2]);
      const alphaDiff = Math.abs(alpha - bg[3]);
      if ((bg[3] < 250 && alpha > 8) || alphaDiff > 32 || (alpha > 8 && diff > 54)) {
        left = Math.min(left, x);
        top = Math.min(top, y);
        right = Math.max(right, x + 1);
        bottom = Math.max(bottom, y + 1);
      }
    }
  }
  if (right <= left || bottom <= top) return "";
  const areaRatio = ((right - left) * (bottom - top)) / Math.max(1, detectWidth * detectHeight);
  if (areaRatio > 0.98) return "";
  const scaleX = sourceWidth / detectWidth;
  const scaleY = sourceHeight / detectHeight;
  let cropLeft = Math.floor(left * scaleX);
  let cropTop = Math.floor(top * scaleY);
  let cropRight = Math.ceil(right * scaleX);
  let cropBottom = Math.ceil(bottom * scaleY);
  const margin = Math.ceil(Math.max(cropRight - cropLeft, cropBottom - cropTop) * 0.06);
  cropLeft = Math.max(0, cropLeft - margin);
  cropTop = Math.max(0, cropTop - margin);
  cropRight = Math.min(sourceWidth, cropRight + margin);
  cropBottom = Math.min(sourceHeight, cropBottom + margin);
  const sourceAspect = sourceWidth / Math.max(1, sourceHeight);
  let cropWidth = cropRight - cropLeft;
  let cropHeight = cropBottom - cropTop;
  if (cropWidth / cropHeight < sourceAspect) {
    const targetWidth = Math.min(sourceWidth, cropHeight * sourceAspect);
    cropLeft = Math.max(0, Math.min(sourceWidth - targetWidth, cropLeft - (targetWidth - cropWidth) / 2));
    cropWidth = targetWidth;
  } else {
    const targetHeight = Math.min(sourceHeight, cropWidth / sourceAspect);
    cropTop = Math.max(0, Math.min(sourceHeight - targetHeight, cropTop - (targetHeight - cropHeight) / 2));
    cropHeight = targetHeight;
  }
  const outScale = Math.min(1, 1200 / Math.max(sourceWidth, sourceHeight));
  const outWidth = Math.max(1, Math.round(sourceWidth * outScale));
  const outHeight = Math.max(1, Math.round(sourceHeight * outScale));
  const out = document.createElement("canvas");
  out.width = outWidth;
  out.height = outHeight;
  out
    .getContext("2d")
    .drawImage(image, cropLeft, cropTop, cropWidth, cropHeight, 0, 0, outWidth, outHeight);
  return out.toDataURL("image/jpeg", 0.9);
}

async function renderSelectedFilePreview(prefix, file, preview, previewImage, empty) {
  const url = filePreviewUrl(prefix, file);
  if (!url) {
    preview.classList.remove("thumb-loading", "has-image");
    empty.textContent = slotFileName(file);
    return;
  }
  preview.classList.add("thumb-loading");
  try {
    const image = await loadImage(url);
    if (state.files.get(prefix) !== file || !document.body.contains(preview)) return;
    const fitted = isSlotFit(prefix) ? fittedImageDataUrl(image) : "";
    previewImage.src = fitted || url;
    preview.classList.add("has-image");
    preview.classList.remove("thumb-loading");
  } catch (_error) {
    if (state.files.get(prefix) !== file || !document.body.contains(preview)) return;
    preview.classList.remove("thumb-loading", "has-image");
    empty.textContent = "Podglad niedostepny";
  }
}

function loadedFileUrl(photo, prefix) {
  const source = selectedSlotSource(prefix, photo);
  if (source === "similar") return similarCandidateForSlot(prefix)?.url || "";
  if (source === "sql") {
    const value = String(photo?.sql_value || "").trim();
    return isHttpUrl(value) ? value : "";
  }
  if (source === "ftp" && photo?.ftp_url) return photo.ftp_url;
  if (source === "local" && photo?.url) return photo.url;
  const token = selectedPhotoToken(photo, prefix);
  return token ? `/api/file?token=${encodeURIComponent(token)}` : "";
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

function openOcrImageWindow() {
  const popup = window.open("", "_blank");
  if (popup) {
    try {
      popup.opener = null;
    } catch (_error) {
      // Some browser security modes expose a read-only opener property.
    }
  }
  return popup;
}

function showPlainImageInOcrWindow(popup, url) {
  if (popup && !popup.closed) {
    popup.location.href = url;
    popup.focus();
    return;
  }
  window.open(url, "_blank", "noopener");
}

function appendOcrBoxesToOpenedImage(stage, image, values) {
  const width = Number(image.naturalWidth || 0);
  const height = Number(image.naturalHeight || 0);
  if (!width || !height) return;
  for (const value of values) {
    const [left, top, right, bottom] = Array.isArray(value?.bbox) ? value.bbox.map(Number) : [];
    if (![left, top, right, bottom].every(Number.isFinite)) continue;
    const box = image.ownerDocument.createElement("div");
    const label = image.ownerDocument.createElement("span");
    box.className = "ocr-slot-open-box";
    label.className = "ocr-slot-open-label";
    box.style.left = `${Math.max(0, Math.min(100, (left / width) * 100))}%`;
    box.style.top = `${Math.max(0, Math.min(100, (top / height) * 100))}%`;
    box.style.width = `${Math.max(0, Math.min(100, ((right - left) / width) * 100))}%`;
    box.style.height = `${Math.max(0, Math.min(100, ((bottom - top) / height) * 100))}%`;
    label.textContent = `${String(value?.text || "?")} · ${ocrConfidenceLabel(value?.confidence)}`;
    box.appendChild(label);
    stage.appendChild(box);
  }
}

async function openOcrAnnotatedImage(url, token, popup = null) {
  if (!token) {
    showPlainImageInOcrWindow(popup, url);
    return;
  }
  let scan;
  try {
    scan = await requestJson(`/api/ocr/scan?token=${encodeURIComponent(token)}`);
  } catch (_error) {
    showPlainImageInOcrWindow(popup, url);
    return;
  }
  const values = Array.isArray(scan?.values) ? scan.values : [];
  if (!popup || popup.closed || !values.length) {
    showPlainImageInOcrWindow(popup, url);
    return;
  }
  const doc = popup.document;
  doc.open();
  doc.write("<!doctype html><title>Podglad OCR</title><meta charset=\"utf-8\">");
  doc.close();
  const style = doc.createElement("style");
  style.textContent = ".ocr-slot-open-page{margin:0;background:#151922;color:#eef2ff;font:14px system-ui,sans-serif}.ocr-slot-open-header{padding:12px 16px}.ocr-slot-open-stage{position:relative;display:inline-block;line-height:0;max-width:100%}.ocr-slot-open-image{display:block;max-width:100%;height:auto}.ocr-slot-open-overlay{position:absolute;inset:0;pointer-events:none}.ocr-slot-open-box{position:absolute;box-sizing:border-box;border:2px solid #48d260}.ocr-slot-open-label{position:absolute;left:-2px;bottom:calc(100% + 2px);padding:2px 5px;border-radius:4px;background:#48d260;color:#111827;font-size:12px;font-weight:700;line-height:1.25;white-space:nowrap}.ocr-slot-open-wrap{padding:0 16px 16px}";
  doc.head.appendChild(style);
  const header = doc.createElement("div");
  const wrap = doc.createElement("div");
  const stage = doc.createElement("div");
  const overlay = doc.createElement("div");
  const image = doc.createElement("img");
  header.className = "ocr-slot-open-header";
  wrap.className = "ocr-slot-open-wrap";
  stage.className = "ocr-slot-open-stage";
  overlay.className = "ocr-slot-open-overlay";
  image.className = "ocr-slot-open-image";
  header.textContent = `OCR: ${values.length} wykrytych wartosci`;
  image.alt = "Podglad obrazu z wynikami OCR";
  image.addEventListener("load", () => appendOcrBoxesToOpenedImage(overlay, image, values), { once: true });
  image.src = url;
  stage.append(image, overlay);
  wrap.appendChild(stage);
  doc.body.className = "ocr-slot-open-page";
  doc.body.append(header, wrap);
  popup.focus();
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

async function copyTextToClipboard(text, successMessage = "Skopiowano.") {
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      formStatus.textContent = successMessage;
      return;
    } catch (_error) {
      // Older LAN/browser contexts can expose clipboard but still reject writes.
    }
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.style.position = "fixed";
  field.style.left = "-9999px";
  document.body.appendChild(field);
  field.focus();
  field.select();
  document.execCommand("copy");
  field.remove();
  formStatus.textContent = successMessage;
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

function isPhotoSourceLoading(source) {
  const status = state.photoSourceStatus.get(source);
  return status === "pending" || status === "loading";
}

function sourceLoadingTitle(source) {
  if (source === "ftp") {
    return "Wczytywanie FTP";
  }
  if (source === "local") {
    return "Wczytywanie plikow lokalnych";
  }
  if (source === "sql") {
    return "Wczytywanie SQL";
  }
  return "Wczytywanie danych";
}

function photoHasUsableContent(photo) {
  if (!photo) return false;
  return Boolean(
    photo.token ||
      photo.url ||
      photo.thumb_url ||
      photo.filename ||
      photo.ftp_token ||
      photo.ftp_filename ||
      photo.ftp_url ||
      photo.ftp_thumb_url ||
      photo.sql_value ||
      photo.local ||
      photo.ftp ||
      photo.sql
  );
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

function uploadCacheErrorMessage(payload, fallback = "Nie udalo sie wyslac pliku do cache.") {
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail?.message) return detail.message;
  return fallback;
}

function fileItemPrefixes(item) {
  const prefixes = [];
  for (const [prefix, current] of state.files.entries()) {
    if (current === item) prefixes.push(prefix);
  }
  return prefixes;
}

function refreshFileItemSlots(item) {
  for (const prefix of fileItemPrefixes(item)) {
    updateSlotPreview(prefix);
  }
  updateSubmitButtonState();
}

function clientTargetFormatInfo(file) {
  const settings = currentProcessingSettings();
  const sourceType = String(file?.type || "").toLowerCase();
  const sourceName = String(file?.name || "");
  const sourceExt = sourceName.split(".").pop()?.toLowerCase() || "";
  if (settings.convert_enabled) {
    const target = String(settings.target_format || "PNG").toUpperCase();
    if (target === "JPG" || target === "JPEG") return { type: "image/jpeg", ext: "jpg" };
    if (target === "PNG") return { type: "image/png", ext: "png" };
    if (target === "WEBP") return { type: "image/webp", ext: "webp" };
  }
  if (
    sourceType === "image/jpeg" ||
    sourceExt === "jpg" ||
    sourceExt === "jpeg" ||
    sourceExt === "jfif" ||
    sourceExt === "jpe" ||
    sourceExt === "peg"
  ) {
    return { type: "image/jpeg", ext: "jpg" };
  }
  if (sourceType === "image/png" || sourceType === "image/apng" || sourceExt === "png" || sourceExt === "apng") {
    return { type: "image/png", ext: "png" };
  }
  if (sourceType === "image/webp" || sourceExt === "webp") return { type: "image/webp", ext: "webp" };
  return null;
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("Przegladarka nie utworzyla przetworzonego obrazu."));
        }
      },
      type,
      quality
    );
  });
}

function loadImageForProcessing(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Nie udalo sie odczytac obrazu po stronie klienta."));
    };
    image.src = url;
  });
}

async function preprocessFileOnClient(file) {
  const settings = currentProcessingSettings();
  if (uploadProcessingMode() !== "client") {
    return { file, preprocessed: false, elapsed_ms: 0 };
  }
  if (
    !settings.resize_enabled &&
    !settings.compress_enabled &&
    !settings.max_size_enabled &&
    !settings.convert_enabled
  ) {
    return { file, preprocessed: false, elapsed_ms: 0 };
  }
  const format = clientTargetFormatInfo(file);
  if (!format) {
    return { file, preprocessed: false, elapsed_ms: 0 };
  }
  const started = performance.now();
  const image = await loadImageForProcessing(file);
  const maxDim = Math.max(64, Math.min(20000, Number(settings.max_dim || 2000)));
  let width = image.naturalWidth || image.width;
  let height = image.naturalHeight || image.height;
  if (settings.resize_enabled && Math.max(width, height) > maxDim) {
    const scale = maxDim / Math.max(width, height);
    width = Math.max(1, Math.round(width * scale));
    height = Math.max(1, Math.round(height * scale));
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { alpha: format.type !== "image/jpeg" });
  if (!ctx) {
    return { file, preprocessed: false, elapsed_ms: performance.now() - started };
  }
  if (format.type === "image/jpeg") {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
  }
  ctx.drawImage(image, 0, 0, width, height);
  const qualityBase = Math.max(1, Math.min(100, Number(settings.compress_quality || 85))) / 100;
  let quality = settings.compress_enabled ? qualityBase : 0.95;
  let blob = await canvasToBlob(canvas, format.type, quality);
  if (settings.max_size_enabled && ["image/jpeg", "image/webp"].includes(format.type)) {
    const maxBytes = Math.max(1, Number(settings.max_file_kb || 500)) * 1024;
    while (blob.size > maxBytes && quality > 0.1) {
      quality = Math.max(0.1, quality - 0.05);
      blob = await canvasToBlob(canvas, format.type, quality);
    }
  }
  const sourceName = String(file.name || "upload");
  const stem = sourceName.includes(".") ? sourceName.replace(/\.[^.]+$/, "") : sourceName;
  const processed = new File([blob], `${stem}.${format.ext}`, {
    type: format.type,
    lastModified: Date.now(),
  });
  return {
    file: processed,
    preprocessed: true,
    elapsed_ms: performance.now() - started,
    original_size: file.size || 0,
  };
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

function setFtpBadgeLoading(prefix, loading) {
  const card = slotGrid.querySelector(`[data-slot-prefix="${prefix}"]`);
  const badge = card?.querySelector('.slot-badge-ftp[data-source="ftp"]');
  if (!badge) return;
  const selected = badge.classList.contains("selected");
  badge.classList.toggle("loading", Boolean(loading));
  if (loading) {
    badge.setAttribute("aria-busy", "true");
    badge.title = "Pobieranie miniatury FTP w tle";
  } else {
    badge.removeAttribute("aria-busy");
    badge.title = selected ? "Wpis dla slotu jest na FTP (aktywny podglad)" : "Wpis dla slotu jest na FTP";
  }
}

function slotRevision(prefix) {
  return Number(state.slotRevisions.get(prefix) || 0);
}

function bumpSlotRevision(prefix) {
  state.slotRevisions.set(prefix, slotRevision(prefix) + 1);
}

function ftpPreviewCacheKey(photo, fallbackEan = "") {
  const filename = String(photo?.ftp_filename || "").trim();
  const ean = String(photo?.ean || fallbackEan || "").trim();
  return filename && ean ? `${ean}|${filename}` : "";
}

function setFtpPreviewCache(key, value) {
  if (!key) return;
  state.ftpPreviewCache.delete(key);
  state.ftpPreviewCache.set(key, value);
  while (state.ftpPreviewCache.size > FTP_PREVIEW_CACHE_LIMIT) {
    state.ftpPreviewCache.delete(state.ftpPreviewCache.keys().next().value);
  }
}

function clearFtpPreviewCacheForPrefixes(prefixes, fallbackEan = "") {
  const prefixSet = new Set(
    [...(prefixes || [])].map((prefix) => String(prefix || "").trim()).filter(Boolean)
  );
  if (!prefixSet.size) return;
  const ean = String(fallbackEan || formValue("ean") || state.loadedEntryOriginal?.ean || "").trim();
  for (const prefix of prefixSet) {
    const photo = state.loadedPhotos.get(prefix);
    const directKey = ftpPreviewCacheKey(photo, ean);
    if (directKey) {
      state.ftpPreviewCache.delete(directKey);
    }
  }
  for (const key of Array.from(state.ftpPreviewCache.keys())) {
    const [keyEan, filename] = String(key).split("|", 2);
    if (ean && keyEan && keyEan !== ean) continue;
    for (const prefix of prefixSet) {
      if (filename?.startsWith(`${keyEan}_${prefix}.`) || filename?.includes(`_${prefix}.`)) {
        state.ftpPreviewCache.delete(key);
        break;
      }
    }
  }
}

function applyCachedFtpPreview(photo, prefix, cached) {
  if (!cached) return photo;
  if (cached.file_version && photo?.ftp_file_version && cached.file_version !== photo.ftp_file_version) {
    return photo;
  }
  return {
    ...photo,
    ftp_token: cached.token || photo?.ftp_token || "",
    ftp_url: cached.url || photo?.ftp_url || "",
    ftp_thumb_url: cached.thumb_url || photo?.ftp_thumb_url || "",
    ftp_file_version: cached.file_version || photo?.ftp_file_version || "",
  };
}

async function loadFtpPreview(photo, prefix, requestId = state.photoLoadRequestId, options = {}) {
  if (!photo?.ftp_filename) return;
  if (state.ftpPreviewLoading.has(prefix)) {
    const pending = state.ftpPreviewRequests.get(prefix);
    if (!pending) return;
    await pending;
    if (!options.forceRefresh) return;
    if (requestId !== state.photoLoadRequestId) return;
    const refreshedPhoto = state.loadedPhotos.get(prefix);
    if (!refreshedPhoto?.ftp_filename) return;
    return loadFtpPreview(refreshedPhoto, prefix, requestId, options);
  }
  const revision = slotRevision(prefix);
  const cacheKey = ftpPreviewCacheKey(photo, formValue("ean") || "");
  const forceRefresh = Boolean(options.forceRefresh);
  const cached = forceRefresh ? null : cacheKey ? state.ftpPreviewCache.get(cacheKey) : null;
  if (cached) {
    setFtpPreviewCache(cacheKey, cached);
    const currentPhoto = state.loadedPhotos.get(prefix);
    if (
      requestId !== state.photoLoadRequestId ||
      revision !== slotRevision(prefix) ||
      !currentPhoto ||
      ftpPreviewCacheKey(currentPhoto, formValue("ean") || "") !== cacheKey
    ) {
      return;
    }
    const updated = applyCachedFtpPreview(currentPhoto, prefix, cached);
    state.loadedPhotos.set(prefix, updated);
    if (options.background && selectedSlotSource(prefix, updated) !== "ftp") {
      setFtpBadgeLoading(prefix, false);
    } else {
      updateSlotPreview(prefix);
    }
    return;
  }
  state.ftpPreviewLoading.add(prefix);
  let finishRequest;
  const requestComplete = new Promise((resolve) => {
    finishRequest = resolve;
  });
  state.ftpPreviewRequests.set(prefix, requestComplete);
  const background = Boolean(options.background);
  if (background) {
    state.ftpPreviewBackgroundLoading.add(prefix);
  } else {
    state.ftpPreviewBackgroundLoading.delete(prefix);
  }
  if (!background) {
    formStatus.textContent = `Pobieranie podgladu FTP dla slotu ${prefix}...`;
  }
  if (background) {
    setFtpBadgeLoading(prefix, true);
  } else {
    updateSlotPreview(prefix);
  }
  try {
    const payload = await requestJson("/api/ftp-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ean: photo.ean || formValue("ean") || "", filename: photo.ftp_filename }),
    });
    if (cacheKey) {
      setFtpPreviewCache(cacheKey, {
        token: payload.token || "",
        url: payload.url || "",
        thumb_url: payload.thumb_url || "",
        file_version: payload.file_version || "",
      });
    }
    const currentPhoto = state.loadedPhotos.get(prefix);
    if (
      requestId !== state.photoLoadRequestId ||
      revision !== slotRevision(prefix) ||
      !currentPhoto ||
      ftpPreviewCacheKey(currentPhoto, formValue("ean") || "") !== cacheKey
    ) {
      return;
    }
    const updated = {
      ...currentPhoto,
      ftp_token: payload.token || "",
      ftp_url: payload.url || "",
      ftp_thumb_url: payload.thumb_url || "",
      ftp_file_version: payload.file_version || "",
    };
    state.loadedPhotos.set(prefix, updated);
    if (!background) {
      formStatus.textContent = `Pobrano podglad FTP dla slotu ${prefix}.`;
    }
  } finally {
    finishRequest();
    if (state.ftpPreviewRequests.get(prefix) !== requestComplete) return;
    state.ftpPreviewLoading.delete(prefix);
    state.ftpPreviewBackgroundLoading.delete(prefix);
    state.ftpPreviewRequests.delete(prefix);
    if (requestId !== state.photoLoadRequestId || revision !== slotRevision(prefix)) return;
    const currentPhoto = state.loadedPhotos.get(prefix);
    if (background && selectedSlotSource(prefix, currentPhoto) !== "ftp") {
      setFtpBadgeLoading(prefix, false);
    } else {
      updateSlotPreview(prefix);
    }
  }
}

function nextBackgroundFtpPreviewCandidate() {
  for (const slot of state.slots || []) {
    const prefix = slot.prefix;
    const photo = state.loadedPhotos.get(prefix);
    if (
      photo?.ftp &&
      photo.ftp_filename &&
      !photo.ftp_token &&
      !state.files.has(prefix) &&
      !state.deletedSlots.has(prefix) &&
      !photo?.dirty &&
      !state.ftpPreviewLoading.has(prefix)
    ) {
      return { prefix, photo };
    }
  }
  return null;
}

function scheduleBackgroundFtpPreviewLoad(requestId = state.photoLoadRequestId, delayMs = 900) {
  window.clearTimeout(state.backgroundFtpPreviewTimer);
  state.backgroundFtpPreviewTimer = window.setTimeout(() => {
    loadNextBackgroundFtpPreview(requestId).catch(() => {});
  }, delayMs);
}

async function loadNextBackgroundFtpPreview(requestId = state.photoLoadRequestId) {
  if (requestId !== state.photoLoadRequestId) {
    return;
  }
  let launched = 0;
  const limit = Math.max(1, Number(state.backgroundFtpPreviewLimit) || 1);
  while (state.ftpPreviewBackgroundLoading.size < limit) {
    const candidate = nextBackgroundFtpPreviewCandidate();
    if (!candidate) {
      break;
    }
    launched += 1;
    loadFtpPreview(candidate.photo, candidate.prefix, requestId, { background: true })
      .catch(() => {
        // Background preview loading must not block regular editing.
      })
      .finally(() => {
        if (requestId === state.photoLoadRequestId && nextBackgroundFtpPreviewCandidate()) {
          scheduleBackgroundFtpPreviewLoad(requestId, 900);
        }
      });
  }
  if (launched && requestId === state.photoLoadRequestId && nextBackgroundFtpPreviewCandidate()) {
    scheduleBackgroundFtpPreviewLoad(requestId, 900);
  }
}

function isSlotFit(prefix) {
  if (state.slotFits.has(prefix)) {
    return Boolean(state.slotFits.get(prefix));
  }
  return Boolean(state.defaultSlotFit);
}

function thumbnailUrl(photo, prefix) {
  const source = selectedSlotSource(prefix, photo);
  if (source === "similar") {
    const candidate = similarCandidateForSlot(prefix);
    return candidate?.thumb_url || candidate?.url || "";
  }
  const url =
    source === "ftp"
      ? photo?.ftp_thumb_url || photo?.ftp_url || ""
      : photo?.thumb_url || photo?.url || "";
  if (!url) return "";
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}fit=${isSlotFit(prefix) ? "1" : "0"}&width=260&height=180`;
}

function renderSimilarCandidatePreview(prefix, preview, previewImage, empty) {
  const candidate = similarCandidateForSlot(prefix);
  if (!candidate) return false;
  preview.classList.add("has-similar-candidate");
  if (candidate.is_pdf) {
    const object = document.createElement("object");
    const fallback = document.createElement("span");
    object.className = "slot-similar-preview";
    object.type = "application/pdf";
    object.data = candidate.url;
    fallback.textContent = candidate.filename || "Podglad PDF niedostepny";
    object.appendChild(fallback);
    preview.appendChild(object);
    empty.textContent = candidate.filename || "Dokument PDF";
    return true;
  }
  const thumb = candidate.thumb_url || candidate.url || "";
  if (!thumb) {
    empty.textContent = candidate.filename || "Podglad niedostepny";
    return true;
  }
  previewImage.addEventListener(
    "error",
    () => {
      preview.classList.remove("has-image");
      empty.textContent = candidate.filename || "Podglad niedostepny";
    },
    { once: true }
  );
  previewImage.src = thumb;
  preview.classList.add("has-image");
  return true;
}

function renderSqlPreview(prefix, photo, preview, empty) {
  const value = String(photo?.sql_value || "").trim();
  const card = document.createElement("div");
  const text = document.createElement("code");
  const copyButton = document.createElement("button");
  card.className = "slot-sql-preview";
  text.textContent = value || "Brak wartosci SQL";
  copyButton.type = "button";
  copyButton.className = "slot-sql-copy-button";
  copyButton.textContent = "Kopiuj";
  copyButton.disabled = !value;
  copyButton.addEventListener("click", (event) => {
    event.stopPropagation();
    copyTextToClipboard(value, `Skopiowano wartosc SQL dla slotu ${prefix}.`).catch((error) => {
      formStatus.textContent = error.message;
    });
  });
  card.append(text, copyButton);
  preview.classList.add("has-sql-preview");
  empty.textContent = "";
  preview.appendChild(card);
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

function uploadFileExtension(file) {
  const name = String(file?.name || slotFileName(file) || "").trim();
  const match = name.match(/\.([a-z0-9]+)$/i);
  return match ? match[1].toLowerCase() : "";
}

function uploadFileValidationError(file) {
  const extension = uploadFileExtension(file);
  const security = currentSecuritySettings();
  const allowed = normalizeUploadExtensionList(security.allowed_upload_extensions);
  const blocked = normalizeUploadExtensionList(security.blocked_upload_extensions);
  if (!extension) {
    return "Format niedozwolony: plik musi miec rozszerzenie.";
  }
  if (blocked.includes(extension)) {
    return `Format niedozwolony: .${extension} jest na czarnej liscie.`;
  }
  if (security.block_executable_uploads !== false && CLIENT_EXECUTABLE_UPLOAD_EXTENSIONS.has(extension)) {
    return `Format niedozwolony: .${extension} jest plikiem wykonywalnym.`;
  }
  if (allowed.length && !allowed.includes(extension)) {
    return `Format niedozwolony: .${extension} nie jest na bialej liscie.`;
  }
  return "";
}

function fileListFromInput(files) {
  return Array.from(files || []).filter(Boolean);
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

function renderListTabs() {
  listTabs.textContent = "";
  for (const [key, label] of Object.entries(listLabels)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${label} (${(state.lists[key] || []).length})`;
    button.classList.toggle("active", state.selectedList === key);
    button.addEventListener("click", () => {
      state.selectedList = key;
      state.listFilter = "";
      renderListEditor();
    });
    listTabs.appendChild(button);
  }
}

function normalizeListValue(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLocaleLowerCase("pl-PL");
}

function boundedEditDistance(a, b, maxDistance = 4) {
  if (Math.abs(a.length - b.length) > maxDistance) return maxDistance + 1;
  const previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  const current = Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i += 1) {
    current[0] = i;
    let rowMin = current[0];
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost);
      rowMin = Math.min(rowMin, current[j]);
    }
    if (rowMin > maxDistance) return maxDistance + 1;
    for (let j = 0; j <= b.length; j += 1) previous[j] = current[j];
  }
  return previous[b.length];
}

function listMatch(value, query) {
  const normalized = normalizeListValue(value);
  const needle = normalizeListValue(query);
  if (!needle) {
    return { visible: true, rank: 9, distance: 0, className: "" };
  }
  if (normalized === needle) {
    return { visible: true, rank: 0, distance: 0, className: "exact-match" };
  }
  if (normalized.startsWith(needle)) {
    return { visible: true, rank: 1, distance: normalized.length - needle.length, className: "partial-match" };
  }
  if (normalized.includes(needle)) {
    return { visible: true, rank: 2, distance: normalized.length - needle.length, className: "partial-match" };
  }
  const maxDistance = needle.length <= 5 ? 2 : 4;
  const distance = boundedEditDistance(normalized, needle, maxDistance);
  if (distance <= maxDistance) {
    return { visible: true, rank: 3, distance, className: "similar-match" };
  }
  return { visible: false, rank: 99, distance: 99, className: "" };
}

function ensureListFilterInfo() {
  let info = document.querySelector("#listFilterInfo");
  if (!info) {
    info = document.createElement("div");
    info.id = "listFilterInfo";
    info.className = "list-filter-info";
    listAddForm.insertAdjacentElement("afterend", info);
  }
  return info;
}

function renderListEditor() {
  renderListTabs();
  listValues.textContent = "";
  listAddInput.value = state.listFilter;
  listAddInput.placeholder = `Nowa wartosc: ${listLabels[state.selectedList]}`;
  const info = ensureListFilterInfo();
  const query = state.listFilter;
  const values = state.lists[state.selectedList] || [];
  const rows = values
    .map((value, index) => ({ value, index, match: listMatch(value, query) }))
    .filter((item) => item.match.visible)
    .sort((left, right) => {
      if (!query) return left.index - right.index;
      return (
        left.match.rank - right.match.rank ||
        left.match.distance - right.match.distance ||
        left.value.localeCompare(right.value, "pl")
      );
    });
  const duplicate = Boolean(query) && values.some((value) => normalizeListValue(value) === normalizeListValue(query));
  if (query) {
    info.textContent = duplicate
      ? "Taka wartosc juz istnieje. Dodawanie duplikatu jest zablokowane."
      : `Pasujace wpisy: ${rows.length}. Enter doda nowa wartosc, jesli nie jest duplikatem.`;
    info.classList.toggle("duplicate", duplicate);
  } else {
    info.textContent = "";
    info.classList.remove("duplicate");
  }
  for (const { value, match } of rows) {
    const row = document.createElement("div");
    row.className = `list-value-row ${match.className}`;
    const text = document.createElement("span");
    const remove = document.createElement("button");
    text.textContent = value;
    if (match.rank === 3) {
      row.title = `Podobny wpis, roznica znakow: ${match.distance}`;
    }
    remove.type = "button";
    remove.className = "icon-button";
    remove.textContent = "X";
    remove.title = "Usun";
    remove.addEventListener("click", () => removeListValue(value));
    row.append(text, remove);
    listValues.appendChild(row);
  }
  if (!rows.length && query) {
    const empty = document.createElement("div");
    empty.className = "list-empty-filter";
    empty.textContent = "Brak podobnych wpisow.";
    listValues.appendChild(empty);
  }
}

function setBusy(isBusy, text = "") {
  if (submitButton) {
    submitButton.dataset.busy = isBusy ? "1" : "";
    submitButton.disabled = Boolean(isBusy);
  }
  formStatus.textContent = text;
  updateSubmitButtonState();
}

function stopProcessStatusTicker(text = "") {
  window.clearInterval(state.processStatusTimer);
  state.processStatusTimer = 0;
  state.processStatusStartedAt = 0;
  if (text) formStatus.textContent = text;
}

function startProcessStatusTicker(label, prefixes = new Set()) {
  stopProcessStatusTicker();
  const phaseTexts = [
    "backend zapisuje lokalne zmiany",
    "backend sprawdza brakujace zrodla",
    "backend synchronizuje FTP/SQL",
    "czekam na odpowiedz backendu",
  ];
  const changed = [...prefixes].filter(Boolean).sort();
  const slotText = changed.length ? ` Sloty: ${changed.join(", ")}.` : "";
  let step = 0;
  state.processStatusStartedAt = performance.now();
  const render = () => {
    const elapsed = Math.max(1, Math.round((performance.now() - state.processStatusStartedAt) / 1000));
    const phase = phaseTexts[Math.min(step, phaseTexts.length - 1)];
    formStatus.textContent = `${label}: ${phase} (${elapsed} s).${slotText}`;
    step += 1;
  };
  render();
  state.processStatusTimer = window.setInterval(render, 5000);
}

function clearResult() {
  resultMeta.textContent = "";
  resultOutput.className = "result-output empty-state";
  resultOutput.textContent = "Brak aktywnych pomiarow.";
}

function showError(error) {
  resultMeta.textContent = "";
  resultOutput.className = "result-output error-text";
  resultOutput.textContent = error.message || String(error);
}

function processingOperationLabel(operation) {
  const labels = {
    copy_preprocessed: "kopiowanie po obrobce",
    copy_without_processing: "kopiowanie bez obrobki",
    copy_document: "kopiowanie dokumentu",
    copy_unsupported_image: "kopiowanie formatu bez obrobki",
    copy_no_pillow: "kopiowanie bez Pillow",
    process_image: "resize/kompresja",
    same_target: "bez kopiowania",
  };
  return labels[operation] || operation || "plik";
}

function renderTimingDetails(timing, savedFiles = []) {
  const stages = timing?.stages || [];
  const files = savedFiles || [];
  if (!stages.length && !files.length) return null;
  const box = document.createElement("details");
  const summary = document.createElement("summary");
  const list = document.createElement("div");
  box.className = "timing-details";
  summary.textContent = `Czas operacji: ${formatDuration(timing?.total_ms)}`;
  list.className = "timing-list";
  for (const stage of stages) {
    const row = document.createElement("div");
    const label = document.createElement("span");
    const value = document.createElement("strong");
    const details = stage.details || {};
    const detailText =
      stage.key === "antivirus_scan"
        ? ` (${details.enabled ? "wlaczony" : "wylaczony"}, skan: ${details.scanned || 0})`
        : "";
    label.textContent = `${stage.label || stage.key || "Etap"}${detailText}`;
    value.textContent = formatDuration(stage.elapsed_ms);
    row.append(label, value);
    list.appendChild(row);
  }
  if (files.length) {
    const section = document.createElement("div");
    section.className = "timing-section";
    section.textContent = "Pliki";
    list.appendChild(section);
  }
  for (const file of files) {
    const row = document.createElement("div");
    const label = document.createElement("span");
    const value = document.createElement("strong");
    const flags = [];
    if (file.preprocessed) flags.push("preprocessed");
    if (file.content_fit) flags.push("FIT");
    const sizes =
      file.source_size_bytes || file.size_bytes
        ? ` (${formatFileSize(file.source_size_bytes)} -> ${formatFileSize(file.size_bytes)})`
        : "";
    const suffix = flags.length ? `, ${flags.join(", ")}` : "";
    const operation = processingOperationLabel(file.operation);
    label.textContent = `${file.prefix || "Slot"} - ${operation}${suffix}${sizes}`;
    value.textContent = formatDuration(file.elapsed_ms);
    row.append(label, value);
    list.appendChild(row);
  }
  box.append(summary, list);
  return box;
}

function showResult(payload) {
  resultOutput.className = "result-output";
  resultOutput.textContent = "";
  resultMeta.textContent = payload.timing?.total_ms ? `Czas: ${formatDuration(payload.timing.total_ms)}` : "";
  if (payload.entry && payload.entry.product_id) {
    productForm.elements.product_id.value = payload.entry.product_id;
  }
  if (!productForm.elements.ean.value && payload.ean && payload.ean !== "BRAK-EAN") {
    productForm.elements.ean.value = payload.ean;
  }
  const timing = renderTimingDetails(payload.timing, []);
  if (timing) {
    resultOutput.appendChild(timing);
  } else {
    resultOutput.className = "result-output empty-state";
    resultOutput.textContent = "Brak danych pomiarowych.";
  }
}

function processJobIsActive(job = {}) {
  return ["queued", "running"].includes(job.status || "");
}

function processJobProblemMessages(job = {}) {
  if (job.status === "failed") {
    return [job.error || "Zadanie nie powiodlo sie."];
  }
  return job.warning_messages || [];
}

function entryFromProcessJob(job = {}) {
  if (job.result) {
    return entryFromProcessPayload(job.result, job.entry || {});
  }
  const entry = { ...(job.entry || {}) };
  entry.label = productEntryLabel(entry);
  return entry;
}

function closeProcessAlert() {
  processAlertModal?.classList.remove("active");
  if (processAlertLoadButton) {
    processAlertLoadButton.dataset.jobId = "";
  }
}

function showProcessJobAlert(job = {}) {
  if (!processAlertModal || state.acknowledgedProcessAlerts.has(job.job_id)) {
    return;
  }
  const messages = processJobProblemMessages(job);
  if (!messages.length) {
    return;
  }
  state.acknowledgedProcessAlerts.add(job.job_id);
  if (processAlertTitle) {
    processAlertTitle.textContent =
      job.status === "failed" ? "Zadanie nie powiodlo sie" : "Zadanie zakonczone z ostrzezeniem";
  }
  if (processAlertEntry) {
    processAlertEntry.textContent = `Wpis: ${job.entry_label || productEntryLabel(job.entry || {}) || "bez danych"}`;
  }
  if (processAlertMessage) {
    processAlertMessage.textContent = messages.join(" | ");
  }
  if (processAlertLoadButton) {
    processAlertLoadButton.dataset.jobId = job.job_id || "";
    processAlertLoadButton.disabled = !job.entry;
  }
  processAlertModal.classList.add("active");
}

function showQueuedProcess(job = {}) {
  resultMeta.textContent = "Kolejka";
  resultOutput.className = "result-output";
  resultOutput.textContent = "";
  const message = document.createElement("p");
  message.className = "ok-text";
  message.textContent = `Przyjeto zadanie dla wpisu: ${
    job.entry_label || productEntryLabel(job.entry || {}) || "bez danych"
  }. Pomiary beda aktualizowane podczas pracy kolejki.`;
  resultOutput.appendChild(message);
}

function clampProgress(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0))));
}

function processQueueMeta(job = {}) {
  const user = job.username ? `uzytkownik: ${job.username}` : "";
  if (job.status === "running") {
    return ["Teraz", user].filter(Boolean).join(" | ");
  }
  const position = Number(job.queue_position || 0);
  return [`W kolejce${position ? ` #${position}` : ""}`, user].filter(Boolean).join(" | ");
}

function processQueueElapsedMs(job = {}, payload = state.processQueue, key = "started_at") {
  const reference = Number(payload.server_time || Date.now() / 1000);
  const started = Number(job[key] || 0);
  return started > 0 ? Math.max(0, Math.round((reference - started) * 1000)) : 0;
}

function processMetricRow(labelText, valueText, options = {}) {
  const row = document.createElement("div");
  const label = document.createElement("span");
  const value = document.createElement("strong");
  if (options.wide) {
    row.className = "wide";
  }
  label.textContent = labelText;
  value.textContent = valueText;
  row.append(label, value);
  return row;
}

function renderProcessMeasurements(payload = state.processQueue) {
  if (!resultOutput || !resultMeta) {
    return;
  }
  applyTimingDetailsVisibility();
  if (!showTimingDetails()) {
    return;
  }
  const jobs = payload.jobs || [];
  const current = jobs.find((job) => job.status === "running");
  resultOutput.textContent = "";
  if (!jobs.length) {
    resultMeta.textContent = "";
    resultOutput.className = "result-output empty-state";
    resultOutput.textContent = "Brak aktywnych pomiarow.";
    return;
  }
  resultOutput.className = "result-output";
  const metrics = document.createElement("div");
  metrics.className = "timing-list";
  if (current) {
    const stages = current.timing?.stages || [];
    resultMeta.textContent = `${clampProgress(current.progress)}% | czeka: ${payload.queued_count || 0}`;
    metrics.append(
      processMetricRow("Aktualny towar", current.entry_label || "zadanie", { wide: true }),
      processMetricRow("Etap", current.progress_label || "Trwa"),
      processMetricRow("Czas zadania", formatDuration(processQueueElapsedMs(current, payload, "started_at"))),
      processMetricRow("Czas od zlecenia", formatDuration(processQueueElapsedMs(current, payload, "created_at"))),
      processMetricRow("Oczekuje w kolejce", String(payload.queued_count || 0))
    );
    if (stages.length) {
      const section = document.createElement("div");
      section.className = "timing-section";
      section.textContent = "Czynnosci";
      metrics.appendChild(section);
      for (const stage of stages) {
        metrics.appendChild(
          processMetricRow(
            stage.running ? `${stage.label || stage.key} (trwa)` : stage.label || stage.key || "Etap",
            timingMs(stage.elapsed_ms)
          )
        );
      }
    }
  } else {
    const first = jobs[0] || {};
    resultMeta.textContent = `Czeka: ${payload.queued_count || jobs.length}`;
    metrics.append(
      processMetricRow("Pierwszy w kolejce", first.entry_label || "zadanie", { wide: true }),
      processMetricRow("Czas oczekiwania", formatDuration(processQueueElapsedMs(first, payload, "created_at"))),
      processMetricRow("Liczba zadan", String(jobs.length))
    );
  }
  resultOutput.appendChild(metrics);
}

function renderProcessQueue(payload = state.processQueue) {
  if (!processQueuePanel || !processQueueList || !processQueueSummary) {
    return;
  }
  const jobs = payload.jobs || [];
  state.processQueue = payload;
  processQueuePanel.classList.toggle("empty", !jobs.length);
  processQueueList.textContent = "";
  if (!jobs.length) {
    processQueueSummary.textContent = "Brak zadan";
    processQueueList.className = "process-queue-list empty-state";
    processQueueList.textContent = "Kolejka pusta.";
    renderProcessMeasurements(payload);
    return;
  }
  const current = jobs.find((job) => job.status === "running");
  processQueueSummary.textContent = current
    ? `Teraz: ${current.entry_label || "zadanie"} | czeka: ${payload.queued_count || 0}`
    : `Czeka: ${payload.queued_count || jobs.length}`;
  processQueueList.className = "process-queue-list";
  for (const job of jobs) {
    const item = document.createElement("article");
    const meta = document.createElement("div");
    const title = document.createElement("strong");
    const stage = document.createElement("span");
    const progressLine = document.createElement("div");
    const progressBar = document.createElement("i");
    const progressText = document.createElement("small");
    const progress = clampProgress(job.progress);
    item.className = `process-queue-item process-queue-${job.status || "queued"}`;
    meta.className = "process-queue-meta";
    meta.textContent = processQueueMeta(job);
    title.textContent = job.entry_label || productEntryLabel(job.entry || {}) || "Zadanie bez nazwy";
    stage.textContent =
      job.progress_label || processStatusLabels[job.status] || job.status || "Zadanie";
    progressLine.className = "process-queue-progress";
    progressLine.style.setProperty("--queue-progress", `${progress}%`);
    progressText.textContent = `${progress}%`;
    progressLine.appendChild(progressBar);
    item.append(meta, title, stage, progressLine, progressText);
    processQueueList.appendChild(item);
  }
  renderProcessMeasurements(payload);
}

async function fetchProcessJobs({ activeJob } = {}) {
  const payload = await requestJson("/api/process-jobs/active");
  const previousJobId = activeJob?.job_id || "";
  const activeJobIds = new Set((payload.jobs || []).map((job) => job.job_id));
  if (previousJobId && !activeJobIds.has(previousJobId)) {
    try {
      payload.completedJob = await requestJson(
        `/api/process-jobs/${encodeURIComponent(previousJobId)}`
      );
    } catch (error) {
      payload.completedJob = {
        ...activeJob,
        status: "failed",
        error: error.message || "Nie udalo sie sprawdzic statusu zadania.",
      };
    }
  }
  return payload;
}

function renderProcessJobs(payload = {}) {
  for (const job of payload.jobs || []) {
    updateProcessJobFromPayload(job);
  }
  if (payload.completedJob) {
    updateProcessJobFromPayload(payload.completedJob);
  }
  renderProcessQueue(payload);
}

const processJobsController = new PicSyncra.ProcessJobsController({
  fetchJobs: fetchProcessJobs,
  render: renderProcessJobs,
  timerApi: window,
});
state.processJobsController = processJobsController;

function refreshProcessQueue(runtimeVersion) {
  return processJobsController.refresh(runtimeVersion);
}

function updateProcessJobFromPayload(job = {}) {
  if (!job.job_id) return;
  const previous = state.processJobs.get(job.job_id) || {};
  const merged = { ...previous, ...job };
  state.processJobs.set(job.job_id, merged);
  if (processJobIsActive(merged)) {
    return;
  }
  if (merged.result) {
    upsertProductEntry(entryFromProcessJob(merged));
    if (merged.result.file_index) {
      state.fileIndex = merged.result.file_index;
      updateRuntimeMetrics();
    }
  }
  const messages = processJobProblemMessages(merged);
  if (messages.length) {
    showProcessJobAlert(merged);
    formStatus.textContent = `Zadanie w tle ma problem: ${messages[0]}`;
  } else if (!hasProductDraftData()) {
    formStatus.textContent = `Zadanie w tle zakonczone: ${merged.entry_label || "wpis"}.`;
  }
}

function trackProcessJob(job = {}) {
  if (!job.job_id) {
    return;
  }
  state.processJobs.set(job.job_id, job);
  refreshProcessQueue().catch(() => {});
}

async function loadRecentProcessJobs() {
  const payload = await requestJson("/api/process-jobs?limit=10");
  for (const job of payload.jobs || []) {
    if (processJobIsActive(job)) {
      trackProcessJob(job);
    } else if (processJobProblemMessages(job).length) {
      updateProcessJobFromPayload(job);
    }
  }
}

function entryFromHistoryGroup(group) {
  if (group.entry && typeof group.entry === "object") {
    return group.entry;
  }
  for (const item of group.items || []) {
    if (item.details?.entry) return item.details.entry;
  }
  return {};
}

function entryField(entry, ...keys) {
  for (const key of keys) {
    const value = entry?.[key];
    if (value) return value;
  }
  return "";
}

function historyEntryLabel(entry) {
  const colors = [
    entryField(entry, "KOLOR1", "color1"),
    entryField(entry, "KOLOR2", "color2"),
    entryField(entry, "KOLOR3", "color3"),
  ]
    .filter(Boolean)
    .join(" / ");
  return [
    entryField(entry, "NAZWA", "name") ? `Nazwa: ${entryField(entry, "NAZWA", "name")}` : "",
    entryField(entry, "TYP", "type_name") ? `Typ: ${entryField(entry, "TYP", "type_name")}` : "",
    entryField(entry, "MODEL", "model") ? `Model: ${entryField(entry, "MODEL", "model")}` : "",
    colors ? `Kolory: ${colors}` : "",
    entryField(entry, "DODATKI", "extra") ? `Dodatek: ${entryField(entry, "DODATKI", "extra")}` : "",
  ]
    .filter(Boolean)
    .join(" | ");
}

function timingMs(value) {
  return `${Math.max(0, Math.round(Number(value || 0)))} ms`;
}

function historyChangeValue(value) {
  if (value === null || value === undefined || value === "") return "Brak danych";
  if (typeof value === "object") {
    return Array.isArray(value)
      ? `Dane zlozone: lista (${value.length})`
      : `Dane zlozone: obiekt (${Object.keys(value).length})`;
  }
  return String(value);
}

function historyTechnicalValue(value) {
  if (value === null || value === undefined || value === "") return "Brak danych";
  if (typeof value !== "object") return String(value);
  const seen = new WeakSet();
  try {
    const serialized = JSON.stringify(value, (_key, nested) => {
      if (!nested || typeof nested !== "object") return nested;
      if (seen.has(nested)) return "[Dane cykliczne]";
      seen.add(nested);
      if (Array.isArray(nested)) return nested;
      return Object.fromEntries(Object.keys(nested).sort().map((key) => [key, nested[key]]));
    }, 2);
    return serialized === undefined ? "Brak danych" : serialized;
  } catch (_error) {
    return "Nie mozna wyswietlic danych";
  }
}

function formatBytes(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Brak danych";
  const bytes = Math.max(0, Number(value));
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatHistoryDuration(value) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) {
    return "Brak danych";
  }
  return `${Math.max(0, Number(value))} ms`;
}

function historyChangeRow(label, value, formatter = historyChangeValue) {
  const row = document.createElement("div");
  const name = document.createElement("strong");
  const output = document.createElement("span");
  row.className = "history-change-row";
  name.textContent = label;
  output.textContent = formatter(value);
  row.append(name, output);
  return row;
}

function historyChangeSection(title) {
  const section = document.createElement("section");
  const heading = document.createElement("h2");
  section.className = "history-change-section";
  heading.textContent = title;
  section.appendChild(heading);
  return section;
}

function historyChangeComparison(label, before, after, formatter = historyChangeValue) {
  const row = document.createElement("div");
  const heading = document.createElement("strong");
  const values = document.createElement("div");
  const beforeCell = document.createElement("div");
  const beforeLabel = document.createElement("small");
  const beforeValue = document.createElement("span");
  const afterCell = document.createElement("div");
  const afterLabel = document.createElement("small");
  const afterValue = document.createElement("span");
  row.className = "history-change-comparison";
  heading.textContent = historyChangeValue(label);
  values.className = "history-change-before-after";
  beforeCell.className = "history-change-before";
  beforeLabel.textContent = "Przed";
  beforeValue.textContent = formatter(before);
  afterCell.className = "history-change-after";
  afterLabel.textContent = "Po";
  afterValue.textContent = formatter(after);
  beforeCell.append(beforeLabel, beforeValue);
  afterCell.append(afterLabel, afterValue);
  values.append(beforeCell, afterCell);
  row.append(heading, values);
  return row;
}

function historyChangeJobId(details = {}, changeSet = {}) {
  return (
    details.job_id ??
    changeSet.job_id ??
    details.pimcore_operation?.operation_id ??
    changeSet.pimcore?.operation_id
  );
}

function historyFileOperationLabel(operation) {
  return {
    added: "Dodano",
    deleted: "Usunieto",
    replaced: "Zastapiono",
    migrated: "Przeniesiono",
  }[operation] || historyChangeValue(operation);
}

function historyTechnicalDetails(title) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const content = document.createElement("div");
  details.className = "history-technical-details";
  summary.textContent = title;
  content.className = "history-technical-content";
  details.append(summary, content);
  return { details, content };
}

function historyEvidenceEntries(value) {
  if (Array.isArray(value)) return value.filter((entry) => entry && typeof entry === "object");
  return value && typeof value === "object" ? [value] : [];
}

function historyEvidenceStatuses(entry = {}) {
  const statuses = [];
  if (entry.status !== undefined) statuses.push(String(entry.status));
  if (entry.upload_status !== undefined) statuses.push(`wysylka: ${entry.upload_status}`);
  if (entry.delete_status !== undefined) statuses.push(`usuniecie: ${entry.delete_status}`);
  return statuses.length ? statuses : ["brak danych"];
}

function historyEvidenceBadges(evidence = {}) {
  const badges = document.createElement("div");
  badges.className = "history-evidence-badges";
  for (const [key, label] of Object.entries({ local: "Lokalnie", ftp: "FTP", sql: "SQL" })) {
    const entries = historyEvidenceEntries(evidence[key]);
    if (!entries.length) continue;
    const badge = document.createElement("span");
    badge.className = `history-evidence-badge history-evidence-${key}`;
    badge.textContent = `${label}: ${entries.map((entry) => {
      const operation = entry.operation ? `${entry.operation} ` : "";
      const duration = entry.elapsed_ms === undefined ? "" : ` · ${formatHistoryDuration(entry.elapsed_ms)}`;
      return `${operation}${historyEvidenceStatuses(entry).join(", ")}${duration}`;
    }).join(" / ")}`;
    badges.appendChild(badge);
  }
  return badges;
}

function historyEvidenceDetails(evidence = {}) {
  const wrapper = document.createElement("section");
  wrapper.className = "history-evidence-details";
  for (const [key, label] of Object.entries({ local: "Lokalnie", ftp: "FTP", sql: "SQL" })) {
    const entries = historyEvidenceEntries(evidence[key]);
    for (const entry of entries) {
      const operation = document.createElement("article");
      const heading = document.createElement("h4");
      operation.className = `history-evidence-operation history-evidence-${key}`;
      heading.textContent = `${label}: ${entry.operation || "operacja"}`;
      operation.append(
        heading,
        historyChangeRow("Status", historyEvidenceStatuses(entry).join(", "))
      );
      if (entry.elapsed_ms !== undefined) {
        operation.appendChild(historyChangeRow("Czas", formatHistoryDuration(entry.elapsed_ms)));
      }
      for (const [field, fieldLabel] of Object.entries({
        filename: "Plik",
        path: "Sciezka",
        local_path: "Sciezka lokalna",
        remote_path: "Sciezka FTP",
        sql_value: "Wartosc SQL",
      })) {
        if (entry[field] !== undefined) operation.appendChild(historyChangeRow(fieldLabel, entry[field]));
      }
      wrapper.appendChild(operation);
    }
  }
  return wrapper;
}

function historyCompactFileRow(file = {}) {
  const operation = String(file.operation || "unknown").toLowerCase();
  const operationClass = ["added", "deleted", "replaced", "migrated"].includes(operation)
    ? operation
    : "unknown";
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const slot = document.createElement("strong");
  const action = document.createElement("span");
  const filename = document.createElement("span");
  const size = document.createElement("span");
  const content = document.createElement("div");
  const evidence = file.evidence && typeof file.evidence === "object" ? file.evidence : {};
  details.className = `history-file-change history-file-change-${operationClass}`;
  summary.className = "history-file-summary-row";
  slot.textContent = `Slot ${historyChangeValue(file.slot)}`;
  action.textContent = historyFileOperationLabel(operation);
  filename.textContent = `${historyChangeValue(file.before_name)} → ${historyChangeValue(file.after_name)}`;
  size.textContent = `${formatBytes(file.before_size_bytes)} → ${formatBytes(file.after_size_bytes)}`;
  content.className = "history-file-details";
  summary.append(slot, action, filename, size, historyEvidenceBadges(evidence));
  content.append(
    historyChangeComparison("Nazwa", file.before_name, file.after_name),
    historyChangeComparison("Rozmiar", file.before_size_bytes, file.after_size_bytes, formatBytes)
  );
  if (file.source_name !== undefined || file.source_size_bytes !== undefined) {
    content.append(
      historyChangeRow("Plik zrodlowy", file.source_name),
      historyChangeRow("Rozmiar zrodlowy", formatBytes(file.source_size_bytes))
    );
  }
  if (file.processing_operation !== undefined) {
    content.appendChild(historyChangeRow("Przetwarzanie", file.processing_operation));
  }
  if (file.elapsed_ms !== undefined) {
    content.appendChild(historyChangeRow("Czas", formatHistoryDuration(file.elapsed_ms)));
  }
  if (file.content_fit !== undefined) {
    content.appendChild(historyChangeRow("Dopasowanie zawartosci", file.content_fit ? "Tak" : "Nie"));
  }
  if (file.preprocessed !== undefined) {
    content.appendChild(historyChangeRow("Wstepnie przetworzony", file.preprocessed ? "Tak" : "Nie"));
  }
  const evidenceDetails = historyEvidenceDetails(evidence);
  if (evidenceDetails.childElementCount) content.appendChild(evidenceDetails);
  details.append(summary, content);
  return details;
}

let historyChangesReturnFocus = null;
let historyChangesBackgroundState = [];

function setHistoryChangesBackgroundInert() {
  if (historyChangesBackgroundState.length) return;
  const backgroundModals = document.querySelectorAll(
    "#historyView.active, #historyDetailModal.active, #historyTimingModal.active"
  );
  historyChangesBackgroundState = Array.from(backgroundModals)
    .filter((modal) => modal !== historyChangesModal)
    .map((modal) => {
      const state = {
        modal,
        inert: modal.getAttribute("inert"),
        ariaHidden: modal.getAttribute("aria-hidden"),
      };
      modal.setAttribute("inert", "");
      modal.setAttribute("aria-hidden", "true");
      return state;
    });
}

function restoreHistoryChangesBackground() {
  for (const state of historyChangesBackgroundState) {
    if (state.inert === null) {
      state.modal.removeAttribute("inert");
    } else {
      state.modal.setAttribute("inert", state.inert);
    }
    if (state.ariaHidden === null) {
      state.modal.removeAttribute("aria-hidden");
    } else {
      state.modal.setAttribute("aria-hidden", state.ariaHidden);
    }
  }
  historyChangesBackgroundState = [];
}

function openHistoryChangesModal() {
  if (!historyChangesModal) return;
  if (!historyChangesModal.classList.contains("active")) {
    historyChangesReturnFocus = document.activeElement;
    setHistoryChangesBackgroundInert();
  }
  historyChangesModal.classList.add("active");
  window.setTimeout(() => historyChangesCloseButton?.focus(), 0);
}

function closeHistoryChangesModal({ restoreFocus = true } = {}) {
  historyChangesModal?.classList.remove("active");
  restoreHistoryChangesBackground();
  if (restoreFocus && historyChangesReturnFocus?.focus) {
    historyChangesReturnFocus.focus();
  }
  historyChangesReturnFocus = null;
}

function trapHistoryChangesFocus(event) {
  if (!historyChangesModal?.classList.contains("active")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeHistoryChangesModal();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(
    historyChangesModal.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  ).filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
  if (!focusable.length) {
    event.preventDefault();
    historyChangesModal.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const focusOutside = !historyChangesModal.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || focusOutside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || focusOutside)) {
    event.preventDefault();
    first.focus();
  }
}

function renderHistoryTiming(item = {}, { open = true } = {}) {
  state.historyTimingItem = item;
  if (!historyTimingTitle || !historyTimingOutput) {
    return;
  }
  const timing = item.details?.timing || {};
  historyTimingTitle.textContent = `Czasy: ${formatPanelTimestamp(item.ts || item.created_at, {
    epochUnit: "seconds",
  })}`;
  historyTimingOutput.textContent = "";
  const stages = timing.stages || [];
  historyTimingOutput.appendChild(processMetricRow("Razem", timingMs(timing.total_ms)));
  if (stages.length) {
    const section = document.createElement("div");
    section.className = "timing-section";
    section.textContent = "Czynnosci";
    historyTimingOutput.appendChild(section);
  }
  for (const stage of stages) {
    historyTimingOutput.appendChild(
      processMetricRow(stage.label || stage.key || "Etap", timingMs(stage.elapsed_ms))
    );
  }
  if (!stages.length && !timing.total_ms) {
    historyTimingOutput.className = "timing-list empty-state";
    historyTimingOutput.textContent = "Ta zmiana nie ma zapisanych pomiarow czasu.";
  } else {
    historyTimingOutput.className = "timing-list";
  }
  if (open) document.querySelector("#historyTimingModal")?.classList.add("active");
}

function renderHistoryChanges(item = {}, { open = true } = {}) {
  state.historyChangesItem = item;
  if (!historyChangesModal || !historyChangesTitle || !historyChangesOutput) {
    return;
  }
  const details = item.details && typeof item.details === "object" ? item.details : {};
  const changeSet = details.change_set && typeof details.change_set === "object"
    ? details.change_set
    : null;
  historyChangesTitle.textContent = `Zmiany: ${formatPanelTimestamp(item.ts || item.created_at, {
    epochUnit: "seconds",
  })}`;
  historyChangesOutput.textContent = "";

  if (!changeSet) {
    const compatibility = document.createElement("p");
    historyChangesOutput.className = "history-changes-output empty-state";
    compatibility.textContent = "Szczegolowy zapis zmian nie byl jeszcze dostepny dla tej operacji.";
    historyChangesOutput.appendChild(compatibility);
    if (Object.keys(details).length) {
      const legacy = historyTechnicalDetails("Dane techniczne");
      for (const [key, value] of Object.entries(details)) {
        legacy.content.appendChild(historyChangeRow(key, value, historyTechnicalValue));
      }
      historyChangesOutput.appendChild(legacy.details);
    }
    if (open) openHistoryChangesModal();
    return;
  }

  historyChangesOutput.className = "history-changes-output";
  const overview = historyChangeSection("Operacja");
  overview.appendChild(historyChangeRow("Rodzaj", changeSet.kind));
  const jobId = historyChangeJobId(details, changeSet);
  if (jobId !== null && jobId !== undefined && jobId !== "") {
    overview.appendChild(historyChangeRow("ID zadania", jobId));
  }
  historyChangesOutput.appendChild(overview);

  const fields = Array.isArray(changeSet.fields) ? changeSet.fields : [];
  if (fields.length) {
    const section = historyChangeSection("Pola produktu");
    for (const field of fields) {
      section.appendChild(
        historyChangeComparison(field.label || field.key, field.before, field.after)
      );
    }
    historyChangesOutput.appendChild(section);
  }

  const pimcore = changeSet.pimcore && typeof changeSet.pimcore === "object"
    ? changeSet.pimcore
    : {};
  const pimcoreFields = Array.isArray(pimcore.fields) ? pimcore.fields : [];
  if (pimcore.kind || pimcoreFields.length) {
    const section = historyChangeSection("Pimcore");
    if (pimcore.kind) {
      section.appendChild(historyChangeRow("Rodzaj", pimcore.kind));
    }
    if (pimcore.object_id !== undefined) {
      section.appendChild(historyChangeRow("ID obiektu", pimcore.object_id));
    }
    if (pimcore.object_path !== undefined) {
      section.appendChild(historyChangeRow("Sciezka obiektu", pimcore.object_path));
    }
    if (pimcore.total_ms !== undefined) {
      section.appendChild(historyChangeRow("Czas calkowity", formatHistoryDuration(pimcore.total_ms)));
    }
    if (pimcore.send_ms !== undefined) {
      section.appendChild(historyChangeRow("Wysylka", formatHistoryDuration(pimcore.send_ms)));
    }
    if (pimcore.verification_ms !== undefined) {
      section.appendChild(historyChangeRow("Weryfikacja", formatHistoryDuration(pimcore.verification_ms)));
    }
    for (const field of pimcoreFields) {
      section.appendChild(
        historyChangeComparison(field.label || field.key, field.before, field.after)
      );
    }
    historyChangesOutput.appendChild(section);
  }

  const files = Array.isArray(changeSet.files) ? changeSet.files : [];
  if (files.length) {
    const section = historyChangeSection("Pliki");
    for (const file of files) {
      section.appendChild(historyCompactFileRow(file));
    }
    historyChangesOutput.appendChild(section);
  }

  const integrations = changeSet.integrations && typeof changeSet.integrations === "object"
    ? changeSet.integrations
    : null;
  if (integrations && Object.keys(integrations).length) {
    const section = historyTechnicalDetails("Dane techniczne");
    for (const [key, value] of Object.entries(integrations)) {
      section.content.appendChild(historyChangeRow(key, value, historyTechnicalValue));
    }
    historyChangesOutput.appendChild(section.details);
  }

  if (open) openHistoryChangesModal();
}

function rerenderHistoryDetailTimestamps() {
  const items = Array.isArray(state.historyDetailGroup?.items)
    ? state.historyDetailGroup.items
    : [];
  historyDetailOutput?.querySelectorAll("[data-history-item-index]").forEach((meta) => {
    const item = items[Number(meta.dataset.historyItemIndex)];
    if (!item) return;
    meta.textContent = `${formatPanelTimestamp(item.ts || item.created_at, {
      epochUnit: "seconds",
    })} | ${item.user || ""}`;
  });
}

function renderHistoryDetails(group, { open = true } = {}) {
  state.historyDetailGroup = group;
  state.historyDetailPage = Number(group.page || state.historyDetailPage || 1);
  historyDetailTitle.textContent = `Historia EAN ${group.ean}`;
  historyDetailOutput.className = "history-detail-output";
  historyDetailOutput.textContent = "";
  const fragment = document.createDocumentFragment();
  for (const [itemIndex, item] of (group.items || []).entries()) {
    const row = document.createElement("article");
    const meta = document.createElement("div");
    const summary = document.createElement("strong");
    const details = document.createElement("span");
    const actions = document.createElement("div");
    const changesButton = document.createElement("button");
    const timingButton = document.createElement("button");
    row.className = "history-item";
    meta.className = "history-meta";
    meta.dataset.historyItemIndex = String(itemIndex);
    meta.textContent = `${formatPanelTimestamp(item.ts || item.created_at, {
      epochUnit: "seconds",
    })} | ${item.user || ""}`;
    summary.textContent = item.summary || item.action || "Zmiana";
    const saved = item.details?.saved_files?.length || 0;
    const deleted = item.details?.deleted_slots?.length || 0;
    const ftp = item.details?.ftp;
    const sql = item.details?.sql;
    details.textContent = [
      historyEntryLabel(item.details?.entry) || "",
      saved ? `zapisane pliki: ${saved}` : "",
      deleted ? `usuniete sloty: ${deleted}` : "",
      item.details?.local_delete?.deleted ? `usunieto lokalnie: ${item.details.local_delete.deleted}` : "",
      ftp?.enabled ? `FTP wyslano/usunieto: ${ftp.uploaded || 0}/${ftp.deleted || 0}${ftp.error ? `, blad: ${ftp.error}` : ""}` : "",
      sql?.enabled ? `SQL aktualizacje/czyszczenia: ${sql.updated || 0}/${sql.cleared || 0}${sql.error ? `, blad: ${sql.error}` : ""}` : "",
    ]
      .filter(Boolean)
      .join(" | ");
    actions.className = "history-item-actions";
    changesButton.type = "button";
    changesButton.className = "secondary-button";
    changesButton.textContent = "Zmiany";
    const hasChangeSet = Boolean(item.details?.change_set);
    const hasLegacyDetails = Boolean(
      item.details && typeof item.details === "object" && Object.keys(item.details).length
    );
    changesButton.disabled = !hasChangeSet && !hasLegacyDetails;
    changesButton.addEventListener("click", () => renderHistoryChanges(item));
    timingButton.type = "button";
    timingButton.className = "secondary-button";
    timingButton.textContent = "Czasy";
    timingButton.disabled = !item.details?.timing;
    timingButton.addEventListener("click", () => renderHistoryTiming(item));
    actions.append(changesButton, timingButton);
    row.append(meta, summary, details, actions);
    fragment.appendChild(row);
  }
  historyDetailOutput.appendChild(fragment);
  updateHistoryDetailPagination(group);
  if (open) document.querySelector("#historyDetailModal").classList.add("active");
}

function updateHistoryDetailPagination(payload) {
  const page = Number(payload.page || state.historyDetailPage || 1);
  const totalPages = Number(payload.total_pages || 1);
  const totalItems = Number(payload.total_items || 0);
  if (historyDetailPageInfo) {
    historyDetailPageInfo.textContent = `Strona ${page}/${totalPages} | wpisy: ${totalItems}`;
  }
  if (historyDetailPrevButton) {
    historyDetailPrevButton.disabled = page <= 1;
  }
  if (historyDetailNextButton) {
    historyDetailNextButton.disabled = page >= totalPages;
  }
}

function updateHistoryPagination(payload) {
  if (!historyPageInfo) {
    return;
  }
  const page = Number(payload.page || 1);
  const totalPages = Number(payload.total_pages || 1);
  const totalGroups = Number(payload.total_groups || 0);
  historyPageInfo.textContent = `Strona ${page}/${totalPages} | wpisy: ${totalGroups}`;
  if (historyPrevButton) {
    historyPrevButton.disabled = page <= 1;
  }
  if (historyNextButton) {
    historyNextButton.disabled = page >= totalPages;
  }
}

function renderHistory(payload) {
  state.history = payload;
  state.historyPage = Number(payload.page || state.historyPage || 1);
  const selectedUser = historyUserFilter.value;
  historyUserFilter.textContent = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "Wszyscy uzytkownicy";
  historyUserFilter.appendChild(all);
  for (const user of payload.users || []) {
    const option = document.createElement("option");
    option.value = user;
    option.textContent = user;
    option.selected = user === selectedUser;
    historyUserFilter.appendChild(option);
  }
  historyOutput.textContent = "";
  updateHistoryPagination(payload);
  const groups = payload.groups || [];
  if (!groups.length) {
    historyOutput.className = "history-output empty-state";
    historyOutput.textContent = "Brak historii dla wybranego filtra.";
    return;
  }
  historyOutput.className = "history-output";
  for (const group of groups) {
    const entry = entryFromHistoryGroup(group);
    const row = document.createElement("button");
    const title = document.createElement("strong");
    const fields = document.createElement("span");
    const meta = document.createElement("small");
    row.type = "button";
    row.className = "history-summary-row";
    title.textContent = `EAN ${group.ean}`;
    const readableFields = historyEntryLabel(entry);
    fields.textContent = readableFields || "Brak danych pol tekstowych";
    meta.textContent = `${Number(group.change_count || 0)} zmian | ostatnio: ${formatPanelTimestamp(
      group.latest_ts,
      { epochUnit: "seconds" }
    )}`;
    row.append(title, fields, meta);
    row.addEventListener("click", () => {
      loadHistoryDetails(group).catch(showHistoryDetailLoadError);
    });
    historyOutput.appendChild(row);
  }
}

function closeHistoryDetail() {
  historyDetailsController?.abort();
  historyDetailsController = null;
  state.historyDetailGroup = null;
  state.historyDetailPage = 1;
  if (historyDetailPrevButton) historyDetailPrevButton.disabled = true;
  if (historyDetailNextButton) historyDetailNextButton.disabled = true;
  if (historyDetailPageInfo) historyDetailPageInfo.textContent = "Strona 1";
  document.querySelector("#historyDetailModal")?.classList.remove("active");
}

async function loadHistoryDetails(group, { page = 1 } = {}) {
  historyDetailsController?.abort();
  const controller = new AbortController();
  historyDetailsController = controller;
  state.historyDetailGroup = group;
  state.historyDetailPage = page;
  if (historyDetailPrevButton) historyDetailPrevButton.disabled = true;
  if (historyDetailNextButton) historyDetailNextButton.disabled = true;
  if (historyDetailPageInfo) historyDetailPageInfo.textContent = "Wczytywanie...";
  historyDetailTitle.textContent = `Historia EAN ${group.ean}`;
  historyDetailOutput.className = "history-detail-output empty-state";
  historyDetailOutput.textContent = "Wczytywanie szczegolow historii...";
  document.querySelector("#historyDetailModal")?.classList.add("active");
  const params = new URLSearchParams({
    ean: group.ean || "",
    user: historyUserFilter?.value || "",
    query: historySearchInput?.value || "",
    page: String(page),
    page_size: String(state.historyDetailPageSize),
  });
  try {
    const payload = await requestJson(`/api/history/details?${params.toString()}`, {
      signal: controller.signal,
    });
    if (controller.signal.aborted || historyDetailsController !== controller) return;
    renderHistoryDetails(payload);
  } finally {
    if (historyDetailsController === controller) historyDetailsController = null;
  }
}

async function loadHistory(options = {}) {
  historyLoadController?.abort();
  const controller = new AbortController();
  historyLoadController = controller;
  const page = Math.max(1, Number(options.page || state.historyPage || 1));
  state.historyPage = page;
  const params = new URLSearchParams({
    user: historyUserFilter?.value || "",
    query: historySearchInput?.value || "",
    page: String(page),
    page_size: String(state.historyPageSize || 50),
  });
  try {
    const payload = await requestJson(`/api/history?${params.toString()}`, {
      signal: controller.signal,
    });
    if (controller.signal.aborted || historyLoadController !== controller) return;
    renderHistory(payload);
  } catch (error) {
    if (error?.name === "AbortError") return;
    throw error;
  } finally {
    if (historyLoadController === controller) historyLoadController = null;
  }
}

function showHistoryDetailLoadError(error) {
  if (error?.name === "AbortError") return;
  if (historyDetailOutput) {
    historyDetailOutput.className = "history-detail-output empty-state";
    historyDetailOutput.textContent = error.message;
  }
}

function showHistoryLoadError(error) {
  if (error?.name === "AbortError") return;
  if (historyOutput) {
    historyOutput.className = "history-output empty-state";
    historyOutput.textContent = error.message;
  }
}

function observabilityTab(tab = state.observability.activeTab) {
  return state.observability.tabs[tab] || state.observability.tabs.live;
}

function updateLogBadges() {
  const tabs = state.observability.tabs;
  document.querySelectorAll("[data-log-badge]").forEach((badge) => {
    const tab = badge.dataset.logBadge || "";
    const value = ["critical", "error", "warning"].includes(tab)
      ? Number(tabs[tab]?.unread || 0)
      : Number(tabs[tab]?.items?.length || 0);
    badge.textContent = String(value);
    badge.hidden = value === 0;
  });
}

function updateLogAlert(unread = {}) {
  state.observability.unread = {
    critical: Number(unread.critical || 0),
    error: Number(unread.error || 0),
    warning: Number(unread.warning || 0),
    total: Number(unread.total || 0),
    highest: String(unread.highest || ""),
  };
  for (const severity of ["critical", "error", "warning"]) {
    state.observability.tabs[severity].unread = state.observability.unread[severity];
  }
  updateLogBadges();
  if (!logsButton || !state.isAdmin) {
    logsButton?.classList.remove("log-alert-critical", "log-alert-error", "log-alert-warning");
    return;
  }
  const severity = state.observability.unread.highest;
  logsButton.classList.toggle("log-alert-critical", severity === "critical");
  logsButton.classList.toggle("log-alert-error", severity === "error");
  logsButton.classList.toggle("log-alert-warning", severity === "warning");
  if (severity === "critical") {
    logsButton.title = "Nowy krytyczny blad w logach.";
  } else if (severity === "error") {
    logsButton.title = "Nowy blad w logach.";
  } else if (severity === "warning") {
    logsButton.title = "Nowe ostrzezenie w logach.";
  } else {
    logsButton.title = "";
  }
}

function logSeverityLabel(severity = "info") {
  if (severity === "critical") return "Krytyczny";
  if (severity === "error") return "Blad";
  if (severity === "warning") return "Ostrzezenie";
  return "Info";
}

function renderLogEvent(event) {
  const block = document.createElement("article");
  const meta = document.createElement("span");
  const severityBadge = document.createElement("span");
  const title = document.createElement("strong");
  const context = document.createElement("span");
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const disclosure = document.createElement("small");
  const lines = document.createElement("pre");
  const severity = event.severity || "info";
  block.className = `log-event log-event-compact log-event-${severity}`;
  block.dataset.observabilityId = event.id || "";
  meta.className = "log-event-meta log-event-time";
  meta.textContent = formatPanelTimestamp(event.created_at);
  severityBadge.className = `log-event-severity log-event-severity-${severity}`;
  severityBadge.textContent = logSeverityLabel(severity);
  title.textContent = event.summary || "Zdarzenie";
  title.title = title.textContent;
  summary.className = "log-event-summary-row";
  context.textContent = [
    event.username ? `uzytkownik: ${event.username}` : "",
    event.ean ? `EAN: ${event.ean}` : "",
    event.job_id ? `zadanie: ${event.job_id}` : "",
    event.module || "",
    event.stage || "",
  ]
    .filter(Boolean)
    .join(" | ");
  disclosure.textContent = "Szczegoly";
  lines.className = "log-lines";
  lines.textContent = [
    event.summary ? `Podsumowanie: ${event.summary}` : "",
    event.recommended_action ? `Zalecane dzialanie: ${event.recommended_action}` : "",
    event.exception_type ? `Wyjatek: ${event.exception_type}` : "",
    event.traceback_text || "",
    Object.keys(event.details || {}).length ? JSON.stringify(event.details, null, 2) : "",
  ]
    .filter(Boolean)
    .join("\n");
  if (!lines.textContent) lines.textContent = "Brak dodatkowych szczegolow.";
  summary.append(meta, severityBadge, title, context, disclosure);
  details.append(summary, lines);
  block.appendChild(details);
  return block;
}

function incidentValue(incident, key) {
  return incident[key] || incident.context?.[key] || "";
}

const DELIVERY_STATUS_LABELS = {
  pending: "Oczekuje",
  sending: "Oczekuje",
  sent: "Wysłano",
  fallback: "Fallback",
  skipped: "Pominięto",
  error: "Błąd",
};

function deliveryStatusLabel(status) {
  return DELIVERY_STATUS_LABELS[status] || "Błąd";
}

function deliveryChannelLabel(channel) {
  if (channel === "smtp") return "SMTP";
  if (channel === "entra") return "Microsoft Entra";
  return "brak kanału";
}

function renderIncidentDeliveries(incident) {
  const deliveries = Array.isArray(incident.deliveries) ? incident.deliveries : [];
  if (!deliveries.length) return null;
  const wrapper = document.createElement("div");
  const latest = deliveries[0];
  const badge = document.createElement("span");
  const details = document.createElement("details");
  const heading = document.createElement("summary");
  const list = document.createElement("div");
  wrapper.className = "log-delivery-summary";
  badge.className = `log-delivery-badge log-delivery-${latest.status || "error"}`;
  badge.textContent = `${deliveryStatusLabel(latest.status)} · ${deliveryChannelLabel(
    latest.used_channel
  )}`;
  details.className = "log-delivery-details";
  heading.textContent = `Powiadomienia e-mail (${deliveries.length})`;
  list.className = "log-delivery-list";
  for (const delivery of deliveries) {
    const item = document.createElement("section");
    const meta = document.createElement("strong");
    const recipients = document.createElement("span");
    const attempts = document.createElement("ul");
    item.className = "log-delivery-item";
    meta.textContent = [
      deliveryStatusLabel(delivery.status),
      deliveryChannelLabel(delivery.used_channel),
      formatPanelTimestamp(delivery.updated_at || delivery.created_at),
    ]
      .filter(Boolean)
      .join(" | ");
    recipients.textContent = `Liczba odbiorców: ${Number(delivery.recipient_count || 0)}`;
    attempts.className = "log-delivery-attempts";
    for (const attempt of delivery.attempts || []) {
      const row = document.createElement("li");
      row.textContent = [
        deliveryChannelLabel(attempt.channel),
        attempt.status === "sent" ? "Wysłano" : "Błąd",
        Number.isInteger(attempt.status_code) ? `kod ${attempt.status_code}` : "",
        Number.isInteger(attempt.elapsed_ms) ? `${attempt.elapsed_ms} ms` : "",
        attempt.code || "",
        attempt.message || "",
      ]
        .filter(Boolean)
        .join(" | ");
      attempts.appendChild(row);
    }
    item.append(meta, recipients);
    if (attempts.childElementCount) item.appendChild(attempts);
    list.appendChild(item);
  }
  details.append(heading, list);
  wrapper.append(badge, details);
  return wrapper;
}

function renderIncidentContext(incident, key, label) {
  const details = document.createElement("details");
  const heading = document.createElement("summary");
  const output = document.createElement("div");
  const items = Array.isArray(incident[key]) ? incident[key] : [];
  details.className = `log-incident-context log-incident-context-${key}`;
  heading.textContent = `${label} (${items.length})`;
  output.className = "log-context-events";
  if (!items.length) {
    const empty = document.createElement("span");
    empty.textContent = "Brak zdarzen.";
    output.appendChild(empty);
  } else {
    for (const item of items) output.appendChild(renderLogEvent(item));
  }
  details.append(heading, output);
  return details;
}

function renderLazyIncidentContext(incident) {
  const details = document.createElement("details");
  const heading = document.createElement("summary");
  const output = document.createElement("div");
  let loading = false;
  let loaded = false;
  let problemNextCursor = "";
  const context = { before: [], problem: [], after: [] };
  details.className = "log-incident-context-lazy";
  heading.textContent = "Kontekst zdarzenia";
  output.className = "log-incident-context-content";
  output.textContent = "Rozwin, aby wczytac kontekst.";

  const paint = () => {
    output.textContent = "";
    output.append(
      renderIncidentContext(context, "before", "Przed"),
      renderIncidentContext(context, "problem", "Problem"),
      renderIncidentContext(context, "after", "Po")
    );
    if (problemNextCursor) {
      const loadMore = document.createElement("button");
      loadMore.type = "button";
      loadMore.className = "secondary-button";
      loadMore.textContent = "Wczytaj wiecej";
      loadMore.disabled = loading;
      loadMore.addEventListener("click", (event) => {
        event.preventDefault();
        loadPage(problemNextCursor).catch(showLogsError);
      });
      output.appendChild(loadMore);
    }
  };
  const loadPage = async (cursor = "") => {
    if (loading || !incident.id) return;
    loading = true;
    const params = new URLSearchParams({ limit: String(OBSERVABILITY_PAGE_SIZE) });
    if (cursor) params.set("cursor", cursor);
    try {
      const payload = await requestObservabilityPayload(
        `/api/observability/incidents/${encodeURIComponent(incident.id)}/context?${params}`
      );
      if (!cursor) {
        context.before = Array.isArray(payload.before) ? payload.before : [];
        context.after = Array.isArray(payload.after) ? payload.after : [];
      }
      const known = new Set(context.problem.map((item) => item.id));
      for (const item of Array.isArray(payload.problem) ? payload.problem : []) {
        if (item?.id && !known.has(item.id)) {
          known.add(item.id);
          context.problem.push(item);
        }
      }
      context.problem.sort((left, right) =>
        `${left.created_at || ""}\u0000${left.id || ""}`.localeCompare(
          `${right.created_at || ""}\u0000${right.id || ""}`
        )
      );
      problemNextCursor = String(payload.problem_next_cursor || "");
      loaded = true;
      paint();
    } catch (error) {
      output.textContent = error?.message || "Nie mozna wczytac kontekstu.";
      throw error;
    } finally {
      loading = false;
    }
  };
  details.addEventListener("toggle", () => {
    if (details.open && !loaded && !loading) loadPage().catch(() => {});
  });
  details.append(heading, output);
  return details;
}

function openHistoryForEan(ean) {
  if (!ean || !historySearchInput) return;
  closeModals();
  historySearchInput.value = ean;
  state.historyPage = 1;
  openModal("history");
}

function renderIncidentCard(incident) {
  const card = document.createElement("article");
  const meta = document.createElement("div");
  const title = document.createElement("strong");
  const action = document.createElement("p");
  const context = document.createElement("span");
  const links = document.createElement("div");
  const severity = incident.severity || "warning";
  const ean = incidentValue(incident, "ean");
  const jobId = incident.job_id || incidentValue(incident, "job_id");
  card.id = incident.id || "";
  card.dataset.observabilityId = incident.id || "";
  card.tabIndex = -1;
  card.className = `log-incident log-event-${severity}`;
  meta.className = "log-event-meta";
  meta.textContent = [
    formatPanelTimestamp(incident.last_seen_at || incident.first_seen_at),
    logSeverityLabel(severity),
    `wystapienia: ${Number(incident.occurrence_count || 1)}`,
  ]
    .filter(Boolean)
    .join(" | ");
  title.textContent = incidentValue(incident, "summary") || incident.event_type || "Incydent";
  action.className = "log-recommended-action";
  action.textContent = incidentValue(incident, "recommended_action")
    ? `Zalecane dzialanie: ${incidentValue(incident, "recommended_action")}`
    : "Brak zalecanego dzialania.";
  context.textContent = [
    incidentValue(incident, "username") ? `uzytkownik: ${incidentValue(incident, "username")}` : "",
    ean ? `EAN: ${ean}` : "",
    jobId ? `zadanie: ${jobId}` : "",
    incidentValue(incident, "module") ? `modul: ${incidentValue(incident, "module")}` : "",
  ]
    .filter(Boolean)
    .join(" | ");
  links.className = "log-card-links";
  if (ean) {
    const historyLink = document.createElement("button");
    historyLink.type = "button";
    historyLink.className = "ghost-button";
    historyLink.textContent = "Historia EAN";
    historyLink.addEventListener("click", () => openHistoryForEan(ean));
    links.appendChild(historyLink);
  }
  if (jobId) {
    const jobLink = document.createElement("button");
    jobLink.type = "button";
    jobLink.className = "ghost-button";
    jobLink.textContent = "Pokaz zadanie";
    jobLink.addEventListener("click", () => {
      openObservabilityRecord("jobs", jobId).catch(showLogsError);
    });
    links.appendChild(jobLink);
  }
  card.append(meta, title, action);
  if (context.textContent) card.appendChild(context);
  if (links.childElementCount) card.appendChild(links);
  const deliveryStatus = renderIncidentDeliveries(incident);
  if (deliveryStatus) card.appendChild(deliveryStatus);
  card.appendChild(renderLazyIncidentContext(incident));
  return card;
}

function renderJobCard(job) {
  const card = document.createElement("article");
  const meta = document.createElement("div");
  const title = document.createElement("strong");
  const context = document.createElement("span");
  const stages = document.createElement("ol");
  const links = document.createElement("div");
  const jobId = job.id || job.job_id || "";
  const ean = job.ean || job.entry?.ean || job.details?.ean || "";
  const incidentId = job.incident_id || job.details?.incident_id || "";
  card.className = `log-job log-job-${job.status || "unknown"}`;
  card.dataset.observabilityId = jobId;
  card.tabIndex = -1;
  meta.className = "log-event-meta";
  meta.textContent = [
    formatPanelTimestamp(job.started_at),
    job.finished_at ? formatPanelTimestamp(job.finished_at) : "",
    job.status || "",
  ]
    .filter(Boolean)
    .join(" | ");
  title.textContent = job.summary || jobId || "Zadanie";
  context.textContent = [
    job.username ? `uzytkownik: ${job.username}` : "",
    ean ? `EAN: ${ean}` : "",
    jobId ? `ID: ${jobId}` : "",
  ]
    .filter(Boolean)
    .join(" | ");
  stages.className = "log-job-stages";
  for (const stage of job.stages || []) {
    const item = document.createElement("li");
    item.textContent = [stage.name || stage.key || "Etap", stage.status || "", stage.error || ""]
      .filter(Boolean)
      .join(" | ");
    stages.appendChild(item);
  }
  links.className = "log-card-links";
  if (incidentId) {
    const incidentLink = document.createElement("button");
    incidentLink.type = "button";
    incidentLink.className = "ghost-button";
    incidentLink.textContent = "Pokaz incydent";
    incidentLink.addEventListener("click", () => {
      openObservabilityRecord("incidents", incidentId).catch(showLogsError);
    });
    links.appendChild(incidentLink);
  }
  if (ean) {
    const historyLink = document.createElement("button");
    historyLink.type = "button";
    historyLink.className = "ghost-button";
    historyLink.textContent = "Historia EAN";
    historyLink.addEventListener("click", () => openHistoryForEan(ean));
    links.appendChild(historyLink);
  }
  card.append(meta, title);
  if (context.textContent) card.appendChild(context);
  if (stages.childElementCount) card.appendChild(stages);
  if (links.childElementCount) card.appendChild(links);
  return card;
}

function normalizeLogSearchText(value) {
  return String(value || "").toLowerCase();
}

function logFilterInputValues() {
  return {
    query: normalizeLogSearchText(logsTextFilter?.value).trim(),
    severity: logsSeverityFilter?.value || "",
    module: normalizeLogSearchText(logsModuleFilter?.value).trim(),
    username: normalizeLogSearchText(logsUserFilter?.value).trim(),
    ean: normalizeLogSearchText(logsEanFilter?.value).trim(),
    jobId: normalizeLogSearchText(logsJobFilter?.value).trim(),
  };
}

function resetLiveArchiveForFilters() {
  const live = observabilityTab("live");
  stopObservabilityStream();
  state.observability.seedGeneration = Number(state.observability.seedGeneration || 0) + 1;
  state.observability.streamSeeded = false;
  state.observability.streamAfterId = "";
  state.observability.seedLoading = false;
  state.observability.buffer = [];
  live.requestId = Number(live.requestId || 0) + 1;
  live.loading = false;
  live.items = [];
  live.nextCursor = "";
  live.archiveSince = "";
}

function commitLogFilters(filters = logFilterInputValues()) {
  const normalized = { ...filters };
  const changed = JSON.stringify(normalized) !== JSON.stringify(
    state.observability.committedFilters
  );
  state.observability.committedFilters = normalized;
  if (changed) resetLiveArchiveForFilters();
  return changed;
}

function resetCommittedLogFilters() {
  for (const control of [
    logsTextFilter,
    logsSeverityFilter,
    logsModuleFilter,
    logsUserFilter,
    logsEanFilter,
    logsJobFilter,
  ]) {
    if (control) control.value = "";
  }
  return commitLogFilters({
    query: "",
    severity: "",
    module: "",
    username: "",
    ean: "",
    jobId: "",
  });
}

function logEventSearchText(item) {
  return normalizeLogSearchText([
    item.created_at,
    item.id,
    item.severity,
    item.event_type,
    item.module,
    item.stage,
    item.username,
    item.ean,
    item.product_id,
    item.slot,
    item.job_id,
    item.correlation_id,
    item.incident_id,
    item.summary,
    item.recommended_action,
    JSON.stringify(item.details || {}),
    item.exception_type,
    item.traceback_text,
  ]
    .map((value) => String(value || ""))
    .join("\n"));
}

function logItemMatchesFilters(item) {
  const filters = state.observability.committedFilters;
  const { query, severity, username, ean, jobId } = filters;
  const moduleName = filters.module;
  const context = item.context || {};
  const searchText = item.created_at
    ? logEventSearchText(item)
    : normalizeLogSearchText(JSON.stringify(item));
  if (query && !searchText.includes(query)) return false;
  if (severity && (item.severity || "") !== severity) return false;
  if (moduleName && !normalizeLogSearchText(item.module || context.module).includes(moduleName)) return false;
  if (username && !normalizeLogSearchText(item.username || context.username).includes(username)) return false;
  if (ean && !normalizeLogSearchText(item.ean || context.ean || item.entry?.ean).includes(ean)) return false;
  if (jobId && !normalizeLogSearchText(item.job_id || item.id || context.job_id).includes(jobId)) return false;
  return true;
}

function renderLogs() {
  logsOutput.textContent = "";
  const tabName = state.observability.activeTab;
  const items = observabilityTab(tabName).items.filter(logItemMatchesFilters);
  if (!items.length) {
    logsOutput.className = "logs-output empty-state";
    logsOutput.textContent = "Brak zdarzen dla wybranych filtrow.";
  } else {
    logsOutput.className = `logs-output logs-output-${tabName}`;
    for (const item of items) {
      if (tabName === "live") logsOutput.appendChild(renderLogEvent(item));
      else if (tabName === "jobs") logsOutput.appendChild(renderJobCard(item));
      else logsOutput.appendChild(renderIncidentCard(item));
    }
  }
  const tab = observabilityTab(tabName);
  logsLoadMoreButton.textContent = "Wczytaj wiecej";
  logsLoadMoreButton.hidden = !tab.nextCursor;
  logsLoadMoreButton.disabled = Boolean(tab.loading);
  updateLogBadges();
  if (tabName === "live" && state.observability.autoscroll) {
    logsOutput.scrollTop = logsOutput.scrollHeight;
  }
}

function applyObservabilityUnread(unread = {}, requestId = 0) {
  if (requestId !== state.observability.unreadRequestId) return false;
  updateLogAlert(unread);
  return true;
}

async function requestObservabilityPayload(path, options = {}) {
  const requestId = Number(state.observability.unreadRequestId || 0) + 1;
  state.observability.unreadRequestId = requestId;
  const payload = await requestJson(path, options);
  applyObservabilityUnread(payload.unread || {}, requestId);
  return payload;
}

const HEALTH_COMPONENT_LABELS = [
  ["backend", "Backend"],
  ["sqlite", "SQLite"],
  ["job_processor", "Proces zadan"],
  ["notification_worker", "Powiadomienia"],
  ["ftp", "FTP"],
  ["sql", "SQL"],
  ["sql_profiles", "Profile SQL"],
  ["pimcore", "Pimcore"],
];

const HEALTH_STATUS_LABELS = {
  online: "Online",
  degraded: "Ograniczony",
  critical: "Krytyczny",
  disabled: "Wylaczony",
  unknown: "Brak danych",
};

function normalizedHealthStatus(value) {
  const status = String(value || "unknown").toLowerCase();
  return Object.hasOwn(HEALTH_STATUS_LABELS, status) ? status : "unknown";
}

function normalizedHealthComponents(components = {}) {
  return Object.fromEntries(
    HEALTH_COMPONENT_LABELS.map(([key]) => [
      key,
      {
        status: normalizedHealthStatus(components[key]?.status),
        observed_at: String(components[key]?.observed_at || ""),
      },
    ])
  );
}

function canonicalHealthTimestamp(value) {
  const text = String(value || "");
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(text) ? text : "";
}

function renderBackendHealthDetails(
  components = {},
  { serverTime = "", currentLatencyMs = 0, medianLatencyMs = 0 } = {}
) {
  if (!backendHealthDetailsList) return;
  const rows = HEALTH_COMPONENT_LABELS.map(([key, label]) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const status = document.createElement("strong");
    const normalized = normalizedHealthStatus(components[key]?.status);
    name.textContent = label;
    const observedAt = canonicalHealthTimestamp(components[key]?.observed_at);
    status.textContent = observedAt
      ? `${HEALTH_STATUS_LABELS[normalized]} · ${formatPanelTimestamp(observedAt)}`
      : HEALTH_STATUS_LABELS[normalized];
    item.dataset.level = normalized;
    item.append(name, status);
    return item;
  });
  const metrics = [
    ["Biezace opoznienie", `${Math.round(currentLatencyMs)} ms`],
    ["Mediana opoznienia", `${Math.round(medianLatencyMs)} ms`],
    ["Czas serwera", formatPanelTimestamp(serverTime)],
  ].map(([label, value]) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const status = document.createElement("strong");
    name.textContent = label;
    status.textContent = value;
    item.append(name, status);
    return item;
  });
  backendHealthDetailsList.replaceChildren(...rows, ...metrics);
}

function medianHealthLatency() {
  const recentSamples = healthSamples.slice(-5).sort((left, right) => left - right);
  if (!recentSamples.length) return 0;
  const middle = Math.floor(recentSamples.length / 2);
  if (recentSamples.length % 2) return recentSamples[middle];
  return (recentSamples[middle - 1] + recentSamples[middle]) / 2;
}

function updateBackendHealthStatus(
  level,
  currentLatencyMs = 0,
  components = {},
  { medianLatencyMs = currentLatencyMs, serverTime = "" } = {}
) {
  if (!backendHealthStatus || !backendHealthText) return;
  const labels = {
    online: "Online",
    slow: "Wolno",
    critical: "Krytyczny",
    offline: "Offline",
  };
  const safeLevel = Object.hasOwn(labels, level) ? level : "critical";
  backendHealthStatus.dataset.level = safeLevel;
  backendHealthText.textContent =
    safeLevel === "offline"
      ? labels[safeLevel]
      : `${labels[safeLevel]} · ${Math.round(currentLatencyMs)} ms`;
  renderBackendHealthDetails(components, { serverTime, currentLatencyMs, medianLatencyMs });
}

function rerenderCachedHealthDetails() {
  if (!state.lastHealthPayload) return;
  const health = state.lastHealthPayload;
  renderBackendHealthDetails(health.components, {
    currentLatencyMs: health.elapsedMs,
    medianLatencyMs: health.medianMs,
    serverTime: health.serverTime,
  });
}

function resourceUnavailableText(value, parent = {}) {
  for (const candidate of [value, parent]) {
    if (!candidate || typeof candidate !== "object" || candidate.available !== false) continue;
    const reason = String(candidate.reason || "").trim();
    return reason ? `brak danych (${reason})` : "brak danych";
  }
  return "brak danych";
}

function formatResourceDetail(value, formatter, parent = {}) {
  const number = resourceNumber(value);
  return number === null ? resourceUnavailableText(value, parent) : formatter(number);
}

function renderResourceDetails(resources = {}) {
  if (!resourceDetailsList) return;
  const host = resources.host || {};
  const backend = resources.backend || {};
  const detector = resources.detector || {};
  const monitorSettings = state.settings?.resource_monitor || {};
  const latched = Array.isArray(detector.latched_metrics) ? detector.latched_metrics : [];
  const pending = Array.isArray(detector.pending_metrics) ? detector.pending_metrics : [];
  const ioDetail = (value) => `${value} B/s (${formatMib(value)}/s)`;
  const rows = [
    ["System CPU", formatResourceDetail(host.cpu_percent, (value) => `${value}%`, host)],
    ["System RAM", formatResourceDetail(host.memory_percent, (value) => `${value}%`, host)],
    ["System RAM uzyty", formatResourceDetail(host.memory_used_bytes, formatResourceBytes, host)],
    ["System RAM lacznie", formatResourceDetail(host.memory_total_bytes, formatResourceBytes, host)],
    ["System dysk zajety", formatResourceDetail(host.disk_busy_percent, (value) => `${value}%`, host)],
    ["Backend CPU", formatResourceDetail(backend.cpu_percent, (value) => `${value}%`, backend)],
    ["Backend RAM", formatResourceDetail(backend.memory_percent, (value) => `${value}%`, backend)],
    ["Backend working set", formatResourceDetail(backend.memory_working_set_bytes, formatResourceBytes, backend)],
    ["Backend private bytes", formatResourceDetail(backend.memory_private_bytes, formatResourceBytes, backend)],
    ["Backend odczyt dysku", formatResourceDetail(backend.disk_read_bytes_per_second, ioDetail, backend)],
    ["Backend zapis dysku", formatResourceDetail(backend.disk_write_bytes_per_second, ioDetail, backend)],
    ["Backend I/O", formatResourceDetail(backend.disk_io_bytes_per_second, ioDetail, backend)],
    [
      "Proces OCR",
      backend.ocr_worker_registered
        ? `PID ${backend.ocr_worker_pid || "brak"} — lokalny worker OCR`
        : "niepotwierdzony",
    ],
    ["Aktywne zadania", formatResourceDetail(backend.active_jobs, String, backend)],
    ["Zadania w kolejce", formatResourceDetail(backend.queued_jobs, String, backend)],
    ["Aktywni w ostatnich 3 min", formatResourceDetail(backend.active_clients, String, backend)],
    ["Prog CPU backendu", formatPercent(monitorSettings.cpu_percent_threshold)],
    ["Prog RAM backendu", formatPercent(monitorSettings.memory_percent_threshold)],
    [
      "Prog I/O backendu",
      resourceNumber(monitorSettings.io_mib_per_second_threshold) === null
        ? "brak danych"
        : `${monitorSettings.io_mib_per_second_threshold} MB/s`,
    ],
    ["Alarm aktywny (2 probki)", latched.length ? latched.join(", ") : "nie"],
    ["Alarm oczekujacy (1. probka)", pending.length ? pending.join(", ") : "nie"],
    ["Ostatni alarm", formatPanelTimestamp(detector.last_trigger_at)],
    ["Probka", formatPanelTimestamp(resources.observed_at)],
  ].map(([label, value]) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const detail = document.createElement("strong");
    name.textContent = label;
    detail.textContent = value;
    item.append(name, detail);
    return item;
  });
  resourceDetailsList.replaceChildren(...rows);
}

function renderResourceStatus(resources = {}) {
  if (!resourceStatus || !resourceStatusText) return;
  state.resources = resources && typeof resources === "object" ? resources : {};
  const host = state.resources.host || {};
  resourceStatus.hidden = state.settings?.resource_monitor?.show_status === false;
  resourceStatusText.textContent =
    `System: ${formatPercent(host.cpu_percent)}/${formatPercent(host.memory_percent)}/${formatPercent(host.disk_busy_percent)}`;
  resourceStatus.dataset.level = resourceLevel(state.resources.detector || {});
  renderResourceDetails(state.resources);
}

function healthLevel(ms, components = {}, payloadOk = true) {
  if (
    payloadOk === false ||
    components.backend?.status !== "online" ||
    components.sqlite?.status === "critical" ||
    components.job_processor?.status === "critical" ||
    components.notification_worker?.status === "critical"
  ) {
    return "critical";
  }
  if (ms > HEALTH_CRITICAL_MS) return "critical";
  if (ms >= HEALTH_SLOW_MS || Object.values(components).some((item) => item.status === "degraded")) {
    return "slow";
  }
  return "online";
}

async function pollBackendHealth() {
  if (document.hidden) return;
  const requestGeneration = ++healthPollGeneration;
  healthPollController?.abort();
  const controller = new AbortController();
  healthPollController = controller;
  const startedAt = performance.now();
  try {
    const payload = await requestJson("/api/health", { signal: controller.signal });
    const elapsedMs = Math.max(0, performance.now() - startedAt);
    if (
      requestGeneration !== healthPollGeneration ||
      controller.signal.aborted ||
      document.hidden
    ) {
      return;
    }
    const components = normalizedHealthComponents(payload.components || {});
    renderResourceStatus(payload.resources || {});
    lastSuccessfulHealthComponents = components;
    healthFailures = 0;
    healthSamples.push(elapsedMs);
    if (healthSamples.length > 5) healthSamples.shift();
    const medianMs = medianHealthLatency();
    state.lastHealthPayload = {
      components,
      elapsedMs,
      medianMs,
      ok: payload.ok,
      serverTime: payload.time,
    };
    updateBackendHealthStatus(
      healthLevel(medianMs, components, payload.ok),
      elapsedMs,
      components,
      { medianLatencyMs: medianMs, serverTime: payload.time }
    );
  } catch (error) {
    if (
      error?.name === "AbortError" ||
      controller.signal.aborted ||
      requestGeneration !== healthPollGeneration ||
      document.hidden
    ) {
      return;
    }
    healthFailures += 1;
    if (healthFailures >= HEALTH_OFFLINE_FAILURES) {
      updateBackendHealthStatus("offline", 0, lastSuccessfulHealthComponents);
    }
  } finally {
    if (requestGeneration === healthPollGeneration) {
      if (healthPollController === controller) healthPollController = null;
    }
  }
}

function updateRuntimeHealthSummary(payload = {}, elapsedMs = 0) {
  const health = payload.health || {};
  const status = String(health.status || "unknown");
  const components = lastSuccessfulHealthComponents;
  healthFailures = 0;
  healthSamples.push(elapsedMs);
  if (healthSamples.length > 5) healthSamples.shift();
  const medianMs = medianHealthLatency();
  let level = "critical";
  if (health.ok && status === "online") {
    level = healthLevel(medianMs, components, true);
  } else if (health.ok && status === "degraded") {
    level = "slow";
  }
  state.lastHealthPayload = {
    components,
    elapsedMs,
    medianMs,
    ok: Boolean(health.ok),
    serverTime: payload.observed_at || "",
  };
  updateBackendHealthStatus(level, elapsedMs, components, {
    medianLatencyMs: medianMs,
    serverTime: payload.observed_at || "",
  });
}

async function fetchRuntimeStatus() {
  const startedAt = performance.now();
  try {
    const payload = await requestJson("/api/runtime-status");
    updateRuntimeHealthSummary(payload, Math.max(0, performance.now() - startedAt));
    return payload;
  } catch (error) {
    healthFailures += 1;
    if (healthFailures >= HEALTH_OFFLINE_FAILURES) {
      updateBackendHealthStatus("offline", 0, lastSuccessfulHealthComponents);
    }
    throw error;
  }
}

function setBackendHealthDetailsExpanded(expanded, { pinned = healthDetailsPinned } = {}) {
  healthDetailsPinned = pinned;
  backendHealthIndicator?.classList.toggle("details-open", expanded);
  if (backendHealthDetails) backendHealthDetails.hidden = !expanded;
  backendHealthStatus?.setAttribute("aria-expanded", expanded ? "true" : "false");
}

function refreshBackendHealthDetailsExpanded() {
  const expanded = Boolean(
    healthDetailsPinned ||
      healthDetailsPointerInside ||
      backendHealthIndicator?.contains(document.activeElement)
  );
  setBackendHealthDetailsExpanded(expanded);
}

backendHealthIndicator?.addEventListener("pointerenter", () => {
  healthDetailsPointerInside = true;
  setBackendHealthDetailsExpanded(true);
});

backendHealthIndicator?.addEventListener("pointerleave", () => {
  healthDetailsPointerInside = false;
  refreshBackendHealthDetailsExpanded();
});

backendHealthIndicator?.addEventListener("focusin", () => {
  setBackendHealthDetailsExpanded(true);
});

backendHealthIndicator?.addEventListener("focusout", () => {
  window.setTimeout(refreshBackendHealthDetailsExpanded, 0);
});

backendHealthStatus?.addEventListener("click", (event) => {
  event.stopPropagation();
  const pinned = !healthDetailsPinned;
  setBackendHealthDetailsExpanded(
    Boolean(
      pinned ||
        healthDetailsPointerInside ||
        backendHealthIndicator?.contains(document.activeElement)
    ),
    { pinned }
  );
});

backendHealthStatus?.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  setBackendHealthDetailsExpanded(false, { pinned: false });
  backendHealthStatus.focus();
});

function setResourceDetailsExpanded(expanded, { pinned = resourceDetailsPinned } = {}) {
  resourceDetailsPinned = pinned;
  resourceStatusIndicator?.classList.toggle("details-open", expanded);
  if (resourceDetails) resourceDetails.hidden = !expanded;
  resourceStatus?.setAttribute("aria-expanded", expanded ? "true" : "false");
}

function refreshResourceDetailsExpanded() {
  const expanded = Boolean(
    resourceDetailsPinned ||
      resourceDetailsPointerInside ||
      resourceStatusIndicator?.contains(document.activeElement)
  );
  setResourceDetailsExpanded(expanded);
}

resourceStatusIndicator?.addEventListener("pointerenter", () => {
  resourceDetailsPointerInside = true;
  setResourceDetailsExpanded(true);
});

resourceStatusIndicator?.addEventListener("pointerleave", () => {
  resourceDetailsPointerInside = false;
  refreshResourceDetailsExpanded();
});

resourceStatusIndicator?.addEventListener("focusin", () => {
  setResourceDetailsExpanded(true);
});

resourceStatusIndicator?.addEventListener("focusout", () => {
  window.setTimeout(refreshResourceDetailsExpanded, 0);
});

resourceStatus?.addEventListener("click", (event) => {
  event.stopPropagation();
  const pinned = !resourceDetailsPinned;
  setResourceDetailsExpanded(
    Boolean(
      pinned ||
        resourceDetailsPointerInside ||
        resourceStatusIndicator?.contains(document.activeElement)
    ),
    { pinned }
  );
});

resourceStatus?.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  setResourceDetailsExpanded(false, { pinned: false });
  resourceStatus.focus();
});

document.addEventListener("click", (event) => {
  if (!backendHealthIndicator?.contains(event.target)) {
    setBackendHealthDetailsExpanded(false, { pinned: false });
  }
  if (!resourceStatusIndicator?.contains(event.target)) {
    setResourceDetailsExpanded(false, { pinned: false });
  }
});

function showLogsError(error) {
  if (!logsOutput) return;
  logsOutput.className = "logs-output empty-state";
  logsOutput.textContent = error.message || String(error);
}

function waitForLogsPaint() {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(resolve);
    });
  });
}

async function markSeverityRead(severity, requestId) {
  const tab = observabilityTab(severity);
  if (!tab.items.length || !tab.unread || tab.readInFlight) return;
  tab.readInFlight = true;
  try {
    await waitForLogsPaint();
    if (
      !logsView?.classList.contains("active") ||
      state.observability.activeTab !== severity ||
      tab.requestId !== requestId
    ) {
      return;
    }
    const card = logsOutput.querySelector(".log-incident[data-observability-id]");
    if (!card || card.hidden || !card.isConnected || !card.getClientRects().length) return;
    const incident = tab.items.find((item) => item.id === card.dataset.observabilityId);
    const eventId = incident?.latest_event_id || incident?.first_event_id || "";
    const createdAt = incident?.last_seen_at || incident?.first_seen_at || "";
    if (!eventId || !createdAt) return;
    await requestObservabilityPayload("/api/observability/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ severity, event_id: eventId, created_at: createdAt }),
    });
  } finally {
    tab.readInFlight = false;
  }
}

function mergeLiveItems(items = [], since = "", keepOldest = false) {
  const byId = new Map();
  for (const item of items) {
    if (!item?.id || (since && String(item.created_at || "") < since)) continue;
    byId.set(item.id, item);
  }
  const ordered = [...byId.values()]
    .sort((left, right) =>
      `${left.created_at || ""}\u0000${left.id}`.localeCompare(
        `${right.created_at || ""}\u0000${right.id}`
      )
    );
  return keepOldest
    ? ordered.slice(0, MAX_LIVE_LOG_EVENTS)
    : ordered.slice(-MAX_LIVE_LOG_EVENTS);
}

function appendPausedObservabilityEvents(items = []) {
  const live = observabilityTab("live");
  const knownIds = new Set(
    [...live.items, ...state.observability.buffer].map((item) => item.id)
  );
  for (const item of items) {
    if (
      item?.id &&
      (!live.archiveSince || String(item.created_at || "") >= live.archiveSince) &&
      !knownIds.has(item.id)
    ) {
      knownIds.add(item.id);
      state.observability.buffer.push(item);
    }
  }
  if (state.observability.buffer.length > MAX_LIVE_LOG_EVENTS) {
    state.observability.buffer.splice(
      0,
      state.observability.buffer.length - MAX_LIVE_LOG_EVENTS
    );
  }
}

async function seedLiveLogs({ force = false } = {}) {
  const live = observabilityTab("live");
  if (state.observability.streamSeeded && !force) {
    renderLogs();
    return;
  }
  if (state.observability.seedLoading && !force) return;
  const seedGeneration = Number(state.observability.seedGeneration || 0) + 1;
  state.observability.seedGeneration = seedGeneration;
  state.observability.seedLoading = true;
  stopObservabilityStream();
  if (state.observability.paused && logsStreamStatus) {
    logsStreamStatus.textContent = "Wstrzymano";
  }
  try {
    const params = new URLSearchParams({ live_seed: "1" });
    const filters = state.observability.committedFilters;
    if (filters.query) params.set("query", filters.query);
    if (filters.severity) params.set("severity", filters.severity);
    if (filters.module) params.set("module", filters.module);
    if (filters.username) params.set("username", filters.username);
    if (filters.ean) params.set("ean", filters.ean);
    if (filters.jobId) params.set("job_id", filters.jobId);
    const payload = await requestObservabilityPayload(
      "/api/observability/events?" + params.toString()
    );
    if (state.observability.seedGeneration !== seedGeneration) return;
    const seedItems = mergeLiveItems(Array.isArray(payload.items) ? payload.items : []);
    const streamAfterId = String(payload.stream_after_id || "");
    if (!streamAfterId) {
      throw new Error("Serwer nie zwrocil punktu wznowienia strumienia.");
    }
    if (state.observability.paused) {
      appendPausedObservabilityEvents(seedItems);
    } else {
      live.items = seedItems;
      if (state.observability.activeTab === "live") renderLogs();
    }
    live.nextCursor = String(payload.next_cursor || "");
    live.archiveSince = String(payload.archive_since || "");
    state.observability.streamAfterId = streamAfterId;
    state.observability.streamSeeded = true;
    startObservabilityStream(streamAfterId);
  } catch (error) {
    if (state.observability.seedGeneration !== seedGeneration) return;
    if (state.observability.streamAfterId) {
      startObservabilityStream(state.observability.streamAfterId);
    } else if (logsStreamStatus) {
      logsStreamStatus.textContent = "Rozlaczono";
    }
    throw error;
  } finally {
    if (state.observability.seedGeneration === seedGeneration) {
      state.observability.seedLoading = false;
    }
  }
}

function liveArchiveEndpoint(cursor = "") {
  const live = observabilityTab("live");
  const filters = state.observability.committedFilters;
  const params = new URLSearchParams({ limit: String(OBSERVABILITY_PAGE_SIZE) });
  if (cursor) params.set("cursor", cursor);
  if (live.archiveSince) params.set("since", live.archiveSince);
  if (filters.query) params.set("query", filters.query);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.module) params.set("module", filters.module);
  if (filters.username) params.set("username", filters.username);
  if (filters.ean) params.set("ean", filters.ean);
  if (filters.jobId) params.set("job_id", filters.jobId);
  return "/api/observability/events?" + params.toString();
}

async function loadOlderLiveLogs() {
  const live = observabilityTab("live");
  if (live.loading || !live.nextCursor || !live.archiveSince) return;
  const cursor = live.nextCursor;
  const requestId = Number(live.requestId || 0) + 1;
  const seedGeneration = Number(state.observability.seedGeneration || 0);
  live.requestId = requestId;
  live.loading = true;
  renderLogs();
  try {
    const payload = await requestObservabilityPayload(liveArchiveEndpoint(cursor));
    if (
      live.requestId !== requestId ||
      state.observability.seedGeneration !== seedGeneration
    ) return;
    const older = Array.isArray(payload.items) ? payload.items : [];
    live.items = mergeLiveItems([...older, ...live.items], live.archiveSince, true);
    live.nextCursor = String(payload.next_cursor || "");
  } finally {
    if (live.requestId === requestId) {
      live.loading = false;
      if (state.observability.activeTab === "live") renderLogs();
    }
  }
}

function appendLiveEvent(event) {
  const live = observabilityTab("live");
  if (
    !event?.id ||
    (live.archiveSince && String(event.created_at || "") < live.archiveSince) ||
    live.items.some((item) => item.id === event.id)
  ) return;
  live.items.push(event);
  live.items.sort((left, right) =>
    `${left.created_at || ""}\u0000${left.id || ""}`.localeCompare(
      `${right.created_at || ""}\u0000${right.id || ""}`
    )
  );
  let removed = [];
  if (live.items.length > MAX_LIVE_LOG_EVENTS) {
    removed = live.items.splice(0, live.items.length - MAX_LIVE_LOG_EVENTS);
  }
  if (state.observability.activeTab !== "live") {
    updateLogBadges();
    return;
  }
  if (!live.items.some((item) => item.id === event.id)) {
    updateLogBadges();
    return;
  }
  for (const item of removed) {
    if (logItemMatchesFilters(item)) logsOutput.firstElementChild?.remove();
  }
  if (!logItemMatchesFilters(event)) {
    updateLogBadges();
    if (!logsOutput.childElementCount) {
      logsOutput.className = "logs-output empty-state";
      logsOutput.textContent = "Brak zdarzen dla wybranych filtrow.";
    }
    return;
  }
  if (logsOutput.classList.contains("empty-state")) {
    logsOutput.textContent = "";
    logsOutput.className = "logs-output logs-output-live";
  }
  const eventIndex = live.items.findIndex((item) => item.id === event.id);
  const nextVisible = live.items
    .slice(eventIndex + 1)
    .find((item) => logItemMatchesFilters(item));
  const nextNode = nextVisible
    ? [...logsOutput.children].find(
        (node) => node.dataset.observabilityId === nextVisible.id
      )
    : null;
  if (nextNode) {
    logsOutput.insertBefore(renderLogEvent(event), nextNode);
  } else {
    logsOutput.appendChild(renderLogEvent(event));
  }
  while (logsOutput.childElementCount > MAX_LIVE_LOG_EVENTS) {
    logsOutput.firstElementChild?.remove();
  }
  updateLogBadges();
  if (state.observability.autoscroll) {
    logsOutput.scrollTop = logsOutput.scrollHeight;
  }
}

function handleObservabilityEvent(event) {
  let item;
  try {
    item = JSON.parse(event.data);
  } catch (_error) {
    return;
  }
  if (!item || typeof item !== "object") return;
  state.observability.streamAfterId =
    item.id || event.lastEventId || state.observability.streamAfterId;
  if (state.observability.paused) {
    appendPausedObservabilityEvents([item]);
    if (logsStreamStatus) {
      logsStreamStatus.textContent = `Wstrzymano (${state.observability.buffer.length} oczekuje)`;
    }
    return;
  }
  appendLiveEvent(item);
}

function startObservabilityStream(afterId = state.observability.streamAfterId || "") {
  if (
    state.observability.stream ||
    !state.isAdmin ||
    !logsView?.classList.contains("active")
  ) {
    return;
  }
  if (!afterId) {
    state.observability.streamConnected = false;
    if (logsStreamStatus) logsStreamStatus.textContent = "Rozlaczono";
    return;
  }
  const stream = new EventSource(
    "/api/observability/stream?after_id=" + encodeURIComponent(afterId)
  );
  state.observability.stream = stream;
  state.observability.streamConnected = false;
  if (logsStreamStatus && !state.observability.paused) {
    logsStreamStatus.textContent = "Laczenie...";
  }
  stream.onopen = () => {
    if (state.observability.stream !== stream) return;
    state.observability.streamConnected = true;
    if (logsStreamStatus) {
      logsStreamStatus.textContent = state.observability.paused ? "Wstrzymano" : "Polaczono";
    }
  };
  stream.onmessage = handleObservabilityEvent;
  stream.onerror = () => {
    if (state.observability.stream !== stream) return;
    state.observability.streamConnected = false;
    if (logsStreamStatus) {
      logsStreamStatus.textContent = state.observability.paused
        ? "Wstrzymano"
        : "Ponowne laczenie...";
    }
  };
}

function stopObservabilityStream() {
  state.observability.stream?.close();
  state.observability.stream = null;
  state.observability.streamConnected = false;
  if (logsStreamStatus) logsStreamStatus.textContent = "";
}

function observabilityEndpoint(tabName, cursor = "") {
  const params = new URLSearchParams({ limit: String(OBSERVABILITY_PAGE_SIZE) });
  if (cursor) params.set("cursor", cursor);
  if (tabName === "jobs") return "/api/observability/jobs?" + params.toString();
  params.set("severity", tabName);
  return "/api/observability/incidents?" + params.toString();
}

function appendUniqueObservabilityItems(tab, items = []) {
  const knownIds = new Set(tab.items.map((item) => item.id).filter(Boolean));
  tab.items = tab.items.concat(
    items.filter((item) => {
      if (!item?.id || knownIds.has(item.id)) return false;
      knownIds.add(item.id);
      return true;
    })
  );
}

async function findIncidentRecord(recordId) {
  let cursor = "";
  const visitedCursors = new Set();
  while (true) {
    const params = new URLSearchParams({ limit: String(OBSERVABILITY_PAGE_SIZE) });
    if (cursor) params.set("cursor", cursor);
    const payload = await requestObservabilityPayload(
      `/api/observability/incidents?${params.toString()}`
    );
    const items = Array.isArray(payload.items) ? payload.items : [];
    const found = items.find((item) => item.id === recordId);
    if (found) return found;
    const nextCursor = payload.next_cursor || "";
    if (!nextCursor || visitedCursors.has(nextCursor)) return null;
    visitedCursors.add(nextCursor);
    cursor = nextCursor;
  }
  return null;
}

async function loadIncidentThroughRecord(severity, recordId) {
  if (!["critical", "error", "warning"].includes(severity)) return null;
  const tab = observabilityTab(severity);
  const requestId = Number(tab.requestId || 0) + 1;
  tab.requestId = requestId;
  tab.loading = true;
  tab.items = [];
  tab.nextCursor = "";
  let cursor = "";
  const visitedCursors = new Set();
  try {
    while (true) {
      const payload = await requestObservabilityPayload(observabilityEndpoint(severity, cursor));
      if (tab.requestId !== requestId) return null;
      appendUniqueObservabilityItems(
        tab,
        (Array.isArray(payload.items) ? payload.items : []).filter(
          (item) => item.severity === severity
        )
      );
      tab.nextCursor = payload.next_cursor || "";
      const found = tab.items.find((item) => item.id === recordId);
      if (found) return found;
      if (!tab.nextCursor || visitedCursors.has(tab.nextCursor)) return null;
      visitedCursors.add(tab.nextCursor);
      cursor = tab.nextCursor;
    }
  } finally {
    if (tab.requestId === requestId) tab.loading = false;
  }
}

async function loadJobThroughRecord(recordId) {
  const jobs = observabilityTab("jobs");
  const requestId = Number(jobs.requestId || 0) + 1;
  jobs.requestId = requestId;
  jobs.loading = true;
  jobs.items = [];
  jobs.nextCursor = "";
  let cursor = "";
  const visitedCursors = new Set();
  try {
    while (true) {
      const payload = await requestObservabilityPayload(observabilityEndpoint("jobs", cursor));
      if (jobs.requestId !== requestId) return null;
      appendUniqueObservabilityItems(jobs, Array.isArray(payload.items) ? payload.items : []);
      jobs.nextCursor = payload.next_cursor || "";
      const found = jobs.items.find((item) => item.id === recordId);
      if (found) return found;
      if (!jobs.nextCursor || visitedCursors.has(jobs.nextCursor)) return null;
      visitedCursors.add(jobs.nextCursor);
      cursor = jobs.nextCursor;
    }
  } finally {
    if (jobs.requestId === requestId) jobs.loading = false;
  }
}

async function walkObservabilityPages(kind, recordId) {
  if (!recordId || !["incidents", "jobs"].includes(kind)) return null;
  if (kind === "jobs") {
    const item = await loadJobThroughRecord(recordId);
    return item ? { item, tabName: "jobs" } : null;
  }
  const discovered = await findIncidentRecord(recordId);
  if (!discovered) return null;
  const item = await loadIncidentThroughRecord(discovered.severity, recordId);
  return item ? { item, tabName: discovered.severity } : null;
}

function focusObservabilityRecord(recordId) {
  const card = [...logsOutput.querySelectorAll("[data-observability-id]")].find(
    (item) => item.dataset.observabilityId === recordId
  );
  if (!card) return false;
  card.classList.add("log-card-highlight");
  card.focus({ preventScroll: true });
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  window.setTimeout(() => card.classList.remove("log-card-highlight"), 2400);
  return true;
}

async function openObservabilityRecord(kind, recordId) {
  const located = await walkObservabilityPages(kind, recordId);
  if (!located || !state.observability.tabs[located.tabName]) {
    throw new Error("Nie znaleziono wskazanego rekordu obserwowalnosci.");
  }
  resetCommittedLogFilters();
  await switchLogTab(located.tabName);
  await waitForLogsPaint();
  if (!focusObservabilityRecord(recordId)) {
    throw new Error("Nie mozna pokazac wskazanego rekordu obserwowalnosci.");
  }
}

async function loadObservabilityTab(tabName, { append = false, force = false } = {}) {
  if (tabName === "live") {
    if (append) {
      await loadOlderLiveLogs();
      return;
    }
    await seedLiveLogs({ force });
    startObservabilityStream();
    return;
  }
  const tab = observabilityTab(tabName);
  if (tab.loading) return;
  if (force) {
    tab.items = [];
    tab.nextCursor = "";
  }
  if (!append && tab.items.length) {
    renderLogs();
    if (["critical", "error", "warning"].includes(tabName)) {
      await markSeverityRead(tabName, tab.requestId);
    }
    return;
  }
  const cursor = append ? tab.nextCursor : "";
  const endpoint = observabilityEndpoint(tabName, cursor);
  const requestId = Number(tab.requestId || 0) + 1;
  tab.requestId = requestId;
  tab.loading = true;
  if (state.observability.activeTab === tabName) renderLogs();
  let rendered = false;
  try {
    const payload = await requestObservabilityPayload(endpoint);
    if (tab.requestId !== requestId) return;
    const items = Array.isArray(payload.items) ? payload.items : [];
    if (append) {
      appendUniqueObservabilityItems(tab, items);
    } else {
      tab.items = items;
    }
    tab.nextCursor = payload.next_cursor || "";
    if (state.observability.activeTab === tabName) {
      tab.loading = false;
      renderLogs();
      rendered = true;
      if (!append && ["critical", "error", "warning"].includes(tabName)) {
        await markSeverityRead(tabName, requestId);
      }
    }
  } finally {
    if (tab.requestId === requestId) {
      tab.loading = false;
      if (!rendered && state.observability.activeTab === tabName) renderLogs();
    }
  }
}

async function switchLogTab(tabName) {
  if (!state.observability.tabs[tabName]) return;
  state.observability.activeTab = tabName;
  document.querySelectorAll("[data-log-tab]").forEach((button) => {
    const active = button.dataset.logTab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelector(".logs-live-controls")?.toggleAttribute("hidden", tabName !== "live");
  renderLogs();
  await loadObservabilityTab(tabName);
}

async function loadLogs({ refresh = false } = {}) {
  const tabName = state.observability.activeTab;
  await loadObservabilityTab(tabName, { force: refresh });
  startObservabilityStream();
}

async function pollLogStatus() {
  if (!state.isAdmin) {
    updateLogAlert({});
    return;
  }
  if (state.observability.stream && state.observability.streamConnected) {
    return;
  }
  await requestObservabilityPayload("/api/observability/events?limit=1");
}

function createPoller(name, intervalMs, callback, options = {}) {
  const maxDelayMs = Number(options.maxDelayMs || 60000);
  const hiddenDelayMs = Number(options.hiddenDelayMs || POLL_HIDDEN_DELAY_MS);
  const poller = {
    name,
    intervalMs,
    failures: 0,
    timer: 0,
    running: false,
  };
  const schedule = (delayMs = intervalMs) => {
    if (poller.timer) {
      window.clearTimeout(poller.timer);
    }
    poller.timer = window.setTimeout(run, Math.max(0, delayMs));
  };
  const nextDelay = () => {
    if (document.hidden) {
      return hiddenDelayMs;
    }
    if (!poller.failures) {
      return intervalMs;
    }
    return Math.min(maxDelayMs, intervalMs * 2 ** poller.failures);
  };
  const run = async () => {
    poller.timer = 0;
    if (document.hidden) {
      schedule(hiddenDelayMs);
      return;
    }
    if (poller.running) {
      schedule(intervalMs);
      return;
    }
    poller.running = true;
    try {
      await callback();
      poller.failures = 0;
    } catch (_error) {
      poller.failures += 1;
    } finally {
      poller.running = false;
      schedule(nextDelay());
    }
  };
  poller.schedule = schedule;
  poller.kick = () => {
    schedule(0);
  };
  state.pollers.push(poller);
  return poller;
}

function startBackgroundPollers() {
  state.runtimeStatusPoller = new PicSyncra.RuntimeStatusPoller({
    fetchStatus: fetchRuntimeStatus,
    onVersionChanged: refreshRuntimeDetailForVersion,
    activeIntervalMs: 5000,
    hiddenIntervalMs: 30000,
    maxBackoffMs: 60000,
    isHidden: () => document.hidden,
  });
  state.runtimeStatusPoller.start().catch(() => {});
  createPoller("logs", 15000, pollLogStatus).schedule(15000);
  createPoller("ocr-queue", 2000, refreshOcrBackgroundQueue).schedule(2000);
  createPoller("ocr-slot-state", 1500, refreshOcrSlotStates).schedule(1500);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    healthPollGeneration += 1;
    healthPollController?.abort();
    healthPollController = null;
    return;
  }
  state.pollers.forEach((poller) => poller.kick());
});

function openLogsClearModal() {
  if (!logsClearPassword || !logsClearStatus) {
    return;
  }
  logsClearStatus.textContent = "";
  logsClearPassword.value = "";
  document.querySelector("#logsClearModal")?.classList.add("active");
  window.setTimeout(() => logsClearPassword?.focus(), 0);
}

function closeLogsClearModal() {
  if (!logsClearPassword || !logsClearStatus) {
    return;
  }
  logsClearPassword.value = "";
  logsClearStatus.textContent = "";
  document.querySelector("#logsClearModal")?.classList.remove("active");
}

function resetObservabilityLists() {
  stopObservabilityStream();
  state.observability.streamSeeded = false;
  state.observability.streamAfterId = "";
  state.observability.seedGeneration = Number(state.observability.seedGeneration || 0) + 1;
  state.observability.seedLoading = false;
  state.observability.unreadRequestId = Number(state.observability.unreadRequestId || 0) + 1;
  state.observability.buffer = [];
  for (const tab of Object.values(state.observability.tabs)) {
    tab.requestId = Number(tab.requestId || 0) + 1;
    tab.loading = false;
    tab.items = [];
    tab.nextCursor = "";
    tab.unread = 0;
  }
  updateLogAlert({});
}

async function clearLogs(password) {
  if (!password) {
    return;
  }
  if (logsClearStatus) {
    logsClearStatus.textContent = "Czyszczenie...";
  }
  const payload = await requestJson("/api/logs/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  resetObservabilityLists();
  await loadLogs({ refresh: true });
  if ((payload.clear_errors || []).length) {
    if (logsClearStatus) {
      logsClearStatus.textContent = `Nie wyczyszczono wszystkich logow: ${(payload.clear_errors || []).join(
        "; "
      )}`;
    }
    return;
  }
  closeLogsClearModal();
}

function formPayload() {
  return {
    product_id: productForm.elements.product_id.value,
    name: productForm.elements.name.value,
    type_name: productForm.elements.type_name.value,
    model: productForm.elements.model.value,
    color1: productForm.elements.color1.value,
    color2: productForm.elements.color2.value,
    color3: productForm.elements.color3.value,
    extra: productForm.elements.extra.value,
    ean: productForm.elements.ean.value,
  };
}

function normalizedIdentityValue(value) {
  return String(value || "").trim().toUpperCase();
}

function productEntryLabel(entry = {}) {
  const colors = [entry.color1, entry.color2, entry.color3].filter(Boolean).join(" / ");
  const parts = [entry.name, entry.type_name, entry.model, colors, entry.extra].filter(Boolean);
  const suffix = entry.ean ? `EAN ${entry.ean}` : entry.product_id || "";
  return parts.join(" | ") + (suffix ? ` - ${suffix}` : "");
}

function entryFromProcessPayload(payload = {}, fallback = {}) {
  const result = payload.entry || {};
  const raw = result.entry || {};
  const entry = {
    product_id: result.product_id || raw.PRODUCT_ID || fallback.product_id || "",
    ean: raw.EAN || fallback.ean || payload.ean || "",
    name: raw.NAZWA || fallback.name || "",
    type_name: raw.TYP || fallback.type_name || "",
    model: raw.MODEL || fallback.model || "",
    color1: raw.KOLOR1 || fallback.color1 || "",
    color2: raw.KOLOR2 || fallback.color2 || "",
    color3: raw.KOLOR3 || fallback.color3 || "",
    extra: raw.DODATKI || fallback.extra || "",
  };
  entry.label = productEntryLabel(entry);
  return entry;
}

function upsertProductEntry(entry = {}) {
  if (!entry.product_id && !entry.ean) return;
  const productId = normalizedIdentityValue(entry.product_id);
  const ean = normalizedIdentityValue(entry.ean);
  const entries = [...(state.entries || [])];
  const index = entries.findIndex((item) => {
    const itemProductId = normalizedIdentityValue(item.product_id);
    const itemEan = normalizedIdentityValue(item.ean);
    return (productId && itemProductId === productId) || (ean && itemEan === ean);
  });
  if (index >= 0) {
    entries[index] = { ...entries[index], ...entry, label: entry.label || entries[index].label };
  } else {
    entries.unshift(entry);
  }
  state.entries = entries;
  renderEntrySelect();
}

function productFieldsChangedSinceLoad() {
  if (!state.loadedEntryOriginal) {
    return false;
  }
  const current = formPayload();
  return trackedProductFields.some(
    (fieldName) =>
      normalizedIdentityValue(current[fieldName]) !==
      normalizedIdentityValue(state.loadedEntryOriginal[fieldName])
  );
}

function hasProductDraftData() {
  const current = formPayload();
  return trackedProductFields.some((fieldName) => String(current[fieldName] || "").trim());
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

function hasPendingUserChanges() {
  return (
    hasPendingSlotChanges() ||
    productFieldsChangedSinceLoad() ||
    (!state.loadedEntryOriginal && hasProductDraftData())
  );
}

function updateSubmitButtonState() {
  if (!submitButton || submitButton.dataset.busy === "1") {
    return;
  }
  const pendingUploads = activeSlotUploads();
  if (pendingUploads.length) {
    submitButton.disabled = true;
    submitButton.textContent = `Wysylanie ${pendingUploads.length}`;
    submitButton.title = "Poczekaj, az nowe pliki trafia do cache backendu.";
    submitButton.setAttribute("aria-label", submitButton.textContent);
    return;
  }
  const failedUploads = failedSlotUploads();
  if (failedUploads.length) {
    const [prefix, item] = failedUploads[0];
    const reason = slotUploadError(item);
    submitButton.disabled = true;
    submitButton.textContent = "Upload nieudany";
    submitButton.title = reason
      ? `Slot ${prefix}: ${reason}`
      : "Popraw slot z nieudanym uploadem albo wybierz plik ponownie.";
    submitButton.setAttribute(
      "aria-label",
      reason ? `Upload nieudany: slot ${prefix}: ${reason}` : submitButton.textContent
    );
    return;
  }
  submitButton.disabled = false;
  const hasChanges = hasPendingUserChanges();
  submitButton.textContent = hasChanges ? "Aktualizuj" : "Synchronizuj";
  submitButton.title = hasChanges
    ? "Zapisuje zmiany w danych i slotach oraz aktualizuje lokalne pliki, FTP i SQL."
    : "Pobiera brakujace zdjecia z FTP i uzupelnia lokalne pliki.";
  submitButton.setAttribute("aria-label", submitButton.textContent);
}

function pageExitWarningText() {
  const reasons = [];
  if (hasPendingUserChanges()) reasons.push("sa niezapisane zmiany");
  if (activeSlotUploads().length) reasons.push("trwa wysylanie plikow");
  if (state.photosLoading) reasons.push("trwa wczytywanie danych");
  if (submitButton?.dataset.busy === "1") reasons.push("trwa zapisywanie");
  const detail = reasons.length ? ` (${reasons.join(", ")})` : "";
  return `Opuscic strone${detail}?`;
}

function shouldConfirmPageExit() {
  if (state.navigationGuardBypass) return false;
  return Boolean(
    hasPendingUserChanges() ||
      activeSlotUploads().length ||
      state.photosLoading ||
      submitButton?.dataset.busy === "1"
  );
}

function confirmPageExit() {
  if (!shouldConfirmPageExit()) return true;
  return window.confirm(pageExitWarningText());
}

function continueBrowserBackNavigation() {
  state.navigationGuardBypass = true;
  window.history.back();
  window.setTimeout(() => {
    state.navigationGuardBypass = false;
    if (!window.history.state?.picsyncraLeaveGuard) {
      window.history.pushState({ picsyncraLeaveGuard: true }, "", window.location.href);
    }
  }, 600);
}

function setupPageExitGuards() {
  window.addEventListener("pagehide", () => {
    notifyActiveUsersPresenceLeave();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!shouldConfirmPageExit()) return;
    event.preventDefault();
    event.returnValue = "";
  });
  if (!window.history?.pushState) {
    return;
  }
  window.history.replaceState({ ...(window.history.state || {}), picsyncraBase: true }, "", window.location.href);
  window.history.pushState({ picsyncraLeaveGuard: true }, "", window.location.href);
  window.addEventListener("popstate", () => {
    if (state.navigationGuardBypass) return;
    if (!confirmPageExit()) {
      window.history.pushState({ picsyncraLeaveGuard: true }, "", window.location.href);
      return;
    }
    continueBrowserBackNavigation();
  });
}

function mergePhotoRecord(existing = {}, incoming = {}) {
  const merged = { ...existing, ...incoming };
  for (const key of ["local", "ftp", "sql", "is_image", "sql_checked"]) {
    merged[key] = Boolean(existing[key] || incoming[key]);
  }
  for (const key of [
    "filename",
    "path",
    "token",
    "url",
    "thumb_url",
    "file_version",
    "ftp_filename",
    "ftp_path",
    "ftp_token",
    "ftp_url",
    "ftp_thumb_url",
    "ftp_file_version",
    "sql_value",
  ]) {
    if (incoming[key]) {
      merged[key] = incoming[key];
    } else if (existing[key]) {
      merged[key] = existing[key];
    } else {
      merged[key] = "";
    }
  }
  if (incoming.sql_checked) {
    merged.sql = Boolean(incoming.sql);
    merged.sql_checked = true;
    merged.sql_value = incoming.sql_value || "";
  }
  merged.prefix = incoming.prefix || existing.prefix || "";
  const cachedFtpKey = ftpPreviewCacheKey(
    merged,
    formValue("ean") || state.loadedEntryOriginal?.ean || ""
  );
  const cachedFtp = state.ftpPreviewCache.get(cachedFtpKey);
  if (cachedFtp) {
    setFtpPreviewCache(cachedFtpKey, cachedFtp);
    return applyCachedFtpPreview(merged, merged.prefix, cachedFtp);
  }
  return merged;
}

function photoLoadingText() {
  const loading = [];
  for (const [source, status] of state.photoSourceStatus.entries()) {
    if (status === "pending" || status === "loading") {
      loading.push(photoSourceLabels[source] || source);
    }
  }
  return loading.length ? `Wczytywanie: ${loading.join(", ")}` : "Wczytywanie";
}

function photoStatusSummary() {
  const done = [];
  const loading = [];
  const failed = [];
  for (const [source, status] of state.photoSourceStatus.entries()) {
    if (status === "done") done.push(photoSourceLabels[source] || source);
    if (status === "pending" || status === "loading") loading.push(photoSourceLabels[source] || source);
    if (status === "failed") failed.push(photoSourceLabels[source] || source);
  }
  const parts = [];
  if (done.length) parts.push(`gotowe: ${done.join(", ")}`);
  if (loading.length) parts.push(`trwa: ${loading.join(", ")}`);
  if (failed.length) parts.push(`blad: ${failed.join(", ")}`);
  return parts.join(" | ");
}

function setPhotoSourceStatus(source, status, requestId) {
  if (requestId !== state.photoLoadRequestId) return;
  state.photoSourceStatus.set(source, status);
  const summary = photoStatusSummary();
  formStatus.textContent = summary || photoLoadingText();
}

function applyPhotoPayload(photos = [], options = {}) {
  const changedPrefixes = new Set();
  const allowedPrefixes = options.prefixes instanceof Set ? options.prefixes : null;
  for (const photo of photos) {
    if (!photo?.prefix) continue;
    if (allowedPrefixes && !allowedPrefixes.has(photo.prefix)) continue;
    if (!options.force && state.files.has(photo.prefix)) {
      const existing = state.loadedPhotos.get(photo.prefix) || {};
      const merged = mergePhotoRecord(existing, photo);
      state.loadedPhotos.set(photo.prefix, merged);
      applyDefaultSlotSource(photo.prefix, merged);
      if (photoHasUsableContent(photo)) {
        for (const changedPrefix of relocateProvisionalSlotFile(photo.prefix)) {
          changedPrefixes.add(changedPrefix);
        }
      }
      continue;
    }
    if (!options.force && slotHasPendingUserEdit(photo.prefix)) continue;
    const existing = state.loadedPhotos.get(photo.prefix) || {};
    const merged = mergePhotoRecord(existing, photo);
    if (options.clearDirty) {
      delete merged.dirty;
    }
    state.loadedPhotos.set(photo.prefix, merged);
    applyDefaultSlotSource(photo.prefix, merged);
    changedPrefixes.add(photo.prefix);
  }
  if (changedPrefixes.size) {
    renderChangedSlots(changedPrefixes);
    scheduleBackgroundFtpPreviewLoad(undefined, 1500);
  }
  return changedPrefixes;
}

function photoRequestTimeoutMs(source) {
  if (source === "ftp") return 15000;
  if (source === "all") return 25000;
  return 20000;
}

async function requestEntryPhotos(entry, source, prefixes = null, options = {}) {
  const params = new URLSearchParams({ source });
  if (prefixes && prefixes.size) {
    params.set("prefixes", [...prefixes].join(","));
  }
  return requestJson(`/api/entries/photos?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
    timeoutMs: Number(options.timeoutMs || photoRequestTimeoutMs(source)),
  });
}

function backgroundFtpLookupKey(fields = formPayload()) {
  const ean = normalizedIdentityValue(fields.ean);
  if (!state.ftpEnabled || !/^\d{13}$/.test(ean)) return "";
  for (const fieldName of ["name", "type_name", "model", "color1"]) {
    if (!String(fields[fieldName] || "").trim()) return "";
  }
  return [
    ean,
    normalizedIdentityValue(fields.name),
    normalizedIdentityValue(fields.type_name),
    normalizedIdentityValue(fields.model),
    normalizedIdentityValue(fields.color1),
    normalizedIdentityValue(fields.color2),
    normalizedIdentityValue(fields.color3),
    normalizedIdentityValue(fields.extra),
  ].join("|");
}

function clearStaleBackgroundFtpPhotos(activeKey) {
  let changed = false;
  for (const [prefix, photo] of Array.from(state.loadedPhotos.entries())) {
    if (!photo?.background_ftp_key || photo.background_ftp_key === activeKey) continue;
    if (slotHasPendingUserEdit(prefix)) continue;
    state.loadedPhotos.delete(prefix);
    state.slotSources.delete(prefix);
    state.userSelectedSlotSources.delete(prefix);
    changed = true;
    renderSlot(prefix);
  }
  if (changed) updateSubmitButtonState();
}

async function loadBackgroundFtpPhotosForCurrentForm() {
  const entry = formPayload();
  const key = backgroundFtpLookupKey(entry);
  if (!key) {
    state.backgroundFtpLookupKey = "";
    clearStaleBackgroundFtpPhotos("");
    return;
  }
  clearStaleBackgroundFtpPhotos(key);
  if (state.backgroundFtpLookupKey === key) return;
  state.backgroundFtpLookupKey = key;
  const requestId = state.backgroundFtpLookupRequestId + 1;
  state.backgroundFtpLookupRequestId = requestId;
  try {
    const payload = await requestEntryPhotos(entry, "ftp", null, { timeoutMs: 15000 });
    if (state.backgroundFtpLookupRequestId !== requestId) return;
    if (backgroundFtpLookupKey() !== key) return;
    const photos = (payload.photos || []).map((photo) => ({
      ...photo,
      background_ftp_key: key,
    }));
    applyPhotoPayload(photos, { force: false });
    if (photos.length) {
      formStatus.textContent = `Znaleziono zdjecia FTP: ${photos.length}.`;
    }
    updateSubmitButtonState();
  } catch (error) {
    if (state.backgroundFtpLookupRequestId === requestId && showTimingDetails()) {
      formStatus.textContent = `Nie udalo sie sprawdzic FTP w tle: ${error.message}`;
    }
  }
}

function scheduleBackgroundFtpLookup(delay = 900) {
  window.clearTimeout(state.backgroundFtpLookupTimer);
  state.backgroundFtpLookupTimer = window.setTimeout(() => {
    loadBackgroundFtpPhotosForCurrentForm().catch(() => {});
  }, delay);
}

function similarFileIdentityKey(fields = formPayload(), occupiedPrefixes = similarOccupiedSlotPrefixes()) {
  const formIdentity = [
    fields.name,
    fields.type_name,
    fields.model,
    fields.color1,
    fields.color2,
    fields.color3,
    fields.extra,
  ]
    .map(normalizedIdentityValue)
    .join("|");
  return `${formIdentity}|slots:${occupiedPrefixes.map(normalizedIdentityValue).join(",")}`;
}

function similarOccupiedSlotPrefixes() {
  const occupied = new Set(state.files.keys());
  for (const prefix of state.loadedPhotos.keys()) {
    if (!state.deletedSlots.has(prefix)) occupied.add(prefix);
  }
  return Array.from(occupied).sort();
}

function hasSimilarBaseIdentity(fields = formPayload()) {
  return Boolean(fields.name && fields.type_name && fields.model);
}

function applySimilarCandidates(candidates) {
  const acceptedCandidates = new Map(
    Array.from(state.similarCandidates.entries()).filter(
      ([prefix]) => state.slotSources.get(prefix) === "similar" && state.files.has(prefix)
    )
  );
  state.similarCandidates.clear();
  for (const [prefix, candidate] of acceptedCandidates) {
    state.similarCandidates.set(prefix, candidate);
  }
  for (const candidate of candidates) {
    const prefix = String(candidate.target_prefix || "").trim();
    if (prefix && !acceptedCandidates.has(prefix) && !state.dismissedSimilarSlots.has(prefix)) {
      state.similarCandidates.set(prefix, candidate);
    }
  }
  renderSlots();
}

function setSimilarFileLookupState(active, key = "") {
  state.similarFileLookupInFlight = active;
  state.similarFileLookupKey = active ? key : "";
  if (active) state.similarFileLookupStartedAt = performance.now();
  renderSlots();
}

function cancelSimilarFileLookup() {
  window.clearTimeout(state.similarFileLookupTimer);
  state.similarFileLookupController?.abort();
  state.similarFileLookupController = null;
  state.similarFileLookupRequestId += 1;
  setSimilarFileLookupState(false);
}

async function lookupSimilarFiles() {
  const fields = formPayload();
  const occupiedPrefixes = similarOccupiedSlotPrefixes();
  const key = similarFileIdentityKey(fields, occupiedPrefixes);
  if (!hasSimilarBaseIdentity(fields)) {
    applySimilarCandidates([]);
    cancelSimilarFileLookup();
    return;
  }
  state.similarFileLookupController?.abort();
  const controller = new AbortController();
  state.similarFileLookupController = controller;
  const requestId = ++state.similarFileLookupRequestId;
  setSimilarFileLookupState(true, key);
  try {
    const payload = await requestJson("/api/similar-files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...fields, occupied_prefixes: occupiedPrefixes }),
      signal: controller.signal,
      timeoutMs: 15000,
    });
    if (state.similarFileLookupRequestId !== requestId || similarFileIdentityKey() !== key) return;
    applySimilarCandidates(payload.candidates || []);
  } catch (error) {
    if (error.name === "AbortError") return;
    if (state.similarFileLookupRequestId === requestId && similarFileIdentityKey() === key) {
      formStatus.textContent = `Nie udalo sie sprawdzic plikow z podobnych produktow: ${error.message}`;
    }
  } finally {
    if (state.similarFileLookupRequestId === requestId) {
      state.similarFileLookupController = null;
      setSimilarFileLookupState(false);
    }
  }
}

function scheduleSimilarFileLookup(delay = 450) {
  window.clearTimeout(state.similarFileLookupTimer);
  state.similarFileLookupTimer = window.setTimeout(() => {
    lookupSimilarFiles().catch(() => {});
  }, delay);
}

function startSimilarFileLookup({ immediate = false } = {}) {
  window.clearTimeout(state.similarFileLookupTimer);
  if (immediate) {
    lookupSimilarFiles().catch(() => {});
    return;
  }
  scheduleSimilarFileLookup();
}

function clearSelectedFiles() {
  for (const prefix of Array.from(state.filePreviewUrls.keys())) {
    revokeFilePreviewUrl(prefix);
  }
  state.files.clear();
}

async function loadPhotosForEntry(entry, options = {}) {
  recordOcrActivity({ kind: "data-load" });
  const started = performance.now();
  const progressive = options.progressive !== false;
  const targetPrefixes = new Set((options.prefixes || []).map((prefix) => String(prefix || "").trim()).filter(Boolean));
  const partial = targetPrefixes.size > 0;
  const requestId = state.photoLoadRequestId + 1;
  state.photoLoadRequestId = requestId;
  state.photosLoading = true;
  const collectedPrefixes = new Set();
  if (!partial) {
    state.loadedPhotos.clear();
    state.deletedSlots.clear();
    state.slotSources.clear();
    state.userSelectedSlotSources.clear();
    state.ftpPreviewLoading.clear();
    state.ftpPreviewBackgroundLoading.clear();
    state.photoSourcesLoaded.clear();
    state.backgroundFtpLookupKey = "";
    state.backgroundFtpLookupRequestId += 1;
    window.clearTimeout(state.backgroundFtpLookupTimer);
  } else {
    for (const prefix of targetPrefixes) {
      state.ftpPreviewLoading.delete(prefix);
      state.ftpPreviewBackgroundLoading.delete(prefix);
      state.userSelectedSlotSources.delete(prefix);
    }
  }
  window.clearTimeout(state.backgroundFtpPreviewTimer);
  const sources = progressive ? ["local", "sql", "ftp"] : ["all"];
  state.photoSourceStatus.clear();
  for (const source of sources) {
    state.photoSourceStatus.set(source, "pending");
  }
  formStatus.textContent = photoLoadingText();
  if (!partial) {
    renderSlotsExceptPendingUserEdits();
  }
  const tasks = sources.map(async (source) => {
    setPhotoSourceStatus(source, "loading", requestId);
    try {
      const payload = await requestEntryPhotos(entry, source, partial ? targetPrefixes : null);
      if (state.photoLoadRequestId === requestId) {
        setPhotoSourceStatus(source, "done", requestId);
        state.photoSourcesLoaded.add(payload.source || source);
        const payloadPhotos = partial
          ? (payload.photos || []).filter((photo) => targetPrefixes.has(photo?.prefix))
          : payload.photos || [];
        for (const photo of payloadPhotos) {
          if (photo?.prefix) collectedPrefixes.add(photo.prefix);
        }
        applyPhotoPayload(payloadPhotos, {
          prefixes: partial ? targetPrefixes : null,
          force: Boolean(options.force),
          clearDirty: Boolean(options.clearDirty),
        });
        if ((payload.source || source) === "ftp" || (payload.source || source) === "all") {
          scheduleBackgroundFtpPreviewLoad(requestId, 1200);
        }
        updateSubmitButtonState();
      }
      return payload;
    } catch (error) {
      setPhotoSourceStatus(source, "failed", requestId);
      throw error;
    }
  });
  try {
    const settled = await Promise.allSettled(tasks);
    if (state.photoLoadRequestId !== requestId) return;
    const failures = settled.filter((item) => item.status === "rejected");
    if (failures.length && failures.length === settled.length) {
      throw failures[0].reason;
    }
    if (failures.length) {
      formStatus.textContent = "Czesc zrodel podgladu nie odpowiedziala.";
    } else {
      formStatus.textContent = photoStatusSummary() || "Wczytano podglady.";
    }
    state.lastLookupMs = performance.now() - started;
  } finally {
    if (state.photoLoadRequestId !== requestId) return;
    state.photosLoading = false;
    state.photoSourceStatus.clear();
    if (partial) {
      for (const prefix of targetPrefixes) {
        if (!collectedPrefixes.has(prefix) && !slotHasPendingUserEdit(prefix)) {
          state.loadedPhotos.delete(prefix);
          state.slotSources.delete(prefix);
          state.userSelectedSlotSources.delete(prefix);
          state.slotFits.delete(prefix);
          bumpSlotRevision(prefix);
        }
      }
    }
    updateRuntimeMetrics();
    renderSlotsExceptPendingUserEdits(partial ? targetPrefixes : null);
    scheduleBackgroundFtpPreviewLoad(requestId, 1500);
  }
}

function fillForm(entry, options = {}) {
  state.suppressAutoSearch = true;
  state.loadedEntryOriginal = { ...entry };
  state.slotFits.clear();
  state.deletedSlots.clear();
  state.slotSources.clear();
  state.similarCandidates.clear();
  state.dismissedSimilarSlots.clear();
  cancelSimilarFileLookup();
  state.userSelectedSlotSources.clear();
  state.ftpPreviewLoading.clear();
  state.ftpPreviewBackgroundLoading.clear();
  state.photoSourcesLoaded.clear();
  state.backgroundFtpLookupKey = "";
  state.backgroundFtpLookupRequestId += 1;
  window.clearTimeout(state.backgroundFtpLookupTimer);
  productForm.elements.product_id.value = entry.product_id || "";
  productForm.elements.name.value = entry.name || "";
  productForm.elements.type_name.value = entry.type_name || "";
  productForm.elements.model.value = entry.model || "";
  productForm.elements.color1.value = entry.color1 || "";
  productForm.elements.color2.value = entry.color2 || "";
  productForm.elements.color3.value = entry.color3 || "";
  productForm.elements.extra.value = entry.extra || "";
  productForm.elements.ean.value = entry.ean || "";
  handlePimcoreEanInput();
  applyProductFieldSettings();
  formStatus.textContent = entry.product_id ? `Wczytano ${entry.product_id}` : "Wczytano wpis";
  updateFieldWarnings();
  setTimeout(() => {
    state.suppressAutoSearch = false;
  }, 200);
  if (options.loadPhotos) {
    const photoLoad = loadPhotosForEntry({ ...entry, ...formPayload() });
    const photoLoadRequestId = state.photoLoadRequestId;
    photoLoad
      .catch((error) => {
        formStatus.textContent = `Wpis wczytany, ale zdjecia nie: ${error.message}`;
      })
      .then(() => {
        if (state.photoLoadRequestId !== photoLoadRequestId) return;
        startSimilarFileLookup({ immediate: true });
      });
    return;
  }
  state.photoLoadRequestId += 1;
  startSimilarFileLookup({ immediate: true });
}

async function refreshData() {
  const payload = await requestJson("/api/data");
  state.lists = payload.lists || {};
  state.entries = payload.entries || [];
  state.fileIndex = payload.file_index || state.fileIndex;
  state.ftpEnabled = payload.ftp_enabled !== false;
  state.productFields = payload.product_fields || state.productFields || {};
  renderDatalists();
  applyProductFieldLabels();
  renderEntrySelect();
  renderListEditor();
  updateRuntimeMetrics();
}

async function loadBootstrap(options = {}) {
  const payload = await requestJson("/api/bootstrap", options);
  state.settings = {
    ...(state.settings || {}),
    web_display: payload.web_display || state.settings?.web_display || { time_zone: "UTC" },
  };
  rerenderPanelTimestampViews();
  state.csrfToken = payload.csrf_token || state.csrfToken || "";
  state.ocrEnabledSlots = Array.isArray(payload.ocr_enabled_slots)
    ? payload.ocr_enabled_slots.map(String)
    : state.ocrEnabledSlots;
  state.defaultSlotFit = Boolean(payload.auto_content_fit);
  state.processing = payload.processing || state.processing || {};
  state.security = payload.security || state.security || {};
  state.ftpEnabled = payload.ftp_enabled !== false;
  if (versionInfo) {
    versionInfo.textContent = payload.version ? `Wersja ${payload.version}` : "";
  }
  serverInfo.textContent = payload.processed_dir;
  logoutButton.hidden = !payload.auth_enabled;
  state.currentUser = payload.current_user || null;
  applyPimcoreRuntimeCapabilities(payload.pimcore);
  updateAdminUi();
  applyTimingDetailsVisibility();
  pollLogStatus().catch(() => {});
  loadRecentProcessJobs().catch(() => {});
  refreshGithubStatus().catch(() => {});
  state.lists = payload.lists || {};
  state.entries = payload.entries || [];
  state.fileIndex = payload.file_index || null;
  state.ftpEnabled = payload.ftp_enabled !== false;
  state.productFields = payload.product_fields || {};
  state.processing = payload.processing || state.processing || {};
  state.security = payload.security || state.security || {};
  renderDatalists();
  applyProductFieldLabels();
  renderEntrySelect();
  renderSlots(payload.slots || []);
  renderListEditor();
  updateRuntimeMetrics();
  refreshRuntimeDetailViews();
  refreshOcrBackgroundQueue().catch(() => {});
}

async function refreshFileIndexStatus() {
  const payload = await requestJson("/api/file-index/status");
  state.fileIndex = payload;
  updateRuntimeMetrics();
}

function refreshRuntimeDetailForVersion(name, version) {
  const refreshers = {
    file_index: refreshFileIndexStatus,
    process_queue: () => refreshProcessQueue(version),
    active_clients: refreshActiveUsersPresence,
  };
  const refresh = refreshers[name];
  return refresh ? refresh() : Promise.resolve();
}

function refreshRuntimeDetailViews() {
  refreshFileIndexStatus().catch(() => {});
  refreshProcessQueue().catch(() => {});
  refreshActiveUsersPresence().catch(() => {
    renderActiveUsersPresence({ enabled: false, users: [] });
  });
}

async function searchByEan() {
  const ean = productForm.elements.ean.value.trim();
  if (!ean) {
    formStatus.textContent = "Wpisz EAN do wyszukania.";
    return;
  }
  const payload = await requestJson(`/api/entries/search?ean=${encodeURIComponent(ean)}`);
  renderEntrySelect(payload.entries || []);
  if (payload.entries && payload.entries.length === 1) {
    fillForm(payload.entries[0], { loadPhotos: true });
  } else {
    renderEntryModal(payload.entries || []);
    formStatus.textContent = `${(payload.entries || []).length} dopasowan po EAN.`;
  }
}

async function searchByProduct({ automatic = false } = {}) {
  const fields = formPayload();
  const params = new URLSearchParams({
    name: fields.name,
    type_name: fields.type_name,
    model: fields.model,
  });
  if (!automatic) {
    startSimilarFileLookup({ immediate: true });
  }
  const payload = await requestJson(`/api/entries/search?${params.toString()}`);
  renderEntrySelect(payload.entries || []);
  if (payload.entries && payload.entries.length > 0) {
    renderEntryModal(payload.entries);
  }
  if (!automatic) {
    formStatus.textContent = `${(payload.entries || []).length} dopasowan produktu.`;
  }
}

let autoSearchTimer = null;
function scheduleProductAutoSearch() {
  if (state.suppressAutoSearch) {
    return;
  }
  clearTimeout(autoSearchTimer);
  autoSearchTimer = setTimeout(() => {
    const fields = formPayload();
    const key = `${fields.name}|${fields.type_name}|${fields.model}`.toUpperCase();
    if (!fields.name || !fields.type_name || !fields.model || key === state.lastAutoSearchKey) {
      return;
    }
    state.lastAutoSearchKey = key;
    searchByProduct({ automatic: true }).catch(() => {});
  }, 500);
}

async function addListValue(event) {
  event.preventDefault();
  const value = listAddInput.value.trim();
  if (!value) {
    listStatus.textContent = "Wpisz wartosc.";
    return;
  }
  const exists = (state.lists[state.selectedList] || []).some(
    (item) => normalizeListValue(item) === normalizeListValue(value)
  );
  if (exists) {
    listStatus.textContent = "Taka wartosc juz istnieje na liscie.";
    state.listFilter = value;
    renderListEditor();
    return;
  }
  const payload = await requestJson(`/api/lists/${state.selectedList}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  state.lists = payload.lists || {};
  state.entries = payload.entries || state.entries;
  state.listFilter = "";
  renderDatalists();
  renderListEditor();
  listStatus.textContent = "Dodano.";
}

async function removeListValue(value) {
  const listLabel = listLabels[state.selectedList] || state.selectedList;
  if (!window.confirm(`Usunac "${value}" z listy ${listLabel}?`)) {
    return;
  }
  let payload;
  try {
    payload = await requestJson(`/api/lists/${state.selectedList}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
  } catch (error) {
    const detail = error.detail || {};
    if (error.status === 409 && Array.isArray(detail.used_by)) {
      renderListUsageModal(detail.value || value, detail.used_by);
      listStatus.textContent = error.message;
      return;
    }
    throw error;
  }
  state.lists = payload.lists || {};
  state.entries = payload.entries || state.entries;
  renderDatalists();
  renderListEditor();
  listStatus.textContent = "Usunieto.";
}

function inputField(name, label, value = "", attrs = {}) {
  const wrapper = document.createElement("label");
  const input = document.createElement(attrs.textarea ? "textarea" : "input");
  wrapper.textContent = label;
  input.name = name;
  if (attrs.type) input.type = attrs.type;
  if (attrs.className) wrapper.className = attrs.className;
  if (attrs.min !== undefined) input.min = attrs.min;
  if (attrs.max !== undefined) input.max = attrs.max;
  if (attrs.step !== undefined) input.step = attrs.step;
  if (attrs.placeholder !== undefined) input.placeholder = attrs.placeholder;
  if (attrs.checked !== undefined) input.checked = Boolean(attrs.checked);
  if (attrs.type === "checkbox") {
    input.value = "1";
  } else {
    input.value = value || "";
  }
  wrapper.appendChild(input);
  if (attrs.description) {
    const small = document.createElement("small");
    small.textContent = attrs.description;
    wrapper.appendChild(small);
  }
  return wrapper;
}

function panelTimeZoneField(value = "UTC") {
  const wrapper = document.createElement("label");
  const input = document.createElement("input");
  const datalist = document.createElement("datalist");
  const description = document.createElement("small");
  wrapper.textContent = "Globalna strefa czasu";
  input.type = "search";
  input.name = "web_display_time_zone";
  input.value = value || "UTC";
  input.required = true;
  input.setAttribute("list", "panelTimeZoneCatalog");
  datalist.id = "panelTimeZoneCatalog";
  for (const timeZone of state.panelTimeZones) {
    const option = document.createElement("option");
    option.value = timeZone;
    datalist.appendChild(option);
  }
  const validate = () => {
    input.setCustomValidity(
      state.panelTimeZones.includes(input.value)
        ? ""
        : "Wybierz strefe czasu z listy IANA."
    );
  };
  input.addEventListener("input", validate);
  input.addEventListener("change", validate);
  validate();
  description.textContent =
    "Wyszukaj i wybierz pelna nazwe IANA. Ustawienie obowiazuje wszystkich uzytkownikow.";
  wrapper.append(input, datalist, description);
  return wrapper;
}

function checkField(name, label, checked = false, description = "") {
  const wrapper = document.createElement("div");
  const input = document.createElement("input");
  const text = document.createElement("div");
  const title = document.createElement("strong");
  wrapper.className = "check-row";
  input.type = "checkbox";
  input.name = name;
  input.checked = Boolean(checked);
  input.setAttribute("aria-label", label);
  title.textContent = label;
  text.appendChild(title);
  if (description) {
    const small = document.createElement("small");
    small.textContent = description;
    text.appendChild(small);
  }
  wrapper.append(input, text);
  return wrapper;
}

function settingsFieldGroup(titleText, ...nodes) {
  const group = document.createElement("div");
  const title = document.createElement("h2");
  group.className = "settings-field-group";
  title.textContent = titleText;
  group.appendChild(title);
  for (const node of nodes.flat()) {
    if (node) group.appendChild(node);
  }
  return group;
}

function productFieldSettingsList(settings = {}) {
  const list = document.createElement("div");
  list.className = "product-field-settings-list wide-field";
  const normalized = normalizedProductFields(settings);
  for (const [key, definition] of Object.entries(productFieldDefinitions)) {
    const item = normalized[key];
    const row = document.createElement("div");
    const title = document.createElement("strong");
    const labelField = inputField(
      `product_field_${key}_label`,
      "Wlasna nazwa",
      item.label,
      { placeholder: definition.label }
    );
    const enabled = checkField(`product_field_${key}_enabled`, "Aktywne", item.enabled);
    const required = checkField(`product_field_${key}_required`, "Wymagane", item.required);
    const enabledInput = enabled.querySelector("input");
    const requiredInput = required.querySelector("input");
    row.className = "product-field-settings-row";
    row.dataset.productFieldSetting = key;
    title.textContent = definition.label;
    const syncRequired = () => {
      requiredInput.disabled = !enabledInput.checked;
      if (!enabledInput.checked) requiredInput.checked = false;
    };
    enabledInput.addEventListener("change", syncRequired);
    syncRequired();
    row.append(title, labelField, enabled, required);
    list.appendChild(row);
  }
  return list;
}

function collectProductFieldSettings(data) {
  return Object.fromEntries(
    Object.keys(productFieldDefinitions).map((key) => [
      key,
      {
        label: data.get(`product_field_${key}_label`) || "",
        enabled: data.has(`product_field_${key}_enabled`),
        required: data.has(`product_field_${key}_required`),
      },
    ])
  );
}

function credentialField(name, label, isSet = false, attrs = {}) {
  const field = document.createElement("label");
  const title = document.createElement("span");
  const row = document.createElement("span");
  const input = document.createElement("input");
  const originalType = attrs.type || "text";
  field.className = attrs.className ? `credential-field ${attrs.className}` : "credential-field";
  title.textContent = label;
  row.className = "credential-actions";
  input.name = name;
  input.type = originalType;
  input.placeholder = isSet ? "Zapisane - wpisz nowe, zeby zmienic" : "Nie ustawiono";
  row.appendChild(input);
  if (attrs.secretPath && isSet) {
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "secondary-button";
    reveal.textContent = "Pokaz zapisane";
    reveal.title = "Wymaga hasla administratora i pokazuje wartosc tylko tymczasowo.";
    reveal.addEventListener("click", () => {
      toggleCredentialReveal(input, reveal, attrs.secretPath, originalType);
    });
    row.appendChild(reveal);
  }
  field.append(title, row);
  return field;
}

function secretValueByPath(payload, path) {
  let value = payload;
  for (const part of String(path || "").split(".")) {
    if (!part) continue;
    value = value?.[part];
  }
  return value === undefined || value === null ? "" : String(value);
}

const secretRevealTimers = new WeakMap();

function clearSecretRevealTimer(input) {
  const timer = secretRevealTimers.get(input);
  if (timer) {
    window.clearTimeout(timer);
    secretRevealTimers.delete(input);
  }
}

function hideCredentialSecret(input, button, originalType) {
  clearSecretRevealTimer(input);
  input.value = "";
  input.type = originalType;
  input.dataset.secretVisible = "";
  button.textContent = "Pokaz zapisane";
}

async function loadSettingsSecrets(password) {
  return requestJson("/api/settings/secrets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
    timeoutMs: 10000,
  });
}

let secretRevealResolve = null;

function closeSecretRevealModal(result = null) {
  if (secretRevealModal) {
    secretRevealModal.classList.remove("active");
  }
  if (secretRevealPassword) {
    secretRevealPassword.value = "";
  }
  if (secretRevealStatus) {
    secretRevealStatus.textContent = "";
  }
  if (secretRevealResolve) {
    const resolve = secretRevealResolve;
    secretRevealResolve = null;
    resolve(result);
  }
}

function requestSecretRevealPassword() {
  if (!secretRevealModal || !secretRevealPassword || !secretRevealStatus) {
    return Promise.reject(new Error("Brak formularza potwierdzenia hasla administratora."));
  }
  if (secretRevealResolve) {
    closeSecretRevealModal();
  }
  secretRevealPassword.value = "";
  secretRevealStatus.textContent = "";
  secretRevealModal.classList.add("active");
  window.setTimeout(() => secretRevealPassword.focus(), 0);
  return new Promise((resolve) => {
    secretRevealResolve = resolve;
  });
}

async function toggleCredentialReveal(input, button, secretPath, originalType) {
  if (input.dataset.secretVisible === "1") {
    hideCredentialSecret(input, button, originalType);
    return;
  }
  const password = await requestSecretRevealPassword();
  if (password === null) {
    return;
  }
  if (!password) {
    settingsStatus.textContent = "Podaj haslo administratora.";
    return;
  }
  const previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Wczytywanie...";
  try {
    const payload = await loadSettingsSecrets(password);
    const value = secretValueByPath(payload, secretPath);
    if (!value) {
      settingsStatus.textContent = "Brak zapisanej wartosci albo nie mozna jej odczytac aktualnym APP_SECRET.";
      button.textContent = previousLabel;
      return;
    }
    input.value = value;
    if (originalType === "password") {
      input.type = "text";
    }
    input.dataset.secretVisible = "1";
    button.textContent = "Ukryj";
    clearSecretRevealTimer(input);
    secretRevealTimers.set(
      input,
      window.setTimeout(() => hideCredentialSecret(input, button, originalType), SECRET_REVEAL_MS)
    );
    settingsStatus.textContent = "Wczytano zapisana wartosc do pola na 60 s. Zapisz tylko wtedy, gdy chcesz ja utrwalic.";
  } catch (error) {
    settingsStatus.textContent = error.message || "Nie udalo sie wczytac zapisanej wartosci.";
    button.textContent = previousLabel;
  } finally {
    state.settingsSecrets = null;
    button.disabled = false;
  }
}

function selectField(name, label, value, choices) {
  const wrapper = document.createElement("label");
  const select = document.createElement("select");
  wrapper.textContent = label;
  select.name = name;
  for (const [choiceValue, choiceLabel] of choices) {
    const option = document.createElement("option");
    option.value = choiceValue;
    option.textContent = choiceLabel;
    option.selected = choiceValue === value;
    select.appendChild(option);
  }
  wrapper.appendChild(select);
  return wrapper;
}

function actionRow(...buttons) {
  const actions = document.createElement("div");
  actions.className = "settings-actions";
  actions.append(...buttons);
  return actions;
}

function formatDiagnosticResult(target, payload) {
  if (target === "local" && Array.isArray(payload.checks)) {
    const failed = payload.checks.filter((item) => !item.read || !item.write);
    if (!failed.length) {
      return "Foldery lokalne: odczyt i zapis dzialaja.";
    }
    return failed
      .map((item) => `${item.key}: ${item.error || "brak odczytu lub zapisu"} (${item.path})`)
      .join(" | ");
  }
  return payload.message || (payload.ok ? "Test zakonczony powodzeniem." : "Test nie powiodl sie.");
}

function diagnosticButton(target, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    settingsStatus.textContent = "Testowanie...";
    try {
      const payload = await requestJson(`/api/diagnostics/${target}`, { method: "POST" });
      settingsStatus.textContent = formatDiagnosticResult(target, payload);
    } catch (error) {
      settingsStatus.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function detectSqlColumnsButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Wykryj pola SQL";
  button.addEventListener("click", async () => {
    button.disabled = true;
    settingsStatus.textContent = "Wykrywanie pol SQL...";
    try {
      const payload = await requestJson("/api/settings/sql-columns/detect", {
        method: "POST",
        timeoutMs: 60000,
      });
      if (payload.settings) {
        state.settings = payload.settings;
        state.currentUser = state.settings.current_user || state.currentUser;
      } else if (Array.isArray(payload.columns)) {
        state.settings.sql_available_columns = payload.columns;
      }
      ensureSqlColumnsDatalist();
      renderSettings();
      settingsStatus.textContent = payload.message || "Wykryto pola SQL.";
    } catch (error) {
      settingsStatus.textContent = error.message || "Nie udalo sie wykryc pol SQL.";
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function fileIndexRefreshButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Odswiez indeks";
  button.addEventListener("click", async () => {
    button.disabled = true;
    settingsStatus.textContent = "Uruchamiam indeksowanie...";
    try {
      const payload = await requestJson("/api/file-index/refresh", { method: "POST" });
      state.fileIndex = payload;
      updateRuntimeMetrics();
      settingsStatus.textContent = payload.label || "Indeksowanie uruchomione.";
    } catch (error) {
      settingsStatus.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function repairSqliteDatabaseButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Napraw SQLite";
  button.addEventListener("click", async () => {
    if (!window.confirm("Utworzyc kopie i uruchomic naprawe aktywnej bazy SQLite?")) {
      return;
    }
    button.disabled = true;
    settingsStatus.textContent = "Naprawianie SQLite...";
    try {
      const payload = await requestJson("/api/settings/sqlite/repair", {
        method: "POST",
        timeoutMs: 120000,
      });
      if (payload.settings) {
        state.settings = payload.settings;
        renderSettings();
      }
      settingsStatus.textContent = payload.message || "Naprawa SQLite zakonczona.";
    } catch (error) {
      settingsStatus.textContent = error.message || "Nie udalo sie naprawic SQLite.";
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function manualSqliteBackupButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Utworz kopie SQLite";
  button.addEventListener("click", async () => {
    button.disabled = true;
    settingsStatus.textContent = "Tworzenie kopii SQLite...";
    try {
      const payload = await requestJson("/api/settings/sqlite/backup", {
        method: "POST",
        timeoutMs: 60000,
      });
      settingsStatus.textContent = `Utworzono kopie: ${payload.backup_path || "SQLite"}`;
      await loadSqliteBackups();
    } catch (error) {
      settingsStatus.textContent = error.message || "Nie udalo sie utworzyc kopii SQLite.";
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

async function loadSqliteBackups() {
  const payload = await requestJson("/api/settings/sqlite/backups");
  renderBackupHistory(payload.items || []);
  return payload.items || [];
}

function backupHistoryButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Historia wersji";
  button.addEventListener("click", async () => {
    button.disabled = true;
    settingsStatus.textContent = "Wczytywanie historii kopii...";
    try {
      await loadSqliteBackups();
      document.querySelector("#backupHistoryModal")?.classList.add("active");
      settingsStatus.textContent = "Wczytano historie kopii.";
    } catch (error) {
      settingsStatus.textContent = error.message || "Nie udalo sie wczytac historii kopii.";
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function sqliteBackupScheduleGrid(settings = {}) {
  const wrapper = document.createElement("div");
  const grid = document.createElement("div");
  const selectedSlots = new Set(settings.slots || []);
  if (!selectedSlots.size) {
    const selectedDays = new Set(settings.days || []);
    const selectedHours = new Set((settings.hours || []).map((hour) => Number(hour)));
    for (const day of selectedDays) {
      for (const hour of selectedHours) {
        selectedSlots.add(`${day}:${hour}`);
      }
    }
  }
  wrapper.className = "sqlite-backup-settings wide-field";
  wrapper.appendChild(
    checkField(
      "sqlite_backup_enabled",
      "Automatyczne kopie SQLite",
      settings.enabled,
      "Backend tworzy kopie w wybrane dni i godziny."
    )
  );
  grid.className = "sqlite-backup-grid";
  const corner = document.createElement("span");
  corner.textContent = "Dzien";
  grid.appendChild(corner);
  for (let hour = 0; hour < 24; hour += 1) {
    const label = document.createElement("span");
    label.textContent = String(hour).padStart(2, "0");
    grid.appendChild(label);
  }
  for (const [key, labelText] of SQLITE_BACKUP_DAYS) {
    const day = document.createElement("strong");
    day.textContent = labelText;
    grid.appendChild(day);
    for (let hour = 0; hour < 24; hour += 1) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "sqlite_backup_slot";
      input.value = `${key}:${hour}`;
      input.checked = selectedSlots.has(input.value);
      input.setAttribute("aria-label", `Kopia ${labelText} ${String(hour).padStart(2, "0")}:00`);
      label.title = `${labelText} ${String(hour).padStart(2, "0")}:00`;
      label.appendChild(input);
      grid.appendChild(label);
    }
  }
  wrapper.appendChild(grid);
  return wrapper;
}

function collectSqliteBackupSchedule(form) {
  const data = new FormData(form);
  const slots = [...form.querySelectorAll('[name="sqlite_backup_slot"]:checked')]
    .map((input) => input.value)
    .filter(Boolean);
  const days = [...new Set(slots.map((slot) => slot.split(":")[0]).filter(Boolean))];
  const hours = [
    ...new Set(
      slots
        .map((slot) => Number(slot.split(":")[1]))
        .filter((hour) => Number.isFinite(hour))
    ),
  ].sort((a, b) => a - b);
  return {
    enabled: data.has("sqlite_backup_enabled"),
    slots,
    days,
    hours,
    max_copies: Math.max(1, Math.min(999, Number(data.get("sqlite_backup_max_copies") || 10))),
    archive_dirs: String(data.get("sqlite_backup_archive_dirs") || "")
      .split(/\r?\n/)
      .map((path) => path.trim())
      .filter(Boolean),
  };
}

function backupItemLabel(item) {
  const parts = [formatPanelTimestamp(item.created_at)];
  if (item.reason) parts.push(item.reason);
  if (item.schema_version !== undefined && item.schema_version !== null) {
    parts.push(`schema ${item.schema_version}`);
  }
  parts.push(formatFileSize(item.size_bytes || 0));
  return parts.join(" | ");
}

function renderBackupHistory(items = []) {
  state.backupHistoryItems = Array.isArray(items) ? items : [];
  if (!backupHistoryOutput) {
    return;
  }
  backupHistoryOutput.textContent = "";
  if (!items.length) {
    backupHistoryOutput.className = "backup-history-output empty-state";
    backupHistoryOutput.textContent = "Brak kopii.";
    return;
  }
  backupHistoryOutput.className = "backup-history-output";
  for (const item of items) {
    const row = document.createElement("div");
    const details = document.createElement("div");
    const title = document.createElement("strong");
    const path = document.createElement("small");
    const actions = document.createElement("div");
    const diff = document.createElement("button");
    const restore = document.createElement("button");
    const backupPath = item.backup_path || "";
    row.className = "backup-history-row";
    title.textContent = backupItemLabel(item);
    path.textContent = backupPath;
    diff.type = "button";
    diff.className = "secondary-button";
    diff.textContent = "Porownaj";
    diff.disabled = !backupPath;
    diff.addEventListener("click", () => showSqliteBackupDiff(backupPath));
    restore.type = "button";
    restore.className = "danger-button";
    restore.textContent = "Przywroc";
    restore.disabled = !backupPath;
    restore.addEventListener("click", () => restoreSqliteBackup(backupPath));
    details.append(title, path);
    actions.className = "heading-actions";
    actions.append(diff, restore);
    row.append(details, actions);
    backupHistoryOutput.appendChild(row);
  }
}

async function restoreSqliteBackup(backupPath) {
  if (!backupPath) {
    return;
  }
  if (!window.confirm("Przywrocic aktywna baze SQLite z tej kopii? Przed przywroceniem zostanie utworzona kopia aktualnej bazy.")) {
    return;
  }
  settingsStatus.textContent = "Przywracanie kopii SQLite...";
  try {
    const payload = await requestJson("/api/settings/sqlite/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup_path: backupPath }),
      timeoutMs: 120000,
    });
    if (payload.settings) {
      state.settings = payload.settings;
      renderSettings();
    }
    await loadSqliteBackups();
    settingsStatus.textContent = `Przywrocono kopie: ${payload.restored_from || backupPath}`;
  } catch (error) {
    settingsStatus.textContent = error.message || "Nie udalo sie przywrocic kopii SQLite.";
  }
}

async function showSqliteBackupDiff(backupPath) {
  if (!backupPath || !backupDiffOutput) {
    return;
  }
  backupDiffOutput.className = "backup-diff-output empty-state";
  backupDiffOutput.textContent = "Porownywanie...";
  document.querySelector("#backupDiffModal")?.classList.add("active");
  try {
    const payload = await requestJson("/api/settings/sqlite/backup-diff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup_path: backupPath }),
      timeoutMs: 60000,
    });
    backupDiffOutput.textContent = "";
    backupDiffOutput.className = "backup-diff-output";
    for (const [table, counts] of Object.entries(payload.tables || {}).sort()) {
      const row = document.createElement("div");
      const name = document.createElement("strong");
      const values = document.createElement("span");
      row.className = "backup-diff-row";
      name.textContent = table;
      values.textContent =
        `aktywna: ${counts.active || 0}, kopia: ${counts.backup || 0}, ` +
        `dodane: ${counts.added || 0}, usuniete: ${counts.removed || 0}`;
      row.append(name, values);
      backupDiffOutput.appendChild(row);
    }
    const config = payload.config || {};
    const configRow = document.createElement("div");
    const configTitle = document.createElement("strong");
    const configValues = document.createElement("span");
    configRow.className = "backup-diff-row";
    configTitle.textContent = "Ustawienia";
    configValues.textContent =
      `dodane: ${(config.added || []).length}, usuniete: ${(config.removed || []).length}, ` +
      `zmienione: ${(config.changed || []).length}`;
    configRow.append(configTitle, configValues);
    backupDiffOutput.appendChild(configRow);
  } catch (error) {
    backupDiffOutput.className = "backup-diff-output empty-state";
    backupDiffOutput.textContent = error.message || "Nie udalo sie porownac kopii SQLite.";
  }
}

function ensureSqlColumnsDatalist() {
  let datalist = document.querySelector("#sqlColumnsList");
  if (!datalist) {
    datalist = document.createElement("datalist");
    datalist.id = "sqlColumnsList";
    document.body.appendChild(datalist);
  }
  datalist.textContent = "";
  for (const column of state.settings?.sql_available_columns || []) {
    const option = document.createElement("option");
    option.value = column;
    datalist.appendChild(option);
  }
}

function rerenderPanelTimestampViews() {
  updateRuntimeMetrics();
  if (state.githubStatus) renderGithubStatus(state.githubStatus);
  renderActiveUsersPresence({ enabled: state.activeUsersEnabled, users: state.activeUsers });
  if (state.history) renderHistory(state.history);
  if (
    state.historyDetailGroup &&
    document.querySelector("#historyDetailModal")?.classList.contains("active")
  ) {
    rerenderHistoryDetailTimestamps();
  }
  if (
    state.historyTimingItem &&
    document.querySelector("#historyTimingModal")?.classList.contains("active")
  ) {
    renderHistoryTiming(state.historyTimingItem, { open: false });
  }
  if (state.historyChangesItem && historyChangesModal?.classList.contains("active")) {
    renderHistoryChanges(state.historyChangesItem, { open: false });
  }
  if (
    Object.values(state.observability.tabs).some((tab) => Array.isArray(tab.items) && tab.items.length)
  ) {
    renderLogs();
  }
  renderResourceStatus(state.resources);
  rerenderCachedHealthDetails();
  if (state.backupHistoryItems.length) renderBackupHistory(state.backupHistoryItems);
  if (state.pimcoreHistoryItems.length) renderPimcoreHistory(state.pimcoreHistoryItems);
  renderPimcoreLiveEvents();
  const entraContainer = document.querySelector(".entra-expiry-status");
  if (entraContainer && state.entraExpiryStatus) {
    renderEntraExpiryStatus(entraContainer, state.entraExpiryStatus);
  }
}

function settingsSaveButton(form, buildPayload) {
  const actions = document.createElement("div");
  actions.className = "settings-actions";
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = "Zapisz ustawienia";
  actions.appendChild(button);
  form.appendChild(actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const previousBaseDir = state.settings?.base_dir || "";
    button.disabled = true;
    settingsStatus.textContent = "Zapisywanie...";
    try {
      state.settingsSecrets = null;
      state.settings = await requestJson("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload(new FormData(form))),
        timeoutMs: 60000,
      });
      if (state.settings.session_invalidated) {
        state.currentUser = null;
        updateAdminUi();
        settingsStatus.textContent =
          state.settings.session_message || "Zapisano. Zaloguj sie ponownie.";
        window.setTimeout(() => {
          window.location.href = "/login";
        }, 1500);
        return;
      }
      state.currentUser = state.settings.current_user || state.currentUser;
      state.defaultSlotFit = Boolean(state.settings.auto_content_fit);
      state.ftpEnabled = state.settings.ftp?.enabled !== false;
      state.processing = state.settings.processing || state.processing || {};
      state.security = state.settings.security || state.security || {};
      state.productFields = state.settings.product_fields || state.productFields || {};
      rerenderPanelTimestampViews();
      renderResourceStatus(state.resources);
      updateAdminUi();
      if (Array.isArray(state.settings.slots)) {
        renderSlots(state.settings.slots);
      }
      applyProductFieldLabels();
      let saveMessage = "Zapisano.";
      if (previousBaseDir && state.settings.base_dir !== previousBaseDir) {
        try {
          await loadBootstrap({ timeoutMs: 60000 });
          saveMessage = `Zapisano. Aktywny katalog bazowy: ${state.settings.base_dir}`;
        } catch (error) {
          saveMessage =
            `Zapisano katalog bazowy: ${state.settings.base_dir}. ` +
            `Nie udalo sie odswiezyc danych po zapisie: ${error.message || error}`;
        }
      }
      renderSettings();
      settingsStatus.textContent = saveMessage;
    } catch (error) {
      settingsStatus.textContent = error.message || "Nie udalo sie zapisac ustawien.";
    } finally {
      button.disabled = false;
    }
  });
}

function renderSettingsApp() {
  const s = state.settings;
  const form = document.createElement("form");
  form.className = "settings-form";
  const configNote = document.createElement("p");
  configNote.className = "settings-note wide-field";
  configNote.textContent =
    `Panel webowy uzywa tej samej lokalizacji i config.json co lokalna aplikacja uruchomiona na backendzie. local_settings.json: ${
      s.local_settings_path || "nieznany"
    }`;
  const runtimeWarning = document.createElement("p");
  runtimeWarning.className = "settings-note wide-field";
  runtimeWarning.textContent = s.runtime_warning ? `Ostrzezenie runtime: ${s.runtime_warning}` : "";
  const versionNote = document.createElement("p");
  versionNote.className = "settings-note wide-field";
  versionNote.textContent = `Wersja programu: ${s.version || "dev"}`;
  const productFieldsNote = document.createElement("p");
  productFieldsNote.className = "settings-note wide-field";
  productFieldsNote.textContent =
    "Pusta nazwa zachowuje etykiete domyslna. Wylaczone pola sa pomijane przy zapisie i przetwarzaniu.";
  form.append(
    settingsFieldGroup("Runtime aplikacji",
      versionNote,
      configNote,
      runtimeWarning,
      selectField("data_mode", "Tryb danych", s.data_mode || "legacy", [
        ["legacy", "Pliki legacy"],
        ["sqlite", "SQLite"],
      ]),
      inputField("image_dir", "Lokalizacja zdjec", s.image_dir || s.base_dir, {
        placeholder: "np. C:\\PicSyncra albo \\\\SERWER\\Udzial\\Zdjecia",
        description:
          "Folder, w ktorym backend trzyma zdjecia i cache podgladow. " +
          "Dla uslugi Windows najlepiej uzywac pelnej sciezki lokalnej albo UNC; dyski mapowane typu Z:\\ moga nie byc widoczne.",
      }),
      selectField("database_location_mode", "Lokalizacja SQLite", s.database_location_mode || "image_dir", [
        ["image_dir", "Przy zdjeciach"],
        ["custom", "Wskazana sciezka"],
        ["exe_dir", "Przy backendzie"],
      ]),
      inputField("database_path", "Plik SQLite", s.database_path || "", {
        placeholder: "np. C:\\PicSyncra\\picsyncra.sqlite",
        description: "Uzywane tylko dla lokalizacji: wskazana sciezka.",
      }),
      actionRow(
        repairSqliteDatabaseButton(),
        manualSqliteBackupButton(),
        backupHistoryButton()
      )
    ),
    settingsFieldGroup("Kopie zapasowe SQLite",
      sqliteBackupScheduleGrid(s.sqlite_backup || {}),
      inputField("sqlite_backup_max_copies", "Maksymalna liczba kopii", s.sqlite_backup?.max_copies || 10, {
        type: "number",
        min: 1,
        max: 999,
      }),
      inputField(
        "sqlite_backup_archive_dirs",
        "Dodatkowe katalogi archiwalnych kopii",
        (s.sqlite_backup?.archive_dirs || []).join("\n"),
        {
          textarea: true,
          placeholder: "np. D:\\Archiwum\\PicSyncraBACKUP",
          description: "Po jednej zaufanej lokalizacji w wierszu. Nowe kopie nadal trafiaja do domyslnego BACKUP.",
        }
      )
    ),
    settingsFieldGroup("Indeks lokalny",
      checkField(
        "local_file_index",
        "Indeks plikow lokalnych",
        s.local_file_index,
        "Backend sprawdza lokalne pliki przy wczytywaniu statusow slotow."
      ),
      actionRow(diagnosticButton("local", "Test folderow backendu"), fileIndexRefreshButton())
    ),
    settingsFieldGroup("Widok panelu",
      panelTimeZoneField(s.web_display?.time_zone || "UTC"),
      checkField(
        "user_show_timing_details",
        "Pokazuj blok Pomiary",
        showTimingDetails(),
        "Ustawienie tylko dla aktualnego uzytkownika. Pokazuje lub ukrywa blok Pomiary z czasami kolejki i operacji."
      )
    ),
    settingsFieldGroup("Pola produktu",
      productFieldsNote,
      productFieldSettingsList(s.product_fields || {})
    )
  );
  settingsSaveButton(form, (data) => ({
    app: {
      image_dir: data.get("image_dir"),
      data_mode: data.get("data_mode"),
      database_location_mode: data.get("database_location_mode"),
      database_path: data.get("database_path"),
      local_file_index: data.has("local_file_index"),
      product_fields: collectProductFieldSettings(data),
    },
    sqlite_backup: collectSqliteBackupSchedule(form),
    web_display: {
      time_zone: data.get("web_display_time_zone"),
    },
  }));
  form.addEventListener("submit", () => {
    const data = new FormData(form);
    setTimingDetailsVisible(data.has("user_show_timing_details"));
  });
  settingsOutput.appendChild(form);
}

function renderSettingsProcessing() {
  const p = state.settings.processing || {};
  const formats = state.settings.processing_formats?.length
    ? state.settings.processing_formats
    : ["JPG", "PNG", "WEBP", "BMP", "GIF", "TIFF"];
  const form = document.createElement("form");
  form.className = "settings-form";
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent =
    "Te ustawienia sa stosowane przy zapisie z panelu webowego. FIT w slocie nadal moze byc wlaczany osobno dla pojedynczego zdjecia.";
  form.append(
    note,
    settingsFieldGroup("FIT slotu",
      checkField(
        "auto_content_fit",
        "FIT domyslnie dla kazdego slotu",
        state.settings.auto_content_fit,
        "Nowe i wczytane sloty startuja z wlaczonym FIT, ale pojedynczy slot nadal mozna przelaczyc."
      )
    ),
    settingsFieldGroup("Przetwarzanie uploadu",
      selectField(
        "upload_processing_mode",
        "Kiedy przetwarzac obrazy",
        p.upload_processing_mode || "save",
        [
          ["save", "Host przy zapisie"],
          ["host", "Host przy uploadzie do cache"],
          ["client", "Klient przed uploadem"],
        ]
      )
    ),
    settingsFieldGroup("Zmniejszanie obrazu",
      checkField(
        "resize_enabled",
        "Wlacz zmniejszanie",
        p.resize_enabled,
        "Najdluzszy bok obrazu zostanie ograniczony do podanej liczby pikseli."
      ),
      inputField("max_dim", "Maksymalny bok (px)", p.max_dim || 2000, {
        type: "number",
        min: 64,
        max: 20000,
      })
    ),
    settingsFieldGroup("Kompresja JPG/WEBP",
      checkField(
        "compress_enabled",
        "Wlacz kompresje",
        p.compress_enabled,
        "Uzywa podanej jakosci przy zapisie stratnych formatow."
      ),
      inputField("compress_quality", "Jakosc (%)", p.compress_quality || 85, {
        type: "number",
        min: 1,
        max: 100,
      })
    ),
    settingsFieldGroup("Limit rozmiaru pliku",
      checkField(
        "max_size_enabled",
        "Wlacz limit rozmiaru",
        p.max_size_enabled,
        "Dla JPG/WEBP jakosc jest obnizana stopniowo, az plik miesci sie w limicie."
      ),
      inputField("max_file_kb", "Maksymalny rozmiar (KB)", p.max_file_kb || 500, {
        type: "number",
        min: 1,
        max: 102400,
      })
    ),
    settingsFieldGroup("Konwersja formatu",
      checkField(
        "convert_enabled",
        "Wlacz konwersje",
        p.convert_enabled,
        "Obrazy sa zapisywane w wybranym formacie zamiast w formacie zrodlowym."
      ),
      selectField(
        "target_format",
        "Format docelowy",
        p.target_format || "PNG",
        formats.map((format) => [format, format])
      )
    )
  );
  settingsSaveButton(form, (data) => ({
    app: {
      auto_content_fit: data.has("auto_content_fit"),
    },
    processing: {
      resize_enabled: data.has("resize_enabled"),
      max_dim: data.get("max_dim"),
      compress_enabled: data.has("compress_enabled"),
      compress_quality: data.get("compress_quality"),
      max_size_enabled: data.has("max_size_enabled"),
      max_file_kb: data.get("max_file_kb"),
      convert_enabled: data.has("convert_enabled"),
      target_format: data.get("target_format"),
      upload_processing_mode: data.get("upload_processing_mode"),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsSecurity() {
  const security = state.settings.security || {};
  const form = document.createElement("form");
  form.className = "settings-form";
  const secretHint = document.createElement("p");
  secretHint.className = "settings-note";
  secretHint.textContent =
    "APP_SECRET sluzy do odczytu zaszyfrowanych hasel z config.json. " +
    "Przy podpinaniu istniejacego katalogu wpisz sekret uzyty przy jego konfiguracji; puste pole niczego nie zmienia.";
  form.append(
    settingsFieldGroup("Sekret aplikacji",
      secretHint,
      credentialField("app_secret", "APP_SECRET", state.settings.app_secret_set, {
        type: "password",
        secretPath: "app_secret",
      })
    ),
    settingsFieldGroup("Limity uploadu",
      inputField("max_upload_mb", "Maksymalny upload (MB)", security.max_upload_mb || 50, {
        type: "number",
        min: 1,
        max: 2048,
        description: "Backend przerwie zapis i usunie czesciowy plik po przekroczeniu limitu.",
      }),
      inputField(
        "max_upload_pixels",
        "Maksymalna liczba pikseli",
        security.max_upload_pixels || 25000000,
        {
          type: "number",
          min: 1,
          max: 400000000,
          step: 100000,
          description: "Dotyczy obrazow z uploadu, cache, rozszerzenia i importu z URL.",
        }
      )
    ),
    settingsFieldGroup("Typy plikow uploadu",
      inputField(
        "allowed_upload_extensions",
        "Akceptowane rozszerzenia",
        extensionListText(security.allowed_upload_extensions),
        {
          textarea: true,
          description:
            "Lista po przecinku. Gdy ma wpisy, wszystko spoza niej jest odrzucane. " +
            "Pusta lista wylacza allow-liste, ale nadal dzialaja blokady ponizej.",
        }
      ),
      inputField(
        "blocked_upload_extensions",
        "Zabronione rozszerzenia",
        extensionListText(security.blocked_upload_extensions),
        {
          textarea: true,
          description: "Lista po przecinku. Te typy sa odrzucane niezaleznie od listy akceptowanych.",
        }
      ),
      checkField(
        "block_executable_uploads",
        "Blokuj pliki wykonywalne",
        security.block_executable_uploads !== false,
        "Odrzuca m.in. exe, bat, cmd, msi, ps1, vbs, js, jar, dll, scr, sh."
      ),
      checkField(
        "antivirus_scan_uploads",
        "Skanuj upload Microsoft Defender",
        Boolean(security.antivirus_scan_uploads),
        "Dotyczy tylko plikow wysylanych przez panel lub rozszerzenie; pliki juz lokalne i pobrane z FTP nie sa ponownie skanowane."
      ),
      checkField(
        "show_active_web_users",
        "Pokaz aktywnych uzytkownikow",
        Boolean(security.show_active_web_users),
        "Uzytkownicy zobacza nazwy kont obecnie aktywnych w panelu WWW."
      )
    )
  );
  settingsSaveButton(form, (data) => ({
    security: {
      app_secret: data.get("app_secret"),
      max_upload_mb: data.get("max_upload_mb"),
      max_upload_pixels: data.get("max_upload_pixels"),
      allowed_upload_extensions: data.get("allowed_upload_extensions"),
      blocked_upload_extensions: data.get("blocked_upload_extensions"),
      block_executable_uploads: data.has("block_executable_uploads"),
      antivirus_scan_uploads: data.has("antivirus_scan_uploads"),
      show_active_web_users: data.has("show_active_web_users"),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsFtp() {
  const ftp = state.settings.ftp;
  const form = document.createElement("form");
  form.className = "settings-form";
  form.append(
    settingsFieldGroup("Polaczenie FTP",
      checkField(
        "enabled",
        "Aktualizacja FTP",
        ftp.enabled,
        "Po zapisie backend bedzie wysylal przetworzone pliki na FTP."
      ),
      inputField("host", "Host", ftp.host),
      inputField("port", "Port", ftp.port, { type: "number" }),
      inputField("path", "Sciezka", ftp.path),
      actionRow(diagnosticButton("ftp", "Test FTP"))
    ),
    settingsFieldGroup("Dane logowania FTP",
      credentialField("user", "Uzytkownik", ftp.user_set, { secretPath: "ftp.user" }),
      credentialField("password", "Haslo", ftp.password_set, {
        type: "password",
        secretPath: "ftp.password",
      })
    )
  );
  settingsSaveButton(form, (data) => ({
    ftp: {
      enabled: data.has("enabled"),
      host: data.get("host"),
      port: data.get("port"),
      path: data.get("path"),
      user: data.get("user"),
      password: data.get("password"),
    },
  }));
  settingsOutput.appendChild(form);
}

function sqlPlaceholderHelp(items = []) {
  const wrapper = document.createElement("div");
  wrapper.className = "settings-note sql-placeholder-help";
  wrapper.append("Dostepne placeholdery SQL: ");
  for (const [token, label] of items) {
    const code = document.createElement("code");
    code.textContent = token;
    wrapper.append(code, ` ${label}; `);
  }
  return wrapper;
}

function sqlProfileRow(profile = {}) {
  const row = document.createElement("div");
  row.className = "sql-profile-card sql-profile-row";
  row.dataset.profileId = profile.id || "";
  row.append(
    inputField("profile_label", "Nazwa profilu", profile.label || ""),
    selectField("profile_type", "Typ bazy", profile.type || "mysql", [
      ["mysql", "MySQL"],
      ["mssql", "MS SQL"],
    ]),
    inputField("profile_host", "Serwer", profile.host || ""),
    inputField("profile_database", "Baza", profile.database || ""),
    credentialField("profile_user", "Uzytkownik", profile.user_set, {
      secretPath: `database.profiles.${profile.id}.user`,
    }),
    credentialField("profile_password", "Haslo", profile.password_set, {
      type: "password",
      secretPath: `database.profiles.${profile.id}.password`,
    }),
    checkField("profile_enabled", "Aktywny", profile.enabled !== false)
  );
  if (profile.locked) {
    row.querySelectorAll("input, select").forEach((field) => {
      field.disabled = true;
    });
  }
  const test = document.createElement("button");
  test.type = "button";
  test.className = "secondary-button";
  test.textContent = "Test profilu";
  test.addEventListener("click", async () => {
    test.disabled = true;
    try {
      const result = await requestJson(
        `/api/settings/sql-profiles/${encodeURIComponent(profile.id || "")}/test`,
        { method: "POST" }
      );
      settingsStatus.textContent = result.message || "";
    } catch (error) {
      settingsStatus.textContent = error.message;
    } finally {
      test.disabled = false;
    }
  });
  row.appendChild(test);
  if (!profile.locked) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ghost-button";
    remove.textContent = "Usun";
    remove.addEventListener("click", () => row.remove());
    row.appendChild(remove);
  }
  return row;
}

function collectSqlProfiles(form) {
  return Array.from(form.querySelectorAll(".sql-profile-row"))
    .filter((row) => row.dataset.profileId !== "default")
    .map((row) => ({
      id: row.dataset.profileId || row.querySelector('[name="profile_label"]').value,
      label: row.querySelector('[name="profile_label"]').value,
      type: row.querySelector('[name="profile_type"]').value,
      host: row.querySelector('[name="profile_host"]').value,
      database: row.querySelector('[name="profile_database"]').value,
      user: row.querySelector('[name="profile_user"]').value,
      password: row.querySelector('[name="profile_password"]').value,
      enabled: row.querySelector('[name="profile_enabled"]').checked,
    }));
}

function renderSettingsSql() {
  const db = state.settings.database;
  const form = document.createElement("form");
  const profiles = document.createElement("div");
  const addProfile = document.createElement("button");
  const placeholderItems = [
    ["{ean}", "EAN aktualnego produktu"],
    ["{filename}", "Nazwa wygenerowanego pliku"],
    ["{col}", "Kolumna SQL przypisana do slotu"],
    ["{column}", "Alias dla {col}"],
  ];
  profiles.className = "sql-profile-list wide-field";
  for (const profile of additionalSqlProfiles(db)) {
    profiles.appendChild(sqlProfileRow(profile));
  }
  addProfile.type = "button";
  addProfile.className = "secondary-button";
  addProfile.textContent = "Dodaj profil Pimcore SQL";
  addProfile.addEventListener("click", () => {
    profiles.appendChild(
      sqlProfileRow({
        id: `profile-${Date.now()}`,
        label: "Nowy profil",
        type: "mysql",
        enabled: true,
      })
    );
  });
  form.className = "settings-form";
  form.append(
    settingsFieldGroup("Tryb SQL",
      selectField("type", "Typ bazy", db.type, [["mysql", "MySQL"], ["mssql", "MS SQL"]]),
      checkField(
        "sql_update_enabled",
        "Aktualizacja SQL",
        db.sql_update_enabled,
        "Backend bedzie aktualizowal pola SQL przypisane w zakladce Sloty."
      ),
      inputField("query", "Zapytanie SQL", db.query, { textarea: true }),
      sqlPlaceholderHelp(placeholderItems),
      actionRow(diagnosticButton("sql", "Test SQL")),
      settingsNote("Domyslne polaczenie dla zdjec i slotow."),
      inputField("mssql_server", "MS SQL server", db.mssql.server),
      inputField("mssql_database", "MS SQL database", db.mssql.database),
      credentialField("mssql_user", "MS SQL user", db.mssql.user_set, {
        secretPath: "database.mssql.user",
      }),
      credentialField("mssql_password", "MS SQL haslo", db.mssql.password_set, {
        type: "password",
        secretPath: "database.mssql.password",
      }),
      inputField("mysql_server", "MySQL server", db.mysql.server),
      inputField("mysql_database", "MySQL database", db.mysql.database),
      credentialField("mysql_user", "MySQL user", db.mysql.user_set, {
        secretPath: "database.mysql.user",
      }),
      credentialField("mysql_password", "MySQL haslo", db.mysql.password_set, {
        type: "password",
        secretPath: "database.mysql.password",
      })
    ),
    settingsFieldGroup("Profile dodatkowe SQL",
      settingsNote("Niezalezne profile uzywane tylko po wybraniu w builderze wartosci pola Pimcore."),
      profiles,
      actionRow(addProfile)
    )
  );
  settingsSaveButton(form, (data) => ({
    database: {
      type: data.get("type"),
      sql_update_enabled: data.has("sql_update_enabled"),
      query: data.get("query"),
      mssql: {
        server: data.get("mssql_server"),
        database: data.get("mssql_database"),
        user: data.get("mssql_user"),
        password: data.get("mssql_password"),
      },
      mysql: {
        server: data.get("mysql_server"),
        database: data.get("mysql_database"),
        user: data.get("mysql_user"),
        password: data.get("mysql_password"),
      },
      profiles: collectSqlProfiles(form),
    },
  }));
  settingsOutput.appendChild(form);
}

const PIMCORE_TEMPLATE_PRODUCT_SOURCES = [
  ["Nazwa", "PRODUCT:name"],
  ["Typ", "PRODUCT:type"],
  ["Model", "PRODUCT:model"],
  ["Kolor 1", "PRODUCT:color1"],
  ["Kolor 2", "PRODUCT:color2"],
  ["Kolor 3", "PRODUCT:color3"],
  ["Dodatek", "PRODUCT:extra"],
  ["EAN", "PRODUCT:ean"],
];

const PIMCORE_TEMPLATE_FUNCTIONS = [
  ["Bez zmiany", "|keep"],
  ["Przytnij spacje", "|trim"],
  ["Ujednolic spacje", "|normalize_spaces"],
  ["WIELKIE LITERY", "|upper"],
  ["male litery", "|lower"],
  ["Kazde Slowo", "|title"],
  ["Pierwsza litera", "|capitalize"],
  ["Bez polskich znakow", "|strip_diacritics"],
  ["Slug", "|slug"],
  ["Zamien tekst", '|replace:"stary","nowy"'],
  ["Wartosc awaryjna", '|default:"brak"'],
  ["Fragment", "|substring:0,10"],
  ["Skroc", '|truncate:30,"..."'],
  ["Liczba", '|number:2,","," "'],
  ["Wypelnione (1/0)", "|filled"],
  ["Ktorekolwiek wypelnione (1/0)", '|any_filled:"PIMCORE:inne_pole"'],
  ["Policz wypelnione", '|count_filled:"PIMCORE:inne_pole"'],
  ["Warunek wypelnienia", '|if_filled:"TAK","NIE"'],
];

const PIMCORE_TEMPLATE_MATH_TOKENS = [
  ["Oblicz", "oblicz()"],
  ["Dodaj", "+"],
  ["Odejmij", "-"],
  ["Mnoz", "*"],
  ["Dziel", "/"],
];

const TEMPLATE_FUNCTION_HELP = [
  ["Podstawy", "Placeholder", "{NAZWA}", "Placeholder pobiera wartosc jednego pola. Wpisz go w nawiasach klamrowych; nie wpisuj wartosci recznie w miejsce nazwy pola.", [["Rozny zapis nazwy", "{NAZWA} / {Nazwa} / {nazwa}", "Ten sam tekst zostanie zwrocony wielkimi literami, z pierwsza wielka litera albo malymi literami."], ["Pole Pimcore", "{PIMCORE:parcel_1_width|keep}", "Wstawia szerokosc pierwszej paczki bez zmiany zapisu."]]],
  ["Podstawy", "Grupa warunkowa (...)", "({MODEL})", "Grupa jest przydatna dla dodatku, ktory ma zniknac razem ze znakiem obok. Gdy ktorykolwiek placeholder wewnatrz jest pusty, cala grupa nie pojawi sie w wyniku.", [["Model opcjonalny", "{NAZWA}( - {MODEL|trim})", "Dla pustego modelu zostanie tylko nazwa; myslnik nie zostanie sam."], ["Dwa kolory", "{KOLOR 1}( / {KOLOR 2})", "Drugi kolor i ukosnik pojawia sie tylko wtedy, gdy drugi kolor istnieje."]]],
  ["Podstawy", "oblicz / calc", "oblicz(wyrazenie)", "Liczy dzialania na liczbach: +, -, * i /. W srodku uzywaj tylko liczb, nawiasow i pol zawierajacych liczby; tekst nie moze byc liczony.", [["Proste dodawanie", "oblicz({PIMCORE:parcel_1_weight|keep}+{PIMCORE:parcel_2_weight|keep})", "Dodaje dwie wagi."], ["Nawiasy i mnozenie", "calc(({PIMCORE:A|keep}+{PIMCORE:B|keep})*4)", "Najpierw dodaje A i B, potem mnozy wynik przez 4."]]],
  ["Podstawy", "SQL", "{SQL|keep}", "SQL nie jest zwyklym tekstem. Dziala tylko w mapowaniu, dla ktorego skonfigurowano zapytanie SQL i profil; do wyniku trafia pierwsza wartosc zwrocona przez zapytanie.", [["Wstawienie wyniku", "Kod: {SQL|keep}", "Dopisuje wynik SQL za etykieta Kod:."], ["Wartosc awaryjna", '{SQL|trim|default:"brak danych"}', "Gdy zapytanie zwroci pusty tekst, pokazuje brak danych."]]],
  ["Tekst", "keep", "|keep", "keep oznacza: zostaw wartosc dokladnie tak, jak przyszla. Uzyj go, gdy nie chcesz automatycznej zmiany wielkosci liter.", [["Kod", "{PIMCORE:CN_Code|keep}", "Kod AB-12 pozostanie AB-12."], ["Model", "Model: {MODEL|keep}", "Wstawia model bez formatowania."]]],
  ["Tekst", "trim", "|trim", "trim usuwa spacje tylko z poczatku i konca. Nie usuwa spacji pomiedzy wyrazami.", [["Czyszczenie modelu", "{MODEL|trim}", "Wartosc '  M-20  ' staje sie 'M-20'."], ["Z wartoscia awaryjna", '{MODEL|trim|default:"brak modelu"}', "Puste lub same spacje dadza brak modelu."]]],
  ["Tekst", "normalize_spaces", "|normalize_spaces", "Zamienia kilka kolejnych spacji, tabulatory i nowe linie na jedna spacje. Przydaje sie po danych wklejonych z roznych zrodel.", [["Nazwa", "{NAZWA|normalize_spaces}", "'Stol   dębowy' staje sie 'Stol dębowy'."], ["Z wielkimi literami", "{NAZWA|normalize_spaces|upper}", "Najpierw porzadkuje odstepy, potem zmienia litery."]]],
  ["Tekst", "upper", "|upper", "upper zamienia wszystkie litery na WIELKIE. Cyfry, spacje i znaki specjalne pozostaja bez zmian.", [["Kod wielkimi literami", "{MODEL|trim|upper}", "Wartosc 'm-20' staje sie 'M-20'."], ["Nazwa produktu", "{NAZWA|upper}", "Wartosc 'Stol debowy' staje sie 'STOL DEBOWY'."]]],
  ["Tekst", "lower", "|lower", "lower zamienia wszystkie litery na male. Uzyj go, gdy dane maja byc zawsze zapisywane jednym, malym formatem.", [["Kod malymi literami", "{MODEL|lower}", "Wartosc 'M-20' staje sie 'm-20'."], ["Adres e-mail", "{EMAIL|trim|lower}", "Wartosc ' BIURO@FIRMA.PL ' staje sie 'biuro@firma.pl'."]]],
  ["Tekst", "title", "|title", "title ustawia pierwsza litere kazdego slowa jako wielka, a pozostale jako male. Najlepiej sprawdza sie przy nazwach i opisach, nie przy kodach technicznych.", [["Nazwa produktu", "{NAZWA|title}", "Wartosc 'STOL DEBOWY' staje sie 'Stol Debowy'."], ["Po uporzadkowaniu spacji", "{NAZWA|normalize_spaces|title}", "Wartosc '  krzeslo   biurowe ' staje sie 'Krzeslo Biurowe'."]]],
  ["Tekst", "capitalize", "|capitalize", "capitalize ustawia wielka tylko pierwsza litere calej wartosci, a wszystkie pozostale litery zmienia na male. Rozni sie od title, ktore poprawia kazde slowo.", [["Jeden opis", "{OPIS|capitalize}", "Wartosc 'NOWA DOSTAWA' staje sie 'Nowa dostawa'."], ["Po oczyszczeniu", "{MODEL|trim|capitalize}", "Wartosc '  mODEL TEST  ' staje sie 'Model test'."]]],
  ["Tekst", "replace", '|replace:"stary","nowy"', "replace zamienia doslownie jeden fragment tekstu na drugi. Pierwszy argument to szukany tekst, drugi to jego zastepstwo; oba wpisuj w cudzyslowach.", [["Podkreslnik na spacje", '{MODEL|replace:"_"," "}', "'M_20' staje sie 'M 20'."], ["Usuniecie tekstu", '{MODEL|replace:"-OLD",""}', "Usuwa koncowke -OLD z modelu."]]],
  ["Tekst", "default", '|default:"wartosc"', "default daje wartosc zapasowa tylko wtedy, gdy pole jest puste. Gdy pole ma dane, zwraca jego prawdziwa wartosc i ignoruje zapas.", [["Brak modelu", '{MODEL|default:"brak"}', "Pusty model wyswietli brak."], ["Slug z zapasem", '{MODEL|trim|default:"produkt"|slug}', "Pusty model da produkt, a nie pusty wynik."]]],
  ["Tekst", "substring", "|substring:poczatek,dlugosc", "substring wycina fragment tekstu. Pierwsza liczba zaczyna liczenie od zera, a druga okresla liczbe znakow; druga jest opcjonalna.", [["Pierwsze 8 znakow", "{MODEL|substring:0,8}", "Z M-123456789 zostawi M-123456."], ["Od trzeciego znaku", "{MODEL|substring:2}", "Z AB-123 zostawi -123."]]],
  ["Tekst", "truncate", '|truncate:dlugosc,"dopisek"', "truncate skroci tekst tylko wtedy, gdy jest za dlugi. Opcjonalny dopisek, np. ..., jest doklejany po obcietej wartosci.", [["Krotka nazwa", "{NAZWA|truncate:20}", "Tekst dluzszy niz 20 znakow zostanie obciety."], ["Kropki po skroceniu", '{NAZWA|truncate:20,"..."}', "Po obcietej nazwie pojawia sie ... ."]]],
  ["Tekst", "strip_diacritics", "|strip_diacritics", "Usuwa polskie znaki i inne znaki diakrytyczne, ale nie zmienia pozostalej tresci. Jest dobry, gdy system docelowy nie akceptuje znakow narodowych.", [["Polskie znaki", "{NAZWA|strip_diacritics}", "'żółć' staje sie 'zolc'."], ["Z kodem", "{MODEL|trim|strip_diacritics|upper}", "Najpierw czysci spacje i znaki, potem daje wielkie litery."]]],
  ["Tekst", "slug", "|slug", "slug tworzy bezpieczny tekst malymi literami, ze slowami polaczonymi myslnikami. Usuwa znaki specjalne, wiec nadaje sie np. na fragment adresu lub klucza.", [["Nazwa produktu", "{NAZWA|slug}", "'Stol Dębowy 120 cm' staje sie 'stol-debowy-120-cm'."], ["Wartosc awaryjna", '{MODEL|default:"produkt"|slug}', "Pusty model daje bezpieczne produkt."]]],
  ["Tekst", "number", '|number:miejsca,"przecinek","tysiace"', "number formatuje liczbe do czytelnej postaci. Podaj kolejno liczbe miejsc po przecinku, separator dziesietny i opcjonalny separator tysiecy.", [["Cena PL", '{PIMCORE:CENA|number:2,","," "}', "1234,5 staje sie 1 234,50."], ["Liczba calkowita", '{PIMCORE:SZTUKI|number:0,"."," "}', "12500 staje sie 12 500."]]],
  ["Paczki i warunki", "filled", "|filled", "filled zwraca 1, gdy pole ma jakakolwiek wartosc, albo 0, gdy jest puste. To nie zwraca szerokosci; jest przeznaczone do liczenia wpisanych paczek.", [["Jedna paczka", "{PIMCORE:parcel_1_width|filled}", "Wpisane 120 daje 1, puste pole daje 0."], ["Suma paczek", "{PIMCORE:parcel_1_width|filled}+{PIMCORE:parcel_2_width|filled}", "Dwie wpisane szerokosci dadza 2."]]],
  ["Paczki i warunki", "any_filled", '|any_filled:"PIMCORE:inne_pole"', "any_filled zwraca 1, gdy biezace pole albo przynajmniej jedno wskazane dodatkowe pole ma dane. Nazwy dodatkowych pol wpisuj w cudzyslowach.", [["Dowolny wymiar", '{PIMCORE:parcel_1_depth|any_filled:"PIMCORE:parcel_1_height","PIMCORE:parcel_1_width"}', "Sama wysokosc lub sama szerokosc wystarczy, aby wynik byl 1."], ["Stan danych", '{PIMCORE:EAN|any_filled:"PIMCORE:CN_Code"}', "Zwraca 1, gdy istnieje EAN albo kod CN."]]],
  ["Paczki i warunki", "count_filled", '|count_filled:"PIMCORE:inne_pole"', "count_filled liczy, ile pol jest naprawde wypelnionych. W przeciwienstwie do any_filled wynik moze byc 0, 1, 2 i wiecej.", [["Kompletnosc wymiarow", '{PIMCORE:parcel_1_depth|count_filled:"PIMCORE:parcel_1_height","PIMCORE:parcel_1_width"}', "Trzy wypelnione wymiary dadza 3."], ["Dwa identyfikatory", '{PIMCORE:EAN|count_filled:"PIMCORE:CN_Code"}', "Gdy oba istnieja, wynik to 2."]]],
  ["Paczki i warunki", "if_filled", '|if_filled:"gdy jest","gdy brak"', "if_filled wybiera jeden z dwoch tekstow. Pierwszy pojawia sie dla wypelnionego pola, drugi dla pustego; oba teksty wpisuj w cudzyslowach.", [["Prosty status", '{PIMCORE:parcel_1_width|if_filled:"JEST PACZKA","BRAK PACZKI"}', "Pokazuje czy paczka ma szerokosc."], ["Etykieta CN", '{PIMCORE:CN_Code|if_filled:"kod CN podany","kod CN brak"}', "Daje czytelny komunikat zamiast surowej wartosci."]]],
];

function pimcoreFieldLanguage(value = {}) {
  return String(value?.language || "").trim();
}

function pimcoreFieldSource(name, language) {
  const fieldName = String(name || "").trim();
  const fieldLanguage = String(language || "").trim();
  if (!fieldName || !fieldLanguage) return fieldName;
  const suffix = `_${fieldLanguage.toUpperCase()}`;
  return fieldName.toUpperCase().endsWith(suffix) ? fieldName : `${fieldName}${suffix}`;
}

function pimcoreFieldOptionText(field = {}) {
  const language = pimcoreFieldLanguage(field);
  const label = field.label || field.name || "";
  const localized =
    language && !String(label).includes(`[${language}]`) ? ` [${language}]` : "";
  return `${label}${localized} - ${field.type || "input"}`;
}

function pimcoreFieldsMatch(field = {}, mapping = {}) {
  return (
    String(field.name || "") === String(mapping.pimcore_field || "") &&
    pimcoreFieldLanguage(field) === pimcoreFieldLanguage(mapping)
  );
}

function pimcoreSelectedMappingSource(select) {
  const option = select?.selectedOptions?.[0];
  return pimcoreFieldSource(select?.value || "", option?.dataset.language || "");
}

function pimcoreTemplateLanguageForRow(row) {
  if (!row) return "";
  if (row.classList.contains("pimcore-setup-field-row")) {
    return row.dataset.fieldLanguage || "";
  }
  if (row.classList.contains("pimcore-simple-mapping-row")) {
    return row.querySelector('[name="mapping_target"]')?.selectedOptions[0]?.dataset.language || "";
  }
  return row.querySelector('[name="mapping_language"]')?.value.trim() || "";
}

function pimcoreTemplateBuilderButton(row) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost-button pimcore-template-button";
  button.textContent = "Konstruuj";
  button.addEventListener("click", () => openPimcoreTemplateBuilder(row));
  return button;
}

function pimcoreTemplateFieldType(row) {
  if (row.classList.contains("pimcore-setup-field-row")) {
    return row.dataset.fieldType || "input";
  }
  if (row.classList.contains("pimcore-simple-mapping-row")) {
    return row.querySelector('[name="mapping_target"]')?.selectedOptions[0]?.dataset.type || "input";
  }
  return row.querySelector('[name="mapping_type"]')?.value || "input";
}

function updatePimcoreTemplateButton(row) {
  const button = row.querySelector(".pimcore-template-button");
  if (!button) return;
  const supported = ["input", "textarea", "select"].includes(pimcoreTemplateFieldType(row));
  button.disabled = !supported;
  button.textContent = pimcoreRowHasRuntimeTemplate(row) ? "Zmien szablon" : "Konstruuj";
  button.title = supported
    ? "Zbuduj automatyczna wartosc pola"
    : "Szablony sa dostepne tylko dla pol tekstowych";
}

function pimcoreTemplateSource(row) {
  if (row.classList.contains("pimcore-setup-field-row")) {
    const eanTarget =
      row.closest(".pimcore-setup-body")?.querySelector('[name="ean_target"]')?.value ||
      state.pimcoreSetup?.eanTarget;
    return row.dataset.fieldName === eanTarget
      ? "EAN"
      : pimcoreFieldSource(row.dataset.fieldName, row.dataset.fieldLanguage);
  }
  if (row.classList.contains("pimcore-simple-mapping-row")) {
    return (
      row.dataset.source ||
      pimcoreSelectedMappingSource(row.querySelector('[name="mapping_target"]'))
    );
  }
  return row.querySelector('[name="mapping_source"]')?.value.trim() || "";
}

function pimcoreTemplateMappings(row) {
  const form = row.closest("form");
  if (row.classList.contains("pimcore-setup-field-row")) {
    const use = row.querySelector('[name="mapping_use"]');
    if (use && !use.disabled) use.checked = true;
    return collectPimcoreSetupMappings(row.closest(".pimcore-setup-body"));
  }
  if (row.classList.contains("pimcore-simple-mapping-row")) {
    const use = row.querySelector('[name="mapping_use"]');
    if (use) use.checked = true;
    return collectSimplePimcoreMappings(form);
  }
  return collectPimcoreMappings(form);
}

function insertPimcoreTemplateText(text, { wrap = false } = {}) {
  if (!pimcoreTemplateText) return;
  const start = pimcoreTemplateText.selectionStart ?? pimcoreTemplateText.value.length;
  const end = pimcoreTemplateText.selectionEnd ?? start;
  const selected = pimcoreTemplateText.value.slice(start, end);
  const inserted = wrap ? `(${selected})` : text;
  pimcoreTemplateText.setRangeText(inserted, start, end, "end");
  if (wrap && !selected) {
    pimcoreTemplateText.setSelectionRange(start + 1, start + 1);
  }
  pimcoreTemplateText.focus();
}

function insertPimcoreTemplateFunction(token) {
  if (!pimcoreTemplateText) return;
  const value = pimcoreTemplateText.value;
  const start = pimcoreTemplateText.selectionStart ?? value.length;
  const end = pimcoreTemplateText.selectionEnd ?? start;
  const selected = value.slice(start, end);
  if (selected.startsWith("{") && selected.endsWith("}")) {
    pimcoreTemplateText.setRangeText(
      `${selected.slice(0, -1)}${token}}`,
      start,
      end,
      "end"
    );
  } else {
    const before = value.slice(0, start);
    const position = before.endsWith("}") ? start - 1 : start;
    pimcoreTemplateText.setRangeText(token, position, position, "end");
  }
  pimcoreTemplateText.focus();
}

function insertPimcoreTemplateSqlToken() {
  insertPimcoreTemplateText("{SQL|keep}");
}

function pimcoreTemplateHelpTextElement(tagName, value, className = "") {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = value;
  return element;
}

function selectPimcoreTemplateHelp(index) {
  if (!pimcoreTemplateHelpList || !pimcoreTemplateHelpDetail) return;
  const item = TEMPLATE_FUNCTION_HELP[index];
  if (!item) return;
  const [category, name, syntax, description, examples] = item;

  for (const button of pimcoreTemplateHelpList.querySelectorAll("button[data-help-index]")) {
    const isActive = Number(button.dataset.helpIndex) === index;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-current", isActive ? "true" : "false");
  }

  pimcoreTemplateHelpDetail.replaceChildren();
  const categoryLabel = pimcoreTemplateHelpTextElement("p", category, "pimcore-template-help-category");
  const heading = pimcoreTemplateHelpTextElement("h2", name);
  const introduction = pimcoreTemplateHelpTextElement("p", description, "pimcore-template-help-description");
  const syntaxHeading = pimcoreTemplateHelpTextElement("h3", "Skladnia");
  const syntaxBlock = pimcoreTemplateHelpTextElement("pre", syntax, "pimcore-template-help-syntax");
  const examplesHeading = pimcoreTemplateHelpTextElement("h3", "Przyklady");
  const examplesBox = document.createElement("div");
  examplesBox.className = "pimcore-template-help-examples";

  examples.forEach(([title, template, outcome], exampleIndex) => {
    const example = document.createElement("section");
    example.className = "pimcore-template-help-example";
    const exampleHeading = pimcoreTemplateHelpTextElement("h4", `Przyklad ${exampleIndex + 1}: ${title}`);
    const templateLabel = pimcoreTemplateHelpTextElement("span", "Wpisz do szablonu", "pimcore-template-help-example-label");
    const templateBlock = pimcoreTemplateHelpTextElement("pre", template, "pimcore-template-help-example-template");
    const outcomeLabel = pimcoreTemplateHelpTextElement("span", "Co sie stanie", "pimcore-template-help-example-label");
    const outcomeText = pimcoreTemplateHelpTextElement("p", outcome);
    example.append(exampleHeading, templateLabel, templateBlock, outcomeLabel, outcomeText);
    examplesBox.appendChild(example);
  });

  pimcoreTemplateHelpDetail.append(categoryLabel, heading, introduction, syntaxHeading, syntaxBlock, examplesHeading, examplesBox);
}

function renderPimcoreTemplateHelp() {
  if (!pimcoreTemplateHelpList || !pimcoreTemplateHelpDetail || pimcoreTemplateHelpList.childElementCount) return;
  let previousCategory = "";
  TEMPLATE_FUNCTION_HELP.forEach(([category, name], index) => {
    if (category !== previousCategory) {
      pimcoreTemplateHelpList.appendChild(pimcoreTemplateHelpTextElement("p", category, "pimcore-template-help-list-group"));
      previousCategory = category;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button pimcore-template-help-list-button";
    button.dataset.helpIndex = String(index);
    button.textContent = name;
    button.addEventListener("click", () => selectPimcoreTemplateHelp(index));
    pimcoreTemplateHelpList.appendChild(button);
  });
  selectPimcoreTemplateHelp(0);
}

function openPimcoreTemplateHelp() {
  if (!pimcoreTemplateHelpModal) return;
  renderPimcoreTemplateHelp();
  pimcoreTemplateHelpModal.classList.add("active");
  pimcoreTemplateHelpCloseButton?.focus();
}

function closePimcoreTemplateHelp() {
  pimcoreTemplateHelpModal?.classList.remove("active");
  if (pimcoreTemplateModal?.classList.contains("active")) pimcoreTemplateHelpButton?.focus();
}

function pimcoreOcrValidationFromRow(row) {
  return row?.dataset.ocrValidation === "true";
}

function setPimcoreOcrValidationRow(row, value) {
  if (row) row.dataset.ocrValidation = value ? "true" : "false";
}

function pimcoreRowHasRuntimeTemplate(row) {
  return Boolean(row?.dataset?.valueTemplate) || pimcoreOcrValidationFromRow(row);
}

function pimcoreMappingHasRuntimeTemplate(mapping) {
  return Boolean(mapping?.value_template) || Boolean(mapping?.ocr_validation);
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

function renderPimcoreTemplateTokens(row) {
  pimcoreTemplateSources.textContent = "";
  pimcoreTemplateFunctions.textContent = "";
  for (const [label, source] of PIMCORE_TEMPLATE_PRODUCT_SOURCES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = `{${label}}`;
    button.addEventListener("click", () => insertPimcoreTemplateText(`{${source}|keep}`));
    pimcoreTemplateSources.appendChild(button);
  }
  const targetSource = pimcoreTemplateSource(row);
  for (const mapping of pimcoreTemplateMappings(row)) {
    if (!mapping.source || mapping.source === targetSource) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = `{${mapping.label || mapping.source}}`;
    button.title = `Pole Pimcore: ${mapping.source}`;
    button.addEventListener("click", () =>
      insertPimcoreTemplateText(`{PIMCORE:${mapping.source}|keep}`)
    );
    pimcoreTemplateSources.appendChild(button);
  }
  const group = document.createElement("button");
  group.type = "button";
  group.className = "ghost-button";
  group.textContent = "Nawiasy (...)";
  group.title = "Grupa warunkowa albo nawiasy dzialania";
  group.addEventListener("click", () => insertPimcoreTemplateText("", { wrap: true }));
  pimcoreTemplateFunctions.appendChild(group);
  const sql = document.createElement("button");
  sql.type = "button";
  sql.className = "ghost-button";
  sql.textContent = "SQL";
  sql.title = "{SQL|keep}";
  sql.addEventListener("click", insertPimcoreTemplateSqlToken);
  pimcoreTemplateFunctions.appendChild(sql);
  for (const [label, token] of PIMCORE_TEMPLATE_MATH_TOKENS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = label;
    button.title = token;
    button.addEventListener("click", () => insertPimcoreTemplateText(token));
    pimcoreTemplateFunctions.appendChild(button);
  }
  for (const [label, token] of PIMCORE_TEMPLATE_FUNCTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = label;
    button.title = token;
    button.addEventListener("click", () => insertPimcoreTemplateFunction(token));
    pimcoreTemplateFunctions.appendChild(button);
  }
}

function renderPimcoreTemplateSqlControls(row) {
  if (!pimcoreTemplateSqlControls) return;
  pimcoreTemplateSqlControls.textContent = "";
  pimcoreTemplateSqlControls.classList.add("pimcore-template-sql-controls");
  pimcoreTemplateSqlControls.appendChild(
    pimcoreSqlMappingControls(row, {
      sql_query: row.dataset.sqlQuery || "",
      sql_profile_id: row.dataset.sqlProfileId || "",
    })
  );
}

function pimcoreTemplateSqlValues() {
  return {
    sql_query:
      pimcoreTemplateSqlControls?.querySelector('[name="mapping_sql_query"]')?.value || "",
    sql_profile_id:
      pimcoreTemplateSqlControls?.querySelector('[name="mapping_sql_profile_id"]')?.value || "",
  };
}

function openPimcoreTemplateBuilder(row) {
  if (!row || !pimcoreTemplateModal || pimcoreTemplateFieldType(row) === "checkbox") return;
  state.pimcoreTemplateRow = row;
  pimcoreTemplateText.value = row.dataset.valueTemplate || "";
  pimcoreTemplateTranslate.checked = row.dataset.translate === "true";
  pimcoreTemplateLanguage.value = row.dataset.targetLanguage || pimcoreTemplateLanguageForRow(row);
  pimcoreTemplateLanguage.disabled = !pimcoreTemplateTranslate.checked;
  pimcoreTemplateOcrValidation.checked = pimcoreOcrValidationFromRow(row);
  pimcoreTemplateTarget.textContent = `Pole: ${pimcoreTemplateSource(row) || "nowe mapowanie"}`;
  pimcoreTemplatePreview.textContent = "Wpisz szablon i uruchom podglad.";
  pimcoreTemplateStatus.textContent = "";
  renderPimcoreTemplateSqlControls(row);
  renderPimcoreTemplateTokens(row);
  pimcoreTemplateModal.classList.add("active");
  pimcoreTemplateText.focus();
}

function pimcoreTemplatePreviewPayload() {
  const row = state.pimcoreTemplateRow;
  const targetSource = pimcoreTemplateSource(row);
  const mappings = pimcoreTemplateMappings(row);
  const target = mappings.find((mapping) => mapping.source === targetSource);
  if (!target) throw new Error("Najpierw wybierz pole Pimcore dla tego mapowania.");
  target.value_template = pimcoreTemplateText.value;
  Object.assign(target, pimcoreTemplateSqlValues());
  target.translate = pimcoreTemplateTranslate.checked;
  target.target_language =
    pimcoreTemplateLanguage.value.trim() || pimcoreTemplateLanguageForRow(row) || null;
  target.ocr_validation = pimcoreTemplateOcrValidation.checked;
  return {
    mappings,
    target_source: targetSource,
    product_values: formPayload(),
    values: Object.fromEntries(mappings.map((mapping) => [mapping.source, mapping.default || ""])),
    slot_tokens: pimcoreSlotTokens(),
  };
}

async function previewPimcoreTemplate() {
  pimcoreTemplatePreviewButton.disabled = true;
  pimcoreTemplateStatus.textContent = "Przeliczanie...";
  try {
    const payload = pimcoreTemplatePreviewPayload();
    const result = await requestJson("/api/settings/pimcore/template-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    pimcoreTemplatePreview.textContent = result.values?.[payload.target_source] ?? "";
    pimcoreTemplateStatus.textContent = (result.warnings || [])
      .map((warning) => warning.message || warning.code)
      .filter(Boolean)
      .join(" ");
  } catch (error) {
    pimcoreTemplatePreview.textContent = "Nie mozna wygenerowac podgladu.";
    pimcoreTemplateStatus.textContent = error.message;
  } finally {
    pimcoreTemplatePreviewButton.disabled = false;
  }
}

function savePimcoreTemplateBuilder() {
  const row = state.pimcoreTemplateRow;
  if (!row) return;
  const template = pimcoreTemplateText.value.trim();
  const translate = pimcoreTemplateTranslate.checked;
  const language = pimcoreTemplateLanguage.value.trim() || pimcoreTemplateLanguageForRow(row);
  if (translate && !template) {
    pimcoreTemplateStatus.textContent = "Tlumaczenie wymaga szablonu.";
    return;
  }
  if (translate && !language) {
    pimcoreTemplateStatus.textContent = "Podaj jezyk docelowy tlumaczenia.";
    return;
  }
  row.dataset.valueTemplate = template;
  const sqlValues = pimcoreTemplateSqlValues();
  row.dataset.sqlQuery = sqlValues.sql_query;
  row.dataset.sqlProfileId = sqlValues.sql_profile_id;
  row.dataset.translate = translate ? "true" : "false";
  row.dataset.targetLanguage = translate ? language : "";
  setPimcoreOcrValidationRow(row, pimcoreTemplateOcrValidation.checked);
  if (translate) pimcoreTemplateLanguage.value = language;
  updatePimcoreTemplateButton(row);
  closePimcoreTemplateBuilder();
}

function closePimcoreTemplateBuilder() {
  pimcoreTemplateModal?.classList.remove("active");
  pimcoreTemplateHelpModal?.classList.remove("active");
  if (pimcoreTemplateSqlControls) pimcoreTemplateSqlControls.textContent = "";
  state.pimcoreTemplateRow = null;
}

function additionalSqlProfiles(db = {}) {
  return (db.profiles || []).filter((profile) => profile.usage === "pimcore_sql");
}

function sqlProfileOptions(selected = "") {
  const options = additionalSqlProfiles(state.settings?.database || {})
    .filter((profile) => profile.enabled !== false)
    .map((profile) => [profile.id, profile.label || profile.id]);
  if (selected && !options.some(([id]) => id === selected)) {
    options.push([selected, selected]);
  }
  return options;
}

function pimcoreLayoutOrderValue(value, fallback = 0) {
  const order = Number.parseInt(value, 10);
  return Number.isFinite(order) ? Math.max(0, order) : fallback;
}

function pimcoreMappingLayoutControls(mapping = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "pimcore-layout-controls";
  wrapper.append(
    inputField("mapping_layout_group", "Grupa w formularzu", mapping.layout_group || "", {
      placeholder: "np. Dane podstawowe",
    }),
    inputField("mapping_layout_order", "Wiersz", mapping.layout_order ?? "", {
      type: "number",
      min: 0,
    })
  );
  return wrapper;
}

function collectPimcoreLayout(row, fallbackOrder = 0) {
  return {
    layout_group: row.querySelector('[name="mapping_layout_group"]')?.value.trim() || "",
    layout_order: pimcoreLayoutOrderValue(
      row.querySelector('[name="mapping_layout_order"]')?.value,
      fallbackOrder
    ),
  };
}

function pimcoreSqlMappingControls(row, mapping = {}) {
  const wrapper = document.createElement("div");
  const query = inputField("mapping_sql_query", "Zapytanie SQL", mapping.sql_query || "", {
    textarea: true,
  });
  const profile = selectField(
    "mapping_sql_profile_id",
    "Profil SQL",
    mapping.sql_profile_id || "",
    [["", "Wybierz profil"]].concat(sqlProfileOptions(mapping.sql_profile_id || ""))
  );
  wrapper.className = "pimcore-sql-mapping-controls";
  wrapper.append(query, profile);
  return wrapper;
}

function pimcoreMappingRow(mapping = {}) {
  const row = document.createElement("div");
  row.dataset.valueTemplate = mapping.value_template || "";
  row.dataset.translate = mapping.translate ? "true" : "false";
  row.dataset.targetLanguage = mapping.target_language || "";
  row.dataset.sqlQuery = mapping.sql_query || "";
  row.dataset.sqlProfileId = mapping.sql_profile_id || "";
  setPimcoreOcrValidationRow(row, mapping.ocr_validation);
  row.className = "pimcore-mapping-row";
  const textInput = (name, value, label) => {
    const input = document.createElement("input");
    input.name = name;
    input.value = value || "";
    input.placeholder = label;
    input.setAttribute("aria-label", label);
    return input;
  };
  const choice = (name, value, values, label) => {
    const select = document.createElement("select");
    select.name = name;
    select.setAttribute("aria-label", label);
    for (const item of values) {
      const option = document.createElement("option");
      option.value = item;
      option.textContent = item;
      option.selected = item === value;
      select.appendChild(option);
    }
    return select;
  };
  const required = document.createElement("input");
  required.type = "checkbox";
  required.name = "mapping_required";
  required.checked = Boolean(mapping.required);
  required.setAttribute("aria-label", "Pole wymagane");
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "ghost-button";
  remove.textContent = "Usun";
  remove.title = "Usun mapowanie";
  remove.addEventListener("click", () => row.remove());
  const template = pimcoreTemplateBuilderButton(row);
  row.append(
    textInput("mapping_source", mapping.source, "Kolumna CSV"),
    textInput("mapping_label", mapping.label, "Etykieta"),
    textInput("mapping_target", mapping.pimcore_field, "Pole Pimcore"),
    choice(
      "mapping_type",
      mapping.type || "input",
      ["input", "textarea", "numeric", "checkbox", "select"],
      "Typ Pimcore"
    ),
    textInput("mapping_language", mapping.language, "Jezyk"),
    required,
    textInput("mapping_default", mapping.default, "Wartosc domyslna"),
    choice(
      "mapping_parser",
      mapping.parser || "text",
      ["text", "integer", "decimal_comma", "boolean", "empty_to_null"],
      "Parser"
    ),
    pimcoreMappingLayoutControls(mapping),
    template,
    remove
  );
  return row;
}

function collectPimcoreMappings(form) {
  return [...form.querySelectorAll(".pimcore-mapping-row")].map((row, index) => ({
    source: row.querySelector('[name="mapping_source"]').value.trim(),
    label: row.querySelector('[name="mapping_label"]').value.trim(),
    pimcore_field: row.querySelector('[name="mapping_target"]').value.trim(),
    type: row.querySelector('[name="mapping_type"]').value,
    language: row.querySelector('[name="mapping_language"]').value.trim() || null,
    required: row.querySelector('[name="mapping_required"]').checked,
    default: row.querySelector('[name="mapping_default"]').value,
    parser: row.querySelector('[name="mapping_parser"]').value,
    value_template: row.dataset.valueTemplate || "",
    sql_query: row.querySelector('[name="mapping_sql_query"]')?.value || row.dataset.sqlQuery || "",
    sql_profile_id:
      row.querySelector('[name="mapping_sql_profile_id"]')?.value || row.dataset.sqlProfileId || "",
    translate: row.dataset.translate === "true",
    target_language: row.dataset.targetLanguage || null,
    ocr_validation: pimcoreOcrValidationFromRow(row),
    ...collectPimcoreLayout(row, index),
  }));
}

function collectPimcoreSettings(form) {
  const data = new FormData(form);
  return {
    enabled: data.has("enabled"),
    base_url: data.get("base_url"),
    api_key: data.get("api_key"),
    class_name: data.get("class_name"),
    parent_id: data.get("parent_id"),
    published: data.has("published"),
    object_key_template: data.get("object_key_template"),
    existence_fields: String(data.get("existence_fields") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    timeout_seconds: Number(data.get("timeout_seconds") || 10),
    verify_tls: data.has("verify_tls"),
    field_mappings: collectPimcoreMappings(form),
  };
}

function pimcoreCompactClassItems(pimcore = {}) {
  const items = Array.isArray(state.pimcoreSetup?.classes) ? [...state.pimcoreSetup.classes] : [];
  if (
    pimcore.class_id &&
    !items.some((item) => String(item.id) === String(pimcore.class_id))
  ) {
    items.push({ id: pimcore.class_id, name: pimcore.class_name || pimcore.class_id });
  }
  return items;
}

function pimcoreCompactFolderItems(pimcore = {}) {
  const items = Array.isArray(state.pimcoreSetup?.folders) ? [...state.pimcoreSetup.folders] : [];
  if (
    pimcore.parent_id &&
    !items.some((item) => String(item.id) === String(pimcore.parent_id))
  ) {
    items.push({
      id: pimcore.parent_id,
      key: pimcore.parent_path || pimcore.parent_id,
      path: pimcore.parent_path || pimcore.parent_id,
    });
  }
  return items;
}

function pimcoreCompactFields(pimcore = {}) {
  const discovered = Array.isArray(state.pimcoreSetup?.fields) ? state.pimcoreSetup.fields : [];
  const fields = discovered.length ? [...discovered] : [];
  for (const mapping of pimcore.field_mappings || []) {
    if (
      mapping.pimcore_field &&
      !fields.some((field) => pimcoreFieldsMatch(field, mapping))
    ) {
      fields.push({
        name: mapping.pimcore_field,
        label: mapping.label || mapping.pimcore_field,
        type: mapping.type || "input",
        parser: mapping.parser || "text",
        language: mapping.language || "",
        supported: true,
      });
    }
  }
  return fields;
}

function pimcoreSimpleMappingRow(mapping = {}, fields = []) {
  const row = document.createElement("div");
  const use = document.createElement("input");
  const label = document.createElement("input");
  const target = document.createElement("select");
  const required = document.createElement("input");
  const remove = document.createElement("button");
  const template = pimcoreTemplateBuilderButton(row);
  const layout = pimcoreMappingLayoutControls(mapping);
  const isEan = String(mapping.source || "").toUpperCase() === "EAN";
  const availableFields = [...fields];
  row.className = "pimcore-simple-mapping-row";
  use.type = "checkbox";
  use.name = "mapping_use";
  use.checked = true;
  use.setAttribute("aria-label", "Uzyj pola");
  label.name = "mapping_label";
  label.value = mapping.label || mapping.source || "";
  label.placeholder = "Etykieta";
  label.setAttribute("aria-label", "Etykieta");
  target.name = "mapping_target";
  target.setAttribute("aria-label", "Pole Pimcore");
  if (
    mapping.pimcore_field &&
    !availableFields.some((field) => pimcoreFieldsMatch(field, mapping))
  ) {
    availableFields.push({
      name: mapping.pimcore_field,
      label: mapping.pimcore_field,
      type: mapping.type || "input",
      parser: mapping.parser || "text",
      language: mapping.language || "",
      supported: true,
    });
  }
  for (const field of availableFields) {
    const option = document.createElement("option");
    option.value = field.name;
    option.textContent = pimcoreFieldOptionText(field);
    option.disabled = field.supported === false;
    option.selected = pimcoreFieldsMatch(field, mapping);
    option.dataset.type = field.type || "input";
    option.dataset.parser = field.parser || "text";
    option.dataset.language = field.language || "";
    if (field.unsupported_reason) option.title = field.unsupported_reason;
    target.appendChild(option);
  }
  required.type = "checkbox";
  required.name = "mapping_required";
  required.checked = isEan || Boolean(mapping.required);
  required.disabled = isEan;
  required.setAttribute("aria-label", "Pole wymagane");
  remove.type = "button";
  remove.className = "ghost-button";
  remove.textContent = "Usun";
  remove.disabled = isEan;
  remove.addEventListener("click", () => row.remove());
  row.dataset.source = isEan ? "EAN" : String(mapping.source || mapping.pimcore_field || "");
  row.dataset.valueTemplate = mapping.value_template || "";
  row.dataset.translate = mapping.translate ? "true" : "false";
  row.dataset.targetLanguage = mapping.target_language || "";
  row.dataset.sqlQuery = mapping.sql_query || "";
  row.dataset.sqlProfileId = mapping.sql_profile_id || "";
  setPimcoreOcrValidationRow(row, mapping.ocr_validation);
  target.addEventListener("change", () => {
    if (!row.dataset.source && !label.value.trim()) {
      label.value = pimcoreSelectedMappingSource(target);
    }
    updatePimcoreTemplateButton(row);
  });
  row.append(use, label, target, required, layout, template, remove);
  updatePimcoreTemplateButton(row);
  return row;
}

function collectSimplePimcoreMappings(form) {
  return [...form.querySelectorAll(".pimcore-simple-mapping-row")]
    .filter((row) => row.querySelector('[name="mapping_use"]')?.checked)
    .map((row, index) => {
      const select = row.querySelector('[name="mapping_target"]');
      const option = select?.selectedOptions[0];
      const source = row.dataset.source || pimcoreSelectedMappingSource(select);
      return {
        source,
        label: row.querySelector('[name="mapping_label"]').value.trim() || source,
        pimcore_field: select?.value || "",
        type: option?.dataset.type || "input",
        language: option?.dataset.language || null,
        required:
          String(source).toUpperCase() === "EAN" ||
          row.querySelector('[name="mapping_required"]').checked,
        default: "",
        parser: option?.dataset.parser || "text",
        value_template: row.dataset.valueTemplate || "",
        sql_query:
          row.querySelector('[name="mapping_sql_query"]')?.value || row.dataset.sqlQuery || "",
        sql_profile_id:
          row.querySelector('[name="mapping_sql_profile_id"]')?.value ||
          row.dataset.sqlProfileId ||
          "",
        translate: row.dataset.translate === "true",
        target_language: row.dataset.targetLanguage || null,
        ocr_validation: pimcoreOcrValidationFromRow(row),
        ...collectPimcoreLayout(row, index),
      };
    })
    .filter((mapping) => mapping.source && mapping.pimcore_field);
}

function collectCompactPimcoreSettings(form) {
  const data = new FormData(form);
  const classSelect = form.querySelector('[name="class_id"]');
  const parentSelect = form.querySelector('[name="parent_id"]');
  const selectedClass = classSelect?.selectedOptions[0];
  const selectedParent = parentSelect?.selectedOptions[0];
  const mappings = collectSimplePimcoreMappings(form);
  const manualClassId = String(data.get("manual_class_id") || "").trim();
  const manualClassName = String(data.get("manual_class_name") || "").trim();
  const manualParentId = String(data.get("manual_parent_id") || "").trim();
  const manualParentPath = String(data.get("manual_parent_path") || "").trim();
  return {
    setup_complete: true,
    enabled: data.has("enabled"),
    base_url: data.get("base_url"),
    api_key: data.get("api_key"),
    class_id: manualClassId || classSelect?.value || "",
    class_name: manualClassName || selectedClass?.dataset.name || "",
    parent_id: manualParentId || parentSelect?.value || "",
    parent_path: manualParentPath || selectedParent?.dataset.path || "",
    published: true,
    object_key_template: "{EAN}",
    existence_fields: mappings
      .filter((item) => String(item.source).toUpperCase() === "EAN")
      .map((item) => item.pimcore_field),
    timeout_seconds: Number(data.get("timeout_seconds") || 30),
    verify_tls: data.has("verify_tls"),
    field_mappings: collectSimplePimcoreMappings(form),
  };
}

function pimcoreManualCompactLocationFields(pimcore = {}) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const grid = document.createElement("div");
  summary.textContent = "Wpisz klase i folder recznie";
  grid.className = "pimcore-setup-grid";
  grid.append(
    inputField("manual_class_name", "Nazwa klasy", "", {
      placeholder: pimcore.class_name || "Product",
    }),
    inputField("manual_class_id", "ID klasy", "", {
      placeholder: pimcore.class_id || "",
    }),
    inputField("manual_parent_id", "ID folderu", "", {
      placeholder: pimcore.parent_id || "",
    }),
    inputField("manual_parent_path", "Sciezka folderu", "", {
      placeholder: pimcore.parent_path || "/Products",
    })
  );
  details.className = "wide-field";
  details.append(summary, grid);
  return details;
}

async function requestPimcoreSettingsDiscovery(kind, settings, extra = {}) {
  const payload = await requestJson(PIMCORE_DISCOVERY_ENDPOINTS[kind], {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings, ...extra }),
    timeoutMs: 120000,
  });
  return Array.isArray(payload.items) ? payload.items : [];
}

async function refreshCompactPimcoreMetadata(form, button) {
  const snapshot = collectCompactPimcoreSettings(form);
  button.disabled = true;
  settingsStatus.textContent = "Pobieranie klas i folderow Pimcore...";
  try {
    const classes = await requestPimcoreSettingsDiscovery("classes", snapshot);
    const folders = await requestPimcoreSettingsDiscovery("folders", snapshot);
    const classId = snapshot.class_id || classes[0]?.id || "";
    const fields = classId
      ? await requestPimcoreSettingsDiscovery("fields", snapshot, { class_id: classId })
      : [];
    state.pimcoreSetup = {
      ...(state.pimcoreSetup || {}),
      settings: snapshot,
      classes,
      folders,
      fields,
      mappings: snapshot.field_mappings || [],
    };
    state.settings.pimcore = { ...(state.settings.pimcore || {}), ...snapshot };
    settingsStatus.textContent =
      `Pobrano ${classes.length} klas, ${folders.length} folderow i ${fields.length} pol.`;
    renderSettings();
  } catch (error) {
    settingsStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function pimcoreCsvImportButton(mappingList, fields = []) {
  const input = document.createElement("input");
  const button = document.createElement("button");
  const wrapper = document.createElement("span");
  input.type = "file";
  input.accept = ".csv,text/csv";
  input.hidden = true;
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Wczytaj naglowki CSV";
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const body = new FormData();
      body.set("file", file, file.name);
      const payload = await requestJson("/api/settings/pimcore/import-csv-headers", {
        method: "POST",
        body,
      });
      const existing = new Set(
        [...mappingList.querySelectorAll('[name="mapping_source"], [name="mapping_label"]')]
          .map((item) => item.value)
      );
      for (const header of payload.headers || []) {
        if (!existing.has(header)) {
          if (mappingList.classList.contains("pimcore-simple-mapping-list")) {
            mappingList.appendChild(pimcoreSimpleMappingRow({ source: header, label: header }, fields));
          } else {
            mappingList.appendChild(pimcoreMappingRow({ source: header, label: header }));
          }
          existing.add(header);
        }
      }
      settingsStatus.textContent = `Wczytano ${(payload.headers || []).length} naglowkow CSV.`;
    } catch (error) {
      settingsStatus.textContent = error.message;
    } finally {
      input.value = "";
    }
  });
  wrapper.append(button, input);
  return wrapper;
}

function pimcoreChecklistElement() {
  const output = document.createElement("div");
  output.id = "pimcoreSettingsChecklist";
  output.className = "pimcore-checklist empty-state";
  output.textContent = "Test nie zostal uruchomiony.";
  return output;
}

function renderPimcoreChecklist(report = {}, target = null) {
  const output = target || document.querySelector("#pimcoreSettingsChecklist");
  if (!output) return;
  output.textContent = "";
  output.className = "pimcore-checklist";
  const checks = Array.isArray(report.checks) ? report.checks : [];
  if (!checks.length) {
    output.className = "pimcore-checklist empty-state";
    output.textContent = report.ok ? "Test zakonczony bez dodatkowych komunikatow." : "Brak wynikow testu.";
    return;
  }
  for (const check of checks) {
    const row = document.createElement("div");
    const title = document.createElement("strong");
    const status = check.status || "info";
    row.className = `pimcore-check-row ${status}`;
    if (status === "skipped") {
      row.setAttribute("aria-disabled", "true");
    }
    title.textContent = `${status}: ${check.message || check.key || "kontrola"}`;
    const technical = [
      check.endpoint,
      check.status_code ? `HTTP ${check.status_code}` : "",
      `${Number(check.elapsed_ms || 0)} ms`,
      check.response_excerpt,
      check.suggested_fix,
    ]
      .filter(Boolean);
    row.appendChild(title);
    if (technical.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      const detail = document.createElement("pre");
      summary.textContent = "Szczegoly techniczne";
      detail.textContent = technical.join("\n");
      details.append(summary, detail);
      row.appendChild(details);
    }
    output.appendChild(row);
  }
}

const PIMCORE_DISCOVERY_ENDPOINTS = {
  classes: "/api/settings/pimcore/discover/classes",
  folders: "/api/settings/pimcore/discover/folders",
  fields: "/api/settings/pimcore/discover/fields",
};

function pimcoreDiscoveryErrorText(error) {
  const detail = error?.detail && typeof error.detail === "object" ? error.detail : {};
  const technical = [
    detail.status_code ? `HTTP ${detail.status_code}` : "",
    detail.response_excerpt || "",
  ].filter(Boolean);
  return technical.length ? `${error.message} Szczegoly: ${technical.join(" | ")}` : error.message;
}

function settingsNote(text) {
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent = text;
  return note;
}

function pimcoreSetupInput(name, labelText, value = "", type = "text", placeholder = "") {
  const label = document.createElement("label");
  const title = document.createElement("span");
  const input = document.createElement("input");
  title.textContent = labelText;
  input.name = name;
  input.type = type;
  input.value = value || "";
  input.placeholder = placeholder;
  input.autocomplete = type === "password" ? "new-password" : "off";
  label.append(title, input);
  return label;
}

function pimcoreSetupSelect(name, labelText, items, selected, valueKey, textBuilder) {
  const label = document.createElement("label");
  const title = document.createElement("span");
  const select = document.createElement("select");
  const placeholder = document.createElement("option");
  title.textContent = labelText;
  select.name = name;
  placeholder.value = "";
  placeholder.textContent = "Wybierz...";
  placeholder.disabled = true;
  placeholder.selected = !selected;
  select.appendChild(placeholder);
  for (const item of items) {
    const option = document.createElement("option");
    option.value = String(item[valueKey] ?? "");
    option.textContent = textBuilder(item);
    option.selected = option.value === String(selected || "");
    if (item.name) option.dataset.name = item.name;
    if (item.path) option.dataset.path = item.path;
    select.appendChild(option);
  }
  label.append(title, select);
  return label;
}

function openPimcoreSetupWizard() {
  const saved = state.settings?.pimcore || {};
  state.pimcoreSetup = {
    step: 1,
    settings: { ...saved, api_key: "" },
    classes: [],
    folders: [],
    fields: [],
    mappings: Array.isArray(saved.field_mappings) ? [...saved.field_mappings] : [],
    manualLocation: false,
    eanTarget:
      (saved.field_mappings || []).find((item) => item.source === "EAN")?.pimcore_field || "",
    report: null,
  };
  pimcoreSetupModal?.classList.add("active");
  renderPimcoreSetupStep();
}

function renderPimcoreSetupStep() {
  const setup = state.pimcoreSetup;
  if (!setup || !pimcoreSetupBody) return;
  const titles = {
    1: "Krok 1 z 4: Polaczenie",
    2: "Krok 2 z 4: Miejsce zapisu",
    3: "Krok 3 z 4: Pola produktu",
    4: "Krok 4 z 4: Test i zapis",
  };
  pimcoreSetupBody.textContent = "";
  if (pimcoreSetupStepTitle) pimcoreSetupStepTitle.textContent = titles[setup.step] || titles[1];
  [...(pimcoreSetupProgress?.children || [])].forEach((item, index) => {
    item.classList.toggle("active", index + 1 === setup.step);
  });
  const renderers = {
    1: renderPimcoreConnectionStep,
    2: renderPimcoreLocationStep,
    3: renderPimcoreFieldsStep,
    4: renderPimcoreVerifyStep,
  };
  renderers[setup.step]();
  if (pimcoreSetupBackButton) pimcoreSetupBackButton.disabled = setup.step === 1;
  if (pimcoreSetupNextButton) {
    pimcoreSetupNextButton.textContent =
      setup.step === 4 ? "Zapisz i wlacz integracje" : "Dalej";
  }
}

function renderPimcoreConnectionStep() {
  const setup = state.pimcoreSetup;
  const grid = document.createElement("div");
  const test = document.createElement("button");
  const manual = document.createElement("button");
  grid.className = "pimcore-setup-grid";
  grid.append(
    pimcoreSetupInput(
      "base_url",
      "Adres Pimcore",
      setup.settings.base_url,
      "text",
      "http://twoj-adres-pimcore.example"
    ),
    pimcoreSetupInput("api_key", "Klucz API", setup.settings.api_key || "", "password")
  );
  test.type = "button";
  test.className = "secondary-button";
  test.textContent = "Sprawdz polaczenie i pobierz klasy";
  test.addEventListener("click", async () => {
    capturePimcoreSetupStep();
    test.disabled = true;
    try {
      setup.classes = await requestPimcoreDiscovery("classes");
      if (pimcoreSetupStatus) {
        pimcoreSetupStatus.textContent = `Pobrano ${setup.classes.length} klas.`;
      }
    } catch (error) {
      if (pimcoreSetupStatus) pimcoreSetupStatus.textContent = pimcoreDiscoveryErrorText(error);
    } finally {
      test.disabled = false;
    }
  });
  manual.type = "button";
  manual.className = "ghost-button";
  manual.textContent = "Kontynuuj z recznym wpisaniem klasy i folderu";
  manual.addEventListener("click", () => {
    capturePimcoreSetupStep();
    if (!setup.settings.base_url || (!setup.settings.api_key && !state.settings?.pimcore?.api_key_set)) {
      if (pimcoreSetupStatus) pimcoreSetupStatus.textContent = "Podaj adres Pimcore i klucz API.";
      return;
    }
    setup.manualLocation = true;
    setup.step = 2;
    renderPimcoreSetupStep();
  });
  pimcoreSetupBody.append(grid, actionRow(test, manual));
}

function renderPimcoreLocationStep() {
  const setup = state.pimcoreSetup;
  const grid = document.createElement("div");
  const refresh = document.createElement("button");
  grid.className = "pimcore-setup-grid";
  grid.append(
    pimcoreSetupSelect(
      "class_id",
      "Klasa produktu",
      setup.classes,
      setup.settings.class_id,
      "id",
      (item) => `${item.name} (ID ${item.id})`
    ),
    pimcoreSetupSelect(
      "parent_id",
      "Folder docelowy",
      setup.folders,
      setup.settings.parent_id,
      "id",
      (item) => `${item.path || item.key} (ID ${item.id})`
    )
  );
  refresh.type = "button";
  refresh.className = "secondary-button";
  refresh.textContent = "Odswiez foldery";
  refresh.addEventListener("click", async () => {
    capturePimcoreSetupStep();
    try {
      setup.folders = await requestPimcoreDiscovery("folders");
      renderPimcoreSetupStep();
    } catch (error) {
      if (pimcoreSetupStatus) {
        pimcoreSetupStatus.textContent = `${pimcoreDiscoveryErrorText(error)} Wpisz ID folderu recznie.`;
      }
    }
  });
  pimcoreSetupBody.append(grid, refresh);
  if (!setup.folders.length) {
    pimcoreSetupBody.append(
      settingsNote(
        "Nie wykryto folderow Pimcore. Otworz sekcje ponizej i wpisz ID folderu recznie; sciezka folderu jest opcjonalna."
      )
    );
  }
  pimcoreSetupBody.append(pimcoreManualLocationFallback());
}

function renderPimcoreFieldsStep() {
  const setup = state.pimcoreSetup;
  const supported = setup.fields.filter((field) => field.supported);
  if (!setup.eanTarget) {
    setup.eanTarget = supported.find((field) => field.name.toUpperCase() === "EAN")?.name || "";
  }
  const eanTarget = pimcoreSetupSelect(
    "ean_target",
    "Pole EAN w Pimcore",
    supported,
    setup.eanTarget,
    "name",
    (item) => `${item.label || item.name} (${item.name})`
  );
  const intro = document.createElement("p");
  const eanHelp = document.createElement("p");
  const header = document.createElement("div");
  intro.className = "settings-note";
  intro.textContent =
    "Ktore dane uzytkownik ma wpisywac podczas dodawania produktu? Zaznacz Zapisz pole tylko dla potrzebnych danych.";
  eanHelp.className = "settings-note";
  eanHelp.textContent =
    "Lista Pole EAN w Pimcore wskazuje kolumne, w ktorej Pimcore przechowuje 13-cyfrowy EAN.";
  header.className = "pimcore-setup-field-header";
  for (const text of ["Zapisz pole", "Pole w Pimcore", "Nazwa w formularzu", "Wymagane", "Układ", "Wartosc"]) {
    const cell = document.createElement("strong");
    cell.textContent = text;
    header.appendChild(cell);
  }
  const table = document.createElement("div");
  table.className = "pimcore-setup-field-list";
  table.appendChild(header);
  for (const field of setup.fields) {
    table.appendChild(pimcoreSetupFieldRow(field, setup.mappings, setup.eanTarget));
  }
  eanTarget.querySelector("select").addEventListener("change", (event) => {
    setup.mappings = collectPimcoreSetupMappings(pimcoreSetupBody).filter(
      (item) => item.source !== "EAN"
    );
    setup.eanTarget = event.target.value;
    renderPimcoreSetupStep();
  });
  pimcoreSetupBody.append(intro, eanTarget, eanHelp, table);
}

function renderPimcoreVerifyStep() {
  const run = document.createElement("button");
  const output = document.createElement("div");
  output.className = "pimcore-checklist empty-state";
  output.textContent = "Test nie zostal uruchomiony.";
  run.type = "button";
  run.className = "secondary-button";
  run.textContent = "Sprawdz konfiguracje";
  run.addEventListener("click", async () => {
    const report = await requestJson("/api/settings/pimcore/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: buildPimcoreSetupPayload() }),
      timeoutMs: 120000,
    });
    state.pimcoreSetup.report = report;
    renderPimcoreChecklist(report, output);
    if (pimcoreSetupNextButton) pimcoreSetupNextButton.disabled = !report.ok;
  });
  if (pimcoreSetupNextButton) {
    pimcoreSetupNextButton.disabled = !state.pimcoreSetup.report?.ok;
  }
  pimcoreSetupBody.append(run, output);
}

function pimcoreManualLocationFallback() {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const grid = document.createElement("div");
  const setup = state.pimcoreSetup;
  const classKnown = setup.classes.some(
    (item) => String(item.id) === String(setup.settings.class_id || "")
  );
  const folderKnown = setup.folders.some(
    (item) => String(item.id) === String(setup.settings.parent_id || "")
  );
  summary.textContent = "Wpisz wartosci recznie";
  grid.className = "pimcore-setup-grid";
  grid.append(
    pimcoreSetupInput("manual_class_name", "Nazwa klasy", classKnown ? "" : setup.settings.class_name),
    pimcoreSetupInput("manual_class_id", "ID klasy", classKnown ? "" : setup.settings.class_id),
    pimcoreSetupInput("manual_parent_id", "ID folderu", folderKnown ? "" : setup.settings.parent_id),
    pimcoreSetupInput(
      "manual_parent_path",
      "Sciezka folderu",
      folderKnown ? "" : setup.settings.parent_path
    )
  );
  details.append(summary, grid);
  return details;
}

function pimcoreSetupFieldRow(field, mappings, eanTarget) {
  const existing = mappings.find((item) => pimcoreFieldsMatch(field, item)) || {};
  const row = document.createElement("div");
  const use = document.createElement("input");
  const label = document.createElement("input");
  const required = document.createElement("input");
  const useLabel = document.createElement("label");
  const fieldName = document.createElement("code");
  const labelWrapper = document.createElement("label");
  const requiredLabel = document.createElement("label");
  const layout = pimcoreMappingLayoutControls(existing);
  const isEan = field.name === eanTarget;
  row.className = "pimcore-setup-field-row";
  row.dataset.fieldName = field.name;
  row.dataset.fieldType = field.type;
  row.dataset.fieldLanguage = field.language || "";
  row.dataset.fieldParser = field.parser || "";
  row.dataset.valueTemplate = existing.value_template || "";
  row.dataset.translate = existing.translate ? "true" : "false";
  row.dataset.targetLanguage = existing.target_language || "";
  row.dataset.sqlQuery = existing.sql_query || "";
  row.dataset.sqlProfileId = existing.sql_profile_id || "";
  setPimcoreOcrValidationRow(row, existing.ocr_validation);
  use.type = "checkbox";
  use.name = "mapping_use";
  use.checked = isEan || Boolean(existing.pimcore_field);
  use.disabled = !field.supported || isEan;
  label.name = "mapping_label";
  label.value = existing.label || field.label || field.name;
  label.disabled = !field.supported;
  required.type = "checkbox";
  required.name = "mapping_required";
  required.checked = isEan || Boolean(existing.required);
  required.disabled = isEan || !field.supported;
  use.setAttribute("aria-label", `Zapisz pole ${field.name}`);
  required.setAttribute("aria-label", `Pole ${field.name} wymagane`);
  useLabel.append(use, document.createTextNode(" Zapisz"));
  fieldName.textContent = field.language ? `${field.name} [${field.language}]` : field.name;
  labelWrapper.append(label);
  requiredLabel.append(required, document.createTextNode(" Wymagane"));
  const template = pimcoreTemplateBuilderButton(row);
  row.append(useLabel, fieldName, labelWrapper, requiredLabel, layout, template);
  updatePimcoreTemplateButton(row);
  if (!field.supported) row.title = field.unsupported_reason || "Pole nie jest obslugiwane.";
  return row;
}

function collectPimcoreSetupMappings(container) {
  const eanTarget =
    container.querySelector('[name="ean_target"]')?.value || state.pimcoreSetup.eanTarget;
  return [...container.querySelectorAll(".pimcore-setup-field-row")]
    .filter(
      (row) =>
        row.dataset.fieldName === eanTarget ||
        row.querySelector('[name="mapping_use"]')?.checked
    )
    .map((row, index) => {
      const source =
        row.dataset.fieldName === eanTarget
          ? "EAN"
          : pimcoreFieldSource(row.dataset.fieldName, row.dataset.fieldLanguage);
      return {
        source,
        label: row.querySelector('[name="mapping_label"]').value.trim() || source,
        pimcore_field: row.dataset.fieldName,
        type: row.dataset.fieldType,
        language: row.dataset.fieldLanguage || null,
        required: source === "EAN" || row.querySelector('[name="mapping_required"]').checked,
        default: "",
        parser: row.dataset.fieldParser,
        value_template: row.dataset.valueTemplate || "",
        sql_query:
          row.querySelector('[name="mapping_sql_query"]')?.value || row.dataset.sqlQuery || "",
        sql_profile_id:
          row.querySelector('[name="mapping_sql_profile_id"]')?.value ||
          row.dataset.sqlProfileId ||
          "",
        translate: row.dataset.translate === "true",
        target_language: row.dataset.targetLanguage || null,
        ocr_validation: pimcoreOcrValidationFromRow(row),
        ...collectPimcoreLayout(row, index),
      };
    });
}

function capturePimcoreSetupStep() {
  const setup = state.pimcoreSetup;
  if (!setup || !pimcoreSetupForm) return;
  const data = new FormData(pimcoreSetupForm);
  for (const key of ["base_url", "api_key", "class_id", "parent_id"]) {
    if (data.has(key)) setup.settings[key] = String(data.get(key) || "").trim();
  }
  if (setup.step === 2) {
    const selectedClass = setup.classes.find((item) => String(item.id) === setup.settings.class_id);
    const selectedFolder = setup.folders.find((item) => String(item.id) === setup.settings.parent_id);
    if (selectedClass) setup.settings.class_name = selectedClass.name;
    if (selectedFolder) setup.settings.parent_path = selectedFolder.path;
    const manualClassId = String(data.get("manual_class_id") || "").trim();
    const manualClassName = String(data.get("manual_class_name") || "").trim();
    const manualParentId = String(data.get("manual_parent_id") || "").trim();
    const manualParentPath = String(data.get("manual_parent_path") || "").trim();
    if (manualClassId || manualClassName) {
      setup.settings.class_id = manualClassId;
      setup.settings.class_name = manualClassName;
    }
    if (manualParentId) {
      setup.settings.parent_id = manualParentId;
      setup.settings.parent_path = manualParentPath;
    }
  }
  if (setup.step === 3) setup.mappings = collectPimcoreSetupMappings(pimcoreSetupBody);
}

function buildPimcoreSetupPayload() {
  const setup = state.pimcoreSetup;
  return {
    ...setup.settings,
    enabled: true,
    setup_complete: false,
    published: true,
    object_key_template: "{EAN}",
    field_mappings: setup.mappings,
  };
}

async function requestPimcoreDiscovery(kind, extra = {}) {
  const setup = state.pimcoreSetup;
  return requestPimcoreSettingsDiscovery(kind, setup.settings, extra);
}

async function advancePimcoreSetup() {
  const setup = state.pimcoreSetup;
  if (!setup) return;
  if (pimcoreSetupStatus) pimcoreSetupStatus.textContent = "";
  capturePimcoreSetupStep();
  try {
    if (setup.step === 1) {
      if (!setup.settings.base_url || (!setup.settings.api_key && !state.settings?.pimcore?.api_key_set)) {
        throw new Error("Podaj adres Pimcore i klucz API.");
      }
      if (!setup.classes.length) {
        setup.classes = await requestPimcoreDiscovery("classes");
      }
      if (!setup.classes.length) throw new Error("Nie znaleziono klas Pimcore.");
      try {
        setup.folders = await requestPimcoreDiscovery("folders");
      } catch (error) {
        setup.folders = [];
        if (pimcoreSetupStatus) {
          pimcoreSetupStatus.textContent = `Nie pobrano folderow: ${error.message}. Wpisz folder recznie.`;
        }
      }
      setup.step = 2;
    } else if (setup.step === 2) {
      if (!setup.settings.class_id || !setup.settings.class_name || !setup.settings.parent_id) {
        throw new Error("Wybierz klase produktu i folder docelowy albo wpisz je recznie.");
      }
      setup.fields = await requestPimcoreDiscovery("fields", {
        class_id: setup.settings.class_id,
      });
      if (!setup.fields.length) throw new Error("Klasa nie udostepnia pol do przypisania.");
      setup.step = 3;
    } else if (setup.step === 3) {
      const ean = setup.mappings.find((item) => item.source === "EAN" && item.required);
      if (!ean) throw new Error("Wybierz wymagane pole EAN.");
      setup.report = null;
      setup.step = 4;
    } else {
      await savePimcoreSetup();
      return;
    }
    renderPimcoreSetupStep();
  } catch (error) {
    if (pimcoreSetupStatus) pimcoreSetupStatus.textContent = error.message;
  }
}

async function savePimcoreSetup() {
  if (pimcoreSetupNextButton) pimcoreSetupNextButton.disabled = true;
  if (pimcoreSetupStatus) pimcoreSetupStatus.textContent = "Zapisywanie konfiguracji...";
  try {
    const result = await requestJson("/api/settings/pimcore/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: buildPimcoreSetupPayload() }),
      timeoutMs: 120000,
    });
    state.settings = result.settings || state.settings;
    pimcoreSetupModal?.classList.remove("active");
    renderSettingsPimcore();
  } catch (error) {
    if (pimcoreSetupStatus) pimcoreSetupStatus.textContent = error.message;
  } finally {
    if (pimcoreSetupNextButton) pimcoreSetupNextButton.disabled = false;
  }
}

function pimcoreReadOnlyTestButton(getSettings) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Sprawdz konfiguracje";
  button.addEventListener("click", async () => {
    button.disabled = true;
    settingsStatus.textContent = "Testowanie Pimcore...";
    try {
      const report = await requestJson("/api/settings/pimcore/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: getSettings() }),
        timeoutMs: 120000,
      });
      renderPimcoreChecklist(report);
      settingsStatus.textContent = report.ok
        ? "Test konfiguracji Pimcore zakonczony powodzeniem."
        : "Test konfiguracji Pimcore wykryl problemy.";
    } catch (error) {
      settingsStatus.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function pimcoreOpenWriteTestButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Testowo dodaj obiekt";
  button.addEventListener("click", openPimcoreWriteTest);
  return button;
}

function pimcoreHistoryButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Historia Pimcore";
  button.addEventListener("click", () => {
    openPimcoreHistory().catch((error) => {
      if (pimcoreHistoryOutput) {
        pimcoreHistoryOutput.className = "history-output empty-state";
        pimcoreHistoryOutput.textContent = error.message;
      }
    });
  });
  return button;
}

function pimcoreSettingsExportButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Eksport danych Pimcore";
  button.addEventListener("click", () => {
    openPimcoreExportModal();
  });
  return button;
}

function pimcoreExportLayoutOpenButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = "Edytuj kolejność pól do eksportu";
  button.addEventListener("click", openPimcoreExportLayoutModal);
  return button;
}

function pimcoreRuntimeLayoutGroups(schema = []) {
  const groups = new Map();
  const fields = (Array.isArray(schema) ? schema : [])
    .map((mapping, index) => ({
      mapping,
      index,
      groupName: cleanDisplayLabel(mapping?.layout_group),
      rowOrder: pimcoreLayoutOrderValue(mapping?.layout_order, index),
    }))
    .sort((left, right) => left.rowOrder - right.rowOrder || left.index - right.index);
  for (const field of fields) {
    const groupKey = field.groupName || "";
    let group = groups.get(groupKey);
    if (!group) {
      group = {
        name: field.groupName,
        firstOrder: field.rowOrder,
        firstIndex: field.index,
        rows: new Map(),
      };
      groups.set(groupKey, group);
    }
    const rowKey = String(field.rowOrder);
    let row = group.rows.get(rowKey);
    if (!row) {
      row = {
        order: field.rowOrder,
        firstIndex: field.index,
        fields: [],
      };
      group.rows.set(rowKey, row);
    }
    row.fields.push(field.mapping);
  }
  return [...groups.values()]
    .sort((left, right) => left.firstOrder - right.firstOrder || left.firstIndex - right.firstIndex)
    .map((group) => ({
      ...group,
      rows: [...group.rows.values()].sort(
        (left, right) => left.order - right.order || left.firstIndex - right.firstIndex
      ),
    }));
}

function pimcoreRuntimeSection(form, groupName) {
  const section = document.createElement("section");
  const title = document.createElement("h3");
  section.className = "pimcore-runtime-section";
  title.textContent = groupName;
  section.appendChild(title);
  form.appendChild(section);
  return section;
}

function pimcoreRuntimeRow(container, fieldCount) {
  const row = document.createElement("div");
  const columns = Math.max(1, Number(fieldCount || 0));
  row.className = "pimcore-runtime-row";
  row.style.setProperty("--pimcore-runtime-columns", String(columns));
  container.appendChild(row);
  return row;
}

function populatePimcoreRuntimeForm(
  form,
  schema,
  values = {},
  { readOnlySources = [], allowRecalculate = false, status = null, idPrefix = "pimcoreField" } = {}
) {
  if (!form) return;
  form.textContent = "";
  const readOnly = new Set(readOnlySources);
  for (const group of pimcoreRuntimeLayoutGroups(schema)) {
    const groupContainer = group.name ? pimcoreRuntimeSection(form, group.name) : form;
    for (const layoutRow of group.rows) {
      const rowContainer = pimcoreRuntimeRow(groupContainer, layoutRow.fields.length);
      for (const mapping of layoutRow.fields) {
        const label = document.createElement("label");
        const heading = document.createElement("span");
        const input = document.createElement("input");
        const fieldRow = document.createElement("span");
        label.className = "pimcore-runtime-field";
        heading.textContent = `${mapping.label || mapping.source}${mapping.required ? " *" : ""}`;
        input.name = mapping.source;
        input.value = values?.[mapping.source] ?? mapping.default ?? "";
        input.dataset.originalValue = input.value;
        input.required = Boolean(mapping.required);
        input.readOnly = readOnly.has(mapping.source);
        input.autocomplete = "off";
        const legacyEanIds = {
          pimcoreCreate: "pimcoreCreateEan",
          pimcoreEdit: "pimcoreEditEan",
        };
        input.id =
          mapping.source === "EAN" && legacyEanIds[idPrefix]
            ? legacyEanIds[idPrefix]
            : `${idPrefix}-${String(mapping.source || "field").replace(/[^A-Za-z0-9_-]/g, "-")}`;
        input.addEventListener("input", () => {
          if (mapping.ocr_validation) input.value = input.value.replace(/,/g, ".");
          updatePimcoreRuntimeFieldChangeState(input);
          if (mapping.ocr_validation) {
            schedulePimcoreOcrFieldValidation(form, schema, mapping.source);
          }
        });
        if (mapping.ocr_validation) {
          input.addEventListener("change", () => {
            schedulePimcoreOcrFieldValidation(form, schema, mapping.source, 0);
          });
        }
        fieldRow.className = "pimcore-runtime-field-row";
        fieldRow.appendChild(input);
        if (allowRecalculate && pimcoreMappingHasRuntimeTemplate(mapping)) {
          const recalculate = document.createElement("button");
          recalculate.type = "button";
          recalculate.className = "ghost-button icon-button pimcore-recalculate-field";
          recalculate.textContent = "↻";
          recalculate.title = `Przelicz pole ${mapping.label || mapping.source}`;
          recalculate.setAttribute("aria-label", recalculate.title);
          recalculate.addEventListener("click", async () => {
            recalculate.disabled = true;
            if (status) status.textContent = `Przeliczanie pola ${mapping.label || mapping.source}...`;
            try {
              const result = await renderPimcoreRuntimeTemplates(form, schema, [mapping.source]);
              if (status) status.textContent = pimcoreRuntimeRecalculateStatus(form, result);
            } catch (error) {
              if (status) status.textContent = error.message;
            } finally {
              recalculate.disabled = false;
            }
          });
          fieldRow.appendChild(recalculate);
        }
        label.append(heading, fieldRow);
        rowContainer.appendChild(label);
      }
    }
  }
}

const pimcoreOcrValidationTimers = new WeakMap();
const pimcoreOcrValidationRevisions = new WeakMap();

function pimcoreOcrValidationState(form) {
  let timers = pimcoreOcrValidationTimers.get(form);
  if (!timers) {
    timers = new Map();
    pimcoreOcrValidationTimers.set(form, timers);
  }
  let revisions = pimcoreOcrValidationRevisions.get(form);
  if (!revisions) {
    revisions = new Map();
    pimcoreOcrValidationRevisions.set(form, revisions);
  }
  return { timers, revisions };
}

function setPimcoreOcrChecking(field, checking) {
  if (!field) return;
  const existing = field.querySelector(".pimcore-runtime-ocr-checking");
  if (!checking) {
    existing?.remove();
    return;
  }
  if (existing) return;
  const indicator = document.createElement("span");
  indicator.className = "pimcore-runtime-ocr pimcore-runtime-ocr-checking";
  indicator.textContent = "Sprawdzanie OCR...";
  field.appendChild(indicator);
}

function schedulePimcoreOcrFieldValidation(form, schema, source, delayMs = 300) {
  const input = form?.elements?.[source];
  if (!input) return;
  const { timers, revisions } = pimcoreOcrValidationState(form);
  window.clearTimeout(timers.get(source));
  const revision = (revisions.get(source) || 0) + 1;
  revisions.set(source, revision);
  const field = typeof input.closest === "function"
    ? input.closest(".pimcore-runtime-field")
    : null;
  clearPimcoreOcrMismatch(field);
  timers.set(source, window.setTimeout(async () => {
    setPimcoreOcrChecking(field, true);
    try {
      await validatePimcoreOcrFields(form, schema, [source], (candidate) => (
        candidate === source && revisions.get(source) === revision
      ));
    } catch (_error) {
      // The input remains editable; the next edit retries validation.
    } finally {
      if (revisions.get(source) === revision) {
        timers.delete(source);
        setPimcoreOcrChecking(field, false);
      }
    }
  }, Math.max(0, Number(delayMs) || 0)));
}

function pimcoreRuntimeWarnings(warnings = []) {
  return warnings
    .map((warning) => warning.message || warning.code || "")
    .filter(Boolean)
    .join(" ");
}

function clearPimcoreRuntimeConflict(field) {
  if (!field) return;
  field.classList.remove("pimcore-runtime-pulse");
  if (!field.classList.contains("pimcore-runtime-ocr-mismatch")) {
    field.classList.remove("pimcore-runtime-conflict");
  }
  const info = field.querySelector(".pimcore-runtime-calculated");
  if (info) info.hidden = true;
}

function pimcoreRuntimeActions(...buttons) {
  const actions = document.createElement("span");
  actions.className = "pimcore-runtime-actions";
  actions.append(...buttons);
  return actions;
}

function updatePimcoreRuntimeOriginalState(input) {
  const form = input?.form;
  const field = input?.closest(".pimcore-runtime-field");
  if (!form || !field) return;
  const changed = form.dataset.pimcoreMode === "edit" && input.value !== input.dataset.originalValue;
  field.classList.toggle("pimcore-runtime-different", changed);
  let original = field.querySelector(".pimcore-runtime-original");
  if (!original) {
    original = document.createElement("span");
    original.className = "pimcore-runtime-original";
    const text = document.createElement("span");
    const undo = document.createElement("button");
    undo.type = "button";
    undo.className = "ghost-button pimcore-runtime-action-button pimcore-runtime-undo-action";
    undo.textContent = "\u00d7";
    undo.title = "Cofnij zmiany";
    undo.setAttribute("aria-label", undo.title);
    undo.addEventListener("click", () => {
      input.value = input.dataset.originalValue || "";
      clearPimcoreRuntimeConflict(field);
      updatePimcoreRuntimeFieldChangeState(input, { userInput: false });
    });
    original.append(text, pimcoreRuntimeActions(undo));
    field.appendChild(original);
  }
  original.querySelector("span").textContent = `Oryginalnie: ${input.dataset.originalValue || "(puste)"}`;
  original.hidden = !changed;
}

function hasBlockingPimcoreRuntimeDifferences(form = pimcoreEditForm) {
  return Boolean(form?.querySelector(".pimcore-runtime-conflict"));
}

function pimcoreRuntimeDifferenceCount(form) {
  return form?.querySelectorAll(".pimcore-runtime-conflict").length || 0;
}

function focusFirstPimcoreRuntimeDifference(form = pimcoreEditForm) {
  const field = form?.querySelector(".pimcore-runtime-conflict");
  if (!field) return false;
  field.scrollIntoView({ behavior: "smooth", block: "center" });
  field.classList.remove("pimcore-runtime-pulse");
  void field.offsetWidth;
  field.classList.add("pimcore-runtime-pulse");
  const input = field.querySelector("input");
  if (input) input.focus({ preventScroll: true });
  window.setTimeout(() => field.classList.remove("pimcore-runtime-pulse"), 1800);
  return true;
}

function updatePimcoreRuntimeSubmitState(form, button) {
  if (!button || button.dataset.busy === "1") return;
  const blocked = hasBlockingPimcoreRuntimeDifferences(form);
  button.classList.toggle("pimcore-submit-blocked", blocked);
  button.setAttribute("aria-disabled", blocked ? "true" : "false");
  button.title = blocked
    ? "Najpierw zastosuj wyliczona wartosc albo cofnij zmiany w oznaczonej komorce."
    : "";
}

function updatePimcoreEditSubmitState() {
  updatePimcoreRuntimeSubmitState(pimcoreEditForm, pimcoreEditSubmitButton);
}

function updatePimcoreCreateSubmitState() {
  updatePimcoreRuntimeSubmitState(pimcoreCreateForm, pimcoreCreateSubmitButton);
}

function updatePimcoreRuntimeFieldChangeState(input, { userInput = true } = {}) {
  const field = input?.closest(".pimcore-runtime-field");
  updatePimcoreRuntimeOriginalState(input);
  if (userInput && field?.classList.contains("pimcore-runtime-conflict")) {
    const calculated = String(input.dataset.calculatedValue ?? "");
    const original = String(input.dataset.originalValue ?? "");
    if (String(input.value ?? "") === calculated || String(input.value ?? "") === original) {
      clearPimcoreRuntimeConflict(field);
    }
  }
  updatePimcoreCreateSubmitState();
  updatePimcoreEditSubmitState();
}

function updatePimcoreRuntimeCalculatedState(form, result = {}, schema = []) {
  const calculated = result.calculated_values || {};
  const changed = result.changed || {};
  for (const [source, value] of Object.entries(calculated)) {
    const input = form.elements[source];
    if (!input) continue;
    const field = input.closest(".pimcore-runtime-field");
    if (!field) continue;
    const mapping = (schema || []).find((item) => item.source === source);
    input.dataset.calculatedValue = value ?? "";
    let info = field.querySelector(".pimcore-runtime-calculated");
    if (!info) {
      info = document.createElement("span");
      info.className = "pimcore-runtime-calculated";
      const text = document.createElement("span");
      const apply = document.createElement("button");
      apply.type = "button";
      apply.className = "ghost-button pimcore-runtime-action-button pimcore-runtime-apply-action";
      apply.textContent = "\u2713";
      apply.title = "Zastosuj wyliczone";
      apply.setAttribute("aria-label", apply.title);
      apply.addEventListener("click", () => {
        input.value = input.dataset.calculatedValue || "";
        clearPimcoreRuntimeConflict(field);
        updatePimcoreRuntimeFieldChangeState(input, { userInput: false });
        if (mapping?.ocr_validation) {
          schedulePimcoreOcrFieldValidation(form, schema, source, 0);
        }
        info.hidden = true;
      });
      const undo = document.createElement("button");
      undo.type = "button";
      undo.className = "ghost-button pimcore-runtime-action-button pimcore-runtime-undo-action";
      undo.textContent = "\u00d7";
      undo.title = "Cofnij zmiany";
      undo.setAttribute("aria-label", undo.title);
      undo.addEventListener("click", () => {
        input.value = input.dataset.originalValue || "";
        clearPimcoreRuntimeConflict(field);
        updatePimcoreRuntimeFieldChangeState(input, { userInput: false });
      });
      info.append(text, pimcoreRuntimeActions(apply, undo));
      field.appendChild(info);
    }
    info.querySelector("span").textContent = `Wyliczone: ${value ?? ""}`;
    const isDifferent = changed[source] === true && String(input.value) !== String(value ?? "");
    field.classList.toggle("pimcore-runtime-conflict", isDifferent);
    updatePimcoreRuntimeOriginalState(input);
    info.hidden = !isDifferent;
  }
  updatePimcoreCreateSubmitState();
  updatePimcoreEditSubmitState();
}

function clearPimcoreOcrMismatch(field) {
  if (!field) return;
  field.classList.remove("pimcore-runtime-ocr-mismatch");
  field.querySelector(".pimcore-runtime-ocr")?.remove();
  const input = field.querySelector("input");
  if (
    !Object.prototype.hasOwnProperty.call(input?.dataset || {}, "calculatedValue") ||
    String(input?.value ?? "") === String(input?.dataset.calculatedValue ?? "")
  ) {
    field.classList.remove("pimcore-runtime-conflict");
  }
}

function renderPimcoreOcrMismatch(form, mapping, input, result) {
  const field = input.closest(".pimcore-runtime-field");
  if (!field) return;
  clearPimcoreOcrMismatch(field);
  if (!result?.mismatch) return;
  field.classList.add("pimcore-runtime-conflict", "pimcore-runtime-ocr-mismatch");
  const info = document.createElement("span");
  info.className = "pimcore-runtime-ocr";
  const text = document.createElement("span");
  const values = (result.images || []).flatMap((image) => image.values || [])
    .map((item) => String(item.text || "")).filter(Boolean);
  text.textContent = "Wartosc nie pasuje do OCR.";
  text.title = values.length ? `Wykryte wartosci: ${[...new Set(values)].join(", ")}` : "Brak wykrytych wartosci.";
  const accept = document.createElement("button");
  accept.type = "button";
  accept.className = "ghost-button pimcore-runtime-action-button pimcore-runtime-apply-action";
  accept.textContent = "✓";
  accept.title = "Potwierdz wprowadzona wartosc";
  accept.addEventListener("click", async () => {
    accept.disabled = true;
    try {
      await requestJson("/api/ocr/approval", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          field_id: mapping.pimcore_field || mapping.source,
          value: input.value,
          slot_tokens: Object.values(pimcoreOcrSlotTokens()),
        }),
      });
      clearPimcoreOcrMismatch(field);
      updatePimcoreRuntimeFieldChangeState(input, { userInput: false });
    } catch (error) {
      accept.disabled = false;
      text.textContent = error.message || "Nie udalo sie potwierdzic wartosci.";
    }
  });
  const reject = document.createElement("button");
  reject.type = "button";
  reject.className = "ghost-button pimcore-runtime-action-button pimcore-runtime-undo-action";
  reject.textContent = "×";
  reject.title = "Cofnij zmiane lub wyczysc pole";
  reject.addEventListener("click", () => {
    input.value = input.dataset.originalValue || "";
    clearPimcoreOcrMismatch(field);
    updatePimcoreRuntimeFieldChangeState(input, { userInput: false });
  });
  info.append(text, pimcoreRuntimeActions(accept, reject));
  field.appendChild(info);
}

async function validatePimcoreOcrFields(form, schema, targets = null, isCurrent = null) {
  if (state.settings?.ocr_available === false) return;
  const selected = Array.isArray(targets) ? new Set(targets) : null;
  const slotTokens = Object.values(pimcoreOcrSlotTokens());
  if (!slotTokens.length) return;
  const mappings = (schema || []).filter((mapping) => (
    mapping?.ocr_validation && (!selected || selected.has(mapping.source))
  ));
  await Promise.all(mappings.map(async (mapping) => {
    const input = form.elements[mapping.source];
    if (!input) return;
    input.value = input.value.replace(/,/g, ".");
    const result = await requestJson("/api/ocr/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        field_id: mapping.pimcore_field || mapping.source,
        value: input.value,
        slot_tokens: slotTokens,
      }),
    });
    if (typeof isCurrent === "function" && !isCurrent(mapping.source)) return;
    renderPimcoreOcrMismatch(form, mapping, input, result);
  }));
  updatePimcoreCreateSubmitState();
  updatePimcoreEditSubmitState();
}

function pimcoreRuntimeRecalculateStatus(form, result = {}) {
  const warnings = pimcoreRuntimeWarnings(result.warnings);
  if (warnings) return warnings;
  const count = pimcoreRuntimeDifferenceCount(form);
  return count
    ? `Roznice po przeliczeniu: ${count}. Zastosuj wyliczone albo cofnij zmiany.`
    : "";
}

function blockPimcoreRuntimeSubmitIfNeeded(form, status) {
  if (!hasBlockingPimcoreRuntimeDifferences(form)) return false;
  focusFirstPimcoreRuntimeDifference(form);
  if (status) {
    status.textContent =
      "Najpierw zastosuj wyliczona wartosc albo cofnij zmiany w oznaczonej komorce.";
  }
  return true;
}

async function renderPimcoreRuntimeTemplates(form, schema, targets = null) {
  const hasExplicitTargets = Array.isArray(targets);
  const selected = hasExplicitTargets
    ? targets
    : (schema || []).filter((mapping) => mapping.value_template).map((mapping) => mapping.source);
  const renderedTargets = selected.filter((source) => (
    (schema || []).some((mapping) => mapping.source === source && mapping.value_template)
  ));
  const validationTargets = hasExplicitTargets ? selected : null;
  if (form === pimcoreCreateForm) state.pimcoreCreateIntegrationContextId = "";
  if (form === pimcoreEditForm) state.pimcoreEditIntegrationContextId = "";
  if (!renderedTargets.length) {
    await validatePimcoreOcrFields(form, schema, validationTargets);
    return { values: {}, warnings: [], calculated_values: {}, changed: {} };
  }
  const values = Object.fromEntries(new FormData(form).entries());
  if (form === pimcoreCreateForm) state.pimcoreCreateIntegrations = { sql_profiles: [] };
  if (form === pimcoreEditForm) state.pimcoreEditIntegrations = { sql_profiles: [] };
  const result = await requestJson("/api/pimcore/render-templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      product_values: formPayload(),
      values,
      targets: renderedTargets,
      mode: form.dataset.pimcoreMode || "create",
      object_id:
        form === pimcoreEditForm ? Number(state.pimcoreEditObjectId || 0) : null,
      slot_tokens: pimcoreSlotTokens(),
    }),
  });
  const integrationContext = result.integrations || { sql_profiles: [] };
  if (form === pimcoreCreateForm) state.pimcoreCreateIntegrations = integrationContext;
  if (form === pimcoreEditForm) state.pimcoreEditIntegrations = integrationContext;
  if (form === pimcoreCreateForm) {
    state.pimcoreCreateIntegrationContextId = String(result.integration_context_id || "");
  }
  if (form === pimcoreEditForm) {
    state.pimcoreEditIntegrationContextId = String(result.integration_context_id || "");
  }
  for (const source of renderedTargets) {
    const input = form.elements[source];
    if (input && Object.prototype.hasOwnProperty.call(result.values || {}, source)) {
      if (!input.value) {
        input.value = result.values[source] ?? "";
      } else if (form.dataset.pimcoreMode === "apply") {
        input.value = result.values[source] ?? "";
      }
      updatePimcoreRuntimeFieldChangeState(input);
    }
  }
  updatePimcoreRuntimeCalculatedState(form, result, schema);
  await validatePimcoreOcrFields(form, schema, validationTargets);
  return result;
}

function pimcoreEditHasRuntimeTemplates() {
  return (state.pimcoreEditSchema || []).some(pimcoreMappingHasRuntimeTemplate);
}

function pimcoreCreateHasRuntimeTemplates() {
  return (state.pimcoreCreateSchema || []).some(pimcoreMappingHasRuntimeTemplate);
}

async function recalculateAllPimcoreCreateFields() {
  if (!pimcoreCreateForm || !pimcoreCreateHasRuntimeTemplates()) return;
  if (pimcoreCreateRecalculateAllButton) pimcoreCreateRecalculateAllButton.disabled = true;
  if (pimcoreCreateStatus) pimcoreCreateStatus.textContent = "Przeliczanie wszystkich pol...";
  try {
    const result = await renderPimcoreRuntimeTemplates(pimcoreCreateForm, state.pimcoreCreateSchema);
    if (pimcoreCreateStatus) {
      pimcoreCreateStatus.textContent = pimcoreRuntimeRecalculateStatus(pimcoreCreateForm, result);
    }
  } catch (error) {
    if (pimcoreCreateStatus) pimcoreCreateStatus.textContent = error.message;
  } finally {
    if (pimcoreCreateRecalculateAllButton) {
      pimcoreCreateRecalculateAllButton.disabled = !pimcoreCreateHasRuntimeTemplates();
    }
  }
}

async function recalculateAllPimcoreEditFields() {
  if (!pimcoreEditForm || !pimcoreEditHasRuntimeTemplates()) return;
  if (pimcoreEditRecalculateAllButton) pimcoreEditRecalculateAllButton.disabled = true;
  if (pimcoreEditStatus) pimcoreEditStatus.textContent = "Przeliczanie wszystkich pol...";
  try {
    const result = await renderPimcoreRuntimeTemplates(pimcoreEditForm, state.pimcoreEditSchema);
    if (pimcoreEditStatus) {
      pimcoreEditStatus.textContent = pimcoreRuntimeRecalculateStatus(pimcoreEditForm, result);
    }
  } catch (error) {
    if (pimcoreEditStatus) pimcoreEditStatus.textContent = error.message;
  } finally {
    if (pimcoreEditRecalculateAllButton) {
      pimcoreEditRecalculateAllButton.disabled = !pimcoreEditHasRuntimeTemplates();
    }
  }
}

function openPimcoreWriteTest() {
  if (!pimcoreTestForm || !pimcoreTestModal) return;
  pimcoreTestModal.querySelectorAll('[name="pimcore_cleanup_policy"]').forEach((item) => {
    item.checked = false;
  });
  clearPimcoreLiveLog();
  pimcoreTestModal.classList.add("active");
  loadPimcoreTestSample();
}

async function loadPimcoreTestSample() {
  if (!pimcoreTestForm) return;
  pimcoreTestSubmitButton.disabled = true;
  pimcoreTestClearButton.disabled = true;
  pimcoreTestRegenerateButton.disabled = true;
  pimcoreTestStatus.textContent = "Generowanie unikalnych danych testowych...";
  try {
    const sample = await requestJson("/api/settings/pimcore/test-sample", { method: "POST" });
    pimcoreTestForm.dataset.pimcoreMode = "test";
    populatePimcoreRuntimeForm(
      pimcoreTestForm,
      sample.form_schema || [],
      sample.values || {},
      { idPrefix: "pimcoreTest" }
    );
    pimcoreTestStatus.textContent = pimcoreRuntimeWarnings(sample.warnings);
  } catch (error) {
    pimcoreTestForm.textContent = "";
    pimcoreTestStatus.textContent = `Nie mozna wygenerowac danych testowych: ${error.message}`;
  } finally {
    pimcoreTestSubmitButton.disabled = false;
    pimcoreTestClearButton.disabled = false;
    pimcoreTestRegenerateButton.disabled = false;
  }
}

function collectPimcoreTestValues() {
  if (!pimcoreTestForm) return {};
  return Object.fromEntries(
    [...pimcoreTestForm.querySelectorAll("input[name]")].map((input) => [input.name, input.value])
  );
}

function clearPimcoreLiveLog() {
  state.pimcoreLiveEvents = [];
  if (!pimcoreLiveLog || !pimcoreTestElapsed || !pimcoreTestStatus) return;
  pimcoreLiveLog.textContent = "Brak operacji.";
  pimcoreLiveLog.className = "pimcore-live-log empty-state";
  pimcoreTestElapsed.textContent = "0 ms";
  pimcoreTestStatus.textContent = "";
}

function renderPimcoreLiveEvents() {
  if (!pimcoreLiveLog) return;
  const wasAtBottom =
    pimcoreLiveLog.scrollHeight - pimcoreLiveLog.scrollTop - pimcoreLiveLog.clientHeight < 24;
  pimcoreLiveLog.textContent = "";
  if (!state.pimcoreLiveEvents.length) {
    pimcoreLiveLog.textContent = "Brak operacji.";
    pimcoreLiveLog.className = "pimcore-live-log empty-state";
    return;
  }
  pimcoreLiveLog.className = "pimcore-live-log";
  for (const event of state.pimcoreLiveEvents) {
    const row = document.createElement("div");
    const heading = document.createElement("strong");
    const detail = document.createElement("span");
    const diagnostic = document.createElement("pre");
    row.className = `pimcore-live-event ${event.severity || "info"}`;
    heading.textContent =
      `[${formatPanelTimestamp(event.timestamp, {
        date: false,
        epochUnit: "seconds",
      })}] ${event.stage || "etap"}: ${event.message || ""}`;
    detail.textContent = [
      event.method,
      event.endpoint,
      event.status_code ? `HTTP ${event.status_code}` : "",
      `od startu ${Number(event.elapsed_ms || 0)} ms`,
      event.stage_elapsed_ms !== undefined ? `etap ${Number(event.stage_elapsed_ms || 0)} ms` : "",
    ]
      .filter(Boolean)
      .join(" | ");
    diagnostic.textContent = [
      event.response_excerpt,
      event.suggested_fix,
      event.error ? JSON.stringify(event.error, null, 2) : "",
    ]
      .filter(Boolean)
      .join("\n");
    row.append(heading, detail);
    if (diagnostic.textContent) row.appendChild(diagnostic);
    pimcoreLiveLog.appendChild(row);
  }
  if (wasAtBottom) pimcoreLiveLog.scrollTop = pimcoreLiveLog.scrollHeight;
}

function appendPimcoreLiveEvents(events) {
  const rows = Array.isArray(events) ? events : [];
  if (!rows.length) return;
  state.pimcoreLiveEvents.push(...rows);
  renderPimcoreLiveEvents();
}

function pimcoreTestObjectKey(template, values) {
  const missing = [];
  const rendered = String(template || "{EAN}").replace(/\{([^{}]+)\}/g, (_match, source) => {
    const value = String(values[source] || "").trim();
    if (!value) missing.push(source);
    return value;
  });
  if (missing.length) {
    throw new Error(`Brak wartosci dla klucza: ${[...new Set(missing)].join(", ")}`);
  }
  const key = rendered.replace(/[^0-9A-Za-z_.-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "");
  if (!key) throw new Error("Nie mozna zbudowac klucza obiektu Pimcore.");
  return key.slice(0, 190);
}

async function submitPimcoreWriteTest() {
  if (!pimcoreTestForm || !pimcoreTestModal) return;
  if (!pimcoreTestForm.reportValidity()) return;
  const cleanup =
    pimcoreTestModal.querySelector('[name="pimcore_cleanup_policy"]:checked')?.value || "";
  if (!cleanup) {
    throw new Error("Wybierz, czy obiekt ma zostac usuniety po tescie.");
  }
  const values = collectPimcoreTestValues();
  const target = state.settings?.pimcore || {};
  const objectKey = pimcoreTestObjectKey(target.object_key_template, values);
  if (
    !window.confirm(
      `Wyslac obiekt do ${target.base_url}, klasa ${target.class_name}, parent ${target.parent_id}, klucz ${objectKey}, tryb ${cleanup}?`
    )
  ) {
    return;
  }
  pimcoreTestSubmitButton.disabled = true;
  pimcoreTestClearButton.disabled = true;
  pimcoreTestRegenerateButton.disabled = true;
  clearPimcoreLiveLog();
  const payload = await requestJson("/api/settings/pimcore/test-create-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values, cleanup_policy: cleanup }),
  });
  state.pimcoreTestOperation = {
    operationId: payload.operation.operation_id,
    lastSequence: 0,
    active: true,
  };
  await pollPimcoreTestOperation();
}

async function pollPimcoreTestOperation() {
  const tracked = state.pimcoreTestOperation;
  if (!tracked?.active) return;
  try {
    const params = new URLSearchParams({ after_sequence: String(tracked.lastSequence || 0) });
    const payload = await requestJson(
      `/api/settings/pimcore/test-create-runs/${encodeURIComponent(tracked.operationId)}?${params.toString()}`
    );
    appendPimcoreLiveEvents(payload.events || []);
    for (const event of payload.events || []) {
      tracked.lastSequence = Math.max(tracked.lastSequence, Number(event.sequence || 0));
    }
    if (pimcoreTestElapsed) {
      pimcoreTestElapsed.textContent = formatDuration(payload.total_ms || 0);
    }
    if (["completed", "partial", "failed"].includes(payload.status)) {
      tracked.active = false;
      pimcoreTestSubmitButton.disabled = false;
      pimcoreTestClearButton.disabled = false;
      pimcoreTestRegenerateButton.disabled = false;
      pimcoreTestStatus.textContent = `Wynik: ${payload.status}. Operacja ${payload.operation_id}.`;
      return;
    }
  } catch (error) {
    appendPimcoreLiveEvents([
      {
        sequence: tracked.lastSequence,
        severity: "warning",
        stage: "poll",
        message: `Utrata polaczenia z logiem: ${error.message}`,
      },
    ]);
  }
  window.setTimeout(pollPimcoreTestOperation, 500);
}

function renderPimcoreHistory(items) {
  if (!pimcoreHistoryOutput) return;
  const rows = Array.isArray(items) ? items : [];
  state.pimcoreHistoryItems = rows;
  pimcoreHistoryOutput.textContent = "";
  pimcoreHistoryOutput.className = rows.length ? "history-output" : "history-output empty-state";
  if (!rows.length) {
    pimcoreHistoryOutput.textContent = "Brak operacji Pimcore dla wybranego filtra.";
    return;
  }
  for (const item of rows) {
    const row = document.createElement("div");
    const toggle = document.createElement("button");
    const title = document.createElement("strong");
    const meta = document.createElement("span");
    const details = document.createElement("div");
    const resultPayload = item.result?.payload || {};
    row.className = "pimcore-history-row";
    toggle.type = "button";
    toggle.className = "history-summary-row";
    title.textContent = `${item.operation_type || "operacja"} | ${item.status || "unknown"} | ${
      item.operation_id || ""
    }`;
    meta.textContent = [
      formatPanelTimestamp(item.started_at, { epochUnit: "seconds" }),
      item.username,
      `${Number(item.total_ms || 0)} ms`,
      `klasa ${resultPayload.className || "brak"}`,
      `parent ${resultPayload.parentId || "brak"}`,
      `obiekt ${item.result?.object_id || item.result?.object?.id || "brak"}`,
      item.result?.object_path || item.result?.object?.path || "",
    ]
      .filter(Boolean)
      .join(" | ");
    details.className = "pimcore-history-event-details";
    details.hidden = true;
    for (const event of item.events || []) {
      const line = document.createElement("div");
      line.textContent = [
        `${event.sequence}. ${event.stage}: ${event.message}`,
        event.method,
        event.endpoint,
        event.status_code ? `HTTP ${event.status_code}` : "",
        `od startu ${Number(event.elapsed_ms || 0)} ms`,
        event.stage_elapsed_ms !== undefined ? `etap ${Number(event.stage_elapsed_ms || 0)} ms` : "",
        event.response_excerpt,
        event.suggested_fix,
      ]
        .filter(Boolean)
        .join(" | ");
      details.appendChild(line);
    }
    toggle.addEventListener("click", () => {
      details.hidden = !details.hidden;
    });
    toggle.append(title, meta);
    row.append(toggle, details);
    pimcoreHistoryOutput.appendChild(row);
  }
}

async function loadPimcoreHistory() {
  if (!pimcoreHistoryFilters) return;
  const data = new FormData(pimcoreHistoryFilters);
  const params = new URLSearchParams();
  for (const key of ["operation_type", "result", "user", "query"]) {
    const value = String(data.get(key) || "").trim();
    if (value) params.set(key, value);
  }
  const from = String(data.get("date_from") || "");
  const to = String(data.get("date_to") || "");
  if (from) params.set("date_from", String(new Date(`${from}T00:00:00`).getTime() / 1000));
  if (to) params.set("date_to", String(new Date(`${to}T23:59:59`).getTime() / 1000));
  const payload = await requestJson(`/api/settings/pimcore/operations?${params.toString()}`);
  renderPimcoreHistory(payload.items || []);
}

function openPimcoreExportModal() {
  pimcoreExportModal?.classList.add("active");
}

function closePimcoreExportModal() {
  pimcoreExportModal?.classList.remove("active");
}

function pimcoreExportFieldMappings() {
  return (state.settings?.pimcore?.field_mappings || []).filter((mapping) => mapping?.pimcore_field);
}

function collectPimcoreExportColumns() {
  if (!pimcoreExportLayoutList) return [];
  return [...pimcoreExportLayoutList.querySelectorAll(".pimcore-export-layout-row")].map((row) => {
    const header = row.querySelector('[name="export_header"]')?.value.trim() || "";
    if (row.dataset.columnType === "blank") return { type: "blank", header };
    return {
      type: "field",
      pimcore_field: row.querySelector('[name="export_pimcore_field"]')?.value || "",
      header,
    };
  });
}

function pimcoreExportColumnsFromEditor() {
  pimcoreExportLayoutDraft = collectPimcoreExportColumns();
  return pimcoreExportLayoutDraft;
}

function clearPimcoreExportLayoutSelection() {
  pimcoreExportLayoutSelection.clear();
}

function selectedPimcoreExportColumnIndexes() {
  return [...pimcoreExportLayoutSelection]
    .filter((index) => index >= 0 && index < pimcoreExportLayoutDraft.length)
    .sort((left, right) => left - right);
}

function selectPimcoreExportColumn(index, additive = false) {
  if (!additive) clearPimcoreExportLayoutSelection();
  if (additive && pimcoreExportLayoutSelection.has(index)) {
    pimcoreExportLayoutSelection.delete(index);
  } else {
    pimcoreExportLayoutSelection.add(index);
  }
}

function insertPimcoreExportBlankColumn(index) {
  pimcoreExportColumnsFromEditor();
  const insertionIndex = Math.max(0, Math.min(index, pimcoreExportLayoutDraft.length));
  const retainedSelection = selectedPimcoreExportColumnIndexes().map((selectedIndex) =>
    selectedIndex >= insertionIndex ? selectedIndex + 1 : selectedIndex
  );
  clearPimcoreExportLayoutSelection();
  retainedSelection.forEach((selectedIndex) => pimcoreExportLayoutSelection.add(selectedIndex));
  pimcoreExportLayoutDraft.splice(insertionIndex, 0, { type: "blank", header: "" });
  renderPimcoreExportLayout();
}

function pimcoreExportLayoutDropIndexIsNoop(dropIndex) {
  const selectedIndexes = selectedPimcoreExportColumnIndexes();
  if (!selectedIndexes.length) return true;
  const isContiguous = selectedIndexes.every((index, offset) => index === selectedIndexes[0] + offset);
  if (!isContiguous) return false;
  return dropIndex >= selectedIndexes[0] && dropIndex <= selectedIndexes[selectedIndexes.length - 1] + 1;
}

function movePimcoreExportColumns(dropIndex) {
  pimcoreExportColumnsFromEditor();
  const selectedIndexes = selectedPimcoreExportColumnIndexes();
  if (!selectedIndexes.length) return;
  const selectedSet = new Set(selectedIndexes);
  const movingColumns = selectedIndexes.map((index) => pimcoreExportLayoutDraft[index]);
  const remainingColumns = pimcoreExportLayoutDraft.filter((_, index) => !selectedSet.has(index));
  const adjustedDropIndex = Math.max(
    0,
    Math.min(dropIndex - selectedIndexes.filter((index) => index < dropIndex).length, remainingColumns.length)
  );
  const nextColumns = [
    ...remainingColumns.slice(0, adjustedDropIndex),
    ...movingColumns,
    ...remainingColumns.slice(adjustedDropIndex),
  ];
  if (nextColumns.every((column, index) => column === pimcoreExportLayoutDraft[index])) return;
  pimcoreExportLayoutDraft = nextColumns;
  clearPimcoreExportLayoutSelection();
  movingColumns.forEach((_, index) => pimcoreExportLayoutSelection.add(adjustedDropIndex + index));
  renderPimcoreExportLayout();
}

function finishPimcoreExportLayoutDrag() {
  pimcoreExportLayoutDragState = null;
  pimcoreExportLayoutList?.classList.remove("pimcore-export-layout-dragging");
  pimcoreExportLayoutList
    ?.querySelectorAll(".pimcore-export-layout-drop-target")
    .forEach((zone) => zone.classList.remove("pimcore-export-layout-drop-target"));
}

function startPimcoreExportLayoutMarquee(event) {
  const startsOnFreeListSpace = event.target === pimcoreExportLayoutList || event.target.classList?.contains("pimcore-export-layout-insert");
  if (!pimcoreExportLayoutList || event.button !== 0 || !startsOnFreeListSpace) return;
  const listBounds = pimcoreExportLayoutList.getBoundingClientRect();
  const initialSelection = event.ctrlKey ? new Set(pimcoreExportLayoutSelection) : new Set();
  const marquee = document.createElement("div");
  marquee.className = "pimcore-export-layout-marquee";
  pimcoreExportLayoutList.appendChild(marquee);
  pimcoreExportLayoutMarquee = { eventPointerId: event.pointerId, marquee, initialSelection, startX: event.clientX, startY: event.clientY };
  pimcoreExportLayoutList.setPointerCapture?.(event.pointerId);

  const update = (pointerEvent) => {
    if (!pimcoreExportLayoutMarquee || pointerEvent.pointerId !== pimcoreExportLayoutMarquee.eventPointerId) return;
    const left = Math.min(pimcoreExportLayoutMarquee.startX, pointerEvent.clientX);
    const top = Math.min(pimcoreExportLayoutMarquee.startY, pointerEvent.clientY);
    const right = Math.max(pimcoreExportLayoutMarquee.startX, pointerEvent.clientX);
    const bottom = Math.max(pimcoreExportLayoutMarquee.startY, pointerEvent.clientY);
    Object.assign(marquee.style, {
      left: `${left - listBounds.left}px`,
      top: `${top - listBounds.top}px`,
      width: `${right - left}px`,
      height: `${bottom - top}px`,
    });
    const nextSelection = new Set(pimcoreExportLayoutMarquee.initialSelection);
    pimcoreExportLayoutList.querySelectorAll(".pimcore-export-layout-row").forEach((row) => {
      const rowBounds = row.getBoundingClientRect();
      const intersects = rowBounds.right >= left && rowBounds.left <= right && rowBounds.bottom >= top && rowBounds.top <= bottom;
      if (intersects) nextSelection.add(Number(row.dataset.index));
    });
    clearPimcoreExportLayoutSelection();
    nextSelection.forEach((index) => pimcoreExportLayoutSelection.add(index));
    pimcoreExportLayoutList.querySelectorAll(".pimcore-export-layout-row").forEach((row) => {
      row.classList.toggle("pimcore-export-layout-selected", pimcoreExportLayoutSelection.has(Number(row.dataset.index)));
    });
  };
  const finish = (pointerEvent) => {
    if (!pimcoreExportLayoutMarquee || pointerEvent.pointerId !== pimcoreExportLayoutMarquee.eventPointerId) return;
    marquee.remove();
    pimcoreExportLayoutMarquee = null;
    pimcoreExportLayoutList.releasePointerCapture?.(pointerEvent.pointerId);
    pimcoreExportLayoutList.removeEventListener("pointermove", update);
    pimcoreExportLayoutList.removeEventListener("pointerup", finish);
    pimcoreExportLayoutList.removeEventListener("pointercancel", finish);
  };
  pimcoreExportLayoutList.addEventListener("pointermove", update);
  pimcoreExportLayoutList.addEventListener("pointerup", finish);
  pimcoreExportLayoutList.addEventListener("pointercancel", finish);
}

function createPimcoreExportLayoutInsertZone(index) {
  const zone = document.createElement("div");
  const insert = document.createElement("button");
  zone.className = "pimcore-export-layout-insert";
  zone.dataset.dropIndex = String(index);
  insert.type = "button";
  insert.className = "pimcore-export-layout-insert-button";
  insert.textContent = "+";
  insert.title = "Wstaw pustą kolumnę w tym miejscu";
  insert.setAttribute("aria-label", `Wstaw pustą kolumnę przed pozycją ${index + 1}`);
  insert.addEventListener("pointerdown", (event) => event.stopPropagation());
  insert.addEventListener("click", () => insertPimcoreExportBlankColumn(index));
  zone.addEventListener("dragover", (event) => {
    if (!pimcoreExportLayoutDragState || pimcoreExportLayoutDropIndexIsNoop(index)) return;
    event.preventDefault();
    zone.classList.add("pimcore-export-layout-drop-target");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("pimcore-export-layout-drop-target"));
  zone.addEventListener("drop", (event) => {
    if (!pimcoreExportLayoutDragState || pimcoreExportLayoutDropIndexIsNoop(index)) return;
    event.preventDefault();
    movePimcoreExportColumns(index);
    finishPimcoreExportLayoutDrag();
  });
  zone.appendChild(insert);
  return zone;
}

function renderPimcoreExportLayout() {
  if (!pimcoreExportLayoutList) return;
  pimcoreExportLayoutList.textContent = "";
  const mappings = pimcoreExportFieldMappings();
  const usedFields = new Set(
    pimcoreExportLayoutDraft
      .filter((column) => column.type === "field")
      .map((column) => String(column.pimcore_field || ""))
  );
  pimcoreExportLayoutList.className = `pimcore-export-layout-list${pimcoreExportLayoutDraft.length ? "" : " empty-state"}`;
  pimcoreExportLayoutList.appendChild(createPimcoreExportLayoutInsertZone(0));
  if (!pimcoreExportLayoutDraft.length) {
    const empty = document.createElement("p");
    empty.className = "pimcore-export-layout-empty-message";
    empty.textContent = "Dodaj pole Pimcore albo pustą kolumnę.";
    pimcoreExportLayoutList.appendChild(empty);
  }
  pimcoreExportLayoutDraft.forEach((column, index) => {
    const row = document.createElement("div");
    const position = document.createElement("span");
    const label = document.createElement("span");
    const header = document.createElement("input");
    const remove = document.createElement("button");
    row.className = `pimcore-export-layout-row${pimcoreExportLayoutSelection.has(index) ? " pimcore-export-layout-selected" : ""}`;
    row.dataset.columnType = column.type;
    row.dataset.index = String(index);
    row.draggable = true;
    position.textContent = String(index + 1);
    position.className = "pimcore-export-layout-position pimcore-export-layout-grip";
    position.title = "Kliknij z Ctrl, aby zaznaczyć. Przeciągnij zaznaczone pozycje.";
    header.name = "export_header";
    header.value = column.header || "";
    header.placeholder = "Nagłówek kolumny";
    header.setAttribute("aria-label", `Nagłówek kolumny ${index + 1}`);
    remove.type = "button";
    remove.className = "ghost-button";
    remove.textContent = "Usuń";
    remove.addEventListener("click", () => {
      pimcoreExportColumnsFromEditor();
      pimcoreExportLayoutDraft.splice(index, 1);
      const retainedSelection = selectedPimcoreExportColumnIndexes()
        .filter((selectedIndex) => selectedIndex !== index)
        .map((selectedIndex) => (selectedIndex > index ? selectedIndex - 1 : selectedIndex));
      clearPimcoreExportLayoutSelection();
      retainedSelection.forEach((selectedIndex) => pimcoreExportLayoutSelection.add(selectedIndex));
      renderPimcoreExportLayout();
    });
    row.addEventListener("mousedown", (event) => {
      if (event.button !== 0 || !event.target.closest(".pimcore-export-layout-grip")) return;
      if (event.ctrlKey) {
        selectPimcoreExportColumn(index, true);
      } else if (!pimcoreExportLayoutSelection.has(index)) {
        selectPimcoreExportColumn(index);
      }
      row.classList.toggle("pimcore-export-layout-selected", pimcoreExportLayoutSelection.has(index));
      if (!event.ctrlKey && pimcoreExportLayoutSelection.size === 1) {
        pimcoreExportLayoutList.querySelectorAll(".pimcore-export-layout-row").forEach((candidate) => {
          if (candidate !== row) candidate.classList.remove("pimcore-export-layout-selected");
        });
      }
    });
    row.addEventListener("dragstart", (event) => {
      if (event.target.closest("button, input, select")) {
        event.preventDefault();
        return;
      }
      if (!pimcoreExportLayoutSelection.has(index)) selectPimcoreExportColumn(index);
      pimcoreExportLayoutDragState = { indexes: selectedPimcoreExportColumnIndexes() };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "pimcore-export-columns");
      pimcoreExportLayoutList.classList.add("pimcore-export-layout-dragging");
      pimcoreExportLayoutList.querySelectorAll(".pimcore-export-layout-row").forEach((candidate) => {
        candidate.classList.toggle("pimcore-export-layout-selected", pimcoreExportLayoutSelection.has(Number(candidate.dataset.index)));
      });
    });
    row.addEventListener("dragend", finishPimcoreExportLayoutDrag);
    if (column.type === "blank") {
      label.textContent = "Pusta kolumna";
      label.className = "pimcore-export-layout-kind";
      header.classList.add("pimcore-export-layout-blank-header");
      row.append(position, label, header, remove);
    } else {
      const field = document.createElement("select");
      field.name = "export_pimcore_field";
      field.setAttribute("aria-label", `Pole Pimcore w kolumnie ${index + 1}`);
      for (const mapping of mappings) {
        const option = document.createElement("option");
        const fieldName = String(mapping.pimcore_field || "");
        option.value = fieldName;
        option.textContent = fieldName;
        option.selected = fieldName === column.pimcore_field;
        option.disabled = usedFields.has(fieldName) && !option.selected;
        field.appendChild(option);
      }
      label.textContent = "Pole Pimcore";
      label.className = "pimcore-export-layout-kind";
      row.append(position, label, field, header, remove);
    }
    pimcoreExportLayoutList.appendChild(row);
    pimcoreExportLayoutList.appendChild(createPimcoreExportLayoutInsertZone(index + 1));
  });
  if (pimcoreExportLayoutAddFieldButton) {
    pimcoreExportLayoutAddFieldButton.disabled = mappings.every((mapping) =>
      usedFields.has(String(mapping.pimcore_field || ""))
    );
  }
}

function openPimcoreExportLayoutModal() {
  const columns = state.settings?.pimcore?.export_columns || [];
  pimcoreExportLayoutDraft = columns.map((column) => ({ ...column }));
  clearPimcoreExportLayoutSelection();
  renderPimcoreExportLayout();
  pimcoreExportLayoutModal?.classList.add("active");
}

function closePimcoreExportLayoutModal() {
  clearPimcoreExportLayoutSelection();
  finishPimcoreExportLayoutDrag();
  pimcoreExportLayoutModal?.classList.remove("active");
}

async function savePimcoreExportColumns() {
  if (!pimcoreExportLayoutSaveButton || !state.settings?.pimcore) return;
  const export_columns = collectPimcoreExportColumns();
  pimcoreExportLayoutSaveButton.disabled = true;
  settingsStatus.textContent = "Zapisywanie układu eksportu...";
  try {
    state.settings = await requestJson("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pimcore: { ...state.settings.pimcore, export_columns },
      }),
      timeoutMs: 60000,
    });
    settingsStatus.textContent = "Zapisano układ eksportu Pimcore.";
    closePimcoreExportLayoutModal();
  } catch (error) {
    settingsStatus.textContent = error.message;
  } finally {
    pimcoreExportLayoutSaveButton.disabled = false;
  }
}

function pimcoreHistoryExportParams(format, options = {}) {
  const params = new URLSearchParams({ format });
  if (options.includeFilters === false || !pimcoreHistoryFilters) {
    return params;
  }
  const data = new FormData(pimcoreHistoryFilters);
  for (const key of ["operation_type", "result", "user", "query"]) {
    const value = String(data.get(key) || "").trim();
    if (value) params.set(key === "result" ? "status" : key, value);
  }
  const from = String(data.get("date_from") || "").trim();
  const to = String(data.get("date_to") || "").trim();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  return params;
}

function exportPimcoreSubmissions(format = "", options = {}) {
  const selectedFormat = String(format || "").toLowerCase();
  if (!selectedFormat) {
    openPimcoreExportModal();
    return;
  }
  const params = pimcoreHistoryExportParams(selectedFormat, options);
  window.location.href = `/api/settings/pimcore/submissions/export?${params.toString()}`;
}

async function openPimcoreHistory() {
  if (!pimcoreHistoryModal) return;
  pimcoreHistoryModal.classList.add("active");
  await loadPimcoreHistory();
}

function applyPimcoreRuntimeCapabilities(capabilities = {}) {
  state.pimcoreRuntimeEnabled = capabilities.enabled === true;
  state.pimcoreExistingObject = null;
  state.pimcoreLastCheckedEan = "";
  state.pimcoreMissingEan = "";
  state.pimcoreCreateSchema = [];
  if (pimcoreEditButton) {
    pimcoreEditButton.hidden = !state.pimcoreRuntimeEnabled;
    pimcoreEditButton.disabled = true;
    pimcoreEditButton.title = "";
  }
}

function handlePimcoreEanInput() {
  state.pimcoreExistingObject = null;
  state.pimcoreLastCheckedEan = "";
  state.pimcoreMissingEan = "";
  state.pimcoreCreateSchema = [];
  if (pimcoreEditButton) {
    pimcoreEditButton.disabled = true;
    pimcoreEditButton.title = "";
  }
  if (!state.pimcoreRuntimeEnabled) return;
  schedulePimcoreStatusLookup();
}

function schedulePimcoreStatusLookup() {
  if (!state.pimcoreRuntimeEnabled) return;
  window.clearTimeout(state.pimcoreLookupTimer);
  const ean = productForm.elements.ean.value.trim();
  if (!/^\d{13}$/.test(ean) || ean === state.pimcoreLastCheckedEan) return;
  state.pimcoreLookupTimer = window.setTimeout(() => {
    checkPimcoreProductStatus(ean).catch((error) => {
      formStatus.textContent = `Nie mozna sprawdzic Pimcore: ${error.message}. Mozesz kontynuowac prace.`;
    });
  }, 500);
}

async function checkPimcoreProductStatus(ean) {
  const requestId = ++state.pimcoreLookupRequestId;
  const payload = await requestJson(`/api/pimcore/product-status?ean=${encodeURIComponent(ean)}`);
  if (requestId !== state.pimcoreLookupRequestId || productForm.elements.ean.value.trim() !== ean) {
    return;
  }
  state.pimcoreLastCheckedEan = ean;
  if (!payload.enabled) {
    state.pimcoreExistingObject = null;
    if (pimcoreEditButton) {
      pimcoreEditButton.disabled = true;
      pimcoreEditButton.title = "";
    }
    return;
  }
  if (payload.available === false) {
    state.pimcoreExistingObject = null;
    if (pimcoreEditButton) {
      pimcoreEditButton.disabled = true;
      pimcoreEditButton.title = "";
    }
    formStatus.textContent = `Pimcore niedostepny: ${payload.error?.message || "blad polaczenia"}`;
    return;
  }
  if (payload.exists) {
    const objectId = Number(payload.object?.id || 0);
    if (objectId > 0) {
      state.pimcoreExistingObject = payload.object || null;
      if (pimcoreEditButton) {
        pimcoreEditButton.disabled = false;
        pimcoreEditButton.title = "";
      }
      return;
    }
    state.pimcoreExistingObject = null;
    if (pimcoreEditButton) {
      pimcoreEditButton.disabled = true;
      pimcoreEditButton.title = "";
    }
    formStatus.textContent = "Pimcore zwrocil produkt bez poprawnego ID. Edycja jest niedostepna.";
    return;
  }
  state.pimcoreExistingObject = null;
  state.pimcoreCreateSchema = Array.isArray(payload.form_schema) ? payload.form_schema : [];
  state.pimcoreMissingEan = ean;
  if (pimcoreEditButton) {
    pimcoreEditButton.disabled = state.pimcoreCreateSchema.length === 0;
    pimcoreEditButton.title = state.pimcoreCreateSchema.length
      ? "Otworz formularz dodania produktu Pimcore."
      : "";
  }
  pimcoreMissingMessage.textContent = `EAN ${ean} nie istnieje w Pimcore. Czy dodac produkt?`;
  pimcoreMissingModal.classList.add("active");
}

function openPimcoreCreateModal(ean) {
  if (!pimcoreCreateForm || !pimcoreCreateModal) return;
  pimcoreCreateForm.dataset.pimcoreMode = "create";
  state.pimcoreCreateIntegrations = { sql_profiles: [] };
  state.pimcoreCreateIntegrationContextId = "";
  const values = Object.fromEntries(
    (state.pimcoreCreateSchema || []).map((mapping) => [
      mapping.source,
      mapping.source === "EAN" ? ean : mapping.default || "",
    ])
  );
  populatePimcoreRuntimeForm(
    pimcoreCreateForm,
    state.pimcoreCreateSchema,
    values,
    {
      readOnlySources: ["EAN"],
      allowRecalculate: true,
      status: pimcoreCreateStatus,
      idPrefix: "pimcoreCreate",
    }
  );
  updatePimcoreCreateSubmitState();
  const pimcoreCreateEan = pimcoreCreateForm.querySelector("#pimcoreCreateEan");
  if (pimcoreCreateEan) pimcoreCreateEan.readOnly = true;
  if (pimcoreCreateRecalculateAllButton) {
    pimcoreCreateRecalculateAllButton.disabled = !pimcoreCreateHasRuntimeTemplates();
  }
  if (pimcoreCreateStatus) pimcoreCreateStatus.textContent = "";
  pimcoreMissingModal?.classList.remove("active");
  pimcoreCreateModal.classList.add("active");
  refreshOpenPimcoreOcrPanels().catch(() => {});
  renderPimcoreRuntimeTemplates(pimcoreCreateForm, state.pimcoreCreateSchema)
    .then((result) => {
      if (pimcoreCreateStatus) {
        pimcoreCreateStatus.textContent = pimcoreRuntimeRecalculateStatus(pimcoreCreateForm, result);
      }
    })
    .catch((error) => {
      if (pimcoreCreateStatus) {
        pimcoreCreateStatus.textContent = `Nie przeliczono szablonow: ${error.message}`;
      }
    });
}

async function submitPimcoreRuntimeCreate(event) {
  event.preventDefault();
  if (!pimcoreCreateForm.reportValidity()) return;
  if (blockPimcoreRuntimeSubmitIfNeeded(pimcoreCreateForm, pimcoreCreateStatus)) return;
  pimcoreCreateSubmitButton.disabled = true;
  pimcoreCreateStatus.textContent = "Zapisywanie w Pimcore...";
  try {
    const values = Object.fromEntries(new FormData(pimcoreCreateForm).entries());
    const payload = await requestJson("/api/pimcore/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        values,
        integration_context_id: state.pimcoreCreateIntegrationContextId,
      }),
      timeoutMs: 120000,
    });
    const object = payload.object || {};
    pimcoreCreateModal.classList.remove("active");
    state.pimcoreLastCheckedEan = state.pimcoreMissingEan || values.EAN || "";
    formStatus.textContent = payload.duplicate
      ? `EAN juz istnieje w Pimcore: ${object.path || object.id}.`
      : `Utworzono produkt Pimcore: ${object.path || object.id}. Mozesz kontynuowac dodawanie zdjec.`;
  } catch (error) {
    pimcoreCreateStatus.textContent = error.message;
  } finally {
    pimcoreCreateSubmitButton.disabled = false;
  }
}

async function openPimcoreEditModal() {
  let objectId = Number(state.pimcoreExistingObject?.id || 0);
  const currentEan = productForm.elements.ean.value.trim();
  if (objectId <= 0 && state.pimcoreRuntimeEnabled) {
    if (/^\d{13}$/.test(currentEan)) {
      formStatus.textContent = "Sprawdzanie produktu Pimcore...";
      try {
        await checkPimcoreProductStatus(currentEan);
      } catch (error) {
        formStatus.textContent = `Nie mozna sprawdzic Pimcore: ${error.message}.`;
        return;
      }
      objectId = Number(state.pimcoreExistingObject?.id || 0);
    }
  }
  if (
    objectId <= 0 &&
    state.pimcoreCreateSchema.length &&
    /^\d{13}$/.test(state.pimcoreMissingEan || currentEan)
  ) {
    openPimcoreCreateModal(state.pimcoreMissingEan || currentEan);
    return;
  }
  if (objectId <= 0) {
    formStatus.textContent = "Nie mozna edytowac produktu Pimcore bez poprawnego ID.";
    return;
  }
  if (!pimcoreEditForm || !pimcoreEditModal) return;
  const requestId = ++state.pimcoreEditRequestId;
  if (pimcoreEditButton) pimcoreEditButton.disabled = true;
  state.pimcoreEditObjectId = 0;
  state.pimcoreEditMarker = "";
  state.pimcoreEditIntegrations = { sql_profiles: [] };
  state.pimcoreEditIntegrationContextId = "";
  pimcoreEditForm.textContent = "";
  pimcoreEditObjectInfo.textContent = `ID ${objectId}`;
  pimcoreEditStatus.textContent = "Pobieranie danych Pimcore...";
  pimcoreEditSubmitButton.disabled = true;
  if (pimcoreEditRecalculateAllButton) pimcoreEditRecalculateAllButton.disabled = true;
  pimcoreEditModal.classList.add("active");
  try {
    const payload = await requestJson(`/api/pimcore/products/${encodeURIComponent(objectId)}`);
    if (requestId !== state.pimcoreEditRequestId) return;
    state.pimcoreEditObjectId = Number(payload.object?.id || objectId);
    if (!Number.isInteger(state.pimcoreEditObjectId) || state.pimcoreEditObjectId <= 0) {
      throw new Error("Pimcore zwrocil niepoprawny identyfikator obiektu.");
    }
    state.pimcoreEditMarker = String(payload.marker || "");
    state.pimcoreEditSchema = Array.isArray(payload.form_schema) ? payload.form_schema : [];
    pimcoreEditForm.dataset.pimcoreMode = "edit";
    populatePimcoreRuntimeForm(
      pimcoreEditForm,
      state.pimcoreEditSchema,
      payload.values || {},
      {
        readOnlySources: ["EAN"],
        allowRecalculate: true,
        status: pimcoreEditStatus,
        idPrefix: "pimcoreEdit",
      }
    );
    const pimcoreEditEan = pimcoreEditForm.querySelector("#pimcoreEditEan");
    if (pimcoreEditEan) pimcoreEditEan.readOnly = true;
    if (pimcoreEditObjectInfo) {
      pimcoreEditObjectInfo.textContent = [
        `ID ${state.pimcoreEditObjectId}`,
        payload.object?.path || "",
      ]
        .filter(Boolean)
        .join(" - ");
    }
    if (pimcoreEditStatus) pimcoreEditStatus.textContent = "";
    pimcoreEditSubmitButton.disabled = false;
    updatePimcoreEditSubmitState();
    if (pimcoreEditRecalculateAllButton) {
      pimcoreEditRecalculateAllButton.disabled = !pimcoreEditHasRuntimeTemplates();
    }
    refreshOpenPimcoreOcrPanels().catch(() => {});
  } catch (error) {
    if (requestId !== state.pimcoreEditRequestId) return;
    pimcoreEditForm.textContent = "";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "secondary-button";
    retry.textContent = "Sprobuj ponownie";
    retry.addEventListener("click", openPimcoreEditModal);
    pimcoreEditForm.appendChild(retry);
    pimcoreEditStatus.textContent = `Nie mozna pobrac danych Pimcore: ${error.message}`;
    formStatus.textContent = pimcoreEditStatus.textContent;
    if (pimcoreEditRecalculateAllButton) pimcoreEditRecalculateAllButton.disabled = true;
  } finally {
    if (requestId === state.pimcoreEditRequestId && !state.pimcoreEditObjectId) {
      pimcoreEditSubmitButton.disabled = true;
    }
    if (pimcoreEditButton) {
      pimcoreEditButton.disabled =
        Number(state.pimcoreExistingObject?.id || 0) <= 0 && state.pimcoreCreateSchema.length === 0;
    }
  }
}

function closePimcoreEditModal() {
  state.pimcoreEditRequestId += 1;
  pimcoreEditModal?.classList.remove("active");
  if (pimcoreEditForm) pimcoreEditForm.textContent = "";
  if (pimcoreEditStatus) pimcoreEditStatus.textContent = "";
  if (pimcoreEditRecalculateAllButton) pimcoreEditRecalculateAllButton.disabled = true;
  pimcoreEditSubmitButton?.classList.remove("pimcore-submit-blocked");
  pimcoreEditSubmitButton?.removeAttribute("aria-disabled");
  if (pimcoreEditSubmitButton) pimcoreEditSubmitButton.title = "";
  state.pimcoreEditObjectId = 0;
  state.pimcoreEditMarker = "";
  state.pimcoreEditSchema = [];
  state.pimcoreEditIntegrations = { sql_profiles: [] };
  state.pimcoreEditIntegrationContextId = "";
}

async function submitPimcoreRuntimeEdit(event) {
  event.preventDefault();
  if (!pimcoreEditForm.reportValidity()) return;
  if (blockPimcoreRuntimeSubmitIfNeeded(pimcoreEditForm, pimcoreEditStatus)) return;
  pimcoreEditSubmitButton.disabled = true;
  pimcoreEditStatus.textContent = "Zapisywanie i publikowanie...";
  try {
    const values = Object.fromEntries(new FormData(pimcoreEditForm).entries());
    const result = await requestJson(
      `/api/pimcore/products/${encodeURIComponent(state.pimcoreEditObjectId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          marker: state.pimcoreEditMarker,
          values,
          integration_context_id: state.pimcoreEditIntegrationContextId,
        }),
        timeoutMs: 120000,
      }
    );
    state.pimcoreEditMarker = result.marker || state.pimcoreEditMarker;
    state.pimcoreExistingObject = result.object || state.pimcoreExistingObject;
    pimcoreEditStatus.textContent = `Zapisano obiekt ${result.object?.id || state.pimcoreEditObjectId}.`;
  } catch (error) {
    pimcoreEditStatus.textContent =
      error.status === 409
        ? "Produkt zostal zmieniony w Pimcore. Zamknij okno i otworz go ponownie."
        : error.message;
  } finally {
    pimcoreEditSubmitButton.disabled = false;
  }
}

function renderSettingsPimcore() {
  const pimcore = state.settings.pimcore || {};
  const form = document.createElement("form");
  form.className = "settings-form";
  if (pimcore.setup_complete !== true) {
    form.append(settingsNote("Integracja Pimcore wymaga pierwszej konfiguracji."));
    const start = document.createElement("button");
    start.type = "button";
    start.textContent = "Uruchom kreator";
    start.addEventListener("click", openPimcoreSetupWizard);
    form.appendChild(start);
    settingsOutput.appendChild(form);
    if (state.currentUser?.role === "admin" && !state.pimcoreSetupPrompted) {
      state.pimcoreSetupPrompted = true;
      queueMicrotask(openPimcoreSetupWizard);
    }
    return;
  }
  const fields = pimcoreCompactFields(pimcore);
  const classes = pimcoreCompactClassItems(pimcore);
  const folders = pimcoreCompactFolderItems(pimcore);
  const mappings = document.createElement("div");
  const addMapping = document.createElement("button");
  const refresh = document.createElement("button");
  const advanced = document.createElement("details");
  const advancedSummary = document.createElement("summary");
  const advancedBody = document.createElement("div");
  const configuredMappings = pimcore.field_mappings?.length
    ? pimcore.field_mappings
    : [{ source: "EAN", label: "EAN", pimcore_field: pimcore.existence_fields?.[0] || "EAN", required: true }];
  mappings.className = "pimcore-simple-mapping-list wide-field";
  for (const mapping of configuredMappings) {
    mappings.appendChild(pimcoreSimpleMappingRow(mapping, fields));
  }
  addMapping.type = "button";
  addMapping.className = "secondary-button";
  addMapping.textContent = "Dodaj pole";
  addMapping.addEventListener("click", () => {
    mappings.appendChild(pimcoreSimpleMappingRow({}, fields));
  });
  refresh.type = "button";
  refresh.className = "secondary-button";
  refresh.textContent = "Odswiez klasy i foldery";
  refresh.addEventListener("click", () => {
    refreshCompactPimcoreMetadata(form, refresh);
  });
  advanced.id = "pimcoreAdvancedSettings";
  advanced.className = "pimcore-advanced-settings";
  advanced.open = false;
  advancedSummary.textContent = "Zaawansowane";
  advancedBody.className = "settings-field-group";
  advancedBody.append(
    inputField("timeout_seconds", "Timeout [s]", pimcore.timeout_seconds || 30, {
      type: "number",
      min: "1",
      max: "120",
    }),
    checkField("verify_tls", "Weryfikuj certyfikat TLS", pimcore.verify_tls !== false),
    pimcoreCsvImportButton(mappings, fields),
    settingsNote("Klucz obiektu: {EAN}. Pole wyszukiwania EAN wynika z przypisania EAN."),
    settingsNote("Typ danych wykryty automatycznie na podstawie pola Pimcore.")
  );
  advanced.append(advancedSummary, advancedBody);
  form.append(
    settingsFieldGroup(
      "Polaczenie Pimcore",
      checkField("enabled", "Integracja wlaczona", pimcore.enabled),
      inputField("base_url", "Adres Pimcore", pimcore.base_url || "", {
        placeholder: "http://twoj-adres-pimcore.example",
      }),
      credentialField("api_key", "Klucz API", pimcore.api_key_set, {
        type: "password",
        secretPath: "pimcore.api_key",
      }),
      actionRow(refresh)
    ),
    settingsFieldGroup(
      "Miejsce zapisu",
      pimcoreSetupSelect(
        "class_id",
        "Klasa produktu",
        classes,
        pimcore.class_id,
        "id",
        (item) => `${item.name} (ID ${item.id})`
      ),
      pimcoreSetupSelect(
        "parent_id",
        "Folder docelowy",
        folders,
        pimcore.parent_id,
        "id",
        (item) => `${item.path || item.key} (ID ${item.id})`
      ),
      pimcoreManualCompactLocationFields(pimcore)
    ),
    settingsFieldGroup(
      "Pola produktu",
      settingsNote("Typ danych wykryty automatycznie na podstawie pola Pimcore."),
      mappings,
      actionRow(addMapping)
    ),
    settingsFieldGroup(
      "Testy integracji",
      actionRow(
        pimcoreReadOnlyTestButton(() => collectCompactPimcoreSettings(form)),
        pimcoreOpenWriteTestButton(),
        pimcoreHistoryButton()
      ),
      pimcoreChecklistElement()
    ),
    settingsFieldGroup(
      "Dane lokalne Pimcore",
      actionRow(pimcoreSettingsExportButton(), pimcoreExportLayoutOpenButton())
    ),
    advanced
  );
  settingsSaveButton(form, () => ({ pimcore: collectCompactPimcoreSettings(form) }));
  settingsOutput.appendChild(form);
}

function splitEmailRecipients(value) {
  const recipients = [];
  const seen = new Set();
  for (const rawItem of String(value || "").split(",")) {
    const item = rawItem.trim();
    const identity = item.toLowerCase();
    if (!item || seen.has(identity)) continue;
    seen.add(identity);
    recipients.push(item);
  }
  return recipients;
}

const MAIL_SEVERITY_RULES = [
  {
    severity: "info",
    label: "Informacje",
    help:
      "Dla zwyklych uzytkownikow. Jeden dzienny, kompaktowy raport jest wysylany tylko wtedy, gdy zaszly zmiany. Zawiera EAN oraz informacje o utworzeniu wpisu, zmianie danych PIMcore lub zdjec. Nie zawiera krokow SQL, FTP ani logow technicznych.",
    enabledName: "email_rule_info_enabled",
    recipientsName: "email_rule_info_recipients",
    includeActorName: "email_rule_info_include_actor",
  },
  {
    severity: "warning",
    label: "Ostrzezenia",
    help:
      "Dla uzytkownika i opcjonalnie osoby wykonujacej zadanie. Dotyczy problemow, ktore wymagaja korekty, ale zadanie moze zostac ukonczone czesciowo, np. niedozwolony plik w slocie, brak wymaganego pola lub pominiete zdjecie.",
    enabledName: "email_rule_warning_enabled",
    recipientsName: "email_rule_warning_recipients",
    includeActorName: "email_rule_warning_include_actor",
  },
  {
    severity: "error",
    label: "Bledy",
    help:
      "Dla administracji oraz opcjonalnie osoby wykonujacej zadanie. Dotyczy problemow blokujacych dana operacje, np. Brak mozliwosci aktualizacji PIMcore, blad wymaganego profilu SQL, FTP albo zapisu zdjec.",
    enabledName: "email_rule_error_enabled",
    recipientsName: "email_rule_error_recipients",
    includeActorName: "email_rule_error_include_actor",
  },
  {
    severity: "critical",
    label: "Bledy krytyczne",
    help:
      "Dla administracji. Natychmiastowy alert o awarii wymagajacej reakcji, np. nieobsluzony wyjatek backendu lub frontendu, niedostepny backend albo wygasajacy Client Secret Entra.",
    enabledName: "email_rule_critical_enabled",
    recipientsName: "email_rule_critical_recipients",
    includeActorName: "email_rule_critical_include_actor",
  },
];

let openMailHelpPopover = null;
let mailHelpPopoverSequence = 0;

function closeMailHelpPopover({ restoreFocus = false } = {}) {
  if (!openMailHelpPopover) return;
  const { button, popover } = openMailHelpPopover;
  popover.hidden = true;
  button.setAttribute("aria-expanded", "false");
  openMailHelpPopover = null;
  if (restoreFocus) button.focus();
}

function createMailHelpPopover(label, message) {
  const wrapper = document.createElement("span");
  const button = document.createElement("button");
  const popover = document.createElement("span");
  const popoverId = `mail-help-${mailHelpPopoverSequence += 1}`;
  wrapper.className = "mail-help";
  button.type = "button";
  button.className = "mail-help-trigger";
  button.textContent = "?";
  button.setAttribute("aria-label", `Pomoc: ${label}`);
  button.setAttribute("aria-controls", popoverId);
  button.setAttribute("aria-expanded", "false");
  popover.id = popoverId;
  popover.className = "mail-help-popover";
  popover.hidden = true;
  popover.setAttribute("role", "tooltip");
  popover.textContent = message;
  button.addEventListener("click", () => {
    const isOpen = openMailHelpPopover?.button === button;
    closeMailHelpPopover();
    if (isOpen) return;
    popover.hidden = false;
    button.setAttribute("aria-expanded", "true");
    openMailHelpPopover = { button, popover };
  });
  wrapper.append(button, popover);
  return wrapper;
}

function mailHelpTitle(label, message, tagName = "span") {
  const title = document.createElement(tagName);
  title.className = "mail-help-title";
  title.append(document.createTextNode(label), createMailHelpPopover(label, message));
  return title;
}

function addMailFieldHelp(field, label, message) {
  const title = mailHelpTitle(label, message);
  if (field.firstChild) {
    field.replaceChild(title, field.firstChild);
  } else {
    field.appendChild(title);
  }
  return field;
}

function mailRuleCard(definition, rule = {}) {
  const card = document.createElement("div");
  card.className = `mail-rule-card mail-rule-${definition.severity}`;
  card.append(
    mailHelpTitle(definition.label, definition.help, "h3"),
    checkField(
      definition.enabledName,
      "Wysylaj powiadomienia",
      Boolean(rule.enabled)
    ),
    inputField(
      definition.recipientsName,
      "Adresy odbiorcow (oddzielone przecinkami)",
      Array.isArray(rule.recipients) ? rule.recipients.join(", ") : "",
      { placeholder: "np. admin@example.com, serwis@example.com" }
    ),
    checkField(
      definition.includeActorName,
      "Wyslij takze do powiazanego uzytkownika",
      Boolean(rule.include_actor),
      "Adres jest pobierany z konta osoby powiazanej ze zdarzeniem."
    )
  );
  return card;
}

function renderMailTestResult(container, result) {
  container.textContent = "";
  container.className = `mail-test-status ${result.ok ? "success-text" : "error-text"}`;
  const summary = document.createElement("strong");
  const channel = result.used_channel === "smtp" ? "SMTP" : "Microsoft Entra";
  summary.textContent = result.ok
    ? `Wiadomosc wyslana przez ${channel} (${Number(result.elapsed_ms || 0)} ms).`
    : `Test wysylki nie powiodl sie (${Number(result.elapsed_ms || 0)} ms).`;
  container.appendChild(summary);
  const attempts = Array.isArray(result.attempts) ? result.attempts : [];
  if (attempts.length) {
    const list = document.createElement("div");
    list.className = "mail-test-attempts";
    for (const attempt of attempts) {
      const row = document.createElement("div");
      const attemptChannel = attempt.channel === "smtp" ? "SMTP" : "Entra";
      row.className = `mail-test-attempt mail-test-attempt-${attempt.status === "sent" ? "sent" : "error"}`;
      row.textContent = attempt.status === "sent"
        ? `${attemptChannel}: wyslano${Number.isFinite(attempt.elapsed_ms) ? ` (${attempt.elapsed_ms} ms)` : ""}.`
        : `${attemptChannel}: ${attempt.message || "kanal nie wyslal wiadomosci"}`;
      list.appendChild(row);
    }
    container.appendChild(list);
  }
}

function renderMailTestSuiteResult(container, result) {
  container.textContent = "";
  container.className = `mail-test-status ${result.ok ? "success-text" : "error-text"}`;
  const summary = document.createElement("strong");
  const scenarios = Array.isArray(result.scenarios) ? result.scenarios : [];
  const finished = scenarios.filter((item) =>
    ["sent", "fallback", "skipped"].includes(item?.status)
  ).length;
  summary.textContent = result.ok
    ? `Przetestowano ${finished}/${scenarios.length} typow powiadomien (${Number(result.elapsed_ms || 0)} ms).`
    : `Test zestawu zakonczyl sie problemem (${finished}/${scenarios.length} poprawnych, ${Number(result.elapsed_ms || 0)} ms).`;
  container.appendChild(summary);
  const labels = {
    pimcore_rejection: "Odrzucenie danych PIMcore",
    ftp_failure: "Blad transferu FTP",
    photo_location_unavailable: "Niedostepna lokalizacja zdjec",
    backend_exception: "Nieobsluzony wyjatek backendu",
    entra_secret_expiry: "Client Secret Entra wygasa za 7 dni",
  };
  const statuses = {
    sent: "wyslano",
    fallback: "wyslano fallbackiem",
    skipped: "pominieto — brak aktywnych odbiorcow",
    error: "blad wysylki",
  };
  const list = document.createElement("div");
  list.className = "mail-test-attempts";
  for (const scenario of scenarios) {
    const row = document.createElement("div");
    const status = statuses[scenario?.status] || "blad wysylki";
    const channel = scenario?.used_channel === "smtp" ? "SMTP" : "Entra";
    const recipients = Number.isFinite(scenario?.recipient_count)
      ? `, odbiorcow: ${scenario.recipient_count}`
      : "";
    row.className = `mail-test-attempt mail-test-attempt-${["sent", "fallback", "skipped"].includes(scenario?.status) ? "sent" : "error"}`;
    row.textContent = `${labels[scenario?.kind] || "Powiadomienie"}: ${status} (${channel}${recipients}).`;
    list.appendChild(row);
  }
  container.appendChild(list);
}

function entraExpiryRemainingDays(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return null;
  const milliseconds = date.getTime() - Date.now();
  const day = 24 * 60 * 60 * 1000;
  return milliseconds >= 0 ? Math.ceil(milliseconds / day) : Math.floor(milliseconds / day);
}

function entraExpiryMetadata(label, value, title = "") {
  const row = document.createElement("div");
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  row.className = "entra-expiry-meta-row";
  term.textContent = label;
  description.textContent = value;
  if (title) description.title = title;
  row.append(term, description);
  return row;
}

function renderEntraExpiryStatus(container, status = {}) {
  state.entraExpiryStatus = status;
  container.textContent = "";
  const panel = document.createElement("section");
  const heading = document.createElement("strong");
  const details = document.createElement("dl");
  const source = String(status.source || "saved");
  const expiresAt = formatPanelTimestamp(status.expires_at);
  const checkedAt = formatPanelTimestamp(status.last_checked_at);
  const successfulAt = formatPanelTimestamp(status.last_success_at);
  const remainingDays = entraExpiryRemainingDays(status.expires_at);
  const permissionRequired = status.error_code === "permission_required";
  const expirySeverity = remainingDays === null
    ? "info"
    : remainingDays <= 3 ? "critical" : remainingDays <= 14 ? "warning" : "info";
  let summary = "Nie ma jeszcze zapisanego statusu terminu waznosci Client Secret.";

  panel.className = "entra-expiry-panel";
  details.className = "entra-expiry-metadata";
  if (permissionRequired) {
    summary = "Nadaj aplikacji uprawnienie Application.Read.All i zatwierdz admin consent, aby odczytac termin waznosci.";
  } else if (status.status === "ok" && remainingDays !== null) {
    summary = remainingDays < 0
      ? "Client Secret wygasl. Zaktualizuj konfiguracje Microsoft Entra."
      : `Client Secret wygasa za ${remainingDays} ${remainingDays === 1 ? "dzien" : "dni"}.`;
  } else if (status.status === "unavailable") {
    summary = "Nie mozna teraz odczytac statusu Microsoft Entra. Sprobuj ponownie pozniej.";
  }
  panel.classList.add(`entra-expiry-${expirySeverity}`);
  if (permissionRequired) panel.classList.add("entra-expiry-permission-required");
  if (permissionRequired || status.status === "unavailable") panel.classList.add("entra-expiry-warning");
  heading.textContent = summary;
  details.append(
    entraExpiryMetadata("Aplikacja", String(status.application_name || "Brak danych")),
    entraExpiryMetadata("Credential", String(status.credential_name || "Brak danych")),
    entraExpiryMetadata("Wygasa", expiresAt),
    entraExpiryMetadata(
      "Pozostalo",
      remainingDays === null ? "Brak danych" : remainingDays < 0 ? `${Math.abs(remainingDays)} dni po terminie` : `${remainingDays} dni`
    ),
    entraExpiryMetadata("Ostatnia kontrola", checkedAt),
    entraExpiryMetadata("Ostatni sukces", successfulAt),
    entraExpiryMetadata(
      "W cache",
      source === "microsoft_graph" ? "Nie - odswiezono teraz" : "Tak - zapisany bezpieczny stan"
    )
  );
  panel.append(heading, details);
  container.appendChild(panel);
}

function renderEntraExpiryRefreshFailure(container) {
  const existing = container.querySelector(".entra-expiry-refresh-error");
  if (existing) existing.remove();
  const message = document.createElement("p");
  message.className = "entra-expiry-refresh-error";
  message.setAttribute("role", "alert");
  message.textContent = "Nie udalo sie odswiezyc statusu. Wyswietlono poprzednia bezpieczna wartosc.";
  container.appendChild(message);
}

async function loadCachedEntraExpiryStatus(container) {
  try {
    const status = await requestJson("/api/settings/email/entra-expiry");
    renderEntraExpiryStatus(container, status);
  } catch (_error) {
    renderEntraExpiryStatus(container, { status: "unavailable" });
  }
}

function renderSettingsMail() {
  const email = state.settings.email_notifications || {};
  const form = document.createElement("form");
  const channelGrid = document.createElement("div");
  const entraCard = document.createElement("section");
  const smtpCard = document.createElement("section");
  const entraTitle = document.createElement("h3");
  const smtpTitle = document.createElement("h3");
  const smtpWarning = document.createElement("p");
  const entraExpiryStatus = document.createElement("div");
  const entraExpiryRefreshButton = document.createElement("button");
  const entraTenantId = addMailFieldHelp(
    inputField("email_entra_tenant_id", "Tenant ID", email.entra?.tenant_id || ""),
    "Tenant ID",
    "Pozycja: Identyfikator katalogu (dzierzawy) w widoku Przeglad rejestracji aplikacji Microsoft Entra. Nie jest to Identyfikator obiektu."
  );
  const entraClientId = addMailFieldHelp(
    inputField("email_entra_client_id", "Client ID", email.entra?.client_id || ""),
    "Client ID",
    "Pozycja: Identyfikator aplikacji (klienta) w widoku Przeglad tej rejestracji aplikacji Microsoft Entra. Nie jest to Identyfikator obiektu."
  );
  const entraClientSecret = addMailFieldHelp(
    credentialField(
      "email_entra_client_secret",
      "Client Secret",
      Boolean(email.entra?.client_secret_set),
      { type: "password" }
    ),
    "Client Secret",
    "Pozycja: Wartosc w Certyfikaty i wpisy tajne -> Wpisy tajne klienta dla utworzonego sekretu. Nie wpisuj Identyfikatora wpisu tajnego ani Identyfikatora obiektu. Wartosc jest widoczna w Entra tylko bezposrednio po utworzeniu sekretu."
  );
  const entraFromAddress = addMailFieldHelp(
    inputField("email_entra_from_address", "Adres Od", email.entra?.from_address || "", {
      type: "email",
      placeholder: "powiadomienia@example.com",
    }),
    "Adres Od",
    "Adres skrzynki Microsoft 365, z ktorej odbiorcy zobacza wiadomosci. Aplikacja Entra musi miec prawo wysylania z tej skrzynki."
  );
  const smtpSecurity = selectField(
    "email_smtp_security",
    "Szyfrowanie polaczenia",
    email.smtp?.security || "starttls",
    [
      ["starttls", "STARTTLS"],
      ["tls", "TLS od poczatku polaczenia"],
      ["none", "Brak szyfrowania"],
    ]
  );
  addMailFieldHelp(
    smtpSecurity,
    "Szyfrowanie polaczenia",
    "Sposob zabezpieczenia polaczenia z serwerem SMTP. Wybierz STARTTLS lub TLS, gdy dostawca je udostepnia."
  );
  const smtpSecuritySelect = smtpSecurity.querySelector("select");
  const updateSmtpWarning = () => {
    const security = smtpSecuritySelect.value;
    smtpWarning.hidden = security !== "none";
  };
  form.className = "settings-form mail-settings-form";
  channelGrid.className = "mail-channel-grid wide-field";
  entraCard.className = "mail-channel-card";
  smtpCard.className = "mail-channel-card";
  entraTitle.textContent = "Microsoft Entra / Graph";
  smtpTitle.textContent = "SMTP (dowolny dostawca)";
  smtpWarning.className = "mail-security-warning";
  smtpWarning.setAttribute("role", "alert");
  smtpWarning.textContent =
    "Uwaga: tryb bez TLS. Nie szyfruje polaczenia ani danych logowania. Uzywaj go tylko w zaufanej sieci.";
  entraExpiryStatus.className = "entra-expiry-status";
  entraExpiryStatus.setAttribute("role", "status");
  entraExpiryStatus.setAttribute("aria-live", "polite");
  entraExpiryStatus.textContent = "Pobieranie zapisanego statusu Client Secret...";
  entraExpiryRefreshButton.type = "button";
  entraExpiryRefreshButton.className = "secondary-button entra-expiry-refresh";
  entraExpiryRefreshButton.textContent = "Sprawdz teraz";
  entraExpiryRefreshButton.addEventListener("click", async () => {
    entraExpiryRefreshButton.disabled = true;
    try {
      const status = await requestJson("/api/settings/email/entra-expiry/refresh", {
        method: "POST",
      });
      renderEntraExpiryStatus(entraExpiryStatus, status);
    } catch (_error) {
      renderEntraExpiryRefreshFailure(entraExpiryStatus);
    } finally {
      entraExpiryRefreshButton.disabled = false;
    }
  });
  smtpSecuritySelect.addEventListener("change", updateSmtpWarning);
  updateSmtpWarning();
  entraCard.append(
    entraTitle,
    entraExpiryStatus,
    entraExpiryRefreshButton,
    entraTenantId,
    entraClientId,
    entraClientSecret,
    entraFromAddress
  );
  loadCachedEntraExpiryStatus(entraExpiryStatus);
  smtpCard.append(
    smtpTitle,
    addMailFieldHelp(
      inputField("email_smtp_host", "Host SMTP", email.smtp?.host || ""),
      "Host SMTP",
      "Adres serwera SMTP udostepniony przez dostawce poczty, np. smtp.gmail.com."
    ),
    addMailFieldHelp(
      inputField("email_smtp_port", "Port", email.smtp?.port || 587, {
        type: "number",
        min: 1,
        max: 65535,
      }),
      "Port",
      "Port serwera SMTP wskazany przez dostawce poczty. Dla STARTTLS najczesciej jest to 587."
    ),
    smtpSecurity,
    smtpWarning,
    addMailFieldHelp(
      inputField("email_smtp_username", "Login", email.smtp?.username || ""),
      "Login",
      "Login wymagany przez serwer SMTP; u wielu dostawcow jest to pelny adres e-mail skrzynki."
    ),
    addMailFieldHelp(
      credentialField(
        "email_smtp_password",
        "Haslo",
        Boolean(email.smtp?.password_set),
        { type: "password" }
      ),
      "Haslo",
      "Haslo SMTP lub haslo aplikacji wygenerowane przez dostawce poczty. Nie jest to haslo do panelu PicSyncra."
    ),
    addMailFieldHelp(
      inputField("email_smtp_from_address", "Adres Od", email.smtp?.from_address || "", {
        type: "email",
        placeholder: "powiadomienia@example.com",
      }),
      "Adres Od",
      "Adres skrzynki SMTP, z ktorej odbiorcy zobacza wiadomosci. Zwykle musi odpowiadac skonfigurowanemu loginowi."
    ),
    addMailFieldHelp(
      inputField("email_smtp_from_name", "Nazwa Od", email.smtp?.from_name || "PicSyncra"),
      "Nazwa Od",
      "Czytelna nazwa nadawcy wyswietlana odbiorcom obok adresu skrzynki."
    )
  );
  channelGrid.append(entraCard, smtpCard);

  const rules = email.rules || {};
  const dailySummaryTime = addMailFieldHelp(
    inputField(
      "daily_summary_time",
      "Godzina dziennego podsumowania",
      email.daily_summary_time || "16:00",
      { type: "time" }
    ),
    "Godzina dziennego podsumowania",
    "Godzina wyslania jednego podsumowania zmian dla odbiorcow Informacji. Czas Europe/Warsaw. Raport obejmuje zmiany od poprzedniego poprawnie wyslanego raportu."
  );
  const rulesGrid = document.createElement("div");
  rulesGrid.className = "mail-rule-grid wide-field";
  rulesGrid.append(
    ...MAIL_SEVERITY_RULES.map((definition) =>
      mailRuleCard(definition, rules[definition.severity])
    )
  );

  const testRecipient = inputField(
    "email_test_recipient",
    "Adres odbiorcy testu",
    "",
    { type: "email", placeholder: "admin@example.com" }
  );
  const testChannel = selectField("email_test_channel", "Kanal testu", "primary", [
    ["primary", "Kanal podstawowy"],
    ["entra", "Microsoft Entra"],
    ["smtp", "SMTP"],
  ]);
  const testFallback = checkField(
    "email_test_use_fallback",
    "Uzyj fallbacku, gdy kanal testowy zawiedzie",
    Boolean(email.fallback_enabled)
  );
  const testButton = document.createElement("button");
  const testSuiteButton = document.createElement("button");
  const testStatus = document.createElement("div");
  const testSuiteStatus = document.createElement("div");
  testButton.type = "button";
  testButton.textContent = "Wyslij wiadomosc testowa";
  testSuiteButton.type = "button";
  testSuiteButton.textContent = "Testuj wszystkie typy powiadomien";
  testStatus.className = "mail-test-status";
  testSuiteStatus.className = "mail-test-status";
  testStatus.setAttribute("role", "status");
  testStatus.setAttribute("aria-live", "polite");
  testSuiteStatus.setAttribute("role", "status");
  testSuiteStatus.setAttribute("aria-live", "polite");
  testButton.addEventListener("click", async () => {
    const recipient = testRecipient.querySelector("input").value.trim();
    if (!recipient) {
      testStatus.className = "mail-test-status error-text";
      testStatus.textContent = "Podaj adres odbiorcy testu.";
      return;
    }
    testButton.disabled = true;
    testStatus.className = "mail-test-status";
    testStatus.textContent = "Wysylanie testu...";
    try {
      const result = await requestJson("/api/settings/email/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipient,
          channel: testChannel.querySelector("select").value,
          use_fallback: testFallback.querySelector("input").checked,
        }),
        timeoutMs: 60000,
      });
      renderMailTestResult(testStatus, result);
    } catch (error) {
      const result = error.payload || error.detail;
      if (result && typeof result === "object" && Array.isArray(result.attempts)) {
        renderMailTestResult(testStatus, result);
      } else {
        testStatus.className = "mail-test-status error-text";
        testStatus.textContent = "Test wysylki nie powiodl sie. Sprawdz konfiguracje kanalu.";
      }
    } finally {
      testButton.disabled = false;
    }
  });
  testSuiteButton.addEventListener("click", async () => {
    testSuiteButton.disabled = true;
    testSuiteStatus.className = "mail-test-status";
    testSuiteStatus.textContent = "Wysylanie pieciu testowych powiadomien...";
    try {
      const result = await requestJson("/api/settings/email/test-suite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel: testChannel.querySelector("select").value,
          use_fallback: testFallback.querySelector("input").checked,
        }),
        timeoutMs: 180000,
      });
      renderMailTestSuiteResult(testSuiteStatus, result);
    } catch (error) {
      const result = error.payload || error.detail;
      if (result && typeof result === "object" && Array.isArray(result.scenarios)) {
        renderMailTestSuiteResult(testSuiteStatus, result);
      } else {
        testSuiteStatus.className = "mail-test-status error-text";
        testSuiteStatus.textContent = "Test zestawu nie powiodl sie. Sprawdz konfiguracje kanalow.";
      }
    } finally {
      testSuiteButton.disabled = false;
    }
  });

  form.append(
    settingsFieldGroup(
      "Sposob wysylki",
      selectField(
        "email_primary_channel",
        "Kanal podstawowy",
        email.primary_channel || "entra",
        [
          ["entra", "Microsoft Entra"],
          ["smtp", "SMTP"],
        ]
      ),
      checkField(
        "email_fallback_enabled",
        "Wlacz kanal zapasowy",
        Boolean(email.fallback_enabled),
        "Gdy kanal podstawowy zawiedzie, aplikacja wykona jedna probe drugim kanalem."
      ),
      channelGrid
    ),
    settingsFieldGroup(
      "Reguly powiadomien",
      rulesGrid,
      settingsNote("Znaki zapytania wyjasniaja, kto otrzymuje dany typ wiadomosci i kiedy jest wysylany.")
    ),
    settingsFieldGroup(
      "Dzienne podsumowanie informacji",
      dailySummaryTime,
      settingsNote("Jedna wiadomosc tylko wtedy, gdy wystapily zmiany produktow. Strefa czasowa: Europe/Warsaw.")
    ),
    settingsFieldGroup(
      "Wiadomosc testowa",
      testRecipient,
      testChannel,
      testFallback,
      actionRow(testButton, testSuiteButton),
      testStatus,
      testSuiteStatus
    )
  );
  settingsSaveButton(form, (data) => ({
    email_notifications: {
      primary_channel: data.get("email_primary_channel"),
      fallback_enabled: data.has("email_fallback_enabled"),
      daily_summary_time: data.get("daily_summary_time"),
      entra: {
        tenant_id: data.get("email_entra_tenant_id"),
        client_id: data.get("email_entra_client_id"),
        client_secret: data.get("email_entra_client_secret"),
        from_address: data.get("email_entra_from_address"),
      },
      smtp: {
        host: data.get("email_smtp_host"),
        port: data.get("email_smtp_port"),
        security: data.get("email_smtp_security"),
        username: data.get("email_smtp_username"),
        password: data.get("email_smtp_password"),
        from_address: data.get("email_smtp_from_address"),
        from_name: data.get("email_smtp_from_name"),
      },
      rules: Object.fromEntries(
        MAIL_SEVERITY_RULES.map((definition) => [
          definition.severity,
          {
            enabled: data.has(definition.enabledName),
            recipients: splitEmailRecipients(data.get(definition.recipientsName)),
            include_actor: data.has(definition.includeActorName),
          },
        ])
      ),
    },
  }));
  settingsOutput.appendChild(form);
}

function selectedSimilarSlotPrefixes(rows) {
  return Array.from(rows)
    .filter((row) => row.querySelector('[name="similar_file_slot_prefixes"]')?.checked)
    .map((row) => String(row.querySelector('[name="prefix"]')?.value || "").trim())
    .filter(Boolean);
}

function renderSettingsSlots() {
  ensureSqlColumnsDatalist();
  const form = document.createElement("form");
  form.className = "settings-form";
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent =
    "Nazwa w web jest tylko etykieta slotu. ID trafia do EAN_ID, nazwa w pliku jest zapisywana literalnie po usunieciu znakow niedozwolonych, a pole SQL sluzy do aktualizacji bazy.";
  const list = document.createElement("div");
  const addButton = document.createElement("button");
  const similarSettings = state.settings.similar_file_detection || {};
  const similarEnabled = document.createElement("input");
  const similarEnabledRow = document.createElement("label");
  list.className = "slot-settings-list";
  similarEnabled.type = "checkbox";
  similarEnabled.name = "similar_files_enabled";
  similarEnabled.checked = Boolean(similarSettings.enabled);
  similarEnabledRow.className = "check-row";
  similarEnabledRow.append(similarEnabled, document.createTextNode("Wykrywaj pliki z podobnych produktow"));
  const nextPrefix = () => {
    const used = [...list.querySelectorAll('[name="prefix"]')]
      .map((input) => parseInt(input.value, 10))
      .filter((value) => Number.isFinite(value));
    const next = Math.max(0, ...used) + 1;
    return String(next).padStart(2, "0");
  };
  const addSlotRow = (slot = {}) => {
    const row = document.createElement("div");
    const remove = document.createElement("button");
    const similarOption = document.createElement("label");
    const similarInput = document.createElement("input");
    row.className = "slot-settings-row";
    row.dataset.filenameLabelExplicit = slot.filename_label_explicit ? "1" : "0";
    row.dataset.originalLabel = slot.label || "";
    row.dataset.originalFilenameLabel = slot.filename_label || slot.label || "";
    const column = inputField("sql_column", "Pole SQL", slot.sql_column || "");
    column.querySelector("input").setAttribute("list", "sqlColumnsList");
    remove.type = "button";
    remove.className = "secondary-button";
    remove.textContent = "Usun";
    remove.addEventListener("click", () => row.remove());
    similarOption.className = "slot-similar-option";
    similarInput.type = "checkbox";
    similarInput.name = "similar_file_slot_prefixes";
    similarInput.value = slot.prefix || "";
    similarInput.checked = (similarSettings.slot_prefixes || []).includes(slot.prefix);
    similarInput.disabled = !similarEnabled.checked;
    similarOption.append(similarInput, document.createTextNode("Podobne"));
    row.append(
      inputField("label", "Nazwa w web", slot.label),
      inputField("prefix", "ID", slot.prefix),
      inputField("filename_label", "Nazwa w pliku", slot.filename_label || slot.label),
      column,
      similarOption,
      remove
    );
    list.appendChild(row);
  };
  for (const slot of state.settings.slots || []) {
    addSlotRow(slot);
  }
  similarEnabled.addEventListener("change", () => {
    list.querySelectorAll('[name="similar_file_slot_prefixes"]').forEach((input) => {
      input.disabled = !similarEnabled.checked;
    });
  });
  addButton.type = "button";
  addButton.className = "secondary-button";
  addButton.textContent = "Dodaj slot";
  addButton.addEventListener("click", () => {
    const prefix = nextPrefix();
    addSlotRow({
      prefix,
      label: `Slot ${prefix}`,
      filename_label: `Slot ${prefix}`,
      filename_label_explicit: true,
      sql_column: "",
    });
  });
  form.append(
    settingsFieldGroup("Lista slotow", note, similarEnabledRow, list, actionRow(addButton, detectSqlColumnsButton()))
  );
  settingsSaveButton(form, (data) => {
    const slotRows = [...form.querySelectorAll(".slot-settings-row")];
    const slots = slotRows.map((row) => {
      const label = row.querySelector('[name="label"]').value;
      const filenameLabel = row.querySelector('[name="filename_label"]').value;
      const wasExplicit = row.dataset.filenameLabelExplicit === "1";
      const originalLabel = row.dataset.originalLabel || "";
      const originalFilenameLabel = row.dataset.originalFilenameLabel || "";
      const unchangedLegacyFilename =
        !wasExplicit && label === originalLabel && filenameLabel === originalFilenameLabel;
      return {
        prefix: row.querySelector('[name="prefix"]').value,
        label,
        filename_label: unchangedLegacyFilename ? "" : filenameLabel,
        sql_column: row.querySelector('[name="sql_column"]').value,
      };
    });
    return {
      slots,
      "similar_file_detection": {
        enabled: data.has("similar_files_enabled"),
        slot_prefixes: selectedSimilarSlotPrefixes(slotRows),
      },
    };
  });
  settingsOutput.appendChild(form);
}

function renderSettingsUsers() {
  const wrapper = document.createElement("div");
  wrapper.className = "settings-form";
  const addForm = document.createElement("form");
  addForm.className = "user-add-form wide-field";
  const input = document.createElement("input");
  const emailInput = document.createElement("input");
  const password = document.createElement("input");
  const role = document.createElement("select");
  const button = document.createElement("button");
  input.name = "username";
  input.placeholder = "Nowy uzytkownik";
  emailInput.name = "email";
  emailInput.type = "email";
  emailInput.autocomplete = "email";
  emailInput.placeholder = "E-mail opcjonalnie";
  password.name = "password";
  password.type = "password";
  password.placeholder = "Haslo";
  for (const value of ["user", "admin"]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    role.appendChild(option);
  }
  button.textContent = "Dodaj";
  addForm.append(input, emailInput, password, role, button);
  addForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = await requestJson("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: input.value,
        email: emailInput.value,
        password: password.value,
        role: role.value,
      }),
    });
    state.settings.users = payload.users;
    state.currentUser = payload.current_user || state.currentUser;
    updateAdminUi();
    input.value = "";
    emailInput.value = "";
    password.value = "";
    renderSettings();
  });
  const list = document.createElement("div");
  list.className = "user-list";
  for (const user of state.settings.users || []) {
    const row = document.createElement("div");
    row.className = "user-row";
    row.classList.toggle("user-row-locked", Boolean(user.locked));
    const name = document.createElement("div");
    const nameTitle = document.createElement("strong");
    const nameMeta = document.createElement("small");
    const role = document.createElement("select");
    const enabled = document.createElement("input");
    const enabledWrap = document.createElement("div");
    const enabledText = document.createElement("div");
    const enabledTitle = document.createElement("strong");
    const enabledDescription = document.createElement("small");
    const userEmailInput = document.createElement("input");
    const passwordInput = document.createElement("input");
    const actions = document.createElement("div");
    const save = document.createElement("button");
    const unlock = document.createElement("button");
    const revokeSessions = document.createElement("button");
    const revokeExtension = document.createElement("button");
    const isCurrentUser =
      state.currentUser &&
      String(state.currentUser.username || "").toLowerCase() === String(user.username || "").toLowerCase();
    const loginMeta = [];
    name.className = "user-summary";
    nameTitle.textContent = user.username;
    if (user.locked) {
      loginMeta.push(
        user.lock_manual
          ? "Zablokowane do recznego odblokowania"
          : `Zablokowane do ${formatPanelTimestamp(user.lock_expires_ts, { epochUnit: "seconds" })}`
      );
    }
    if (user.failed_login_count) {
      loginMeta.push(`Bledne proby: ${user.failed_login_count}`);
    }
    if (user.last_failed_login_ts) {
      const ip = user.last_failed_login_ip ? `, ${user.last_failed_login_ip}` : "";
      loginMeta.push(
        `Ostatnia bledna: ${formatPanelTimestamp(user.last_failed_login_ts, {
          epochUnit: "seconds",
        })}${ip}`
      );
    }
    loginMeta.push(`Sesje v${Number(user.session_version || 0)}`);
    loginMeta.push(
      `Token rozszerzenia v${Number(user.extension_token_version || 0)}${
        user.extension_token_last_used_ts
          ? `, ostatnio ${formatPanelTimestamp(user.extension_token_last_used_ts, {
              epochUnit: "seconds",
            })}`
          : ""
      }`
    );
    nameMeta.textContent = loginMeta.join(" | ") || "Brak blednych prob logowania.";
    nameMeta.className = user.locked ? "user-lock-warning" : "";
    name.append(nameTitle, nameMeta);
    for (const value of ["user", "admin"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      option.selected = user.role === value;
      role.appendChild(option);
    }
    enabled.type = "checkbox";
    enabled.checked = Boolean(user.enabled);
    enabled.disabled = Boolean(isCurrentUser);
    enabled.setAttribute("aria-label", `Konto aktywne: ${user.username}`);
    enabledTitle.textContent = "Konto aktywne";
    enabledDescription.textContent = isCurrentUser
      ? "Nie mozna wylaczyc konta aktualnej sesji."
      : "Wylaczenie blokuje logowanie tego uzytkownika.";
    enabledText.append(enabledTitle, enabledDescription);
    enabledWrap.className = "check-row compact-check";
    enabledWrap.append(enabled, enabledText);
    userEmailInput.name = "email";
    userEmailInput.type = "email";
    userEmailInput.autocomplete = "email";
    userEmailInput.placeholder = "E-mail opcjonalnie";
    userEmailInput.value = String(user.email || "");
    passwordInput.type = "password";
    passwordInput.placeholder = user.has_password ? "Nowe haslo opcjonalnie" : "Ustaw haslo";
    save.type = "button";
    save.textContent = "Zapisz";
    unlock.type = "button";
    unlock.textContent = "Odblokuj";
    unlock.hidden = !user.locked && !user.failed_login_count;
    revokeSessions.type = "button";
    revokeSessions.textContent = "Wyloguj sesje";
    revokeExtension.type = "button";
    revokeExtension.textContent = "Uniewaznij token";
    actions.className = "user-actions";
    save.addEventListener("click", async () => {
      const payload = {
        enabled: enabled.checked,
        role: role.value,
        email: userEmailInput.value,
      };
      if (passwordInput.value) {
        payload.password = passwordInput.value;
      }
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      updateAdminUi();
      renderSettings();
    });
    unlock.addEventListener("click", async () => {
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unlock: true }),
      });
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      if (response.session_invalidated) {
        window.location.href = "/login";
        return;
      }
      updateAdminUi();
      renderSettings();
    });
    revokeSessions.addEventListener("click", async () => {
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revoke_sessions: true }),
      });
      if (response.session_invalidated) {
        window.location.href = "/login";
        return;
      }
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      updateAdminUi();
      renderSettings();
    });
    revokeExtension.addEventListener("click", async () => {
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revoke_extension_token: true }),
      });
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      updateAdminUi();
      renderSettings();
    });
    actions.append(save, unlock, revokeSessions, revokeExtension);
    row.append(name, role, userEmailInput, passwordInput, enabledWrap, actions);
    list.appendChild(row);
  }
  wrapper.append(
    settingsFieldGroup("Nowy uzytkownik", addForm),
    settingsFieldGroup("Lista uzytkownikow", list)
  );
  settingsOutput.appendChild(wrapper);
}

function renderSettingsResourceMonitor() {
  const monitor = state.settings.resource_monitor || {};
  const form = document.createElement("form");
  form.className = "settings-form";
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent =
    "Progi dotycza procesu backendu. Alarm jest zatwierdzany po kolejnych probkach, aby ograniczyc falszywe ostrzezenia.";
  const testNote = document.createElement("p");
  testNote.className = "settings-note wide-field";
  testNote.textContent =
    "Bezpieczna symulacja zapisuje trwale zdarzenie testowe; brak zapisu jest wynikiem niepowodzenia. Testy rzeczywiste tworza kontrolowane obciazenie CPU, RAM albo dysku i moga trwac okolo 20 sekund.";
  const testResult = document.createElement("p");
  testResult.id = "resourceMonitorTestResult";
  testResult.className = "resource-monitor-test-result wide-field";
  testResult.setAttribute("role", "status");

  const safeButton = document.createElement("button");
  safeButton.type = "button";
  safeButton.className = "secondary-button";
  safeButton.dataset.resourceMonitorTest = "safe";
  safeButton.textContent = "Bezpieczna symulacja";
  safeButton.addEventListener("click", () => runResourceMonitorTest("safe"));

  const cpuButton = document.createElement("button");
  cpuButton.type = "button";
  cpuButton.className = "secondary-button";
  cpuButton.dataset.resourceMonitorTest = "cpu";
  cpuButton.dataset.resourceMonitorRealTest = "cpu";
  cpuButton.textContent = "Rzeczywisty test CPU";
  cpuButton.addEventListener("click", () => runResourceMonitorTest("cpu"));

  const memoryButton = document.createElement("button");
  memoryButton.type = "button";
  memoryButton.className = "secondary-button";
  memoryButton.dataset.resourceMonitorTest = "memory";
  memoryButton.dataset.resourceMonitorRealTest = "memory";
  memoryButton.textContent = "Rzeczywisty test RAM";
  memoryButton.addEventListener("click", () => runResourceMonitorTest("memory"));

  const diskButton = document.createElement("button");
  diskButton.type = "button";
  diskButton.className = "secondary-button";
  diskButton.dataset.resourceMonitorTest = "disk";
  diskButton.dataset.resourceMonitorRealTest = "disk";
  diskButton.textContent = "Rzeczywisty test dysku";
  diskButton.addEventListener("click", () => runResourceMonitorTest("disk"));

  form.append(
    settingsFieldGroup(
      "Wskaznik zasobow",
      checkField(
        "show_status",
        "Pokazuj status zasobow w naglowku",
        monitor.show_status !== false,
        "Ukrywa tylko wskaznik zasobow; glowny status backendu pozostaje widoczny."
      )
    ),
    settingsFieldGroup(
      "Progi alarmow backendu",
      note,
      inputField(
        "cpu_percent_threshold",
        "CPU (%)",
        monitor.cpu_percent_threshold ?? 25,
        { type: "number", min: 10, max: 90, step: 1 }
      ),
      inputField(
        "memory_percent_threshold",
        "RAM (%)",
        monitor.memory_percent_threshold ?? 20,
        { type: "number", min: 1, max: 90, step: 1 }
      ),
      inputField(
        "io_mib_per_second_threshold",
        "Dysk I/O (MB/s)",
        monitor.io_mib_per_second_threshold ?? 8,
        { type: "number", min: 1, max: 256, step: 1 }
      )
    ),
    settingsFieldGroup(
      "Test monitora",
      testNote,
      actionRow(safeButton, cpuButton, memoryButton, diskButton),
      testResult
    )
  );
  settingsSaveButton(form, (data) => ({
    resource_monitor: {
      show_status: data.has("show_status"),
      cpu_percent_threshold: data.get("cpu_percent_threshold"),
      memory_percent_threshold: data.get("memory_percent_threshold"),
      io_mib_per_second_threshold: data.get("io_mib_per_second_threshold"),
    },
  }));
  settingsOutput.appendChild(form);
  updateResourceMonitorTestUi();
}

function updateResourceMonitorTestUi() {
  const result = document.querySelector("#resourceMonitorTestResult");
  const buttons = Array.from(settingsOutput.querySelectorAll("[data-resource-monitor-test]"));
  if (result) result.textContent = resourceMonitorTestState.message;
  for (const button of buttons) button.disabled = resourceMonitorTestState.pending;
}

async function runResourceMonitorTest(mode) {
  if (resourceMonitorTestState.pending) return;
  resourceMonitorTestState.pending = true;
  resourceMonitorTestState.message = "Uruchamianie testu monitora...";
  updateResourceMonitorTestUi();
  try {
    let payload;
    if (mode === "safe") {
      payload = await requestJson("/api/resource-monitor/simulate-safe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
    } else {
      payload = await requestJson("/api/resource-monitor/real-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: mode }),
        timeoutMs: 60000,
      });
    }
    resourceMonitorTestState.message = String(payload.message || JSON.stringify(payload));
    updateResourceMonitorTestUi();
    if (payload.resources) renderResourceStatus(payload.resources);
    await pollBackendHealth();
  } catch (error) {
    resourceMonitorTestState.message = error.message || String(error);
    updateResourceMonitorTestUi();
  } finally {
    resourceMonitorTestState.pending = false;
    updateResourceMonitorTestUi();
  }
}

function ocrConfidenceLabel(value) {
  return `${Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100)}%`;
}

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

function ocrDisplayRegions(report) {
  if (report.regions.length) return report.regions;
  return report.candidates
    .filter((candidate) => Array.isArray(candidate.bbox) && candidate.bbox.length === 4)
    .map((candidate, index) => ({
      region_id: `full-image-${index + 1}`,
      fast: null,
      source_bbox: candidate.bbox.map(Number),
      crop_bbox: null,
      accurate: [{
        text: String(candidate.text || ""),
        value: String(candidate.value || ""),
        confidence: Number(candidate.confidence) || 0,
        bbox: candidate.bbox.map(Number),
      }],
      status: "full_image",
      reason: "Brak regionu szybkiego modelu: wykonano odczyt pelnego obrazu.",
      timings_ms: { fast: 0, crop: 0, accurate: 0 },
    }));
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

function pimcoreOcrStateLabel(value) {
  const state = String(value || "missing");
  const labels = {
    queued: "Oczekuje",
    scanning: "Skanowanie",
    refining: "Dopracowywanie",
    completed: "Gotowe",
    disabled: "Wyłączone",
    error: "Błąd OCR",
    missing: "Brak wyniku",
  };
  return labels[state] || state;
}

function renderPimcoreOcrCrop(image, url, bbox, label) {
  image.src = url;
  image.alt = `Wycinek OCR: ${label}`;
  const coordinates = Array.isArray(bbox) ? bbox.map(Number) : [];
  if (coordinates.length !== 4 || coordinates.some((value) => !Number.isFinite(value))) return;
  image.addEventListener("load", () => {
    const [left, top, right, bottom] = coordinates;
    const sourceWidth = image.naturalWidth;
    const sourceHeight = image.naturalHeight;
    const width = Math.max(1, right - left);
    const height = Math.max(1, bottom - top);
    if (!sourceWidth || !sourceHeight || width <= 0 || height <= 0) return;
    const canvas = document.createElement("canvas");
    canvas.width = 92;
    canvas.height = 68;
    try {
      canvas.getContext("2d")?.drawImage(
        image,
        Math.max(0, left),
        Math.max(0, top),
        Math.min(width, sourceWidth - left),
        Math.min(height, sourceHeight - top),
        0,
        0,
        canvas.width,
        canvas.height,
      );
      image.src = canvas.toDataURL("image/jpeg", 0.86);
    } catch (_error) {
      // A thumbnail remains useful if a browser prevents local canvas cropping.
    }
  }, { once: true });
}

async function renderPimcoreOcrPanel(panel) {
  const content = panel?.querySelector(".pimcore-ocr-sidebar-content");
  if (!content) return;
  const requestId = String(Number(panel.dataset.requestId || 0) + 1);
  panel.dataset.requestId = requestId;
  const slots = Object.entries(pimcoreOcrSlotTokens());
  if (!slots.length) {
    content.textContent = "Brak zdjęć w aktywnych slotach OCR.";
    return;
  }
  content.textContent = "Odczytywanie danych OCR...";
  const scans = await Promise.all(slots.map(async ([prefix, token]) => {
    const item = state.files.get(prefix) || state.loadedPhotos.get(prefix);
    let scan = { state: item?.ocr_state || "missing", values: [] };
    try {
      scan = await requestJson(`/api/ocr/scan?token=${encodeURIComponent(token)}`);
    } catch (_error) {
      // Keep the locally-known state and display it instead of hiding the slot.
    }
    return { prefix, token, item, scan };
  }));
  if (panel.dataset.requestId !== requestId) return;
  content.replaceChildren();
  for (const { prefix, item, scan } of scans) {
    const card = document.createElement("article");
    card.className = "pimcore-ocr-slot";
    const heading = document.createElement("div");
    heading.className = "pimcore-ocr-slot-heading";
    const slot = document.createElement("strong");
    slot.textContent = `Slot ${prefix}`;
    const stateLabel = document.createElement("span");
    stateLabel.className = "pimcore-ocr-slot-state";
    stateLabel.textContent = pimcoreOcrStateLabel(scan?.state || item?.ocr_state);
    heading.append(slot, stateLabel);
    card.appendChild(heading);
    const values = Array.isArray(scan?.values) ? scan.values : [];
    if (!values.length) {
      const empty = document.createElement("span");
      empty.textContent = String(scan?.state || item?.ocr_state) === "completed"
        ? "Nie wykryto wartości."
        : "Wyniki pojawią się po skanowaniu.";
      card.appendChild(empty);
    }
    const imageUrl = item?.url || item?.thumb_url || "";
    for (const value of values) {
      const row = document.createElement("div");
      row.className = "pimcore-ocr-value";
      if (imageUrl) {
        const crop = document.createElement("img");
        crop.className = "pimcore-ocr-crop";
        renderPimcoreOcrCrop(crop, imageUrl, value?.bbox, String(value?.text || "wartość"));
        row.appendChild(crop);
      }
      const text = document.createElement("span");
      text.className = "pimcore-ocr-value-text";
      const raw = String(value?.text || "");
      const comparison = String(value?.comparison || "");
      text.textContent = comparison && comparison !== raw ? `${raw} → ${comparison}` : raw || "—";
      const confidence = document.createElement("span");
      confidence.className = "pimcore-ocr-confidence";
      confidence.textContent = `${Math.round(Number(value?.confidence || 0) * 100)}%`;
      row.append(text, confidence);
      card.appendChild(row);
    }
    content.appendChild(card);
  }
}

async function refreshOpenPimcoreOcrPanels() {
  const tasks = [];
  if (pimcoreCreateModal?.classList.contains("active")) {
    tasks.push(renderPimcoreOcrPanel(pimcoreCreateOcrPanel));
  }
  if (pimcoreEditModal?.classList.contains("active")) {
    tasks.push(renderPimcoreOcrPanel(pimcoreEditOcrPanel));
  }
  await Promise.all(tasks);
}

async function revalidateOpenPimcoreOcrFields() {
  const validations = [];
  if (pimcoreCreateModal?.classList.contains("active") && pimcoreCreateForm) {
    validations.push(validatePimcoreOcrFields(pimcoreCreateForm, state.pimcoreCreateSchema));
  }
  if (pimcoreEditModal?.classList.contains("active") && pimcoreEditForm) {
    validations.push(validatePimcoreOcrFields(pimcoreEditForm, state.pimcoreEditSchema));
  }
  await Promise.all(validations);
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

function renderSettingsOcr() {
  const form = document.createElement("form");
  form.className = "settings-form";
  const ocrSettings = state.settings?.ocr || {};
  const status = document.createElement("p");
  status.className = "settings-note wide-field";
  status.textContent = "Pobieranie informacji o lokalnym OCR...";
  const engineInfo = document.createElement("div");
  engineInfo.className = "ocr-engine-info wide-field";
  const file = inputField("ocr_test_file", "Obraz testowy", "", {
    type: "file",
    description: "Obraz trafia do tymczasowego cache aplikacji; nie jest zapisywany jako konfiguracja.",
  });
  const fileInput = file.querySelector("input");
  fileInput.accept = "image/*";
  const idleSeconds = inputField("ocr_idle_seconds", "Czas bez aktywnosci (s)", ocrSettings.idle_seconds ?? 5, {
    type: "number",
    min: 0,
    max: 3600,
    step: 1,
    description: "Tyle czasu OCR czeka przed wznowieniem kolejki w tle.",
  });
  const maxCpu = inputField("ocr_max_cpu_percent", "Maksymalne uzycie CPU (%)", ocrSettings.max_cpu_percent ?? 35, {
    type: "number", min: 0, max: 100, step: 1,
    description: "Twardy limit CPU dla procesu OCR. Nie obciaza procesu panelu WWW.",
  });
  const pauseCpu = inputField("ocr_pause_cpu_percent", "Nie uruchamiaj powyzej CPU (%)", ocrSettings.pause_cpu_percent ?? 85, {
    type: "number", min: 0, max: 100, step: 1,
    description: "Przed startem kolejnego zadania OCR sprawdzane jest aktualne uzycie calego systemu.",
  });
  const memoryMode = selectField("ocr_max_memory_mode", "Miekki prog RAM systemu", ocrSettings.max_memory_mode || "percent", [
    ["percent", "Procent calego RAM"],
    ["gigabytes", "GB aktualnego uzycia"],
  ]);
  const maxMemoryPercent = inputField("ocr_max_memory_percent", "Aktualne uzycie RAM (%)", ocrSettings.max_memory_percent ?? 30, {
    type: "range", min: 1, max: 100, step: 1,
    description: "OCR sprawdza uzycie przed kazdym etapem i czeka przed rozpoczeciem kolejnego; nie przerywa etapu, ktory juz trwa.",
  });
  const maxMemoryGb = inputField("ocr_max_memory_gb", "Aktualne uzycie RAM (GB)", ocrSettings.max_memory_gb ?? 4, {
    type: "number", min: 0.1, max: 1024, step: 0.1,
    description: "Alternatywa dla procentu; dotyczy uzycia, nie pojemnosci dysku.",
  });
  const maxDiskBusy = inputField("ocr_max_disk_busy_percent", "Aktualna aktywnosc dysku (%)", ocrSettings.max_disk_busy_percent ?? 80, {
    type: "range", min: 0, max: 100, step: 1,
    description: "Przy wysokiej aktywnosci dysku OCR zwalnia miedzy etapami zamiast przerywac odczyt.",
  });
  const accurateThreshold = document.createElement("label");
  accurateThreshold.className = "ocr-accurate-threshold";
  accurateThreshold.appendChild(document.createTextNode("Skanuj dokladnym modelem przy pewnosci szybkiego do (%)"));
  const accurateThresholdControls = document.createElement("span");
  accurateThresholdControls.className = "ocr-accurate-threshold-controls";
  const accurateThresholdRange = document.createElement("input");
  accurateThresholdRange.type = "range";
  accurateThresholdRange.name = "ocr_accurate_confidence_threshold_range";
  accurateThresholdRange.min = "0";
  accurateThresholdRange.max = "100";
  accurateThresholdRange.step = "1";
  const accurateThresholdNumber = document.createElement("input");
  accurateThresholdNumber.type = "number";
  accurateThresholdNumber.name = "ocr_accurate_confidence_threshold";
  accurateThresholdNumber.min = "0";
  accurateThresholdNumber.max = "100";
  accurateThresholdNumber.step = "1";
  const initialAccurateThreshold = Math.round(Math.max(0, Math.min(100, Number(ocrSettings.accurate_confidence_threshold ?? 99) || 0)));
  accurateThresholdRange.value = String(initialAccurateThreshold);
  accurateThresholdNumber.value = String(initialAccurateThreshold);
  const synchronizeAccurateThreshold = (source, target) => {
    const value = Math.round(Math.max(0, Math.min(100, Number(source.value) || 0)));
    source.value = String(value);
    target.value = String(value);
  };
  accurateThresholdRange.addEventListener("input", () => synchronizeAccurateThreshold(accurateThresholdRange, accurateThresholdNumber));
  accurateThresholdNumber.addEventListener("input", () => synchronizeAccurateThreshold(accurateThresholdNumber, accurateThresholdRange));
  accurateThresholdControls.append(accurateThresholdRange, accurateThresholdNumber);
  accurateThreshold.append(
    accurateThresholdControls,
    document.createTextNode(" Przy 100% dokladny model skanuje kazdy wykryty wycinek; przy 50% tylko odczyty do 50% pewnosci.")
  );
  const updateMemoryMode = () => {
    const useGb = memoryMode.querySelector("select")?.value === "gigabytes";
    maxMemoryPercent.hidden = useGb;
    maxMemoryGb.hidden = !useGb;
  };
  memoryMode.querySelector("select")?.addEventListener("change", updateMemoryMode);
  updateMemoryMode();
  const background = checkField(
    "ocr_background_enabled",
    "Wlacz kolejke dopracowywania OCR w tle",
    Boolean(ocrSettings.background_enabled),
    "Kolejka dziala dopiero po okresie bez aktywnosci uzytkownika."
  );
  const queueVisibility = checkField(
    "ocr_background_queue_visible_to_users",
    "Pokaz kolejke dopracowywania OCR uzytkownikom",
    Boolean(ocrSettings.background_queue_visible_to_users),
    "Administrator widzi kolejke zawsze; zwykli uzytkownicy tylko po wlaczeniu tej opcji."
  );
  const profiles = document.createElement("div");
  profiles.className = "ocr-profile-options wide-field";
  const profileHeading = document.createElement("div");
  const profileTitle = document.createElement("strong");
  const profileHelp = document.createElement("span");
  profileTitle.textContent = "Mechanizm OCR";
  profileHelp.textContent = "Wybierz szybszy, dokladniejszy albo oba lokalnie dostepne profile. Aplikacja niczego nie pobiera podczas pracy.";
  profileHeading.className = "ocr-profile-options-heading";
  profileHeading.append(profileTitle, profileHelp);
  profiles.appendChild(profileHeading);
  const selectedProfiles = new Set((ocrSettings.model_profiles || ["fast"]).map(String));
  const profileDefinitions = [
    { id: "fast", title: "Szybki", description: "PP-OCRv5 Mobile — najszybszy odczyt." },
    { id: "accurate", title: "Dokladny", description: "PP-OCRv5 Server — wolniejszy, z wieksza szansa na trudny odczyt." },
  ];
  const profileCards = new Map();
  for (const profile of profileDefinitions) {
    const card = document.createElement("label");
    const input = document.createElement("input");
    const details = document.createElement("span");
    const title = document.createElement("strong");
    const description = document.createElement("small");
    const availability = document.createElement("em");
    card.className = "ocr-profile-card";
    input.type = "checkbox";
    input.name = "ocr_model_profile";
    input.value = profile.id;
    input.checked = selectedProfiles.has(profile.id);
    title.textContent = profile.title;
    description.textContent = profile.description;
    availability.textContent = "Sprawdzanie dostepnosci...";
    details.append(title, description, availability);
    card.append(input, details);
    profiles.appendChild(card);
    profileCards.set(profile.id, { card, input, availability });
  }
  const slotsHeading = document.createElement("div");
  const slotsTitle = document.createElement("strong");
  const slotsCount = document.createElement("span");
  slotsHeading.className = "ocr-slot-list-heading wide-field";
  slotsTitle.textContent = "Sloty objete kolejka";
  slotsHeading.append(slotsTitle, slotsCount);
  const slots = document.createElement("div");
  slots.className = "settings-slot-list ocr-slot-grid wide-field";
  const enabledSlots = new Set((ocrSettings.enabled_slots || []).map(String));
  const updateSelectedSlotCount = () => {
    const selected = slots.querySelectorAll('input[name="ocr_enabled_slot"]:checked').length;
    slotsCount.textContent = `${selected} z ${(state.settings?.slots || []).length} zaznaczonych`;
  };
  for (const slot of state.settings?.slots || []) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "ocr_enabled_slot";
    input.value = String(slot.prefix || "");
    input.checked = enabledSlots.has(input.value);
    input.addEventListener("change", updateSelectedSlotCount);
    label.append(input, document.createTextNode(` ${slot.label || "Slot"}`));
    const code = document.createElement("small");
    code.textContent = input.value;
    label.appendChild(code);
    slots.appendChild(label);
  }
  updateSelectedSlotCount();
  const analyze = document.createElement("button");
  analyze.type = "button";
  analyze.className = "secondary-button";
  analyze.textContent = "Przetestuj OCR";
  const cancelAnalyze = document.createElement("button");
  cancelAnalyze.type = "button";
  cancelAnalyze.className = "secondary-button";
  cancelAnalyze.textContent = "Zatrzymaj po etapie";
  cancelAnalyze.hidden = true;
  const results = document.createElement("div");
  results.className = "wide-field";
  const collection = settingsFieldGroup(
    "Zbieranie wartosci OCR",
    background,
    queueVisibility,
    idleSeconds,
    maxCpu,
    pauseCpu,
    memoryMode,
    maxMemoryPercent,
    maxMemoryGb,
    maxDiskBusy,
    profiles,
    accurateThreshold,
    slotsHeading,
    slots
  );
  collection.classList.add("ocr-collection-settings");
  form.append(
    collection,
    settingsFieldGroup("Tester OCR", status, engineInfo, file, actionRow(analyze, cancelAnalyze), results)
  );
  analyze.addEventListener("click", async () => {
    const selected = fileInput.files?.[0];
    if (!selected) {
      status.textContent = "Wybierz obraz do analizy.";
      return;
    }
    analyze.disabled = true;
    results.textContent = "";
    let livePreview = null;
    let activeRunId = "";
    let cancelled = false;
    cancelAnalyze.hidden = false;
    cancelAnalyze.onclick = async () => {
      if (!activeRunId || cancelled) return;
      cancelled = true;
      cancelAnalyze.disabled = true;
      try {
        await requestJson(`/api/settings/ocr/runs/${encodeURIComponent(activeRunId)}/cancel`, { method: "POST" });
        status.textContent = "Anulowanie zostanie wykonane po biezacym etapie OCR.";
      } catch (error) {
        status.textContent = error.message || "Nie udalo sie anulowac OCR.";
      }
    };
    status.textContent = "Wysylanie obrazu do lokalnego testu OCR...";
    try {
      const upload = new FormData();
      upload.set("prefix", "ocr-test");
      upload.set("file", selected, selected.name || "ocr-test-image");
      const cached = await requestJson("/api/upload-cache", { method: "POST", body: upload, timeoutMs: 120000 });
      if (!cached.token) throw new Error("Backend nie zwrocil tokenu obrazu testowego.");
      livePreview = await renderOcrLivePreview(selected);
      results.appendChild(livePreview.element);
      livePreview.setStatus("Wysylanie zadania do procesu OCR...");
      status.textContent = "Analiza OCR trwa — sektory i wycinki beda pokazywane na zywo.";
      const started = await requestJson("/api/settings/ocr/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: cached.token }),
        timeoutMs: 30000,
      });
      activeRunId = String(started.run_id || "");
      if (!activeRunId) throw new Error("Backend nie zwrocil identyfikatora testu OCR.");
      livePreview.setStatus("Zadanie przekazane do procesu OCR; oczekiwanie na rozpoczecie etapu.");
      let sequence = 0;
      let finalSnapshot = null;
      while (!finalSnapshot) {
        const snapshot = await requestJson(`/api/settings/ocr/runs/${encodeURIComponent(activeRunId)}?after_sequence=${sequence}`, { timeoutMs: 30000 });
        sequence = Math.max(sequence, Number(snapshot.latest_sequence) || 0);
        for (const event of Array.isArray(snapshot.events) ? snapshot.events : []) {
          livePreview.showEvent(event);
        }
        if (["completed", "error", "cancelled", "paused"].includes(String(snapshot.state || ""))) {
          finalSnapshot = snapshot;
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 600));
      }
      livePreview.dispose();
      results.textContent = "";
      const result = { ...(finalSnapshot.result || {}), image_url: URL.createObjectURL(selected) };
      results.appendChild(renderOcrDiagnostics(result));
      status.textContent = finalSnapshot.state === "paused"
        ? "Test OCR wstrzymany przez prog uruchomienia zasobow."
        : result.available
        ? "Analiza OCR zakonczona."
        : String(result.message || finalSnapshot.error || "Lokalny OCR nie jest dostepny.");
    } catch (error) {
      status.textContent = error.message || "Nie udalo sie wykonac analizy OCR.";
    } finally {
      livePreview?.dispose();
      analyze.disabled = false;
      cancelAnalyze.hidden = true;
      cancelAnalyze.disabled = false;
    }
  });
  settingsSaveButton(form, (data) => ({
    ocr: {
      enabled_slots: [...form.querySelectorAll('[name="ocr_enabled_slot"]:checked')].map((input) => input.value),
      model_profiles: [...form.querySelectorAll('[name="ocr_model_profile"]:checked')].map((input) => input.value),
      background_enabled: data.has("ocr_background_enabled"),
      background_queue_visible_to_users: data.has("ocr_background_queue_visible_to_users"),
      idle_seconds: data.get("ocr_idle_seconds"),
      max_cpu_percent: data.get("ocr_max_cpu_percent"),
      pause_cpu_percent: data.get("ocr_pause_cpu_percent"),
      max_memory_mode: data.get("ocr_max_memory_mode"),
      max_memory_percent: data.get("ocr_max_memory_percent"),
      max_memory_gb: data.get("ocr_max_memory_gb"),
      max_disk_busy_percent: data.get("ocr_max_disk_busy_percent"),
      accurate_confidence_threshold: data.get("ocr_accurate_confidence_threshold"),
    },
  }));
  settingsOutput.appendChild(form);
  requestJson("/api/settings/ocr/status")
    .then((info) => {
      const engine = info.engine || {};
      const runtime = info.runtime || {};
      const models = Array.isArray(info.models) ? info.models : [];
      const modelStatuses = new Map(models.map((model) => [String(model.id || ""), model]));
      for (const profile of profileDefinitions) {
        const controls = profileCards.get(profile.id);
        const model = modelStatuses.get(profile.id);
        if (!controls) continue;
        const available = model?.status === "ready";
        controls.input.disabled = !available;
        if (!available) controls.input.checked = false;
        controls.card.classList.toggle("unavailable", !available);
        controls.availability.textContent = available
          ? "Dostepny lokalnie"
          : "Niedostepny lokalnie";
      }
      engineInfo.textContent = "";
      const title = document.createElement("strong");
      title.textContent = `${engine.name || "OCR"} ${engine.version || ""}`.trim();
      const runtimeLine = document.createElement("span");
      runtimeLine.textContent = `${runtime.name || "Runtime"}: ${runtime.version || "brak"}`;
      const modelList = document.createElement("ul");
      for (const model of models) {
        const item = document.createElement("li");
        item.textContent = `${model.name || "Model"} ${model.version ? `(${model.version})` : ""} — ${model.status || "unknown"}`;
        modelList.appendChild(item);
      }
      const link = document.createElement("a");
      link.href = String(info.github_url || "https://github.com/PaddlePaddle/PaddleOCR");
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "Oficjalny projekt OCR na GitHub";
      engineInfo.append(title, runtimeLine, modelList, link);
      const modelReady = models.some((model) => model.status === "ready");
      status.textContent = !info.available
        ? "Silnik OCR nie jest dostepny w tej instalacji."
        : modelReady
          ? "Silnik OCR i model sa gotowe do testu."
          : "Silnik OCR jest zainstalowany, ale wybrany profil nie jest dostepny lokalnie.";
    })
    .catch((error) => {
      status.textContent = error.message || "Nie udalo sie odczytac statusu OCR.";
    });
}

function moduleBuildStatusUtilities() {
  return window.PicSyncra?.ModuleBuildStatus || null;
}

function moduleBuildStatusValue(value) {
  return String(value || "").trim() || "Brak danych";
}

function moduleBuildStatusCommitNode(value, utilities) {
  const commit = moduleBuildStatusValue(value);
  const url = utilities.commitUrl(value);
  const node = document.createElement(url ? "a" : "span");
  node.textContent = commit;
  if (url) {
    node.href = url;
    node.target = "_blank";
    node.rel = "noreferrer";
    node.title = "Otworz commit na GitHub";
  }
  return node;
}

function appendModuleBuildStatusRow(tableBody, module, statusLabel, utilities) {
  const row = document.createElement("tr");
  const moduleCell = document.createElement("td");
  const buildCell = document.createElement("td");
  const localCell = document.createElement("td");
  const statusCell = document.createElement("td");
  const title = document.createElement("strong");
  const identifier = document.createElement("small");
  const buildDate = document.createElement("small");
  const localDate = document.createElement("small");
  const badge = document.createElement("span");

  title.textContent = moduleBuildStatusValue(module.label);
  identifier.textContent = moduleBuildStatusValue(module.id);
  buildDate.textContent = moduleBuildStatusValue(module.build_committed_at);
  localDate.textContent = moduleBuildStatusValue(module.local_committed_at);
  badge.className = `module-build-status-badge ${module.status || "unknown"}`;
  badge.textContent = statusLabel;
  badge.setAttribute("aria-label", `Status: ${statusLabel}`);

  moduleCell.append(title, identifier);
  buildCell.append(moduleBuildStatusCommitNode(module.build_commit, utilities), buildDate);
  localCell.append(moduleBuildStatusCommitNode(module.local_commit, utilities), localDate);
  statusCell.appendChild(badge);
  row.append(moduleCell, buildCell, localCell, statusCell);
  tableBody.appendChild(row);
}

async function loadModuleBuildStatus() {
  const utilities = moduleBuildStatusUtilities();
  if (!utilities) {
    throw new Error("Nie zaladowano modulu statusu buildu.");
  }
  state.moduleBuildStatusLoading = true;
  state.moduleBuildStatusError = "";
  try {
    const payload = await requestJson("/api/settings/module-status");
    state.moduleBuildStatus = utilities.normalizeSnapshot(payload);
    return state.moduleBuildStatus;
  } catch (error) {
    state.moduleBuildStatusError = error.message || "Nie udalo sie odczytac statusu buildu.";
    throw error;
  } finally {
    state.moduleBuildStatusLoading = false;
  }
}

function renderSettingsModuleStatus() {
  const utilities = moduleBuildStatusUtilities();
  const panel = document.createElement("section");
  const heading = document.createElement("div");
  const title = document.createElement("h2");
  const refresh = document.createElement("button");
  const description = document.createElement("p");

  panel.className = "settings-block module-build-status";
  heading.className = "module-build-status-heading";
  title.textContent = "Wersje modulow";
  refresh.type = "button";
  refresh.className = "secondary-button";
  refresh.textContent = "Odswiez porownanie";
  refresh.disabled = state.moduleBuildStatusLoading;
  refresh.addEventListener("click", () => {
    loadModuleBuildStatus()
      .catch(() => {})
      .finally(() => renderSettings());
  });
  description.className = "settings-note";
  description.textContent = "Porownanie jest lokalne i tylko do odczytu. Nie wysyla danych do GitHub ani nie uruchamia builda.";
  heading.append(title, refresh);
  panel.append(heading, description);

  if (state.moduleBuildStatusLoading) {
    const loading = document.createElement("p");
    loading.className = "settings-note";
    loading.textContent = "Odczytywanie wersji modulow...";
    panel.appendChild(loading);
  } else if (state.moduleBuildStatusError) {
    const error = document.createElement("p");
    error.className = "error-text";
    error.textContent = state.moduleBuildStatusError;
    panel.appendChild(error);
  } else if (!state.moduleBuildStatus) {
    const loading = document.createElement("p");
    loading.className = "settings-note";
    loading.textContent = "Przygotowywanie porownania...";
    panel.appendChild(loading);
  } else if (!utilities) {
    const error = document.createElement("p");
    error.className = "error-text";
    error.textContent = "Nie zaladowano modulu statusu buildu.";
    panel.appendChild(error);
  } else {
    const snapshot = utilities.normalizeSnapshot(state.moduleBuildStatus);
    const build = snapshot.build;
    const summary = document.createElement("div");
    summary.className = "module-build-status-summary";
    if (build) {
      for (const [label, value] of [
        ["Wariant", build.build_variant],
        ["Build", build.generated_at],
        ["Commit repozytorium", build.repository_commit],
      ]) {
        const item = document.createElement("div");
        const itemLabel = document.createElement("span");
        const itemValue = document.createElement("strong");
        itemLabel.textContent = label;
        if (label === "Commit repozytorium") {
          itemValue.appendChild(moduleBuildStatusCommitNode(value, utilities));
        } else {
          itemValue.textContent = moduleBuildStatusValue(value);
        }
        item.append(itemLabel, itemValue);
        summary.appendChild(item);
      }
    } else {
      summary.textContent = "Brak wbudowanych danych buildu. Ten program wymaga ponownego zbudowania.";
    }
    panel.appendChild(summary);

    if (snapshot.repository_status !== "available") {
      const note = document.createElement("p");
      note.className = "settings-note";
      note.textContent = "Nie znaleziono lokalnego repozytorium Git, dlatego widoczne sa tylko dane wbudowane w program.";
      panel.appendChild(note);
    }

    const tableWrapper = document.createElement("div");
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    const body = document.createElement("tbody");
    tableWrapper.className = "module-build-status-table-wrapper";
    table.className = "module-build-status-table";
    for (const label of ["Modul", "Wbudowany build", "Lokalne repozytorium", "Status"]) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      headRow.appendChild(cell);
    }
    head.appendChild(headRow);
    for (const module of snapshot.modules) {
      appendModuleBuildStatusRow(
        body,
        module,
        utilities.statusLabel(module.status),
        utilities,
      );
    }
    if (!snapshot.modules.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = "Brak danych o modulach w tym buildzie.";
      row.appendChild(cell);
      body.appendChild(row);
    }
    table.append(head, body);
    tableWrapper.appendChild(table);
    panel.appendChild(tableWrapper);
  }

  settingsOutput.appendChild(panel);
  if (!state.moduleBuildStatus && !state.moduleBuildStatusLoading && !state.moduleBuildStatusError) {
    loadModuleBuildStatus()
      .catch(() => {})
      .finally(() => {
        if (state.activeSettingsTab === "module-status") renderSettings();
      });
  }
}

function renderSettings() {
  if (!state.settings) {
    return;
  }
  settingsOutput.textContent = "";
  document.querySelectorAll(".settings-tab").forEach((button) => {
    const isOcrTab = button.dataset.settingsTab === "ocr";
    button.hidden = isOcrTab && state.settings.ocr_available === false;
    button.classList.toggle("active", button.dataset.settingsTab === state.activeSettingsTab);
  });
  if (state.settings.ocr_available === false && state.activeSettingsTab === "ocr") {
    state.activeSettingsTab = "app";
  }
  settingsStatus.textContent = state.settings.windows_admin
    ? "Proces backendu ma uprawnienia administratora Windows. Rola web admin jest niezalezna."
    : "Proces backendu dziala bez uprawnien administratora Windows. Rola web admin jest niezalezna.";
  if (state.activeSettingsTab === "app") renderSettingsApp();
  if (state.activeSettingsTab === "module-status") renderSettingsModuleStatus();
  if (state.activeSettingsTab === "processing") renderSettingsProcessing();
  if (state.activeSettingsTab === "security") renderSettingsSecurity();
  if (state.activeSettingsTab === "ftp") renderSettingsFtp();
  if (state.activeSettingsTab === "sql") renderSettingsSql();
  if (state.activeSettingsTab === "pimcore") renderSettingsPimcore();
  if (state.activeSettingsTab === "ocr") renderSettingsOcr();
  if (state.activeSettingsTab === "mail") renderSettingsMail();
  if (state.activeSettingsTab === "monitor") renderSettingsResourceMonitor();
  if (state.activeSettingsTab === "slots") renderSettingsSlots();
  if (state.activeSettingsTab === "users") renderSettingsUsers();
}

async function loadSettings() {
  const [settingsPayload, catalogPayload] = await Promise.all([
    requestJson("/api/settings"),
    requestJson("/api/settings/time-zones"),
  ]);
  state.settings = settingsPayload;
  state.panelTimeZones = [...new Set(
    (Array.isArray(catalogPayload.time_zones) ? catalogPayload.time_zones : [])
      .map((value) => String(value || "").trim())
      .filter(Boolean)
  )];
  state.settingsSecrets = null;
  state.currentUser = state.settings.current_user || state.currentUser;
  state.defaultSlotFit = Boolean(state.settings.auto_content_fit);
  state.ftpEnabled = state.settings.ftp?.enabled !== false;
  state.processing = state.settings.processing || state.processing || {};
  state.security = state.settings.security || state.security || {};
  state.productFields = state.settings.product_fields || state.productFields || {};
  updateAdminUi();
  renderResourceStatus(state.resources);
  applyTimingDetailsVisibility();
  applyProductFieldLabels();
  renderSettings();
}

document.querySelectorAll("[data-modal]").forEach((button) => {
  button.addEventListener("click", () => openModal(button.dataset.modal));
});

document.querySelectorAll("[data-close-modal]").forEach((button) => {
  button.addEventListener("click", closeModals);
});

similarDecisionRejectAllButton?.addEventListener("click", () => {
  const prefixes = [...pendingSimilarCandidatePrefixes()];
  for (const prefix of prefixes) {
    dismissSimilarCandidate(prefix);
    renderSlot(prefix);
  }
  renderSimilarDecisionModal();
});

similarDecisionContinueButton?.addEventListener("click", () => {
  if (pendingSimilarCandidatePrefixes().length) return;
  closeSimilarDecisionModal();
  submitProductForm().catch(handleProductSubmitError);
});

document.querySelectorAll("[data-close-similar-decision]").forEach((button) => {
  button.addEventListener("click", closeSimilarDecisionModal);
});

similarDecisionModal?.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const focusable = Array.from(
    similarDecisionModal.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  );
  if (!focusable.length) return;
  const currentIndex = focusable.indexOf(document.activeElement);
  if (event.shiftKey && currentIndex <= 0) {
    event.preventDefault();
    focusable.at(-1)?.focus();
  } else if (!event.shiftKey && currentIndex === focusable.length - 1) {
    event.preventDefault();
    focusable[0]?.focus();
  }
});

document.querySelectorAll("[data-close-web-images]").forEach((button) => {
  button.addEventListener("click", closeWebImagesModal);
});

document.querySelectorAll("[data-close-github-status]").forEach((button) => {
  button.addEventListener("click", () => {
    githubStatusModal?.classList.remove("active");
  });
});

document.querySelectorAll("[data-close-history-detail]").forEach((button) => {
  button.addEventListener("click", closeHistoryDetail);
});

document.querySelectorAll("[data-close-history-timing]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#historyTimingModal")?.classList.remove("active");
  });
});

document.querySelectorAll("[data-close-history-changes]").forEach((button) => {
  button.addEventListener("click", closeHistoryChangesModal);
});
historyChangesModal?.addEventListener("keydown", trapHistoryChangesFocus);

document.querySelectorAll("[data-close-backup-history]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#backupHistoryModal")?.classList.remove("active");
  });
});

document.querySelectorAll("[data-close-backup-diff]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#backupDiffModal")?.classList.remove("active");
  });
});

document.querySelectorAll("[data-close-logs-clear]").forEach((button) => {
  button.addEventListener("click", closeLogsClearModal);
});

document.querySelectorAll("[data-close-secret-reveal]").forEach((button) => {
  button.addEventListener("click", () => closeSecretRevealModal());
});

document.querySelectorAll("[data-close-process-alert]").forEach((button) => {
  button.addEventListener("click", closeProcessAlert);
});

pimcoreTestSubmitButton?.addEventListener("click", () => {
  submitPimcoreWriteTest().catch((error) => {
    if (pimcoreTestStatus) {
      pimcoreTestStatus.textContent = error.message;
    }
    if (pimcoreTestSubmitButton) {
      pimcoreTestSubmitButton.disabled = false;
    }
    if (pimcoreTestClearButton) {
      pimcoreTestClearButton.disabled = false;
    }
    if (pimcoreTestRegenerateButton) {
      pimcoreTestRegenerateButton.disabled = false;
    }
  });
});

pimcoreTestClearButton?.addEventListener("click", () => {
  if (state.pimcoreTestOperation?.active) return;
  pimcoreTestForm.reset();
  pimcoreTestModal.querySelectorAll('[name="pimcore_cleanup_policy"]').forEach((item) => {
    item.checked = false;
  });
  clearPimcoreLiveLog();
});

pimcoreTestCloseButton?.addEventListener("click", () => {
  if (pimcoreTestModal) {
    pimcoreTestModal.classList.remove("active");
  }
});

pimcoreTestRegenerateButton?.addEventListener("click", () => {
  if (state.pimcoreTestOperation?.active) return;
  clearPimcoreLiveLog();
  loadPimcoreTestSample();
});

pimcoreTemplateTranslate?.addEventListener("change", () => {
  pimcoreTemplateLanguage.disabled = !pimcoreTemplateTranslate.checked;
  if (pimcoreTemplateTranslate.checked) {
    if (!pimcoreTemplateLanguage.value.trim()) {
      pimcoreTemplateLanguage.value = pimcoreTemplateLanguageForRow(state.pimcoreTemplateRow);
    }
    pimcoreTemplateLanguage.focus();
  }
});

pimcoreTemplatePreviewButton?.addEventListener("click", previewPimcoreTemplate);
pimcoreTemplateSaveButton?.addEventListener("click", savePimcoreTemplateBuilder);
pimcoreTemplateClearButton?.addEventListener("click", () => {
  pimcoreTemplateText.value = "";
  const sqlQuery = pimcoreTemplateSqlControls?.querySelector('[name="mapping_sql_query"]');
  const sqlProfile = pimcoreTemplateSqlControls?.querySelector('[name="mapping_sql_profile_id"]');
  if (sqlQuery) sqlQuery.value = "";
  if (sqlProfile) sqlProfile.value = "";
  pimcoreTemplateTranslate.checked = false;
  pimcoreTemplateLanguage.value = "";
  pimcoreTemplateLanguage.disabled = true;
  pimcoreTemplateOcrValidation.checked = false;
  savePimcoreTemplateBuilder();
});
pimcoreTemplateCancelButton?.addEventListener("click", closePimcoreTemplateBuilder);
pimcoreTemplateHelpButton?.addEventListener("click", openPimcoreTemplateHelp);
pimcoreTemplateHelpCloseButton?.addEventListener("click", closePimcoreTemplateHelp);

pimcoreHistoryCloseButton?.addEventListener("click", () => {
  if (pimcoreHistoryModal) {
    pimcoreHistoryModal.classList.remove("active");
  }
});

pimcoreHistoryFilters?.addEventListener("submit", (event) => {
  event.preventDefault();
  loadPimcoreHistory().catch((error) => {
    if (pimcoreHistoryOutput) {
      pimcoreHistoryOutput.className = "history-output empty-state";
      pimcoreHistoryOutput.textContent = error.message;
    }
  });
});

pimcoreHistoryExportCsvButton?.addEventListener("click", () => exportPimcoreSubmissions("csv"));
pimcoreHistoryExportXlsxButton?.addEventListener("click", () => exportPimcoreSubmissions("xlsx"));
pimcoreExportCloseButton?.addEventListener("click", closePimcoreExportModal);
pimcoreExportCsvButton?.addEventListener("click", () => {
  closePimcoreExportModal();
  exportPimcoreSubmissions("csv", { includeFilters: false });
});
pimcoreExportXlsxButton?.addEventListener("click", () => {
  closePimcoreExportModal();
  exportPimcoreSubmissions("xlsx", { includeFilters: false });
});
pimcoreExportLayoutCloseButton?.addEventListener("click", closePimcoreExportLayoutModal);
pimcoreExportLayoutCancelButton?.addEventListener("click", closePimcoreExportLayoutModal);
pimcoreExportLayoutList?.addEventListener("pointerdown", startPimcoreExportLayoutMarquee);
pimcoreExportLayoutAddFieldButton?.addEventListener("click", () => {
  pimcoreExportLayoutDraft = collectPimcoreExportColumns();
  const usedFields = new Set(
    pimcoreExportLayoutDraft
      .filter((column) => column.type === "field")
      .map((column) => String(column.pimcore_field || ""))
  );
  const mapping = pimcoreExportFieldMappings().find(
    (item) => !usedFields.has(String(item.pimcore_field || ""))
  );
  if (!mapping) return;
  const pimcore_field = String(mapping.pimcore_field || "");
  pimcoreExportLayoutDraft.push({ type: "field", pimcore_field, header: pimcore_field });
  renderPimcoreExportLayout();
});
pimcoreExportLayoutAddBlankButton?.addEventListener("click", () => {
  pimcoreExportLayoutDraft = collectPimcoreExportColumns();
  pimcoreExportLayoutDraft.push({ type: "blank", header: "" });
  renderPimcoreExportLayout();
});
pimcoreExportLayoutSaveButton?.addEventListener("click", savePimcoreExportColumns);

pimcoreMissingCreateButton?.addEventListener("click", () => {
  openPimcoreCreateModal(state.pimcoreMissingEan);
});

pimcoreMissingContinueButton?.addEventListener("click", () => {
  pimcoreMissingModal?.classList.remove("active");
});

pimcoreMissingCancelButton?.addEventListener("click", () => {
  pimcoreMissingModal?.classList.remove("active");
});

pimcoreCreateCancelButton?.addEventListener("click", () => {
  pimcoreCreateModal?.classList.remove("active");
});

pimcoreCreateForm?.addEventListener("submit", submitPimcoreRuntimeCreate);
pimcoreCreateRecalculateAllButton?.addEventListener("click", recalculateAllPimcoreCreateFields);

pimcoreEditButton?.addEventListener("click", openPimcoreEditModal);
pimcoreEditForm?.addEventListener("submit", submitPimcoreRuntimeEdit);
pimcoreEditRecalculateAllButton?.addEventListener("click", recalculateAllPimcoreEditFields);
pimcoreEditCancelButton?.addEventListener("click", () => {
  closePimcoreEditModal();
});

pimcoreSetupNextButton?.addEventListener("click", advancePimcoreSetup);
pimcoreSetupBackButton?.addEventListener("click", () => {
  capturePimcoreSetupStep();
  if (!state.pimcoreSetup) return;
  state.pimcoreSetup.step = Math.max(1, state.pimcoreSetup.step - 1);
  renderPimcoreSetupStep();
});
pimcoreSetupCancelButton?.addEventListener("click", () => {
  pimcoreSetupModal?.classList.remove("active");
  state.pimcoreSetup = null;
});

processAlertLoadButton?.addEventListener("click", () => {
  const jobId = processAlertLoadButton.dataset.jobId || "";
  const job = state.processJobs.get(jobId);
  if (!job) {
    closeProcessAlert();
    return;
  }
  if (hasPendingUserChanges() && !window.confirm("Wczytac wpis z zadania i zastapic aktualny formularz?")) {
    return;
  }
  const entry = entryFromProcessJob(job);
  fillForm(entry, { loadPhotos: Boolean(entry.product_id || entry.ean) });
  closeProcessAlert();
});

activeUsersMoreButton?.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleActiveUsersPopover();
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".mail-help")) {
    closeMailHelpPopover();
  }
  if (!activeUsersPresence || activeUsersPresence.contains(event.target)) {
    return;
  }
  toggleActiveUsersPopover(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeMailHelpPopover({ restoreFocus: true });
    toggleActiveUsersPopover(false);
  }
});

themeToggleButton?.addEventListener("click", () => {
  state.theme = state.theme === "dark" ? "light" : "dark";
  applyTheme();
});

githubStatusButton?.addEventListener("click", () => {
  openGithubStatusModal();
  refreshGithubStatus().catch(() => {});
});

document.querySelectorAll(".settings-tab").forEach((button) => {
  button.addEventListener("click", () => {
    state.activeSettingsTab = button.dataset.settingsTab;
    renderSettings();
  });
});

historyUserFilter?.addEventListener("change", () => {
  state.historyPage = 1;
  loadHistory({ page: 1 }).catch(showHistoryLoadError);
});

historySearchInput?.addEventListener("input", () => {
  window.clearTimeout(state.historySearchTimer);
  state.historySearchTimer = window.setTimeout(() => {
    state.historyPage = 1;
    loadHistory({ page: 1 }).catch(showHistoryLoadError);
  }, 250);
});

historyRefreshButton?.addEventListener("click", () => {
  loadHistory({ page: state.historyPage || 1 }).catch(showHistoryLoadError);
});

historyPrevButton?.addEventListener("click", () => {
  const page = Math.max(1, Number(state.historyPage || 1) - 1);
  loadHistory({ page }).catch(showHistoryLoadError);
});

historyNextButton?.addEventListener("click", () => {
  const page = Math.max(1, Number(state.historyPage || 1) + 1);
  loadHistory({ page }).catch(showHistoryLoadError);
});

historyDetailPrevButton?.addEventListener("click", () => {
  const group = state.historyDetailGroup;
  if (!group) return;
  const page = Math.max(1, Number(state.historyDetailPage || 1) - 1);
  loadHistoryDetails(group, { page }).catch(showHistoryDetailLoadError);
});

historyDetailNextButton?.addEventListener("click", () => {
  const group = state.historyDetailGroup;
  if (!group) return;
  const page = Math.max(1, Number(state.historyDetailPage || 1) + 1);
  loadHistoryDetails(group, { page }).catch(showHistoryDetailLoadError);
});

document.querySelectorAll("[data-log-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    switchLogTab(button.dataset.logTab || "live").catch(showLogsError);
  });
});

logsFilters?.addEventListener("submit", (event) => {
  event.preventDefault();
  const filtersChanged = commitLogFilters();
  renderLogs();
  const tabName = state.observability.activeTab;
  if (filtersChanged && tabName === "live") {
    seedLiveLogs({ force: true }).catch(showLogsError);
  }
  if (["critical", "error", "warning"].includes(tabName)) {
    markSeverityRead(tabName, observabilityTab(tabName).requestId).catch(showLogsError);
  }
});

logsFilters?.addEventListener("reset", () => {
  const filtersChanged = resetCommittedLogFilters();
  renderLogs();
  const tabName = state.observability.activeTab;
  if (filtersChanged && tabName === "live") {
    seedLiveLogs({ force: true }).catch(showLogsError);
  }
  if (["critical", "error", "warning"].includes(tabName)) {
    markSeverityRead(tabName, observabilityTab(tabName).requestId).catch(showLogsError);
  }
});

logsPauseButton?.addEventListener("click", () => {
  state.observability.paused = !state.observability.paused;
  logsPauseButton.textContent = state.observability.paused ? "Wznow" : "Wstrzymaj";
  if (state.observability.paused) {
    if (logsStreamStatus) logsStreamStatus.textContent = "Wstrzymano";
    return;
  }
  const buffered = state.observability.buffer.splice(0);
  const live = observabilityTab("live");
  live.items = mergeLiveItems([...live.items, ...buffered], live.archiveSince);
  if (logsStreamStatus) {
    logsStreamStatus.textContent = state.observability.streamConnected
      ? "Polaczono"
      : state.observability.stream
        ? "Laczenie..."
        : "Rozlaczono";
  }
  renderLogs();
});

if (logsAutoscrollToggle) {
  logsAutoscrollToggle.checked = state.observability.autoscroll;
  logsAutoscrollToggle.addEventListener("change", () => {
    state.observability.autoscroll = logsAutoscrollToggle.checked;
    localStorage.setItem(LOG_AUTOSCROLL_KEY, String(state.observability.autoscroll));
    if (state.observability.autoscroll && state.observability.activeTab === "live") {
      logsOutput.scrollTop = logsOutput.scrollHeight;
    }
  });
}

logsLoadMoreButton?.addEventListener("click", () => {
  loadObservabilityTab(state.observability.activeTab, { append: true }).catch(showLogsError);
});

logsRefreshButton?.addEventListener("click", () => {
  loadLogs({ refresh: true }).catch(showLogsError);
});

logsClearButton?.addEventListener("click", () => {
  openLogsClearModal();
});

logsClearForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  clearLogs(logsClearPassword.value).catch((error) => {
    if (logsClearStatus) {
      logsClearStatus.textContent = error.message;
    }
  });
});

secretRevealForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const password = secretRevealPassword?.value || "";
  if (!password) {
    if (secretRevealStatus) {
      secretRevealStatus.textContent = "Podaj haslo administratora.";
    }
    return;
  }
  closeSecretRevealModal(password);
});

entrySelect.addEventListener("change", () => {
  const option = entrySelect.selectedOptions[0];
  if (!option || !option.dataset.entry) return;
  fillForm(JSON.parse(option.dataset.entry), { loadPhotos: true });
});

for (const name of ["name", "type_name", "model"]) {
  productForm.elements[name].addEventListener("input", scheduleProductAutoSearch);
}

productForm.elements.ean?.addEventListener("input", handlePimcoreEanInput);

for (const name of trackedProductFields) {
  productForm.elements[name]?.addEventListener("input", () => {
    scheduleBackgroundFtpLookup();
    scheduleSimilarFileLookup();
  });
}

for (const name of Object.keys(fieldListKey)) {
  productForm.elements[name]?.addEventListener("change", () => {
    promptAddProductFieldToList(name).catch((error) => {
      formStatus.textContent = error.message;
    });
  });
}

function handleProductSubmitError(error) {
  stopProcessStatusTicker();
  showError(error);
  setBusy(false, "");
}

async function submitProductForm() {
  clearResult();
  recordOcrActivity();
  try {
    ensureSlotUploadsReady();
    setBusy(true, "Sprawdzanie list...");
    await ensureProductListValues();
    if (pendingSimilarCandidatePrefixes().length) {
      setBusy(false, "");
      openSimilarDecisionModal();
      return;
    }
    const identityChanged = productFieldsChangedSinceLoad();
    const updateMode = hasPendingUserChanges();
    setBusy(
      true,
      updateMode
        ? identityChanged
          ? "Aktualizowanie i przenoszenie istniejacych zdjec..."
          : "Aktualizowanie..."
        : "Synchronizowanie brakujacych danych..."
    );
    const changedPrefixes = pendingChangedSlotPrefixes();
    const data = new FormData(productForm);
    for (const slot of state.slots || []) {
      data.delete(`slot_${slot.prefix}`);
    }
    for (const [prefix, item] of state.files.entries()) {
      const token = slotFileToken(item);
      if (token) {
        data.set(`existing_slot_${prefix}`, token);
        data.set(`existing_slot_name_${prefix}`, slotFileName(item));
        if (item.preprocessed) {
          data.set(`existing_slot_preprocessed_${prefix}`, "1");
        }
      } else {
        const file = slotFileObject(item);
        if (!file) {
          throw new Error(`Slot ${prefix} nie ma pliku ani tokenu cache.`);
        }
        data.set(`slot_${prefix}`, file, file.name);
      }
      data.set(`slot_fit_${prefix}`, isSlotFit(prefix) ? "1" : "0");
    }
    for (const [prefix, photo] of state.loadedPhotos.entries()) {
      if (!state.files.has(prefix) && photo.dirty) {
        const transferSource = transferableSlotSource(prefix, photo);
        const token = transferablePhotoToken(photo, prefix);
        if (token) {
          data.set(`existing_slot_${prefix}`, token);
          data.set(`slot_fit_${prefix}`, isSlotFit(prefix) ? "1" : "0");
          changedPrefixes.add(prefix);
        } else if (transferSource === "ftp" && photo.ftp_filename) {
          data.set(`existing_ftp_slot_${prefix}`, photo.ftp_filename);
          data.set(
            `existing_ftp_ean_${prefix}`,
            photo.ean || state.loadedEntryOriginal?.ean || productForm.elements.ean.value
          );
          data.set(`slot_fit_${prefix}`, isSlotFit(prefix) ? "1" : "0");
          changedPrefixes.add(prefix);
        } else if (photo.dirty) {
          throw new Error(`Slot ${prefix} nie ma lokalnego ani FTP zrodla do przeniesienia.`);
        }
      }
    }
    for (const [prefix, item] of state.deletedSlots.entries()) {
      data.set(`delete_slot_${prefix}`, "1");
      if (item.token) data.set(`delete_local_slot_${prefix}`, item.token);
      if (item.ftp_filename) data.set(`delete_ftp_slot_${prefix}`, item.ftp_filename);
      if (item.sql) data.set(`delete_sql_slot_${prefix}`, "1");
    }
    startProcessStatusTicker(updateMode ? "Aktualizacja" : "Synchronizacja", changedPrefixes);
    const payload = await requestJson("/api/process/background", { method: "POST", body: data });
    const job = payload.job || {};
    stopProcessStatusTicker("Backend przyjal zadanie w tle.");
    trackProcessJob(job);
    showQueuedProcess(job);
    resetCurrentDraft({
      clearOutput: false,
      status: "Zadanie przyjete w tle. Mozesz uzupelniac kolejny wpis.",
    });
    setBusy(false, "Zadanie przyjete w tle. Mozesz uzupelniac kolejny wpis.");
  } catch (error) {
    handleProductSubmitError(error);
  }
}

productForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (pendingSimilarCandidatePrefixes().length) {
    openSimilarDecisionModal();
    return;
  }
  return submitProductForm().catch(handleProductSubmitError);
});

function resetCurrentDraft({ clearOutput = true, status = "" } = {}) {
  state.photoLoadRequestId += 1;
  productForm.reset();
  productForm.elements.product_id.value = "";
  for (const prefix of Array.from(state.filePreviewUrls.keys())) {
    revokeFilePreviewUrl(prefix);
  }
  state.files.clear();
  state.loadedPhotos.clear();
  state.slotFits.clear();
  state.deletedSlots.clear();
  state.slotSources.clear();
  state.similarCandidates.clear();
  state.dismissedSimilarSlots.clear();
  cancelSimilarFileLookup();
  state.userSelectedSlotSources.clear();
  state.photoSourceStatus.clear();
  state.ftpPreviewLoading.clear();
  state.ftpPreviewBackgroundLoading.clear();
  state.photoSourcesLoaded.clear();
  state.backgroundFtpLookupKey = "";
  state.backgroundFtpLookupRequestId += 1;
  window.clearTimeout(state.pimcoreLookupTimer);
  state.pimcoreLookupRequestId += 1;
  state.pimcoreLastCheckedEan = "";
  state.pimcoreMissingEan = "";
  state.pimcoreCreateSchema = [];
  state.pimcoreExistingObject = null;
  if (pimcoreEditButton) {
    pimcoreEditButton.disabled = true;
    pimcoreEditButton.title = "";
  }
  pimcoreMissingModal?.classList.remove("active");
  pimcoreCreateModal?.classList.remove("active");
  closePimcoreEditModal();
  window.clearTimeout(state.backgroundFtpLookupTimer);
  window.clearTimeout(state.backgroundFtpPreviewTimer);
  state.loadedEntryOriginal = null;
  state.lastAutoSearchKey = "";
  applyProductFieldSettings();
  renderSlots();
  renderEntrySelect();
  updateFieldWarnings();
  if (clearOutput) {
    clearResult();
  }
  formStatus.textContent = status;
}

clearButton.addEventListener("click", () => {
  resetCurrentDraft();
});

findByEanButton.addEventListener("click", () => {
  searchByEan().catch((error) => {
    formStatus.textContent = error.message;
  });
});

findProductButton.addEventListener("click", () => {
  searchByProduct().catch((error) => {
    formStatus.textContent = error.message;
  });
});

scanWebImagesButton?.addEventListener("click", () => {
  scanWebImages().catch((error) => {
    formStatus.textContent = error.message;
  });
});

webImagesButton?.addEventListener("click", () => {
  openWebImagesModal();
  renderWebImagesPicker();
});

webImageUrl?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  scanWebImages().catch((error) => {
    formStatus.textContent = error.message;
  });
});

for (const input of [
  webImageMinWidth,
  webImageMinHeight,
  webImageMinKb,
  webImageUrlFilter,
  webImageHideThumbnails,
]) {
  input?.addEventListener("input", renderWebImagesPicker);
  input?.addEventListener("change", renderWebImagesPicker);
}

if (webImageScanMode) {
  webImageScanMode.value = state.webImageScanMode;
}

webImageScanMode?.addEventListener("change", () => {
  state.webImageScanMode = webImageScanMode.value || "links";
  localStorage.setItem("picsyncra-web-image-scan-mode", state.webImageScanMode);
  renderWebImagesPicker();
});

browserExtensionHelpButton?.addEventListener("click", () => {
  if (!browserExtensionHelp) return;
  browserExtensionHelp.hidden = !browserExtensionHelp.hidden;
});

browserExtensionDownload?.addEventListener("click", () => {
  downloadBrowserExtension().catch((error) => {
    formStatus.textContent = error.message;
  });
});

browserExtensionReceiveButton?.addEventListener("click", () => {
  receiveBrowserExtensionImages().catch((error) => {
    formStatus.textContent = error.message;
  });
});

webImagesSelectVisibleButton?.addEventListener("click", () => {
  for (const entry of visibleWebImageEntries()) {
    state.webImageSelected.add(entry.index);
    queueWebImageCache(entry.image, "web", { render: false });
  }
  renderWebImagesPicker();
});

webImagesClearSelectionButton?.addEventListener("click", () => {
  state.webImageSelected.clear();
  renderWebImagesPicker();
});

webImagesClearDataButton?.addEventListener("click", () => {
  clearLoadedWebImages();
});

webImagesAddButton?.addEventListener("click", () => {
  addSelectedWebImagesToSlots().catch((error) => {
    formStatus.textContent = error.message;
  });
});

listAddForm.addEventListener("submit", (event) => {
  addListValue(event).catch((error) => {
    listStatus.textContent = error.message;
  });
});

listAddInput.addEventListener("input", () => {
  state.listFilter = listAddInput.value;
  renderListEditor();
  listAddInput.focus();
  const length = listAddInput.value.length;
  listAddInput.setSelectionRange(length, length);
});

logoutButton.addEventListener("click", async () => {
  if (!confirmPageExit()) {
    return;
  }
  state.navigationGuardBypass = true;
  await fetch("/api/logout", {
    method: "POST",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      [CLIENT_ID_HEADER]: activePresenceClientId(),
      ...(state.csrfToken ? { [CSRF_HEADER]: state.csrfToken } : {}),
    },
  }).catch(() => {});
  window.location.href = "/";
});

const autocompleteControls = window.PicSyncra.setupAutocomplete({
  document,
  productForm,
  fieldNames: Object.keys(fieldListKey),
  localSuggestions,
  remoteSuggestions,
  captureRequest: autocompleteRequestSnapshot,
  uniqueValues,
  maxOptions: MAX_AUTOCOMPLETE_OPTIONS,
  setTimer: (callback, delay) => window.setTimeout(callback, delay),
  clearTimer: (timer) => window.clearTimeout(timer),
});
setupFieldChangeTracking();
setupPageExitGuards();
applyTheme();
renderResourceStatus();
loadBootstrap().catch(showError);
startBackgroundPollers();
pollBackendHealth().catch(() => {});
