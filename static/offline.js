(function () {
  const DB_NAME = "mice-manage-offline";
  const DB_VERSION = 1;
  const META_STORE = "meta";
  const QUEUE_STORE = "queue";
  const DRAFT_KEY = "offline_form_draft";
  const BOOTSTRAP_KEY = "bootstrap_cache";
  const BOOTSTRAP_TIME_KEY = "bootstrap_cached_at";

  const ACTION_LABELS = {
    add_usage_record: "新增操作记录",
    add_birth_record: "新增新生鼠登记",
    update_birth_processing: "补填新生鼠处理",
    update_cage_fields: "更新笼位字段",
    create_cage: "新增笼位",
  };

  function readJsonScript(id, fallback) {
    const element = document.getElementById(id);
    if (!element || !element.textContent.trim()) {
      return fallback;
    }
    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      console.error("Failed to parse json script:", id, error);
      return fallback;
    }
  }

  function emptyBootstrap() {
    return {
      generated_at: null,
      users: [],
      rooms: [],
      cages: [],
      status_options: ["繁殖", "实验"],
      action_options: ["查看", "取用", "归还", "补笼", "换笼", "清笼", "备注"],
    };
  }

  const bootstrapData = readJsonScript("bootstrap-data", emptyBootstrap());
  const offlineOperatorData = readJsonScript("offline-operator-data", null);
  const offlineConfig = readJsonScript("offline-config", {
    mode: "server",
    api_base_url: "",
  });

  const state = {
    serverBootstrap: bootstrapData,
    bootstrap: bootstrapData,
    queueItems: [],
    queueFilter: "all",
    searchKeyword: "",
  };

  const networkStatusEl = document.getElementById("network-status");
  const serverStatusEl = document.getElementById("server-status");
  const noticeBannerEl = document.getElementById("notice-banner");
  const syncSummaryEl = document.getElementById("sync-summary");
  const queueListEl = document.getElementById("queue-list");
  const cageCacheListEl = document.getElementById("cage-cache-list");
  const cacheTimeEl = document.getElementById("cache-time");
  const importBootstrapButtonEl = document.getElementById("import-bootstrap-button");
  const bootstrapFileInputEl = document.getElementById("bootstrap-file-input");

  const statCagesEl = document.getElementById("stat-cages");
  const statPendingEl = document.getElementById("stat-pending");
  const statFailedEl = document.getElementById("stat-failed");
  const statCacheTimeEl = document.getElementById("stat-cache-time");

  const formEl = document.getElementById("offline-form");
  const operatorNameEl = document.getElementById("operator-name");
  const operatorDisplayEl = document.getElementById("operator-display");
  const actionTypeEl = document.getElementById("action-type");
  const cageCodeEl = document.getElementById("cage-code");
  const existingCageFieldsEl = document.getElementById("existing-cage-fields");
  const offlineRoomFilterEl = document.getElementById("offline-room-filter");
  const offlineCageSearchEl = document.getElementById("offline-cage-search");
  const selectedCageEl = document.getElementById("selected-cage");
  const cageSearchEl = document.getElementById("cage-search");

  const usageFieldsEl = document.getElementById("usage-fields");
  const recordActionEl = document.getElementById("record-action");
  const recordPurposeEl = document.getElementById("record-purpose");
  const recordNoteEl = document.getElementById("record-note");

  const birthFieldsEl = document.getElementById("birth-fields");
  const birthDateEl = document.getElementById("birth-date");
  const birthCountEl = document.getElementById("birth-count");
  const birthCodesEl = document.getElementById("birth-codes");
  const birthNoteEl = document.getElementById("birth-note");

  const processingFieldsEl = document.getElementById("processing-fields");
  const birthRecordIdEl = document.getElementById("birth-record-id");
  const processingTextEl = document.getElementById("processing-text");

  const updateFieldsEl = document.getElementById("update-fields");
  const legacyUpdateStrainEl = document.getElementById("update-strain");
  const updateMaleGenotypeEl =
    document.getElementById("update-male-genotype") || legacyUpdateStrainEl;
  const updateFemaleGenotypeEl = document.getElementById("update-female-genotype");
  const updateMaleCodeEl = document.getElementById("update-male-code");
  const updateFemaleCodeEl = document.getElementById("update-female-code");
  const updateSetupDateEl = document.getElementById("update-setup-date");
  const updateRoomNameEl = document.getElementById("update-room-name");
  const updateRackNameEl = document.getElementById("update-rack-name");
  const updateStatusEl = document.getElementById("update-status");
  const updateNoteEl = document.getElementById("update-note");

  const createFieldsEl = document.getElementById("create-fields");
  const createCageCodeEl = document.getElementById("create-cage-code");
  const createRoomNameEl = document.getElementById("create-room-name");
  const createRackNameEl = document.getElementById("create-rack-name");
  const createOwnerSelectWrapEl = document.getElementById(
    "create-owner-select-wrap"
  );
  const createOwnerFixedWrapEl = document.getElementById(
    "create-owner-fixed-wrap"
  );
  const createOwnerIdEl = document.getElementById("create-owner-id");
  const createOwnerFixedEl = document.getElementById("create-owner-fixed");
  const legacyCreateStrainEl = document.getElementById("create-strain");
  const createMaleGenotypeEl =
    document.getElementById("create-male-genotype") || legacyCreateStrainEl;
  const createFemaleGenotypeEl = document.getElementById("create-female-genotype");
  const createMaleCodeEl = document.getElementById("create-male-code");
  const createFemaleCodeEl = document.getElementById("create-female-code");
  const createSetupDateEl = document.getElementById("create-setup-date");
  const createStatusEl = document.getElementById("create-status");
  const createNoteEl = document.getElementById("create-note");

  const saveButtonEl = document.getElementById("save-button");
  const syncButtonEl = document.getElementById("sync-button");
  const exportJsonButtonEl = document.getElementById("export-json-button");
  const retryFailedButtonEl = document.getElementById("retry-failed-button");
  const clearSyncedButtonEl = document.getElementById("clear-synced-button");
  const refreshButtonEl = document.getElementById("refresh-button");
  const clearDraftButtonEl = document.getElementById("clear-draft-button");

  function apiUrl(path) {
    const base = String(offlineConfig.api_base_url || "").replace(/\/$/, "");
    return base ? base + path : path;
  }

  function createId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "op-" + Date.now() + "-" + Math.floor(Math.random() * 100000);
  }

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function formatTime(value) {
    if (!value) {
      return "未记录";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString();
  }

  function statusLabel(value) {
    return ({ pending: "待同步", success: "已同步", failed: "失败" }[value] || value);
  }

  function actionTypeLabel(value) {
    return ACTION_LABELS[value] || value;
  }

  function sanitizeSyncMessage(value) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }

    const exact = {
      "鍚屾鎴愬姛": "同步成功",
      "????": "重复导入，已跳过",
      "??? JSON????????": "已导出 JSON，等待服务器导入",
    };
    if (exact[text]) {
      return exact[text];
    }

    if (text.startsWith("鏈壘鍒扮浣")) {
      return text.replace("鏈壘鍒扮浣", "未找到笼位");
    }
    if (text.startsWith("涓嶆敮鎸佺殑鍔ㄤ綔绫诲瀷")) {
      return text.replace("涓嶆敮鎸佺殑鍔ㄤ綔绫诲瀷", "不支持的动作类型");
    }

    return text;
  }

  function readFieldValue(element) {
    return element ? element.value : "";
  }

  function writeFieldValue(element, value) {
    if (element) {
      element.value = value || "";
    }
  }

  function currentUpdateMaleGenotypeValue() {
    return readFieldValue(updateMaleGenotypeEl);
  }

  function currentUpdateFemaleGenotypeValue() {
    return readFieldValue(updateFemaleGenotypeEl) || (updateFemaleGenotypeEl ? "" : readFieldValue(legacyUpdateStrainEl));
  }

  function currentCreateMaleGenotypeValue() {
    return readFieldValue(createMaleGenotypeEl);
  }

  function currentCreateFemaleGenotypeValue() {
    return readFieldValue(createFemaleGenotypeEl) || (createFemaleGenotypeEl ? "" : readFieldValue(legacyCreateStrainEl));
  }

  function splitSearchTerms(value) {
    return String(value || "")
      .replace(/，/g, " ")
      .replace(/,/g, " ")
      .split(/\s+/)
      .map((term) => term.trim().toLowerCase())
      .filter(Boolean);
  }

  function resolvedMaleGenotype(cage) {
    return cage.male_genotype || cage.strain || "";
  }

  function resolvedFemaleGenotype(cage) {
    return cage.female_genotype || cage.strain || "";
  }

  function showNotice(message, tone) {
    noticeBannerEl.textContent = message;
    noticeBannerEl.className = "notice-banner";
    noticeBannerEl.classList.add(tone || "info");
  }

  function hideNotice() {
    noticeBannerEl.className = "notice-banner hidden";
    noticeBannerEl.textContent = "";
  }

  function currentOperator() {
    return state.bootstrap.users.find((item) => item.name === operatorNameEl.value) || null;
  }

  function currentActionType() {
    return actionTypeEl.value;
  }

  function currentSelectedCage() {
    return state.bootstrap.cages.find((item) => item.cage_code === cageCodeEl.value) || null;
  }

  function setOptions(selectEl, items, mapper, allowEmptyLabel) {
    const previousValue = selectEl.value;
    selectEl.innerHTML = "";
    if (allowEmptyLabel) {
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = allowEmptyLabel;
      selectEl.appendChild(emptyOption);
    }
    items.forEach((item) => {
      const mapped = mapper(item);
      const option = document.createElement("option");
      option.value = mapped.value;
      option.textContent = mapped.label;
      selectEl.appendChild(option);
    });
    if ([...selectEl.options].some((option) => option.value === previousValue)) {
      selectEl.value = previousValue;
    }
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = function () {
        const db = request.result;
        if (!db.objectStoreNames.contains(META_STORE)) {
          db.createObjectStore(META_STORE, { keyPath: "key" });
        }
        if (!db.objectStoreNames.contains(QUEUE_STORE)) {
          db.createObjectStore(QUEUE_STORE, { keyPath: "op_id" });
        }
      };

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function withStore(storeName, mode, callback) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);
      const result = callback(store);
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  async function metaSet(key, value) {
    return withStore(META_STORE, "readwrite", (store) => {
      store.put({ key, value });
    });
  }

  async function metaGet(key) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(META_STORE, "readonly");
      const store = tx.objectStore(META_STORE);
      const request = store.get(key);
      request.onsuccess = () => resolve(request.result ? request.result.value : null);
      request.onerror = () => reject(request.error);
    });
  }

  async function metaDelete(key) {
    return withStore(META_STORE, "readwrite", (store) => {
      store.delete(key);
    });
  }

  async function queuePut(item) {
    return withStore(QUEUE_STORE, "readwrite", (store) => {
      store.put(item);
    });
  }

  async function queueDelete(opId) {
    return withStore(QUEUE_STORE, "readwrite", (store) => {
      store.delete(opId);
    });
  }

  async function queueList() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(QUEUE_STORE, "readonly");
      const store = tx.objectStore(QUEUE_STORE);
      const request = store.getAll();
      request.onsuccess = () => resolve(request.result || []);
      request.onerror = () => reject(request.error);
    });
  }

  function rebuildDerivedBootstrap() {
    const derived = deepClone(state.serverBootstrap);
    const activeItems = state.queueItems.filter((item) => item.sync_status !== "success");
    activeItems.forEach((item) => {
      applyQueueItemToBootstrap(derived, item);
    });
    state.bootstrap = derived;
  }

  function applyQueueItemToBootstrap(bootstrap, item) {
    const payload = item.payload || {};

    if (item.action_type === "create_cage") {
      const owner =
        bootstrap.users.find((user) => String(user.id) === String(payload.owner_user_id || "")) ||
        bootstrap.users.find((user) => user.name === payload.owner_name) ||
        bootstrap.users.find((user) => user.name === item.operator_name);

      if (!payload.cage_code || bootstrap.cages.some((cage) => cage.cage_code === payload.cage_code)) {
        return;
      }

      bootstrap.cages.unshift({
        id: "local-" + item.op_id,
        cage_code: payload.cage_code,
        strain:
          payload.strain ||
          [payload.male_genotype || "", payload.female_genotype || ""]
            .filter(Boolean)
            .join(" / "),
        male_genotype: payload.male_genotype || payload.strain || "",
        female_genotype: payload.female_genotype || payload.strain || "",
        status: payload.status || "",
        pup_count: Number(payload.pup_count || 0),
        owner_user_id: owner ? owner.id : "",
        owner: owner ? owner.name : item.operator_name,
        room_id: "",
        room: payload.room_name || "未填写房间",
        rack_id: "",
        rack: payload.rack_name || "未填写笼架",
        male_code: payload.male_code || "",
        female_code: payload.female_code || "",
        setup_date: payload.setup_date || "",
        birth_date: "",
        notes: payload.notes || "",
        updated_at: item.client_created_at,
        birth_records: [],
      });
      return;
    }

    const cage = bootstrap.cages.find((entry) => entry.cage_code === item.cage_code);
    if (!cage) {
      return;
    }

    if (item.action_type === "update_cage_fields") {
      cage.strain =
        payload.strain ||
        [payload.male_genotype || "", payload.female_genotype || ""]
          .filter(Boolean)
          .join(" / ");
      cage.male_genotype = payload.male_genotype || payload.strain || "";
      cage.female_genotype = payload.female_genotype || payload.strain || "";
      cage.male_code = payload.male_code || "";
      cage.female_code = payload.female_code || "";
      cage.setup_date = payload.setup_date || "";
      cage.room = payload.room_name || "未填写房间";
      cage.rack = payload.rack_name || "未填写笼架";
      cage.status = payload.status || "";
      cage.notes = payload.notes || "";
      cage.updated_at = item.client_created_at;
      return;
    }

    if (item.action_type === "add_birth_record") {
      cage.birth_date = payload.birth_date || cage.birth_date;
      cage.pup_count = Number(cage.pup_count || 0) + Number(payload.count || 0);
      cage.updated_at = item.client_created_at;
      cage.birth_records = cage.birth_records || [];
      cage.birth_records.unshift({
        id: "local-birth-" + item.op_id,
        created_at: item.client_created_at,
        operator: item.operator_name,
        birth_date: payload.birth_date || "-",
        count: Number(payload.count || 0),
        codes: payload.codes || "-",
        processing: "-",
        note: payload.note || "",
      });
      return;
    }

    if (item.action_type === "update_birth_processing") {
      const target = (cage.birth_records || []).find(
        (record) => String(record.id) === String(payload.birth_record_id || "")
      );
      if (target) {
        target.processing = payload.processing || "-";
      }
    }
  }

  function filteredCages() {
    const terms = splitSearchTerms(state.searchKeyword);
    if (!terms.length) {
      return state.bootstrap.cages;
    }
    return state.bootstrap.cages.filter((cage) => {
      const haystack = [
        cage.cage_code,
        cage.strain,
        cage.male_genotype,
        cage.female_genotype,
        cage.owner,
        cage.status,
        cage.room,
        cage.rack,
      ]
        .filter(Boolean)
        .map((value) => String(value).toLowerCase());
      return terms.every((term) =>
        haystack.some((value) => value.includes(term))
      );
    });
  }

  function renderSelectedCage() {
    if (currentActionType() === "create_cage") {
      selectedCageEl.innerHTML =
        "<p class='muted'>当前是新增笼位模式，保存后会先加入本地缓存并等待同步。</p>";
      return;
    }

    const cage = currentSelectedCage();
    if (!cage) {
      selectedCageEl.innerHTML = "<p class='muted'>请选择笼位查看缓存信息。</p>";
      return;
    }

    const birthRecords = (cage.birth_records || [])
      .slice(0, 3)
      .map(
        (record) =>
          "<div class='info-box compact-box'><strong>" +
          (record.birth_date || "-") +
          "</strong><p>数量：" +
          Number(record.count || 0) +
          "</p><p>处理：" +
          (record.processing || "-") +
          "</p></div>"
      )
      .join("");

    selectedCageEl.innerHTML =
      "<div class='card-top'><div><h3>" +
      cage.cage_code +
      "</h3><p>" +
      "父 " +
      (resolvedMaleGenotype(cage) || "-") +
      " / 母 " +
      (resolvedFemaleGenotype(cage) || "-") +
      "</p></div><span class='status-badge'>" +
      (cage.status || "未填写状态") +
      "</span></div>" +
      "<dl class='detail-grid compact-grid'>" +
      "<div><dt>房间</dt><dd>" +
      (cage.room || "未填写房间") +
      "</dd></div>" +
      "<div><dt>笼架</dt><dd>" +
      (cage.rack || "未填写笼架") +
      "</dd></div>" +
      "<div><dt>负责人</dt><dd>" +
      (cage.owner || "未填写负责人") +
      "</dd></div>" +
      "<div><dt>父本基因型</dt><dd>" +
      (resolvedMaleGenotype(cage) || "-") +
      "</dd></div>" +
      "<div><dt>母本基因型</dt><dd>" +
      (resolvedFemaleGenotype(cage) || "-") +
      "</dd></div>" +
      "<div><dt>当前仔鼠数</dt><dd>" +
      Number(cage.pup_count || 0) +
      "</dd></div>" +
      "<div><dt>父本编号-DOB</dt><dd>" +
      (cage.male_code || "-") +
      "</dd></div>" +
      "<div><dt>母本编号-DOB</dt><dd>" +
      (cage.female_code || "-") +
      "</dd></div>" +
      "<div><dt>合笼日期</dt><dd>" +
      (cage.setup_date || "-") +
      "</dd></div>" +
      "<div><dt>备注</dt><dd>" +
      (cage.notes || "暂无备注") +
      "</dd></div>" +
      "</dl>" +
      "<p class='muted'>最近服务器更新时间：" +
      formatTime(cage.updated_at) +
      "</p>" +
      (birthRecords
        ? "<div class='birth-preview-list'><h3>最近新生鼠记录</h3>" + birthRecords + "</div>"
        : "");
  }

  function renderCages(cachedAt) {
    const cages = filteredCages();
    cacheTimeEl.textContent = cachedAt ? "缓存于 " + cachedAt : "尚未缓存";
    cageCacheListEl.innerHTML = "";

    if (!cages.length) {
      cageCacheListEl.innerHTML = "<p class='muted'>没有匹配到笼位。</p>";
      return;
    }

    cages.forEach((cage) => {
      const card = document.createElement("article");
      card.className = "cage-card";
      card.innerHTML =
        "<div class='card-top'><div><h2>" +
        cage.cage_code +
        "</h2><p>" +
        "父 " +
        (resolvedMaleGenotype(cage) || "-") +
        " / 母 " +
        (resolvedFemaleGenotype(cage) || "-") +
        "</p></div><span class='status-badge'>" +
        (cage.status || "未填写状态") +
        "</span></div>" +
        "<dl class='meta-grid'>" +
        "<div><dt>房间</dt><dd>" +
        (cage.room || "未填写房间") +
        "</dd></div>" +
        "<div><dt>笼架</dt><dd>" +
        (cage.rack || "未填写笼架") +
        "</dd></div>" +
        "<div><dt>负责人</dt><dd>" +
        (cage.owner || "未填写负责人") +
        "</dd></div>" +
        "<div><dt>仔鼠数</dt><dd>" +
        Number(cage.pup_count || 0) +
        "</dd></div>" +
        "</dl><p class='notes'>" +
        (cage.notes || "暂无备注") +
        "</p>";
      cageCacheListEl.appendChild(card);
    });
  }

  function queueStats(items) {
    return {
      pending: items.filter((item) => item.sync_status === "pending").length,
      failed: items.filter((item) => item.sync_status === "failed").length,
      success: items.filter((item) => item.sync_status === "success").length,
    };
  }

  function updateSummary(cachedAt) {
    const stats = queueStats(state.queueItems);
    statCagesEl.textContent = String(state.bootstrap.cages.length);
    statPendingEl.textContent = String(stats.pending);
    statFailedEl.textContent = String(stats.failed);
    statCacheTimeEl.textContent = cachedAt || "未缓存";
    syncSummaryEl.textContent =
      "待同步 " +
      stats.pending +
      " 条 / 失败 " +
      stats.failed +
      " 条 / 已同步 " +
      stats.success +
      " 条";
    retryFailedButtonEl.disabled = stats.failed === 0;
    clearSyncedButtonEl.disabled = stats.success === 0;
    syncButtonEl.disabled = stats.pending === 0;
  }

  function queuePayloadSummary(item) {
    const payload = item.payload || {};
    if (item.action_type === "create_cage") {
      return "笼位 " + (payload.cage_code || "") + " / 房间 " + (payload.room_name || "未填写");
    }
    if (item.action_type === "add_birth_record") {
      return "出生日期 " + (payload.birth_date || "-") + " / 数量 " + Number(payload.count || 0);
    }
    if (item.action_type === "update_birth_processing") {
      return "处理：" + (payload.processing || "-");
    }
    if (item.action_type === "update_cage_fields") {
      return "状态 " + (payload.status || "未填写") + " / 房间 " + (payload.room_name || "未填写");
    }
    return "动作 " + (payload.action || "备注") + " / 用途 " + (payload.purpose || "未填写");
  }

  function renderQueue() {
    const sorted = [...state.queueItems].sort((a, b) =>
      (b.client_created_at || "").localeCompare(a.client_created_at || "")
    );
    const filtered =
      state.queueFilter === "all"
        ? sorted
        : sorted.filter((item) => item.sync_status === state.queueFilter);

    queueListEl.innerHTML = "";
    if (!filtered.length) {
      queueListEl.innerHTML = "<p class='muted'>当前筛选条件下没有记录。</p>";
      return;
    }

    filtered.forEach((item) => {
      const block = document.createElement("div");
      block.className = "timeline-item";
      block.innerHTML =
        "<div class='timeline-head'><strong>" +
        (item.cage_code || "未指定笼位") +
        " / " +
        actionTypeLabel(item.action_type) +
        "</strong><div class='timeline-head-actions'><span class='queue-status queue-" +
        item.sync_status +
        "'>" +
        statusLabel(item.sync_status) +
        "</span><button type='button' class='queue-delete-button' data-op-id='" +
        item.op_id +
        "' aria-label='删除这条待同步记录'>X</button></div></div><p>" +
        queuePayloadSummary(item) +
        "</p><p class='muted'>操作人 " +
        item.operator_name +
        " | 时间 " +
        formatTime(item.client_created_at) +
        "</p>" +
        (item.sync_message ? "<p class='muted'>同步结果：" + sanitizeSyncMessage(item.sync_message) + "</p>" : "");
      queueListEl.appendChild(block);
    });
  }

  async function deleteQueueItem(opId) {
    if (!opId) {
      return;
    }
    await queueDelete(opId);
    await refreshQueueState();
    showNotice("已删除这条待同步记录。", "success");
  }

  async function saveBootstrap(payload) {
    await metaSet(BOOTSTRAP_KEY, payload);
    await metaSet(BOOTSTRAP_TIME_KEY, new Date().toLocaleString());
  }

  async function loadCachedBootstrap() {
    const cached = await metaGet(BOOTSTRAP_KEY);
    const cachedAt = await metaGet(BOOTSTRAP_TIME_KEY);
    if (!cached) {
      return null;
    }
    return { cached, cachedAt };
  }

  async function refreshBootstrapFromServer() {
    if (offlineConfig.mode === "export-only") {
      throw new Error("当前是静态离线模式，请导入基础数据 JSON。");
    }
    const response = await fetch(apiUrl("/api/bootstrap"), { cache: "no-store" });
    if (!response.ok) {
      throw new Error("无法获取服务器基础数据");
    }
    const data = await response.json();
    state.serverBootstrap = data;
    await saveBootstrap(data);
    rebuildDerivedBootstrap();
    return data;
  }

  async function detectServer() {
    if (offlineConfig.mode === "export-only") {
      serverStatusEl.textContent = "静态离线模式";
      serverStatusEl.className = "user-chip";
      return false;
    }
    try {
      const response = await fetch(apiUrl("/health"), { cache: "no-store" });
      if (!response.ok) {
        throw new Error("服务器不可用");
      }
      serverStatusEl.textContent = "服务器可连接";
      serverStatusEl.className = "user-chip server-ok";
      return true;
    } catch (error) {
      serverStatusEl.textContent = "服务器不可连接";
      serverStatusEl.className = "user-chip server-bad";
      return false;
    }
  }

  function updateNetworkStatus() {
    if (navigator.onLine) {
      networkStatusEl.textContent = "设备当前在线";
      networkStatusEl.className = "status-badge network-online";
    } else {
      networkStatusEl.textContent = "设备当前离线";
      networkStatusEl.className = "status-badge network-offline";
    }
  }

  function syncFormVisibility() {
    const actionType = currentActionType();
    const usesExistingCage = actionType !== "create_cage";
    existingCageFieldsEl.classList.toggle("hidden", !usesExistingCage);
    usageFieldsEl.classList.toggle("hidden", actionType !== "add_usage_record");
    birthFieldsEl.classList.toggle("hidden", actionType !== "add_birth_record");
    processingFieldsEl.classList.toggle("hidden", actionType !== "update_birth_processing");
    updateFieldsEl.classList.toggle("hidden", actionType !== "update_cage_fields");
    createFieldsEl.classList.toggle("hidden", actionType !== "create_cage");

    const operator = currentOperator();
    const adminMode = actionType === "create_cage" && operator && operator.role === "admin";
    const ownerMode = actionType === "create_cage" && operator && operator.role === "owner";
    createOwnerSelectWrapEl.classList.toggle("hidden", !adminMode);
    createOwnerFixedWrapEl.classList.toggle("hidden", !ownerMode);
    if (ownerMode) {
      createOwnerFixedEl.value = operator.name;
    }
  }

  function populateBirthRecordOptions() {
    const cage = currentSelectedCage();
    const birthRecords = cage
      ? (cage.birth_records || []).filter((item) => /^\d+$/.test(String(item.id)))
      : [];
    setOptions(
      birthRecordIdEl,
      birthRecords,
      (item) => ({
        value: String(item.id),
        label:
          (item.birth_date || "-") +
          " / 数量 " +
          Number(item.count || 0) +
          " / 处理 " +
          (item.processing || "-"),
      }),
      "请选择新生鼠记录"
    );
  }

  function prefillUpdateFields() {
    const cage = currentSelectedCage();
    if (!cage || currentActionType() !== "update_cage_fields") {
      return;
    }
    writeFieldValue(updateMaleGenotypeEl, resolvedMaleGenotype(cage));
    writeFieldValue(updateFemaleGenotypeEl, resolvedFemaleGenotype(cage));
    updateMaleCodeEl.value = cage.male_code || "";
    updateFemaleCodeEl.value = cage.female_code || "";
    updateSetupDateEl.value = cage.setup_date || "";
    updateRoomNameEl.value = cage.room || "";
    updateRackNameEl.value = cage.rack || "";
    updateStatusEl.value = cage.status || "";
    updateNoteEl.value = cage.notes || "";
  }

  function currentDraft() {
    return {
      operator_name: operatorNameEl.value,
      action_type: actionTypeEl.value,
      offline_room_filter: offlineRoomFilterEl.value,
      offline_cage_search: offlineCageSearchEl.value,
      cage_code: cageCodeEl.value,
      record_action: recordActionEl.value,
      record_purpose: recordPurposeEl.value,
      record_note: recordNoteEl.value,
      birth_date: birthDateEl.value,
      birth_count: birthCountEl.value,
      birth_codes: birthCodesEl.value,
      birth_note: birthNoteEl.value,
      birth_record_id: birthRecordIdEl.value,
      processing_text: processingTextEl.value,
      update_male_genotype: currentUpdateMaleGenotypeValue(),
      update_female_genotype: currentUpdateFemaleGenotypeValue(),
      update_male_code: updateMaleCodeEl.value,
      update_female_code: updateFemaleCodeEl.value,
      update_setup_date: updateSetupDateEl.value,
      update_room_name: updateRoomNameEl.value,
      update_rack_name: updateRackNameEl.value,
      update_status: updateStatusEl.value,
      update_note: updateNoteEl.value,
      create_cage_code: createCageCodeEl.value,
      create_room_name: createRoomNameEl.value,
      create_rack_name: createRackNameEl.value,
      create_owner_id: createOwnerIdEl.value,
      create_male_genotype: currentCreateMaleGenotypeValue(),
      create_female_genotype: currentCreateFemaleGenotypeValue(),
      create_male_code: createMaleCodeEl.value,
      create_female_code: createFemaleCodeEl.value,
      create_setup_date: createSetupDateEl.value,
      create_status: createStatusEl.value,
      create_note: createNoteEl.value,
    };
  }

  async function saveDraft() {
    await metaSet(DRAFT_KEY, currentDraft());
  }

  async function restoreDraft() {
    const draft = await metaGet(DRAFT_KEY);
    if (!draft) {
      return;
    }

    operatorNameEl.value = draft.operator_name || operatorNameEl.value;
    actionTypeEl.value = draft.action_type || actionTypeEl.value;
    syncFormVisibility();
    offlineRoomFilterEl.value = draft.offline_room_filter || offlineRoomFilterEl.value;
    offlineCageSearchEl.value = draft.offline_cage_search || "";
    await refreshOfflineCageSelect();
    cageCodeEl.value = draft.cage_code || cageCodeEl.value;
    recordActionEl.value = draft.record_action || recordActionEl.value;
    recordPurposeEl.value = draft.record_purpose || "";
    recordNoteEl.value = draft.record_note || "";
    birthDateEl.value = draft.birth_date || "";
    birthCountEl.value = draft.birth_count || "0";
    birthCodesEl.value = draft.birth_codes || "";
    birthNoteEl.value = draft.birth_note || "";
    populateBirthRecordOptions();
    birthRecordIdEl.value = draft.birth_record_id || birthRecordIdEl.value;
    processingTextEl.value = draft.processing_text || "";
    writeFieldValue(updateMaleGenotypeEl, draft.update_male_genotype || "");
    writeFieldValue(updateFemaleGenotypeEl, draft.update_female_genotype || "");
    updateMaleCodeEl.value = draft.update_male_code || "";
    updateFemaleCodeEl.value = draft.update_female_code || "";
    updateSetupDateEl.value = draft.update_setup_date || "";
    updateRoomNameEl.value = draft.update_room_name || "";
    updateRackNameEl.value = draft.update_rack_name || "";
    updateStatusEl.value = draft.update_status || updateStatusEl.value;
    updateNoteEl.value = draft.update_note || "";
    createCageCodeEl.value = draft.create_cage_code || "";
    createRoomNameEl.value = draft.create_room_name || "";
    createRackNameEl.value = draft.create_rack_name || "";
    createOwnerIdEl.value = draft.create_owner_id || createOwnerIdEl.value;
    writeFieldValue(createMaleGenotypeEl, draft.create_male_genotype || "");
    writeFieldValue(createFemaleGenotypeEl, draft.create_female_genotype || "");
    createMaleCodeEl.value = draft.create_male_code || "";
    createFemaleCodeEl.value = draft.create_female_code || "";
    createSetupDateEl.value = draft.create_setup_date || "";
    createStatusEl.value = draft.create_status || createStatusEl.value;
    createNoteEl.value = draft.create_note || "";
  }

  async function clearDraft() {
    formEl.reset();
    birthCountEl.value = "0";
    await metaDelete(DRAFT_KEY);
    syncFormVisibility();
    populateBirthRecordOptions();
    renderSelectedCage();
    showNotice("表单草稿已清空。", "info");
  }

  async function refreshQueueState() {
    state.queueItems = (await queueList()).map((item) => ({
      ...item,
      sync_message: sanitizeSyncMessage(item.sync_message),
    }));
    rebuildDerivedBootstrap();
    await initializeBootstrapOptions();
    populateBirthRecordOptions();
    const cachedAt = (await metaGet(BOOTSTRAP_TIME_KEY)) || "未缓存";
    updateSummary(cachedAt);
    renderQueue();
    renderSelectedCage();
    renderCages(cachedAt);
  }

  function buildQueueItem() {
    const operator = currentOperator();
    if (!operator) {
      throw new Error("请选择操作人");
    }

    const actionType = currentActionType();
    const item = {
      op_id: createId(),
      action_type: actionType,
      cage_code: "",
      operator_name: operator.name,
      payload: {},
      client_created_at: new Date().toISOString(),
      sync_status: "pending",
      sync_message: "等待同步",
    };

    if (actionType === "create_cage") {
      const cageCode = createCageCodeEl.value.trim().toUpperCase();
      if (!cageCode) {
        throw new Error("新增笼位时必须填写笼位编号");
      }
      item.cage_code = cageCode;
      item.payload = {
        cage_code: cageCode,
        room_name: createRoomNameEl.value.trim(),
        rack_name: createRackNameEl.value.trim(),
        owner_user_id: operator.role === "admin" ? createOwnerIdEl.value : String(operator.id),
        owner_name:
          operator.role === "admin"
            ? (
                state.bootstrap.users.find(
                  (user) => String(user.id) === String(createOwnerIdEl.value)
                ) || {}
              ).name || ""
            : operator.name,
        male_genotype: currentCreateMaleGenotypeValue().trim(),
        female_genotype: currentCreateFemaleGenotypeValue().trim(),
        male_code: createMaleCodeEl.value.trim(),
        female_code: createFemaleCodeEl.value.trim(),
        setup_date: createSetupDateEl.value,
        status: createStatusEl.value,
        notes: createNoteEl.value.trim(),
        pup_count: 0,
      };
      return item;
    }

    const cage = currentSelectedCage();
    if (!cage) {
      throw new Error("请选择笼位");
    }
    item.cage_code = cage.cage_code;

    if (actionType === "add_usage_record") {
      item.payload = {
        action: recordActionEl.value,
        purpose: recordPurposeEl.value.trim(),
        note: recordNoteEl.value.trim(),
      };
      return item;
    }

    if (actionType === "add_birth_record") {
      item.payload = {
        birth_date: birthDateEl.value,
        count: Number(birthCountEl.value || 0),
        codes: birthCodesEl.value.trim(),
        note: birthNoteEl.value.trim(),
      };
      return item;
    }

    if (actionType === "update_birth_processing") {
      if (!birthRecordIdEl.value) {
        throw new Error("请选择要补填处理的新生鼠记录");
      }
      item.payload = {
        birth_record_id: birthRecordIdEl.value,
        processing: processingTextEl.value.trim(),
      };
      return item;
    }

    item.payload = {
      base_updated_at: cage.updated_at || "",
      male_genotype: currentUpdateMaleGenotypeValue().trim(),
      female_genotype: currentUpdateFemaleGenotypeValue().trim(),
      male_code: updateMaleCodeEl.value.trim(),
      female_code: updateFemaleCodeEl.value.trim(),
      setup_date: updateSetupDateEl.value,
      room_name: updateRoomNameEl.value.trim(),
      rack_name: updateRackNameEl.value.trim(),
      status: updateStatusEl.value,
      notes: updateNoteEl.value.trim(),
    };
    return item;
  }

  async function syncPending() {
    if (offlineConfig.mode === "export-only") {
      showNotice("当前是静态离线模式，请导出 JSON 后到服务器页面导入。", "warn");
      return;
    }
    const serverAvailable = await detectServer();
    if (!serverAvailable) {
      showNotice("当前无法连接服务器，暂时不能同步。", "error");
      return;
    }

    const pending = state.queueItems.filter((item) => item.sync_status === "pending");
    if (!pending.length) {
      showNotice("没有待同步记录。", "info");
      return;
    }

    const response = await fetch(apiUrl("/api/sync"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: pending }),
    });
    if (!response.ok) {
      showNotice("同步请求失败，请稍后重试。", "error");
      return;
    }

    const result = await response.json();
    const resultMap = new Map(result.results.map((entry) => [entry.op_id, entry]));

    for (const item of pending) {
      const syncResult = resultMap.get(item.op_id);
      if (!syncResult) {
        continue;
      }
      item.sync_status =
        syncResult.status === "success" || syncResult.status === "duplicate"
          ? "success"
          : "failed";
      item.sync_message = sanitizeSyncMessage(syncResult.message);
      await queuePut(item);
    }

    await refreshBootstrapFromServer();
    await refreshQueueState();
    showNotice(
      "同步完成：成功 " +
        result.success_count +
        " 条，失败 " +
        result.failed_count +
        " 条，重复 " +
        result.duplicate_count +
        " 条。",
      result.failed_count > 0 ? "warn" : "success"
    );
  }

  async function retryFailed() {
    const failedItems = state.queueItems.filter((item) => item.sync_status === "failed");
    if (!failedItems.length) {
      showNotice("当前没有失败记录。", "info");
      return;
    }

    for (const item of failedItems) {
      item.sync_status = "pending";
      item.sync_message = "已重新标记为待同步";
      await queuePut(item);
    }

    await refreshQueueState();
    showNotice("失败记录已重新标记为待同步。", "success");
  }

  async function clearSynced() {
    const syncedItems = state.queueItems.filter((item) => item.sync_status === "success");
    if (!syncedItems.length) {
      showNotice("当前没有已同步记录。", "info");
      return;
    }

    for (const item of syncedItems) {
      await queueDelete(item.op_id);
    }

    await refreshQueueState();
    showNotice("已同步记录已从本地队列清理。", "success");
  }

  function buildExportPayload(items) {
    return {
      version: 1,
      exported_at: new Date().toISOString(),
      source: "mice-manage-offline",
      operator: offlineOperatorData ? offlineOperatorData.name : operatorNameEl.value,
      items: items.map((item) => ({
        op_id: item.op_id,
        action_type: item.action_type,
        cage_code: item.cage_code,
        operator_name: item.operator_name,
        payload: item.payload,
        client_created_at: item.client_created_at || null,
      })),
    };
  }

  function downloadJsonFile(filename, content) {
    const blob = new Blob([JSON.stringify(content, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  async function exportPendingJson() {
    const exportableItems = state.queueItems.filter(
      (item) => item.sync_status === "pending" || item.sync_status === "failed"
    );
    if (!exportableItems.length) {
      showNotice("当前没有待导出记录。", "info");
      return;
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const payload = buildExportPayload(exportableItems);
    downloadJsonFile("mice-manage-sync-" + timestamp + ".json", payload);

    for (const item of exportableItems) {
      item.sync_status = "success";
      item.sync_message = "已导出 JSON，等待服务器导入";
      await queuePut(item);
    }

    await refreshQueueState();
    showNotice(
      "已导出 " + exportableItems.length + " 条记录，并标记为已导出。确认服务器导入成功后，再点击“清理已同步记录”。",
      "success"
    );
  }

  async function importBootstrapFromFile(file) {
    if (!file) {
      return;
    }

    let text = "";
    try {
      text = await file.text();
      const payload = JSON.parse(text);
      if (!payload || !Array.isArray(payload.cages) || !Array.isArray(payload.users)) {
        throw new Error("基础数据 JSON 格式不正确。");
      }
      state.serverBootstrap = payload;
      await saveBootstrap(payload);
      await refreshQueueState();
      showNotice("基础数据已导入本地缓存。", "success");
    } catch (error) {
      showNotice(error.message || "基础数据导入失败。", "error");
    }
  }

  function filteredOfflineCageChoices() {
    const roomFilter = offlineRoomFilterEl.value;
    const terms = splitSearchTerms(offlineCageSearchEl.value);
    return state.bootstrap.cages.filter((cage) => {
      if (roomFilter && cage.room !== roomFilter) {
        return false;
      }
      if (!terms.length) {
        return true;
      }
      const haystack = [
        cage.cage_code,
        cage.room,
        cage.rack,
        cage.owner,
        cage.strain,
        cage.status,
      ]
        .filter(Boolean)
        .map((value) => String(value).toLowerCase());
      return terms.every((term) =>
        haystack.some((value) => value.includes(term))
      );
    });
  }

  async function refreshOfflineCageSelect() {
    const choices = filteredOfflineCageChoices();
    const previousValue = cageCodeEl.value;
    setOptions(cageCodeEl, choices, (item) => ({
      value: item.cage_code,
      label:
        item.cage_code +
        " / " +
        (item.room || "未填写房间") +
        " / " +
        (item.owner || "未填写负责人"),
    }));
    if (previousValue && choices.some((item) => item.cage_code === previousValue)) {
      cageCodeEl.value = previousValue;
    }
    populateBirthRecordOptions();
    renderSelectedCage();
  }

  async function initializeBootstrapOptions() {
    const operatorOptions = offlineOperatorData
      ? state.bootstrap.users.filter((item) => item.name === offlineOperatorData.name)
      : state.bootstrap.users;
    setOptions(operatorNameEl, operatorOptions, (item) => ({
      value: item.name,
      label: item.name + " / " + item.role,
    }));
    if (offlineOperatorData) {
      operatorNameEl.value = offlineOperatorData.name;
      operatorNameEl.style.display = "none";
      if (operatorDisplayEl) {
        operatorDisplayEl.value = offlineOperatorData.name + " / " + offlineOperatorData.role;
      }
    }
    const roomNames = Array.from(
      new Set(state.bootstrap.cages.map((item) => item.room).filter(Boolean))
    ).sort((a, b) => String(a).localeCompare(String(b)));
    setOptions(
      offlineRoomFilterEl,
      roomNames,
      (item) => ({ value: item, label: item }),
      "全部房间"
    );
    await refreshOfflineCageSelect();
    setOptions(recordActionEl, state.bootstrap.action_options, (item) => ({
      value: item,
      label: item,
    }));
    setOptions(
      updateStatusEl,
      state.bootstrap.status_options,
      (item) => ({ value: item, label: item }),
      "未填写"
    );
    setOptions(
      createStatusEl,
      state.bootstrap.status_options,
      (item) => ({ value: item, label: item }),
      "未填写"
    );
    setOptions(
      createOwnerIdEl,
      state.bootstrap.users,
      (item) => ({ value: String(item.id), label: item.name + " / " + item.role }),
      "未填写"
    );
    syncFormVisibility();
  }

  function bindDraftPersistence() {
    [
      operatorNameEl,
      actionTypeEl,
      cageCodeEl,
      recordActionEl,
      recordPurposeEl,
      recordNoteEl,
      birthDateEl,
      birthCountEl,
      birthCodesEl,
      birthNoteEl,
      birthRecordIdEl,
      processingTextEl,
      updateMaleGenotypeEl,
      updateFemaleGenotypeEl,
      updateMaleCodeEl,
      updateFemaleCodeEl,
      updateSetupDateEl,
      updateRoomNameEl,
      updateRackNameEl,
      updateStatusEl,
      updateNoteEl,
      createCageCodeEl,
      createRoomNameEl,
      createRackNameEl,
      createOwnerIdEl,
      createMaleGenotypeEl,
      createFemaleGenotypeEl,
      createMaleCodeEl,
      createFemaleCodeEl,
      createSetupDateEl,
      createStatusEl,
      createNoteEl,
    ]
      .filter(Boolean)
      .forEach((element) => {
      const eventName = element.tagName === "SELECT" ? "change" : "input";
      element.addEventListener(eventName, saveDraft);
    });

    operatorNameEl.addEventListener("change", async () => {
      syncFormVisibility();
      await saveDraft();
    });

    actionTypeEl.addEventListener("change", async () => {
      syncFormVisibility();
      prefillUpdateFields();
      populateBirthRecordOptions();
      renderSelectedCage();
      await saveDraft();
    });

    cageCodeEl.addEventListener("change", async () => {
      prefillUpdateFields();
      populateBirthRecordOptions();
      renderSelectedCage();
      await saveDraft();
    });

    offlineRoomFilterEl.addEventListener("change", async () => {
      await refreshOfflineCageSelect();
      await saveDraft();
    });

    offlineCageSearchEl.addEventListener("input", async () => {
      await refreshOfflineCageSelect();
    });
  }

  async function init() {
    hideNotice();
    updateNetworkStatus();
    window.addEventListener("online", async () => {
      updateNetworkStatus();
      const serverAvailable = await detectServer();
      if (serverAvailable && state.queueItems.some((item) => item.sync_status === "pending")) {
        showNotice("网络已恢复，当前有待同步记录，可以点击同步。", "info");
      }
    });
    window.addEventListener("offline", updateNetworkStatus);

    await saveBootstrap(state.serverBootstrap);
    await initializeBootstrapOptions();
    await restoreDraft();
    prefillUpdateFields();
    populateBirthRecordOptions();
    renderSelectedCage();
    bindDraftPersistence();

    const cached = await loadCachedBootstrap();
    if (cached && cached.cached) {
      state.serverBootstrap = cached.cached;
    }
    await refreshQueueState();
    await detectServer();

    formEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      saveButtonEl.disabled = true;
      try {
        const item = buildQueueItem();
        await queuePut(item);
        await metaDelete(DRAFT_KEY);
        formEl.reset();
        birthCountEl.value = "0";
        await refreshQueueState();
        syncFormVisibility();
        prefillUpdateFields();
        populateBirthRecordOptions();
        showNotice("这条操作已经保存到本地待同步队列。", "success");
      } catch (error) {
        showNotice(error.message || "保存失败，请检查填写内容。", "error");
      } finally {
        saveButtonEl.disabled = false;
      }
    });

    syncButtonEl.addEventListener("click", async () => {
      syncButtonEl.disabled = true;
      try {
        await syncPending();
      } finally {
        syncButtonEl.disabled = false;
      }
    });

    exportJsonButtonEl.addEventListener("click", exportPendingJson);
    retryFailedButtonEl.addEventListener("click", retryFailed);
    clearSyncedButtonEl.addEventListener("click", clearSynced);
    clearDraftButtonEl.addEventListener("click", clearDraft);

    if (importBootstrapButtonEl && bootstrapFileInputEl) {
      importBootstrapButtonEl.addEventListener("click", () => {
        bootstrapFileInputEl.click();
      });
      bootstrapFileInputEl.addEventListener("change", async () => {
        const file = bootstrapFileInputEl.files && bootstrapFileInputEl.files[0];
        await importBootstrapFromFile(file);
        bootstrapFileInputEl.value = "";
      });
    }

    refreshButtonEl.addEventListener("click", async () => {
      refreshButtonEl.disabled = true;
      try {
        await refreshBootstrapFromServer();
        await refreshQueueState();
        showNotice("服务器基础数据已刷新并缓存到本地。", "success");
      } catch (error) {
        showNotice("刷新失败，请确认已经连接到服务器。", "error");
      } finally {
        refreshButtonEl.disabled = false;
      }
    });

    cageSearchEl.addEventListener("input", () => {
      state.searchKeyword = cageSearchEl.value;
      renderCages(cacheTimeEl.textContent.replace(/^缓存于 /, ""));
    });

    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        state.queueFilter = button.getAttribute("data-filter");
        document
          .querySelectorAll("[data-filter]")
          .forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        renderQueue();
      });
    });

    queueListEl.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const deleteButton = target.closest(".queue-delete-button");
      if (!deleteButton) {
        return;
      }
      const opId = deleteButton.getAttribute("data-op-id");
      if (!opId) {
        return;
      }
      if (!window.confirm("确认删除这条待同步记录吗？")) {
        return;
      }
      await deleteQueueItem(opId);
    });
  }

  init().catch((error) => {
    console.error(error);
    showNotice("离线页面初始化失败，请刷新后重试。", "error");
  });
})();
