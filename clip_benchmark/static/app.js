const elements = {
  form: document.querySelector("#searchForm"),
  query: document.querySelector("#queryInput"),
  searchButton: document.querySelector("#searchButton"),
  quantization: document.querySelector("#quantizationSelect"),
  reloadButton: document.querySelector("#reloadButton"),
  stateBadge: document.querySelector("#stateBadge"),
  modelSummary: document.querySelector("#modelSummary"),
  gpuName: document.querySelector("#gpuName"),
  deviceMemory: document.querySelector("#deviceMemory"),
  processMemory: document.querySelector("#processMemory"),
  imageCount: document.querySelector("#imageCount"),
  loadTime: document.querySelector("#loadTime"),
  indexTime: document.querySelector("#indexTime"),
  resultMeta: document.querySelector("#resultMeta"),
  queryTiming: document.querySelector("#queryTiming"),
  emptyState: document.querySelector("#emptyState"),
  resultsGrid: document.querySelector("#resultsGrid"),
  toast: document.querySelector("#toast"),
};

let currentState = "not_loaded";
let toastTimer;

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "--";
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatMs(value) {
  return Number.isFinite(value) ? `${value.toFixed(0)} ms` : "--";
}

function notify(message, isError = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast show${isError ? " error" : ""}`;
  toastTimer = setTimeout(() => { elements.toast.className = "toast"; }, 3200);
}

function setBusy(busy) {
  elements.searchButton.disabled = busy || currentState !== "ready";
  elements.reloadButton.disabled = busy || ["loading_model", "indexing_images"].includes(currentState);
}

function renderStatus(status) {
  currentState = status.state;
  const stateLabels = {
    ready: "就绪",
    loading_model: "加载模型",
    indexing_images: "构建索引",
    error: "错误",
    not_loaded: "未加载",
  };
  elements.stateBadge.textContent = stateLabels[status.state] || status.state;
  elements.stateBadge.className = `state-badge ${status.state === "ready" ? "ready" : status.state === "error" ? "error" : "busy"}`;
  elements.modelSummary.textContent = `${status.quantization?.toUpperCase() || "--"} · ${status.embedding_dimension} 维 · ${status.image_count} 张图片`;
  if (status.quantization) elements.quantization.value = status.quantization;

  const gpu = status.gpu || {};
  elements.gpuName.textContent = gpu.device_name || "--";
  elements.deviceMemory.textContent = gpu.device_total_bytes
    ? `${formatBytes(gpu.device_used_bytes)} / ${formatBytes(gpu.device_total_bytes)}`
    : "--";
  elements.processMemory.textContent = gpu.process_allocated_bytes
    ? `${formatBytes(gpu.process_allocated_bytes)}（保留 ${formatBytes(gpu.process_reserved_bytes)}）`
    : "--";
  elements.imageCount.textContent = `${status.image_count || 0} · ${status.embedding_dimension || 512} 维`;
  elements.loadTime.textContent = formatMs(status.model_load_ms);
  elements.indexTime.textContent = formatMs(status.index_build_ms);
  setBusy(false);
  if (status.error) notify(status.error, true);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

async function refreshStatus() {
  try {
    renderStatus(await fetchJson("/api/status"));
  } catch (error) {
    currentState = "error";
    elements.stateBadge.textContent = "断开";
    elements.stateBadge.className = "state-badge error";
    setBusy(true);
  }
}

function renderResults(payload) {
  elements.resultsGrid.replaceChildren();
  elements.emptyState.hidden = payload.results.length > 0;
  elements.resultMeta.textContent = `“${payload.query}” · ${payload.returned}/${payload.total_candidates} · CLIP 余弦相似度 · 无阈值过滤`;
  elements.queryTiming.textContent = `文本编码 ${payload.timings_ms.text_embedding.toFixed(2)} ms · 排序 ${payload.timings_ms.ranking.toFixed(2)} ms · 总计 ${payload.timings_ms.total.toFixed(2)} ms`;

  payload.results.forEach((result) => {
    const card = document.createElement("article");
    card.className = "result-card";
    const imageWrap = document.createElement("div");
    imageWrap.className = "image-wrap";
    const image = document.createElement("img");
    image.src = result.image_url;
    image.alt = result.filename;
    image.loading = "lazy";
    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = `#${result.rank}`;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = `相似度 ${result.similarity.toFixed(4)}`;
    score.title = "CLIP 余弦相似度，不是概率置信度";
    imageWrap.append(image, rank, score);

    const body = document.createElement("div");
    body.className = "result-body";
    const filename = document.createElement("div");
    filename.className = "filename";
    filename.textContent = result.filename;
    const path = document.createElement("div");
    path.className = "path";
    path.textContent = result.relative_path;
    body.append(filename, path);
    card.append(imageWrap, body);
    elements.resultsGrid.append(card);
  });
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (currentState !== "ready") return;
  setBusy(true);
  elements.searchButton.textContent = "检索中";
  try {
    const payload = await fetchJson("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: elements.query.value }),
    });
    renderResults(payload);
  } catch (error) {
    notify(error.message, true);
  } finally {
    elements.searchButton.textContent = "检索 Top 20";
    setBusy(false);
  }
});

elements.reloadButton.addEventListener("click", async () => {
  const quantization = elements.quantization.value;
  setBusy(true);
  elements.resultsGrid.replaceChildren();
  elements.emptyState.hidden = false;
  elements.emptyState.textContent = "模型重载并重建索引中";
  try {
    await fetchJson("/api/model/reload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantization }),
    });
    currentState = "loading_model";
    notify(`已开始切换到 ${quantization.toUpperCase()}`);
  } catch (error) {
    notify(error.message, true);
  }
});

refreshStatus();
setInterval(refreshStatus, 1000);
