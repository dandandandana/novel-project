"use strict";

const API_ROOT = "/api/v1";
const STORAGE_KEY = "novel-rag.workspace";
const POLL_INTERVAL_MS = 2500;
const EVENT_RETRY_MS = 1800;

const dom = {};
const workspace = {
  token: "",
  workspaceId: "",
  storageKey: STORAGE_KEY,
  tabId: "",
  previousTabId: "",
  localScope: null,
  localLoadedKey: "",
  localRecovery: null,
  localCopies: new Map(),
  localSaveFailed: false,
  pendingNewStory: null,
  pendingNewStoryKey: "",
  storyCreating: false,
  ready: false,
  stories: [],
  profiles: [],
  driverSelectionTouched: false,
  profileSelectionTouched: false,
  scopeSelectionTouched: false,
  outlineInputTouched: false,
  requestInputTouched: false,
  inputRestoreRunId: "",
  runSelectionInitialized: false,
  runId: "",
  sessionId: "",
  snapshot: null,
  lastEventSeq: 0,
  currentTurnId: "",
  turnPreview: "",
  draftBaseline: "",
  draftExpectedRevision: 0,
  draftDirty: false,
  coordinateDirty: false,
  runRequestInFlight: false,
  pendingRunRequest: null,
  snapshotRequestSeq: 0,
  snapshotInFlight: null,
  memoryBrowseGeneration: 0,
  memoryBrowse: null,
  terminalRunId: "",
  draftSaveInFlight: null,
  eventController: null,
  pendingAdoptionIds: new Map(),
  resourceReady: false,
  resourceScopeKey: "",
  resourceLoadSeq: 0,
  resourceLoadState: "idle",
  preferencesBaseline: "",
  preferencesExpectedRevision: null,
  preferencesDirty: false,
  preferencesSaving: false,
  preferencesDrafts: new Map(),
  documents: [],
  documentSelections: new Map(),
  documentDrafts: new Map(),
  documentDetailSeq: 0,
  activeDocumentId: "",
  activeDocumentType: "",
  documentBaseline: "",
  documentExpectedRevision: null,
  documentSourceRef: null,
  documentDirty: false,
  documentEditable: false,
  documentSaving: false,
  reviseBaseRef: null,
  harnessContextRunId: "",
  harnessContextRequestRunId: ""
};

/**
 * 依赖：HTML 中固定的界面 ID。
 * 输入：无。
 * 输出：无；将页面节点写入 dom。
 * 实现：逐个读取静态节点，避免重复查找并明确页面契约。
 */
function cacheDom() {
  const ids = [
    "runStatus", "runForm", "storySelect", "timelineSelect", "driverSelect", "profileSelect", "profileHelp",
    "outlineInput", "requestInput", "startButton", "feedbackButton", "cancelButton",
    "draftRevision", "errorBanner", "draftEditor", "draftEditState", "saveDraftButton",
    "adoptButton", "generatedDraftButton", "generatedDraftPanel", "generatedDraftMeta",
    "generatedDraftPreview", "volumeInput", "chapterInput", "sceneInput", "liveTurnLabel",
    "livePreview", "saveReceivedButton", "savedPartialPanel", "savedPartialPreview",
    "sourceList", "coverageList", "gapList", "toolLog", "memoryCards", "memorySurface", "memoryStatus",
    "refreshMemoryButton", "moreMemoryButton", "memoryQueryInput", "memoryQueryForm", "preferencesEditor",
    "preferencesStatus", "savePreferencesButton", "reloadDocumentsButton", "documentSelect", "resourcesSurface",
    "resourcesPanel",
    "documentStatus", "documentEditorLabel", "documentEditor", "documentPreview",
    "saveDocumentButton", "reviseDocumentButton", "reviseDocumentStatus", "harnessPanel",
    "harnessContextStatus", "harnessContextButton", "harnessContextOutput", "harnessCommand",
    "localSaveStatus", "localRecoveryPanel", "localRecoveryText", "localRecoveryMessage", "restoreLocalDraftButton",
    "localArchivePanel", "localCopySelect", "localCopyText", "setupHint", "setupMessage", "setupButton",
    "useHarnessButton", "setupDialog", "closeSetupButton", "refreshProfilesButton", "setupStatus",
    "newStoryButton", "newStoryDialog", "newStoryTitleInput", "createStoryForm", "createStoryButton",
    "closeNewStoryButton", "newStoryStatus", "writingOptions"
  ];
  for (const id of ids) dom[id] = document.getElementById(id);
}

/**
 * 依赖：dom.runStatus 与可访问的状态区。
 * 输入：状态文案和可选状态类别。
 * 输出：无。
 * 实现：只写入文本和 data-state，不解析服务端内容。
 */
function setRunStatus(message, state = "idle") {
  dom.runStatus.textContent = message;
  dom.runStatus.dataset.state = state;
}

/**
 * 依赖：dom.errorBanner。
 * 输入：错误文本；空值表示清除提示。
 * 输出：无。
 * 实现：用 textContent 呈现错误，保留所有输入与正文编辑。
 */
function showError(message) {
  const text = message ? String(message) : "";
  dom.errorBanner.textContent = text;
  dom.errorBanner.hidden = text.length === 0;
}

/**
 * 依赖：localStorage 与 STORAGE_KEY。
 * 输入：无。
 * 输出：只含 run_id、driver 与作品/时间线/profile 选择的对象。
 * 实现：读取损坏或不可用的存储时返回空选择，不读取或保存 token。
 */
function readStoredWorkspace() {
  try {
    const value = JSON.parse(localStorage.getItem(workspace.storageKey) || "{}");
    return {
      runId: typeof value.run_id === "string" ? value.run_id : "",
      storyId: typeof value.story_id === "string" ? value.story_id : "",
      timelineId: typeof value.timeline_id === "string" ? value.timeline_id : "",
      profileName: typeof value.profile_name === "string" ? value.profile_name : "",
      driver: value.driver === "harness" ? "harness" : "builtin"
    };
  } catch {
    return { runId: "", storyId: "", timelineId: "", profileName: "", driver: "builtin" };
  }
}

/**
 * 依赖：localStorage、当前选择节点和 STORAGE_KEY。
 * 输入：无。
 * 输出：无。
 * 实现：仅持久化当前 run_id、driver 与同一 scope 选择；存储故障不影响页面操作。
 */
function writeStoredWorkspace() {
  const value = {
    run_id: workspace.runId,
    story_id: dom.storySelect.value,
    timeline_id: dom.timelineSelect.value,
    profile_name: dom.profileSelect.value,
    driver: selectedDriver()
  };
  try {
    localStorage.setItem(workspace.storageKey, JSON.stringify(value));
  } catch {
    setRunStatus("浏览器未保存本地恢复位置", "warning");
  }
}

/** 依赖：sessionStorage/crypto。输入：无。输出：本页写者身份。实现：每document新nonce，旧身份仅用于恢复，opener复制也不共写。 */
function initializeLocalWriter() {
  workspace.tabId = crypto.randomUUID();
  try {
    workspace.previousTabId = sessionStorage.getItem("novel-rag.input-writer") || "";
    sessionStorage.setItem("novel-rag.input-writer", workspace.tabId);
  } catch { workspace.previousTabId = ""; }
}

/** 依赖：原run binding/选择节点。输入：无。输出：书线或null。实现：正文优先属于固定run；未开任务使用当前作品线。 */
function localInputScope() {
  const scope = workspace.snapshot && workspace.snapshot.binding && workspace.snapshot.binding.scope;
  const selected = scope || workspace.localScope || selectedResourceScope();
  return { story_id: selected.story_id || selected.storyId, timeline_id: selected.timeline_id || selected.timelineId };
}

/** 依赖：bootstrap身份/书线。输入：scope和可选run。输出：版本化本机键前缀。实现：编码归属，末尾写者nonce分离并发副本。 */
function localInputPrefix(scope, runId) {
  if (!workspace.workspaceId || !scope || !scope.story_id || !scope.timeline_id) return "";
  const prefix = `novel-rag.inputs.v1:${encodeURIComponent(workspace.workspaceId)}:${encodeURIComponent(JSON.stringify([scope.story_id, scope.timeline_id]))}:`;
  return runId === undefined ? prefix : `${prefix}${encodeURIComponent(runId || "new")}:`;
}

/** 依赖：localStorage/版本白名单。输入：scope和可选run。输出：本书合法副本列表。实现：坏记录保留不执行；只读取作者字段，不接受token/HTML或其他库。 */
function readLocalInputs(scope, runId) {
  const prefix = localInputPrefix(scope, runId);
  if (!prefix) return [];
  const copies = [];
  let damaged = false;
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key || !key.startsWith(prefix)) continue;
      let value;
      try { value = JSON.parse(localStorage.getItem(key)); } catch { damaged = true; continue; }
      if (!value || value.version !== 1 || typeof value.run_id !== "string"
          || !value.scope || value.scope.story_id !== scope.story_id || value.scope.timeline_id !== scope.timeline_id
          || typeof value.text !== "string" || typeof value.baseline !== "string"
          || typeof value.outline !== "string" || typeof value.request !== "string"
          || !Number.isInteger(value.baseline_revision) || value.baseline_revision < 0) { damaged = true; continue; }
      copies.push({ ...value, key });
    }
  } catch {
    dom.localSaveStatus.textContent = "浏览器临时保存不可用，请保存到工作区或复制正文。";
  }
  if (damaged) dom.localSaveStatus.textContent = "有本机副本损坏或版本不兼容，原记录已保留；请保存当前输入。";
  return copies.sort((left, right) => (Number(right.saved_at) || 0) - (Number(left.saved_at) || 0));
}

/** 依赖：唯一编辑state/localStorage。输入：无。输出：保存成功boolean。实现：保存作者文本/原CAS/待确认envelope，每页独立键；失败保留DOM和旧副本。 */
function persistLocalInputs() {
  const scope = localInputScope();
  const prefix = localInputPrefix(scope, workspace.runId);
  if (!prefix) return false;
  const value = {
    version: 1, scope: { story_id: scope.story_id, timeline_id: scope.timeline_id }, run_id: workspace.runId,
    writer: workspace.tabId, saved_at: Date.now(), outline: dom.outlineInput.value, request: dom.requestInput.value,
    task_kind: selectedTaskKind(), driver: selectedDriver(), profile_name: dom.profileSelect.value,
    text: dom.draftEditor.value, baseline: workspace.draftBaseline, baseline_revision: workspace.draftExpectedRevision,
    dirty: workspace.draftDirty, outline_touched: workspace.outlineInputTouched, request_touched: workspace.requestInputTouched,
    coordinates: [dom.volumeInput.value, dom.chapterInput.value, dom.sceneInput.value], coordinate_dirty: workspace.coordinateDirty,
    pending_run: workspace.pendingRunRequest, pending_adoption: workspace.pendingAdoptionIds.get(workspace.runId) || null,
    revise_base_ref: workspace.reviseBaseRef, recovery: workspace.localRecovery
  };
  try {
    localStorage.setItem(prefix + workspace.tabId, JSON.stringify(value));
    localStorage.setItem(workspace.storageKey + ".scope." + encodeURIComponent(JSON.stringify([scope.story_id, scope.timeline_id])), JSON.stringify({ run_id: workspace.runId }));
    workspace.localSaveFailed = false;
    dom.localSaveStatus.textContent = "输入已临时保存在本机浏览器；正式草稿仍需点击保存。";
    return true;
  } catch {
    workspace.localSaveFailed = true;
    dom.localSaveStatus.textContent = "本机临时保存失败，请保存到工作区或复制输入后再离开。";
    return false;
  }
}

/** 依赖：现有控件/服务器基线/本机副本。输入：无。输出：恢复匹配输入或可查看的冲突候选。实现：仅首次读取；已键入内容优先，不发任何写请求。 */
function restoreLocalInputs() {
  const scope = localInputScope();
  const identity = localInputPrefix(scope, workspace.runId);
  if (!identity || workspace.localLoadedKey === identity) return;
  workspace.localLoadedKey = identity;
  const copies = readLocalInputs(scope, workspace.runId);
  const copy = copies.find((item) => item.writer === workspace.tabId)
    || copies.find((item) => item.writer === workspace.previousTabId) || copies[0];
  if (!copy) { renderLocalArchive(); return; }
  if (!workspace.outlineInputTouched) {
    dom.outlineInput.value = copy.outline;
    workspace.outlineInputTouched = Boolean(copy.outline_touched);
  }
  if (!workspace.requestInputTouched) {
    dom.requestInput.value = copy.request;
    workspace.requestInputTouched = Boolean(copy.request_touched);
  }
  if (["write", "revise", "discuss"].includes(copy.task_kind)) {
    document.querySelector(`input[name="task_kind"][value="${copy.task_kind}"]`).checked = true;
  }
  if (copy.revise_base_ref && typeof copy.revise_base_ref === "object") workspace.reviseBaseRef = copy.revise_base_ref;
  if (!workspace.driverSelectionTouched && !workspace.snapshot && ["builtin", "harness"].includes(copy.driver)) dom.driverSelect.value = copy.driver;
  if (!workspace.profileSelectionTouched && workspace.profiles.some((profile) => profile.name === copy.profile_name)) dom.profileSelect.value = copy.profile_name;
  updateDriverControls();
  if (copy.pending_run && ["start", "feedback"].includes(copy.pending_run.kind)
      && typeof copy.pending_run.requestId === "string" && copy.pending_run.body
      && typeof copy.pending_run.path === "string"
      && /^\/runs$|^\/sessions\/[^/]+\/feedback$/.test(copy.pending_run.path)) {
    workspace.pendingRunRequest = copy.pending_run;
    showError("找到上次待确认的创作请求。点击原操作会使用原编号与原输入确认结果。");
  }
  if (copy.pending_adoption && typeof copy.pending_adoption.operation_id === "string") {
    workspace.pendingAdoptionIds.set(workspace.runId, copy.pending_adoption);
    showError("找到上次待确认的采用请求。再次采用会确认原版本与原章节，当前新改动不会发送。");
  }
  if (Array.isArray(copy.coordinates) && copy.coordinates.length === 3 && !workspace.coordinateDirty) {
    [dom.volumeInput, dom.chapterInput, dom.sceneInput].forEach((field, index) => { field.value = String(copy.coordinates[index] ?? ""); });
    workspace.coordinateDirty = Boolean(copy.coordinate_dirty);
  }
  const candidate = copy.recovery && typeof copy.recovery.text === "string" ? copy.recovery : copy;
  if (candidate.dirty || candidate.text !== candidate.baseline) {
    if (!workspace.draftDirty && candidate.baseline_revision === workspace.draftExpectedRevision
        && candidate.baseline === workspace.draftBaseline && !copy.recovery) {
      dom.draftEditor.value = candidate.text;
      workspace.draftDirty = candidate.text !== workspace.draftBaseline;
      dom.draftEditState.textContent = "已恢复本机未保存的正文修改。";
    } else {
      workspace.localRecovery = { text: candidate.text, baseline: candidate.baseline, baseline_revision: candidate.baseline_revision, dirty: true };
      dom.localRecoveryText.value = candidate.text;
      dom.localRecoveryPanel.hidden = false;
    }
  }
  dom.localSaveStatus.textContent = "已找到本机临时输入；恢复不会自动保存或开始创作。";
  renderLocalArchive();
}

/** 依赖：恢复候选/当前服务器基线。输入：作者点击。输出：候选进入dirty编辑器。实现：明确选择后绑定当前revision；未来快照仍不自动换基线。 */
function restoreLocalDraft() {
  if (!workspace.localRecovery) return;
  workspace.draftBaseline = workspace.snapshot && typeof workspace.snapshot.draft_text === "string" ? workspace.snapshot.draft_text : "";
  workspace.draftExpectedRevision = workspace.snapshot && Number.isInteger(workspace.snapshot.draft_revision) ? workspace.snapshot.draft_revision : 0;
  dom.draftEditor.value = workspace.localRecovery.text;
  workspace.localRecovery = null;
  dom.localRecoveryPanel.hidden = true;
  onDraftInput();
  dom.draftEditor.focus();
}

/** 依赖：本书本机记录/原生select。输入：无。输出：可查看复制的历史输入。实现：只列当前scope，旧run/未开任务副本仍可回读，不自动转成当前稿。 */
function renderLocalArchive() {
  const copies = readLocalInputs(localInputScope());
  workspace.localCopies = new Map(copies.map((copy) => [copy.key, copy]));
  fillSelect(dom.localCopySelect, copies.map((copy) => ({ key: copy.key,
    label: `${new Date(copy.saved_at).toLocaleString()} · ${copy.run_id ? "任务草稿" : "未开始的输入"} · ${copy.outline.slice(0, 16)}`
  })), "key", "label", "暂无本机副本", dom.localCopySelect.value);
  showLocalArchiveCopy();
}

/** 依赖：本机副本选择/只读textarea。输入：选择事件。输出：作者可复制的原始输入。实现：仅写value，不执行内容或更改运行/CAS。 */
function showLocalArchiveCopy() {
  const copy = workspace.localCopies.get(dom.localCopySelect.value);
  dom.localCopyText.value = copy ? `大纲\n${copy.outline}\n\n本轮要求\n${copy.request}\n\n正文\n${copy.recovery?.text ?? copy.text}` : "";
}

/** 依赖：本机保存/编辑状态。输入：beforeunload事件。输出：必要时浏览器离开提示。实现：刷新不提交副作用；所有尚未工作区保存的输入保留离开保护。 */
function protectPageExit(event) {
  persistLocalInputs();
  const submitted = workspace.snapshot?.request_snapshot;
  const unsentInputs = submitted
    ? dom.outlineInput.value !== (submitted.outline || "") || dom.requestInput.value !== (submitted.request || "")
    : Boolean(dom.outlineInput.value || dom.requestInput.value);
  if (workspace.draftDirty || unsentInputs
      || workspace.preferencesDirty || workspace.documentDirty || workspace.pendingRunRequest
      || workspace.pendingAdoptionIds.size || workspace.storyCreating || workspace.pendingNewStory) {
    event.preventDefault();
    event.returnValue = "";
  }
}

/**
 * 依赖：fetch、API_ROOT 与 bootstrap 返回的内存 token。
 * 输入：API 路径和可选 fetch 参数。
 * 输出：解析后的 JSON；HTTP 失败额外携带状态码，网络失败保留可辨别的 Error。
 * 实现：除 token 引导 bootstrap 外，每个请求都发送 X-Workspace-Token。
 */
async function apiFetch(path, options = {}, bootstrap = false) {
  const headers = new Headers(options.headers || {});
  if (!bootstrap) headers.set("X-Workspace-Token", workspace.token);
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    cache: "no-store",
    ...options,
    headers
  });
  const raw = await response.text();
  let payload = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = { detail: raw };
    }
  }
  if (!response.ok) {
    let message = "请求失败，请稍后重试。";
    if (payload && typeof payload.detail === "string") message = payload.detail;
    else if (payload && typeof payload.message === "string") message = payload.message;
    else if (payload && payload.error && typeof payload.error.message === "string") message = payload.error.message;
    const error = new Error(message);
    error.httpStatus = response.status;
    error.code = payload?.error?.code;
    throw error;
  }
  return payload;
}

/**
 * 依赖：select 节点及其 ownerDocument。
 * 输入：选择节点、选项数组、value 字段名、label 字段名、空提示和目标值。
 * 输出：无。
 * 实现：用 createElement 与 textContent 构造选项，不将资料当作 HTML。
 */
function fillSelect(select, items, valueKey, labelKey, emptyLabel, selectedValue) {
  select.replaceChildren();
  if (!items.length) {
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = emptyLabel;
    select.append(emptyOption);
    select.disabled = true;
    return;
  }
  for (const item of items) {
    const option = document.createElement("option");
    option.value = String(item[valueKey] ?? "");
    option.textContent = String(item[labelKey] ?? item[valueKey] ?? "");
    select.append(option);
  }
  select.disabled = false;
  for (const item of items) {
    if (String(item[valueKey] ?? "") === selectedValue) {
      select.value = selectedValue;
      break;
    }
  }
}

/**
 * 依赖：workspace.stories、作品选择框和 timelineSelect。
 * 输入：期望恢复的 timeline_id，可省略。
 * 输出：无。
 * 实现：只展示所选作品拥有的时间线，并优先恢复有效选择。
 */
function updateTimelineOptions(preferredTimelineId = "") {
  let story = null;
  for (const item of workspace.stories) {
    if (item.story_id === dom.storySelect.value) {
      story = item;
      break;
    }
  }
  const timelines = story && Array.isArray(story.timelines) ? story.timelines : [];
  fillSelect(dom.timelineSelect, timelines, "timeline_id", "name", "此作品没有可选时间线", preferredTimelineId);
}

/**
 * 依赖：bootstrap 数据、localStorage 选择和所有输入节点。
 * 输入：存储的恢复位置。
 * 输出：无。
 * 实现：填充作品、时间线和 profile，并只在恢复到相同 scope 时恢复 driver。
 */
function populateWorkspace(remembered) {
  workspace.stories = Array.isArray(workspace.bootstrap.stories) ? workspace.bootstrap.stories : [];
  workspace.profiles = Array.isArray(workspace.bootstrap.profiles) ? workspace.bootstrap.profiles : [];
  fillSelect(dom.storySelect, workspace.stories, "story_id", "title", "没有可用作品", remembered.storyId);
  updateTimelineOptions(remembered.timelineId);
  fillSelect(dom.profileSelect, workspace.profiles, "name", "name", "没有可用模型配置", remembered.profileName);
  const sameStoredScope = dom.storySelect.value === remembered.storyId && dom.timelineSelect.value === remembered.timelineId;
  if (!workspace.driverSelectionTouched) {
    dom.driverSelect.value = sameStoredScope && remembered.driver === "harness" ? "harness" : "builtin";
  }
  updateDriverControls();
  updateActionAvailability();
  writeStoredWorkspace();
}

/**
 * 依赖：driverSelect、profileSelect、profileHelp 与当前 bootstrap 选择。
 * 输入：无。
 * 输出：无；同步 profile 需求、提示和当前 ready 条件。
 * 实现：只在 builtin 模式要求 profile，harness 模式保留选择但禁用内置配置。
 */
function updateDriverControls() {
  const usesBuiltin = selectedDriver() === "builtin";
  dom.profileSelect.required = usesBuiltin;
  dom.profileSelect.disabled = !usesBuiltin || workspace.profiles.length === 0;
  dom.profileHelp.textContent = usesBuiltin
    ? "网页内置模型会使用所选配置。"
    : "外部写作工具使用自己的模型；本轮不会调用网页内置模型。";
  dom.startButton.textContent = usesBuiltin ? "开始创作" : "准备交接";
  workspace.ready = Boolean(
    workspace.token && dom.storySelect.value && dom.timelineSelect.value
    && (!usesBuiltin || dom.profileSelect.value)
  );
  dom.setupHint.hidden = Boolean(dom.storySelect.value && (!usesBuiltin || workspace.profiles.length));
  dom.setupMessage.textContent = !dom.storySelect.value ? "先新建一部作品，再粘贴大纲。"
    : workspace.bootstrap?.model_configuration_error?.message || "尚未设置内置模型。可以在本机设置，或使用你自己的写作工具。";
}

/**
 * 依赖：当前 run 快照、bootstrap完成状态、请求锁与动作按钮。
 * 输入：无。
 * 输出：无。
 * 实现：同步请求占用情况、停止按钮与草稿/已接收文本动作的可用状态。
 */
function updateActionAvailability() {
  const status = workspace.snapshot ? workspace.snapshot.status : "";
  const running = status === "running" || status === "queued";
  const hasRun = Boolean(workspace.runId && workspace.snapshot);
  const pendingKind = workspace.pendingRunRequest ? workspace.pendingRunRequest.kind : "";
  dom.startButton.disabled = !workspace.ready || running || workspace.runRequestInFlight || pendingKind === "feedback";
  dom.feedbackButton.disabled = !hasRun || running || workspace.runRequestInFlight || pendingKind === "start";
  const canCancel = status === "running"
    || (status === "prepared" && workspace.snapshot && workspace.snapshot.driver === "harness");
  dom.cancelButton.disabled = !hasRun || !canCancel || Boolean(workspace.snapshot.cancel_requested);
  dom.cancelButton.textContent = workspace.snapshot && workspace.snapshot.driver === "harness" ? "停止本地工具" : "停止本轮";
  dom.saveDraftButton.disabled = !hasRun || Boolean(workspace.draftSaveInFlight);
  dom.adoptButton.disabled = !hasRun || Boolean(workspace.draftSaveInFlight);
  const generatedRef = workspace.snapshot && workspace.snapshot.generated_draft_ref;
  const hasGeneratedDraft = Boolean(generatedRef && typeof workspace.snapshot.generated_draft_text === "string");
  dom.generatedDraftButton.hidden = !hasGeneratedDraft;
  dom.generatedDraftButton.disabled = !hasGeneratedDraft;
  const receivedText = workspace.snapshot && workspace.snapshot.received_text;
  const canSaveReceived = Boolean(
    hasRun && typeof receivedText === "string" && receivedText.length > 0
    && status !== "completed"
    && !(Number.isInteger(workspace.snapshot.author_revision) && workspace.snapshot.author_revision > 0)
  );
  dom.saveReceivedButton.hidden = !canSaveReceived;
  dom.saveReceivedButton.disabled = !canSaveReceived || Boolean(workspace.draftSaveInFlight);
  dom.storySelect.disabled = !workspace.stories.length || workspace.runRequestInFlight;
  dom.timelineSelect.disabled = !dom.timelineSelect.value || workspace.runRequestInFlight;
  dom.newStoryButton.disabled = !workspace.token || workspace.runRequestInFlight || workspace.storyCreating;
}

/**
 * 依赖：GET /api/v1/bootstrap 和本地只保存 scope/run_id 的位置。
 * 输入：无。
 * 输出：Promise<void>。
 * 实现：让 URL run 优先于本地恢复位置，先从快照恢复 scope/driver/正文，再按面板可见状态读取资料。
 */
async function startWorkspace() {
  const urlRunId = new URLSearchParams(window.location.search).get("run");
  try {
    workspace.bootstrap = await apiFetch("/bootstrap", {}, true);
    workspace.token = typeof workspace.bootstrap.token === "string" ? workspace.bootstrap.token : "";
    if (!workspace.token) throw new Error("工作区没有返回访问令牌。");
    if (typeof workspace.bootstrap.workspace_id !== "string" || !workspace.bootstrap.workspace_id) {
      throw new Error("工作区服务尚未加载新版，请重新启动本地工作区；当前输入仍在页面中。");
    }
    workspace.workspaceId = workspace.bootstrap.workspace_id;
    workspace.storageKey = `${STORAGE_KEY}.${workspace.workspaceId}`;
    const remembered = readStoredWorkspace();
    if (urlRunId) remembered.runId = urlRunId;
    workspace.runId = remembered.runId;
    populateWorkspace(remembered);
    workspace.localScope = selectedResourceScope();
    setRunStatus("已连接本地工作区", "ready");
    if (remembered.runId) {
      workspace.runId = remembered.runId;
      await refreshRunSnapshot(remembered.runId);
      beginRunObservation(remembered.runId);
    }
    restoreLocalInputs();
    try {
      const key = workspace.storageKey + ".new-story." + workspace.previousTabId;
      const pending = JSON.parse(localStorage.getItem(key) || "null");
      if (pending && typeof pending.story_id === "string" && typeof pending.title === "string") {
        workspace.pendingNewStory = pending;
        workspace.pendingNewStoryKey = key;
      }
    } catch { /* 损坏记录保留，创建表单仍可使用。 */ }
    workspace.resourceReady = true;
    void loadScopedResources();
    updateActionAvailability();
  } catch (error) {
    setRunStatus("无法连接本地工作区", "error");
    showError(error.message || "连接失败，请确认本地服务正在运行。");
    if (workspace.workspaceId) { restoreLocalInputs(); renderLocalArchive(); updateActionAvailability(); }
  }
}

/**
 * 依赖：作品、时间线、driver/profile 输入及 POST /runs。
 * 输入：表单提交事件。
 * 输出：Promise<void>。
 * 实现：发送明确的创作输入；成功后记录 run_id 并载入服务快照。
 */
async function onStartSubmit(event) {
  event.preventDefault();
  const taskKind = selectedTaskKind();
  const driver = selectedDriver();
  const body = {
    story_id: dom.storySelect.value,
    timeline_id: dom.timelineSelect.value,
    profile_name: driver === "builtin" ? dom.profileSelect.value : null,
    driver,
    task_kind: taskKind,
    outline: dom.outlineInput.value,
    request: dom.requestInput.value
  };
  if (taskKind === "revise" && workspace.reviseBaseRef) body.base_ref = workspace.reviseBaseRef;
  await sendRunRequest("start", "/runs", body, "无法开始本轮创作。");
}

/**
 * 依赖：crypto.randomUUID 与当前未确认的创作请求。
 * 输入：start 或 feedback 动作及其JSON正文。
 * 输出：本次请求编号和固定正文；网络结果未知时原样复用。
 * 实现：阻止不同动作抢占未确认操作；网络结果待确认时保留原编号供同页重试。
 */
function ensurePendingRunRequest(kind, body, path) {
  if (workspace.pendingRunRequest) {
    if (workspace.pendingRunRequest.kind !== kind) {
      throw new Error("上一次创作请求尚未确认，请先用原操作重试。");
    }
    return workspace.pendingRunRequest;
  }
  const pending = { kind, requestId: crypto.randomUUID(), body: { ...body }, path };
  workspace.pendingRunRequest = pending;
  return pending;
}

/**
 * 依赖：apiFetch、request_id幂等接口与activateRun。
 * 输入：动作类型、POST路径、JSON正文和失败提示。
 * 输出：Promise<void>；确认响应后切换到新run。
 * 实现：同步占用in-flight锁；网络结果不明时保留编号及原正文供安全重试。
 */
async function sendRunRequest(kind, path, body, failureMessage) {
  if (workspace.runRequestInFlight) return;
  showError("");
  let pending;
  try {
    pending = ensurePendingRunRequest(kind, body, path);
    if (!persistLocalInputs()) throw new Error("临时保存不可用。请先复制输入；本轮尚未发送，可以恢复本机保存后重试。");
  } catch (error) {
    showError(error.message || failureMessage);
    setRunStatus("上一次请求待确认", "warning");
    return;
  }

  if (JSON.stringify(pending.body) !== JSON.stringify(body)) {
    showError("上一次请求结果尚未确认；本次会用同一编号重试原输入，当前新改动不会发送。");
  }
  workspace.runRequestInFlight = true;
  updateActionAvailability();
  let responseConfirmed = false;
  try {
    const result = await apiFetch(pending.path, {
      method: "POST",
      body: JSON.stringify({ ...pending.body, request_id: pending.requestId })
    });
    if (!result || typeof result.run_id !== "string" || !result.run_id) {
      throw new Error("服务已响应，但没有返回运行编号；再次点击会复用本次请求编号。");
    }
    responseConfirmed = true;
    if (workspace.pendingRunRequest === pending) workspace.pendingRunRequest = null;
    if (kind === "start" && pending.body.base_ref === workspace.reviseBaseRef) workspace.reviseBaseRef = null;
    await activateRun(result.run_id, result.session_id);
  } catch (error) {
    const httpStatus = Number.isInteger(error.httpStatus) ? error.httpStatus : null;
    if (!responseConfirmed && httpStatus !== null && httpStatus < 500
        && workspace.pendingRunRequest === pending) {
      workspace.pendingRunRequest = null;
    }
    if (responseConfirmed) {
      showError("服务已确认本轮创建，但页面未能载入状态；刷新后可从本地恢复位置打开。");
      setRunStatus("本轮已创建，状态载入待恢复", "warning");
    } else if (httpStatus === null || httpStatus >= 500) {
      showError("连接结果尚不确定。再次点击同一操作会用相同编号和原输入重试。");
      setRunStatus("请求结果待确认", "warning");
    } else {
      showError(error.message || failureMessage);
      setRunStatus("服务已返回请求错误", "error");
    }
  } finally {
    workspace.runRequestInFlight = false;
    persistLocalInputs();
    updateActionAvailability();
  }
}

/**
 * 依赖：task_kind 单选项。
 * 输入：无。
 * 输出：write、revise 或 discuss。
 * 实现：返回当前选中的明确任务类型，缺省回退为 write。
 */
function selectedTaskKind() {
  const selected = document.querySelector('input[name="task_kind"]:checked');
  return selected ? selected.value : "write";
}

/**
 * 依赖：driverSelect 的受控选项。
 * 输入：无。
 * 输出：builtin 或 harness。
 * 实现：只接受外部写作工具这一显式选项，其它值安全回退到网页内置模型。
 */
function selectedDriver() {
  return dom.driverSelect && dom.driverSelect.value === "harness" ? "harness" : "builtin";
}

/**
 * 依赖：当前 run snapshot、session_id 和 POST /sessions/{id}/feedback。
 * 输入：无。
 * 输出：Promise<void>。
 * 实现：用当前 draft_ref/checkpoint_id 作为父稿锚点，并发送当前 driver 与对应 profile。
 */
async function submitFeedback() {
  const snapshot = workspace.snapshot;
  const draftRef = snapshot && snapshot.draft_ref;
  const sessionId = workspace.sessionId || (snapshot && snapshot.session_id);
  if (!workspace.runId || !sessionId || !draftRef) {
    showError("当前运行尚未提供父稿检查点；正文和输入仍已保留。");
    return;
  }
  const checkpointId = draftRef.checkpoint_id;
  const driver = selectedDriver();
  await sendRunRequest(
    "feedback",
    `/sessions/${encodeURIComponent(sessionId)}/feedback`,
    {
      base_run_id: workspace.runId,
      task_kind: selectedTaskKind(),
      driver,
      profile_name: driver === "builtin" ? dom.profileSelect.value : null,
      request: dom.requestInput.value,
      base_ref: draftRef,
      selected_parent_checkpoint: checkpointId
    },
    "无法从当前父稿继续。"
  );
}

/**
 * 依赖：草稿live PUT、编辑器基线、运行快照。
 * 输入：是否另存已收到的部分文本。
 * 输出：提交回执；切换运行时返回null；写入失败时抛出服务错误。
 * 实现：沿用各自CAS，以实际持久全文更新基线，另合并可用的运行快照。
 */
async function persistDraft(partial = false) {
  const runId = workspace.runId;
  const snapshot = workspace.snapshot;
  if (!runId || !snapshot) throw new Error("当前没有可保存的草稿。");
  if (workspace.draftSaveInFlight) return null;
  const editorText = dom.draftEditor.value;
  const preserveExistingEdit = partial && workspace.draftDirty;
  const text = partial ? snapshot.received_text : editorText;
  const expectedRevision = partial ? snapshot.draft_revision ?? 0 : workspace.draftExpectedRevision;
  const request = {};
  workspace.draftSaveInFlight = request;
  updateActionAvailability();
  try {
    const result = await apiFetch(`/runs/${encodeURIComponent(runId)}/draft?view=live`, {
      method: "PUT",
      body: JSON.stringify({ expected_revision: expectedRevision, text })
    });
    if (workspace.draftSaveInFlight !== request) return null;
    const { saved_draft_ref: ref, saved_draft_revision: revision, saved_draft_text: savedText } = result || {};
    if (result?.run_id !== runId || !Number.isInteger(revision) || ref?.draft_revision !== revision
        || typeof savedText !== "string") {
      throw new Error("服务未返回完整草稿回执，请确认当前修订。");
    }
    const preserveEditor = preserveExistingEdit || dom.draftEditor.value !== editorText;
    if (result.snapshot_view === "live") applySnapshot(result, runId);
    const current = workspace.snapshot;
    if (!Number.isInteger(current.draft_revision) || current.draft_revision <= revision) {
      Object.assign(current, { draft_ref: ref, draft_revision: revision, draft_text: savedText, author_revision: revision });
    }
    const updated = !preserveEditor && current.draft_revision > revision && typeof current.draft_text === "string";
    workspace.draftBaseline = updated ? current.draft_text : savedText;
    workspace.draftExpectedRevision = updated ? current.draft_revision : revision;
    if (!preserveEditor) dom.draftEditor.value = workspace.draftBaseline;
    workspace.draftDirty = preserveEditor && dom.draftEditor.value !== workspace.draftBaseline;
    dom.draftRevision.textContent = `草稿修订 ${current.draft_revision}`;
    invalidateMemoryBrowse(current);

    if (partial) {
      dom.savedPartialPreview.textContent = workspace.draftDirty ? savedText : "";
      dom.savedPartialPanel.hidden = !workspace.draftDirty;
      if (workspace.draftDirty) dom.liveTurnLabel.textContent = "已另存为部分草稿；编辑器内容保持不变";
    }
    const savedMessage = partial ? "部分草稿已保存" : "草稿已保存";
    const editingMessage = workspace.draftDirty ? "，编辑器仍有未保存的修改" : "";
    const readMessage = result.snapshot_read?.status === "unavailable" ? "。运行状态暂时无法读取" : "";
    dom.draftEditState.textContent = `${savedMessage} · 修订 ${revision}${editingMessage}${readMessage}。`;
    persistLocalInputs();
    return result;
  } catch (error) {
    if (workspace.draftSaveInFlight !== request) return null;
    throw error;
  } finally {
    if (workspace.draftSaveInFlight === request) {
      workspace.draftSaveInFlight = null;
      updateActionAvailability();
    }
  }
}

/**
 * 依赖：persistDraft 与保存按钮。
 * 输入：无。
 * 输出：Promise<void>。
 * 实现：报告保存结果；失败时保留输入、正文和 dirty 状态。
 */
async function saveDraft() {
  showError("");
  const runId = workspace.runId;
  try {
    if (!(await persistDraft())) return;
    setRunStatus("草稿已保存", "ready");
  } catch (error) {
    if (runId !== workspace.runId) return;
    showError(error.message || "保存草稿失败。");
    setRunStatus("草稿保存失败", "error");
  }
}

/**
 * 依赖：持久received_text与共同保存入口。
 * 输入：无；只使用当前快照中已保存的文本前缀。
 * 输出：Promise<void>；未完成文本成为明确保存的草稿修订。
 * 实现：阻止覆盖已保存作者版本，使用当前CAS保存部分稿并保留编辑器输入。
 */
async function saveReceivedTextAsDraft() {
  const runId = workspace.runId;
  const snapshot = workspace.snapshot;
  const text = snapshot && snapshot.received_text;
  if (!runId || !snapshot || typeof text !== "string" || !text) return;
  if (Number.isInteger(snapshot.author_revision) && snapshot.author_revision > 0) {
    showError("当前已有已保存的作者版本。请先确认保留该版本，再处理已接收文本。");
    return;
  }
  showError("");
  try {
    if (!(await persistDraft(true))) return;
    setRunStatus("已保存当前部分草稿", "ready");
  } catch (error) {
    if (workspace.runId !== runId) return;
    showError(error.message || "无法保存已接收的部分文本。");
    setRunStatus("部分草稿保存失败", "error");
  }
}

/**
 * 依赖：草稿保存接口、章节坐标、当前快照和 POST /runs/{id}/adopt。
 * 输入：无。
 * 输出：Promise<void>。
 * 实现：先保存未提交编辑；只为坐标匹配的旧目标发送CAS hash，operation_id保持到明确响应。
 */
async function adoptDraft() {
  showError("");
  const runId = workspace.runId;
  const original = workspace.pendingAdoptionIds.get(runId);
  const coordinates = {
    volume: Number(dom.volumeInput.value),
    chapter: Number(dom.chapterInput.value),
    scene: Number(dom.sceneInput.value)
  };
  const coordinateInputs = [dom.volumeInput, dom.chapterInput, dom.sceneInput];
  let coordinatesReady = true;
  for (const input of coordinateInputs) {
    if (input.value.trim() === "") coordinatesReady = false;
  }
  for (const value of Object.values(coordinates)) {
    if (!Number.isFinite(value)) coordinatesReady = false;
  }
  if (!original && !coordinatesReady) {
    showError("请填写卷、章、场三个数字后再采用正文。");
    return;
  }
  try {
    if (!original && workspace.draftDirty) {
      if (!(await persistDraft())) return;
      if (workspace.draftDirty) {
        showError("保存期间有新的正文修改，请核对当前编辑后再次采用。");
        return;
      }
    }
    if (runId !== workspace.runId) return;
    if (!workspace.snapshot || !Number.isInteger(workspace.snapshot.draft_revision)) {
      throw new Error("当前运行尚未提供可采用的草稿修订版本。");
    }
    const binding = workspace.snapshot.binding || {};
    const baseRef = binding.base_ref;
    const hasAdoptionTarget = Object.prototype.hasOwnProperty.call(workspace.snapshot, "adoption_target_coordinate");
    let expectedSourceHash = null;
    if (hasAdoptionTarget) {
      if (coordinatesMatch(coordinates, workspace.snapshot.adoption_target_coordinate)
          && typeof workspace.snapshot.adoption_target_source_hash === "string") {
        expectedSourceHash = workspace.snapshot.adoption_target_source_hash;
      }
    } else if (binding.task_kind === "revise" && baseRef && baseRef.kind === "document"
        && coordinatesMatch(coordinates, baseRef.coordinate)) {
      expectedSourceHash = baseRef.source_hash;
    }
    const envelope = original || {
      draft_revision: workspace.draftExpectedRevision, expected_source_hash: expectedSourceHash,
      coordinates, operation_id: crypto.randomUUID()
    };
    workspace.pendingAdoptionIds.set(runId, envelope);
    if (!persistLocalInputs()) throw new Error("采用编号未能临时保存，采用尚未发送；请复制输入或恢复本机保存后再试。");
    const result = await apiFetch(`/runs/${encodeURIComponent(runId)}/adopt`, {
      method: "POST",
      body: JSON.stringify(envelope)
    });
    if (runId !== workspace.runId) return;
    workspace.pendingAdoptionIds.delete(runId);
    persistLocalInputs();
    if (result && result.run_id) applySnapshot(result, runId);
    setRunStatus("采用请求已返回", "ready");
    if (result && result.adoption) {
      dom.draftEditState.textContent = "正式作品已返回采用结果。";
    }
  } catch (error) {
    if (runId !== workspace.runId) return;
    showError(error.message || "采用正文失败。再次尝试会复用同一个操作编号。");
    setRunStatus("采用结果待确认", "warning");
  }
}

/**
 * 依赖：采用坐标与快照中的目标坐标。
 * 输入：两个卷/章/场坐标对象。
 * 输出：三个整数坐标完全相同时返回true。
 * 实现：拒绝缺失或非整数坐标，防止把旧章节hash用于新场景目标。
 */
function coordinatesMatch(left, right) {
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false;
  return Number.isInteger(left.volume) && Number.isInteger(left.chapter) && Number.isInteger(left.scene)
    && Number.isInteger(right.volume) && Number.isInteger(right.chapter) && Number.isInteger(right.scene)
    && left.volume === right.volume && left.chapter === right.chapter && left.scene === right.scene;
}

/**
 * 依赖：POST /runs/{id}/cancel 与当前 run id。
 * 输入：无。
 * 输出：Promise<void>。
 * 实现：由共同快照入口显示停止进度并拒绝迟到回执。外部运行的按钮只请求停止本地工具。
 */
async function cancelRun() {
  if (!workspace.runId) return;
  const runId = workspace.runId;
  showError("");
  try {
    const result = await apiFetch(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
    applySnapshot(result, runId);
  } catch (error) {
    if (runId !== workspace.runId || workspace.terminalRunId === runId) return;
    showError(error.message || "无法停止本轮。");
  }
}

/**
 * 依赖：GET /runs/{id}、当前 run 状态和 applySnapshot。
 * 输入：run_id及可选的终态事件序号。
 * 输出：Promise<void>。
 * 实现：同run复用热读取。收到终态事件时使用已知序号替换更早的请求，直到确认终态快照。
 */
async function refreshRunSnapshot(runId, terminalSeq = 0) {
  if (!runId || runId !== workspace.runId || workspace.terminalRunId === runId) return;
  const previous = workspace.snapshotInFlight;
  if (previous?.runId === runId && previous.after >= terminalSeq) return previous.promise;
  const requestSeq = ++workspace.snapshotRequestSeq;
  const pending = { runId, after: workspace.lastEventSeq, promise: null };
  /** 依赖：apiFetch/当前run与读取序号。输入：闭包run及高水位。输出：刷新Promise。实现：读取live增量并在finally仅释放自身请求。 */
  async function readLiveSnapshot() {
    try {
      const result = await apiFetch(`/runs/${encodeURIComponent(runId)}?view=live&after=${pending.after}`);
      if (runId !== workspace.runId || requestSeq !== workspace.snapshotRequestSeq) return;
      applySnapshot(result, runId);
    } catch (error) {
      if (runId !== workspace.runId || requestSeq !== workspace.snapshotRequestSeq || workspace.terminalRunId === runId) return;
      showError(error.message || "读取运行状态失败。");
      setRunStatus("状态读取失败，保留当前编辑", "error");
    } finally {
      if (workspace.snapshotInFlight === pending) workspace.snapshotInFlight = null;
    }
  }
  workspace.snapshotInFlight = pending;
  pending.promise = readLiveSnapshot();
  return pending.promise;
}

/**
 * 依赖：服务 snapshot、正文 dirty 标记、事件列表和状态区。
 * 输入：运行 snapshot。
 * 输出：无。
 * 实现：以事件高水位拒绝倒退，合并live元数据；记忆由独立浏览绑定维护，仅未dirty时替换正文。
 */
function applySnapshot(snapshot, expectedRunId = workspace.runId) {
  if (!snapshot || typeof snapshot !== "object") return;
  if (!expectedRunId || expectedRunId !== workspace.runId || snapshot.run_id !== expectedRunId) return;
  const incomingEventSeq = Number.isInteger(snapshot.event_seq) ? snapshot.event_seq : Array.isArray(snapshot.events)
    ? snapshot.events.reduce((maximum, event) => Math.max(maximum, Number(event.seq) || 0), 0)
    : 0;
  if (incomingEventSeq < workspace.lastEventSeq) return;
  if (workspace.terminalRunId === expectedRunId && !isTerminalStatus(snapshot.status)) return;
  const currentRevision = workspace.snapshot && workspace.snapshot.draft_revision;
  if (Number.isInteger(currentRevision) && Number.isInteger(snapshot.draft_revision)
      && snapshot.draft_revision < currentRevision) return;
  workspace.snapshot = { ...(workspace.snapshot || {}), ...snapshot };
  workspace.sessionId = snapshot.session_id || workspace.sessionId;
  restoreRunSelection(snapshot);
  restoreAuthorInputs(snapshot);
  if (Array.isArray(snapshot.events)) {
    for (const event of snapshot.events) consumeEvent(event, false);
  }
  workspace.lastEventSeq = Math.max(workspace.lastEventSeq, incomingEventSeq);
  if (!workspace.draftDirty && !workspace.draftSaveInFlight && typeof snapshot.draft_text === "string") {
    workspace.draftBaseline = snapshot.draft_text;
    workspace.draftExpectedRevision = Number.isInteger(snapshot.draft_revision) ? snapshot.draft_revision : 0;
    dom.draftEditor.value = snapshot.draft_text;
  }
  restoreLocalInputs();
  if (Number.isInteger(snapshot.draft_revision)) {
    dom.draftRevision.textContent = `草稿修订 ${snapshot.draft_revision}`;
    if (!workspace.draftDirty && snapshot.draft_revision !== currentRevision) {
      dom.draftEditState.textContent = "正文与已保存草稿一致。";
    }
  } else {
    dom.draftRevision.textContent = "等待草稿修订";
    if (!workspace.draftDirty) dom.draftEditState.textContent = "尚无已保存的正文修订。";
  }
  if (typeof snapshot.received_turn_id === "string" && snapshot.received_turn_id) {
    if (workspace.currentTurnId !== snapshot.received_turn_id) {
      workspace.currentTurnId = snapshot.received_turn_id;
      workspace.turnPreview = "";
    }
    if (typeof snapshot.received_text === "string") workspace.turnPreview = snapshot.received_text;
    renderLivePreview(snapshot.received_turn_id);
  }
  applySuggestedCoordinate(snapshot);
  renderGeneratedDraft(snapshot);
  invalidateMemoryBrowse(snapshot);
  if (!dom.memorySurface.hidden && !workspace.memoryBrowse) void loadMemoryPage();
  renderHarnessHandoff(snapshot);
  if (snapshot.error) {
    const errorText = typeof snapshot.error === "string" ? snapshot.error : snapshot.error.message;
    if (errorText) showError(errorText);
  }
  const statusText = snapshot.cancel_requested && (snapshot.status === "running" || snapshot.status === "queued")
    ? "已请求停止，等待本轮结束"
    : statusLabel(snapshot.status, snapshot.driver);
  setRunStatus(statusText, snapshot.status || "idle");
  if (isTerminalStatus(snapshot.status)) {
    workspace.terminalRunId = expectedRunId;
    stopRunObservation(expectedRunId);
  }
  updateActionAvailability();
  writeStoredWorkspace();
}

/**
 * 依赖：bootstrap 选择、当前控件、run.binding.scope 与首次快照标记。
 * 输入：当前 run 的初始快照。
 * 输出：无；按仍有效的目录选项恢复 scope、driver 和 builtin profile。
 * 实现：只同步一次且尊重作者已改过的控件，避免迟到快照改写后续选择。
 */
function restoreRunSelection(snapshot) {
  if (workspace.runSelectionInitialized) return;
  workspace.runSelectionInitialized = true;
  const scope = snapshot.binding && snapshot.binding.scope;
  if (!workspace.scopeSelectionTouched && scope && typeof scope.story_id === "string") {
    const storyExists = workspace.stories.some((story) => story.story_id === scope.story_id);
    if (storyExists) {
      dom.storySelect.value = scope.story_id;
      updateTimelineOptions(typeof scope.timeline_id === "string" ? scope.timeline_id : "");
    }
  }
  if (!workspace.driverSelectionTouched && (snapshot.driver === "builtin" || snapshot.driver === "harness")) {
    dom.driverSelect.value = snapshot.driver;
  }
  if (!workspace.profileSelectionTouched && !workspace.driverSelectionTouched
      && snapshot.driver === "builtin" && typeof snapshot.profile_name === "string") {
    const profileExists = workspace.profiles.some((profile) => profile.name === snapshot.profile_name);
    if (profileExists) dom.profileSelect.value = snapshot.profile_name;
  }
  updateDriverControls();
  writeStoredWorkspace();
}

/**
 * 依赖：外部 run 快照、页面 origin 与交接区节点。
 * 输入：当前 run snapshot。
 * 输出：无；安全显示固定接入命令并按 run 切换清空旧上下文。
 * 实现：只渲染真实 run ID/origin，不在命令或页面写入工作区 token。
 */
function renderHarnessHandoff(snapshot) {
  const available = snapshot && snapshot.driver === "harness";
  dom.harnessPanel.hidden = !available;
  if (!available) return;
  if (workspace.harnessContextRunId !== snapshot.run_id) {
    workspace.harnessContextRunId = snapshot.run_id;
    workspace.harnessContextRequestRunId = "";
    dom.harnessContextOutput.value = "";
    dom.harnessContextStatus.textContent = "可读取本轮交接上下文；正文可以在外部工具返回后保存或采用。";
  }
  dom.harnessCommand.textContent = `python -m novel_rag.cli harness mcp --backend ${window.location.origin} --run-id ${snapshot.run_id}`;
  dom.harnessContextButton.disabled = workspace.harnessContextRequestRunId === snapshot.run_id;
}

/**
 * 依赖：GET /runs/{id}/harness-context、内存 token 和当前 run 快照。
 * 输入：交接上下文按钮事件。
 * 输出：Promise<void>；成功时以只读 JSON 文本呈现真实上下文。
 * 实现：仅按按钮读取一次，迟到结果不覆盖新 run，错误留在交接区供重试。
 */
async function loadHarnessContext() {
  const runId = workspace.runId;
  if (!runId || !workspace.snapshot || workspace.snapshot.driver !== "harness"
      || workspace.harnessContextRequestRunId === runId) return;
  workspace.harnessContextRequestRunId = runId;
  dom.harnessContextButton.disabled = true;
  dom.harnessContextStatus.textContent = "正在读取交接上下文…";
  try {
    const context = await apiFetch(`/runs/${encodeURIComponent(runId)}/harness-context?view=model`);
    if (runId !== workspace.runId) return;
    dom.harnessContextOutput.value = JSON.stringify(context, null, 2);
    dom.harnessContextStatus.textContent = "交接上下文已载入；可在只读文本框中选中并复制。";
  } catch (error) {
    if (runId !== workspace.runId) return;
    dom.harnessContextStatus.textContent = `读取失败：${error.message || "请稍后重试。"}`;
  } finally {
    if (runId === workspace.runId) {
      workspace.harnessContextRequestRunId = "";
      dom.harnessContextButton.disabled = false;
    }
  }
}

/**
 * 依赖：snapshot中的suggested_coordinate/target_coordinate与三个坐标框。
 * 输入：当前run的完整快照。
 * 输出：无。
 * 实现：仅在作者未手动改坐标时补入建议值，并优先使用服务显式建议。
 */
function applySuggestedCoordinate(snapshot) {
  if (workspace.coordinateDirty) return;
  const bindingTarget = snapshot.binding && snapshot.binding.target_coordinate;
  const coordinate = snapshot.suggested_coordinate || snapshot.target_coordinate || bindingTarget;
  if (!coordinate || typeof coordinate !== "object") return;
  const fields = [
    [dom.volumeInput, coordinate.volume],
    [dom.chapterInput, coordinate.chapter],
    [dom.sceneInput, coordinate.scene]
  ];
  for (const [input, value] of fields) {
    if (Number.isInteger(value)) input.value = String(value);
  }
}

/**
 * 依赖：generated_draft_ref/text服务快照和只读生成稿面板。
 * 输入：当前run的快照。
 * 输出：无。
 * 实现：用textContent呈现保留稿，不接触作者编辑器或其dirty状态。
 */
function renderGeneratedDraft(snapshot) {
  const reference = snapshot.generated_draft_ref;
  const text = snapshot.generated_draft_text;
  const available = Boolean(reference && typeof text === "string");
  dom.generatedDraftButton.hidden = !available;
  dom.generatedDraftButton.disabled = !available;
  if (!available) {
    dom.generatedDraftPanel.hidden = true;
    dom.generatedDraftButton.setAttribute("aria-expanded", "false");
    dom.generatedDraftButton.textContent = "查看保留的生成稿";
    dom.generatedDraftMeta.textContent = "";
    dom.generatedDraftPreview.textContent = "";
    return;
  }
  const revision = Number.isInteger(reference.draft_revision) ? `修订 ${reference.draft_revision}` : "已保留";
  dom.generatedDraftMeta.textContent = revision;
  dom.generatedDraftPreview.textContent = text;
}

/**
 * 依赖：生成稿查看按钮与独立只读面板。
 * 输入：按钮点击事件。
 * 输出：无。
 * 实现：只切换预览面板，不把保留稿写入正文编辑器。
 */
function toggleGeneratedDraft() {
  const expanded = dom.generatedDraftPanel.hidden;
  dom.generatedDraftPanel.hidden = !expanded;
  dom.generatedDraftButton.setAttribute("aria-expanded", String(expanded));
  dom.generatedDraftButton.textContent = expanded ? "收起保留的生成稿" : "查看保留的生成稿";
}

/**
 * 依赖：RunService终态状态值。
 * 输入：快照status。
 * 输出：是否已完成、取消、失败或中断。
 * 实现：集中识别终态，供快照渲染和SSE重连共同使用。
 */
function isTerminalStatus(status) {
  return ["completed", "cancelled", "failed", "interrupted"].includes(status);
}

/**
 * 依赖：后端运行状态字符串。
 * 输入：status 和 driver。
 * 输出：简短中文状态。
 * 实现：映射当前 API 明确的状态，其它值以文本方式呈现。
 */
function statusLabel(status, driver = "builtin") {
  if (status === "prepared" && driver === "harness") return "已准备，等待外部写作工具";
  if (status === "cancelled" && driver === "harness") return "已停止本地工具，外部模型请在其宿主停止";
  const labels = {
    queued: "排队中",
    running: "运行中",
    completed: "本轮已完成",
    cancelled: "本轮已停止",
    failed: "本轮失败",
    interrupted: "运行中断"
  };
  return labels[status] || (status ? `运行状态：${status}` : "尚无运行");
}

/**
 * 依赖：事件 seq、type 和 payload，以及当前 run。
 * 输入：事件对象；是否允许 status/error 事件触发快照刷新。
 * 输出：无。
 * 实现：按seq去重并更新预览、日志和草稿。状态事件触发快照刷新，关闭观察由已确认的终态快照负责。
 */
function consumeEvent(event, scheduleRefresh = true) {
  if (!event || event.run_id !== workspace.runId) return;
  const sequence = Number(event.seq);
  if (Number.isFinite(sequence) && sequence <= workspace.lastEventSeq) return;
  if (Number.isFinite(sequence)) workspace.lastEventSeq = sequence;
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  if (event.type === "text_delta") {
    const turnId = typeof payload.turn_id === "string" ? payload.turn_id : "";
    if (turnId !== workspace.currentTurnId) {
      workspace.currentTurnId = turnId;
      workspace.turnPreview = "";
    }
    workspace.turnPreview += typeof payload.text === "string" ? payload.text : "";
    renderLivePreview(turnId);
  } else if (event.type === "draft_saved") {
    const revision = payload.draft_revision;
    if (Number.isInteger(revision) && revision < workspace.snapshot?.draft_revision) return;
    if (typeof payload.draft_text === "string" && !workspace.draftDirty && !workspace.draftSaveInFlight
        && revision !== workspace.draftExpectedRevision) {
      workspace.draftBaseline = payload.draft_text;
      workspace.draftExpectedRevision = Number.isInteger(payload.draft_revision) ? payload.draft_revision : workspace.draftExpectedRevision;
      dom.draftEditor.value = payload.draft_text;
      dom.draftEditState.textContent = "收到已保存草稿。";
      workspace.turnPreview = "";
      renderLivePreview(workspace.currentTurnId);
    }
    if (Number.isInteger(revision) && workspace.snapshot) {
      workspace.snapshot.draft_revision = revision;
      workspace.snapshot.draft_ref = payload.draft_ref || workspace.snapshot.draft_ref;
      if (typeof payload.draft_text === "string") workspace.snapshot.draft_text = payload.draft_text;
      dom.draftRevision.textContent = `草稿修订 ${revision}`;
      invalidateMemoryBrowse(workspace.snapshot);
    }
    updateActionAvailability();
  } else if (event.type === "tool_started" || event.type === "tool_finished") {
    appendToolLog(event);
  } else if (scheduleRefresh && (event.type === "status" || event.type === "error")) {
    const terminalSeq = event.type === "status" && isTerminalStatus(payload.status) ? sequence : 0;
    window.setTimeout(refreshRunSnapshot, 0, workspace.runId, terminalSeq);
  }
}

/**
 * 依赖：dom.livePreview 与 dom.liveTurnLabel。
 * 输入：turn_id，可为空。
 * 输出：无。
 * 实现：用 textContent 展示当前轮缓冲；turn 切换由事件处理处清空旧缓冲。
 */
function renderLivePreview(turnId) {
  dom.livePreview.textContent = workspace.turnPreview || "当前轮尚未收到文本。";
  dom.liveTurnLabel.textContent = turnId ? `当前轮 ${turnId}` : "等待生成";
}

/**
 * 依赖：工具事件与 dom.toolLog。
 * 输入：tool_started 或 tool_finished 事件。
 * 输出：无。
 * 实现：只显示工具名和阶段，不展示参数/返回值中的任意敏感内容。
 */
function appendToolLog(event) {
  if (dom.toolLog.children.length === 1 && dom.toolLog.firstElementChild.classList.contains("muted")) {
    dom.toolLog.replaceChildren();
  }
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const toolName = payload.tool_name || payload.name || payload.tool || "记忆工具";
  const item = document.createElement("li");
  const phase = event.type === "tool_started" ? "开始" : "完成";
  item.textContent = `${String(toolName)} · ${phase}`;
  dom.toolLog.append(item);
  while (dom.toolLog.children.length > 80) dom.toolLog.firstElementChild.remove();
}

/**
 * 依赖：snapshot.memory_state 及可选 sources/coverage/gaps 字段。
 * 输入：运行 snapshot。
 * 输出：无。
 * 实现：仅在主动浏览提供记忆包时更新；缺少冷字段的live快照保留原面板，资料全部纯文本渲染。
 */
function renderReferencePanels(snapshot) {
  if (!snapshot.memory_state || typeof snapshot.memory_state !== "object") return;
  const memory = snapshot.memory_state && typeof snapshot.memory_state === "object" ? snapshot.memory_state : {};
  const stateView = memory.state_view && typeof memory.state_view === "object" ? memory.state_view : {};
  renderDataList(dom.sourceList, snapshot.sources ?? memory.sources ?? memory.references);
  const coverage = {};
  if (Object.prototype.hasOwnProperty.call(stateView, "coverage")) coverage.coverage = stateView.coverage;
  if (Object.prototype.hasOwnProperty.call(stateView, "recorded_through")) {
    coverage.recorded_through = stateView.recorded_through;
  }
  if (!Object.keys(coverage).length) {
    if (Object.prototype.hasOwnProperty.call(memory, "coverage")) coverage.coverage = memory.coverage;
    else if (Object.prototype.hasOwnProperty.call(snapshot, "coverage")) coverage.coverage = snapshot.coverage;
  }
  renderDataList(dom.coverageList, coverage);
  renderDataList(dom.gapList, stateView.gaps ?? memory.gaps ?? snapshot.gaps);
  renderMemoryCards(memory);
}

/**
 * 依赖：MemoryService已有可见记忆包、memoryCards DOM。
 * 输入：当前run已读取并去重的memory packet。
 * 输出：本次已查各批的完整记录卡；空包明确未记录。
 * 实现：保留原文、身份、性质、位置、来源及选择说明；当前状态与解除回执来自state_view。
 */
function renderMemoryCards(memory) {
  dom.memoryCards.replaceChildren();
  const state = memory.state_view || {};
  const groups = [["event_lines", "事件线"], ["experiences", "发生过的事"], ["hooks", "伏笔与线索"], ["notes", "创作笔记"], ["entries", "当前参考"], ["ended_entries", "解除与结束记录"]];
  for (const [key, label] of groups) {
    const records = ["entries", "ended_entries"].includes(key) ? state[key] : memory[key];
    for (const record of Array.isArray(records) ? records : []) {
      if (!record || typeof record !== "object") continue;
      const payload = record.payload && typeof record.payload === "object" ? record.payload : record;
      const card = document.createElement("section"); card.className = "memory-card";
      card.dataset.recordId = record.id || record.entry_id || "";
      const type = document.createElement("p"); type.className = "eyebrow"; type.textContent = label;
      const title = document.createElement("h3"); title.textContent = payload.title || payload.kind || label;
      const text = document.createElement("p"); text.textContent = payload.text || displayDataValue(payload.value ?? payload);
      card.append(type, title, text);
      const identity = document.createElement("p"); identity.className = "muted";
      identity.textContent = `ID：${record.id || record.entry_id || "未提供"} · 性质：${payload.nature || record.effect || record.kind || record.record_kind || label}`;
      card.append(identity);
      if (record.narrative_position) {
        const position = document.createElement("p"); position.className = "muted";
        position.textContent = "叙事位置：" + displayDataValue(record.narrative_position); card.append(position);
      }
      const sources = record.source_refs || payload.source_refs;
      if (Array.isArray(sources) && sources.length) {
        const source = document.createElement("p"); source.className = "muted";
        source.textContent = "来源：" + sources.map(displayDataValue).join("、");
        card.append(source);
      }
      const reasons = (memory.selection_reasons || []).filter(reason => reason.record_id === card.dataset.recordId
        || (Array.isArray(reason.pack_ids) && reason.pack_ids.includes(card.dataset.recordId)));
      if (reasons.length) {
        const selection = document.createElement("p"); selection.className = "muted";
        selection.textContent = "选择说明：" + reasons.map(displayDataValue).join("；"); card.append(selection);
      }
      dom.memoryCards.append(card);
    }
  }
  if (!dom.memoryCards.children.length) {
    const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "这一轮尚无事件与状态记录。你仍可以读取原文、继续创作。";
    dom.memoryCards.append(empty);
  }
}

/** 依赖：记忆页原浏览绑定。输入：可信运行修订。输出：无。实现：修订前进后标记旧记忆结果，保留原包供查看。 */
function invalidateMemoryBrowse(snapshot) {
  const browse = workspace.memoryBrowse;
  if (browse?.binding && !browse.stale && (browse.binding.memory_revision < snapshot.memory_revision
      || browse.binding.draft_revision < snapshot.draft_revision)) {
    browse.stale = true;
    renderMemoryBrowser();
  }
}

/** 依赖：当前run/浏览代次和记忆页节点。输入：无。输出：可见加载/数量/失效状态。实现：只更新浏览控件，轻量快照不替换已读取原包。 */
function renderMemoryBrowser() {
  const browse = workspace.memoryBrowse;
  dom.refreshMemoryButton.disabled = !workspace.runId || Boolean(browse?.loading);
  dom.moreMemoryButton.disabled = !browse?.nextArguments || browse.stale || browse.loading;
  dom.moreMemoryButton.hidden = !browse?.nextArguments;
  if (!browse) {
    dom.memoryStatus.textContent = workspace.runId ? "进入此页后读取记忆。" : "请先选择或准备一轮创作。";
    renderMemoryCards({});
    return;
  }
  const progress = browse.packet?.candidate_search;
  const count = progress?.visited_count ?? 0;
  const prefix = browse.pages ? `已查 ${count} 个节点，共 ${browse.pages} 批。` : "";
  dom.memoryStatus.textContent = browse.loading ? `${prefix}正在读取记忆…`
    : browse.error ? `${prefix}读取失败：${browse.error} 请重新读取。`
    : browse.stale ? `${prefix}草稿或记忆可能已变化，请重新读取后继续。`
    : `${prefix}${browse.nextArguments ? "本批完整记录已显示，可继续查找。" : "本次查询范围已查完；不表示所有语义线索已穷尽。"}`;
  renderReferencePanels({ memory_state: browse.packet || {} });
}

/** 依赖：单一apiFetch/作者memory端点/浏览代次。输入：是否继续候选。输出：读取Promise。实现：同次单飞，逐批核绑定并按身份去重；失败、切run或来源变化不拼混原包。 */
async function loadMemoryPage(continuing = false) {
  const runId = workspace.runId;
  if (!runId) { renderMemoryBrowser(); return; }
  const previous = workspace.memoryBrowse;
  if (previous?.loading) return;
  if (continuing && (!previous?.nextArguments || previous.stale)) return;
  const generation = continuing ? workspace.memoryBrowseGeneration : ++workspace.memoryBrowseGeneration;
  const browse = continuing ? previous : { runId, packet: null, binding: null, pages: 0, nextArguments: null, stale: false };
  workspace.memoryBrowse = browse;
  browse.loading = true;
  browse.error = "";
  renderMemoryBrowser();
  const argumentsValue = continuing ? browse.nextArguments : dom.memoryQueryInput.value.trim()
    ? { query: dom.memoryQueryInput.value.trim() } : {};
  try {
    const result = await apiFetch(`/runs/${encodeURIComponent(runId)}/memory`, {
      method: "POST", body: JSON.stringify({ arguments: argumentsValue })
    });
    if (runId !== workspace.runId || generation !== workspace.memoryBrowseGeneration) return;
    const packet = result.packet;
    const binding = packet?.browse_binding;
    if (packet?.ok === false) throw new Error(packet.error?.message || "记忆读取被拒绝");
    if (result.run_id !== runId || result.origin !== "author_browse" || !packet || packet.delivery
        || !binding || binding.run_id !== runId) throw new Error("记忆响应身份或交付形式不匹配");
    if (browse.binding && ["run_id", "draft_ref", "draft_revision", "memory_revision", "source_snapshot_hash"]
      .some(key => displayDataValue(browse.binding[key]) !== displayDataValue(binding[key]))) {
      throw new Error("来源或记忆快照已变化");
    }
    const current = workspace.snapshot;
    if (current && (current.memory_revision > binding.memory_revision || current.draft_revision > binding.draft_revision)) {
      throw new Error("草稿或记忆版本已变化");
    }
    const merged = { ...packet, state_view: { ...(packet.state_view || {}) } };
    for (const group of ["event_lines", "experiences", "hooks", "notes", "links", "selection_reasons", "source_refs", "references", "gaps"]) {
      const rows = [...(browse.packet?.[group] || []), ...(packet[group] || [])];
      merged[group] = [...new Map(rows.map(row => [row.id || row.entry_id || displayDataValue(row), row])).values()];
    }
    for (const group of ["entries", "ended_entries"]) {
      const rows = [...(browse.packet?.state_view?.[group] || []), ...(packet.state_view?.[group] || [])];
      merged.state_view[group] = [...new Map(rows.map(row => [row.entry_id || row.id || displayDataValue(row), row])).values()];
    }
    browse.packet = merged;
    browse.binding = binding;
    browse.pages += 1;
    browse.nextArguments = packet.candidate_search?.next_arguments || null;
  } catch (error) {
    if (runId !== workspace.runId || generation !== workspace.memoryBrowseGeneration) return;
    browse.packet = null;
    browse.binding = null;
    browse.nextArguments = null;
    browse.stale = true;
    browse.error = error.message || "无法读取记忆";
  } finally {
    if (runId === workspace.runId && generation === workspace.memoryBrowseGeneration) {
      browse.loading = false;
      renderMemoryBrowser();
    }
  }
}

/** 依赖：记忆表单/原浏览入口。输入：submit事件。输出：无。实现：阻止页面导航并从当前查询重新读取。 */
function refreshMemory(event) {
  event.preventDefault();
  void loadMemoryPage();
}

/** 依赖：原候选next_arguments/浏览入口。输入：click事件。输出：无。实现：只推进候选，不使用冻结交付next_arguments。 */
function continueMemory() {
  void loadMemoryPage(true);
}

/** 依赖：memorySurface.hidden/当前run。输入：属性变化通知。输出：无。实现：进入页面时读取未浏览或已失效的记忆，失败后可手动刷新。 */
function observeMemorySurface() {
  const browse = workspace.memoryBrowse;
  if (!dom.memorySurface.hidden && workspace.runId && (!browse || (browse.stale && !browse.error))) void loadMemoryPage();
}

/**
 * 依赖：目标列表节点与服务返回的 JSON 值。
 * 输入：ul 节点和值；值可为数组、对象、标量或空值。
 * 输出：无。
 * 实现：构造 li 并将简化后的值写入 textContent，不使用 innerHTML。
 */
function renderDataList(list, value) {
  list.replaceChildren();
  const entries = [];
  if (Array.isArray(value)) {
    for (const entry of value) entries.push(entry);
  } else if (value && typeof value === "object") {
    for (const [key, itemValue] of Object.entries(value)) {
      entries.push(`${key}：${displayDataValue(itemValue)}`);
    }
  } else if (value !== undefined && value !== null) {
    entries.push(value);
  }
  if (!entries.length) {
    const item = document.createElement("li");
    item.className = "muted";
    item.textContent = "当前快照没有此项数据。";
    list.append(item);
    return;
  }
  for (const entry of entries) {
    const item = document.createElement("li");
    item.textContent = displayDataValue(entry);
    list.append(item);
  }
}

/**
 * 依赖：JSON.stringify。
 * 输入：任意服务数据值。
 * 输出：适合 textContent 的纯文本。
 * 实现：标量直接转文本，结构化值序列化；序列化失败时给出固定提示。
 */
function displayDataValue(value) {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "无";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "无法显示此项数据。";
  }
}

/**
 * 依赖：GET /runs/{id}/events SSE、内存 token、seq 游标、applySnapshot和AbortController。
 * 输入：run_id 与 stream AbortSignal。
 * 输出：Promise<void>。
 * 实现：区分普通事件与snapshot帧；只在当前run未终止时按最后seq重连。
 */
async function watchRunEvents(runId, signal) {
  while (!signal.aborted && runId === workspace.runId && workspace.terminalRunId !== runId) {
    try {
      const response = await fetch(`${API_ROOT}/runs/${encodeURIComponent(runId)}/events?after=${workspace.lastEventSeq}`, {
        headers: { "X-Workspace-Token": workspace.token, Accept: "text/event-stream" },
        cache: "no-store",
        signal
      });
      if (!response.ok) throw new Error(`事件流请求失败：${response.status}`);
      if (!response.body) throw new Error("浏览器不支持读取事件流。");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!signal.aborted && runId === workspace.runId && workspace.terminalRunId !== runId) {
        const part = await reader.read();
        if (part.done) break;
        buffer += decoder.decode(part.value, { stream: true });
        buffer = buffer.replace(/\r\n/g, "\n");
        let separator = buffer.indexOf("\n\n");
        while (separator >= 0) {
          const frame = buffer.slice(0, separator);
          buffer = buffer.slice(separator + 2);
          const parsed = parseSseFrame(frame);
          if (parsed && parsed.eventName === "snapshot") {
            applySnapshot(parsed.data, runId);
          } else if (parsed) {
            consumeEvent(parsed.data);
          }
          separator = buffer.indexOf("\n\n");
        }
      }
      if (!signal.aborted && runId === workspace.runId && workspace.terminalRunId !== runId) {
        await pause(EVENT_RETRY_MS);
      }
    } catch (error) {
      if (signal.aborted || runId !== workspace.runId || workspace.terminalRunId === runId) return;
      setRunStatus("事件流重连中，状态仍会定期刷新", "warning");
      await pause(EVENT_RETRY_MS);
    }
  }
}

/**
 * 依赖：SSE data 行与 JSON.parse。
 * 输入：一个以空行分隔的 SSE frame 文本。
 * 输出：解析后的事件对象；没有有效 data 时返回 null。
 * 实现：收集 data 行并解析 JSON，格式错误只丢弃该 frame。
 */
function parseSseFrame(frame) {
  let eventName = "message";
  const dataLines = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  try {
    return { eventName, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * 依赖：Promise 与 window.setTimeout。
 * 输入：等待毫秒数。
 * 输出：等待结束的 Promise<void>。
 * 实现：为 SSE 断线重连提供有界间隔。
 */
function pause(milliseconds) {
  /**
   * 依赖：window.setTimeout 与 pause 的等待时长。
   * 输入：Promise resolve 函数。
   * 输出：无。
   * 实现：在指定间隔后结束 pause 返回的 Promise。
   */
  function schedulePause(resolve) {
    window.setTimeout(resolve, milliseconds);
  }
  return new Promise(schedulePause);
}

/**
 * 依赖：当前run、AbortController、live轮询、事件流及记忆浏览代次。
 * 输入：新的 run_id。
 * 输出：无。
 * 实现：切换观察目标时停止旧流、更新URL、失效旧读取和记忆包，再恢复新run。
 */
function resetRunView(runId = "", sessionId = "") {
  if (workspace.eventController) workspace.eventController.abort();
  window.clearInterval(workspace.pollTimer);
  workspace.snapshotRequestSeq += 1;
  workspace.snapshotInFlight = null;
  workspace.memoryBrowseGeneration += 1;
  workspace.memoryBrowse = null;
  workspace.runId = runId;
  workspace.sessionId = sessionId || "";
  workspace.snapshot = null;
  workspace.terminalRunId = "";
  workspace.lastEventSeq = 0;
  workspace.runSelectionInitialized = false;
  workspace.currentTurnId = "";
  workspace.turnPreview = "";
  workspace.draftBaseline = "";
  workspace.draftExpectedRevision = 0;
  workspace.draftDirty = false;
  workspace.draftSaveInFlight = null;
  workspace.localLoadedKey = "";
  workspace.localRecovery = null;
  dom.localRecoveryPanel.hidden = true;
  workspace.coordinateDirty = false;
  workspace.inputRestoreRunId = "";
  for (const field of [dom.volumeInput, dom.chapterInput, dom.sceneInput]) field.value = "";
  workspace.harnessContextRunId = "";
  workspace.harnessContextRequestRunId = "";
  dom.harnessPanel.hidden = true;
  dom.harnessContextOutput.value = "";
  dom.harnessContextStatus.textContent = "可读取本轮交接上下文。";
  const currentUrl = new URL(window.location.href);
  if (runId) currentUrl.searchParams.set("run", runId);
  else currentUrl.searchParams.delete("run");
  window.history.replaceState(window.history.state, "", currentUrl);
  dom.savedPartialPanel.hidden = true;
  dom.savedPartialPreview.textContent = "";
  dom.draftEditor.value = "";
  dom.draftRevision.textContent = "等待草稿修订";
  dom.draftEditState.textContent = "正在载入运行草稿…";
  renderGeneratedDraft({});
  updateActionAvailability();
  dom.toolLog.replaceChildren();
  renderMemoryBrowser();
  for (const list of [dom.sourceList, dom.coverageList, dom.gapList]) renderDataList(list, null);
  renderLivePreview("");
  showError("");
  writeStoredWorkspace();
}

/** 依赖：本机保存/resetRunView/原快照观察。输入：新run/session及是否保护原编辑。输出：载入完成Promise。实现：先保留原副本再切run，不取消原模型。 */
async function activateRun(runId, sessionId, preserveCurrent = true) {
  if (preserveCurrent && !persistLocalInputs()) throw new Error("本机保存失败，原编辑保留；请复制或保存后再切任务。");
  resetRunView(runId, sessionId);
  await refreshRunSnapshot(runId);
  beginRunObservation(runId);
  persistLocalInputs();
  renderLocalArchive();
  updateActionAvailability();
}

/**
 * 依赖：AbortController、SSE 观察器和 snapshot 定时器。
 * 输入：run_id。
 * 输出：无。
 * 实现：开启单一事件流，并确保定期快照读取最新持久状态。
 */
function beginRunObservation(runId) {
  if (!runId || runId !== workspace.runId || workspace.terminalRunId === runId) return;
  if (workspace.eventController) workspace.eventController.abort();
  workspace.eventController = new AbortController();
  watchRunEvents(runId, workspace.eventController.signal);
  window.clearInterval(workspace.pollTimer);
  workspace.pollTimer = window.setInterval(pollCurrentRun, POLL_INTERVAL_MS);
}

/**
 * 依赖：当前run的SSE AbortController与snapshot定时器。
 * 输入：待停止观察的run_id。
 * 输出：无。
 * 实现：仅关闭仍属于当前run的观察资源，终态不再循环重连。
 */
function stopRunObservation(runId) {
  if (!runId || runId !== workspace.runId) return;
  window.clearInterval(workspace.pollTimer);
  if (workspace.eventController) {
    const controller = workspace.eventController;
    workspace.eventController = null;
    controller.abort();
  }
}

/**
 * 依赖：当前 run_id 与 refreshRunSnapshot。
 * 输入：无。
 * 输出：无。
 * 实现：定时刷新持久快照，确保断开或刷新后能恢复状态。
 */
function pollCurrentRun() {
  if (workspace.runId) refreshRunSnapshot(workspace.runId);
}

/**
 * 依赖：storySelect、timelineSelect、profileSelect 与本地恢复位置。
 * 输入：作品切换事件。
 * 输出：无。
 * 实现：记录作者的 scope 选择，刷新对应时间线并保存当前恢复位置。
 */
function onStoryChange() {
  workspace.scopeSelectionTouched = true;
  updateTimelineOptions("");
  void switchSelectedScope();
}

/**
 * 依赖：当前 scope 选择和 localStorage 恢复位置。
 * 输入：时间线或 profile 变化事件。
 * 输出：无。
 * 实现：标记作者手动改过的 scope/profile，保存选择并更新开始按钮可用状态。
 */
function onScopeChange(event) {
  if (event && event.target === dom.timelineSelect) workspace.scopeSelectionTouched = true;
  if (event && event.target === dom.profileSelect) workspace.profileSelectionTouched = true;
  if (event && event.target === dom.timelineSelect) { void switchSelectedScope(); return; }
  updateDriverControls();
  writeStoredWorkspace();
  updateActionAvailability();
  persistLocalInputs();
}

/**
 * 依赖：driverSelect、profileSelect 与 localStorage 恢复位置。
 * 输入：写作工具选择事件。
 * 输出：无。
 * 实现：保留作者当前选择，更新 profile 必填条件并保存同 scope 的 driver。
 */
function onDriverChange() {
  workspace.driverSelectionTouched = true;
  updateDriverControls();
  writeStoredWorkspace();
  updateActionAvailability();
  persistLocalInputs();
}

/** 依赖：原本机副本/单run观察/资源owner。输入：已改变的作品或时间线选择。输出：恢复新范围Promise。实现：先存旧编辑再断观察，不取消旧run；新scope不展示旧书稿。 */
async function switchSelectedScope() {
  const next = selectedResourceScope();
  const previous = localInputScope();
  if (previous.story_id && !persistLocalInputs()) {
    dom.storySelect.value = previous.story_id;
    updateTimelineOptions(previous.timeline_id);
    showError("本机保存失败，原作品和输入保留。请保存或复制后再切换。");
    return;
  }
  resetRunView();
  workspace.localScope = next;
  workspace.pendingRunRequest = null;
  workspace.outlineInputTouched = false;
  workspace.requestInputTouched = false;
  workspace.reviseBaseRef = null;
  dom.outlineInput.value = "";
  dom.requestInput.value = "";
  document.querySelector('input[name="task_kind"][value="write"]').checked = true;
  let runId = "";
  try {
    const pointer = JSON.parse(localStorage.getItem(workspace.storageKey + ".scope." + encodeURIComponent(next.key)) || "null");
    if (pointer && typeof pointer.run_id === "string") runId = pointer.run_id;
  } catch { /* 原记录保留，新范围仍能使用。 */ }
  try {
    void loadScopedResources();
    if (runId) await activateRun(runId, "", false);
    else { restoreLocalInputs(); writeStoredWorkspace(); }
  } catch (error) { showError(error.message || "范围载入失败，本机副本仍可回读。"); renderLocalArchive(); }
  updateDriverControls();
  updateActionAvailability();
}

/** 依赖：原生dialog。输入：作者点击。输出：设置指引。实现：仅显示已有本机配置路径，不执行命令或接收密钥。 */
function showSetupDialog() { dom.setupDialog.showModal(); }

/** 依赖：原生dialog。输入：作者关闭。输出：返回写作。实现：关闭指引不更改运行或配置。 */
function closeSetupDialog() { dom.setupDialog.close(); }

/** 依赖：原driver控件。输入：作者选择。输出：harness可准备状态。实现：委托原change处理，不调用模型。 */
function chooseHarness() { dom.driverSelect.value = "harness"; onDriverChange(); }

/** 依赖：唯一bootstrap/API和脱敏profile白名单。输入：作者重读。输出：更新profile选择Promise。实现：保持工作区身份、run和所有编辑，不重启观察/模型。 */
async function refreshProfiles() {
  dom.refreshProfilesButton.disabled = true;
  try {
    const result = await apiFetch("/bootstrap", {}, true);
    if (result.workspace_id !== workspace.workspaceId) throw new Error("服务已切到其他工作区，请先复制输入再刷新页面。");
    const selected = dom.profileSelect.value;
    workspace.token = result.token;
    workspace.bootstrap = result;
    workspace.profiles = Array.isArray(result.profiles) ? result.profiles : [];
    fillSelect(dom.profileSelect, workspace.profiles, "name", "name", "没有可用模型配置", selected);
    updateDriverControls();
    updateActionAvailability();
    writeStoredWorkspace();
    dom.setupStatus.textContent = workspace.profiles.length ? "已读取本机模型配置，可以返回写作。" : result.model_configuration_error?.message || "尚未找到配置，也可以使用自己的写作工具。";
  } catch (error) { dom.setupStatus.textContent = error.message || "读取失败，输入仍保留。"; }
  finally { dom.refreshProfilesButton.disabled = false; }
}

/** 依赖：原生新作品dialog/待确认意图。输入：作者点击。输出：标题表单。实现：重试保留原标题及ID，不改变当前编辑。 */
function showNewStoryDialog() {
  if (workspace.pendingNewStory) {
    dom.newStoryTitleInput.value = workspace.pendingNewStory.title;
    dom.newStoryStatus.textContent = "上次创建结果待确认，将使用原标题和编号核对。";
  }
  dom.newStoryDialog.showModal();
}

/** 依赖：原生dialog。输入：作者关闭。输出：返回编辑。实现：保留标题与未知创建意图。 */
function closeNewStoryDialog() { dom.newStoryDialog.close(); }

/** 依赖：薄新作品API/原范围切换。输入：标题表单提交。输出：创建并选择新作品Promise。实现：固定原意图，不重发新ID；确认成功后才切范围，失败保留表单。 */
async function createStory(event) {
  event.preventDefault();
  if (workspace.storyCreating) return;
  const title = dom.newStoryTitleInput.value.trim();
  if (!title) return;
  if (localInputScope().story_id && !persistLocalInputs()) {
    dom.newStoryStatus.textContent = "当前输入尚未临时保存，请保存或复制后再创建。";
    return;
  }
  const pending = workspace.pendingNewStory || { story_id: "story-" + crypto.randomUUID(), title };
  workspace.pendingNewStory = pending;
  const pendingKey = workspace.storageKey + ".new-story." + workspace.tabId;
  try { localStorage.setItem(pendingKey, JSON.stringify(pending)); }
  catch { dom.newStoryStatus.textContent = "浏览器未能保存创建编号，创建尚未发送；请恢复本机存储后重试。"; return; }
  workspace.storyCreating = true;
  dom.createStoryButton.disabled = true;
  updateActionAvailability();
  try {
    const result = await apiFetch("/stories", { method: "POST", body: JSON.stringify(pending) });
    workspace.pendingNewStory = null;
    try {
      localStorage.removeItem(pendingKey);
      if (workspace.pendingNewStoryKey) localStorage.removeItem(workspace.pendingNewStoryKey);
    } catch { /* 已确认的同意图重读安全。 */ }
    workspace.pendingNewStoryKey = "";
    workspace.stories = await apiFetch("/stories");
    fillSelect(dom.storySelect, workspace.stories, "story_id", "title", "没有可用作品", result.story_id);
    updateTimelineOptions("main");
    workspace.scopeSelectionTouched = true;
    await switchSelectedScope();
    dom.newStoryDialog.close();
    dom.outlineInput.focus();
  } catch (error) {
    if (error.code === "source_invalid" || error.code === "scope_denied") {
      workspace.pendingNewStory = null;
      try {
        localStorage.removeItem(pendingKey);
        if (workspace.pendingNewStoryKey) localStorage.removeItem(workspace.pendingNewStoryKey);
      } catch { /* 保留安全失败提示。 */ }
      workspace.pendingNewStoryKey = "";
    }
    dom.newStoryStatus.textContent = error.message || "结果待确认。再次创建会核对原作品，不另建副本。";
  } finally {
    workspace.storyCreating = false;
    dom.createStoryButton.disabled = false;
    updateActionAvailability();
  }
}

/**
 * 依赖：作品与时间线选择框。
 * 输入：无。
 * 输出：当前作品、时间线及稳定的内存键。
 * 实现：仅由受控选择值组成scope，不接受路径或任意资源定位符。
 */
function selectedResourceScope() {
  const storyId = dom.storySelect.value;
  const timelineId = dom.timelineSelect.value;
  return { storyId, timelineId, key: JSON.stringify([storyId, timelineId]) };
}

/** 依赖：资源加载与资料选择序号、当前作品线。输入：请求的scope和序号，资料详情另带选择序号。输出：响应仍可应用的布尔值。实现：同时核对scope、重载及选中项，拒绝迟到的成功响应和错误。 */
function isCurrentResourceRequest(scope, requestSeq, detailSeq) {
  return requestSeq === workspace.resourceLoadSeq && scope.key === selectedResourceScope().key
    && (detailSeq === undefined || detailSeq === workspace.documentDetailSeq);
}

/**
 * 依赖：scope key 与文档ID。
 * 输入：作用域键和资料ID。
 * 输出：此资料未保存编辑的内存缓存键。
 * 实现：JSON编码二元组，避免作品、时间线或资料ID分隔符碰撞。
 */
function documentDraftKey(scopeKey, documentId) {
  return JSON.stringify([scopeKey, documentId]);
}

/**
 * 依赖：作者偏好编辑框、expected_revision 和内存缓存。
 * 输入：无；读取当前偏好编辑状态。
 * 输出：无。
 * 实现：dirty时保存文本与原CAS，clean时删除缓存，切换scope不丢作者输入。
 */
function cacheCurrentPreferenceDraft() {
  const key = workspace.resourceScopeKey;
  if (!key) return;
  if (workspace.preferencesDirty) {
    workspace.preferencesDrafts.set(key, {
      content: dom.preferencesEditor.value,
      baseline: workspace.preferencesBaseline,
      expectedRevision: workspace.preferencesExpectedRevision
    });
  } else {
    workspace.preferencesDrafts.delete(key);
  }
}

/**
 * 依赖：当前资料编辑框、source_ref、revision 与内存缓存。
 * 输入：无；读取当前资料编辑状态。
 * 输出：无。
 * 实现：仅缓存可编辑资料的未保存文本，并保留原双CAS供切回后检测冲突。
 */
function cacheCurrentDocumentDraft() {
  const documentId = workspace.activeDocumentId;
  const scopeKey = workspace.resourceScopeKey;
  if (!documentId || !scopeKey) return;
  const key = documentDraftKey(scopeKey, documentId);
  if (workspace.documentDirty && workspace.documentEditable) {
    workspace.documentDrafts.set(key, {
      content: dom.documentEditor.value,
      baseline: workspace.documentBaseline,
      expectedRevision: workspace.documentExpectedRevision,
      sourceRef: workspace.documentSourceRef
    });
  } else if (!workspace.documentDirty) {
    workspace.documentDrafts.delete(key);
  }
}

/** 依赖：资料面板与原编辑缓存形状。输入：待打开的资料ID和可选缓存。输出：新的详情选择序号。实现：清理前一详情及操作，保留待核对的原文本和CAS。 */
function resetDocumentDetail(documentId = "", cached = null) {
  const detailSeq = ++workspace.documentDetailSeq;
  workspace.activeDocumentId = documentId;
  workspace.activeDocumentType = "";
  workspace.documentBaseline = cached?.baseline ?? "";
  workspace.documentExpectedRevision = cached ? cached.expectedRevision : null;
  workspace.documentSourceRef = cached ? cached.sourceRef : null;
  workspace.documentDirty = Boolean(cached && cached.content !== cached.baseline);
  workspace.documentEditable = false;
  dom.documentEditor.value = cached?.content ?? "";
  dom.documentEditor.hidden = !cached;
  dom.documentEditor.disabled = true;
  dom.documentEditorLabel.hidden = !cached;
  dom.documentPreview.textContent = "";
  dom.documentPreview.hidden = true;
  updateDocumentActions();
  return detailSeq;
}

/**
 * 依赖：当前作品/时间线、偏好与资料 API 及未保存输入缓存。
 * 输入：是否强制重载当前作用域。
 * 输出：Promise<void>；完成两个作用域资源读取。
 * 实现：先按scope失效旧读取并保留未保存输入；面板打开后单次加载，显式刷新复用相同保护。
 */
async function loadScopedResources(force = false) {
  if (!workspace.resourceReady) return;
  const scope = selectedResourceScope();
  const changedScope = scope.key !== workspace.resourceScopeKey;
  const canRead = !dom.resourcesSurface.hidden && dom.resourcesPanel.open && scope.storyId && scope.timelineId;
  if (!changedScope && (!canRead || workspace.resourceLoadState === "loading"
      || (!force && workspace.resourceLoadState === "loaded"))) return;
  cacheCurrentPreferenceDraft();
  cacheCurrentDocumentDraft();
  const requestSeq = ++workspace.resourceLoadSeq;
  workspace.resourceScopeKey = scope.key;
  workspace.resourceLoadState = canRead ? "loading" : "idle";
  if (changedScope) workspace.reviseBaseRef = null;

  const preferenceDraft = workspace.preferencesDrafts.get(scope.key);
  workspace.preferencesBaseline = preferenceDraft ? preferenceDraft.baseline : "";
  workspace.preferencesExpectedRevision = preferenceDraft ? preferenceDraft.expectedRevision : null;
  workspace.preferencesDirty = Boolean(preferenceDraft && preferenceDraft.content !== preferenceDraft.baseline);
  dom.preferencesEditor.value = preferenceDraft ? preferenceDraft.content : "";
  dom.preferencesEditor.disabled = !scope.storyId || !scope.timelineId || !preferenceDraft;
  dom.preferencesStatus.textContent = canRead
    ? (preferenceDraft ? "已保留此范围未保存的偏好，正在核对服务器版本。" : "正在读取此作品和时间线的偏好。")
    : "打开资料面板后读取偏好。";

  workspace.documents = [];
  resetDocumentDetail();
  dom.documentSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = canRead ? "正在读取资料…" : "打开资料面板后读取";
  dom.documentSelect.append(placeholder);
  dom.documentSelect.disabled = true;
  dom.documentStatus.textContent = canRead ? "正在读取此时间线的资料。"
    : scope.storyId && scope.timelineId ? "打开资料面板后读取。" : "选择作品和时间线后读取资料。";
  dom.reviseDocumentStatus.hidden = true;
  dom.reloadDocumentsButton.disabled = true;
  updatePreferenceActions();
  if (!canRead) return;
  await Promise.all([
    loadPreferences(scope, requestSeq),
    loadDocumentList(scope, requestSeq)
  ]);
  if (!isCurrentResourceRequest(scope, requestSeq)) return;
  workspace.resourceLoadState = "loaded";
  dom.reloadDocumentsButton.disabled = false;
}

/** 依赖：导航控制的hidden和原生details。输入：可见性或展开通知。输出：无。实现：只在真实展开时让统一scope加载器判断是否读取。 */
function observeResourceSurface() {
  if (!dom.resourcesSurface.hidden && dom.resourcesPanel.open) void loadScopedResources();
}

/**
 * 依赖：loadScopedResources 与当前scope的资料API。
 * 输入：无。
 * 输出：Promise<void>；重新读取当前作品和时间线的偏好与资料选择。
 * 实现：复用统一scope序号，使手动刷新与自动scope切换采用同一保护逻辑。
 */
function reloadScopedResources() {
  return loadScopedResources(true);
}

/**
 * 依赖：GET/PUT偏好API、当前scope和缓存的作者输入。
 * 输入：scope与本次scope加载序号。
 * 输出：Promise<void>；将服务器偏好载入或保留本地dirty文本。
 * 实现：仅接受仍属于当前作品/时间线的响应，旧缓存保留原expected_revision。
 */
async function loadPreferences(scope, requestSeq) {
  const cached = workspace.preferencesDrafts.get(scope.key);
  const url = `/preferences/${encodeURIComponent(scope.storyId)}?timeline_id=${encodeURIComponent(scope.timelineId)}`;
  try {
    const result = await apiFetch(url);
    if (!isCurrentResourceRequest(scope, requestSeq)) return;
    const serverContent = typeof result.content === "string" ? result.content : "";
    const keepEditor = Boolean(cached || workspace.preferencesDirty);
    workspace.preferencesBaseline = cached ? cached.baseline : serverContent;
    workspace.preferencesExpectedRevision = cached ? cached.expectedRevision : result.expected_revision;
    workspace.preferencesDirty = keepEditor && dom.preferencesEditor.value !== workspace.preferencesBaseline;
    if (cached) {
      const stale = cached.expectedRevision !== result.expected_revision;
      dom.preferencesStatus.textContent = stale
        ? "此范围偏好已在别处更新；你的输入已保留，保存时会检查版本。"
        : "此范围的未保存偏好已保留。";
      dom.preferencesEditor.disabled = false;
    } else if (keepEditor) {
      dom.preferencesStatus.textContent = "读取期间的编辑已保留。";
    } else {
      dom.preferencesEditor.value = serverContent;
      dom.preferencesEditor.disabled = false;
      dom.preferencesStatus.textContent = "已读取此作品和时间线的偏好。";
    }
    cacheCurrentPreferenceDraft();
    updatePreferenceActions();
  } catch (error) {
    if (!isCurrentResourceRequest(scope, requestSeq)) return;
    dom.preferencesEditor.disabled = !cached;
    dom.preferencesStatus.textContent = cached
      ? `偏好读取失败；未保存输入仍保留。${error.message || ""}`
      : `无法读取偏好。${error.message || ""}`;
    updatePreferenceActions();
  }
}

/**
 * 依赖：偏好编辑框、原文基线与draft cache。
 * 输入：偏好textarea的input事件。
 * 输出：无。
 * 实现：以服务器原文计算dirty并缓存当前scope的文本与CAS。
 */
function onPreferencesInput() {
  workspace.preferencesDirty = dom.preferencesEditor.value !== workspace.preferencesBaseline;
  cacheCurrentPreferenceDraft();
  dom.preferencesStatus.textContent = workspace.preferencesDirty ? "偏好有未保存修改。" : "偏好与已保存版本一致。";
  updatePreferenceActions();
}

/**
 * 依赖：偏好PUT API、当前scope与expected_revision。
 * 输入：无；保存当前偏好全文。
 * 输出：Promise<void>；成功时更新基线，版本冲突时保留作者输入。
 * 实现：冻结本次文本和CAS，忽略迟到scope响应，并保留请求期间的新编辑。
 */
async function savePreferences() {
  const scope = selectedResourceScope();
  if (!workspace.preferencesDirty || workspace.preferencesSaving || scope.key !== workspace.resourceScopeKey) return;
  const content = dom.preferencesEditor.value;
  const expectedRevision = workspace.preferencesExpectedRevision;
  if (expectedRevision === null || expectedRevision === undefined) return;
  const requestSeq = workspace.resourceLoadSeq;
  workspace.preferencesSaving = true;
  updatePreferenceActions();
  dom.preferencesStatus.textContent = "正在保存偏好。";
  try {
    const result = await apiFetch(
      `/preferences/${encodeURIComponent(scope.storyId)}?timeline_id=${encodeURIComponent(scope.timelineId)}`,
      { method: "PUT", body: JSON.stringify({ content, expected_revision: expectedRevision }) }
    );
    if (!isCurrentResourceRequest(scope, requestSeq)) return;
    const savedContent = typeof result.content === "string" ? result.content : content;
    workspace.preferencesBaseline = savedContent;
    workspace.preferencesExpectedRevision = result.expected_revision ?? expectedRevision;
    workspace.preferencesDirty = dom.preferencesEditor.value !== savedContent;
    cacheCurrentPreferenceDraft();
    if (workspace.preferencesDirty) {
      dom.preferencesStatus.textContent = "已保存提交版本；你随后输入的修改仍保留。";
    } else {
      dom.preferencesEditor.value = savedContent;
      dom.preferencesStatus.textContent = "偏好已保存。";
    }
  } catch (error) {
    if (!isCurrentResourceRequest(scope, requestSeq)) return;
    workspace.preferencesDirty = true;
    cacheCurrentPreferenceDraft();
    dom.preferencesStatus.textContent = error.httpStatus === 409
      ? "偏好版本已改变；你的输入已保留。请复制修改后再重新读取和核对。"
      : `保存偏好失败；你的输入已保留。${error.message || ""}`;
  } finally {
    workspace.preferencesSaving = false;
    updatePreferenceActions();
  }
}

/**
 * 依赖：偏好dirty标记、CAS版本与保存状态。
 * 输入：无。
 * 输出：无。
 * 实现：只在当前scope偏好已加载且有未保存编辑时开放保存按钮。
 */
function updatePreferenceActions() {
  dom.savePreferencesButton.disabled = !workspace.token || !workspace.resourceScopeKey
    || !workspace.preferencesDirty || workspace.preferencesSaving
    || workspace.preferencesExpectedRevision === null || workspace.preferencesExpectedRevision === undefined;
}

/**
 * 依赖：GET /documents与受控作品/时间线选择。
 * 输入：scope与本次scope加载序号。
 * 输出：Promise<void>；填充资料选择并载入所选条目。
 * 实现：使用textContent构造选项，迟到响应不能替换新scope的资料列表。
 */
async function loadDocumentList(scope, requestSeq) {
  try {
    const query = `story_id=${encodeURIComponent(scope.storyId)}&timeline_id=${encodeURIComponent(scope.timelineId)}`;
    const result = await apiFetch(`/documents?${query}`);
    if (!isCurrentResourceRequest(scope, requestSeq)) return;
    workspace.documents = Array.isArray(result) ? result : [];
    dom.documentSelect.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = workspace.documents.length ? "选择一项资料" : "此时间线没有资料";
    dom.documentSelect.append(placeholder);
    for (const item of workspace.documents) {
      const option = document.createElement("option");
      option.value = String(item.document_id || "");
      option.textContent = `${String(item.title || item.document_id || "资料")} · ${documentTypeLabel(item.document_type)}`;
      dom.documentSelect.append(option);
    }
    dom.documentSelect.disabled = workspace.documents.length === 0;
    dom.documentStatus.textContent = workspace.documents.length
      ? `已载入 ${workspace.documents.length} 项资料；选择后可查看或编辑。`
      : "此时间线目前没有可查看的资料。";
    if (!workspace.documents.length) return;
    const rememberedId = workspace.documentSelections.get(scope.key);
    const selected = rememberedId && workspace.documents.some((item) => item.document_id === rememberedId)
      ? rememberedId : workspace.documents[0].document_id;
    dom.documentSelect.value = selected;
    workspace.documentSelections.set(scope.key, selected);
    await loadDocumentDetail(scope, selected, requestSeq);
  } catch (error) {
    if (!isCurrentResourceRequest(scope, requestSeq)) return;
    dom.documentSelect.disabled = true;
    dom.documentStatus.textContent = `无法读取资料列表。${error.message || ""}`;
  }
}

/**
 * 依赖：GET /documents/{id}、当前scope与资料选择。
 * 输入：scope、资料ID及scope加载序号。
 * 输出：Promise<void>；显示正文、类型、版本和可用作者操作。
 * 实现：按scope/选择序号丢弃迟到响应，缓存dirty文本并只开放允许的纯文本编辑。
 */
async function loadDocumentDetail(scope, documentId, requestSeq) {
  if (!documentId) return;
  cacheCurrentDocumentDraft();
  const item = workspace.documents.find((value) => value.document_id === documentId);
  const cached = workspace.documentDrafts.get(documentDraftKey(scope.key, documentId));
  const detailSeq = resetDocumentDetail(documentId, cached);
  dom.documentStatus.textContent = cached ? "已保留此资料的未保存修改，正在核对版本。" : "正在读取资料正文。";
  try {
    const query = `story_id=${encodeURIComponent(scope.storyId)}&timeline_id=${encodeURIComponent(scope.timelineId)}`;
    const result = await apiFetch(`/documents/${encodeURIComponent(documentId)}?${query}`);
    if (!isCurrentResourceRequest(scope, requestSeq, detailSeq)) return;
    const metadata = result.metadata && typeof result.metadata === "object" ? result.metadata : {};
    const documentType = metadata.document_type || item?.document_type || "";
    const body = result.content;
    const editableText = extractEditableDocumentText(body);
    const canEdit = (documentType === "canon" || String(documentType).toLowerCase().includes("summary"))
      && editableText !== null;
    workspace.activeDocumentType = documentType;
    workspace.documentSourceRef = cached?.sourceRef || result.source_ref || item?.source_ref || null;
    workspace.documentExpectedRevision = cached ? cached.expectedRevision : result.document_revision;
    workspace.documentBaseline = cached ? cached.baseline : editableText ?? "";
    workspace.documentEditable = canEdit;
    if (canEdit || cached) {
      dom.documentEditor.hidden = false;
      dom.documentEditor.disabled = !canEdit;
      dom.documentEditorLabel.hidden = false;
      dom.documentEditorLabel.textContent = canEdit ? "资料正文" : "已保留的本地编辑（当前资料只读）";
      dom.documentEditor.value = cached ? cached.content : editableText;
    }
    workspace.documentDirty = Boolean(cached && dom.documentEditor.value !== workspace.documentBaseline);
    if (canEdit) {
      if (cached) {
        const serverChanged = cached.expectedRevision !== result.document_revision
          || cached.sourceRef?.source_hash !== (result.source_ref && result.source_ref.source_hash);
        dom.documentStatus.textContent = serverChanged
          ? "本地修改已保留，但资料版本已更新；保存会核对原版本。"
          : "此资料的未保存修改已恢复。";
      } else {
        dom.documentStatus.textContent = `${documentTypeLabel(documentType)} · 修订 ${String(result.document_revision ?? "未知")}`;
      }
    } else {
      dom.documentPreview.hidden = false;
      dom.documentPreview.textContent = formatDocumentContent(body);
      if (cached) {
        dom.documentStatus.textContent = "此资料结构只读；已保留的本地编辑仍显示在上方编辑框中。";
      } else if (documentType === "history") {
        dom.documentStatus.textContent = "章节正文只读；可用“修改此章节”将原版本作为创作基线。";
      } else if (body && typeof body === "object") {
        dom.documentStatus.textContent = "这是结构化资料，目前只提供查看，避免编辑时破坏字段。";
      } else {
        dom.documentStatus.textContent = `${documentTypeLabel(documentType)} · 只读`;
      }
    }
    updateDocumentActions();
  } catch (error) {
    if (!isCurrentResourceRequest(scope, requestSeq, detailSeq)) return;
    dom.documentStatus.textContent = `无法读取这项资料。${error.message || ""}`;
    updateDocumentActions();
  }
}

/**
 * 依赖：Canon/summary正文的body映射。
 * 输入：API返回的资料content。
 * 输出：可直接编辑的content字符串；结构化或未知形状返回null。
 * 实现：仅接受body.content为字符串，不把结构化正文压平成可写文本。
 */
function extractEditableDocumentText(body) {
  return body && typeof body === "object" && !Array.isArray(body) && typeof body.content === "string"
    ? body.content
    : null;
}

/**
 * 依赖：JSON安全序列化与资料body。
 * 输入：API返回的资料正文。
 * 输出：用于只读预览的纯文本。
 * 实现：字符串直接展示，结构化body以缩进JSON写入textContent目标。
 */
function formatDocumentContent(body) {
  if (typeof body === "string") return body;
  if (body === null || body === undefined) return "没有正文内容。";
  try {
    return JSON.stringify(body, null, 2);
  } catch {
    return "无法显示此项资料。";
  }
}

/**
 * 依赖：服务端document_type值。
 * 输入：资料类型。
 * 输出：短中文类型标签。
 * 实现：映射常见类型，其它类型仅作为文本显示。
 */
function documentTypeLabel(documentType) {
  const labels = { canon: "设定", history: "章节", summary: "总结笔记", outline: "大纲" };
  return labels[documentType] || String(documentType || "资料");
}

/**
 * 依赖：资料编辑dirty标记、source_ref、revision和两类作者操作按钮。
 * 输入：无。
 * 输出：无。
 * 实现：仅允许Canon/summary纯文本保存，History只显示显式修改入口。
 */
function updateDocumentActions() {
  const sourceHash = workspace.documentSourceRef && workspace.documentSourceRef.source_hash;
  dom.saveDocumentButton.hidden = !workspace.documentEditable;
  dom.saveDocumentButton.disabled = !workspace.documentEditable || !workspace.documentDirty
    || workspace.documentSaving || workspace.documentExpectedRevision === null
    || workspace.documentExpectedRevision === undefined || typeof sourceHash !== "string";
  const canRevise = workspace.activeDocumentType === "history" && Boolean(workspace.documentSourceRef);
  dom.reviseDocumentButton.hidden = !canRevise;
  dom.reviseDocumentButton.disabled = !canRevise;
}

/**
 * 依赖：资料textarea、服务器基线和未保存草稿缓存。
 * 输入：资料正文input事件。
 * 输出：无。
 * 实现：只更新作者本地dirty状态，不触发模型或立即写入资料。
 */
function onDocumentInput() {
  workspace.documentDirty = dom.documentEditor.value !== workspace.documentBaseline;
  cacheCurrentDocumentDraft();
  dom.documentStatus.textContent = workspace.documentDirty ? "资料有未保存修改。" : "资料与已保存版本一致。";
  updateDocumentActions();
}

/**
 * 依赖：documentSelect、受控资料列表和当前scope。
 * 输入：资料选择change事件。
 * 输出：Promise<void>；载入当前scope的所选资料。
 * 实现：先缓存切换前编辑，再用scope及选择序号防止迟到资料替换新内容。
 */
async function onDocumentSelection() {
  const scope = selectedResourceScope();
  const documentId = dom.documentSelect.value;
  if (!documentId || (workspace.reviseBaseRef && workspace.reviseBaseRef.document_id !== documentId)) {
    workspace.reviseBaseRef = null;
    dom.reviseDocumentStatus.hidden = true;
  }
  if (!documentId) return;
  workspace.documentSelections.set(scope.key, documentId);
  await loadDocumentDetail(scope, documentId, workspace.resourceLoadSeq);
}

/**
 * 依赖：PUT /documents/{id}及当前资料双CAS。
 * 输入：无；保存Canon或summary正文字符串。
 * 输出：Promise<void>；成功更新基线，冲突时保留作者输入。
 * 实现：绑定原scope/source hash/revision，并丢弃切换scope或资料后的迟到响应。
 */
async function saveDocument() {
  const scope = selectedResourceScope();
  const documentId = workspace.activeDocumentId;
  if (!workspace.documentEditable || !workspace.documentDirty || workspace.documentSaving
      || !documentId || scope.key !== workspace.resourceScopeKey) return;
  const expectedRevision = workspace.documentExpectedRevision;
  const expectedSourceHash = workspace.documentSourceRef && workspace.documentSourceRef.source_hash;
  if (expectedRevision === null || expectedRevision === undefined || typeof expectedSourceHash !== "string") return;
  const content = dom.documentEditor.value;
  const requestSeq = workspace.resourceLoadSeq;
  const detailSeq = workspace.documentDetailSeq;
  workspace.documentSaving = true;
  updateDocumentActions();
  dom.documentStatus.textContent = "正在保存资料。";
  try {
    const result = await apiFetch(`/documents/${encodeURIComponent(documentId)}`, {
      method: "PUT",
      body: JSON.stringify({
        story_id: scope.storyId,
        timeline_id: scope.timelineId,
        expected_revision: expectedRevision,
        expected_source_hash: expectedSourceHash,
        content
      })
    });
    if (!isCurrentResourceRequest(scope, requestSeq, detailSeq)) return;
    const savedContent = extractEditableDocumentText(result.content) ?? content;
    workspace.documentBaseline = savedContent;
    workspace.documentExpectedRevision = result.document_revision ?? expectedRevision;
    workspace.documentSourceRef = result.source_ref || workspace.documentSourceRef;
    workspace.documentDirty = dom.documentEditor.value !== savedContent;
    cacheCurrentDocumentDraft();
    if (workspace.documentDirty) {
      dom.documentStatus.textContent = "已保存提交版本；你随后输入的修改仍保留。";
    } else {
      dom.documentEditor.value = savedContent;
      dom.documentStatus.textContent = `资料已保存 · 修订 ${String(workspace.documentExpectedRevision)}`;
    }
  } catch (error) {
    if (!isCurrentResourceRequest(scope, requestSeq, detailSeq)) return;
    workspace.documentDirty = true;
    cacheCurrentDocumentDraft();
    dom.documentStatus.textContent = error.httpStatus === 409
      ? "资料版本已改变；你的输入已保留。请复制修改后再重新读取和核对。"
      : `保存资料失败；你的输入已保留。${error.message || ""}`;
  } finally {
    workspace.documentSaving = false;
    updateDocumentActions();
  }
}

/**
 * 依赖：当前History详情、source_ref与修改任务单选项。
 * 输入：无；由“修改此章节”按钮触发。
 * 输出：无。
 * 实现：保留原DocumentRef为start的base_ref，不复制正文或另造来源hash。
 */
function prepareHistoryRevision() {
  if (workspace.activeDocumentType !== "history" || !workspace.documentSourceRef
      || workspace.resourceScopeKey !== selectedResourceScope().key) return;
  workspace.reviseBaseRef = workspace.documentSourceRef;
  for (const input of document.querySelectorAll('input[name="task_kind"]')) {
    input.checked = input.value === "revise";
  }
  dom.reviseDocumentStatus.textContent = "已选定此章节的当前版本作为修改基线；请填写修改要求后开始。";
  dom.reviseDocumentStatus.hidden = false;
  document.dispatchEvent(new CustomEvent("workspace:navigate", { detail: { view: "write", focusId: "requestInput" } }));
  dom.requestInput.focus();
}

/**
 * 依赖：既有request_snapshot、原输入框与用户修改标记。
 * 输入：当前run快照。
 * 输出：首次恢复原始大纲/要求；已输入内容保留。
 * 实现：每run只恢复一次，快照轮询和隐藏面板不覆盖作者新输入。
 */
function restoreAuthorInputs(snapshot) {
  if (workspace.inputRestoreRunId === snapshot.run_id) return;
  workspace.inputRestoreRunId = snapshot.run_id;
  const inputs = snapshot.request_snapshot || {};
  if (!workspace.outlineInputTouched && typeof inputs.outline === "string") dom.outlineInput.value = inputs.outline;
  if (!workspace.requestInputTouched && typeof inputs.request === "string") dom.requestInput.value = inputs.request;
}

/**
 * 依赖：原大纲/要求输入框和用户修改标记。
 * 输入：input事件。
 * 输出：记录作者已编辑的字段。
 * 实现：启动/恢复慢响应期间保留用户输入，不新增持久化或复制草稿状态。
 */
function onAuthorInput(event) {
  if (event.target === dom.outlineInput) workspace.outlineInputTouched = true;
  if (event.target === dom.requestInput) workspace.requestInputTouched = true;
  persistLocalInputs();
}

/**
 * 依赖：本轮task_kind单选项与已选History基线。
 * 输入：task_kind change事件。
 * 输出：无。
 * 实现：作者切离修改模式时清除未提交的History基线，避免误绑定到新创作。
 */
function onTaskKindChange() {
  if (selectedTaskKind() !== "revise") {
    workspace.reviseBaseRef = null;
    dom.reviseDocumentStatus.hidden = true;
  }
  persistLocalInputs();
}

/**
 * 依赖：正文 textarea、已保存基线和编辑状态提示。
 * 输入：正文 input 事件。
 * 输出：无。
 * 实现：只比较当前文本与持久基线，以 dirty 标记阻止迟到快照覆盖编辑。
 */
function onDraftInput() {
  workspace.draftDirty = dom.draftEditor.value !== workspace.draftBaseline;
  dom.draftEditState.textContent = workspace.draftDirty ? "有未保存的正文修改。" : "正文与已保存草稿一致。";
  persistLocalInputs();
}

/**
 * 依赖：卷/章/场输入框和coordinateDirty标记。
 * 输入：任一坐标框的input事件。
 * 输出：无。
 * 实现：记录作者已手动调整坐标，后续快照不再覆盖该选择。
 */
function onCoordinateInput() {
  workspace.coordinateDirty = true;
  persistLocalInputs();
}

/**
 * 依赖：window load、页面节点、MutationObserver与bootstrap。
 * 输入：无。
 * 输出：无。
 * 实现：绑定具名事件处理器及按需面板观察，再启动本地工作区恢复。
 */
function initializeWorkspace() {
  cacheDom();
  initializeLocalWriter();
  dom.runForm.addEventListener("submit", onStartSubmit);
  dom.outlineInput.addEventListener("input", onAuthorInput);
  dom.requestInput.addEventListener("input", onAuthorInput);
  dom.driverSelect.addEventListener("change", onDriverChange);
  dom.feedbackButton.addEventListener("click", submitFeedback);
  dom.cancelButton.addEventListener("click", cancelRun);
  dom.harnessContextButton.addEventListener("click", loadHarnessContext);
  dom.memoryQueryForm.addEventListener("submit", refreshMemory);
  dom.moreMemoryButton.addEventListener("click", continueMemory);
  new MutationObserver(observeMemorySurface).observe(dom.memorySurface, { attributes: true, attributeFilter: ["hidden"] });
  new MutationObserver(observeResourceSurface).observe(dom.resourcesSurface, { attributes: true, attributeFilter: ["hidden"] });
  dom.resourcesPanel.addEventListener("toggle", observeResourceSurface);
  dom.saveDraftButton.addEventListener("click", saveDraft);
  dom.adoptButton.addEventListener("click", adoptDraft);
  dom.generatedDraftButton.addEventListener("click", toggleGeneratedDraft);
  dom.saveReceivedButton.addEventListener("click", saveReceivedTextAsDraft);
  dom.storySelect.addEventListener("change", onStoryChange);
  dom.timelineSelect.addEventListener("change", onScopeChange);
  dom.profileSelect.addEventListener("change", onScopeChange);
  dom.preferencesEditor.addEventListener("input", onPreferencesInput);
  dom.savePreferencesButton.addEventListener("click", savePreferences);
  dom.reloadDocumentsButton.addEventListener("click", reloadScopedResources);
  dom.documentSelect.addEventListener("change", onDocumentSelection);
  dom.documentEditor.addEventListener("input", onDocumentInput);
  dom.saveDocumentButton.addEventListener("click", saveDocument);
  dom.reviseDocumentButton.addEventListener("click", prepareHistoryRevision);
  dom.draftEditor.addEventListener("input", onDraftInput);
  dom.volumeInput.addEventListener("input", onCoordinateInput);
  dom.chapterInput.addEventListener("input", onCoordinateInput);
  dom.sceneInput.addEventListener("input", onCoordinateInput);
  dom.restoreLocalDraftButton.addEventListener("click", restoreLocalDraft);
  dom.localArchivePanel.addEventListener("toggle", renderLocalArchive);
  dom.localCopySelect.addEventListener("change", showLocalArchiveCopy);
  dom.setupButton.addEventListener("click", showSetupDialog);
  dom.closeSetupButton.addEventListener("click", closeSetupDialog);
  dom.useHarnessButton.addEventListener("click", chooseHarness);
  dom.refreshProfilesButton.addEventListener("click", refreshProfiles);
  dom.newStoryButton.addEventListener("click", showNewStoryDialog);
  dom.closeNewStoryButton.addEventListener("click", closeNewStoryDialog);
  dom.createStoryForm.addEventListener("submit", createStory);
  window.addEventListener("beforeunload", protectPageExit);
  window.addEventListener("pagehide", persistLocalInputs);
  for (const input of document.querySelectorAll('input[name="task_kind"]')) {
    input.addEventListener("change", onTaskKindChange);
  }
  startWorkspace();
}

document.addEventListener("DOMContentLoaded", initializeWorkspace);
