const pageState = {
  currentBatchId: null
};

const $ = (selector) => document.querySelector(selector);

function setText(selector, text) {
  const node = $(selector);
  if (node) node.textContent = text;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function renderBatchPreview(batch) {
  const lines = [
    `批次：${batch.id} / ${batch.batch_no}`,
    `类型：${batch.file_type}`,
    `状态：${batch.status}`,
    `行数：${batch.total_rows}，成功：${batch.success_rows}，错误：${batch.error_rows}`,
    `字段映射：${JSON.stringify(batch.mapping_json || {}, null, 2)}`
  ];
  $("#batch-preview").textContent = lines.join("\n");
}

function renderBatches(batches) {
  $("#batch-table").innerHTML = batches.slice(0, 20).map((batch) => `
    <tr>
      <td>${batch.id}</td>
      <td>${batch.batch_no}</td>
      <td>${batch.file_type}</td>
      <td><span class="badge ${batch.status === "committed" ? "ok" : "warn"}">${batch.status}</span></td>
      <td>${batch.total_rows}</td>
      <td>${batch.success_rows}</td>
      <td>${batch.error_rows}</td>
    </tr>
  `).join("") || '<tr><td colspan="7" class="muted">暂无导入批次。</td></tr>';
}

async function loadBatches() {
  const batches = await requestJson("/api/v1/import/batches");
  renderBatches(batches);
}

async function uploadBatch() {
  const file = $("#import-file").files[0];
  if (!file) throw new Error("请选择文件");
  const formData = new FormData();
  formData.append("file_type", $("#import-file-type").value);
  formData.append("data_date", $("#import-data-date").value || new Date().toISOString().slice(0, 10));
  formData.append("file", file);
  const batch = await requestJson("/api/v1/import/upload", {
    method: "POST",
    body: formData
  });
  pageState.currentBatchId = batch.id;
  $("#validate-button").disabled = false;
  $("#commit-button").disabled = true;
  setText("#import-state", `已上传批次 ${batch.id}`);
  renderBatchPreview(batch);
  await loadBatches();
}

async function validateBatch() {
  if (!pageState.currentBatchId) return;
  const batch = await requestJson(`/api/v1/import/batches/${pageState.currentBatchId}/validate`, { method: "POST" });
  $("#commit-button").disabled = batch.error_rows > 0;
  setText("#import-state", batch.error_rows > 0 ? `校验有 ${batch.error_rows} 个错误` : "校验通过");
  renderBatchPreview(batch);
  await loadBatches();
}

async function commitBatch() {
  if (!pageState.currentBatchId) return;
  const batch = await requestJson(`/api/v1/import/batches/${pageState.currentBatchId}/commit`, { method: "POST" });
  $("#commit-button").disabled = true;
  setText("#import-state", `提交结果：${batch.status}`);
  renderBatchPreview(batch);
  await loadBatches();
}

function bind(selector, event, handler) {
  const node = $(selector);
  if (!node) return;
  node.addEventListener(event, async () => {
    try {
      node.disabled = true;
      await handler();
    } catch (error) {
      setText("#import-state", error.message || "操作失败");
    } finally {
      if (selector === "#upload-button" || selector === "#reload-batches-button") {
        node.disabled = false;
      }
      if (selector === "#validate-button") {
        node.disabled = !pageState.currentBatchId;
      }
    }
  });
}

$("#import-data-date").value = new Date().toISOString().slice(0, 10);
bind("#upload-button", "click", uploadBatch);
bind("#validate-button", "click", validateBatch);
bind("#commit-button", "click", commitBatch);
bind("#reload-batches-button", "click", loadBatches);
